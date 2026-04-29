# -*- coding: utf-8 -*-
"""
牛牛圈 潜力 KOC/KOL 挖掘
- 地毯式抓取近7天全部帖子
- 过滤：正文字数 > 200 字
- 排除官方账号
- 按发布时间倒序排列
用法：
  python koc_potential.py              # 默认近7天
  python koc_potential.py --days 3     # 近3天
  python koc_potential.py --min-chars 300  # 字数门槛300
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COOKIE_FILE = Path(__file__).parent / ".futu_cookies.json"
OUT_DIR     = Path(__file__).parent / "reports"
FEED_API    = "https://q.futunn.com/nnq/feed-list"

OFFICIAL_KEYWORDS = [
    "牛牛课堂", "搞活动的牛牛", "富途期权sir", "富途期权Sir",
    "富途牛牛", "富途证券", "富途活动", "富途官方", "Futu官方",
    "moomoo官方", "Moomoo官方", "牛牛活动", "牛牛官方",
    "富途投顾", "富途研究", "富途资讯", "富途新闻",
    "牛牛打新", "富途打新", "新股情报",
    "牛牛团队", "富途团队", "futu team", "moomoo team",
]

def is_official(author: str, identity: int = 0) -> bool:
    if identity == 3:
        return True
    au = author.lower()
    return any(kw.lower() in au for kw in OFFICIAL_KEYWORDS)

def load_cookies() -> str:
    if not COOKIE_FILE.exists():
        raise FileNotFoundError("Cookie 文件不存在，请先运行 futu_login.py")
    state = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    return "; ".join(
        f'{c["name"]}={c["value"]}'
        for c in state.get("cookies", [])
        if "futunn.com" in c.get("domain", "") and c.get("value")
    )

def api_get(url: str, cookie_str: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie":     cookie_str,
        "Referer":    "https://q.futunn.com/",
        "Accept":     "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def extract_text(summary: dict) -> str:
    rt = summary.get("rich_text", [])
    return " ".join(
        re.sub(r"<[^>]+>", "", x.get("text", ""))
        for x in rt if x.get("type") == 0 and x.get("text")
    ).strip()

def fetch_all_posts(cookie_str: str, days: int = 7, min_chars: int = 200) -> list:
    cutoff = datetime.now() - timedelta(days=days)
    posts, seen_ids, more_mark = [], set(), "CgIgAA=="
    page = 0

    print(f"  地毯式抓取近 {days} 天 | 字数门槛 ≥ {min_chars} 字")
    print(f"  时间范围：{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")

    while True:
        page += 1
        params = urllib.parse.urlencode({
            "type": 700, "num": 30,
            "load_list_type": 1, "more_mark": more_mark,
        })
        try:
            data = api_get(f"{FEED_API}?{params}", cookie_str)
        except Exception as e:
            print(f"\n  [API 错误 page={page}: {e}]")
            break

        feeds = data.get("feed", [])
        if not feeds:
            break

        out_of_range = 0
        new_count = 0
        for f in feeds:
            ts   = int(f.get("common", {}).get("timestamp", 0))
            dt   = datetime.fromtimestamp(ts) if ts else None
            if dt and dt < cutoff:
                out_of_range += 1
                continue

            fid = f.get("common", {}).get("feed_id", "")
            if fid in seen_ids:
                continue
            seen_ids.add(fid)

            user     = f.get("user_info", {})
            author   = user.get("nick_name", "")
            identity = int(user.get("identity", 0) or 0)

            if is_official(author, identity):
                continue

            summary = f.get("summary", {})
            text    = extract_text(summary)
            # 字数门槛
            char_count = len(text.replace(" ", ""))
            if char_count < min_chars:
                continue

            likes   = sum(x.get("liked_num", 0) for x in f.get("like", {}).get("like_summary", []))
            cmts    = int(f.get("comment", {}).get("comment_count", 0))
            shares  = int(f.get("forward", {}).get("forward_count", 0) or 0)
            fans    = int(user.get("fans_num", 0) or 0)

            # 提取图片
            imgs = []
            for x in summary.get("rich_text", []):
                if x.get("type") == 4 and x.get("pic"):
                    pic = x["pic"]
                    url = (
                        (pic.get("big_pic") or {}).get("url") or
                        (pic.get("mid_pic") or {}).get("url") or
                        (pic.get("thumb_pic") or {}).get("url") or ""
                    )
                    if url and url.startswith("http"):
                        imgs.append(url)

            posts.append({
                "ts":         ts,
                "dt":         dt.strftime("%Y-%m-%d %H:%M") if dt else "",
                "author":     author,
                "fans":       fans,
                "text":       text,           # 保留全文
                "char_count": char_count,
                "likes":      likes,
                "comments":   cmts,
                "shares":     shares,
                "engagement": likes + cmts + shares,
                "imgs":       imgs[:3],
                "feed_id":    fid,
                "url":        f'https://q.futunn.com/feed/{fid}',
                "uid":        user.get("user_id", ""),
                "identity":   identity,
            })
            new_count += 1

        print(f"  Page {page}: 新增 {new_count} 条 | 累计 {len(posts)} 条 | 超范围 {out_of_range}", end="\r")

        if out_of_range >= len(feeds) * 0.7:
            break
        if not data.get("has_more") or not data.get("more_mark"):
            break
        more_mark = data["more_mark"]
        time.sleep(0.25)

    print(f"\n  抓取完成：{len(posts)} 条符合条件帖子（字数≥{min_chars}，非官方，近{days}天）")
    posts.sort(key=lambda x: x["ts"], reverse=True)
    return posts

# ── 生成 HTML 报告 ───────────────────────────────────────────
def build_html(posts: list, days: int, min_chars: int, generated_at: str) -> str:
    def fans_fmt(n):
        if n >= 10000: return f"{n/10000:.1f}万"
        if n >= 1000:  return f"{n/1000:.1f}k"
        return str(n)

    def eng_color(eng):
        if eng >= 200: return "#f0a500"
        if eng >= 50:  return "#16a34a"
        return "#555"

    cards_html = ""
    for p in posts:
        text_preview = p["text"][:500] + ("…" if len(p["text"]) > 500 else "")
        text_full    = p["text"].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

        imgs_html = ""
        for img in p["imgs"][:2]:
            imgs_html += f'<img src="{img}" style="width:80px;height:60px;object-fit:cover;border-radius:4px;margin-right:4px;flex-shrink:0" onerror="this.style.display=\'none\'">'

        tags_html = ""
        if p["char_count"] >= 500:
            tags_html += '<span style="background:#7c3aed20;color:#a78bfa;border:1px solid #7c3aed40;border-radius:10px;padding:1px 7px;font-size:10px;margin-right:3px">长文</span>'
        if p["engagement"] >= 100:
            tags_html += '<span style="background:#f0a50020;color:#f0a500;border:1px solid #f0a50040;border-radius:10px;padding:1px 7px;font-size:10px;margin-right:3px">高互动</span>'
        if p["fans"] >= 10000:
            tags_html += '<span style="background:#2563eb20;color:#60a5fa;border:1px solid #2563eb40;border-radius:10px;padding:1px 7px;font-size:10px;margin-right:3px">万粉</span>'
        if p["imgs"]:
            tags_html += '<span style="background:#16a34a20;color:#4ade80;border:1px solid #16a34a40;border-radius:10px;padding:1px 7px;font-size:10px">有图</span>'

        cards_html += f'''
<div class="post-card" style="background:#161b22;border:1px solid #21262d;border-radius:10px;padding:16px;margin-bottom:12px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;flex-wrap:wrap;gap:6px">
    <div style="display:flex;align-items:center;gap:8px">
      <div style="width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;flex-shrink:0">{p["author"][:1] if p["author"] else "?"}</div>
      <div>
        <div style="color:#e6e6e6;font-weight:600;font-size:13px">{p["author"]}</div>
        <div style="color:#555;font-size:11px">粉丝 {fans_fmt(p["fans"])} · {p["char_count"]} 字</div>
      </div>
    </div>
    <div style="text-align:right">
      <div style="color:#555;font-size:11px">{p["dt"]}</div>
      <div style="margin-top:2px">{tags_html}</div>
    </div>
  </div>

  <div style="color:#c9d1d9;font-size:13px;line-height:1.7;margin-bottom:10px;white-space:pre-wrap" class="post-text">{text_preview}</div>

  {"" if not p["imgs"] else f'<div style="display:flex;margin-bottom:10px">{imgs_html}</div>'}

  <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid #21262d;padding-top:8px">
    <div style="display:flex;gap:14px;font-size:11px">
      <span style="color:#e84393">♥ {p["likes"]}</span>
      <span style="color:#8b949e">💬 {p["comments"]}</span>
      <span style="color:#8b949e">↗ {p["shares"]}</span>
      <span style="color:{eng_color(p["engagement"])};font-weight:600">互动 {p["engagement"]}</span>
    </div>
    <a href="{p["url"]}" target="_blank" style="font-size:11px;color:#58a6ff;text-decoration:none">查看原帖 →</a>
  </div>
</div>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>潜力 KOC 挖掘 · {generated_at[:10]}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding-bottom:40px}}
a{{text-decoration:none;color:inherit}}
#search{{width:100%;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 12px;color:#c9d1d9;font-size:13px;outline:none;margin-bottom:12px}}
#search:focus{{border-color:#7c3aed}}
.post-card{{transition:border-color .15s}}
.post-card:hover{{border-color:#7c3aed88!important}}
.hidden{{display:none!important}}
</style>
</head>
<body>
<div style="background:#161b22;border-bottom:1px solid #21262d;padding:14px 28px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100">
  <div style="display:flex;align-items:center;gap:12px">
    <div style="width:34px;height:34px;background:linear-gradient(135deg,#7c3aed,#2563eb);border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px">🔍</div>
    <div>
      <div style="color:#e6e6e6;font-weight:700;font-size:15px">潜力 KOC/KOL 挖掘</div>
      <div style="color:#555;font-size:11px">近 {days} 天 · 字数≥{min_chars} · 排除官方 · 共 {len(posts)} 篇 · 按发布时间倒序</div>
    </div>
  </div>
  <div style="text-align:right;font-size:11px;color:#555">生成于 {generated_at}</div>
</div>

<div style="max-width:860px;margin:24px auto;padding:0 20px">
  <input id="search" placeholder="搜索作者名 / 关键词..." oninput="filterPosts(this.value)">

  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px" id="filters">
    <button onclick="setFilter('all')" class="fbtn active" data-f="all">全部 ({len(posts)})</button>
    <button onclick="setFilter('long')" class="fbtn" data-f="long">长文 500+字</button>
    <button onclick="setFilter('hot')" class="fbtn" data-f="hot">高互动 100+</button>
    <button onclick="setFilter('fans')" class="fbtn" data-f="fans">万粉以上</button>
  </div>

  <div id="posts-container">
    {cards_html if cards_html else '<div style="text-align:center;color:#555;padding:60px">本时段暂无符合条件的内容</div>'}
  </div>
</div>

<div style="text-align:center;color:#444;font-size:11px;border-top:1px solid #21262d;padding:16px">
  潜力 KOC 挖掘 · 字数≥{min_chars}字 · 排除官方账号 · 不构成投资建议 · {generated_at}
</div>

<style>
.fbtn{{background:#161b22;border:1px solid #30363d;border-radius:20px;padding:4px 14px;color:#8b949e;font-size:12px;cursor:pointer}}
.fbtn.active{{background:#7c3aed30;border-color:#7c3aed;color:#a78bfa}}
</style>
<script>
const posts = document.querySelectorAll('.post-card');
let currentFilter = 'all';
let currentSearch = '';

function filterPosts(q) {{
  currentSearch = q.toLowerCase();
  applyFilters();
}}
function setFilter(f) {{
  currentFilter = f;
  document.querySelectorAll('.fbtn').forEach(b => b.classList.toggle('active', b.dataset.f === f));
  applyFilters();
}}
function applyFilters() {{
  posts.forEach(card => {{
    const text = card.innerText.toLowerCase();
    const matchSearch = !currentSearch || text.includes(currentSearch);
    let matchFilter = true;
    if (currentFilter === 'long')  matchFilter = card.querySelector('.post-text')?.textContent.trim().length >= 300;
    if (currentFilter === 'hot')   matchFilter = text.includes('互动') && parseInt(card.querySelector('[style*="互动"]')?.textContent.replace(/\D/g,'') || 0) >= 100;
    if (currentFilter === 'fans')  matchFilter = text.includes('万粉');
    card.classList.toggle('hidden', !(matchSearch && matchFilter));
  }});
}}
</script>
</body>
</html>'''

# ── 主流程 ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",      type=int, default=7,   help="抓取最近N天（默认7）")
    parser.add_argument("--min-chars", type=int, default=200, help="最少字数（默认200）")
    parser.add_argument("--no-browser",action="store_true",   help="不打开浏览器")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*55}")
    print(f"  潜力 KOC/KOL 挖掘  |  {now_str}")
    print(f"  字数门槛：≥ {args.min_chars} 字  |  时间范围：近 {args.days} 天")
    print(f"{'='*55}\n")

    try:
        cookie_str = load_cookies()
        print(f"Cookie 已加载（{cookie_str.count(';')+1} 个）\n")
    except FileNotFoundError as e:
        print(f"错误：{e}")
        return

    posts = fetch_all_posts(cookie_str, days=args.days, min_chars=args.min_chars)

    html = build_html(posts, args.days, args.min_chars, now_str)
    out_file = OUT_DIR / f"koc_potential_{datetime.now().strftime('%Y-%m-%d')}.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"\n报告已生成：{out_file}")
    print(f"共收录 {len(posts)} 篇潜力内容\n")

    if not args.no_browser:
        webbrowser.open(f"file:///{str(out_file).replace(chr(92), '/')}")

if __name__ == "__main__":
    main()
