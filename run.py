"""启动本地 AI 工作台。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import load_settings  # noqa: E402
from app.main import app  # noqa: E402

if __name__ == "__main__":
    s = load_settings()
    print(f"==============================================")
    print(f"  本地 AI 工作台已启动")
    print(f"  请在浏览器打开: http://{s.host}:{s.port}")
    print(f"  当前模型模式: {s.provider}")
    print(f"  按 Ctrl+C 停止")
    print(f"==============================================")
    app.run(host=s.host, port=s.port, threaded=True)
