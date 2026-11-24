"""Visual building blocks for the dashboard: small functions that return HTML.

Everything that comes from a user (complaint text, names) goes through html.escape, so a complaint such as
"<script>..." is shown as text and can never run as code.
"""
import json
from html import escape

from modules.geo import SERVICE_AREA, WARD_CENTRES

RED, DARK_RED, BLUE, TINT = "#C1292E", "#A2363A", "#235789", "#E8EEF6"
LEVELS = ["low", "medium", "high", "critical"]
COLORS = {"low": "#2E7D32", "medium": "#F9A825", "high": "#EF6C00", "critical": "#C62828"}
EMOJI = {"low": "\U0001F7E2", "medium": "\U0001F7E1", "high": "\U0001F7E0", "critical": "\U0001F534"}
SHIFT_MIN = 480

# Small line icons (24x24), drawn inline so they need no files or internet.
_ICONS = {
    "pin": '<path d="M12 21s-6-5.2-6-10a6 6 0 1 1 12 0c0 4.8-6 10-6 10z"/><circle cx="12" cy="11" r="2.2"/>',
    "shield": '<path d="M12 3l7 3v5c0 5-3.2 8.5-7 10-3.8-1.5-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    "clipboard": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 11h6M9 15h6"/>',
    "truck": '<path d="M3 7h11v9H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
    "chart": '<path d="M4 20V4M4 20h16"/><path d="M8 16v-5M12 16V8M16 16v-3"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.6 3-6 7-6s7 2.4 7 6"/><circle cx="17" cy="9" r="2.8"/><path d="M17 14c3 0 5 1.8 5 5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "building": '<path d="M4 21V8l8-4 8 4v13"/><path d="M9 21v-5h6v5M8 11h2M14 11h2"/>',
    "map": '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "route": '<circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="6" r="2.2"/><path d="M8 18h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6"/>',
    "bell": '<path d="M6 17V11a6 6 0 0 1 12 0v6l2 2H4z"/><path d="M10 21h4"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "send": '<path d="M21 3L3 11l7 3 3 7z"/><path d="M10 14l11-11"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7z"/>',
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10M10 20v-6h4v6"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "bolt": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "wave": '<path d="M3 9c3-3 5 3 9 0s6 3 9 0M3 15c3-3 5 3 9 0s6 3 9 0"/>',
}
CATEGORY_ICON = {"Road": "route", "Sanitation": "trash", "Electricity": "bolt", "Water Supply": "drop", "Drainage": "wave"}
CATEGORY_EMOJI = {"Road": "\U0001F6E3\uFE0F", "Sanitation": "\U0001F5D1\uFE0F", "Electricity": "\U0001F4A1",
                  "Water Supply": "\U0001F4A7", "Drainage": "\U0001F30A"}
TEXT_ON = {"medium": "#1F2D3D"}          # dark text on yellow, white text on the other colours

_CSS = """
.cs-hero{background:linear-gradient(120deg,#A2363A,#C1292E);color:#fff;padding:30px 34px;border-radius:18px;margin:0 0 20px 0}
.cs-hero h1{margin:0;font-size:38px;color:#fff;font-weight:800;letter-spacing:.01em}
.cs-hero p{margin:8px 0 0 0;font-size:17px;color:#fff;opacity:.93}
.cs-title{margin:0 0 4px 0;font-size:30px;font-weight:800;color:#C1292E}
.cs-sub{margin:0 0 18px 0;font-size:15px;color:#5b6b7b}
.cs-kpis{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 20px 0}
.cs-kpi{flex:1;min-width:150px;background:#E8EEF6;border-radius:14px;padding:16px 18px;border-left:6px solid #235789}
.cs-kpi.red{border-left-color:#C1292E}
.cs-kpi .v{font-size:30px;font-weight:800;color:#235789;line-height:1.1}
.cs-kpi.red .v{color:#C1292E}
.cs-kpi .l{font-size:12px;color:#4a5a6a;text-transform:uppercase;letter-spacing:.05em;margin-top:4px}
.cs-kpi .d{font-size:13px;color:#2E7D32;margin-top:4px;font-weight:600}
.cs-kpi.red .d{color:#8a3b3b}
.cs-badge{display:inline-block;padding:3px 12px;border-radius:999px;color:#fff;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.cs-flow{display:flex;gap:12px;align-items:stretch;margin:8px 0 22px 0;flex-wrap:wrap}
.cs-step{flex:1;min-width:210px;border:1px solid #d5deea;border-radius:14px;padding:16px 18px;background:#fff;color:#1F2D3D}
.cs-step .n{display:inline-block;width:28px;height:28px;line-height:28px;text-align:center;border-radius:50%;background:#C1292E;color:#fff;font-weight:700;margin-right:8px}
.cs-step .t{font-weight:800;color:#235789;font-size:17px}
.cs-step p{margin:8px 0 0 0;font-size:14px;color:#4a5a6a}
.cs-arrow{align-self:center;color:#C1292E;font-size:26px;font-weight:700}
.cs-card{border:1px solid #d5deea;border-left:8px solid #235789;border-radius:14px;padding:16px 20px;background:#fff;margin:0 0 12px 0;color:#1F2D3D}
.cs-card .top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.cs-card .id{font-weight:800;color:#235789;font-size:18px}
.cs-card .txt{margin:10px 0 8px 0;font-size:16px;color:#1F2D3D}
.cs-card .meta{font-size:13px;color:#5b6b7b}
.cs-mini{border:1px solid #d5deea;border-left:6px solid #235789;border-radius:12px;padding:10px 14px;background:#fff;margin:0 0 8px 0;color:#1F2D3D}
.cs-mini .txt{font-size:14px;margin-top:4px}
.cs-mini .meta{font-size:12px;color:#5b6b7b;margin-top:2px}
.cs-trace{margin:0;padding:0}
.cs-tstep{display:flex;gap:12px;margin:0 0 12px 0}
.cs-tnum{flex:0 0 30px;height:30px;line-height:30px;text-align:center;border-radius:50%;background:#235789;color:#fff;font-weight:700;font-size:14px}
.cs-tbody{flex:1;background:#E8EEF6;border-radius:12px;padding:10px 14px;color:#1F2D3D}
.cs-tbody .nm{font-weight:700;color:#235789}
.cs-tbody .rid{display:inline-block;background:#235789;color:#fff;border-radius:6px;padding:0 7px;font-size:11px;margin-left:6px}
.cs-tbody .why{font-size:14px;margin-top:2px}
.cs-tbody .chg{font-size:13px;color:#C1292E;margin-top:2px;font-weight:600}
.cs-flag{background:#FFF4E5;border-left:5px solid #EF6C00;border-radius:8px;padding:8px 12px;margin:0 0 8px 0;color:#7a3e00;font-size:14px}
.cs-tl{margin:6px 0 10px 0;color:#1F2D3D}
.cs-tl-row{display:flex;align-items:center;gap:10px;margin:0 0 8px 0}
.cs-tl-name{flex:0 0 150px;font-weight:700;font-size:14px;color:#235789}
.cs-tl-name span{display:block;font-weight:400;font-size:11px;color:#5b6b7b}
.cs-tl-track{position:relative;flex:1;height:38px;background:#E8EEF6;border-radius:8px;overflow:hidden;background-image:repeating-linear-gradient(to right,transparent 0,transparent calc(12.5% - 1px),#c3cfdd calc(12.5% - 1px),#c3cfdd 12.5%)}
.cs-stop{position:absolute;top:4px;height:30px;border-radius:6px;color:#fff;font-size:11px;font-weight:700;line-height:30px;text-align:center;overflow:hidden;white-space:nowrap;box-sizing:border-box}
.cs-stop.late{border:2px dashed #111}
.cs-tl-axis{display:flex;margin-left:160px;font-size:11px;color:#5b6b7b}
.cs-tl-axis span{flex:1}
.cs-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:#5b6b7b;margin:4px 0 14px 0}
.cs-dot{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.cs-bars{margin:0 0 18px 0;color:#1F2D3D}
.cs-bar{display:flex;align-items:center;gap:10px;margin:0 0 7px 0}
.cs-bar .lb{flex:0 0 130px;font-size:14px}
.cs-bar .tr{position:relative;flex:1;height:22px;background:#E8EEF6;border-radius:6px}
.cs-bar .fl{height:22px;border-radius:6px}
.cs-bar .mk{position:absolute;top:-3px;width:2px;height:28px;background:#111}
.cs-bar .vl{flex:0 0 46px;font-size:13px;font-weight:700;text-align:right}
.cs-hero.blue{background:linear-gradient(120deg,#1b3f66,#235789)}
.cs-hero .pill{display:inline-block;margin-top:14px;padding:5px 14px;border:1px solid rgba(255,255,255,.7);border-radius:999px;font-size:13px;color:#fff}
@keyframes csfade{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes cspulse{0%{box-shadow:0 0 0 0 rgba(193,41,46,.55)}100%{box-shadow:0 0 0 14px rgba(193,41,46,0)}}
.cs-hero,.cs-kpi,.cs-step,.cs-card,.cs-mini,.cs-loc{animation:csfade .5s ease both}
.cs-kpi:nth-child(2),.cs-step:nth-child(3){animation-delay:.07s}
.cs-kpi:nth-child(3),.cs-step:nth-child(5){animation-delay:.14s}
.cs-kpi:nth-child(4){animation-delay:.21s}
.cs-kpi:nth-child(5){animation-delay:.28s}
.cs-kpi,.cs-card,.cs-mini,.cs-step{transition:transform .15s ease,box-shadow .15s ease}
.cs-kpi:hover,.cs-card:hover,.cs-mini:hover,.cs-step:hover{transform:translateY(-3px);box-shadow:0 10px 22px rgba(35,87,137,.16)}
.cs-track{display:flex;align-items:flex-start;margin:22px 0 10px 0}
.cs-ts{flex:1;text-align:center;position:relative;color:#5b6b7b;font-size:14px;padding:0 6px}
.cs-ts .dot{width:40px;height:40px;line-height:40px;border-radius:50%;margin:0 auto 8px auto;background:#c3cfdd;color:#fff;font-weight:700;position:relative;z-index:2}
.cs-ts.done .dot{background:#2E7D32}
.cs-ts.now .dot{background:#C1292E;animation:cspulse 1.6s infinite}
.cs-ts.done,.cs-ts.now{color:#1F2D3D;font-weight:600}
.cs-ts:not(:last-child)::after{content:"";position:absolute;top:18px;left:50%;width:100%;height:4px;background:#c3cfdd;z-index:1}
.cs-ts.done:not(:last-child)::after{background:#2E7D32}
.cs-codewrap{text-align:center;margin:10px 0 6px 0}
.cs-code{display:inline-block;font-family:Consolas,Menlo,monospace;font-size:30px;font-weight:800;letter-spacing:.12em;color:#235789;background:#E8EEF6;border:2px dashed #235789;border-radius:12px;padding:10px 22px}
.cs-loc{border:1px solid #d5deea;border-left:6px solid #2E7D32;border-radius:12px;padding:12px 16px;background:#fff;color:#1F2D3D;margin:8px 0 12px 0}
.cs-loc.bad{border-left-color:#C62828;background:#FDECEA}
.cs-loc .coords{font-family:Consolas,Menlo,monospace;font-size:15px;font-weight:700;color:#235789}
.cs-loc .src{font-size:12px;color:#5b6b7b;text-transform:uppercase;letter-spacing:.05em}
.cs-loc .near{margin-top:6px;font-size:13px;color:#7a3e00;background:#FFF4E5;border-radius:8px;padding:4px 10px;display:inline-block}
.cs-mx{overflow-x:auto;margin:6px 0 16px 0}
.cs-mx table{border-collapse:collapse;width:100%;color:#1F2D3D}
.cs-mx th{background:#235789;color:#fff;padding:10px 12px;font-size:13px;text-align:center}
.cs-mx th:first-child{text-align:left;border-radius:10px 0 0 0}
.cs-mx th:last-child{border-radius:0 10px 0 0}
.cs-mx td{padding:9px 12px;border-bottom:1px solid #e3e9f1;text-align:center;font-size:14px}
.cs-mx td:first-child{text-align:left;font-weight:700;color:#235789}
.cs-mx td.up{background:#FFF4E5}
.cs-mx .sc{display:block;font-size:11px;color:#5b6b7b;margin-top:3px}
.cs-cm{overflow-x:auto;margin:6px 0 14px 0}
.cs-cm table{border-collapse:collapse;color:#1F2D3D}
.cs-cm th{padding:8px 12px;font-size:12px;color:#4a5a6a;font-weight:700}
.cs-cm td{width:74px;height:46px;text-align:center;font-weight:700;border:2px solid #FDFFFC;border-radius:6px}
.cs-cm td.rowh{background:none;color:#4a5a6a;font-size:12px;text-align:right;padding-right:10px;width:auto}
.cs-ups{border-left:3px solid #d5deea;margin:8px 0 16px 10px;padding-left:18px}
.cs-up{position:relative;margin:0 0 14px 0}
.cs-up .dot{position:absolute;left:-27px;top:4px;width:12px;height:12px;border-radius:50%;background:#235789;border:2px solid #FDFFFC}
.cs-up .t{font-size:12px;color:#5b6b7b}
.cs-up .m{font-size:15px;color:#1F2D3D;font-weight:600}
.cs-stop-link a{color:#235789;font-weight:700;text-decoration:none}
.cs-maplegend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:#4a5a6a;margin:8px 0 14px 0}
.cs-maplegend .g{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;color:#fff;font-size:10px;font-weight:700;margin-right:5px}
@keyframes csgradient{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes csfloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-14px)}}
@keyframes csgrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes cspop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
.cs-hero{position:relative;overflow:hidden}
.cs-hero.live{background:linear-gradient(120deg,#A2363A,#C1292E,#D9544F,#A2363A);background-size:240% 240%;animation:csgradient 14s ease infinite}
.cs-hero.blue.live{background:linear-gradient(120deg,#1b3f66,#235789,#2f6aa8,#1b3f66);background-size:240% 240%;animation:csgradient 14s ease infinite}
.cs-hero .blob{position:absolute;border-radius:50%;background:rgba(255,255,255,.10);animation:csfloat 7s ease-in-out infinite}
.cs-hero .b1{width:230px;height:230px;right:-60px;top:-80px}
.cs-hero .b2{width:120px;height:120px;right:190px;bottom:-55px;animation-delay:-3s}
.cs-hero .bigic{position:absolute;right:46px;top:50%;margin-top:-48px;color:#fff;opacity:.28}
.cs-hero h1,.cs-hero p,.cs-hero .pill{position:relative;z-index:2}
.cs-ibub{display:inline-flex;align-items:center;justify-content:center;width:46px;height:46px;border-radius:13px;background:rgba(35,87,137,.12);color:#235789;flex:0 0 46px}
.cs-ibub.red{background:rgba(193,41,46,.12);color:#C1292E}
.cs-ibub.green{background:rgba(46,125,50,.14);color:#2E7D32}
.cs-ibub.amber{background:rgba(239,108,0,.15);color:#EF6C00}
.cs-ibub.big{width:64px;height:64px;border-radius:18px;flex:0 0 64px}
.cs-kpi{display:flex;gap:14px;align-items:center}
.cs-kpi .bd{flex:1;min-width:0}
.cs-badge.crit{animation:cspulse 2s infinite}
.cs-card .top .l{display:flex;align-items:center;gap:12px}
.cs-sect{display:flex;align-items:center;gap:10px;margin:20px 0 10px 0;font-size:20px;font-weight:800;color:#1F2D3D}
.cs-sect .cs-ibub{width:34px;height:34px;border-radius:10px;flex:0 0 34px}
.cs-portals{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 4px 0}
.cs-portal{flex:1;min-width:300px;border:1px solid #d5deea;border-radius:20px;padding:26px 28px 18px 28px;background:#fff;color:#1F2D3D;position:relative;overflow:hidden;transition:transform .18s ease,box-shadow .18s ease;animation:csfade .6s ease both}
.cs-portal.citizen{border-top:6px solid #C1292E}
.cs-portal.officer{border-top:6px solid #235789;animation-delay:.1s}
.cs-portal:hover{transform:translateY(-5px);box-shadow:0 16px 34px rgba(35,87,137,.2)}
.cs-portal .head{display:flex;align-items:center;gap:16px}
.cs-portal h2{margin:0;font-size:26px;font-weight:800;color:#1F2D3D}
.cs-portal .tag{font-size:14px;color:#5b6b7b;margin-top:2px}
.cs-portal ul{margin:16px 0 4px 0;padding:0;list-style:none}
.cs-portal li{display:flex;gap:10px;align-items:center;margin:9px 0;color:#3b4b5b;font-size:15px}
.cs-portal li svg{color:#2E7D32;flex:0 0 18px}
.cs-attn{display:flex;gap:14px;align-items:flex-start;border:1px solid #d5deea;border-radius:14px;padding:14px 16px;background:#fff;color:#1F2D3D;margin:0 0 12px 0}
.cs-attn .n{font-size:28px;font-weight:800;line-height:1}
.cs-attn .t{font-weight:700;color:#235789;margin-top:2px}
.cs-attn .s{font-size:13px;color:#5b6b7b;margin-top:2px}
.cs-ai{display:flex;gap:14px;align-items:center;border:1px solid #cfe0f3;background:linear-gradient(120deg,#eef5fc,#fdf3f3);border-radius:14px;padding:14px 18px;margin:8px 0 12px 0;color:#1F2D3D;animation:csfade .4s ease both}
.cs-ai b{color:#C1292E}
.cs-ai .sm{font-size:13px;color:#5b6b7b;margin-top:2px}
.cs-donutwrap{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin:6px 0 16px 0}
.cs-donut{position:relative;width:170px;height:170px;border-radius:50%;animation:cspop .6s ease both}
.cs-donut .hole{position:absolute;top:26px;left:26px;right:26px;bottom:26px;border-radius:50%;background:#FDFFFC;display:flex;flex-direction:column;align-items:center;justify-content:center}
.cs-donut .hole b{font-size:30px;color:#235789;line-height:1}
.cs-donut .hole span{font-size:11px;color:#5b6b7b;text-transform:uppercase;letter-spacing:.06em;margin-top:4px}
.cs-dleg div{margin:7px 0;font-size:14px;color:#1F2D3D}
.cs-bar .fl{transform-origin:left center;animation:csgrow .9s ease both}
.cs-stop{animation:cspop .45s ease both}
.cs-ts{animation:csfade .5s ease both}
.cs-ts:nth-child(2){animation-delay:.1s}
.cs-ts:nth-child(3){animation-delay:.2s}
.cs-step .n{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;line-height:1}
.cs-mini .cs-ibub{width:40px;height:40px;flex:0 0 40px}
"""


def _one_line(text):
    return "".join(line.strip() for line in text.splitlines())


def css():
    return "<style>" + _one_line(_CSS) + "</style>"


def icon(name, size=22):
    """An inline line icon (uses the surrounding text colour). Unknown names give an empty string."""
    body = _ICONS.get(name)
    if not body:
        return ""
    return (f'<svg width="{int(size)}" height="{int(size)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


def bubble(name, tone="", size=22, big=False):
    cls = " ".join(x for x in ("cs-ibub", tone, "big" if big else "") if x)
    return f'<span class="{cls}">{icon(name, size)}</span>'


def section(icon_name, text):
    return f'<div class="cs-sect">{bubble(icon_name, "red", 18)}{escape(text)}</div>'

def badge(level):
    level = level if level in COLORS else "low"
    pulse = " crit" if level == "critical" else ""
    return f'<span class="cs-badge{pulse}" style="background:{COLORS[level]};color:{TEXT_ON.get(level, "#fff")}">{escape(level)}</span>'


def hero(title, subtitle, tone="red", pill="", icon_name=""):
    extra = f'<span class="pill">{escape(pill)}</span>' if pill else ""
    big = f'<span class="bigic">{icon(icon_name, 96)}</span>' if icon_name else ""
    return (f'<div class="cs-hero live {"blue" if tone == "blue" else ""}"><span class="blob b1"></span><span class="blob b2"></span>'
            f'{big}<h1>{escape(title)}</h1><p>{escape(subtitle)}</p>{extra}</div>')


def page_header(title, subtitle=""):
    sub = f'<p class="cs-sub">{escape(subtitle)}</p>' if subtitle else ""
    return f'<p class="cs-title">{escape(title)}</p>{sub}'


def kpis(items):
    """items: list of (label, value, tone, note) with tone 'blue' or 'red'; note may be ''."""
    cards = []
    for item in items:
        label, value, tone, note = item[:4]
        icon_name = item[4] if len(item) > 4 else ""
        extra = f'<div class="d">{escape(str(note))}</div>' if note else ""
        lead = bubble(icon_name, "red" if tone == "red" else "", 22) if icon_name else ""
        cards.append(f'<div class="cs-kpi {"red" if tone == "red" else ""}">{lead}<div class="bd"><div class="v">{escape(str(value))}</div>'
                     f'<div class="l">{escape(str(label))}</div>{extra}</div></div>')
    return f'<div class="cs-kpis">{"".join(cards)}</div>'


def flow():
    steps = [("eye", "Perceive", "Reads the complaint, predicts its category and priority, and spots duplicate reports."),
             ("layers", "Reason", "Applies editable rules to choose the department and explains every decision."),
             ("truck", "Act", "Assigns crews and plans routes so urgent problems are reached before their deadlines.")]
    out = []
    for i, (n, title, text) in enumerate(steps):
        out.append(f'<div class="cs-step"><span class="n">{icon(n, 16)}</span><span class="t">{title}</span><p>{escape(text)}</p></div>')
        if i < len(steps) - 1:
            out.append('<div class="cs-arrow">&#10140;</div>')
    return f'<div class="cs-flow">{"".join(out)}</div>'


def _meta(row, extra=""):
    parts = [f"Ward {row['ward']}", escape(str(row["category"])), escape(str(row["department"]))]
    if extra:
        parts.append(extra)
    return " &middot; ".join(parts)


def complaint_card(row, duplicates=0, age_days=0):
    color = COLORS.get(row["priority"], BLUE)
    extra = f"open {age_days} day(s)"
    if duplicates:
        extra += f" &middot; {duplicates} duplicate report(s) merged"
    lead = bubble(CATEGORY_ICON.get(row["category"], "clipboard"), "", 20)
    return (f'<div class="cs-card" style="border-left-color:{color}"><div class="top"><span class="l">{lead}'
            f'<span class="id">Complaint #{row["id"]}</span></span>{badge(row["priority"])}</div><div class="txt">{escape(row["text"])}</div>'
            f'<div class="meta">{_meta(row, extra)}</div></div>')


def mini_card(row):
    color = COLORS.get(row["priority"], BLUE)
    text = row["text"] if len(row["text"]) <= 90 else row["text"][:87] + "..."
    age = f"{row.get('age_days', 0)} day(s) old"
    lead = bubble(CATEGORY_ICON.get(row["category"], "clipboard"), "", 20)
    return (f'<div class="cs-mini" style="border-left-color:{color};display:flex;gap:12px;align-items:center">{lead}<div style="flex:1">'
            f'{badge(row["priority"])} <b style="color:#235789">#{row["id"]}</b><div class="txt">{escape(text)}</div>'
            f'<div class="meta">{_meta(row, age)}</div></div></div>')


def trace_html(trace, flags=()):
    """The 'why this decision' panel."""
    steps = []
    for t in trace:
        changes = "; ".join(t["changes"]) if t["changes"] else "no change"
        steps.append(f'<div class="cs-tstep"><div class="cs-tnum">{t["step"]}</div><div class="cs-tbody">'
                     f'<span class="nm">{escape(t["name"])}</span><span class="rid">{escape(t["rule"])}</span>'
                     f'<div class="why">{escape(t["why"])}</div><div class="chg">{escape(changes)}</div></div></div>')
    notes = "".join(f'<div class="cs-flag">{escape(f)}</div>' for f in flags)
    return f'<div class="cs-trace">{"".join(steps)}</div>{notes}'


def legend():
    items = "".join(f'<span><span class="cs-dot" style="background:{COLORS[l]}"></span>{l}</span>' for l in LEVELS)
    return f'<div class="cs-legend">{items}<span><span class="cs-dot" style="border:2px dashed #111;background:#fff"></span>late</span></div>'


def timeline(routes, crews, clock_time):
    """Each crew's shift as a bar (08:00 to 16:00) with one block per job, coloured by priority."""
    hours = "".join(f"<span>{clock_time(m)}</span>" for m in range(0, SHIFT_MIN, 60))
    rows = []
    for row_no, crew in enumerate(crews):
        stops = routes.get(crew.id, [])
        blocks = []
        for n, s in enumerate(stops):
            job = s["job"]
            left = min(100.0, s["arrive"] / SHIFT_MIN * 100)
            width = max(1.5, min(100 - left, job.service / SHIFT_MIN * 100))
            tip = f"#{job.id} {LEVELS[job.level]}: arrives {clock_time(s['arrive'])}, deadline {clock_time(job.deadline)}"
            if s["late"]:
                tip += " (LATE)"
            blocks.append(f'<div class="cs-stop{" late" if s["late"] else ""}" title="{escape(tip)}" '
                          f'style="left:{left:.2f}%;width:{width:.2f}%;background:{COLORS[LEVELS[job.level]]};'
                          f'color:{TEXT_ON.get(LEVELS[job.level], "#fff")};animation-delay:{row_no * 0.05 + n * 0.07:.2f}s">#{job.id}</div>')
        rows.append(f'<div class="cs-tl-row"><div class="cs-tl-name">{escape(crew.id)}<span>{escape(crew.department)}</span></div>'
                    f'<div class="cs-tl-track">{"".join(blocks)}</div></div>')
    return f'<div class="cs-tl">{"".join(rows)}<div class="cs-tl-axis">{hours}</div></div>'


def bars(items, maximum=None, marker=None):
    """Horizontal bars. items: (label, value, colour). marker: draw a vertical line at this value."""
    top = maximum or max([v for _, v, _ in items] + [1])
    rows = []
    for label, value, color in items:
        width = min(100.0, value / top * 100)
        mk = f'<div class="mk" style="left:{marker / top * 100:.1f}%"></div>' if marker is not None else ""
        shown = f"{value:.2f}" if isinstance(value, float) and value != int(value) else f"{value:g}"
        rows.append(f'<div class="cs-bar"><div class="lb">{escape(str(label))}</div><div class="tr">'
                    f'<div class="fl" style="width:{width:.1f}%;background:{color}"></div>{mk}</div><div class="vl">{shown}</div></div>')
    return f'<div class="cs-bars">{"".join(rows)}</div>'


def public_steps():
    steps = [("pin", "Report", "Pin the problem on the map, describe it, and add a photo if you can."),
             ("sparkle", "We route it", "CivicSense works out what it is, how urgent it is, and which department must act."),
             ("search", "Track it", "Use your tracking code at any time to see where your complaint stands.")]
    out = []
    for i, (n, title, text) in enumerate(steps):
        out.append(f'<div class="cs-step"><span class="n">{icon(n, 16)}</span><span class="t">{title}</span><p>{escape(text)}</p></div>')
        if i < len(steps) - 1:
            out.append('<div class="cs-arrow">&#10140;</div>')
    return f'<div class="cs-flow">{"".join(out)}</div>'


def tracker(stage, labels, current_label=None):
    """Progress of a complaint: stages before `stage` are done, `stage` is current (all done once resolved)."""
    parts = []
    for i, label in enumerate(labels, 1):
        finished = i < stage or (i == stage == len(labels))
        state = "done" if finished else ("now" if i == stage else "")
        text = current_label if (i == stage and current_label and not finished) else label
        mark = "&#10003;" if finished else str(i)
        parts.append(f'<div class="cs-ts {state}"><div class="dot">{mark}</div>{escape(text)}</div>')
    return f'<div class="cs-track">{"".join(parts)}</div>'


def code_box(code):
    return f'<div class="cs-codewrap"><span class="cs-code">{escape(code)}</span></div>'


def location_card(lat, lon, source, ok, note="", nearby=()):
    if ok:
        msg = escape(note) if note else "Inside the service area"
    else:
        msg = "Outside the area CivicSense serves. Please choose a place inside the red rectangle on the map."
    chip = ""
    if ok and nearby:
        names = ", ".join(f"{escape(p['name'])} ({escape(PLACE_LABEL.get(p['type'], p['type']))}, {p['distance_m']:.0f} m)" for p in nearby[:3])
        chip = f'<div class="near">Near {names}. Problems here are given extra priority.</div>'
    return (f'<div class="cs-loc{"" if ok else " bad"}"><div class="src">{escape(source)}</div>'
            f'<div class="coords">{float(lat):.5f}, {float(lon):.5f}</div><div>{msg}</div>{chip}</div>')


def portal_card(kind):
    """The two big choices on the landing page. kind: 'citizen' or 'officer'."""
    if kind == "citizen":
        head, tag, ic, tone = "I am a citizen", "Report a problem in your area and follow it to the end", "users", "red"
        points = ["Pin the exact spot on a map", "Add a photo to show what is wrong", "Get a tracking code, no account needed",
                  "Tell us if the repair really worked"]
    else:
        head, tag, ic, tone = "I am city staff", "Officers and field crews sign in with their account", "shield", ""
        points = ["Officers: review, prioritize and schedule complaints", "Field crews: see today's route and mark jobs done",
                  "Details and photos stay behind your login", "Every action is recorded"]
    items = "".join(f"<li>{icon('check', 18)}{escape(p)}</li>" for p in points)
    return (f'<div class="cs-portal {kind}"><div class="head">{bubble(ic, tone, 30, big=True)}<div><h2>{escape(head)}</h2>'
            f'<div class="tag">{escape(tag)}</div></div></div><ul>{items}</ul></div>')


def portals():
    return f'<div class="cs-portals">{portal_card("citizen")}{portal_card("officer")}</div>'


def attention_card(icon_name, count, title, subtitle, tone="red"):
    color = {"red": RED, "amber": "#EF6C00", "blue": BLUE}.get(tone, BLUE)
    return (f'<div class="cs-attn">{bubble(icon_name, {"red": "red", "amber": "amber"}.get(tone, ""), 22)}<div>'
            f'<div class="n" style="color:{color}">{escape(str(count))}</div><div class="t">{escape(title)}</div>'
            f'<div class="s">{escape(subtitle)}</div></div></div>')


def ai_preview(category, confidence, department, needs_review):
    """A live preview of what the AI makes of a complaint while it is being written."""
    if needs_review:
        body = ("<b>Not sure yet.</b> Add a few more details, such as what is wrong and where. "
                "An officer will check it if it stays unclear.")
        sub = "Preview only. Nothing is sent until you submit."
    else:
        body = (f'Looks like a <b>{escape(category)}</b> problem. It would go to <b>{escape(department)}</b>.')
        sub = f"{confidence:.0%} sure. Preview only; nothing is sent until you submit."
    return (f'<div class="cs-ai">{bubble("sparkle", "red", 22)}<div>{body}<div class="sm">{escape(sub)}</div></div></div>')


def donut(items, center_value, center_label):
    """A ring chart. items: (label, value, colour)."""
    total = sum(v for _, v, _ in items)
    if total <= 0:
        ring = "#E8EEF6"
    else:
        stops, start = [], 0.0
        for _, value, color in items:
            end = start + value / total * 100
            stops.append(f"{color} {start:.2f}% {end:.2f}%")
            start = end
        ring = "conic-gradient(" + ",".join(stops) + ")"
    legend = "".join(f'<div><span class="cs-dot" style="background:{c}"></span>{escape(str(l))}: <b>{v:g}</b></div>' for l, v, c in items)
    return (f'<div class="cs-donutwrap"><div class="cs-donut" style="background:{ring}"><div class="hole">'
            f'<b>{escape(str(center_value))}</b><span>{escape(str(center_label))}</span></div></div>'
            f'<div class="cs-dleg">{legend}</div></div>')


# ---------------------------------------------------------------- hotspot maps (plain SVG: no map library, no internet)
PLACE_STYLE = {"school": ("#3949AB", "S"), "hospital": ("#00838F", "H"), "market": ("#8E24AA", "M"),
               "bus_stand": ("#6D4C41", "B"), "railway_station": ("#546E7A", "R"), "temple": ("#AD1457", "T"),
               "park": ("#7CB342", "P")}
PLACE_LABEL = {"school": "school", "hospital": "hospital", "market": "market", "bus_stand": "bus stand",
               "railway_station": "railway station", "temple": "temple", "park": "park"}
_MAP = 640
_PAD = 26


_lats = [c[0] for c in WARD_CENTRES.values()]
_lons = [c[1] for c in WARD_CENTRES.values()]
WARD_BOX = {"lat_min": min(_lats) - 0.011, "lat_max": max(_lats) + 0.011, "lon_min": min(_lons) - 0.011, "lon_max": max(_lons) + 0.011}


def _xy(lat, lon, box=None):
    a = box or SERVICE_AREA
    x = _PAD + (lon - a["lon_min"]) / (a["lon_max"] - a["lon_min"]) * (_MAP - 2 * _PAD)
    y = _PAD + (a["lat_max"] - lat) / (a["lat_max"] - a["lat_min"]) * (_MAP - 2 * _PAD)
    return min(max(x, _PAD), _MAP - _PAD), min(max(y, _PAD), _MAP - _PAD)


def _svg_open(label, uid):
    return (f'<svg viewBox="0 0 {_MAP} {_MAP}" width="100%" role="img" aria-label="{escape(label)}" '
            f'style="max-width:720px;display:block;border-radius:14px;border:1px solid #d5deea;background:#F4F7FB">'
            f'<defs><radialGradient id="csglow{uid}"><stop offset="0" stop-color="#C1292E" stop-opacity="0.55"/>'
            f'<stop offset="1" stop-color="#C1292E" stop-opacity="0"/></radialGradient></defs>')


def _ward_labels():
    return "".join(f'<text x="{_xy(*c)[0]:.0f}" y="{_xy(*c)[1]:.0f}" text-anchor="middle" font-size="30" font-weight="800" '
                   f'fill="#e3eaf3">{w}</text>' for w, c in WARD_CENTRES.items())


def hotspot_svg(points, places=(), roads=(), show_density=True, show_places=True, uid="a"):
    """Officer hotspot view. points: dicts with id, lat, lon, priority, category. Only fixed words go into tooltips."""
    out = [_svg_open("Hotspot map of open complaints", uid)]
    for (la1, lo1), (la2, lo2) in roads:
        (x1, y1), (x2, y2) = _xy(la1, lo1), _xy(la2, lo2)
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#d9e2ee" stroke-width="3" stroke-linecap="round"/>')
    out.append(_ward_labels())
    if show_density:
        for p in points:
            level = LEVELS.index(p["priority"]) if p["priority"] in LEVELS else 0
            x, y = _xy(p["lat"], p["lon"])
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{28 + 9 * level}" fill="url(#csglow{uid})" opacity="{0.35 + 0.18 * level:.2f}"/>')
    if show_places:
        for pl in places:
            color, letter = PLACE_STYLE.get(pl["type"], ("#546E7A", "?"))
            x, y = _xy(pl["lat"], pl["lon"])
            out.append(f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="10" fill="{color}" stroke="#fff" stroke-width="2"/>'
                       f'<text x="{x:.0f}" y="{y:.0f}" dy="3.5" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">{letter}</text>'
                       f'<title>{escape(pl["name"])} ({escape(PLACE_LABEL.get(pl["type"], pl["type"]))})</title></g>')
    for p in points:
        x, y = _xy(p["lat"], p["lon"])
        color = COLORS.get(p["priority"], BLUE)
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5.5" fill="{color}" stroke="#fff" stroke-width="1.5">'
                   f'<title>#{int(p["id"])} {escape(str(p["priority"]))}: {escape(str(p["category"]))}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def ward_map_svg(counts, hidden=(), uid="w"):
    """Citizen view: one bubble per ward, sized by the number of problems. No exact locations are drawn."""
    out = [_svg_open("Problems reported per ward", uid)]
    top = max(counts.values(), default=1)
    for ward in hidden:
        x, y = _xy(*WARD_CENTRES[ward], box=WARD_BOX)
        out.append(f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="20" fill="none" stroke="#b9c6d6" stroke-width="2" stroke-dasharray="4 4"/>'
                   f'<text x="{x:.0f}" y="{y + 36:.0f}" text-anchor="middle" font-size="13" fill="#9aa9bb">Ward {int(ward)}</text>'
                   f'<title>Ward {int(ward)}: hidden to protect privacy (fewer than 3 problems)</title></g>')
    for ward, n in counts.items():
        x, y = _xy(*WARD_CENTRES[ward], box=WARD_BOX)
        r = 18 + 38 * (n / top) ** 0.5
        out.append(f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="{BLUE}" fill-opacity="0.55" stroke="{BLUE}" stroke-width="2"/>'
                   f'<text x="{x:.0f}" y="{y:.0f}" dy="7" text-anchor="middle" font-size="22" font-weight="800" fill="#fff">{int(n)}</text>'
                   f'<text x="{x:.0f}" y="{y + r + 16:.0f}" text-anchor="middle" font-size="13" fill="#4a5a6a">Ward {int(ward)}</text>'
                   f'<title>Ward {int(ward)}: {int(n)} problems</title></g>')
    out.append("</svg>")
    return "".join(out)


def map_legend(show_places=True):
    pri = "".join(f'<span><span class="cs-dot" style="background:{COLORS[l]};border-radius:50%"></span>{l}</span>' for l in LEVELS)
    pl = ""
    if show_places:
        pl = "".join(f'<span><span class="g" style="background:{c}">{ch}</span>{PLACE_LABEL[t]}</span>' for t, (c, ch) in PLACE_STYLE.items())
    return f'<div class="cs-maplegend">{pri}{pl}</div>'


def priority_matrix(rows, columns):
    """rows: from modules.guide.matrix(); columns: (key, heading). Cells that rank higher than an ordinary street are shaded."""
    head = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        base = row[columns[0][0]]["score"]
        cells = "".join(f'<td class="{"up" if row[k]["score"] > base else ""}">{badge(row[k]["priority"])}'
                        f'<span class="sc">score {row[k]["score"]:.0f}</span></td>' for k, _ in columns)
        body.append(f"<tr><td>{escape(row['problem'])}</td>{cells}</tr>")
    return f'<div class="cs-mx"><table><thead><tr><th>Problem</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


# ---------------------------------------------------------------- real street maps (Leaflet, loaded in the browser)
LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

# Shared start of every map page. Text from the data is only ever put in with textContent, never as HTML.
_LEAFLET_PRELUDE = (
    "function tip(t){var d=document.createElement('div');d.textContent=t;return d;}"
    "var map=L.map('map');"
    "var light=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{maxZoom:19,subdomains:'abcd',"
    "attribution:'&copy; OpenStreetMap contributors &copy; CARTO'});"
    "var osm=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'});"
    "light.addTo(map);L.control.layers({'Light map':light,'OpenStreetMap':osm}).addTo(map);"
    "var a=DATA.area;"
    "L.rectangle([[a.lat_min,a.lon_min],[a.lat_max,a.lon_max]],{color:'#C1292E',weight:2,fill:false,dashArray:'6 6'})"
    ".bindTooltip(tip('Service area')).addTo(map);"
    "function badge(color,letter){var e=document.createElement('div');e.className='pl';e.style.background=color;"
    "e.textContent=letter;return e;}"
)

_LEAFLET_HOTSPOTS = (
    "var pts=DATA.points;"
    "if(DATA.density){pts.forEach(function(p){L.circle([p.lat,p.lon],{radius:170+60*p.level,stroke:false,"
    "fillColor:'#C1292E',fillOpacity:0.10+0.05*p.level}).addTo(map);});}"
    "pts.forEach(function(p){L.circleMarker([p.lat,p.lon],{radius:7,color:'#fff',weight:1.5,fillColor:p.color,fillOpacity:0.95})"
    ".bindTooltip(tip('#'+p.id+' '+p.priority+': '+p.category)).addTo(map);});"
    "DATA.places.forEach(function(pl){L.marker([pl.lat,pl.lon],{icon:L.divIcon({className:'',html:badge(pl.color,pl.letter),"
    "iconSize:[22,22],iconAnchor:[11,11]})}).bindTooltip(tip(pl.name+' ('+pl.kind+')')).addTo(map);});"
    "if(pts.length){map.fitBounds(L.latLngBounds(pts.map(function(p){return [p.lat,p.lon];})).pad(0.25));}"
    "else{map.setView([(a.lat_min+a.lat_max)/2,(a.lon_min+a.lon_max)/2],13);}"
    "document.getElementById('note').textContent=pts.length+' open complaints. Hover a dot or place for details.';"
)

_LEAFLET_WARDS = (
    "DATA.hidden.forEach(function(w){L.circle([w.lat,w.lon],{radius:200,color:'#9aa9bb',weight:2,dashArray:'4 4',fill:false})"
    ".bindTooltip(tip('Ward '+w.ward+': hidden to protect privacy (fewer than 3 problems)')).addTo(map);});"
    "DATA.wards.forEach(function(w){L.circle([w.lat,w.lon],{radius:w.radius,color:'#235789',weight:2,fillColor:'#235789',fillOpacity:0.45})"
    ".bindTooltip(tip('Ward '+w.ward+': '+w.count+' problems')).addTo(map);"
    "L.marker([w.lat,w.lon],{icon:L.divIcon({className:'',html:badge('#235789',String(w.count)),iconSize:[22,22],iconAnchor:[11,11]})}).addTo(map);});"
    "var all=DATA.wards.concat(DATA.hidden);"
    "map.fitBounds(L.latLngBounds(all.map(function(w){return [w.lat,w.lon];})).pad(0.3));"
    "document.getElementById('note').textContent='Totals per ward only. No exact places are shown.';"
)


def _leaflet_page(data, body):
    """A complete HTML page with a Leaflet map. Streamlit shows it with components.html. Needs internet for the map tiles."""
    payload = json.dumps(data).replace("</", "<\\/").replace("<!--", "<\\!--")        # nothing in the data can close the script tag
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<link rel='stylesheet' href='{LEAFLET_CSS}'><style>html,body,#map{{height:100%;margin:0;font-family:Arial,sans-serif}}"
            ".pl{width:22px;height:22px;border-radius:50%;color:#fff;font-weight:700;font-size:12px;line-height:22px;text-align:center;"
            "border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45);box-sizing:content-box}"
            ".note{position:absolute;z-index:1000;left:10px;bottom:24px;background:rgba(255,255,255,.93);padding:6px 10px;"
            "border-radius:8px;font-size:12px;color:#33475b}</style></head>"
            f"<body><div id='map'></div><div class='note' id='note'></div><script src='{LEAFLET_JS}'></script>"
            f"<script>var DATA={payload};{_LEAFLET_PRELUDE}{body}</script></body></html>")


def leaflet_hotspot_html(points, places=(), show_density=True, show_places=True):
    """Officer hotspot map on a real street map. points: dicts with id, lat, lon, priority, category."""
    data = {
        "area": dict(SERVICE_AREA), "density": bool(show_density),
        "points": [{"id": int(p["id"]), "lat": float(p["lat"]), "lon": float(p["lon"]), "priority": str(p["priority"]),
                    "category": str(p["category"]), "level": LEVELS.index(p["priority"]) if p["priority"] in LEVELS else 0,
                    "color": COLORS.get(p["priority"], BLUE)} for p in points],
        "places": [{"name": str(pl["name"]), "kind": PLACE_LABEL.get(pl["type"], str(pl["type"])), "lat": float(pl["lat"]),
                    "lon": float(pl["lon"]), "color": PLACE_STYLE.get(pl["type"], ("#546E7A", "?"))[0],
                    "letter": PLACE_STYLE.get(pl["type"], ("#546E7A", "?"))[1]} for pl in (places if show_places else [])],
    }
    return _leaflet_page(data, _LEAFLET_HOTSPOTS)


def leaflet_ward_html(counts, hidden=()):
    """Citizen map: one circle per ward at the ward centre, sized by the number of problems. No complaint locations."""
    top = max(counts.values(), default=1)
    data = {
        "area": dict(SERVICE_AREA), "density": False, "points": [], "places": [],
        "wards": [{"ward": int(w), "lat": WARD_CENTRES[w][0], "lon": WARD_CENTRES[w][1], "count": int(n),
                   "radius": round(220 + 380 * (n / top) ** 0.5)} for w, n in counts.items()],
        "hidden": [{"ward": int(w), "lat": WARD_CENTRES[w][0], "lon": WARD_CENTRES[w][1]} for w in hidden],
    }
    return _leaflet_page(data, _LEAFLET_WARDS)


def confusion_matrix(labels, matrix, true_label="Actual", predicted_label="Predicted by the model"):
    """A confusion matrix as a table. Rows: the right answer. Columns: what the model said. Green = right, red = wrong."""
    head = "".join(f"<th>{escape(str(l))}</th>" for l in labels)
    body = []
    for i, row in enumerate(matrix):
        total = sum(row) or 1
        cells = []
        for j, n in enumerate(row):
            strength = n / total
            color = f"rgba(46,125,50,{0.15 + 0.7 * strength:.2f})" if i == j else f"rgba(198,40,40,{0.10 + 0.8 * strength:.2f})"
            cells.append(f'<td style="background:{color if n else "#F4F7FB"}">{int(n) if n else ""}</td>')
        body.append(f'<tr><td class="rowh">{escape(str(labels[i]))}</td>{"".join(cells)}</tr>')
    return (f'<div class="cs-cm"><div style="font-size:12px;color:#4a5a6a;margin-left:92px">{escape(predicted_label)}</div>'
            f'<table><thead><tr><th>{escape(true_label)}</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


STATUS_LABEL = {"open": "open", "in_progress": "\U0001F527 in progress", "resolved": "resolved"}


def updates_timeline(updates):
    """The story of a complaint for the citizen: one line per update, oldest first."""
    items = "".join(f'<div class="cs-up"><span class="dot"></span><div class="t">{escape(str(u["when"]))}</div>'
                    f'<div class="m">{escape(str(u["message"]))}</div></div>' for u in updates)
    return f'<div class="cs-ups">{items}</div>'


def stop_card(row, arrive, deadline, late=False, number=None, near=()):
    """One job on a crew's route (phone friendly)."""
    color = COLORS.get(row["priority"], BLUE)
    lead = bubble(CATEGORY_ICON.get(row["category"], "clipboard"), "", 20)
    label = f"{number}. " if number else ""
    maps = f"https://www.google.com/maps?q={float(row['lat']):.6f},{float(row['lon']):.6f}"
    chip = ""
    if near:
        names = ", ".join(f"{escape(p['name'])} ({escape(PLACE_LABEL.get(p['type'], p['type']))})" for p in near[:2])
        chip = f'<div class="near-chip" style="margin-top:8px;display:inline-block;background:#FFF4E5;color:#7a3e00;border-radius:8px;padding:4px 10px;font-size:13px">Near {names}</div>'
    late_tag = ' <b style="color:#C62828">LATE</b>' if late else ""
    return (f'<div class="cs-card" style="border-left-color:{color}"><div class="top"><span class="l">{lead}'
            f'<span class="id">{escape(label)}{escape(str(arrive))}</span></span>{badge(row["priority"])}</div>'
            f'<div class="txt">{escape(row["text"])}</div>'
            f'<div class="meta">{escape(str(row["category"]))} &middot; due by {escape(str(deadline))}{late_tag}</div>{chip}'
            f'<div class="cs-stop-link" style="margin-top:8px"><a href="{maps}" target="_blank" rel="noopener noreferrer">Open in Maps</a></div></div>')
