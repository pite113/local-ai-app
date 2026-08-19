@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist data mkdir data
powershell -NoProfile -Command "Set-Content -LiteralPath 'data\auth_enabled.flag' -Value 'off' -NoNewline"
echo ============================================
echo   [已关闭] 登录验证已关闭
echo   打开页面直接可用（注意: 公网分享前请重新开启）
echo ============================================
pause
