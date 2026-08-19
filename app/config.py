"""配置加载：支持 .env 文件 + 环境变量。"""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    provider: str = "mock"          # mock | ollama | openai
    ollama_base: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    openai_base: str = "https://api.deepseek.com/v1"
    openai_key: str = ""
    openai_model: str = "deepseek-chat"
    data_dir: str = "data"
    upload_dir: str = "data/uploads"
    chunk_size: int = 400
    chunk_min_size: int = 80
    top_k: int = 3
    host: str = "127.0.0.1"
    port: int = 8000
    # 成本估算参考价（每百万 token，USD；DeepSeek V3.2 参考价，可按需修改）
    price_in: float = 0.14
    price_out: float = 0.55
    # 向量化(Embedding)配置
    embed_provider: str = "auto"        # auto | local | ollama | api | lexical
    embed_ollama_base: str = "http://localhost:11434"
    embed_ollama_model: str = "nomic-embed-text"
    embed_api_base: str = ""
    embed_api_key: str = ""
    embed_api_model: str = ""
    embed_local_model: str = "BAAI/bge-small-zh-v1.5"
    # 检索阈值与去重
    retrieve_threshold: float = 0.38          # 语义向量相似度下限
    retrieve_lexical_threshold: float = 0.05  # 词法相似度下限
    dedup_threshold: float = 0.60             # 内容重叠去重阈值
    # 批量作图配置
    image_provider: str = "mock"    # mock(占位图) | api(真实生图)
    image_api_base: str = ""
    image_api_key: str = ""
    image_api_model: str = ""
    # 上架平台
    platform: str = "shopify"
    shopify_shop: str = ""              # 店铺名，不含 .myshopify.com
    shopify_access_token: str = ""
    # 工具与日志
    tool_concurrency: int = 3       # 批量文本并发数
    log_max_mb: float = 2.0         # 日志文件轮转上限(MB)
    agent_max_iterations: int = 15  # Agent 单任务最大步数
    # 访问认证(OTP + 邮件)
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_to: str = ""
    auth_enabled: str = "off"       # on=要求验证码登录 | off=直接可用(默认)
    admin_key: str = ""             # 管理层口令（全视角）
    tech_key: str = ""              # 技术层口令（技术功能，无成本/评估）
    client_key: str = ""            # 使用层口令（仅使用入口）
    otp_ttl_seconds: int = 600          # 验证码有效期 10 分钟
    otp_max_attempts: int = 5           # 最多错误次数
    otp_send_interval: int = 60         # 两次发送最小间隔(秒)
    otp_max_per_hour: int = 5           # 每小时最多发送次数
    session_ttl_seconds: int = 43200    # 会话有效期 12 小时


def _load_dotenv(path: str = ".env") -> None:
    """极简 .env 解析（不依赖第三方库），已存在的环境变量优先。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


def load_settings() -> Settings:
    _load_dotenv()
    s = Settings()
    s.provider = os.environ.get("LLM_PROVIDER", s.provider).strip().lower()
    s.ollama_base = os.environ.get("OLLAMA_BASE_URL", s.ollama_base).strip()
    s.ollama_model = os.environ.get("OLLAMA_MODEL", s.ollama_model).strip()
    s.openai_base = os.environ.get("OPENAI_BASE_URL", s.openai_base).strip()
    s.openai_key = os.environ.get("OPENAI_API_KEY", s.openai_key).strip()
    s.openai_model = os.environ.get("OPENAI_MODEL", s.openai_model).strip()
    s.data_dir = os.environ.get("DATA_DIR", s.data_dir).strip()
    s.upload_dir = os.environ.get("UPLOAD_DIR", os.path.join(s.data_dir, "uploads")).strip()
    s.host = os.environ.get("HOST", s.host).strip()
    s.port = int(os.environ.get("PORT", str(s.port)))
    s.price_in = float(os.environ.get("PRICE_IN_PER_M", str(s.price_in)))
    s.price_out = float(os.environ.get("PRICE_OUT_PER_M", str(s.price_out)))
    s.embed_provider = os.environ.get("EMBED_PROVIDER", s.embed_provider).strip().lower()
    s.embed_ollama_base = os.environ.get("EMBED_OLLAMA_BASE_URL", s.embed_ollama_base).strip()
    s.embed_ollama_model = os.environ.get("EMBED_OLLAMA_MODEL", s.embed_ollama_model).strip()
    s.embed_api_base = os.environ.get("EMBED_API_BASE_URL", s.embed_api_base).strip()
    s.embed_api_key = os.environ.get("EMBED_API_KEY", s.embed_api_key).strip()
    s.embed_api_model = os.environ.get("EMBED_API_MODEL", s.embed_api_model).strip()
    s.embed_local_model = os.environ.get("EMBED_LOCAL_MODEL", s.embed_local_model).strip()
    s.retrieve_threshold = float(os.environ.get("RETRIEVE_THRESHOLD", str(s.retrieve_threshold)))
    s.retrieve_lexical_threshold = float(
        os.environ.get("RETRIEVE_LEXICAL_THRESHOLD", str(s.retrieve_lexical_threshold))
    )
    s.dedup_threshold = float(os.environ.get("DEDUP_THRESHOLD", str(s.dedup_threshold)))
    s.chunk_min_size = int(os.environ.get("CHUNK_MIN_SIZE", str(s.chunk_min_size)))
    s.image_provider = os.environ.get("IMAGE_PROVIDER", s.image_provider).strip().lower()
    s.image_api_base = os.environ.get("IMAGE_API_BASE_URL", s.image_api_base).strip()
    s.image_api_key = os.environ.get("IMAGE_API_KEY", s.image_api_key).strip()
    s.image_api_model = os.environ.get("IMAGE_API_MODEL", s.image_api_model).strip()
    s.platform = os.environ.get("PLATFORM", s.platform).strip().lower()
    s.shopify_shop = os.environ.get("SHOPIFY_SHOP", s.shopify_shop).strip()
    s.shopify_access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", s.shopify_access_token).strip()
    s.tool_concurrency = int(os.environ.get("TOOL_CONCURRENCY", str(s.tool_concurrency)))
    s.log_max_mb = float(os.environ.get("LOG_MAX_MB", str(s.log_max_mb)))
    s.agent_max_iterations = int(os.environ.get("AGENT_MAX_ITERATIONS", str(s.agent_max_iterations)))
    s.smtp_host = os.environ.get("SMTP_HOST", s.smtp_host).strip()
    s.smtp_port = int(os.environ.get("SMTP_PORT", str(s.smtp_port)))
    s.smtp_user = os.environ.get("SMTP_USER", s.smtp_user).strip()
    s.smtp_pass = os.environ.get("SMTP_PASS", s.smtp_pass).strip()
    s.mail_to = os.environ.get("MAIL_TO", s.mail_to).strip()
    s.auth_enabled = os.environ.get("AUTH_ENABLED", s.auth_enabled).strip().lower()
    s.admin_key = os.environ.get("ADMIN_KEY", s.admin_key).strip()
    s.tech_key = os.environ.get("TECH_KEY", s.tech_key).strip()
    s.client_key = os.environ.get("CLIENT_KEY", s.client_key).strip()
    s.otp_ttl_seconds = int(os.environ.get("OTP_TTL_SECONDS", str(s.otp_ttl_seconds)))
    s.otp_max_attempts = int(os.environ.get("OTP_MAX_ATTEMPTS", str(s.otp_max_attempts)))
    s.otp_send_interval = int(os.environ.get("OTP_SEND_INTERVAL", str(s.otp_send_interval)))
    s.otp_max_per_hour = int(os.environ.get("OTP_MAX_PER_HOUR", str(s.otp_max_per_hour)))
    s.session_ttl_seconds = int(os.environ.get("SESSION_TTL_SECONDS", str(s.session_ttl_seconds)))
    return s
