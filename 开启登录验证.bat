@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist data mkdir data
powershell -NoProfile -Command "Set-Content -LiteralPath 'data\auth_enabled.flag' -Value 'on' -NoNewline"
echo ============================================
echo   [已开启] 登录验证已开启
echo   访客需要邮箱验证码才能使用
echo ============================================
pause
