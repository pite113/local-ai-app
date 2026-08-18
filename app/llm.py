"""大模型接入层：mock(演示) / ollama(本地) / openai(兼容API)。

chat() 统一返回 (回复文本, 输入tokens, 输出tokens)，供运行监控统计。
未来接新模型只在这里加一个类即可。
"""
import json
import time

import httpx

from .config import Settings


def estimate_tokens(text: str) -> int:
    """粗略估算：中文约 1.5 字符/token，英文约 4 字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk / 1.5) + int(other / 4))


def _post_with_retry(url: str, *, attempts: int = 3, backoff: float = 1.5, **kwargs) -> httpx.Response:
    """带重试的 POST：网络异常与 5xx 自动重试，其余错误直接返回。"""
    last = None
    for i in range(attempts):
        try:
            r = httpx.post(url, **kwargs)
            if r.status_code < 500:
                return r
            last = r
        except httpx.HTTPError as e:
            last = e
        if i < attempts - 1:
            time.sleep(backoff * (i + 1))
    if isinstance(last, httpx.Response):
        return last
    raise last  # 网络错误在最后一次也失败时抛出


class BaseLLM:
    name = "base"

    def chat(self, messages, system=None):
        """返回 (回复文本, 输入tokens, 输出tokens)。"""
        raise NotImplementedError


class MockLLM(BaseLLM):
    """演示模式：不需要任何模型/API，随时可跑。"""
    name = "mock"

    def chat(self, messages, system=None):
        last = messages[-1]["content"] if messages else ""
        text = (
            "[演示模式] 当前没有连接真实模型，所以这是模拟回复。\n\n"
            f"你刚才问的是：{last}\n\n"
            "（配置 LLM_PROVIDER=ollama 使用本地模型，或 =openai 使用 DeepSeek 等 API，"
            "即可启用真实 AI 回复。详见 README。）"
        )
        prompt = json.dumps(messages, ensure_ascii=False) + (system or "")
        return text, estimate_tokens(prompt), estimate_tokens(text)


class OllamaLLM(BaseLLM):
    """Ollama 本地模型（免费、离线、数据不出门）。"""
    name = "ollama"

    def __init__(self, base: str, model: str):
        self.base = base.rstrip("/")
        self.model = model

    def chat(self, messages, system=None):
        if system:
            messages = [{"role": "system", "content": system}] + messages
        payload = {"model": self.model, "messages": messages, "stream": False}
        r = _post_with_retry(f"{self.base}/api/chat", json=payload, timeout=300)
        r.raise_for_status()
        data = r.json()
        text = data["message"]["content"]
        ti = data.get("prompt_eval_count") or estimate_tokens(
            json.dumps(messages, ensure_ascii=False)
        )
        to = data.get("eval_count") or estimate_tokens(text)
        return text, ti, to


class OpenAICompatLLM(BaseLLM):
    """OpenAI 兼容接口（DeepSeek / OpenAI / 硅基流动 等）。"""
    name = "openai"

    def __init__(self, base: str, key: str, model: str):
        self.base = base.rstrip("/")
        self.key = key
        self.model = model

    def chat(self, messages, system=None):
        if system:
            messages = [{"role": "system", "content": system}] + messages
        headers = {"Authorization": f"Bearer {self.key}"}
        payload = {"model": self.model, "messages": messages}
        r = _post_with_retry(
            f"{self.base}/chat/completions", json=payload, headers=headers, timeout=300
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        ti = usage.get("prompt_tokens") or estimate_tokens(
            json.dumps(messages, ensure_ascii=False)
        )
        to = usage.get("completion_tokens") or estimate_tokens(text)
        return text, ti, to


def get_llm(s: Settings) -> BaseLLM:
    if s.provider == "ollama":
        return OllamaLLM(s.ollama_base, s.ollama_model)
    if s.provider == "openai":
        return OpenAICompatLLM(s.openai_base, s.openai_key, s.openai_model)
    return MockLLM()
