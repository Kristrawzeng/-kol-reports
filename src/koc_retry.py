# -*- coding: utf-8 -*-
"""
KOC 监测下午智能重试脚本 v1
- 每天 15:00 由计划任务调用
- 读取 reports/last_run.json 判断上午运行结果
- 若状态非 ok 或晒单+打点=0，自动重跑 koc_monitor.py --max 800
- 若上午已成功（ok + 晒单或打点>0），直接跳过
"""
import json, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PYTHON   = r"C:\Users\kristrawzeng\AppData\Local\Programs\Python\Python312\python.exe"
BASE_DIR = Path(__file__).parent
LAST_RUN = BASE_DIR / "reports" / "last_run.json"


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def notify_windows(title: str, body: str) -> None:
    try:
        t, b = _xml_escape(title), _xml_escape(body)
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager,"
            " Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
            "[Windows.Data.Xml.Dom.XmlDocument,"
            " Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
            f"$x='<toast><visual><binding template=\"ToastGeneric\">"
            f"<text>{t}</text><text>{b}</text>"
            f"</binding></visual></toast>';"
            "$d=New-Object Windows.Data.Xml.Dom.XmlDocument;$d.LoadXml($x);"
            "$n=[Windows.UI.Notifications.ToastNotification]::new($d);"
            "[Windows.UI.Notifications.ToastNotificationManager]"
            "::CreateToastNotifier('KOC\u76d1\u6d4b\u4e2d\u5fc3').Show($n)"
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    except Exception:
        pass


def load_last_run() -> dict:
    if not LAST_RUN.exists():
        return {}
    try:
        return json.loads(LAST_RUN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    print(f"\n{'='*55}")
    print(f"  KOC 监测下午重试检查  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    data  = load_last_run()

    last_date    = data.get("date", "")
    status       = data.get("status", "")
    trade_cnt    = data.get("trade_cnt", 0)
    signal_cnt   = data.get("signal_cnt", 0)
    koc_cnt      = data.get("koc_cnt", 0)

    # ── 判断是否需要重试 ──────────────────────────────────────────
    if last_date == today and status == "ok" and (trade_cnt + signal_cnt) > 0:
        print(f"✅ 上午已成功：KOC {koc_cnt} · 晒单 {trade_cnt} · 打点 {signal_cnt}，跳过重试")
        return

    if last_date != today:
        reason = f"今日无运行记录（上次记录日期：{last_date or '无'}）"
    elif status in ("cookie_expired", "cookie_missing"):
        reason = f"Cookie 已过期，需要重新登录后才能重试"
        print(f"❌ {reason}")
        notify_windows("❌ KOC监测重试跳过", f"{reason}\n请手动运行 futu_login.py")
        return
    elif status == "vision_fail":
        reason = f"上午图片下载全部失败（Vision=0），重试中..."
    elif status == "protected":
        reason = f"上午被保护策略跳过（晒单 {trade_cnt}+打点 {signal_cnt}=0），重试中..."
    else:
        reason = f"上午状态={status or '未知'}，晒单={trade_cnt} 打点={signal_cnt}，重试中..."

    print(f"🔄 触发重试：{reason}")
    notify_windows("🔄 KOC监测下午重试", reason)

    # ── 执行重试 ─────────────────────────────────────────────────
    result = subprocess.run(
        [PYTHON, str(BASE_DIR / "koc_monitor.py"), "--max", "800"],
    )

    if result.returncode != 0:
        print(f"\n❌ 重试退出码 {result.returncode}")
        notify_windows("❌ KOC监测重试失败", f"退出码 {result.returncode}，请手动检查日志")
    else:
        print(f"\n✅ 重试完成")


if __name__ == "__main__":
    main()
