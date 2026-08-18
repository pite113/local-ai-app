"""文本向量化(Embedding)接入层。

支持四种实现，按配置自动选择，不可用时优雅降级：
- local  : fastembed 本地语义模型（免费、离线、数据不出门）★ 推荐
- ollama : Ollama 本地 embedding 模型
- api    : OpenAI 兼容 /embeddings 接口（硅基流动等）
- lexical: 词法向量回退（零依赖，保证系统永不挂）

向量统一返回：稠密 list[float]（语义）或稀疏 dict（词法）。
"""
import httpx

from .config import Settings
from .textutil import tf_vector, tokenize


class BaseEmbedder:
    name = "base"

    def embed(self, texts, is_query=False):
        """批量向量化，返回与 texts 等长的向量列表。
        is_query=True 表示是检索时的查询文本（部分模型需要不同前缀）。
        """
        raise NotImplementedError


class LexicalEmbedder(BaseEmbedder):
    """词法回退：词频稀疏向量（旧版行为）。"""
    name = "lexical"

    def embed(self, texts, is_query=False):
        return [tf_vector(tokenize(t)) for t in texts]


class FastEmbedEmbedder(BaseEmbedder):
    """fastembed 本地语义模型。"""
    name = "local"

    def __init__(self, model: str):
        self.model = model
        self._fe = None

    def _ensure(self):
        if self._fe is None:
            from fastembed import TextEmbedding
            self._fe = TextEmbedding(model_name=self.model)
        return self._fe

    def embed(self, texts, is_query=False):
        fe = self._ensure()
        kwargs = {}
        if "e5" in self.model.lower():
            kwargs["query_instruction"] = "query: " if is_query else "passage: "
        return [list(v) for v in fe.embed(list(texts), **kwargs)]


class OllamaEmbedder(BaseEmbedder):
    """Ollama 本地 embedding 模型。"""
    name = "ollama"

    def __init__(self, base: str, model: str):
        self.base = base.rstrip("/")
        self.model = model

    def embed(self, texts):
        r = httpx.post(
            f"{self.base}/api/embed",
            json={"model": self.model, "input": list(texts)},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["embeddings"]

    @staticmethod
    def available(base: str) -> bool:
        try:
            r = httpx.get(base.rstrip("/") + "/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False


class OpenAICompatEmbedder(BaseEmbedder):
    """OpenAI 兼容 /embeddings 接口（硅基流动等）。"""
    name = "api"

    def __init__(self, base: str, key: str, model: str):
        self.base = base.rstrip("/")
        self.key = key
        self.model = model

    def embed(self, texts):
        headers = {"Authorization": f"Bearer {self.key}"}
        r = httpx.post(
            f"{self.base}/embeddings",
            json={"model": self.model, "input": list(texts)},
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


def _try_local(model: str):
    """尝试初始化本地语义模型（会触发首次模型下载）；失败返回 None。"""
    try:
        from fastembed import TextEmbedding
        TextEmbedding(model_name=model)
        return FastEmbedEmbedder(model)
    except Exception:
        return None


def get_embedder(s: Settings) -> BaseEmbedder:
    mode = (s.embed_provider or "auto").strip().lower()
    if mode == "auto":
        if OllamaEmbedder.available(s.embed_ollama_base):
            return OllamaEmbedder(s.embed_ollama_base, s.embed_ollama_model)
        if s.embed_api_key:
            return OpenAICompatEmbedder(s.embed_api_base, s.embed_api_key, s.embed_api_model)
        loc = _try_local(s.embed_local_model)
        if loc is not None:
            return loc
        return LexicalEmbedder()
    if mode == "ollama":
        return OllamaEmbedder(s.embed_ollama_base, s.embed_ollama_model)
    if mode == "api":
        return OpenAICompatEmbedder(s.embed_api_base, s.embed_api_key, s.embed_api_model)
    if mode == "local":
        loc = _try_local(s.embed_local_model)
        if loc is not None:
            return loc
        return LexicalEmbedder()
    return LexicalEmbedder()
