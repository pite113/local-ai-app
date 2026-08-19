# -*- coding: utf-8 -*-
"""云服务器一键部署：依赖安装 + 防火墙 + 开机自启 + 启动服务。"""
import subprocess
import sys
import time

PY = r"C:\local-ai-app\.venv\Scripts\python.exe"
APP = r"C:\local-ai-app"
LOG = r"C:\deploy.log"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=1800):
    log("RUN: " + cmd)
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "")[-2000:] + (p.stderr or "")[-2000:]
    log("RC=" + str(p.returncode))
    if out.strip():
        log("OUT: " + out.strip()[-1500:])
    return p.returncode


def main():
    log("=== 开始部署 ===")
    # 1. 依赖（用 venv python 的 pip，清华镜像）
    if run(f'"{PY}" -m pip install -r "{APP}\\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple -q') == 0:
        log("依赖安装完成")
    else:
        log("依赖安装失败，重试一次...")
        run(f'"{PY}" -m pip install -r "{APP}\\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple')
    # 2. 防火墙
    run('netsh advfirewall firewall delete rule name="local-ai-app"')
    run('netsh advfirewall firewall add rule name="local-ai-app" dir=in action=allow protocol=TCP localport=8000')
    # 3. 登录验证强制开启
    run(f'powershell -NoProfile -Command "Set-Content -LiteralPath \'{APP}\\data\\auth_enabled.flag\' -Value \'on\' -NoNewline"')
    # 4. 开机自启（任务计划程序）
    ps = (
        "$a = New-ScheduledTaskAction -Execute '%s' -Argument 'run.py' -WorkingDirectory '%s'; "
        "$t = New-ScheduledTaskTrigger -AtStartup; "
        "Register-ScheduledTask -TaskName 'LocalAIWorkbench' -Action $a -Trigger $t -Force"
    ) % (APP + r"\.venv\Scripts\pythonw.exe", APP)
    run(f'powershell -NoProfile -Command "{ps}"')
    # 5. 启动服务
    run(f'powershell -NoProfile -Command "Start-Process -FilePath \'{APP}\\.venv\\Scripts\\pythonw.exe\' -ArgumentList \'run.py\' -WorkingDirectory \'{APP}\'"')
    log("=== 部署脚本执行完毕 ===")


if __name__ == "__main__":
    main()
