@echo off
cd /d %~dp0
if not exist data mkdir data
echo ============================================
echo   设置访客体验时长  [0 = 不限 / 30 = 30分钟]
echo ============================================
echo.
set /p m=Minutes: 
if not defined m set m=0
powershell -NoProfile -Command "Set-Content -LiteralPath 'data\trial_minutes.flag' -Value '%m%' -NoNewline"
echo.
echo   [已设置] %m% 分钟 (0 = 不限)  -  新登录访客生效
echo ============================================
pause