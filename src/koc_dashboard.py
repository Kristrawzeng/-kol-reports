# -*- coding: utf-8 -*-
"""
KOC 监测仪表盘生成器 v2
- 左侧：历史周报列表
- 主区：内嵌报告 iframe
- 右侧抽屉：创作者挖掘看板（标签体系 / 评分 / 粉丝数 / 历史表现）
- 顶部：浏览器推送通知（发现优质创作者）
"""
import json, os, re, sys, webbrowser
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPORTS_DIR = Path(__file__).parent / "reports"
DB_FILE     = REPORTS_DIR / "creator_db.json"
OUT_FILE    = REPORTS_DIR / "koc_dashboard.html"

TAG_COLORS = {
    "港股":  ("#2563eb", "#1d4ed8"),
    "美股":  ("#60a5fa", "#3b82f6"),
    "A股":   ("#f87171", "#ef4444"),
    "期权":  ("#a78bfa", "#8b5cf6"),
    "期货":  ("#fbbf24", "#f59e0b"),
    "ETF":   ("#34d399", "#10b981"),
    "短线":  ("#f472b6", "#ec4899"),
    "长线":  ("#4ade80", "#22c55e"),
    "打点图":("#93c5fd", "#60a5fa"),
    "高收益":("#fcd34d", "#f0a500"),
}

def tag_pill(tag: str) -> str:
    fg, bg_dark = TAG_COLORS.get(tag, ("#aaa", "#555"))
    return (f'<span style="background:{bg_dark}25;color:{fg};'
            f'font-size:9px;font-weight:700;padding:2px 7px;'
            f'border-radius:10px;margin:1px 2px;display:inline-block">{tag}</span>')

def score_ring(score: int) -> str:
    if score >= 80:   c, label = "#f0a500", "S"
    elif score >= 65: c, label = "#e84393", "A"
    elif score >= 50: c, label = "#7c3aed", "B"
    elif score >= 35: c, label = "#2563eb", "C"
    else:             c, label = "#555",    "D"
    return (f'<div style="width:36px;height:36px;border-radius:50%;'
            f'border:2.5px solid {c};display:flex;align-items:center;'
            f'justify-content:center;font-size:11px;font-weight:900;'
            f'color:{c};flex-shrink:0;">{label}<br>'
            f'<span style="font-size:7px;line-height:1">{score}</span></div>')

def fans_fmt(n: int) -> str:
    if n >= 10000: return f"{n/10000:.1f}万"
    if n >= 1000:  return f"{n/1000:.1f}k"
    return str(n) if n > 0 else "—"

def parse_report_meta(html_path: Path) -> dict:
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        week_m  = re.search(r'本周[：:]\s*([\d/]+\s*~\s*[\d/]+)', text)
        wlabel  = week_m.group(1) if week_m else html_path.stem.replace("koc_monitor_", "")
        # sp-n 是现有报告的 class
        nums = re.findall(r'class="sp-n"[^>]*>(\d+)<', text)
        koc_cnt   = int(nums[0]) if len(nums) > 0 else 0
        trade_cnt = int(nums[1]) if len(nums) > 1 else 0
        sig_cnt   = int(nums[2]) if len(nums) > 2 else 0
        gen_m    = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', text)
        gen_time = gen_m.group(1) if gen_m else ""
        return {
            "file": html_path.name, "path": str(html_path),
            "week_label": wlabel, "koc_cnt": koc_cnt,
            "trade_cnt": trade_cnt, "signal_cnt": sig_cnt,
            "gen_time": gen_time, "mtime": html_path.stat().st_mtime,
        }
    except Exception:
        return {
            "file": html_path.name, "path": str(html_path),
            "week_label": html_path.stem.replace("koc_monitor_", ""),
            "koc_cnt": 0, "trade_cnt": 0, "signal_cnt": 0, "gen_time": "", "mtime": 0,
        }

def load_creator_db() -> list:
    if not DB_FILE.exists():
        return []
    try:
        raw = json.loads(DB_FILE.read_text(encoding="utf-8"))
        creators = list(raw.values())
        creators.sort(key=lambda x: x.get("best_score", 0), reverse=True)
        return creators
    except Exception:
        return []

def build_dashboard():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports = sorted(
        [parse_report_meta(p) for p in REPORTS_DIR.glob("koc_monitor_*.html")],
        key=lambda x: x["mtime"], reverse=True,
    )
    potential_reports = sorted(
        list(REPORTS_DIR.glob("koc_potential_*.html")),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    creators = load_creator_db()
    gen_time     = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_koc    = sum(r["koc_cnt"] for r in reports)
    total_trades = sum(r["trade_cnt"] for r in reports)
    total_sigs   = sum(r.get("signal_cnt", 0) for r in reports)

    # ── 周报侧栏卡片 ──
    def report_cards():
        if not reports:
            return '''<div style="padding:32px 12px;text-align:center;color:#94a3b8;font-size:12px">
              暂无报告<br>运行 <code style="color:#2563eb">koc_weekly_run.py</code></div>'''
        html = ""
        for i, r in enumerate(reports):
            is_latest  = i == 0
            kc = "#db2777" if r["koc_cnt"] > 0 else "#94a3b8"
            tc = "#d97706" if r["trade_cnt"] > 0 else "#94a3b8"
            sc = "#2563eb" if r.get("signal_cnt", 0) > 0 else "#94a3b8"
            html += f"""
            <div class="rep-card {'rep-latest' if is_latest else ''}" onclick="loadReport('{r['file']}',this)">
              {'<div class="new-badge">最新</div>' if is_latest else ''}
              <div style="color:#1e293b;font-size:11px;font-weight:700;margin-bottom:8px">{r['week_label']}</div>
              <div style="display:flex;gap:6px;margin-bottom:6px">
                <div style="flex:1;background:#f0f4f8;border-radius:6px;padding:5px 4px;text-align:center">
                  <div style="font-size:16px;font-weight:700;color:{kc}">{r['koc_cnt']}</div>
                  <div style="font-size:8px;color:#94a3b8">KOC</div>
                </div>
                <div style="flex:1;background:#f0f4f8;border-radius:6px;padding:5px 4px;text-align:center">
                  <div style="font-size:16px;font-weight:700;color:{tc}">{r['trade_cnt']}</div>
                  <div style="font-size:8px;color:#94a3b8">晒单</div>
                </div>
                <div style="flex:1;background:#f0f4f8;border-radius:6px;padding:5px 4px;text-align:center">
                  <div style="font-size:16px;font-weight:700;color:{sc}">{r.get('signal_cnt',0)}</div>
                  <div style="font-size:8px;color:#94a3b8">打点</div>
                </div>
              </div>
              <div style="color:#94a3b8;font-size:9px;margin-bottom:4px">{r['gen_time'] or '—'}</div>
              <a href="{r['file']}" target="_blank" style="color:#2563eb;font-size:9px" onclick="event.stopPropagation()">新标签打开 ↗</a>
            </div>"""
        return html

    # ── 创作者看板卡片 ──
    def creator_cards():
        if not creators:
            return '''<div style="padding:32px 12px;text-align:center;color:#94a3b8;font-size:12px">
              暂无创作者数据<br>运行一次监测后自动生成</div>'''
        html = ""
        for c in creators[:50]:
            author    = c.get("author", "未知")
            author_id = c.get("author_id", "")
            fans      = c.get("fans_num", 0)
            tags      = c.get("tags", [])
            score     = c.get("best_score", 0)
            eng       = c.get("total_engagement", 0)
            appear    = c.get("appearances", 0)
            last_seen = c.get("last_seen", "")
            posts     = c.get("posts", [])
            # 最近一条帖子 URL
            last_url  = posts[-1]["url"] if posts else "#"

            tag_html = "".join(tag_pill(t) for t in tags[:5])
            ring     = score_ring(score)
            trend_pts = []
            for p in posts[-7:]:
                trend_pts.append(p.get("score", 0))

            # Mini sparkline via inline SVG
            if len(trend_pts) >= 2:
                max_v  = max(trend_pts) or 1
                w, h   = 60, 20
                pts    = " ".join(
                    f"{int(i*w/(len(trend_pts)-1))},{int(h - v/max_v*h)}"
                    for i, v in enumerate(trend_pts)
                )
                spark = (f'<svg width="{w}" height="{h}" style="margin-left:auto;opacity:.7">'
                         f'<polyline points="{pts}" fill="none" stroke="#3b82f6" stroke-width="1.5" stroke-linejoin="round"/>'
                         f'</svg>')
            else:
                spark = ""

            html += f"""
            <div class="creator-card" data-score="{score}" data-tags="{','.join(tags)}">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                {ring}
                <div style="flex:1;min-width:0">
                  <div style="color:#1e293b;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{author}</div>
                  <div style="color:#94a3b8;font-size:9px;margin-top:1px">👥 {fans_fmt(fans)} · 出现 {appear} 次 · {last_seen}</div>
                </div>
                {spark}
              </div>
              <div style="margin-bottom:6px">{tag_html or '<span style="color:#94a3b8;font-size:9px">暂无标签</span>'}</div>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div style="font-size:10px;color:#64748b">🔥 互动 {eng:,} · 最高分 {score}</div>
                <a href="{last_url}" target="_blank"
                   style="font-size:9px;color:#2563eb;padding:2px 8px;border:1px solid #bfdbfe;border-radius:5px">
                  最新帖 →
                </a>
              </div>
            </div>"""
        return html

    # ── 潜力挖掘侧栏卡片 ──
    def potential_cards():
        if not potential_reports:
            return '''<div style="padding:16px 4px;text-align:center;color:#94a3b8;font-size:11px">
              暂无报告<br>运行 <code style="color:#2563eb">koc_potential.py</code></div>'''
        html = ""
        for i, p in enumerate(potential_reports[:5]):
            date_str  = p.stem.replace("koc_potential_", "")
            is_latest = i == 0
            try:
                size_kb = p.stat().st_size // 1024
            except Exception:
                size_kb = 0
            html += f"""
            <div class="rep-card {'rep-latest' if is_latest else ''}" onclick="loadPotential('{p.name}',this)">
              {'<div class="new-badge">最新</div>' if is_latest else ''}
              <div style="color:#1e293b;font-size:11px;font-weight:700;margin-bottom:4px">{date_str}</div>
              <div style="color:#6366f1;font-size:10px;margin-bottom:4px">潜力 KOC 挖掘</div>
              <div style="color:#94a3b8;font-size:9px">字数≥200 · 非官方 · {size_kb}KB</div>
              <a href="{p.name}" target="_blank" style="color:#2563eb;font-size:9px;display:block;margin-top:4px" onclick="event.stopPropagation()">新标签打开 ↗</a>
            </div>"""
        return html

    latest_file = reports[0]["file"] if reports else ""
    latest_potential_file = potential_reports[0].name if potential_reports else ""
    creator_json = json.dumps(
        [{"author": c.get("author"), "score": c.get("best_score",0), "tags": c.get("tags",[])}
         for c in creators if c.get("best_score",0) >= 60],
        ensure_ascii=False
    )

    HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>牛牛圈 KOC 监测中心</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f0f4f8;color:#1e293b;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}}
/* Nav */
.nav{{background:#ffffff;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 4px #2563eb0d;padding:11px 20px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:10px}}
.nav-icon{{width:32px;height:32px;background:linear-gradient(135deg,#2563eb,#3b82f6);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}}
.nav-btn{{background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font-size:11px;font-weight:700;padding:6px 14px;border-radius:7px;border:none;cursor:pointer;font-family:inherit;white-space:nowrap}}
.nav-btn:hover{{opacity:.85}}
.notify-btn{{background:#eff6ff;color:#2563eb;font-size:10px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid #bfdbfe;cursor:pointer;font-family:inherit}}
/* Stats bar */
.stats-bar{{background:#ffffff;border-bottom:1px solid #e2e8f0;padding:8px 20px;display:flex;gap:20px;align-items:center;flex-shrink:0;flex-wrap:wrap}}
.sb{{display:flex;align-items:center;gap:6px;font-size:11px}}
.sb-n{{font-size:16px;font-weight:700}}
.sb-div{{width:1px;height:16px;background:#e2e8f0}}
/* Main 3-column layout */
.main{{display:flex;flex:1;overflow:hidden}}
/* Left: report list */
.sidebar{{width:200px;background:#ffffff;border-right:1px solid #e2e8f0;overflow-y:auto;flex-shrink:0;padding:12px 10px}}
.sidebar-title{{color:#3b82f6;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0}}
.rep-card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin-bottom:8px;cursor:pointer;transition:.18s;position:relative}}
.rep-card:hover{{border-color:#93c5fd;box-shadow:0 2px 8px #2563eb10}}
.rep-card.active{{border-color:#2563eb;background:#eff6ff}}
.rep-latest{{border-color:#bfdbfe}}
.new-badge{{position:absolute;top:7px;right:7px;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font-size:8px;font-weight:700;padding:1px 6px;border-radius:8px}}
/* Center: iframe */
.report-area{{flex:1;overflow:hidden;display:flex;flex-direction:column;min-width:0}}
.report-toolbar{{padding:8px 14px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:10px;flex-shrink:0;background:#ffffff}}
.report-frame{{flex:1;border:none;background:#f0f4f8}}
/* Right: creator panel */
.creator-panel{{width:280px;background:#ffffff;border-left:1px solid #e2e8f0;overflow-y:auto;flex-shrink:0;display:flex;flex-direction:column}}
.panel-header{{padding:12px 14px;border-bottom:1px solid #e2e8f0;flex-shrink:0;position:sticky;top:0;background:#ffffff;z-index:5}}
.panel-filter{{padding:8px 14px;border-bottom:1px solid #e2e8f0;flex-shrink:0;display:flex;gap:6px;flex-wrap:wrap}}
.filter-chip{{font-size:9px;font-weight:700;padding:3px 8px;border-radius:10px;border:1px solid #e2e8f0;background:#f8fafc;color:#64748b;cursor:pointer;font-family:inherit;transition:.15s}}
.filter-chip:hover{{border-color:#93c5fd;color:#2563eb}}
.filter-chip.active{{border-color:#2563eb;color:#1d4ed8;background:#dbeafe}}
.creator-list{{flex:1;overflow-y:auto;padding:10px}}
.creator-card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin-bottom:8px;transition:.18s}}
.creator-card:hover{{border-color:#93c5fd;background:#eff6ff}}
/* Scrollbar */
::-webkit-scrollbar{{width:4px}}::-webkit-scrollbar-track{{background:#f0f4f8}}::-webkit-scrollbar-thumb{{background:#bfdbfe;border-radius:2px}}
/* Notification toast */
#toast{{position:fixed;bottom:24px;right:24px;background:#ffffff;border:1px solid #bfdbfe;border-radius:12px;padding:14px 18px;color:#1e293b;font-size:12px;box-shadow:0 8px 32px #2563eb15;z-index:9999;max-width:280px;display:none;animation:fadeIn .3s}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
</style>
</head>
<body>

<!-- Nav -->
<div class="nav">
  <div style="display:flex;align-items:center;gap:10px">
    <div class="nav-icon">📡</div>
    <div>
      <div style="color:#1e293b;font-weight:700;font-size:14px">牛牛圈 KOC 监测中心</div>
      <div style="color:#64748b;font-size:10px">互动≥50挖掘 · 大额晒单 · 买卖打点 · 创作者评分</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <button class="notify-btn" id="notify-btn" onclick="requestNotify()">🔔 开启通知</button>
    <button class="nav-btn" onclick="alert('请在命令行运行：\\npython koc_weekly_run.py')">▶ 立即生成</button>
  </div>
</div>

<!-- Stats bar -->
<div class="stats-bar">
  <div class="sb"><span class="sb-n" style="color:#db2777">{total_koc}</span><span style="color:#64748b">累计KOC</span></div>
  <div class="sb-div"></div>
  <div class="sb"><span class="sb-n" style="color:#d97706">{total_trades}</span><span style="color:#64748b">累计晒单</span></div>
  <div class="sb-div"></div>
  <div class="sb"><span class="sb-n" style="color:#2563eb">{total_sigs}</span><span style="color:#64748b">累计打点</span></div>
  <div class="sb-div"></div>
  <div class="sb"><span class="sb-n" style="color:#16a34a">{len(reports)}</span><span style="color:#64748b">历史周报</span></div>
  <div class="sb-div"></div>
  <div class="sb"><span class="sb-n" style="color:#7c3aed">{len(creators)}</span><span style="color:#64748b">创作者档案</span></div>
  <div class="sb-div"></div>
  <div style="color:#94a3b8;font-size:10px;margin-left:auto">更新：{gen_time}</div>
</div>

<!-- Main -->
<div class="main">

  <!-- Left sidebar: report list + potential -->
  <div class="sidebar">
    <div class="sidebar-title">📋 历史周报</div>
    {report_cards()}
    <div class="sidebar-title" style="margin-top:14px;border-top:1px solid #e2e8f0;padding-top:10px">🔍 潜力挖掘</div>
    {potential_cards()}
  </div>

  <!-- Center: report frame -->
  <div class="report-area">
    <div class="report-toolbar">
      <div style="color:#64748b;font-size:11px;flex:1" id="report-title">
        {'最新报告：' + reports[0]['week_label'] if reports else '暂无报告'}
      </div>
      <button style="color:#2563eb;font-size:10px;padding:4px 10px;border:1px solid #bfdbfe;border-radius:5px;background:#eff6ff;cursor:pointer;font-family:inherit" onclick="openCurrent()">新标签打开 ↗</button>
    </div>
    {'<iframe id="report-frame" class="report-frame" src="' + latest_file + '"></iframe>' if reports else
     '<div style="flex:1;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#555"><div style="font-size:48px">📡</div><div>暂无周报，运行 koc_weekly_run.py 生成</div></div>'}
  </div>

  <!-- Right: creator panel -->
  <div class="creator-panel">
    <div class="panel-header">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div style="color:#1e293b;font-size:12px;font-weight:700">🔍 创作者挖掘看板</div>
        <span style="background:#ede9fe;color:#7c3aed;font-size:9px;font-weight:700;padding:2px 7px;border-radius:8px">{len(creators)} 位</span>
      </div>
      <input id="creator-search" type="text" placeholder="搜索创作者名称..."
        style="width:100%;background:#f8fafc;border:1px solid #e2e8f0;border-radius:7px;padding:6px 10px;font-size:11px;color:#1e293b;outline:none;font-family:inherit"
        oninput="filterCreators()">
    </div>
    <div class="panel-filter" id="tag-filters">
      <button class="filter-chip active" data-tag="all" onclick="setTagFilter('all',this)">全部</button>
      <button class="filter-chip" data-tag="港股"  onclick="setTagFilter('港股',this)">港股</button>
      <button class="filter-chip" data-tag="美股"  onclick="setTagFilter('美股',this)">美股</button>
      <button class="filter-chip" data-tag="期权"  onclick="setTagFilter('期权',this)">期权</button>
      <button class="filter-chip" data-tag="打点图" onclick="setTagFilter('打点图',this)">打点图</button>
      <button class="filter-chip" data-tag="高收益" onclick="setTagFilter('高收益',this)">高收益</button>
      <button class="filter-chip" data-tag="短线"  onclick="setTagFilter('短线',this)">短线</button>
    </div>
    <div class="creator-list" id="creator-list">
      {creator_cards()}
    </div>
  </div>

</div>

<!-- Toast notification -->
<div id="toast"></div>

<script>
var currentFile = '{latest_file}';
var activeTag   = 'all';
var highScorers = {creator_json};

// ── 报告切换（通用）──────────────────────────────────────────
function _switchFrame(file, label) {{
  currentFile = file;
  var frame = document.getElementById('report-frame');
  if (!frame) {{
    frame = document.createElement('iframe');
    frame.id = 'report-frame'; frame.className = 'report-frame';
    document.querySelector('.report-area').appendChild(frame);
  }}
  frame.src = file;
  document.getElementById('report-title').textContent = label;
}}

// ── 周报切换 ──────────────────────────────────────────────────
function loadReport(file, el) {{
  document.querySelectorAll('.rep-card').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  var name = file.replace('koc_monitor_','').replace('.html','');
  _switchFrame(file, '当前报告：' + name);
}}

// ── 潜力挖掘切换 ──────────────────────────────────────────────
function loadPotential(file, el) {{
  document.querySelectorAll('.rep-card').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  var name = file.replace('koc_potential_','').replace('.html','');
  _switchFrame(file, '🔍 潜力挖掘：' + name);
}}

function openCurrent() {{ if (currentFile) window.open(currentFile, '_blank'); }}

// ── 创作者过滤 ────────────────────────────────────────────────
function setTagFilter(tag, el) {{
  activeTag = tag;
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  filterCreators();
}}

function filterCreators() {{
  var q   = (document.getElementById('creator-search').value || '').toLowerCase();
  var cards = document.querySelectorAll('.creator-card');
  cards.forEach(function(card) {{
    var tags   = (card.dataset.tags || '').toLowerCase();
    var author = card.querySelector('[style*="font-weight:700"]');
    var name   = author ? author.textContent.toLowerCase() : '';
    var tagMatch = activeTag === 'all' || tags.includes(activeTag);
    var qMatch   = !q || name.includes(q) || tags.includes(q);
    card.style.display = (tagMatch && qMatch) ? '' : 'none';
  }});
}}

// ── 浏览器推送通知 ────────────────────────────────────────────
function requestNotify() {{
  if (!('Notification' in window)) {{
    showToast('❌ 当前浏览器不支持通知功能');
    return;
  }}
  Notification.requestPermission().then(function(perm) {{
    if (perm === 'granted') {{
      document.getElementById('notify-btn').textContent = '🔔 通知已开启';
      document.getElementById('notify-btn').style.color = '#4ade80';
      document.getElementById('notify-btn').style.borderColor = '#4ade8044';
      showToast('✅ 通知已开启！发现优质创作者时将自动提醒');
      checkAndNotify();
    }} else {{
      showToast('⚠️ 未授权通知权限，请在浏览器设置中允许');
    }}
  }});
}}

function checkAndNotify() {{
  if (Notification.permission !== 'granted') return;
  if (!highScorers || highScorers.length === 0) return;
  var top = highScorers.slice(0, 3);
  var names = top.map(function(c){{ return c.author + '('+c.score+')'; }}).join('、');
  var n = new Notification('🎯 KOC监测中心 · 发现优质创作者', {{
    body: '本期高分创作者：' + names,
    icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><text y="26" font-size="28">📡</text></svg>',
    tag: 'koc-alert',
  }});
  n.onclick = function() {{ window.focus(); }};
}}

function showToast(msg) {{
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(function(){{ t.style.display = 'none'; }}, 3500);
}}

// ── 初始化 ────────────────────────────────────────────────────
(function() {{
  // 标记第一个报告卡片为激活
  var cards = document.querySelectorAll('.rep-card');
  if (cards.length) cards[0].classList.add('active');

  // 若通知已授权，主动检查
  if (Notification.permission === 'granted') {{
    document.getElementById('notify-btn').textContent = '🔔 通知已开启';
    document.getElementById('notify-btn').style.color = '#4ade80';
    checkAndNotify();
  }}

  // 每5分钟自动刷新
  setTimeout(function(){{ window.location.reload(); }}, 5 * 60 * 1000);
}})();
</script>
</body>
</html>"""

    OUT_FILE.write_text(HTML, encoding="utf-8")
    print(f"✅ 仪表盘已更新：{OUT_FILE}")
    return str(OUT_FILE)

if __name__ == "__main__":
    path = build_dashboard()
    webbrowser.open(f"file:///{path.replace(chr(92), '/')}")
