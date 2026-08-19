@echo off
chcp 65001 >nul
echo 正在停止本地AI工作台...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo.
echo 已停止。
timeout /t 3 >nul
