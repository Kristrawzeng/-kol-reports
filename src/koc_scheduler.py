# -*- coding: utf-8 -*-
"""
创建 Windows 计划任务：
  任务1：每天 08:30 自动运行 KOC 日度监测
  任务2：开机自动启动 HTTP 文件服务（供同事访问报告）

一次性运行此脚本即可完成所有配置：
  python koc_scheduler.py
"""
import os, subprocess, sys, socket
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PYTHON     = r"C:\Users\kristrawzeng\AppData\Local\Programs\Python\Python312\python.exe"
BASE_DIR   = Path(__file__).parent
MONITOR    = BASE_DIR / "koc_monitor.py"
RETRY      = BASE_DIR / "koc_retry.py"
SERVER     = BASE_DIR / "koc_server.py"
TASK_MONITOR = "FutuKOCDailyMonitor"
TASK_RETRY   = "FutuKOCAfternoonRetry"
TASK_SERVER  = "FutuKOCWebServer"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def create_monitor_task():
    """每天 08:30 自动跑监测（输出写入 morning_run.log 供排错）"""
    LOG = BASE_DIR / "morning_run.log"
    subprocess.run(["schtasks", "/delete", "/tn", TASK_MONITOR, "/f"], capture_output=True)
    # 用 cmd /c 包一层，把 stdout+stderr 重定向到日志文件
    tr = f'cmd /c ""{PYTHON}" "{MONITOR}" --max 1000 >> "{LOG}" 2>&1"'
    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_MONITOR,
        "/tr",  tr,
        "/sc",  "DAILY",
        "/st",  "08:30",
        "/f"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ 监测任务：每天 08:30 自动运行，日志 → {LOG}")
    else:
        print(f"❌ 监测任务创建失败：{result.stderr or result.stdout}")

def create_retry_task():
    """每天 15:00 智能重试（若上午晒单=0 则重跑）"""
    subprocess.run(["schtasks", "/delete", "/tn", TASK_RETRY, "/f"], capture_output=True)
    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_RETRY,
        "/tr",  f'"{PYTHON}" "{RETRY}"',
        "/sc",  "DAILY",
        "/st",  "15:00",
        "/f"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ 重试任务：每天 15:00 自动检查并重试")
    else:
        print(f"❌ 重试任务创建失败：{result.stderr or result.stdout}")

def create_server_task():
    """开机自动启动 HTTP 服务"""
    subprocess.run(["schtasks", "/delete", "/tn", TASK_SERVER, "/f"], capture_output=True)
    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_SERVER,
        "/tr",  f'"{PYTHON}" "{SERVER}"',
        "/sc",  "ONLOGON",
        "/f"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ Web服务：开机自动启动")
    else:
        print(f"❌ Web服务任务创建失败：{result.stderr or result.stdout}")

def main():
    print(f"\n{'='*55}")
    print(f"  牛牛圈 KOC 监测 · 自动化配置")
    print(f"{'='*55}\n")

    create_monitor_task()
    create_retry_task()
    create_server_task()

    # 立即启动 HTTP 服务
    import subprocess as sp
    sp.Popen([PYTHON, str(SERVER)], creationflags=0x00000008)  # DETACHED_PROCESS

    ip = get_local_ip()
    print(f"\n{'='*55}")
    print(f"  ✅ 配置完成！")
    print(f"{'='*55}")
    print(f"\n  📅 监测计划：08:30 每日运行 · 15:00 自动重试（晒单为0时）")
    print(f"\n  🌐 同事访问地址：")
    print(f"     http://{ip}:8080")
    print(f"\n  把这个地址发给同事，在公司网络下直接打开即可")
    print(f"  （同事无需安装任何东西，浏览器直接访问）")
    print(f"\n{'='*55}\n")

if __name__ == "__main__":
    main()
