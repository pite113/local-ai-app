@echo off
cd /d %~dp0
start "" /D ".." "..\.venv\Scripts\pythonw.exe" run.py
echo 本地AI工作台已启动: http://公网IP:8000
timeout /t 3 >nul