"""文本处理工具：轻量分词、向量余弦、内容重叠度。"""
import math
import re

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str):
    """轻量分词：中文按字符二元组，英文按单词。"""
    toks = []
    for m in _CJK.finditer(text):
        seg = m.group()
        if len(seg) == 1:
            toks.append(seg)
        else:
            for i in range(len(seg) - 1):
                toks.append(seg[i:i + 2])
            if len(seg) <= 4:
                toks.append(seg)
    for m in _LATIN.finditer(text):
        w = m.group().lower()
        if len(w) > 1:
            toks.append(w)
    return toks


def tf_vector(toks) -> dict:
    v = {}
    for t in toks:
        v[t] = v.get(t, 0) + 1
    return v


def cosine(a, b) -> float:
    """支持稀疏 dict 向量与稠密 list 向量。"""
    if isinstance(a, dict) and isinstance(b, dict):
        if not a or not b:
            return 0.0
        dot = sum(a.get(t, 0) * b.get(t, 0) for t in a)
        na = math.sqrt(sum(x * x for x in a.values()))
        nb = math.sqrt(sum(x * x for x in b.values()))
        if not na or not nb:
            return 0.0
        return dot / (na * nb)
    if isinstance(a, list) and isinstance(b, list):
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if not na or not nb:
            return 0.0
        return float(dot / (na * nb))  # 转回 Python float，保证 JSON 可序列化
    return 0.0


def containment(a_toks: set, b_toks: set) -> float:
    """a 的 token 集合被 b 覆盖的比例（用于召回去重）。"""
    if not a_toks or not b_toks:
        return 0.0
    return len(a_toks & b_toks) / len(a_toks)
