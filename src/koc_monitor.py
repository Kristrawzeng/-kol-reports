# -*- coding: utf-8 -*-
"""
牛牛圈 KOC/KOL 潜力挖掘 + 大额晒单监测 v3
直接用 Cookie 调用 Futu API，无需 Playwright 浏览器

维度1：近7天互动量（点赞+转发+评论）50+ 的潜力用户
维度2：大额晒单（港股>20万HKD / 美股>5万USD）
维度3：买卖打点图（无金额门槛）

用法：
  python koc_monitor.py            # 抓近7天数据
  python koc_monitor.py --max 1000 # 最多抓1000条（默认1000）
"""
import argparse, base64, json, os, re, sys, time, urllib.request, urllib.parse
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COOKIE_FILE = Path(__file__).parent / ".futu_cookies.json"
OUT_DIR     = Path(__file__).parent / "reports"
IMG_DIR     = OUT_DIR / "trade_imgs"
DB_FILE     = OUT_DIR / "creator_db.json"
API_KEY     = os.environ.get("ANTHROPIC_API_KEY", "user-key-5kAHiMi7WOwvsoBb")

FEED_API    = "https://q.futunn.com/nnq/feed-list"

# ── 官方账号黑名单 ────────────────────────────────────────────
OFFICIAL_KEYWORDS = [
    "牛牛课堂", "搞活动的牛牛", "富途期权sir", "富途期权Sir",
    "富途牛牛", "富途证券", "富途活动", "富途官方", "Futu官方",
    "moomoo官方", "Moomoo官方", "牛牛活动", "牛牛官方",
    "富途投顾", "富途研究", "富途资讯", "富途新闻",
    "牛牛打新", "富途打新", "新股情报",
    "牛牛团队", "富途团队", "futu team", "moomoo team",
]

def is_official_account(author: str, identity: int = 0) -> bool:
    if identity == 3:
        return True
    a = author.lower()
    for kw in OFFICIAL_KEYWORDS:
        if kw.lower() in a:
            return True
    return False

# ── 近7天 T-7 ────────────────────────────────────────────────
def week_range():
    today = datetime.now()
    start = today - timedelta(days=7)
    return start.replace(hour=0,minute=0,second=0), today.replace(hour=23,minute=59,second=59)

WEEK_START, WEEK_END = week_range()

# ── Cookie 加载 ──────────────────────────────────────────────
def load_cookies() -> str:
    if not COOKIE_FILE.exists():
        raise FileNotFoundError("Cookie 文件不存在，请先运行 futu_login.py 完成登录")
    state = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    cookies = state.get("cookies", [])
    return "; ".join(
        f'{c["name"]}={c["value"]}'
        for c in cookies
        if "futunn.com" in c.get("domain", "") and c.get("value")
    )

# ── API 请求 ──────────────────────────────────────────────────
def api_get(url: str, cookie_str: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie":      cookie_str,
        "Referer":     "https://q.futunn.com/",
        "Accept":      "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# ── 解析单条 Feed ─────────────────────────────────────────────
def parse_feed(f: dict) -> dict:
    common   = f.get("common", {})
    user     = f.get("user_info", {})
    like_sum = f.get("like", {}).get("like_summary", [])
    cmt      = f.get("comment", {})
    summary  = f.get("summary", {})
    rt       = summary.get("rich_text", [])

    feed_id = str(common.get("feed_id", ""))
    ts      = int(common.get("timestamp", 0))
    likes   = sum(x.get("liked_num", 0) for x in like_sum)
    cmts    = int(cmt.get("comment_count", 0))
    shares  = int(common.get("share_count", 0))
    total   = likes + cmts + shares

    text = " ".join(
        re.sub(r"<[^>]+>", "", x.get("text", ""))
        for x in rt if x.get("type") == 0 and x.get("text")
    ).strip()
    char_count = len(text.replace(" ", ""))

    imgs = []
    for x in rt:
        if x.get("type") == 4 and x.get("pic"):
            pic = x["pic"]
            url = (
                (pic.get("big_pic") or {}).get("url")
                or (pic.get("mid_pic") or {}).get("url")
                or (pic.get("thumb_pic") or {}).get("url")
                or ""
            )
            if url and url.startswith("http"):
                imgs.append(url)

    return {
        "feed_id":          feed_id,
        "url":              f"https://q.futunn.com/feed/{feed_id}",
        "ts":               ts,
        "date":             datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "",
        "author":           user.get("nick_name", ""),
        "author_id":        str(user.get("user_id", "")),
        "identity":         int(user.get("identity", 0)),
        "fans_num":         int(user.get("fans_num", 0) or 0),
        "follow_num":       int(user.get("follow_num", 0) or 0),
        "likes":            likes,
        "comments":         cmts,
        "shares":           shares,
        "total_engagement": total,
        "text":             text[:800],
        "char_count":       char_count,
        "imgs":             imgs[:4],
        "is_trade":         bool(imgs),
    }

# ── 拉取帖子 ─────────────────────────────────────────────────
def fetch_feeds(cookie_str: str, max_posts: int = 1000) -> list:
    posts = []
    seen_ids = set()
    more_mark = "CgIgAA=="
    page = 0
    stop_reason = ""

    print(f"  时间范围：{WEEK_START.strftime('%Y-%m-%d')} ~ {WEEK_END.strftime('%Y-%m-%d')}")

    while len(posts) < max_posts:
        page += 1
        params = urllib.parse.urlencode({
            "type": 700,
            "num":  30,
            "load_list_type": 1,
            "more_mark": more_mark,
        })
        url = f"{FEED_API}?{params}"

        try:
            data = api_get(url, cookie_str)
        except Exception as e:
            print(f"\n  [API 请求失败 page={page}: {e}]")
            break

        feeds_raw = data.get("feed", [])
        if not feeds_raw:
            stop_reason = "no more feeds"
            break

        out_of_week = 0
        for f in feeds_raw:
            item = parse_feed(f)
            ts   = item["ts"]
            dt   = datetime.fromtimestamp(ts) if ts else None

            if dt and dt < WEEK_START:
                out_of_week += 1
            else:
                fid = item["feed_id"]
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    posts.append(item)

        print(f"  Page {page}: +{len(feeds_raw)} 条 (本周累计 {len(posts)}, 超出本周 {out_of_week})", end="\r")

        if out_of_week >= len(feeds_raw) * 0.8:
            stop_reason = "mostly out of week range"
            break

        has_more = data.get("has_more", 0)
        more_mark = data.get("more_mark", "")
        if not has_more or not more_mark:
            stop_reason = "no more pages"
            break

        time.sleep(0.4)

    print(f"\n  拉取完成：共 {len(posts)} 条 ({stop_reason or 'max reached'})")
    return posts

# ── 图片媒体类型检测 ──────────────────────────────────────────
def detect_media_type(data: bytes) -> str:
    if data[:4] == b'\x89PNG':
        return "image/png"
    if len(data) > 11 and data[8:12] == b'WEBP':
        return "image/webp"
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    return "image/jpeg"

# ── 图片下载（多策略，带/不带 Cookie 双重尝试）────────────────
_COOKIE_CACHE = ""

def download_img(url: str, path: str, verbose: bool = False) -> bool:
    # 如果已缓存，直接复用
    if Path(path).exists() and Path(path).stat().st_size > 500:
        return True

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://q.futunn.com/",
        "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # 候选 URL：原始 → 去掉 /big /mid /thumb 后缀 → 去掉 query 参数
    candidates = [url]
    for suffix in ("/big", "/mid", "/thumb"):
        if suffix + "?" in url:
            candidates.append(url.replace(suffix + "?", "?"))
        elif url.endswith(suffix):
            candidates.append(url[:-len(suffix)])
    if "?" in url:
        candidates.append(url.split("?")[0])

    last_err = ""
    # 每个 URL 先用 Cookie，再不用 Cookie
    for try_url in candidates:
        for use_cookie in ([True, False] if _COOKIE_CACHE else [False]):
            headers = dict(base_headers)
            if use_cookie:
                headers["Cookie"] = _COOKIE_CACHE
            try:
                req = urllib.request.Request(try_url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as r:
                    status = r.getcode()
                    data = r.read()
                if len(data) < 500:
                    last_err = f"too small ({len(data)}B)"
                    continue
                # 简单校验是否为图片（magic bytes 或大文件）
                is_img = (
                    data[:3] == b'\xff\xd8\xff'  # JPEG
                    or data[:4] == b'\x89PNG'     # PNG
                    or data[:4] == b'RIFF'        # WebP
                    or data[:6] in (b'GIF87a', b'GIF89a')
                    or len(data) > 5000           # 足够大就接受
                )
                if is_img:
                    Path(path).write_bytes(data)
                    return True
                else:
                    last_err = f"not image magic (HTTP {status}, {len(data)}B, head={data[:16]})"
            except Exception as e:
                last_err = str(e)
                continue
    if verbose:
        print(f"    ⚠️  下载失败: {url[-60:]} | {last_err}")
    return False

# ── Claude Vision 晒单分析 ───────────────────────────────────
def analyze_trade_image(img_path: str) -> dict:
    _FALLBACK = {
        "is_trade": False, "is_signal_chart": False,
        "market": None, "amount": None,
        "currency": None, "return_rate": None, "summary": "分析失败",
    }
    try:
        import anthropic
        with open(img_path, "rb") as f:
            raw = f.read()
        b64   = base64.standard_b64encode(raw).decode()
        media = detect_media_type(raw)

        client = anthropic.Anthropic(api_key=API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                {"type": "text", "text": """分析这张图片，判断属于以下哪种类型：

A. 【持仓/盈亏晒单】：显示个人账户的当前持仓市值、持仓盈亏金额、当日/当月盈亏金额。
   注意：仅限"我今天赚了多少"/"我持仓盈亏多少"类截图。
   以下不算A类：累计历史交易额/成交量里程碑（如"累计成交额6800万"）、单笔买卖委托通知（无盈亏显示）
B. 【买卖打点图】：K线图上标注了个人买入(B/买/↑)或卖出(S/卖/↓)的打点记录，有或没有金额均可
C. 【非晒单】：纯行情K线图、市场指数走势、股票市值、ETF市场成交额、技术分析图表、新闻资讯、公司公告、累计交易额勋章等

提取字段：
- is_trade: A或B为true，C为false
- is_signal_chart: B类打点图为true，其他为false
- market: HK / US / OTHER（无法判断填OTHER）
- amount: 仅A类，个人持仓市值或盈亏金额（纯数字，换算好，"20万"→200000，必须是盈亏/持仓值而非成交额）；B/C类填null
- currency: HKD / USD / null
- return_rate: 个人收益率百分比数字（如+221%填221），无则null
- summary: 一句话描述

只返回JSON：
{"is_trade":true/false,"is_signal_chart":true/false,"market":"HK/US/OTHER","amount":数字或null,"currency":"HKD/USD/null","return_rate":数字或null,"summary":"一句话"}"""}
            ]}]
        )
        text = msg.content[0].text.strip()
        s, e = text.find("{"), text.rfind("}") + 1
        if s >= 0 and e > s:
            result = json.loads(text[s:e])
            # 确保必要字段存在
            result.setdefault("is_signal_chart", False)
            result.setdefault("return_rate", None)
            return result
    except Exception as ex:
        print(f"  [Vision 分析异常: {ex}]")
    return _FALLBACK

def is_large_trade(v: dict) -> bool:
    """晒单门槛：港股≥3万HKD / 美股≥5千USD / 收益率≥50%"""
    if not v.get("is_trade"): return False
    market, currency = v.get("market",""), v.get("currency","")
    try:
        amt = float(str(v.get("amount") or 0).replace(",",""))
    except Exception:
        amt = 0
    try:
        rr = float(str(v.get("return_rate") or 0).replace(",","").replace("%",""))
    except Exception:
        rr = 0
    if rr >= 50: return True
    if market == "HK" or currency == "HKD": return amt >= 30_000
    if market == "US" or currency == "USD": return amt >= 5_000
    # 无法识别市场但有金额，也纳入
    if amt >= 30_000: return True
    return False

# ── 用户标签推断 ──────────────────────────────────────────────
def infer_tags(text: str, vision: dict = None) -> list:
    tags = []
    t = (text or "").lower()
    v = vision or {}
    market = v.get("market", "")

    if market == "HK" or any(k in t for k in ["港股", "恒生", "港元", "hkd"]):
        tags.append("港股")
    if market == "US" or any(k in t for k in ["美股", "纳指", "标普", "usd", "标普500"]):
        tags.append("美股")
    if any(k in t for k in ["a股", "沪深", "创业板", "科创板", "沪市", "深市"]):
        tags.append("A股")
    if any(k in t for k in ["期权", "option", "call", "put", "认购", "认沽", "行权"]):
        tags.append("期权")
    if any(k in t for k in ["期货", "futures", "合约", "主力", "原油", "黄金"]):
        tags.append("期货")
    if "etf" in t:
        tags.append("ETF")
    if any(k in t for k in ["短线", "日内", "当日", "t+0", "超短"]):
        tags.append("短线")
    elif any(k in t for k in ["长线", "价值投资", "长期持有", "定投"]):
        tags.append("长线")
    if v.get("is_signal_chart"):
        tags.append("打点图")
    rr = v.get("return_rate")
    try:
        if rr is not None and float(str(rr)) >= 100:
            tags.append("高收益")
    except Exception:
        pass
    return list(dict.fromkeys(tags))[:5]  # 去重，最多5个

# ── 创作者评分 ────────────────────────────────────────────────
def calc_koc_score(post: dict, vision: dict = None) -> int:
    eng = post.get("total_engagement", 0)
    v   = vision or {}

    # 互动分（0-40）
    score = min(40, eng * 40 // max(eng + 100, 1))

    # 内容质量分（0-40）
    if v.get("is_signal_chart"):
        score += 35                    # 买卖打点图价值最高
    elif v.get("is_trade"):
        amt = 0
        try: amt = float(str(v.get("amount") or 0).replace(",", ""))
        except: pass
        rr = 0
        try: rr = float(str(v.get("return_rate") or 0).replace(",", "").replace("%", ""))
        except: pass
        cur = v.get("currency", "")
        if   cur == "HKD": score += min(20, int(amt / 20000))
        elif cur == "USD": score += min(20, int(amt / 5000))
        if   rr >= 200: score += 20
        elif rr >= 100: score += 12
        elif rr >= 50:  score += 6

    # 粉丝影响力分（0-10）
    fans = post.get("fans_num", 0)
    if   fans >= 10000: score += 10
    elif fans >= 1000:  score += 6
    elif fans >= 100:   score += 3

    # 互动质量（0-10）
    if post.get("comments", 0) >= 20: score += 5
    elif post.get("comments", 0) >= 10: score += 2
    if post.get("shares", 0) >= 10: score += 5
    elif post.get("shares", 0) >= 5: score += 2

    return min(100, score)

# ── HTML 报告 ─────────────────────────────────────────────────
def build_report(koc_list, trades, signal_charts, week_start, week_end, total_scanned, potential_posts=None):
    gen_time   = datetime.now().strftime("%Y-%m-%d %H:%M")
    week_label = f"{week_start.strftime('%m/%d')} ~ {week_end.strftime('%m/%d')}"

    TAG_COLORS = {
        "港股":  ("#dbeafe", "#1d4ed8"),
        "美股":  ("#e0f2fe", "#0369a1"),
        "A股":   ("#fee2e2", "#dc2626"),
        "期权":  ("#ede9fe", "#7c3aed"),
        "期货":  ("#fef3c7", "#d97706"),
        "ETF":   ("#d1fae5", "#059669"),
        "短线":  ("#fce7f3", "#db2777"),
        "长线":  ("#dcfce7", "#16a34a"),
        "打点图":("#dbeafe", "#2563eb"),
        "高收益":("#fef9c3", "#ca8a04"),
    }

    def tag_html(tags: list) -> str:
        out = ""
        for tg in tags:
            bg, fg = TAG_COLORS.get(tg, ("#f1f5f9", "#64748b"))
            out += f'<span style="background:{bg};color:{fg};font-size:9px;font-weight:700;padding:1px 6px;border-radius:10px;margin-right:3px;">{tg}</span>'
        return out

    def score_badge(score: int) -> str:
        if score >= 80:   c, bg = "#d97706", "#fef3c7"
        elif score >= 60: c, bg = "#dc2626", "#fee2e2"
        elif score >= 40: c, bg = "#7c3aed", "#ede9fe"
        else:             c, bg = "#64748b", "#f1f5f9"
        return f'<span style="background:{bg};color:{c};font-size:9px;font-weight:800;padding:2px 7px;border-radius:10px;">★ {score}</span>'

    def fans_html(fans: int) -> str:
        if fans <= 0: return ""
        if fans >= 10000: s = f"{fans/10000:.1f}万"
        elif fans >= 1000: s = f"{fans/1000:.1f}k"
        else: s = str(fans)
        return f'<span style="color:#94a3b8;font-size:10px;margin-left:6px;">👥 {s}</span>'

    def koc_cards():
        if not koc_list:
            return '<div class="empty">本周暂未发现互动量≥50的内容<br><small>可尝试增大 --max 参数</small></div>'
        html = '<div class="koc-grid">'
        for i, p in enumerate(koc_list[:40]):
            url    = p.get("url","#")
            title  = p.get("text","")[:55] or "（无文字内容）"
            auth   = p.get("author","") or "未知"
            total  = p.get("total_engagement",0)
            likes  = p.get("likes",0)
            cmts   = p.get("comments",0)
            shares = p.get("shares",0)
            date   = p.get("date","")
            fans   = p.get("fans_num",0)
            tags   = p.get("tags",[])
            score  = p.get("score",0)
            bar    = min(total/5, 100)
            html += f"""
            <a href="{url}" target="_blank" class="koc-card">
              <div class="kc-top">
                <span class="kc-rank">#{i+1}</span>
                <div style="display:flex;align-items:center;gap:4px;">
                  {score_badge(score)}
                  <span class="kc-date">{date}</span>
                </div>
              </div>
              <div class="kc-author">👤 {auth}{fans_html(fans)}</div>
              <div style="margin-bottom:6px;">{tag_html(tags)}</div>
              <div class="kc-text">{title}</div>
              <div class="kc-metrics">
                <span class="m-total">🔥 {total}</span>
                <span class="m-like">👍 {likes}</span>
                <span class="m-cmt">💬 {cmts}</span>
                <span class="m-share">↗️ {shares}</span>
              </div>
              <div class="eng-bar"><div style="width:{bar:.0f}%;background:linear-gradient(90deg,#e84393,#7c3aed);height:3px;border-radius:2px"></div></div>
            </a>"""
        html += "</div>"
        return html

    def trade_cards():
        if not trades:
            return '<div class="empty">本周暂未检测到符合条件的大额晒单<br><small>港股>3万HKD / 美股>5千USD / 收益率≥50%</small></div>'
        html = '<div class="trade-grid">'
        for i, t in enumerate(trades):
            url    = t.get("url","#")
            auth   = t.get("author","")
            date   = t.get("date","")
            fans   = t.get("fans_num",0)
            tags   = t.get("tags",[])
            score  = t.get("score",0)
            v      = t.get("vision",{})
            market = v.get("market","?")
            amt    = v.get("amount",0)
            cur    = v.get("currency","")
            rr     = v.get("return_rate")
            summ   = v.get("summary","")
            raw_b64 = t.get("img_b64","")
            media   = t.get("img_media","image/jpeg")
            mkt     = "🇭🇰 港股" if market=="HK" else ("🇺🇸 美股" if market=="US" else "📊 股票")
            amt_s   = f"{float(str(amt).replace(',','')):,.0f} {cur}" if amt else "待核实"
            rr_s    = f"  📈 {float(str(rr)):.0f}%" if rr else ""
            img_tag = f'<img src="data:{media};base64,{raw_b64}" class="trade-img">' if raw_b64 else '<div class="trade-noimg">图片加载失败</div>'
            html += f"""
            <div class="trade-card">
              <div class="tc-header">
                <span class="tc-rank">#{i+1}</span>
                <span class="tc-mkt">{mkt}</span>
                <span class="tc-amt">💰 {amt_s}{rr_s}</span>
                {score_badge(score)}
              </div>
              {img_tag}
              <div class="tc-body">
                <div class="tc-author">👤 {auth}{fans_html(fans)} · {date}</div>
                <div style="margin:4px 0;">{tag_html(tags)}</div>
                <div class="tc-summ">{summ}</div>
                <a href="{url}" target="_blank" class="tc-link">🔗 查看原帖 →</a>
              </div>
            </div>"""
        html += "</div>"
        return html

    def signal_cards():
        if not signal_charts:
            return '<div class="empty">本周暂未检测到买卖打点图</div>'
        html = '<div class="trade-grid">'
        for i, t in enumerate(signal_charts[:40]):
            url     = t.get("url","#")
            auth    = t.get("author","")
            date    = t.get("date","")
            fans    = t.get("fans_num",0)
            tags    = t.get("tags",[])
            score   = t.get("score",0)
            v       = t.get("vision",{})
            summ    = v.get("summary","")
            raw_b64 = t.get("img_b64","")
            media   = t.get("img_media","image/jpeg")
            mkt     = "🇭🇰 港股" if v.get("market")=="HK" else ("🇺🇸 美股" if v.get("market")=="US" else "📊 股票")
            img_tag = f'<img src="data:{media};base64,{raw_b64}" class="trade-img">' if raw_b64 else '<div class="trade-noimg">图片加载失败</div>'
            html += f"""
            <div class="trade-card" style="border-color:#bfdbfe">
              <div class="tc-header" style="background:#f0f7ff">
                <span class="tc-rank">#{i+1}</span>
                <span class="tc-mkt">📍 {mkt}</span>
                <span style="color:#2563eb;font-size:12px;font-weight:700;margin-left:auto">打点图</span>
                {score_badge(score)}
              </div>
              {img_tag}
              <div class="tc-body">
                <div class="tc-author">👤 {auth}{fans_html(fans)} · {date}</div>
                <div style="margin:4px 0;">{tag_html(tags)}</div>
                <div class="tc-summ">{summ}</div>
                <a href="{url}" target="_blank" class="tc-link">🔗 查看原帖 →</a>
              </div>
            </div>"""
        html += "</div>"
        return html

    def potential_cards():
        posts = potential_posts or []
        if not posts:
            return '<div style="background:#f0f7ff;border:1px solid #bfdbfe;border-radius:12px;padding:40px;text-align:center;color:#94a3b8;font-size:14px">本周暂未发现字数≥200的优质内容</div>'
        html = ""

        def eng_color(eng):
            if eng >= 200: return "#d97706"
            if eng >= 50:  return "#16a34a"
            return "#94a3b8"

        def fans_fmt(n):
            if n >= 10000: return f"{n/10000:.1f}万"
            if n >= 1000:  return f"{n/1000:.1f}k"
            return str(n)

        for p in posts[:100]:
            auth     = p.get("author", "") or "未知"
            date     = p.get("date", "")
            fans     = p.get("fans_num", 0)
            text     = p.get("text", "")
            cc       = p.get("char_count", 0)
            likes    = p.get("likes", 0)
            cmts     = p.get("comments", 0)
            shares   = p.get("shares", 0)
            eng      = likes + cmts + shares
            url      = p.get("url", "#")
            preview  = text[:400] + ("…" if len(text) > 400 else "")

            tag_badges = ""
            if cc >= 500:
                tag_badges += '<span style="background:#ede9fe;color:#7c3aed;border:1px solid #ddd6fe;border-radius:10px;padding:1px 8px;font-size:10px;font-weight:600;margin-right:3px">长文</span>'
            if eng >= 100:
                tag_badges += '<span style="background:#fef3c7;color:#d97706;border:1px solid #fde68a;border-radius:10px;padding:1px 8px;font-size:10px;font-weight:600;margin-right:3px">高互动</span>'
            if fans >= 10000:
                tag_badges += '<span style="background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:10px;padding:1px 8px;font-size:10px;font-weight:600">万粉</span>'

            html += f"""
            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:10px;transition:.18s;box-shadow:0 1px 4px #0000000a" onmouseover="this.style.borderColor='#93c5fd';this.style.boxShadow='0 4px 12px #2563eb18'" onmouseout="this.style.borderColor='#e2e8f0';this.style.boxShadow='0 1px 4px #0000000a'">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;flex-wrap:wrap;gap:6px">
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#6366f1);display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;flex-shrink:0">{auth[:1] if auth else "?"}</div>
                  <div>
                    <div style="color:#1e293b;font-weight:600;font-size:13px">{auth}</div>
                    <div style="color:#94a3b8;font-size:11px">粉丝 {fans_fmt(fans)} · {cc} 字</div>
                  </div>
                </div>
                <div style="text-align:right">
                  <div style="color:#94a3b8;font-size:11px">{date}</div>
                  <div style="margin-top:3px">{tag_badges}</div>
                </div>
              </div>
              <div style="color:#334155;font-size:13px;line-height:1.75;margin-bottom:10px;white-space:pre-wrap">{preview}</div>
              <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid #f1f5f9;padding-top:8px">
                <div style="display:flex;gap:14px;font-size:11px">
                  <span style="color:#ef4444">♥ {likes}</span>
                  <span style="color:#64748b">💬 {cmts}</span>
                  <span style="color:#64748b">↗ {shares}</span>
                  <span style="color:{eng_color(eng)};font-weight:600">互动 {eng}</span>
                </div>
                <a href="{url}" target="_blank" style="font-size:11px;color:#2563eb;font-weight:500;padding:3px 10px;border:1px solid #bfdbfe;border-radius:6px;background:#eff6ff">查看原帖 →</a>
              </div>
            </div>"""
        return html

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>牛牛圈 KOC 监测周报 · {week_label}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f0f4f8;color:#1e293b;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif}}
a{{text-decoration:none;color:inherit}}
.nav{{background:#ffffff;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 6px #2563eb10;padding:14px 32px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}}
.page{{max-width:1280px;margin:0 auto;padding:28px 24px}}
.sec{{margin-bottom:44px}}
.sec-hdr{{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
.sec-lbl{{color:#3b82f6;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase}}
.badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}}
.stat-row{{display:flex;gap:14px;margin-bottom:28px;flex-wrap:wrap}}
.stat-pill{{background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 20px;flex:1;min-width:120px;text-align:center;box-shadow:0 1px 4px #0000000a}}
.sp-n{{font-size:24px;font-weight:700}}.sp-l{{color:#94a3b8;font-size:11px;margin-top:3px}}
.koc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.koc-card{{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;transition:.2s;display:block;position:relative;overflow:hidden;box-shadow:0 1px 4px #0000000a}}
.koc-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#3b82f6,#6366f1)}}
.koc-card:hover{{border-color:#93c5fd;box-shadow:0 4px 16px #2563eb15}}
.kc-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.kc-rank{{color:#cbd5e1;font-size:16px;font-weight:800}}
.kc-date{{color:#94a3b8;font-size:11px}}
.kc-author{{color:#2563eb;font-size:12px;margin-bottom:6px;display:flex;align-items:center}}
.kc-text{{color:#334155;font-size:13px;line-height:1.5;margin-bottom:8px}}
.kc-metrics{{display:flex;gap:8px;font-size:11px;font-weight:600;margin-bottom:6px}}
.m-total{{color:#d97706}}.m-like{{color:#ef4444}}.m-cmt{{color:#16a34a}}.m-share{{color:#7c3aed}}
.eng-bar{{background:#f1f5f9;border-radius:2px;height:3px}}
.trade-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}}
.trade-card{{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;transition:.2s;box-shadow:0 1px 4px #0000000a}}
.trade-card:hover{{border-color:#93c5fd;box-shadow:0 4px 16px #2563eb15}}
.tc-header{{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid #f1f5f9;flex-wrap:wrap}}
.tc-rank{{color:#cbd5e1;font-size:15px;font-weight:800}}
.tc-mkt{{font-size:12px;font-weight:600;padding:2px 8px;background:#f0f7ff;color:#2563eb;border:1px solid #bfdbfe;border-radius:10px}}
.tc-amt{{color:#d97706;font-size:13px;font-weight:700;margin-left:auto}}
.trade-img{{width:100%;max-height:260px;object-fit:contain;display:block;background:#f8fafc}}
.trade-noimg{{width:100%;height:120px;background:#f1f5f9;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px}}
.tc-body{{padding:12px 16px}}
.tc-author{{color:#2563eb;font-size:12px;margin-bottom:4px;display:flex;align-items:center}}
.tc-summ{{color:#64748b;font-size:12px;line-height:1.5;margin-bottom:10px}}
.tc-link{{display:inline-block;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font-size:11px;font-weight:700;padding:5px 14px;border-radius:6px}}
.empty{{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:40px;text-align:center;color:#94a3b8;font-size:14px;line-height:2}}
.footer{{border-top:1px solid #e2e8f0;padding:20px;text-align:center;color:#94a3b8;font-size:11px;background:#fff}}
::-webkit-scrollbar{{width:6px}}::-webkit-scrollbar-track{{background:#f0f4f8}}::-webkit-scrollbar-thumb{{background:#bfdbfe;border-radius:3px}}
</style>
</head>
<body>
<div class="nav">
  <div style="display:flex;align-items:center;gap:12px">
    <div style="width:34px;height:34px;background:linear-gradient(135deg,#2563eb,#3b82f6);border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px">📡</div>
    <div>
      <div style="color:#1e293b;font-weight:700;font-size:15px">牛牛圈 KOC 周度监测报告</div>
      <div style="color:#94a3b8;font-size:11px">近7天 {week_label} · 共扫描 {total_scanned} 条内容</div>
    </div>
  </div>
  <div style="text-align:right;font-size:12px;color:#94a3b8"><div style="color:#1e293b;font-weight:600">{week_label}</div><div>{gen_time}</div></div>
</div>
<div class="page">
<div class="stat-row">
  <div class="stat-pill"><div class="sp-n" style="color:#2563eb">{len(koc_list)}</div><div class="sp-l">潜力 KOC/KOL</div></div>
  <div class="stat-pill"><div class="sp-n" style="color:#d97706">{len(trades)}</div><div class="sp-l">大额晒单</div></div>
  <div class="stat-pill"><div class="sp-n" style="color:#7c3aed">{len(signal_charts)}</div><div class="sp-l">买卖打点图</div></div>
  <div class="stat-pill"><div class="sp-n" style="color:#0369a1">{len(potential_posts or [])}</div><div class="sp-l">字数≥200</div></div>
  <div class="stat-pill"><div class="sp-n" style="color:#16a34a">{total_scanned}</div><div class="sp-l">本周扫描总量</div></div>
</div>
<div class="sec">
  <div class="sec-hdr">
    <div class="sec-lbl">🎯 维度一：潜力 KOC / KOL</div>
    <span class="badge" style="background:#dbeafe;color:#1d4ed8">互动 ≥ 50</span>
    <span class="badge" style="background:#f1f5f9;color:#64748b">已排除官方账号</span>
    <span class="badge" style="background:#dbeafe;color:#1d4ed8">{len(koc_list)} 人</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-bottom:14px">近7天（{week_label}）点赞+转发+评论总量 ≥ 50，★ 评分越高价值越大，点击查看原帖</p>
  {koc_cards()}
</div>
<div class="sec">
  <div class="sec-hdr">
    <div class="sec-lbl">💰 维度二：大额晒单</div>
    <span class="badge" style="background:#fef3c7;color:#d97706">港股>3万HKD · 美股>5千USD · 收益率≥50%</span>
    <span class="badge" style="background:#dcfce7;color:#16a34a">{len(trades)} 张</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-bottom:14px">经 Claude AI 图像识别，持仓/盈亏金额达标的晒单，点击查看原帖</p>
  {trade_cards()}
</div>
<div class="sec">
  <div class="sec-hdr">
    <div class="sec-lbl">📍 维度三：买卖打点图</div>
    <span class="badge" style="background:#dbeafe;color:#2563eb">实战交易记录</span>
    <span class="badge" style="background:#ede9fe;color:#7c3aed">{len(signal_charts)} 张</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-bottom:14px">K线图上标注了个人买卖点位的实战打点图，金额不限，点击查看原帖</p>
  {signal_cards()}
</div>
<div style="background:linear-gradient(135deg,#eff6ff,#f8faff);border:1px solid #dbeafe;border-radius:16px;padding:24px;margin-bottom:44px">
  <div class="sec-hdr" style="margin-bottom:10px">
    <div class="sec-lbl" style="color:#1d4ed8">✍️ 维度四：优质长文内容</div>
    <span class="badge" style="background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe">字数 ≥ 200</span>
    <span class="badge" style="background:#f0f9ff;color:#0369a1;border:1px solid #bae6fd">已排除官方账号</span>
    <span class="badge" style="background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe">{len(potential_posts or [])} 篇</span>
  </div>
  <p style="color:#64748b;font-size:12px;margin-bottom:16px">近7天（{week_label}）正文字数≥200字的非官方内容，按发布时间倒序，适合挖掘潜力创作者</p>
  <div style="max-width:860px">{potential_cards()}</div>
</div>
</div>
<div class="footer">牛牛圈 KOC 监测 · Powered by Claude AI · 不构成投资建议 · {gen_time}</div>
</body>
</html>"""

# ── 创作者数据库：合并当日数据 ────────────────────────────────
def update_creator_db(koc_list, trades, signal_charts):
    today = datetime.now().strftime("%Y-%m-%d")
    new_db = {}

    all_posts = []
    for p in koc_list:
        all_posts.append((p, None))
    for p in trades:
        all_posts.append((p, p.get("vision")))
    for p in signal_charts:
        all_posts.append((p, p.get("vision")))

    for p, vision in all_posts:
        aid = p.get("author_id") or p.get("author", "unknown")
        if not aid:
            continue
        if aid not in new_db:
            new_db[aid] = {
                "author":           p.get("author", ""),
                "author_id":        p.get("author_id", ""),
                "fans_num":         p.get("fans_num", 0),
                "tags":             [],
                "total_engagement": 0,
                "best_score":       0,
                "appearances":      0,
                "last_seen":        today,
                "posts":            [],
            }
        c = new_db[aid]
        c["appearances"]      += 1
        c["total_engagement"] += p.get("total_engagement", 0)
        if p.get("fans_num", 0) > c["fans_num"]:
            c["fans_num"] = p["fans_num"]
        for tg in p.get("tags", []):
            if tg not in c["tags"]:
                c["tags"].append(tg)
        sc = p.get("score", 0)
        if sc > c["best_score"]:
            c["best_score"] = sc
        c["last_seen"] = today
        c["posts"].append({
            "date":             p.get("date", ""),
            "url":              p.get("url", ""),
            "total_engagement": p.get("total_engagement", 0),
            "score":            sc,
            "tags":             p.get("tags", []),
        })

    # 与历史数据合并
    existing = {}
    if DB_FILE.exists():
        try:
            existing = json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    for aid, data in new_db.items():
        if aid in existing:
            ex = existing[aid]
            ex["appearances"]      += data["appearances"]
            ex["total_engagement"] += data["total_engagement"]
            if data["best_score"] > ex.get("best_score", 0):
                ex["best_score"] = data["best_score"]
            if data["fans_num"] > ex.get("fans_num", 0):
                ex["fans_num"] = data["fans_num"]
            for tg in data["tags"]:
                if tg not in ex["tags"]:
                    ex["tags"].append(tg)
            ex["last_seen"] = today
            ex["posts"] = (ex.get("posts", []) + data["posts"])[-30:]
        else:
            existing[aid] = data

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    DB_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 创作者数据库已更新：{len(existing)} 位创作者")
    return existing

# ── 主流程 ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max",         type=int,  default=1000, help="最多扫描条数（默认1000）")
    parser.add_argument("--all-trades",  action="store_true",     help="收录所有晒单（不限金额门槛）")
    parser.add_argument("--vision-cap",  type=int,  default=120,  help="最多Vision分析次数（默认120，约30分钟）")
    parser.add_argument("--skip-vision", action="store_true",     help="跳过Vision分析（仅更新KOC/互动排行，不检测晒单）")
    parser.add_argument("--vision-days", type=int,  default=7,    help="仅对最近N天的帖子做Vision分析（默认7，设1仅今日）")
    parser.add_argument("--headless",    action="store_true",     help="无头模式（忽略，仅兼容旧脚本）")
    parser.add_argument("--pages",       type=int,  default=None, help="兼容参数，等同于 --max N*30")
    args = parser.parse_args()
    # 兼容旧的 --pages 参数
    if args.pages and not args.max:
        args.max = args.pages * 30

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  牛牛圈 KOC 周度监测  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. 加载 Cookie
    try:
        cookie_str = load_cookies()
        global _COOKIE_CACHE
        _COOKIE_CACHE = cookie_str
        print(f"✅ Cookie 已加载（{cookie_str.count(';')+1} 个）")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    # 2. 拉取帖子（API 偶发返回少量数据时自动重试，最多3次）
    print(f"\n📡 拉取本周帖子（最多 {args.max} 条）...")
    all_posts = fetch_feeds(cookie_str, max_posts=args.max)
    for _retry in range(2):
        if len(all_posts) >= 100:
            break
        print(f"  ⚠️  只抓到 {len(all_posts)} 条，30秒后重试（第{_retry+1}次）...")
        time.sleep(30)
        retry_posts = fetch_feeds(cookie_str, max_posts=args.max)
        if len(retry_posts) > len(all_posts):
            print(f"  ✅ 重试成功：{len(retry_posts)} 条")
            all_posts = retry_posts

    # 3. 高互动筛选
    koc_raw = [p for p in all_posts
               if p["total_engagement"] >= 50
               and not is_official_account(p["author"], p.get("identity", 0))]

    # 添加标签和评分（KOC 无 vision，仅文本推断）
    for p in koc_raw:
        p["tags"]  = infer_tags(p.get("text", ""))
        p["score"] = calc_koc_score(p)

    # 先按时间倒序（最新在前），再按评分倒序作为二级排序
    koc_list = sorted(koc_raw, key=lambda x: (x["ts"], x["score"]), reverse=True)
    print(f"🎯 互动≥50（已过滤官方）：{len(koc_list)} 条")

    # 4. 晒单图片分析
    vision_cutoff = datetime.now() - timedelta(days=args.vision_days)
    trade_posts   = [p for p in all_posts
                     if p["is_trade"] and p["imgs"]
                     and (args.vision_days >= 7 or
                          (p["ts"] and datetime.fromtimestamp(p["ts"]) >= vision_cutoff))]
    large_trades  = []
    signal_charts = []

    if args.skip_vision:
        out_check = OUT_DIR / f"koc_monitor_{datetime.now().strftime('%Y-%m-%d')}.html"
        if out_check.exists() and out_check.stat().st_size > 500_000:
            print(f"⏭️  跳过 Vision 分析（--skip-vision），已有报告 {out_check.name}（{out_check.stat().st_size//1024}KB），不覆盖")
            return
        print(f"⏭️  跳过 Vision 分析（--skip-vision）")
        print(f"💰 大额晒单：0 张  📍 买卖打点图：0 张")
    else:
        print(f"🔍 含图候选：{len(trade_posts)} 条，开始 Claude Vision 分析...")
        seen_posts = set()
        analyzed   = 0
        dl_fail    = 0

        for p in trade_posts:
            for img_url in p["imgs"][:2]:
                fname     = re.sub(r"[^\w]", "_", img_url[-40:]) + ".jpg"
                save_path = str(IMG_DIR / fname)
                if not download_img(img_url, save_path, verbose=True):
                    dl_fail += 1
                    continue
                analyzed += 1
                print(f"  [{analyzed}] 分析: {img_url[-50:]}", end=" ")
                vision = analyze_trade_image(save_path)
                print(f"→ {vision.get('summary','')}")

                tags  = infer_tags(p.get("text", ""), vision)
                score = calc_koc_score(p, vision)
                feed_id = p["feed_id"]

                with open(save_path, "rb") as fh:
                    raw_bytes = fh.read()
                b64   = base64.b64encode(raw_bytes).decode()
                media = detect_media_type(raw_bytes)

                enriched = {**p, "img_url": img_url, "img_b64": b64,
                            "img_media": media, "vision": vision,
                            "tags": tags, "score": score}

                qualify = is_large_trade(vision) or (args.all_trades and vision.get("is_trade"))
                if qualify:
                    if feed_id not in seen_posts:
                        large_trades.append(enriched)
                        seen_posts.add(feed_id)
                        print(f"  ✅ 晒单！{vision.get('market')} {vision.get('amount')} {vision.get('currency')} rr={vision.get('return_rate')}%")
                    break
                elif vision.get("is_signal_chart") and feed_id not in seen_posts:
                    signal_charts.append(enriched)
                    seen_posts.add(feed_id)
                    print(f"  📍 买卖打点图")

            if analyzed >= args.vision_cap:
                print(f"  (Vision 分析上限{args.vision_cap}次，已停止)")
                break

        if dl_fail or analyzed == 0:
            print(f"  ⚠️  图片下载失败 {dl_fail} 次（成功 {analyzed} 次）")
            if analyzed == 0 and dl_fail > 0:
                print(f"  ⚠️  所有图片均下载失败！Cookie 可能已过期，请重新运行 futu_login.py")

    large_trades.sort(key=lambda x: x["ts"],  reverse=True)
    signal_charts.sort(key=lambda x: x["ts"], reverse=True)
    print(f"💰 大额晒单：{len(large_trades)} 张  📍 买卖打点图：{len(signal_charts)} 张")

    # 4.5 字数≥200 优质内容（排除官方 + 去除已在第一板的高互动帖）
    koc_feed_ids = {p["feed_id"] for p in koc_list}
    potential_posts = [
        p for p in all_posts
        if p.get("char_count", 0) >= 200
        and not is_official_account(p["author"], p.get("identity", 0))
        and p["feed_id"] not in koc_feed_ids
    ]
    potential_posts.sort(key=lambda x: x["ts"], reverse=True)
    print(f"✍️  字数≥200 优质内容（已去重）：{len(potential_posts)} 篇")

    # 5. 生成周报（防覆盖保护）
    html = build_report(koc_list, large_trades, signal_charts, WEEK_START, WEEK_END, len(all_posts), potential_posts)
    out  = OUT_DIR / f"koc_monitor_{datetime.now().strftime('%Y-%m-%d')}.html"
    if out.exists():
        import re as _re
        existing_html  = out.read_text(encoding="utf-8", errors="replace")
        ex_nums        = _re.findall(r'class="sp-n"[^>]*>(\d+)<', existing_html)
        ex_trades      = int(ex_nums[1]) if len(ex_nums) > 1 else 0
        ex_signals     = int(ex_nums[2]) if len(ex_nums) > 2 else 0
        ex_posts_m     = _re.search(r'扫描.*?(\d+)', existing_html)
        ex_posts       = int(ex_posts_m.group(1)) if ex_posts_m else 0
        new_hits       = len(large_trades) + len(signal_charts)
        ex_hits        = ex_trades + ex_signals
        # 保留规则：
        # a. 若已有报告的晒单+打点 > 0，而本次为 0，跳过覆盖
        if ex_hits > 0 and new_hits == 0:
            print(f"\n⚠️  已有报告含 {ex_trades} 晒单 + {ex_signals} 打点图，本次 Vision 结果为 0，保留已有报告不覆盖")
            print(f"   （原因可能是 Cookie 失效或图片下载失败，请检查后重试）")
        # b. 帖子数明显少于已有报告（不足一半）
        elif ex_posts > 0 and len(all_posts) < ex_posts * 0.5 and new_hits < ex_hits:
            print(f"\n⚠️  本次抓到 {len(all_posts)} 条（已有报告 {ex_posts} 条且晒单更多），跳过覆盖保留好报告")
        else:
            out.write_text(html, encoding="utf-8")
            print(f"\n✅ 周报已生成：{out}")
    else:
        out.write_text(html, encoding="utf-8")
        print(f"\n✅ 周报已生成：{out}")

    # 6. 更新创作者数据库
    update_creator_db(koc_list, large_trades, signal_charts)

    # 7. 更新仪表盘
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "koc_dashboard", Path(__file__).parent / "koc_dashboard.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.build_dashboard()
    except Exception as e:
        print(f"  [仪表盘更新: {e}]")

    # 8. 自动发布到 GitHub Pages
    try:
        import importlib.util
        spec2 = importlib.util.spec_from_file_location(
            "koc_publish", Path(__file__).parent / "koc_publish.py")
        mod2 = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(mod2)
        mod2.main()
    except Exception as e:
        print(f"  [GitHub Pages 发布: {e}]")

    # 9. 打开仪表盘
    dash = OUT_DIR / "koc_dashboard.html"
    open_path = dash if dash.exists() else out
    webbrowser.open(f"file:///{str(open_path).replace(chr(92), '/')}")
    print(f"✅ 已在浏览器打开")
    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    main()
