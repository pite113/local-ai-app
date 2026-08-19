"""知识库：句子级切片 + 向量索引 + 语义/词法检索（带阈值与去重）。

- 切片：按句末标点切分，绝不从句子中间切断；记录章节标题；块长设下限。
- 检索：使用 Embedding 向量（语义）或词法向量（回退），带相似度阈值过滤低分噪声。
- 去重：召回后剔除内容重叠过高的块，避免重复上下文喂给模型浪费 token。
"""
import datetime
import hashlib
import json
import os
import re
import threading

from .embeddings import BaseEmbedder
from .textutil import containment, cosine, tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def _to_jsonable(e):
    """向量统一转成可 JSON 序列化的纯 Python 类型。"""
    if isinstance(e, list):
        return [float(x) for x in e]
    return e


def split_sentences(text: str):
    """按句末标点/换行切成句子（保留标点）。"""
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]


def _is_heading(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return True
    # 表格数据行（含 | 或 , 或 Tab 分隔）不算标题，避免表头/行被误判
    if "|" in s or "," in s or "\t" in s:
        return False
    # 短行且不以句末标点结尾，视为小标题
    return len(s) <= 30 and not re.search(r"[。！？!?；;]$", s)


def chunk_text(text: str, size: int = 400, min_size: int = 80):
    """句子级切片：返回 [(章节标题, 块文本), ...]。"""
    # 1) 按行组织成 (heading, sentences) 段落
    paragraphs = []
    heading = ""
    buf = []
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            if buf:
                paragraphs.append((heading, buf))
                buf = []
            continue
        if _is_heading(s):
            if buf:
                paragraphs.append((heading, buf))
                buf = []
            heading = s.lstrip("#").strip()
        else:
            buf.extend(split_sentences(s))
    if buf:
        paragraphs.append((heading, buf))

    # 2) 句子里累计成块，尽量接近 size 且不小于 min_size
    chunks = []
    for h, sents in paragraphs:
        cur, cur_len = [], 0
        for sent in sents:
            if cur and cur_len + len(sent) > size:
                if cur_len >= min_size:
                    chunks.append((h, "".join(cur)))
                    cur, cur_len = [], 0
                else:
                    # 当前块太小：把这句话并入，允许轻微超长
                    cur.append(sent)
                    cur_len += len(sent)
                    continue
            cur.append(sent)
            cur_len += len(sent)
        if cur:
            chunks.append((h, "".join(cur)))
    return [c for c in chunks if c[1].strip()]


class Index:
    """文档索引：持久化到 JSON 文件。"""

    FORMAT = 2

    def __init__(
        self,
        path: str,
        embedder: BaseEmbedder,
        threshold: float = 0.30,
        lexical_threshold: float = 0.05,
        dedup_threshold: float = 0.60,
    ):
        self.path = path
        self.embedder = embedder
        self.threshold = threshold          # 语义向量相似度下限
        self.lexical_threshold = lexical_threshold  # 词法相似度下限
        self.dedup_threshold = dedup_threshold      # 内容重叠去重阈值
        self._lock = threading.Lock()               # 文档增删/重建/保存互斥
        self.docs = []
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        self.docs = []
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                self.docs = data.get("docs", data) if isinstance(data, dict) else data
                self._migrate()
            except Exception:
                self.docs = []
        self._ensure_embeddings()  # 旧数据自动补向量

    def _migrate(self):
        """旧格式 chunks 为纯字符串 -> 升级为 {text, heading}。"""
        for d in self.docs:
            if d.get("chunks") and isinstance(d["chunks"][0], str):
                d["chunks"] = [{"text": c, "heading": ""} for c in d["chunks"]]

    def _ensure_embeddings(self):
        """确保所有块都有当前嵌入器格式的向量；缺失或格式不符则全量重算。"""
        expected = dict if self.embedder.name == "lexical" else list
        need = False
        for d in self.docs:
            for c in d["chunks"]:
                e = c.get("emb")
                if e is None or not isinstance(e, expected):
                    need = True
                    break
            if need:
                break
        if need:
            all_chunks = [(d, c) for d in self.docs for c in d["chunks"]]
            texts = [c["text"] for _, c in all_chunks]
            try:
                embs = self.embedder.embed(texts)
                for (_, c), e in zip(all_chunks, embs):
                    c["emb"] = _to_jsonable(e)
                self._save()
            except Exception:
                pass  # 向量失败则保留现状，检索时按词法处理

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.docs, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---------- 文档管理 ----------
    def add_document(self, name: str, source: str, text: str, chunk_size: int, min_size: int):
        pairs = chunk_text(text, chunk_size, min_size)
        chunks = [{"text": t, "heading": h} for h, t in pairs]
        try:
            embs = self.embedder.embed([c["text"] for c in chunks])
            for c, e in zip(chunks, embs):
                c["emb"] = _to_jsonable(e)
        except Exception:
            pass  # 向量失败：块无 emb，检索时按词法处理
        doc = {
            "id": hashlib.md5((name + str(datetime.datetime.now())).encode()).hexdigest()[:12],
            "name": name,
            "source": source,
            "text": text,          # 保留原文，重新切片时无需重读原件（兼容 docx/pdf/xlsx）
            "chunks": chunks,
            "added": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "format": self.FORMAT,
        }
        with self._lock:
            self.docs.append(doc)
            self._save()
        return doc

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            before = len(self.docs)
            self.docs = [d for d in self.docs if d["id"] != doc_id]
            if len(self.docs) != before:
                self._save()
                return True
        return False

    def list(self):
        return [
            {"id": d["id"], "name": d["name"], "chunks": len(d["chunks"]), "added": d["added"]}
            for d in self.docs
        ]

    def reindex(self, chunk_size: int, min_size: int) -> int:
        """按当前切片参数重新切片全部文档（优先用 doc 内保存的原文）。"""
        done = 0
        for d in self.docs:
            text = d.get("text")
            if not text:
                src = d.get("source")
                if not src or not os.path.exists(src):
                    continue
                try:
                    with open(src, encoding="utf-8") as f:
                        text = f.read()
                except Exception:
                    continue
            text = text.lstrip("\ufeff")
            pairs = chunk_text(text, chunk_size, min_size)
            chunks = [{"text": t, "heading": h} for h, t in pairs]
            try:
                embs = self.embedder.embed([c["text"] for c in chunks])
                for c, e in zip(chunks, embs):
                    c["emb"] = _to_jsonable(e)
            except Exception:
                pass
            d["chunks"] = chunks
            done += 1
        with self._lock:
            self._save()
        return done

    def detail(self, doc_id: str):
        """返回单篇文档的切片详情（供自检）。"""
        for d in self.docs:
            if d["id"] == doc_id:
                return {
                    "id": d["id"],
                    "name": d["name"],
                    "added": d.get("added", ""),
                    "chunks": [
                        {
                            "index": i,
                            "heading": c.get("heading", ""),
                            "text": c["text"],
                            "chars": len(c["text"]),
                        }
                        for i, c in enumerate(d["chunks"])
                    ],
                }
        return None

    # ---------- 检索 ----------
    def retrieve(self, query: str, k: int = 3):
        """返回 {hits: [...], removed: n}。hits 每项含 score/doc/heading/text。"""
        threshold = self.lexical_threshold if self.embedder.name == "lexical" else self.threshold
        qemb = self.embedder.embed([query], is_query=True)[0]

        scored = []
        for d in self.docs:
            for ch in d["chunks"]:
                sim = cosine(qemb, ch.get("emb"))
                if sim >= threshold:
                    scored.append((sim, d["name"], ch))
        scored.sort(key=lambda x: -x[0])

        # 去重：与已选块内容重叠过高则剔除
        kept, removed = [], 0
        for sim, doc_name, ch in scored:
            toks = set(tokenize(ch["text"]))
            dup = False
            for _, _, kch in kept:
                if containment(toks, set(tokenize(kch["text"]))) > self.dedup_threshold:
                    dup = True
                    removed += 1
                    break
            if not dup:
                kept.append((sim, doc_name, ch))
            if len(kept) >= k:
                break

        hits = [
            {
                "score": round(s, 4),
                "doc": n,
                "heading": ch.get("heading", ""),
                "text": ch["text"],
            }
            for s, n, ch in kept
        ]
        return {"hits": hits, "removed": removed}
