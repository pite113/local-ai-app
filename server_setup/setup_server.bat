@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   云服务器一键部署脚本
echo   前提: 已解压到 C:\local-ai-app
echo ============================================
rem [1/5] Python 检查
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] 未检测到 Python!
    echo     请先安装: https://www.python.org/downloads
    echo     安装时务必勾选 "Add Python to PATH"
    start https://www.python.org/downloads
    pause
    exit /b
)
echo [1/5] Python 已安装
rem [2/5] 虚拟环境 + 依赖
echo [2/5] 创建虚拟环境并安装依赖...
if not exist ..\.venv python -m venv ..\.venv
..\.venv\Scripts\python -m pip install -r ..\requirements.txt -q
rem [3/5] 防火墙 8000
echo [3/5] 开放防火墙 8000 端口...
netsh advfirewall firewall delete rule name="local-ai-app" >nul 2>&1
netsh advfirewall firewall add rule name="local-ai-app" dir=in action=allow protocol=TCP localport=8000
rem [4/5] 数据目录 + 配置模板 + 强制开启登录验证
echo [4/5] 初始化配置...
if not exist ..\data mkdir ..\data
if not exist ..\.env copy ..\.env.example ..\.env >nul
powershell -NoProfile -Command "Set-Content -LiteralPath '..\data\auth_enabled.flag' -Value 'on' -NoNewline"
rem [5/5] 开机自启（开机触发, 无需登录）
echo [5/5] 注册开机自启...
powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute 'C:\local-ai-app\server_setup\start_server.bat'; $t = New-ScheduledTaskTrigger -AtStartup; Register-ScheduledTask -TaskName 'LocalAIWorkbench' -Action $a -Trigger $t -Description 'Local AI Workbench' -Force"
echo.
echo ============================================
echo   部署完成!
echo   下一步:
echo     1. 编辑 ..\.env 填入密钥 (DeepSeek / 生图)
echo     2. 双击 start_server.bat 启动
echo     3. 浏览器访问 http://公网IP:8000
echo     4. 云厂商控制台"防火墙/安全组"也要放行 TCP 8000
echo     5. 登录验证已强制开启 (安全)
echo ============================================
pause