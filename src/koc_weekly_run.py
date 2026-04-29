# -*- coding: utf-8 -*-
"""
KOC 周度监测一键运行脚本
1. 运行 koc_monitor.py（爬取 + 分析 + 生成周报）
2. 运行 koc_dashboard.py（更新总览仪表盘）
3. 在浏览器打开仪表盘

用法：
  python koc_weekly_run.py              # 正常模式（打开浏览器，需要手动登录时可见）
  python koc_weekly_run.py --headless   # 无头模式（需已保存 Cookie）
  python koc_weekly_run.py --pages 15   # 抓取更多页（默认10）
"""
import argparse, subprocess, sys, os, webbrowser, re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PYTHON     = sys.executable
BASE_DIR   = Path(__file__).parent
MONITOR    = BASE_DIR / "koc_monitor.py"
POTENTIAL  = BASE_DIR / "koc_potential.py"
DASHBOARD  = BASE_DIR / "koc_dashboard.py"
COOKIE_FILE= BASE_DIR / ".futu_cookies.json"
LOGIN_PY   = BASE_DIR / "futu_login.py"
DASH_HTML  = BASE_DIR / "reports" / "koc_dashboard.html"

def run(cmd, **kwargs):
    print(f"\n> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    return result.returncode == 0

def self_check(report_dir: Path) -> dict:
    """自检：解析今日报告，返回质量指标"""
    today = datetime.now().strftime("%Y-%m-%d")
    report = report_dir / f"koc_monitor_{today}.html"
    result = {"ok": False, "posts": 0, "trades": 0, "signals": 0, "size_kb": 0, "path": str(report)}
    if not report.exists():
        return result
    html = report.read_text(encoding="utf-8", errors="replace")
    result["size_kb"] = report.stat().st_size // 1024
    # 从报告的 sp-n 数值块精确读取各维度计数（顺序：KOC、晒单、打点、长文、扫描总量）
    nums = re.findall(r'class="sp-n"[^>]*>(\d+)<', html)
    result["koc_cnt"]  = int(nums[0]) if len(nums) > 0 else 0
    result["trades"]   = int(nums[1]) if len(nums) > 1 else 0
    result["signals"]  = int(nums[2]) if len(nums) > 2 else 0
    result["posts"]    = int(nums[4]) if len(nums) > 4 else result["koc_cnt"]
    # 扫描总量也可从文本获取备用
    m = re.search(r'扫描[^\d]*(\d+)', html)
    if result["posts"] == 0 and m:
        result["posts"] = int(m.group(1))
    result["ok"] = (
        result["posts"] >= 100
        and result["size_kb"] >= 500
        and (result["trades"] + result["signals"]) > 0
    )
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless",    action="store_true")
    parser.add_argument("--pages",       type=int, default=None,  help="兼容旧参数")
    parser.add_argument("--max",         type=int, default=1000)
    parser.add_argument("--vision-days", type=int, default=7,     help="对近N天帖子做Vision分析（默认7=整周，确保大额晒单和打点图全覆盖）")
    parser.add_argument("--vision-cap",  type=int, default=120,   help="最多Vision分析次数")
    args = parser.parse_args()
    if args.pages and args.max == 1000:
        args.max = args.pages * 30

    print(f"\n{'='*60}")
    print(f"  牛牛圈 KOC 周度监测  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # 检查登录 Cookie
    if not COOKIE_FILE.exists():
        print("\n⚠️  尚未登录，请先运行登录助手：")
        print(f"  python {LOGIN_PY}")
        print("\n是否立即启动登录助手？(y/n): ", end="", flush=True)
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = "n"
        if ans == "y":
            subprocess.run([PYTHON, str(LOGIN_PY)])
        if not COOKIE_FILE.exists():
            print("取消，请手动运行登录助手后重试")
            return

    # Step 1: 生成监测报告
    print("\n【Step 1/3】运行 KOC 监测爬虫...")
    monitor_cmd = [
        PYTHON, str(MONITOR),
        "--max",         str(args.max),
        "--vision-days", str(args.vision_days),
        "--vision-cap",  str(args.vision_cap),
    ]

    ok = run(monitor_cmd, cwd=str(BASE_DIR))
    if not ok:
        print("⚠️  监测脚本运行遇到问题，但继续更新仪表盘...")

    # 自检：报告质量不达标时自动重试一次
    report_dir = BASE_DIR / "reports"
    chk = self_check(report_dir)
    print(f"\n【自检】帖数={chk['posts']} | KOC={chk.get('koc_cnt',0)} | 晒单={chk['trades']} | 打点={chk['signals']} | 大小={chk['size_kb']}KB", end="")
    if not chk["ok"]:
        if chk["posts"] == 0:
            reason = "报告未生成"
        elif chk["trades"] + chk["signals"] == 0:
            reason = "大额晒单+打点图均为0（Vision分析未命中或图片下载失败）"
        else:
            reason = f"帖数={chk['posts']}<100 或 大小={chk['size_kb']}KB<500"
        print(f" ⚠️  {reason}，30秒后自动重试...")
        import time; time.sleep(30)
        # 删掉不合格报告，用整周全量重跑
        p = Path(chk["path"])
        if p.exists(): p.unlink()
        retry_cmd = monitor_cmd + ["--vision-days", "7"]  # 确保全周视觉分析
        run(retry_cmd, cwd=str(BASE_DIR))
        chk = self_check(report_dir)
        print(f"\n【重试后自检】帖数={chk['posts']} | KOC={chk.get('koc_cnt',0)} | 晒单={chk['trades']} | 打点={chk['signals']} | 大小={chk['size_kb']}KB", end="")
        if chk["ok"]:
            print(" ✅")
        else:
            print(" ❌ 重试后仍不达标")
            if chk["trades"] + chk["signals"] == 0:
                print("  ⚠️  大额晒单和打点图为0，可能原因：")
                print("     1. Cookie 已过期，请重新运行 futu_login.py")
                print("     2. 本周图片帖子偏少，Vision 未识别到晒单/打点图")
                print("     3. 可手动运行: python koc_monitor.py --all-trades")
    else:
        print(" ✅")

    # Step 2: 潜力挖掘
    print("\n【Step 2/3】运行潜力 KOC 挖掘...")
    run([PYTHON, str(POTENTIAL), "--no-browser"], cwd=str(BASE_DIR))

    # Step 3: 更新仪表盘
    print("\n【Step 3/3】更新仪表盘...")
    run([PYTHON, str(DASHBOARD)], cwd=str(BASE_DIR))

    # 打开仪表盘
    if DASH_HTML.exists():
        url = f"file:///{str(DASH_HTML).replace(chr(92), '/')}"
        webbrowser.open(url)
        print(f"\n✅ 已在浏览器打开仪表盘：{url}")
    else:
        print(f"\n⚠️  仪表盘文件未找到：{DASH_HTML}")

    print(f"\n{'='*60}")
    print(f"  完成！{datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
