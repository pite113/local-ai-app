@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist data mkdir data
powershell -NoProfile -Command "Set-Content -LiteralPath 'data\access.flag' -Value 'on' -NoNewline"
echo ============================================
echo   [已开启] 访问已恢复
echo   访客现在可以正常登录使用了
echo ============================================
pause
