#!/usr/bin/env python3
"""
bright-dashboard/generate.py
WP REST API + 事前取得データ → docs/index.html を生成
実行: python3 generate.py
"""
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import dotenv_values

ENV = dotenv_values(os.path.expanduser("~/bright-eyecatch/.env"))
WP_BASE = ENV.get("WP_BASE_URL", "https://law-bright.com")
WP_USER = ENV.get("WP_USER", "bright-marketing")
WP_PASS = ENV.get("WP_APP_PASSWORD", "")
AUTH = (WP_USER, WP_PASS)

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

# ジャンル定義（cat = フィルターキー）
CPTS = [
    # 企業法務
    {"slug": "legaladvisor",  "label": "顧問弁護士",   "color": "#10b981", "cat": "komon"},
    {"slug": "manda",         "label": "M&A",          "color": "#fbbf24", "cat": "komon"},
    {"slug": "employee",      "label": "問題社員",     "color": "#ec4899", "cat": "komon"},
    {"slug": "it",            "label": "IT法務",       "color": "#0ea5e9", "cat": "komon"},
    {"slug": "realestate",    "label": "不動産",       "color": "#a78bfa", "cat": "komon"},
    {"slug": "consultation",  "label": "相談事例",     "color": "#f97316", "cat": "komon"},
    {"slug": "litigation",    "label": "訴訟",         "color": "#84cc16", "cat": "komon"},
    {"slug": "dispute",       "label": "紛争解決",     "color": "#60a5fa", "cat": "komon"},
    # 労災
    {"slug": "labor",         "label": "労災",         "color": "#ef4444", "cat": "rosai"},
    # 交通事故
    {"slug": "kotuziko",      "label": "交通事故",     "color": "#f59e0b", "cat": "kotsu"},
    # その他
    {"slug": "pages",         "label": "固定ページ",   "color": "#6366f1", "cat": "other"},
    {"slug": "posts",         "label": "ブログ記事",   "color": "#8b5cf6", "cat": "other"},
    {"slug": "glossary",      "label": "法律用語集",   "color": "#3b82f6", "cat": "other"},
    {"slug": "download",      "label": "資料DL",       "color": "#14b8a6", "cat": "other"},
    {"slug": "inheritance",   "label": "相続",         "color": "#fb7185", "cat": "other"},
    {"slug": "debt",          "label": "債務整理",     "color": "#34d399", "cat": "other"},
]

# GSCページのジャンル判定
def page_cat(url: str) -> str:
    if "/labor-accident/" in url or "/rosai/" in url:
        return "rosai"
    if "/kotuziko/" in url or "/kotsujiko/" in url:
        return "kotsu"
    if "/corporationlaw/" in url or "/legaladvisor/" in url or "/komon/" in url:
        return "komon"
    return "other"

TASKS = [
    {"name": "交通事故SEO 200本量産",        "status": "進行中", "detail": "publish 79本／draft残34本",                         "badge": "yellow", "cat": "kotsu"},
    {"name": "アイキャッチ差し替え（労災）",  "status": "進行中", "detail": "このチャット系列で進行中",                          "badge": "yellow", "cat": "rosai"},
    {"name": "GBP API 申請",                 "status": "完了",   "detail": "✅ 承認完了（2026-05-14）API稼働確認済",             "badge": "green",  "cat": "other"},
    {"name": "AppSheet REST API（Bot連携）",  "status": "完了",   "detail": "✅ 送付状Modalで本番稼働中（rev 00057-pzl）",         "badge": "green",  "cat": "other"},
    {"name": "マーケ連結レポート",            "status": "完了",   "detail": "✅ marketing_attribution.py 月次cron稼働中",          "badge": "green",  "cat": "other"},
    {"name": "マーケ連結 Phase 2",           "status": "未着手", "detail": "CF7 hidden 8項目→AppSheet 流し込みが前提",            "badge": "gray",   "cat": "other"},
    {"name": "Amazon対策LP・広告",           "status": "進行中", "detail": "月予算20万・高LTVセラー特化／API申請中",             "badge": "yellow", "cat": "komon"},
    {"name": "23条照会自動化",               "status": "未着手", "detail": "設計完了・Phase 1実装待ち",                          "badge": "gray",   "cat": "komon"},
    {"name": "NTA法人番号API（DM営業）",     "status": "待機中", "detail": "承認見込 2026-06-03（リマインダー設定済）",           "badge": "blue",   "cat": "other"},
    {"name": "PMI/DD v2 リライト残12本",     "status": "待機中", "detail": "30日後評価ジョブ at#3（2026-06-02 実行）",           "badge": "blue",   "cat": "komon"},
]

LAWYERS = [
    {"name": "和氣 良浩",  "role": "代表弁護士",           "dept": "全般",   "cat": "other"},
    {"name": "山中 先生",  "role": "弁護士",               "dept": "全般",   "cat": "other"},
    {"name": "嶋本 先生",  "role": "弁護士",               "dept": "企業法務","cat": "komon"},
    {"name": "有本 先生",  "role": "弁護士",               "dept": "全般",   "cat": "other"},
    {"name": "松本 洋明",  "role": "弁護士（交通事故主任）","dept": "交通事故","cat": "kotsu"},
    {"name": "福本 先生",  "role": "弁護士",               "dept": "全般",   "cat": "other"},
    {"name": "笹野 皓平",  "role": "弁護士（労災部部長）", "dept": "労災",   "cat": "rosai"},
]


def fetch_cpt_counts():
    results = []
    for cpt in CPTS:
        slug = cpt["slug"]
        pub = draft = 0
        try:
            r = requests.head(f"{WP_BASE}/wp-json/wp/v2/{slug}?per_page=1&status=publish", auth=AUTH, timeout=10)
            pub = int(r.headers.get("X-WP-Total", 0))
        except Exception:
            pass
        try:
            r = requests.head(f"{WP_BASE}/wp-json/wp/v2/{slug}?per_page=1&status=draft", auth=AUTH, timeout=10)
            draft = int(r.headers.get("X-WP-Total", 0))
        except Exception:
            pass
        results.append({**cpt, "publish": pub, "draft": draft, "total": pub + draft})
    return results


def generate_html(cpt_data, ga4_data, gsc_data, gsc_pages):
    total_pub   = sum(c["publish"] for c in cpt_data)
    total_draft = sum(c["draft"]   for c in cpt_data)

    ga4_sessions    = sum(int(r["sessions"])              for r in ga4_data)
    ga4_conversions = sum(int(float(r["conversions"]))    for r in ga4_data)

    ga4_labels        = [r["date"][4:6]+"/"+r["date"][6:] for r in ga4_data]
    ga4_sessions_vals = [int(r["sessions"])               for r in ga4_data]
    ga4_conv_vals     = [int(float(r["conversions"]))     for r in ga4_data]

    gsc_labels = [d["date"][5:] for d in gsc_data]
    gsc_clicks = [d["clicks"]   for d in gsc_data]
    gsc_imps   = [d["impressions"] for d in gsc_data]

    gsc_total_clicks = sum(gsc_clicks)
    gsc_total_imps   = sum(gsc_imps)
    gsc_avg_ctr      = round(gsc_total_clicks / gsc_total_imps * 100, 2) if gsc_total_imps else 0
    gsc_avg_pos      = round(sum(d["position"]*d["clicks"] for d in gsc_data) / gsc_total_clicks, 1) if gsc_total_clicks else 0

    # CPT ドーナツ用（cat別に集計）
    cat_pub = {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0}
    cat_draft = {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0}
    for c in cpt_data:
        cat_pub[c["cat"]]   += c["publish"]
        cat_draft[c["cat"]] += c["draft"]

    # カテゴリ別 KPI（GSCページデータから集計）
    cat_metrics = {}
    for cat in ["all", "komon", "rosai", "kotsu", "other"]:
        pg = [p for p in gsc_pages if cat == "all" or page_cat(p["page"]) == cat]
        cl  = sum(p["clicks"] for p in pg)
        im  = sum(p["impressions"] for p in pg)
        ctr = round(cl / im * 100, 2) if im else 0
        pos = round(sum(p["position"] * p["clicks"] for p in pg) / cl, 1) if cl else 0
        pub = sum(c["publish"] for c in cpt_data if cat == "all" or c["cat"] == cat)
        dft = sum(c["draft"]   for c in cpt_data if cat == "all" or c["cat"] == cat)
        cat_metrics[cat] = {"clicks": cl, "imps": im, "ctr": ctr, "pos": pos, "pub": pub, "draft": dft}
    cat_metrics_js = json.dumps(cat_metrics)

    # 記事ステータス行
    cpt_rows = ""
    for c in sorted(cpt_data, key=lambda x: -x["publish"]):
        if c["total"] == 0:
            continue
        pct = round(c["publish"] / c["total"] * 100) if c["total"] else 0
        bar = f'<div class="w-full bg-gray-100 rounded-full h-2"><div class="h-2 rounded-full" style="width:{pct}%;background:{c["color"]}"></div></div>'
        cat_label = {"komon":"企業法務","rosai":"労災","kotsu":"交通事故","other":"その他"}[c["cat"]]
        cat_colors = {"komon":"bg-emerald-100 text-emerald-700","rosai":"bg-red-100 text-red-700","kotsu":"bg-amber-100 text-amber-700","other":"bg-slate-100 text-slate-600"}
        badge_cls = cat_colors[c["cat"]]
        cpt_rows += f"""
        <tr class="hover:bg-gray-50 transition-colors cpt-row" data-cat="{c['cat']}">
          <td class="px-4 py-3 font-medium text-gray-800">{c['label']}</td>
          <td class="px-4 py-3"><span class="inline-block {badge_cls} text-xs font-semibold px-2 py-1 rounded-full">{cat_label}</span></td>
          <td class="px-4 py-3 text-center"><span class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2 py-1 rounded-full">{c['publish']}</span></td>
          <td class="px-4 py-3 text-center"><span class="inline-block bg-yellow-100 text-yellow-800 text-xs font-semibold px-2 py-1 rounded-full">{c['draft']}</span></td>
          <td class="px-4 py-3 text-sm text-gray-600 w-40">{bar}</td>
          <td class="px-4 py-3 text-center text-xs text-gray-500">{pct}%</td>
        </tr>"""

    # 上位ページ行
    page_rows = ""
    for i, p in enumerate(gsc_pages[:20], 1):
        url = p["page"]
        short = url.replace("https://law-bright.com", "")
        ctr_pct = round(p["ctr"] * 100, 2)
        ctr_color = "text-green-700" if p["ctr"] > 0.015 else ("text-yellow-700" if p["ctr"] > 0.01 else "text-red-600")
        pos_color = "text-green-700 font-bold" if p["position"] <= 5 else ("text-yellow-700" if p["position"] <= 10 else "text-red-600")
        pc = page_cat(url)
        cat_label = {"komon":"企業法務","rosai":"労災","kotsu":"交通事故","other":"その他"}[pc]
        cat_colors = {"komon":"bg-emerald-100 text-emerald-700","rosai":"bg-red-100 text-red-700","kotsu":"bg-amber-100 text-amber-700","other":"bg-slate-100 text-slate-600"}
        badge_cls = cat_colors[pc]
        page_rows += f"""
        <tr class="hover:bg-gray-50 transition-colors page-row" data-cat="{pc}">
          <td class="px-3 py-2 text-center text-gray-400 text-sm">#{i}</td>
          <td class="px-3 py-2 text-xs text-blue-700 font-mono"><a href="{url}" target="_blank" class="hover:underline">{short}</a></td>
          <td class="px-3 py-2"><span class="inline-block {badge_cls} text-xs font-semibold px-2 py-1 rounded-full">{cat_label}</span></td>
          <td class="px-3 py-2 text-center font-semibold">{p['clicks']:,}</td>
          <td class="px-3 py-2 text-center text-gray-500">{p['impressions']:,}</td>
          <td class="px-3 py-2 text-center {ctr_color}">{ctr_pct}%</td>
          <td class="px-3 py-2 text-center {pos_color}">{p['position']}</td>
        </tr>"""

    # タスク行
    badge_map = {"green":"bg-green-100 text-green-800","yellow":"bg-yellow-100 text-yellow-800","gray":"bg-gray-100 text-gray-600","blue":"bg-blue-100 text-blue-800"}
    task_rows = ""
    for t in TASKS:
        bc = badge_map.get(t["badge"], "bg-gray-100 text-gray-600")
        cat_label = {"komon":"企業法務","rosai":"労災","kotsu":"交通事故","other":"その他"}[t["cat"]]
        cat_colors = {"komon":"bg-emerald-100 text-emerald-700","rosai":"bg-red-100 text-red-700","kotsu":"bg-amber-100 text-amber-700","other":"bg-slate-100 text-slate-600"}
        tbadge = cat_colors[t["cat"]]
        task_rows += f"""
        <tr class="hover:bg-gray-50 transition-colors task-row" data-cat="{t['cat']}">
          <td class="px-4 py-3 font-medium text-gray-800">{t['name']}</td>
          <td class="px-4 py-3"><span class="inline-block {tbadge} text-xs font-semibold px-2 py-1 rounded-full">{cat_label}</span></td>
          <td class="px-4 py-3"><span class="inline-block {bc} text-xs font-semibold px-2 py-1 rounded-full">{t['status']}</span></td>
          <td class="px-4 py-3 text-sm text-gray-600">{t['detail']}</td>
        </tr>"""

    # 弁護士カード
    lawyer_cards = ""
    for lw in LAWYERS:
        cat_border = {"komon":"border-emerald-300","rosai":"border-red-300","kotsu":"border-amber-300","other":"border-slate-200"}[lw["cat"]]
        lawyer_cards += f"""
        <div class="lawyer-card flex items-center gap-3 p-3 bg-gray-50 rounded-lg border-l-4 {cat_border}" data-cat="{lw['cat']}">
          <div class="w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-700 font-bold text-sm flex-shrink-0">{lw['name'][0]}</div>
          <div>
            <div class="font-semibold text-gray-800 text-sm">{lw['name']}</div>
            <div class="text-xs text-gray-500">{lw['role']} · {lw['dept']}</div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ブライト Webダッシュボード</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', sans-serif; }}
  .tab-btn {{ transition: all .15s; border-bottom: 3px solid transparent; }}
  .tab-btn.active {{ border-bottom: 3px solid #4f46e5; color: #4f46e5; font-weight: 700; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .kpi-card {{ transition: transform .15s; }}
  .kpi-card:hover {{ transform: translateY(-2px); }}
  .filter-btn {{ transition: all .12s; }}
  .filter-btn.active {{ background: #4f46e5; color: white; }}
  .filter-btn.active-komon {{ background: #10b981; color: white; }}
  .filter-btn.active-rosai {{ background: #ef4444; color: white; }}
  .filter-btn.active-kotsu {{ background: #f59e0b; color: white; }}
  .filter-btn.active-other {{ background: #64748b; color: white; }}
</style>
</head>
<body class="bg-gray-50 min-h-screen">

<!-- ヘッダー -->
<header class="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between flex-wrap gap-2">
    <div class="flex items-center gap-3">
      <div class="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center flex-shrink-0">
        <span class="text-white text-xs font-bold">B</span>
      </div>
      <div>
        <div class="font-bold text-gray-900 text-sm">弁護士法人ブライト</div>
        <div class="text-xs text-gray-500">Webマーケ ダッシュボード</div>
      </div>
    </div>
    <div class="flex items-center gap-3 flex-wrap">
      <a href="https://law-bright.com" target="_blank" class="text-xs text-indigo-600 hover:underline">law-bright.com ↗</a>
      <a href="https://law-bright.com/wp-admin/" target="_blank" class="text-xs text-indigo-600 hover:underline">WP管理 ↗</a>
      <span class="text-xs text-gray-400">更新: {NOW}</span>
    </div>
  </div>
</header>

<!-- ジャンルフィルター（グローバル） -->
<div class="bg-white border-b border-gray-100 sticky top-[57px] z-40">
  <div class="max-w-7xl mx-auto px-4 py-2 flex items-center gap-2 flex-wrap">
    <span class="text-xs text-gray-500 mr-1">ジャンル：</span>
    <button class="filter-btn active px-3 py-1 rounded-full text-xs font-semibold border border-gray-300" onclick="setFilter('all', this)">全体</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-emerald-300 text-emerald-700" onclick="setFilter('komon', this)">🏢 企業法務</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-red-300 text-red-700" onclick="setFilter('rosai', this)">⚠️ 労災</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-amber-300 text-amber-700" onclick="setFilter('kotsu', this)">🚗 交通事故</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-slate-300 text-slate-600" onclick="setFilter('other', this)">📋 その他</button>
  </div>
</div>

<div class="max-w-7xl mx-auto px-4 py-5">

  <!-- KPIカード -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1" id="kpi-sessions-label">セッション（30日）</div>
      <div class="text-2xl font-bold text-gray-900" id="kpi-sessions">{ga4_sessions:,}</div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-sessions-sub">GA4 · 全ジャンル計</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1">クリック（28日）</div>
      <div class="text-2xl font-bold text-gray-900" id="kpi-clicks">{gsc_total_clicks:,}</div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-clicks-sub">GSC · 平均順位 {gsc_avg_pos}位</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1">インプレッション（28日）</div>
      <div class="text-2xl font-bold text-gray-900" id="kpi-imps">{gsc_total_imps:,}</div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-imps-sub">GSC · CTR {gsc_avg_ctr}%</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1">公開記事数（WP）</div>
      <div class="text-2xl font-bold text-gray-900" id="kpi-pub">{total_pub:,}</div>
      <div class="text-xs text-yellow-600 mt-1" id="kpi-pub-sub">draft {total_draft}本 残</div>
    </div>
  </div>

  <!-- ジャンル別サマリー行 -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5" id="cat-summary">
    <div class="bg-emerald-50 border border-emerald-200 rounded-xl p-3 cat-summary-card" data-cat="komon">
      <div class="text-xs text-emerald-600 font-semibold mb-1">🏢 企業法務</div>
      <div class="text-xl font-bold text-emerald-800">{cat_pub['komon']}<span class="text-sm font-normal text-emerald-600 ml-1">本</span></div>
    </div>
    <div class="bg-red-50 border border-red-200 rounded-xl p-3 cat-summary-card" data-cat="rosai">
      <div class="text-xs text-red-600 font-semibold mb-1">⚠️ 労災</div>
      <div class="text-xl font-bold text-red-800">{cat_pub['rosai']}<span class="text-sm font-normal text-red-600 ml-1">本</span></div>
    </div>
    <div class="bg-amber-50 border border-amber-200 rounded-xl p-3 cat-summary-card" data-cat="kotsu">
      <div class="text-xs text-amber-600 font-semibold mb-1">🚗 交通事故</div>
      <div class="text-xl font-bold text-amber-800">{cat_pub['kotsu']}<span class="text-sm font-normal text-amber-600 ml-1">本</span></div>
    </div>
    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3 cat-summary-card" data-cat="other">
      <div class="text-xs text-slate-600 font-semibold mb-1">📋 その他</div>
      <div class="text-xl font-bold text-slate-800">{cat_pub['other']}<span class="text-sm font-normal text-slate-600 ml-1">本</span></div>
    </div>
  </div>

  <!-- タブ -->
  <div class="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
    <div class="border-b border-gray-200 flex overflow-x-auto">
      <button class="tab-btn active px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('kpi')">📊 KPI</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('articles')">📝 記事ステータス</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('pages')">🏆 上位ページ</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('tasks')">✅ タスク</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('info')">ℹ️ 基本情報</button>
    </div>

    <!-- KPIタブ -->
    <div id="tab-kpi" class="tab-content active p-5">
      <div class="grid md:grid-cols-2 gap-6">
        <div><div class="text-sm font-semibold text-gray-700 mb-3">セッション推移（直近30日）</div><canvas id="chartSessions" height="200"></canvas></div>
        <div><div class="text-sm font-semibold text-gray-700 mb-3">コンバージョン推移（直近30日）</div><canvas id="chartConv" height="200"></canvas></div>
        <div><div class="text-sm font-semibold text-gray-700 mb-3">GSCクリック推移（直近28日）</div><canvas id="chartClicks" height="200"></canvas></div>
        <div>
          <div class="text-sm font-semibold text-gray-700 mb-3">ジャンル別 公開記事数</div>
          <canvas id="chartCpt" height="200"></canvas>
        </div>
      </div>
    </div>

    <!-- 記事ステータスタブ -->
    <div id="tab-articles" class="tab-content">
      <div class="p-4">
        <div id="articles-empty" class="hidden text-center text-gray-400 py-8 text-sm">該当なし</div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                <th class="px-4 py-3 text-left">カテゴリ</th>
                <th class="px-4 py-3 text-left">ジャンル</th>
                <th class="px-4 py-3 text-center">公開</th>
                <th class="px-4 py-3 text-center">下書き</th>
                <th class="px-4 py-3 text-left">進捗</th>
                <th class="px-4 py-3 text-center">公開率</th>
              </tr>
            </thead>
            <tbody id="cpt-tbody" class="divide-y divide-gray-100">{cpt_rows}</tbody>
            <tfoot>
              <tr class="bg-indigo-50 font-bold">
                <td class="px-4 py-3 text-indigo-800" colspan="2">合計</td>
                <td class="px-4 py-3 text-center text-green-700" id="total-pub">{total_pub}</td>
                <td class="px-4 py-3 text-center text-yellow-700" id="total-draft">{total_draft}</td>
                <td class="px-4 py-3"></td>
                <td class="px-4 py-3 text-center text-indigo-700">{round(total_pub/(total_pub+total_draft)*100) if (total_pub+total_draft) else 0}%</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>

    <!-- 上位ページタブ -->
    <div id="tab-pages" class="tab-content">
      <div class="p-4">
        <div class="text-xs text-gray-500 mb-3">直近28日 · Google Search Console · クリック数降順</div>
        <div id="pages-empty" class="hidden text-center text-gray-400 py-8 text-sm">該当なし</div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                <th class="px-3 py-2 text-center">#</th>
                <th class="px-3 py-2 text-left">URL</th>
                <th class="px-3 py-2 text-left">ジャンル</th>
                <th class="px-3 py-2 text-center">クリック</th>
                <th class="px-3 py-2 text-center">表示回数</th>
                <th class="px-3 py-2 text-center">CTR</th>
                <th class="px-3 py-2 text-center">順位</th>
              </tr>
            </thead>
            <tbody id="pages-tbody" class="divide-y divide-gray-100">{page_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- タスクタブ -->
    <div id="tab-tasks" class="tab-content">
      <div class="p-4">
        <div class="text-xs text-gray-500 mb-3">進行中タスク（2026-05-16時点）</div>
        <div id="tasks-empty" class="hidden text-center text-gray-400 py-8 text-sm">該当なし</div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                <th class="px-4 py-3 text-left">案件名</th>
                <th class="px-4 py-3 text-left">ジャンル</th>
                <th class="px-4 py-3 text-center">状況</th>
                <th class="px-4 py-3 text-left">詳細</th>
              </tr>
            </thead>
            <tbody id="tasks-tbody" class="divide-y divide-gray-100">{task_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 基本情報タブ -->
    <div id="tab-info" class="tab-content">
      <div class="p-5 grid md:grid-cols-2 gap-6">
        <div>
          <div class="text-sm font-semibold text-gray-700 mb-3">在籍弁護士（2026-05-16時点）</div>
          <div id="lawyers-list" class="space-y-2">{lawyer_cards}</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-gray-700 mb-3">主要システムリンク</div>
          <div class="space-y-2 text-sm">
            <a href="https://law-bright.com/wp-admin/" target="_blank" class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg hover:bg-indigo-50 transition-colors"><span class="text-indigo-600 font-mono text-xs w-8">WP</span><span class="text-gray-700">WordPress管理画面</span><span class="ml-auto text-gray-400">↗</span></a>
            <a href="https://analytics.google.com/analytics/web/#/p316908797/" target="_blank" class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg hover:bg-indigo-50 transition-colors"><span class="text-orange-600 font-mono text-xs w-8">GA4</span><span class="text-gray-700">Google Analytics</span><span class="ml-auto text-gray-400">↗</span></a>
            <a href="https://search.google.com/search-console/performance/search-analytics?resource_id=https%3A%2F%2Flaw-bright.com%2F" target="_blank" class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg hover:bg-indigo-50 transition-colors"><span class="text-green-600 font-mono text-xs w-8">GSC</span><span class="text-gray-700">Google Search Console</span><span class="ml-auto text-gray-400">↗</span></a>
            <a href="https://docs.google.com/spreadsheets/d/1Fm52M1BJVTOPD97TQyo7UsSfwGp9pNBQN7RdXZENQyI/" target="_blank" class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg hover:bg-indigo-50 transition-colors"><span class="text-green-600 font-mono text-xs w-8">GS</span><span class="text-gray-700">SEOレポートシート</span><span class="ml-auto text-gray-400">↗</span></a>
            <a href="https://bright.3cx.asia:5001/#/recordings" target="_blank" class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg hover:bg-indigo-50 transition-colors"><span class="text-purple-600 font-mono text-xs w-8">3CX</span><span class="text-gray-700">通話録音・ログ</span><span class="ml-auto text-gray-400">↗</span></a>
          </div>
          <div class="text-sm font-semibold text-gray-700 mt-5 mb-3">ジャンル別フリーダイヤル</div>
          <div class="space-y-1 text-xs">
            <div class="flex justify-between p-2 bg-red-50 rounded"><span class="text-red-700 font-medium">⚠️ 労災</span><span class="text-gray-700 font-mono">0120-931-501</span></div>
            <div class="flex justify-between p-2 bg-amber-50 rounded"><span class="text-amber-700 font-medium">🚗 交通事故</span><span class="text-gray-700 font-mono">0120-927-113</span></div>
            <div class="flex justify-between p-2 bg-blue-50 rounded"><span class="text-blue-700 font-medium">🏢 倒産</span><span class="text-gray-700 font-mono">0120-927-577</span></div>
            <div class="flex justify-between p-2 bg-green-50 rounded"><span class="text-green-700 font-medium">🏛️ みんなの法務部</span><span class="text-gray-700 font-mono">0120-929-739</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<footer class="text-center text-xs text-gray-400 py-6">弁護士法人ブライト 内部資料 · 外部公開禁止 · 更新: {NOW}</footer>

<script>
// ── データ ──────────────────────────────────────────
const ga4Labels   = {json.dumps(ga4_labels)};
const ga4Sessions = {json.dumps(ga4_sessions_vals)};
const ga4Conv     = {json.dumps(ga4_conv_vals)};
const gscLabels   = {json.dumps(gsc_labels)};
const gscClicks   = {json.dumps(gsc_clicks)};
const gscImps     = {json.dumps(gsc_imps)};
const GA4_TOTAL   = {ga4_sessions};
const catMetrics  = {cat_metrics_js};

const CAT_COLORS = {{ all:'#6366f1', komon:'#10b981', rosai:'#ef4444', kotsu:'#f59e0b', other:'#64748b' }};
const CAT_LABELS = {{ all:'全ジャンル', komon:'企業法務', rosai:'労災', kotsu:'交通事故', other:'その他' }};

// ── チャート ──────────────────────────────────────────
const chartOpts = (color) => ({{
  responsive: true,
  plugins: {{ legend: {{ display: false }}, tooltip: {{ mode: 'index', intersect: false }} }},
  scales: {{ x: {{ ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }}, y: {{ ticks: {{ font: {{ size: 10 }} }} }} }}
}});

const chartSessions = new Chart(document.getElementById('chartSessions'), {{
  type: 'line',
  data: {{ labels: ga4Labels, datasets: [{{ label: 'セッション', data: ga4Sessions,
    borderColor: '#6366f1', backgroundColor: '#6366f115', fill: true, tension: 0.3, pointRadius: 2 }}] }},
  options: chartOpts()
}});
const chartConv = new Chart(document.getElementById('chartConv'), {{
  type: 'bar',
  data: {{ labels: ga4Labels, datasets: [{{ label: 'CV', data: ga4Conv, backgroundColor: '#10b981aa' }}] }},
  options: chartOpts()
}});
const chartClicks = new Chart(document.getElementById('chartClicks'), {{
  type: 'line',
  data: {{ labels: gscLabels, datasets: [
    {{ label: 'クリック', data: gscClicks, borderColor: '#f59e0b', backgroundColor: '#f59e0b15', fill: true, tension: 0.3, pointRadius: 2 }},
    {{ label: '表示（÷100）', data: gscImps.map(v=>Math.round(v/100)), borderColor: '#94a3b8', borderDash: [4,4], tension: 0.3, pointRadius: 0 }}
  ] }},
  options: {{ responsive: true, plugins: {{ legend: {{ display: true, labels: {{ font: {{ size: 10 }} }} }}, tooltip: {{ mode: 'index', intersect: false }} }}, scales: {{ x: {{ ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }}, y: {{ ticks: {{ font: {{ size: 10 }} }} }} }} }}
}});
const cptData = [{cat_pub['komon']}, {cat_pub['rosai']}, {cat_pub['kotsu']}, {cat_pub['other']}];
const cptColors = ['#10b981','#ef4444','#f59e0b','#64748b'];
const chartCpt = new Chart(document.getElementById('chartCpt'), {{
  type: 'doughnut',
  data: {{
    labels: ['🏢 企業法務', '⚠️ 労災', '🚗 交通事故', '📋 その他'],
    datasets: [{{ data: cptData, backgroundColor: cptColors, borderWidth: 1 }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }} }}
}});

// ── KPI更新 ──────────────────────────────────────────
function fmt(n) {{ return Number(n).toLocaleString('ja-JP'); }}

function updateKpiCards(cat) {{
  const m = catMetrics[cat];
  const label = CAT_LABELS[cat];
  const isAll = cat === 'all';

  // セッション：GA4はジャンル別内訳なし → 全体値を常時表示
  document.getElementById('kpi-sessions').textContent = fmt(GA4_TOTAL);
  document.getElementById('kpi-sessions-sub').textContent = isAll ? 'GA4 · 全ジャンル計' : 'GA4 · ※全体値（ジャンル別内訳なし）';

  // クリック
  document.getElementById('kpi-clicks').textContent = fmt(m.clicks);
  document.getElementById('kpi-clicks-sub').textContent = `GSC · ${{label}} 平均順位 ${{m.pos}}位`;

  // インプレッション
  document.getElementById('kpi-imps').textContent = fmt(m.imps);
  document.getElementById('kpi-imps-sub').textContent = `GSC · ${{label}} CTR ${{m.ctr}}%`;

  // 記事数
  document.getElementById('kpi-pub').textContent = fmt(m.pub);
  document.getElementById('kpi-pub-sub').textContent = `draft ${{m.draft}}本 残`;

  // ドーナツチャートのハイライト
  const catIdx = {{ all: -1, komon: 0, rosai: 1, kotsu: 2, other: 3 }}[cat];
  chartCpt.data.datasets[0].backgroundColor = cptColors.map((c, i) =>
    catIdx === -1 ? c : (i === catIdx ? c : c + '44')
  );
  chartCpt.data.datasets[0].borderWidth = cptColors.map((c, i) =>
    catIdx === -1 ? 1 : (i === catIdx ? 3 : 1)
  );
  chartCpt.update();
}}

// ── フィルター ──────────────────────────────────────
let currentFilter = 'all';

function setFilter(cat, btn) {{
  currentFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => {{
    b.classList.remove('active','active-komon','active-rosai','active-kotsu','active-other');
  }});
  if (cat === 'all') btn.classList.add('active');
  else btn.classList.add('active-' + cat);

  updateKpiCards(cat);
  applyFilter();
}}

function applyFilter() {{
  const cat = currentFilter;

  // 記事ステータス
  let cptVisible = 0;
  document.querySelectorAll('.cpt-row').forEach(row => {{
    const show = cat === 'all' || row.dataset.cat === cat;
    row.style.display = show ? '' : 'none';
    if (show) cptVisible++;
  }});
  document.getElementById('articles-empty').classList.toggle('hidden', cptVisible > 0);

  // 上位ページ
  let pageVisible = 0;
  document.querySelectorAll('.page-row').forEach(row => {{
    const show = cat === 'all' || row.dataset.cat === cat;
    row.style.display = show ? '' : 'none';
    if (show) pageVisible++;
  }});
  document.getElementById('pages-empty').classList.toggle('hidden', pageVisible > 0);

  // タスク
  let taskVisible = 0;
  document.querySelectorAll('.task-row').forEach(row => {{
    const show = cat === 'all' || row.dataset.cat === cat;
    row.style.display = show ? '' : 'none';
    if (show) taskVisible++;
  }});
  document.getElementById('tasks-empty').classList.toggle('hidden', taskVisible > 0);

  // 弁護士
  document.querySelectorAll('.lawyer-card').forEach(card => {{
    card.style.display = (cat === 'all' || card.dataset.cat === cat) ? '' : 'none';
  }});

  // サマリーカードのハイライト
  document.querySelectorAll('.cat-summary-card').forEach(card => {{
    card.style.opacity = (cat === 'all' || card.dataset.cat === cat) ? '1' : '0.35';
  }});
}}

function switchTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.currentTarget.classList.add('active');
}}
</script>
</body>
</html>"""
    return html


if __name__ == "__main__":
    print("⏳ WP記事数を取得中...")
    cpt_data = fetch_cpt_counts()
    for c in cpt_data:
        if c["total"] > 0:
            print(f"  [{c['cat']:6s}] {c['label']:12s}: publish={c['publish']:4d} draft={c['draft']:4d}")

    GA4_DATA = [
        {"date":"20260416","sessions":"738","activeUsers":"634","conversions":"3"},
        {"date":"20260417","sessions":"744","activeUsers":"639","conversions":"6"},
        {"date":"20260418","sessions":"300","activeUsers":"267","conversions":"5"},
        {"date":"20260419","sessions":"259","activeUsers":"236","conversions":"1"},
        {"date":"20260420","sessions":"746","activeUsers":"663","conversions":"3"},
        {"date":"20260421","sessions":"848","activeUsers":"691","conversions":"8"},
        {"date":"20260422","sessions":"790","activeUsers":"666","conversions":"2"},
        {"date":"20260423","sessions":"787","activeUsers":"665","conversions":"4"},
        {"date":"20260424","sessions":"715","activeUsers":"616","conversions":"0"},
        {"date":"20260425","sessions":"345","activeUsers":"306","conversions":"3"},
        {"date":"20260426","sessions":"279","activeUsers":"246","conversions":"4"},
        {"date":"20260427","sessions":"943","activeUsers":"786","conversions":"6"},
        {"date":"20260428","sessions":"1026","activeUsers":"853","conversions":"7"},
        {"date":"20260429","sessions":"423","activeUsers":"362","conversions":"5"},
        {"date":"20260430","sessions":"1041","activeUsers":"876","conversions":"4"},
        {"date":"20260501","sessions":"989","activeUsers":"833","conversions":"23"},
        {"date":"20260502","sessions":"422","activeUsers":"361","conversions":"31"},
        {"date":"20260503","sessions":"335","activeUsers":"290","conversions":"4"},
        {"date":"20260504","sessions":"367","activeUsers":"322","conversions":"2"},
        {"date":"20260505","sessions":"356","activeUsers":"324","conversions":"1"},
        {"date":"20260506","sessions":"403","activeUsers":"356","conversions":"4"},
        {"date":"20260507","sessions":"1084","activeUsers":"935","conversions":"16"},
        {"date":"20260508","sessions":"1186","activeUsers":"1016","conversions":"12"},
        {"date":"20260509","sessions":"456","activeUsers":"409","conversions":"1"},
        {"date":"20260510","sessions":"334","activeUsers":"305","conversions":"1"},
        {"date":"20260511","sessions":"1238","activeUsers":"1062","conversions":"11"},
        {"date":"20260512","sessions":"1253","activeUsers":"1070","conversions":"8"},
        {"date":"20260513","sessions":"1147","activeUsers":"971","conversions":"5"},
        {"date":"20260514","sessions":"1216","activeUsers":"1062","conversions":"20"},
        {"date":"20260515","sessions":"1137","activeUsers":"986","conversions":"5"},
    ]
    GSC_DAILY = [
        {"date":"2026-04-18","clicks":135,"impressions":23775,"ctr":0.0057,"position":6.2},
        {"date":"2026-04-19","clicks":262,"impressions":33809,"ctr":0.0077,"position":6.2},
        {"date":"2026-04-20","clicks":363,"impressions":35177,"ctr":0.0103,"position":7.2},
        {"date":"2026-04-21","clicks":331,"impressions":30340,"ctr":0.0109,"position":8.6},
        {"date":"2026-04-22","clicks":342,"impressions":29632,"ctr":0.0115,"position":8.5},
        {"date":"2026-04-23","clicks":344,"impressions":30726,"ctr":0.0112,"position":8.8},
        {"date":"2026-04-24","clicks":209,"impressions":20412,"ctr":0.0102,"position":9.1},
        {"date":"2026-04-25","clicks":168,"impressions":16122,"ctr":0.0104,"position":9.6},
        {"date":"2026-04-26","clicks":249,"impressions":25293,"ctr":0.0098,"position":8.7},
        {"date":"2026-04-27","clicks":370,"impressions":29351,"ctr":0.0126,"position":8.5},
        {"date":"2026-04-28","clicks":232,"impressions":20768,"ctr":0.0112,"position":9.2},
        {"date":"2026-04-29","clicks":270,"impressions":25881,"ctr":0.0104,"position":8.7},
        {"date":"2026-04-30","clicks":342,"impressions":29738,"ctr":0.0115,"position":8.9},
        {"date":"2026-05-01","clicks":227,"impressions":20850,"ctr":0.0109,"position":9.0},
        {"date":"2026-05-02","clicks":150,"impressions":15371,"ctr":0.0098,"position":9.5},
        {"date":"2026-05-03","clicks":160,"impressions":15494,"ctr":0.0103,"position":9.2},
        {"date":"2026-05-04","clicks":162,"impressions":15551,"ctr":0.0104,"position":9.5},
        {"date":"2026-05-05","clicks":179,"impressions":17288,"ctr":0.0104,"position":9.2},
        {"date":"2026-05-06","clicks":311,"impressions":28181,"ctr":0.011,"position":8.4},
        {"date":"2026-05-07","clicks":447,"impressions":34809,"ctr":0.0128,"position":8.2},
        {"date":"2026-05-08","clicks":312,"impressions":24490,"ctr":0.0127,"position":8.6},
        {"date":"2026-05-09","clicks":164,"impressions":19283,"ctr":0.0085,"position":9.0},
        {"date":"2026-05-10","clicks":373,"impressions":30135,"ctr":0.0124,"position":8.1},
        {"date":"2026-05-11","clicks":476,"impressions":36912,"ctr":0.0129,"position":8.6},
        {"date":"2026-05-12","clicks":429,"impressions":35767,"ctr":0.012,"position":8.6},
        {"date":"2026-05-13","clicks":440,"impressions":35453,"ctr":0.0124,"position":8.8},
        {"date":"2026-05-14","clicks":452,"impressions":33888,"ctr":0.0133,"position":8.7},
        {"date":"2026-05-15","clicks":143,"impressions":12862,"ctr":0.0111,"position":9.3},
    ]
    GSC_PAGES = [
        {"page":"https://law-bright.com/labor-accident/knowledge/form8/","clicks":634,"impressions":41391,"ctr":0.0153,"position":6.5},
        {"page":"https://law-bright.com/labor-accident/knowledge/form5/","clicks":545,"impressions":62107,"ctr":0.0088,"position":6.6},
        {"page":"https://law-bright.com/labor-accident/knowledge/tenosynovitis-workers-comp/","clicks":387,"impressions":8412,"ctr":0.046,"position":4.6},
        {"page":"https://law-bright.com/labor-accident/knowledge/workers-comp-notice-delay/","clicks":376,"impressions":17735,"ctr":0.0212,"position":5.8},
        {"page":"https://law-bright.com/","clicks":289,"impressions":1351,"ctr":0.2139,"position":7.2},
        {"page":"https://law-bright.com/labor-accident/knowledge/workers-compensation-payment-delay/","clicks":282,"impressions":18743,"ctr":0.015,"position":6.1},
        {"page":"https://law-bright.com/labor-accident/knowledge/third-party-act-accident/","clicks":171,"impressions":17573,"ctr":0.0097,"position":7.9},
        {"page":"https://law-bright.com/labor-accident/knowledge/workers-compensation-bonus/","clicks":168,"impressions":4464,"ctr":0.0376,"position":6.7},
        {"page":"https://law-bright.com/labor-accident/knowledge/industrial-accident-application-medical-certificate/","clicks":166,"impressions":15880,"ctr":0.0105,"position":7.2},
        {"page":"https://law-bright.com/labor-accident/knowledge/jigyousyusyoumei/","clicks":160,"impressions":9931,"ctr":0.0161,"position":8.5},
        {"page":"https://law-bright.com/labor-accident/knowledge/workers-compensation-leave/","clicks":152,"impressions":8748,"ctr":0.0174,"position":6.8},
        {"page":"https://law-bright.com/corporationlaw/contents/company/foreigner-accommodation-residence-card/","clicks":140,"impressions":3253,"ctr":0.043,"position":6.2},
        {"page":"https://law-bright.com/corporationlaw/contents/syohisya/hotel-refund-handling/","clicks":132,"impressions":2309,"ctr":0.0572,"position":6.8},
        {"page":"https://law-bright.com/corporationlaw/contents/company/foreigner-hotel-passport/","clicks":124,"impressions":3517,"ctr":0.0353,"position":6.2},
        {"page":"https://law-bright.com/labor-accident/knowledge/commute-deviation-accident/","clicks":115,"impressions":7122,"ctr":0.0161,"position":9.5},
        {"page":"https://law-bright.com/glossary/jc/jc_a/benefit-of-the-doubt/","clicks":109,"impressions":14985,"ctr":0.0073,"position":3.4},
        {"page":"https://law-bright.com/kotuziko/knowledge/nakineiri/","clicks":102,"impressions":5756,"ctr":0.0177,"position":11.5},
        {"page":"https://law-bright.com/labor-accident/knowledge/workers-comp-retaliation/","clicks":94,"impressions":2881,"ctr":0.0326,"position":5.4},
        {"page":"https://law-bright.com/kotuziko/knowledge/kotsujiko_kizu/","clicks":91,"impressions":4008,"ctr":0.0227,"position":8.1},
        {"page":"https://law-bright.com/corporationlaw/contents/saiken/hotel-cancellation-fee-unpaid/","clicks":82,"impressions":6025,"ctr":0.0136,"position":7.9},
    ]

    print("⏳ HTML生成中...")
    html = generate_html(cpt_data, GA4_DATA, GSC_DAILY, GSC_PAGES)
    out_path = Path(__file__).parent / "docs" / "index.html"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 生成完了 → {out_path} ({out_path.stat().st_size:,} bytes)")
