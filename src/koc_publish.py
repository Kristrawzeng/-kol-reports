# -*- coding: utf-8 -*-
"""
牛牛圈 KOC 报告 · 自动发布到 GitHub Pages
每次生成报告后自动推送，同事/自己任何设备都可访问：
  https://kristrawzeng.github.io/kol-reports/

首次运行会引导你完成 GitHub 授权
"""
import sys, subprocess, shutil, os
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GITHUB_USER = "Kristrawzeng"
REPO_NAME   = "-kol-reports"
PAGES_URL   = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/"
BASE_DIR    = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
PUBLISH_DIR = BASE_DIR / ".publish_repo"

def run(cmd, cwd=None, capture=False):
    r = subprocess.run(cmd, shell=True, cwd=cwd,
                       capture_output=capture, text=True, encoding="utf-8", errors="replace")
    return r

def setup_repo():
    """初始化本地发布仓库"""
    if not PUBLISH_DIR.exists():
        PUBLISH_DIR.mkdir()
        run(f'git init', cwd=PUBLISH_DIR)
        run(f'git remote add origin https://github.com/{GITHUB_USER}/{REPO_NAME}.git', cwd=PUBLISH_DIR)
        run(f'git pull origin main --rebase', cwd=PUBLISH_DIR)
        run(f'git checkout -b main', cwd=PUBLISH_DIR)
        print(f"  ✅ 本地发布仓库初始化完成")
    else:
        # 拉取最新
        run('git pull origin main --rebase', cwd=PUBLISH_DIR)

def copy_reports():
    """把报告文件和源码备份复制到发布目录"""
    # 复制所有报告 HTML
    for f in REPORTS_DIR.glob("koc_monitor_*.html"):
        shutil.copy2(f, PUBLISH_DIR / f.name)
    # 同步源码到 src/ 子目录（代码备份，不影响 GitHub Pages）
    src_dir = PUBLISH_DIR / "src"
    src_dir.mkdir(exist_ok=True)
    for py in ["koc_monitor.py", "koc_weekly_run.py", "koc_dashboard.py",
               "koc_publish.py", "koc_potential.py"]:
        src = BASE_DIR / py
        if src.exists():
            shutil.copy2(src, src_dir / py)

    # 生成首页 index.html（自动跳转到最新报告）
    reports = sorted((PUBLISH_DIR).glob("koc_monitor_*.html"), reverse=True)
    if reports:
        latest = reports[0].name
        cards  = ""
        for i, rpt in enumerate(reports[:14]):
            date = rpt.stem.replace("koc_monitor_", "")
            badge = '<span style="background:linear-gradient(135deg,#f0a500,#e84393);color:#000;font-size:9px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:8px">最新</span>' if i == 0 else ""
            cards += f'<a href="{rpt.name}" style="display:block;background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px 18px;margin-bottom:10px;color:#c9d1d9;text-decoration:none;font-size:14px">📋 {date} 监测报告{badge}</a>\n'

        index = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>牛牛圈 KOC 监测中心</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,'PingFang SC',sans-serif;padding:32px 24px;max-width:640px;margin:0 auto}}
h1{{font-size:20px;font-weight:700;margin-bottom:6px}}
p{{color:#555;font-size:12px;margin-bottom:24px}}
a:hover{{border-color:#30363d!important;background:#1a2030!important}}
</style>
</head>
<body>
<h1>📡 牛牛圈 KOC 监测中心</h1>
<p>每天 08:30 自动更新 · Powered by Claude AI</p>
{cards}
</body>
</html>"""
        (PUBLISH_DIR / "index.html").write_text(index, encoding="utf-8")

def push():
    """提交并推送到 GitHub"""
    run('git add -A', cwd=PUBLISH_DIR)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    run(f'git commit -m "report: auto update {now}"', cwd=PUBLISH_DIR)
    result = run('git push origin main', cwd=PUBLISH_DIR, capture=True)
    if result.returncode == 0:
        print(f"  ✅ 已发布到 GitHub Pages")
        print(f"  🌐 访问地址：{PAGES_URL}")
    else:
        print(f"  ⚠️  推送失败：{result.stderr}")
        print(f"  请检查 GitHub 授权（见下方说明）")
        return False
    return True

def main():
    print(f"\n{'='*55}")
    print(f"  牛牛圈 KOC · 发布到 GitHub Pages")
    print(f"{'='*55}\n")

    print("  [1/3] 初始化仓库...")
    setup_repo()

    print("  [2/3] 复制报告文件...")
    copy_reports()

    print("  [3/3] 推送到 GitHub...")
    ok = push()

    if ok:
        print(f"\n  同事访问地址（永久固定）：")
        print(f"  {PAGES_URL}")
    else:
        print(f"""
  首次推送需要 GitHub 授权，请按以下步骤操作：
  1. 打开：https://github.com/settings/tokens/new
  2. Note 填 kol-reports，勾选 repo 权限，点击生成
  3. 复制 token，在终端运行：
     git config --global credential.helper store
  4. 再次运行 python koc_publish.py
     （提示输入密码时粘贴 token）
""")

if __name__ == "__main__":
    main()
