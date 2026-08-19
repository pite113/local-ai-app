"""Shopify 上架适配器。

用 Shopify Admin API 批量创建商品：
POST https://{shop}.myshopify.com/admin/api/{version}/products.json

- 图片支持两种来源：本地上传图（base64 attachment，无需公网地址）或公网 URL（src）。
- 默认 status=draft（草稿），安全；需要立即上架可传 active。
"""
import base64
import os

import httpx

from ..config import Settings
from .base import PlatformAdapter


class ShopifyAdapter(PlatformAdapter):
    name = "shopify"
    api_version = "2024-10"

    def __init__(self, settings: Settings):
        self.shop = (settings.shopify_shop or "").strip()
        self.token = (settings.shopify_access_token or "").strip()

    def validate_config(self):
        if not self.shop:
            return False, "未配置 Shopify：请在 .env 填写 SHOPIFY_SHOP（店铺名，不含 .myshopify.com）"
        if not self.token:
            return False, "未配置 Shopify：请在 .env 填写 SHOPIFY_ACCESS_TOKEN（店铺管理后台获取）"
        return True, "Shopify 配置就绪"

    def _base_url(self):
        return f"https://{self.shop}.myshopify.com/admin/api/{self.api_version}"

    def _resolve_image(self, url_or_path: str, data_dir: str):
        """把图片 URL/路径转成 Shopify 可用格式：本地图→base64 attachment，公网图→src。"""
        if not url_or_path:
            return None
        url = str(url_or_path).strip()
        if url.startswith("/api/tools/image/"):
            fname = os.path.basename(url)
            fpath = os.path.join(data_dir, "output", fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    return {"attachment": base64.b64encode(f.read()).decode()}
            return None
        if url.startswith("http"):
            return {"src": url}
        return None

    def upload_products(self, rows, header, mapping, settings: Settings):
        ok, msg = self.validate_config()
        if not ok:
            return {"created": 0, "total": 0, "results": [], "error": msg}

        def get(col):
            if not col or col not in header:
                return ""
            i = header.index(col)
            return str(row[i]).strip() if i < len(row) and row[i] is not None else ""

        results = []
        created = 0
        for row in rows:
            title = get(mapping.get("title_col"))
            if not title:
                results.append({"title": "", "status": "跳过(无标题)"})
                continue
            product = {
                "title": title,
                "status": mapping.get("status") or "draft",
                "body_html": get(mapping.get("body_col")) or None,
            }
            tags = get(mapping.get("tags_col"))
            if tags:
                product["tags"] = tags.replace("，", ",")
            img = self._resolve_image(get(mapping.get("image_col")), settings.data_dir)
            if img:
                product["images"] = [img]
            payload = {"product": {k: v for k, v in product.items() if v is not None}}
            try:
                r = httpx.post(
                    f"{self._base_url()}/products.json",
                    json=payload,
                    headers={
                        "X-Shopify-Access-Token": self.token,
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                if r.status_code in (200, 201):
                    pid = r.json().get("product", {}).get("id")
                    created += 1
                    results.append({"title": title, "status": "成功", "id": pid})
                else:
                    results.append({"title": title, "status": f"失败 HTTP {r.status_code}: {r.text[:120]}"})
            except Exception as e:
                results.append({"title": title, "status": f"异常: {e}"})

        return {"created": created, "total": len(results), "results": results}
