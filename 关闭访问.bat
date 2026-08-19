@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist data mkdir data
powershell -NoProfile -Command "Set-Content -LiteralPath 'data\access.flag' -Value 'off' -NoNewline"
echo ============================================
echo   [已关闭] 所有访问已停止（包括你自己）
echo   访客再打开页面会看到"演示已关闭"
echo   重新开放：双击"开启访问.bat"
echo ============================================
pause
