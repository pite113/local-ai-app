"""运行日志与统计：记录每次调用，统计 token 消耗与冗余运行。"""
import json
import os
import threading
import time
from collections import Counter
from datetime import datetime


class LogStore:
    """日志存储：内存 + 追加写入 JSONL 文件，可统计与检索；文件超限自动轮转。"""

    def __init__(self, path: str, max_records: int = 5000, max_mb: float = 2.0):
        self.path = path
        self.max_records = max_records
        self.max_mb = max_mb
        self._lock = threading.Lock()
        self.records = []
        self._load()

    def _rotate(self):
        """日志文件超过 max_mb 时轮转：logs.jsonl -> logs.1.jsonl -> logs.2.jsonl ..."""
        try:
            if not os.path.exists(self.path):
                return
            if os.path.getsize(self.path) < self.max_mb * 1024 * 1024:
                return
            for i in range(3, 0, -1):
                old = f"{self.path}.{i}"
                src = f"{self.path}.{i - 1}" if i > 1 else self.path
                if os.path.exists(src):
                    if os.path.exists(old):
                        os.remove(old)
                    os.replace(src, old)
        except Exception:
            pass

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.records = [json.loads(line) for line in f if line.strip()]
            except Exception:
                self.records = []
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

    def add(self, **fields) -> dict:
        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ts_ms": time.time(),
            "level": "info",
            **fields,
        }
        with self._lock:
            self.records.append(rec)
            if len(self.records) > self.max_records:
                self.records = self.records[-self.max_records:]
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                self._rotate()
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return rec

    def recent(self, limit: int = 100, ftype: str = None):
        recs = [r for r in self.records if (not ftype or r.get("type") == ftype)]
        return list(reversed(recs[-limit:]))  # 新的在前

    def stats(self, price_in: float, price_out: float) -> dict:
        recs = self.records
        chat = [r for r in recs if r.get("type") == "chat_request"]
        errs = [r for r in recs if r.get("level") == "error"]
        t_in = sum(r.get("tokens_in", 0) for r in chat)
        t_out = sum(r.get("tokens_out", 0) for r in chat)
        cost = sum(r.get("cost", 0) for r in chat)
        durs = [r.get("duration_ms", 0) for r in chat if r.get("duration_ms")]
        by_type = Counter(r.get("type", "other") for r in recs)

        # 冗余检测：同一句话被重复提问
        msg_counts = Counter()
        msg_tokens = {}
        for r in chat:
            m = r.get("message", "")
            if not m:
                continue
            msg_counts[m] += 1
            bucket = msg_tokens.setdefault(m, [0, 0])
            bucket[0] += r.get("tokens_in", 0) + r.get("tokens_out", 0)
        redundant = []
        for m, c in msg_counts.items():
            if c >= 2:
                total = msg_tokens[m][0]
                wasted = int(total * (c - 1) / c) if c else 0
                redundant.append({"message": m[:60], "count": c, "wasted_tokens": wasted})
        redundant.sort(key=lambda x: -x["count"])

        zero_hits = sum(
            1 for r in recs if r.get("type") == "retrieval" and r.get("hits", 0) == 0
        )
        dedup_removed = sum(r.get("removed", 0) for r in recs if r.get("type") == "retrieval")
        return {
            "total_records": len(recs),
            "chat_calls": len(chat),
            "tokens_in": t_in,
            "tokens_out": t_out,
            "tokens_total": t_in + t_out,
            "est_cost": round(cost, 4),
            "price_in": price_in,
            "price_out": price_out,
            "errors": len(errs),
            "avg_duration_ms": round(sum(durs) / len(durs), 1) if durs else 0,
            "by_type": dict(by_type),
            "redundant": redundant,
            "zero_hit_retrievals": zero_hits,
            "dedup_removed": dedup_removed,
            "since": recs[0]["ts"] if recs else "-",
        }

    def clear(self):
        with self._lock:
            self.records = []
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except Exception:
                pass
