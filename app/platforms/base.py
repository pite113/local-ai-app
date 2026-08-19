"""上架平台适配器基类：统一各平台上架的接口。

新平台 = 继承本类写一个文件，并在 __init__.py 注册一行。
"""
from ..config import Settings


class PlatformAdapter:
    name = "base"

    def validate_config(self):
        """检查配置是否就绪。返回 (ok, message)。"""
        raise NotImplementedError

    def upload_products(self, rows, header, mapping, settings: Settings):
        """批量发布商品。rows 为数据行（不含表头），header 为表头。
        mapping: {title_col, body_col, image_col, tags_col, status}
        返回 {created, total, results: [{title, status, id?}]}
        """
        raise NotImplementedError
