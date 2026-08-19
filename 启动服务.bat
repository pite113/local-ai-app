@echo off
chcp 65001 >nul
cd /d %~dp0
start "" ".venv\Scripts\pythonw.exe" run.py
echo.
echo 本地AI工作台已启动 (后台运行, 无窗口)
echo 浏览器访问: http://127.0.0.1:8000
echo.
timeout /t 3 >nul
