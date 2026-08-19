"""上架平台注册表：新平台在此注册一行即可接入。"""
from .base import PlatformAdapter
from .shopify import ShopifyAdapter

ADAPTERS = {
    "shopify": ShopifyAdapter,
    # 后续: "taobao": TaobaoAdapter, "douyin": DouyinAdapter, ...
}


def get_adapter(name: str, settings) -> PlatformAdapter:
    cls = ADAPTERS.get((name or "").strip().lower())
    if cls is None:
        return None
    return cls(settings)
