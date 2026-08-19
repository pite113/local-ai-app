"""编排器（多 Agent 分工流水线）。

输入：任务描述 + 表格文件 → 编排器 LLM 解析成"作业单" → 文案/生图/表格 worker
并行执行（确定性批量，无 ReAct 冗余）→ 合并装配出交付物（成品表格 + 图片）。

设计要点：
- 编排只调用 1 次 LLM（结构化作业单），之后全部是确定性批量执行。
- 生图是敏感操作：run 需 approve_images=True 才执行。
- 每一步的成本/调用照常进入运行监控。
"""
import csv as _csv
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import tools
from .config import Settings
from .llm import BaseLLM
from .logger import LogStore

PLAN_TTL = 600  # 作业单 10 分钟过期

PLAN_SYSTEM = (
    "你是批量生产任务的编排器。用户会给你一个任务描述和表格的列名。"
    "请把任务解析成结构化作业单（只调用 submit_work_order 工具提交，不要多余解释）：\n"
    "- text_columns: 需要批量处理的文本列。每项含 column(列名)、mode(translate翻译/rewrite改写/generate生成文案)、"
    "language(翻译目标语言，可选)、instruction(附加要求，可选)。\n"
    "- images: 是否需要逐行生成图片。prompt_template 用 {列名} 占位引用该行表格内容，"
    "例如 '商品图：{商品名称}，白底'；size 选 512x512 或 1024x1024。\n"
    "如果任务不明确，做合理推断；只处理用户明确要求的列，不要多余加工。"
)


class Orchestrator:
    def __init__(self, settings: Settings, llm: BaseLLM, logs: LogStore):
        self.s = settings
        self.llm = llm
        self.logs = logs
        self._lock = threading.Lock()
        self._seq = 0
        self.plans = {}  # plan_id -> {filename, raw_path, order, created}

    def _work_order_spec(self):
        return {
            "type": "function",
            "function": {
                "name": "submit_work_order",
                "description": "提交批量生产任务的作业单",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text_columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "mode": {"type": "string", "enum": ["translate", "rewrite", "generate"]},
                                    "language": {"type": "string"},
                                    "instruction": {"type": "string"},
                                },
                                "required": ["column", "mode"],
                            },
                        },
                        "images": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "prompt_template": {"type": "string"},
                                "size": {"type": "string", "enum": ["512x512", "1024x1024"]},
                            },
                        },
                    },
                    "required": ["text_columns"],
                },
            },
        }

    def plan(self, task: str, filename: str, raw_path: str, columns):
        """编排器解析任务 → 作业单。返回 (plan_id, order)。"""
        user = f"任务：{task}\n表格文件：{filename}\n表格列名：{'、'.join(columns)}"
        messages = [{"role": "user", "content": user}]
        _, tool_calls, _, _ = self.llm.chat_with_tools(
            messages, [self._work_order_spec()], system=PLAN_SYSTEM
        )
        if not tool_calls:
            raise ValueError("编排器未能生成作业单，请换个说法描述任务")
        order = json.loads(tool_calls[0]["arguments"] or "{}")
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        self._seq += 1
        with self._lock:
            self.plans[plan_id] = {
                "filename": filename,
                "raw_path": raw_path,
                "order": order,
                "created": time.time(),
            }
        self._prune()
        return plan_id, order

    def _prune(self):
        now = time.time()
        with self._lock:
            for pid in list(self.plans.keys()):
                if now - self.plans[pid]["created"] > PLAN_TTL:
                    self.plans.pop(pid, None)

    def run(self, plan_id: str, approve_images: bool):
        """执行作业单：文案/生图/表格 worker 并行，装配交付。作业单一次性消费，防重复执行。"""
        with self._lock:
            plan = self.plans.pop(plan_id, None)  # 原子取出并消费
        if plan is None:
            raise ValueError("作业单不存在、已过期或已执行（请重新生成）")
        if time.time() - plan["created"] > PLAN_TTL:
            raise ValueError("作业单已过期（10分钟），请重新生成")
        order = plan["order"]
        with open(plan["raw_path"], "rb") as f:
            raw = f.read()
        rows = tools._parse_table(plan["filename"], raw)
        if not rows:
            raise ValueError("表格为空")
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        data_rows = rows[1:]

        text_cols = [
            tc for tc in order.get("text_columns", [])
            if tc.get("column") in header
        ]
        images = order.get("images") or {}
        img_enabled = bool(images.get("enabled")) and approve_images

        # ---- worker 1: 文案（逐列并发批量处理） ----
        def do_text():
            out = []
            for tc in text_cols:
                col = tc["column"]
                ci = header.index(col)
                items = [
                    str(r[ci]).strip() if ci < len(r) and r[ci] is not None else ""
                    for r in data_rows
                ]
                res = tools.batch_text(
                    items, tc.get("mode", "rewrite"), tc.get("language", "英文"),
                    tc.get("instruction", ""), self.llm, self.logs, self.s,
                    concurrency=self.s.tool_concurrency,
                )
                out.append((col, res))
            return out

        # ---- worker 2: 生图（逐行按模板生成，敏感需确认） ----
        def do_images():
            if not img_enabled:
                return []
            template = images.get("prompt_template") or f"{{{header[0]}}}"
            prompts = []
            for row in data_rows:
                p = template
                for col in header:
                    tag = "{" + col + "}"
                    if tag in p:
                        ci = header.index(col)
                        val = str(row[ci]) if ci < len(row) and row[ci] is not None else ""
                        p = p.replace(tag, val)
                prompts.append(p)
            return tools.batch_images(prompts, images.get("size", "512x512"), self.s, self.logs)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_text = ex.submit(do_text)
            f_img = ex.submit(do_images)
            text_results = f_text.result()
            img_results = f_img.result()

        # ---- worker 3: 表格装配 ----
        new_header = header + [f"处理结果_{c}" for c, _ in text_results]
        if img_enabled:
            new_header.append("图片")
        out_rows = [new_header]
        col_map = {col: res for col, res in text_results}
        for i, row in enumerate(data_rows):
            new_row = list(row)
            for col, res in col_map.items():
                new_row.append(res[i] if i < len(res) else "")
            if img_enabled:
                img = img_results[i] if i < len(img_results) else {}
                if img.get("url"):
                    new_row.append(img["url"])
                elif img.get("error"):
                    new_row.append("失败:" + str(img["error"])[:40])
                else:
                    new_row.append("")
            out_rows.append(new_row)

        out_name = f"orchestrated_{uuid.uuid4().hex}{os.path.splitext(plan['filename'])[1]}"
        out_path = os.path.join(self.s.data_dir, "output", out_name)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if plan["filename"].lower().endswith(".csv"):
            with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
                _csv.writer(f).writerows(out_rows)
        else:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            for r in out_rows:
                ws.append(r)
            wb.save(out_path)

        self.logs.add(
            type="orchestrator", message=plan["filename"],
            columns=",".join(c for c, _ in text_results),
            images=len(img_results) if img_enabled else 0,
            rows=len(out_rows) - 1, level="info",
        )
        return {
            "download": "/api/tools/download/" + os.path.basename(out_path),
            "rows": len(out_rows) - 1,
            "text_columns": [c for c, _ in text_results],
            "images": img_results,
            "preview": out_rows[:4],
        }
