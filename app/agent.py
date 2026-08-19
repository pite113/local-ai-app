"""Agent 引擎：ReAct 循环 —— 模型自主决策调用工具，串行执行直至完成任务。

- 模型每轮返回"要调用哪个工具+参数"，系统执行并把结果喂回去，直到模型给出最终答复。
- 敏感工具（花钱/破坏性）执行前暂停，等待用户确认。
- 每步计入运行监控（token/成本/调用内容）。
"""
import json
import threading
import time
import uuid

from .config import Settings
from .llm import BaseLLM
from .logger import LogStore

MAX_ITERATIONS = 15          # 单任务最大步数
PENDING_TIMEOUT = 600        # 待确认任务 10 分钟超时

SYSTEM_PROMPT = (
    "你是一个部署在本地、能自主调用工具完成任务的 AI 助手。"
    "可用的工具：\n"
    "- kb_search(query): 在知识库中检索资料（query 为自然语言问题）\n"
    "- kb_list(): 列出知识库中已有的文档\n"
    "- text_batch(items, mode, language, instruction): 批量处理文本。"
    "mode 可选 translate(翻译)/rewrite(改写优化)/generate(要点生成文案)；"
    "items 为字符串数组，每项一条；language 为翻译目标语言；instruction 为附加要求\n"
    "- image_generate(prompts, size): 批量生成图片。prompts 为提示词数组；"
    "size 可选 512x512 或 1024x1024\n\n"
    "执行要求：\n"
    "1. 用中文回复。任务复杂时，先简短说明执行计划。\n"
    "2. 【重要】当任务需要实际操作（检索资料、处理文本、生成图片）时，"
    "必须调用对应工具完成，禁止只用文字假装完成。例如用户要图片就调 image_generate。\n"
    "3. 合理选择工具、给出正确参数；工具结果不足时再查，不要编造工具结果。\n"
    "4. 每步工具执行结果会以[工具结果]形式返回给你。\n"
    "5. 全部步骤完成后，用中文汇总：做了什么、结果如何、注意事项（如图片文件位置）。"
)

CHAT_SYSTEM = (
    "你是一个部署在本地、能自主调用工具的 AI 助手。可用工具：\n"
    "- kb_search(query): 在本地知识库检索资料\n"
    "- kb_list(): 列出知识库文档\n"
    "- text_batch(items, mode, language, instruction): 批量处理文本"
    "（mode: translate翻译/rewrite改写/generate生成文案；items 为文本数组）\n"
    "- image_generate(prompts, size): 生成图片（prompts 为提示词数组，size 可选 512x512/1024x1024）\n\n"
    "要求：\n"
    "1. 用户要求生成图片、处理文本、查询资料时，必须调用对应工具完成，禁止假装完成。\n"
    "2. 用中文回复；工具执行后，先告知结果再补充说明。\n"
    "3. 图片生成后，直接告诉用户图片已生成。"
)


class Agent:
    def __init__(self, settings: Settings, llm: BaseLLM, logs: LogStore, kb):
        self.s = settings
        self.llm = llm
        self.logs = logs
        self.kb = kb
        self._lock = threading.Lock()
        self._seq = 0
        self.runs = {}

        # 工具注册表：name / description / parameters(JSON Schema) / handler / sensitive
        self.tools = [
            {
                "name": "kb_search",
                "description": "在本地知识库中检索与问题相关的资料",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "检索问题"}},
                    "required": ["query"],
                },
                "handler": lambda a: self._kb_search(a.get("query", "")),
                "sensitive": False,
            },
            {
                "name": "kb_list",
                "description": "列出知识库中已有的文档名称",
                "parameters": {"type": "object", "properties": {}},
                "handler": lambda a: self._kb_list(),
                "sensitive": False,
            },
            {
                "name": "text_batch",
                "description": "批量处理文本：翻译 / 改写优化 / 由要点生成文案",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}, "description": "待处理文本列表"},
                        "mode": {"type": "string", "enum": ["translate", "rewrite", "generate"], "description": "处理方式"},
                        "language": {"type": "string", "description": "翻译目标语言（mode=translate 时用）"},
                        "instruction": {"type": "string", "description": "附加要求，如：电商标题、口语化"},
                    },
                    "required": ["items", "mode"],
                },
                "handler": lambda a: self._text_batch(a),
                "sensitive": False,
            },
            {
                "name": "image_generate",
                "description": "批量生成商品图/海报（调用生图 API，会产生费用）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompts": {"type": "array", "items": {"type": "string"}, "description": "图片提示词列表"},
                        "size": {"type": "string", "enum": ["512x512", "1024x1024"]},
                    },
                    "required": ["prompts"],
                },
                "handler": lambda a: self._image_generate(a),
                "sensitive": True,
                "reason": "生成图片会调用生图 API 并产生费用（约 ¥0.3~0.5/张），是否允许？",
            },
        ]

    # ---------- 对外接口 ----------
    def start(self, task: str):
        """开始一个任务。返回 {status: running|done|need_confirm, ...}"""
        if not (task or "").strip():
            return {"error": "任务不能为空"}
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._seq += 1
        state = {
            "run_id": run_id,
            "messages": [{"role": "user", "content": task.strip()}],
            "steps": [],
            "iteration": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost": 0.0,
            "status": "running",
            "created": time.time(),
        }
        with self._lock:
            self.runs[run_id] = state
        self._prune()
        self.logs.add(type="agent_run", message=task[:60], run_id=run_id, level="info")
        return self._step(run_id)

    def confirm(self, run_id: str, approve: bool):
        """用户对敏感操作给出允许/拒绝后继续。"""
        state = self.runs.get(run_id)
        if not state:
            return {"error": "任务不存在或已过期"}
        if state["status"] != "await_confirm":
            return {"error": "当前任务不需要确认"}
        if time.time() - state.get("created", 0) > PENDING_TIMEOUT:
            state["status"] = "done"
            return {"error": "确认超时（10分钟），任务已终止，请重新发起"}
        pending = state.pop("pending", None)
        if pending is None:
            state["status"] = "done"
            return {"error": "确认信息丢失，任务已终止"}
        if approve:
            try:
                result = self._execute_tool(pending["name"], pending["args"])
                summary = self._summarize_result(pending["name"], result)
            except Exception as e:
                result = {"error": str(e)}
                summary = f"执行失败: {e}"
        else:
            result = {"result": "用户拒绝执行该操作"}
            summary = "用户拒绝执行"
        state["messages"].append({
            "role": "tool",
            "tool_call_id": pending.get("call_id", ""),
            "name": pending["name"],
            "content": json.dumps(result, ensure_ascii=False)[:2000],
        })
        state["steps"].append({
            "tool": pending["name"],
            "approved": approve,
            "summary": summary,
            "time": time.strftime("%H:%M:%S"),
        })
        if state.get("tool_queue"):
            return self._process_queue(run_id)
        return self._step(run_id)

    def cancel(self, run_id: str):
        with self._lock:
            self.runs.pop(run_id, None)
        return {"ok": True}

    # ---------- 对话模式（聊天即任务入口，自动执行工具，图片返回上下文） ----------
    def chat_run(self, history: list):
        """history: [{"role": user|assistant, "content": str}]。自动执行工具（不暂停确认）。
        返回 {answer, images, steps, usage}。"""
        messages = [
            {"role": m["role"], "content": str(m.get("content", ""))[:2000]}
            for m in history[-10:] if m.get("role") in ("user", "assistant")
        ]
        steps = []
        images = []
        t_in = t_out = 0
        limit = self.s.agent_max_iterations or MAX_ITERATIONS
        for _ in range(limit):
            try:
                content, tool_calls, ti, to = self.llm.chat_with_tools(
                    messages, self._tool_specs(), system=CHAT_SYSTEM
                )
            except Exception as e:
                self.logs.add(type="chat_request", level="error", error=str(e)[:300])
                return {"answer": f"[工具调用失败] {e}", "images": images, "steps": steps,
                        "usage": {"tokens_in": t_in, "tokens_out": t_out}}
            t_in += ti
            t_out += to
            if not tool_calls:
                self.logs.add(type="chat_request", message=history[-1].get("content", "")[:60],
                              tokens_in=t_in, tokens_out=t_out,
                              cost=round(t_in / 1e6 * self.s.price_in + t_out / 1e6 * self.s.price_out, 6),
                              level="info")
                return {"answer": content, "images": images, "steps": steps,
                        "usage": {"tokens_in": t_in, "tokens_out": t_out}}
            # 规范化 call_id，assistant 消息与回传一致
            norm = [
                {"id": tc["id"] or f"call_{i}", "name": tc["name"], "arguments": tc["arguments"]}
                for i, tc in enumerate(tool_calls)
            ]
            messages.append({
                "role": "assistant", "content": content,
                "tool_calls": [
                    {"id": n["id"], "type": "function",
                     "function": {"name": n["name"], "arguments": n["arguments"]}}
                    for n in norm
                ],
            })
            for nc in norm:
                tool = self._find_tool(nc["name"])
                try:
                    args = json.loads(nc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if tool is None:
                    result = {"error": f"未知工具 {nc['name']}"}
                else:
                    try:
                        result = self._execute_tool(tool["name"], args)
                    except Exception as e:
                        result = {"error": str(e)}
                messages.append({
                    "role": "tool", "tool_call_id": nc["id"], "name": nc["name"],
                    "content": json.dumps(result, ensure_ascii=False)[:2000],
                })
                steps.append({"tool": nc["name"], "summary": self._summarize_result(nc["name"], result)})
                if nc["name"] == "image_generate" and isinstance(result, list):
                    images.extend(img["url"] for img in result if img.get("url"))
        return {"answer": "已达步数上限，请把请求拆小后重试", "images": images, "steps": steps,
                "usage": {"tokens_in": t_in, "tokens_out": t_out}}

    # ---------- 循环 ----------
    def _step(self, run_id: str):
        state = self.runs.get(run_id)
        if not state:
            return {"error": "任务不存在或已过期"}
        if state["iteration"] >= (self.s.agent_max_iterations or MAX_ITERATIONS):
            return self._finish(state, "已达执行步数上限，请把任务拆小后重试")

        state["iteration"] += 1
        try:
            content, tool_calls, ti, to = self.llm.chat_with_tools(
                state["messages"], self._tool_specs(), system=SYSTEM_PROMPT
            )
        except Exception as e:
            self.logs.add(type="agent_step", run_id=run_id, level="error", error=str(e)[:300])
            return self._finish(state, f"模型调用失败: {e}")

        state["tokens_in"] += ti
        state["tokens_out"] += to
        state["cost"] += ti / 1e6 * self.s.price_in + to / 1e6 * self.s.price_out

        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            # 统一规范化 call_id：assistant 消息、执行队列、tool 回传三处用同一 ID
            norm_calls = [
                {
                    "id": tc["id"] or f"call_{i}",
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                }
                for i, tc in enumerate(tool_calls)
            ]
            assistant_msg["tool_calls"] = [
                {
                    "id": nc["id"],
                    "type": "function",
                    "function": {"name": nc["name"], "arguments": nc["arguments"]},
                }
                for nc in norm_calls
            ]
        state["messages"].append(assistant_msg)

        if not tool_calls:
            return self._finish(state, content)

        # 逐个执行全部工具调用，每个都回传对应 call_id 的结果
        state["tool_queue"] = [dict(nc) for nc in norm_calls]
        return self._process_queue(run_id)

    def _process_queue(self, run_id: str):
        """按顺序执行工具调用队列；敏感操作暂停等待确认。"""
        state = self.runs.get(run_id)
        if not state:
            return {"error": "任务不存在或已过期"}
        while state.get("tool_queue"):
            tc = state["tool_queue"].pop(0)
            call_id = tc["id"] or "call_x"
            tool = self._find_tool(tc["name"])
            if tool is None:
                state["messages"].append({
                    "role": "tool", "tool_call_id": call_id, "name": tc["name"],
                    "content": json.dumps({"error": f"未知工具 {tc['name']}"}),
                })
                continue
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if tool.get("sensitive"):
                state["status"] = "await_confirm"
                state["pending"] = {
                    "call_id": call_id,
                    "name": tool["name"],
                    "args": args,
                }
                self.logs.add(type="agent_step", run_id=run_id, message=f"待确认: {tool['name']}", level="warn")
                return {
                    "status": "need_confirm",
                    "run_id": run_id,
                    "tool": tool["name"],
                    "args": args,
                    "reason": tool.get("reason", "该操作需要确认"),
                }
            try:
                result = self._execute_tool(tool["name"], args)
                summary = self._summarize_result(tool["name"], result)
            except Exception as e:
                result = {"error": str(e)}
                summary = f"执行失败: {e}"
            state["messages"].append({
                "role": "tool", "tool_call_id": call_id, "name": tool["name"],
                "content": json.dumps(result, ensure_ascii=False)[:2000],
            })
            state["steps"].append({
                "tool": tool["name"], "approved": True,
                "summary": summary, "time": time.strftime("%H:%M:%S"),
            })
        return self._step(run_id)

    def _finish(self, state, summary: str):
        state["status"] = "done"
        self.logs.add(type="agent_run", run_id=state["run_id"], message="任务完成",
                      level="info", cost=round(state["cost"], 6),
                      tokens_in=state["tokens_in"], tokens_out=state["tokens_out"])
        return {
            "status": "done",
            "summary": summary,
            "steps": state["steps"],
            "usage": {
                "tokens_in": state["tokens_in"],
                "tokens_out": state["tokens_out"],
                "cost": round(state["cost"], 6),
            },
        }

    # ---------- 工具执行 ----------
    def _find_tool(self, name):
        return next((t for t in self.tools if t["name"] == name), None)

    def _tool_specs(self):
        return [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["parameters"],
            }}
            for t in self.tools
        ]

    def _execute_tool(self, name, args):
        tool = self._find_tool(name)
        if not tool:
            raise ValueError(f"未知工具 {name}")
        self.logs.add(type="agent_step", message=f"调用工具: {name}", args=str(args)[:200], level="info")
        return tool["handler"](args)

    def _summarize_result(self, tool_name, result):
        """把工具结果压成一行摘要（给界面展示）。"""
        try:
            if tool_name == "kb_search":
                hits = result.get("hits", [])
                return f"检索到 {len(hits)} 条相关资料"
            if tool_name == "kb_list":
                docs = result.get("documents", [])
                return f"知识库共 {len(docs)} 篇文档: " + "、".join(d["name"] for d in docs[:5])
            if tool_name == "text_batch":
                return f"已处理 {len(result)} 条文本"
            if tool_name == "image_generate":
                return f"已生成 {len(result)} 张图片（保存在本地 data/output）"
        except Exception:
            pass
        return str(result)[:120]

    def _kb_search(self, query):
        ret = self.kb.retrieve(query, self.s.top_k)
        return {"hits": [
            {"doc": h["doc"], "heading": h.get("heading", ""), "score": h["score"], "text": h["text"][:500]}
            for h in ret["hits"]
        ]}

    def _kb_list(self):
        return {"documents": self.kb.list()}

    def _text_batch(self, args):
        return tools.batch_text(
            args.get("items", []),
            args.get("mode", "rewrite"),
            args.get("language", "英文"),
            args.get("instruction", ""),
            self.llm, self.logs, self.s, concurrency=self.s.tool_concurrency,
        )

    def _image_generate(self, args):
        return tools.batch_images(
            args.get("prompts", []), args.get("size", "512x512"), self.s, self.logs
        )

    # ---------- 清理 ----------
    def _prune(self):
        now = time.time()
        with self._lock:
            for rid in list(self.runs.keys()):
                st = self.runs[rid]
                if st["status"] == "await_confirm" and now - st["created"] > PENDING_TIMEOUT:
                    self.runs.pop(rid, None)
                elif st["status"] == "done":
                    self.runs.pop(rid, None)


# 延迟导入避免循环依赖
from . import tools  # noqa: E402
