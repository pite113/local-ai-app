@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   本地 AI 工作台 - 一键启动
echo ============================================
if not exist .venv (
    echo [1/3] 首次运行，正在创建虚拟环境...
    python -m venv .venv
)
echo [2/3] 检查依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
echo [3/3] 启动服务...
.venv\Scripts\python.exe run.py
pause
