#!/usr/bin/env python3
"""
bright-dashboard/generate.py
WP REST API + GA4 + GSC → docs/index.html を自動生成
実行: python3 generate.py
cron: 毎朝7時に自動実行（~/bright-dashboard/update.sh）
"""
import json
import os
import sys
import subprocess
import requests
from collections import defaultdict
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values

# GA4/GSC API（google-auth使用）
try:
    from google.oauth2 import service_account
    import google.auth
    import google.auth.transport.requests
    from googleapiclient.discovery import build
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

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
    {"slug": "legaladvisor",   "label": "顧問弁護士",     "color": "#10b981", "cat": "komon"},
    {"slug": "corporationlaw", "label": "企業法務ハブ",   "color": "#059669", "cat": "komon"},
    {"slug": "manda",          "label": "M&A",            "color": "#fbbf24", "cat": "komon"},
    {"slug": "employee",       "label": "問題社員",       "color": "#ec4899", "cat": "komon"},
    {"slug": "bankruptcy",     "label": "倒産・破産",     "color": "#7c3aed", "cat": "komon"},
    {"slug": "realestate",     "label": "不動産",         "color": "#a78bfa", "cat": "komon"},
    # 労災
    {"slug": "labor-accident", "label": "労災",           "color": "#ef4444", "cat": "rosai"},
    # 交通事故
    {"slug": "kotuziko",       "label": "交通事故",       "color": "#f59e0b", "cat": "kotsu"},
    # その他
    {"slug": "pages",          "label": "固定ページ",     "color": "#6366f1", "cat": "other"},
    {"slug": "posts",          "label": "ブログ記事",     "color": "#8b5cf6", "cat": "other"},
    {"slug": "glossary",       "label": "法律用語集",     "color": "#3b82f6", "cat": "other"},
    {"slug": "download",       "label": "資料DL",         "color": "#14b8a6", "cat": "other"},
    {"slug": "inheritance",    "label": "相続",           "color": "#fb7185", "cat": "other"},
]

# GSCページのジャンル判定
def page_cat(url: str) -> str:
    if "/labor-accident/" in url or "/rosai/" in url:
        return "rosai"
    if "/kotuziko/" in url or "/kotsujiko/" in url:
        return "kotsu"
    if any(p in url for p in ["/corporationlaw/", "/legaladvisor/", "/komon/",
                               "/manda/", "/employee/", "/bankruptcy/", "/realestate/"]):
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


def fetch_ga4_by_cat(days=30):
    """GA4からページパス別セッション・CVを取得してジャンル別に集計"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days-1)).strftime("%Y-%m-%d")
        resp = svc.properties().runReport(
            property="properties/316908797",
            body={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "pagePath"}],
                "metrics": [{"name": "sessions"}, {"name": "conversions"}],
                "limit": 10000,
                "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            }
        ).execute()
        cat_s  = {"all": 0, "komon": 0, "rosai": 0, "kotsu": 0, "other": 0}
        cat_cv = {"all": 0, "komon": 0, "rosai": 0, "kotsu": 0, "other": 0}
        for row in resp.get("rows", []):
            path = row["dimensionValues"][0]["value"]
            cat  = page_cat(f"https://law-bright.com{path}")
            s  = int(row["metricValues"][0]["value"])
            cv = int(float(row["metricValues"][1]["value"]))
            cat_s["all"]  += s;  cat_s[cat]  += s
            cat_cv["all"] += cv; cat_cv[cat] += cv
        print(f"  GA4 by cat: sessions={cat_s['all']:,} / CV={cat_cv['all']:,}")
        return {"sessions": cat_s, "conv": cat_cv}
    except Exception as e:
        print(f"  GA4 by cat エラー（フォールバック使用）: {e}")
        return None


def fetch_ga4(days=30):
    """GA4 APIから日次セッション・CV数を取得（google ADC使用）"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days-1)).strftime("%Y-%m-%d")
        resp = svc.properties().runReport(
            property=f"properties/316908797",
            body={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "date"}],
                "metrics": [{"name": "sessions"}, {"name": "activeUsers"}, {"name": "conversions"}],
                "orderBys": [{"dimension": {"dimensionName": "date"}}],
            }
        ).execute()
        rows = []
        for row in resp.get("rows", []):
            d = row["dimensionValues"][0]["value"]
            m = row["metricValues"]
            rows.append({"date": d, "sessions": m[0]["value"], "activeUsers": m[1]["value"], "conversions": m[2]["value"]})
        print(f"  GA4: {len(rows)}日分取得")
        return rows
    except Exception as e:
        print(f"  GA4 API エラー（フォールバック使用）: {e}")
        return None


def fetch_ga4_timeseries_cat(days=30):
    """GA4から日付×ページパス別セッション・CVを取得してジャンル別時系列に集計"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days-1)).strftime("%Y-%m-%d")
        resp = svc.properties().runReport(
            property="properties/316908797",
            body={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "date"}, {"name": "pagePath"}],
                "metrics": [{"name": "sessions"}, {"name": "conversions"}],
                "limit": 50000,
                "orderBys": [{"dimension": {"dimensionName": "date"}}],
            }
        ).execute()
        date_cat = defaultdict(lambda: defaultdict(lambda: {"s": 0, "cv": 0}))
        for row in resp.get("rows", []):
            d    = row["dimensionValues"][0]["value"]
            path = row["dimensionValues"][1]["value"]
            cat  = page_cat(f"https://law-bright.com{path}")
            s    = int(row["metricValues"][0]["value"])
            cv   = int(float(row["metricValues"][1]["value"]))
            for c in ("all", cat):
                date_cat[d][c]["s"]  += s
                date_cat[d][c]["cv"] += cv
        all_dates = sorted(date_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels":   [d[4:6]+"/"+d[6:] for d in all_dates],
                "sessions": [date_cat[d][cat]["s"]  for d in all_dates],
                "conv":     [date_cat[d][cat]["cv"] for d in all_dates],
            }
        print(f"  GA4 時系列 by cat: {len(all_dates)}日分")
        return result
    except Exception as e:
        print(f"  GA4 時系列 by cat エラー: {e}")
        return None


def fetch_gsc_timeseries_cat(days=28):
    """GSCから日付×ページ別クリック・表示回数を取得してジャンル別時系列に集計"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        end   = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days+1)).strftime("%Y-%m-%d")
        resp = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start, "endDate": end,
                  "dimensions": ["date", "page"], "rowLimit": 25000}
        ).execute()
        date_cat = defaultdict(lambda: defaultdict(lambda: {"cl": 0, "im": 0}))
        for row in resp.get("rows", []):
            d   = row["keys"][0]
            url = row["keys"][1]
            cat = page_cat(url)
            cl  = int(row["clicks"])
            im  = int(row["impressions"])
            for c in ("all", cat):
                date_cat[d][c]["cl"] += cl
                date_cat[d][c]["im"] += im
        all_dates = sorted(date_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels": [d[5:] for d in all_dates],
                "clicks": [date_cat[d][cat]["cl"] for d in all_dates],
                "imps":   [date_cat[d][cat]["im"] for d in all_dates],
            }
        print(f"  GSC 時系列 by cat: {len(all_dates)}日分")
        return result
    except Exception as e:
        print(f"  GSC 時系列 by cat エラー: {e}")
        return None


def fetch_ga4_ts_offset(days=30, offset_days=0, label=""):
    """offset_days日前を終点とするdays日間のGA4時系列 by カテゴリ"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        end   = (date.today() - timedelta(days=1 + offset_days)).strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days + offset_days)).strftime("%Y-%m-%d")
        resp = svc.properties().runReport(
            property="properties/316908797",
            body={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "date"}, {"name": "pagePath"}],
                "metrics": [{"name": "sessions"}, {"name": "conversions"}],
                "limit": 50000,
                "orderBys": [{"dimension": {"dimensionName": "date"}}],
            }
        ).execute()
        date_cat = defaultdict(lambda: defaultdict(lambda: {"s": 0, "cv": 0}))
        for row in resp.get("rows", []):
            d    = row["dimensionValues"][0]["value"]
            path = row["dimensionValues"][1]["value"]
            cat  = page_cat(f"https://law-bright.com{path}")
            s    = int(row["metricValues"][0]["value"])
            cv   = int(float(row["metricValues"][1]["value"]))
            for c in ("all", cat):
                date_cat[d][c]["s"]  += s
                date_cat[d][c]["cv"] += cv
        all_dates = sorted(date_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels":   [d[4:6]+"/"+d[6:] for d in all_dates],
                "sessions": [date_cat[d][cat]["s"]  for d in all_dates],
                "conv":     [date_cat[d][cat]["cv"] for d in all_dates],
            }
        lbl = label or f"offset={offset_days}d"
        print(f"  GA4 時系列({lbl}): {len(all_dates)}日分 ({start}〜{end})")
        return result
    except Exception as e:
        lbl = label or f"offset={offset_days}d"
        print(f"  GA4 時系列({lbl}) エラー: {e}")
        return None


def fetch_gsc_ts_offset(days=28, offset_days=0, label=""):
    """offset_days日前を終点とするdays日間のGSC時系列 by カテゴリ（GSCは2日ラグ）"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        end   = (date.today() - timedelta(days=2 + offset_days)).strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=1 + days + offset_days)).strftime("%Y-%m-%d")
        resp = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start, "endDate": end,
                  "dimensions": ["date", "page"], "rowLimit": 25000}
        ).execute()
        date_cat = defaultdict(lambda: defaultdict(lambda: {"cl": 0, "im": 0}))
        for row in resp.get("rows", []):
            d   = row["keys"][0]
            url = row["keys"][1]
            cat = page_cat(url)
            cl  = int(row["clicks"])
            im  = int(row["impressions"])
            for c in ("all", cat):
                date_cat[d][c]["cl"] += cl
                date_cat[d][c]["im"] += im
        all_dates = sorted(date_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels": [d[5:] for d in all_dates],
                "clicks": [date_cat[d][cat]["cl"] for d in all_dates],
                "imps":   [date_cat[d][cat]["im"] for d in all_dates],
            }
        lbl = label or f"offset={offset_days}d"
        print(f"  GSC 時系列({lbl}): {len(all_dates)}日分 ({start}〜{end})")
        return result
    except Exception as e:
        lbl = label or f"offset={offset_days}d"
        print(f"  GSC 時系列({lbl}) エラー: {e}")
        return None


def fetch_ga4_monthly(months=36):
    """直近N月の月次集計 by カテゴリ → {cat: {labels, sessions, conv}}"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        today = date.today()
        # 今月1日から months-1 ヶ月前の1日まで
        first_of_this = today.replace(day=1)
        first_of_start = (first_of_this - timedelta(days=(months-1)*30)).replace(day=1)
        end   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        start = first_of_start.strftime("%Y-%m-%d")
        resp = svc.properties().runReport(
            property="properties/316908797",
            body={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "yearMonth"}, {"name": "pagePath"}],
                "metrics": [{"name": "sessions"}, {"name": "conversions"}],
                "limit": 100000,
                "orderBys": [{"dimension": {"dimensionName": "yearMonth"}}],
            }
        ).execute()
        month_cat = defaultdict(lambda: defaultdict(lambda: {"s": 0, "cv": 0}))
        for row in resp.get("rows", []):
            ym   = row["dimensionValues"][0]["value"]  # "202504"
            path = row["dimensionValues"][1]["value"]
            cat  = page_cat(f"https://law-bright.com{path}")
            s    = int(row["metricValues"][0]["value"])
            cv   = int(float(row["metricValues"][1]["value"]))
            for c in ("all", cat):
                month_cat[ym][c]["s"]  += s
                month_cat[ym][c]["cv"] += cv
        all_months = sorted(month_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels":   [f"{ym[:4]}/{ym[4:]}" for ym in all_months],
                "sessions": [month_cat[ym][cat]["s"]  for ym in all_months],
                "conv":     [month_cat[ym][cat]["cv"] for ym in all_months],
            }
        print(f"  GA4 月次集計: {len(all_months)}ヶ月分 ({start}〜{end})")
        return result
    except Exception as e:
        print(f"  GA4 月次集計 エラー: {e}")
        return None


def fetch_gsc_monthly(months=16):
    """直近N月の月次集計 by カテゴリ → {cat: {labels, clicks, imps}}"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        today = date.today()
        first_of_this = today.replace(day=1)
        first_of_start = (first_of_this - timedelta(days=(months-1)*30)).replace(day=1)
        end   = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        start = first_of_start.strftime("%Y-%m-%d")
        resp = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start, "endDate": end,
                  "dimensions": ["date", "page"], "rowLimit": 25000}
        ).execute()
        month_cat = defaultdict(lambda: defaultdict(lambda: {"cl": 0, "im": 0}))
        for row in resp.get("rows", []):
            d   = row["keys"][0]  # "2026-04-17"
            ym  = d[:7].replace("-", "")  # "202604"
            url = row["keys"][1]
            cat = page_cat(url)
            cl  = int(row["clicks"])
            im  = int(row["impressions"])
            for c in ("all", cat):
                month_cat[ym][c]["cl"] += cl
                month_cat[ym][c]["im"] += im
        all_months = sorted(month_cat.keys())
        result = {}
        for cat in ["all", "komon", "rosai", "kotsu", "other"]:
            result[cat] = {
                "labels": [f"{ym[:4]}/{ym[4:]}" for ym in all_months],
                "clicks": [month_cat[ym][cat]["cl"] for ym in all_months],
                "imps":   [month_cat[ym][cat]["im"] for ym in all_months],
            }
        print(f"  GSC 月次集計: {len(all_months)}ヶ月分 ({start}〜{end})")
        return result
    except Exception as e:
        print(f"  GSC 月次集計 エラー: {e}")
        return None


def fetch_gsc_daily(days=28):
    """GSC APIから日次クリック・表示回数を取得"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        end = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days+1)).strftime("%Y-%m-%d")
        resp = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start, "endDate": end, "dimensions": ["date"],
                  "rowLimit": days, "orderBy": [{"fieldName": "date"}]}
        ).execute()
        rows = []
        for row in resp.get("rows", []):
            rows.append({"date": row["keys"][0], "clicks": int(row["clicks"]),
                         "impressions": int(row["impressions"]), "ctr": row["ctr"], "position": row["position"]})
        print(f"  GSC日次: {len(rows)}日分取得")
        return rows
    except Exception as e:
        print(f"  GSC日次 APIエラー（フォールバック使用）: {e}")
        return None


def fetch_gsc_pages(days=28, limit=20):
    """GSC APIからページ別クリック数上位を取得"""
    if not HAS_GOOGLE:
        return None
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        end = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=days+1)).strftime("%Y-%m-%d")
        resp = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start, "endDate": end, "dimensions": ["page"],
                  "rowLimit": limit, "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}]}
        ).execute()
        rows = []
        for row in resp.get("rows", []):
            rows.append({"page": row["keys"][0], "clicks": int(row["clicks"]),
                         "impressions": int(row["impressions"]), "ctr": row["ctr"], "position": row["position"]})
        print(f"  GSCページ: {len(rows)}件取得")
        return rows
    except Exception as e:
        print(f"  GSCページ APIエラー（フォールバック使用）: {e}")
        return None
    return results


# ── 記事管理タブ用 ────────────────────────────────────────────────────

ARTICLE_CPTS = [
    {"slug": "labor-accident", "dai": "労災",    "supervisor": "笹野 皓平"},
    {"slug": "kotuziko",       "dai": "交通事故", "supervisor": "松本 洋明"},
    {"slug": "corporationlaw", "dai": "企業法務", "supervisor": "和氣 良浩"},
    {"slug": "legaladvisor",   "dai": "企業法務", "supervisor": "和氣 良浩"},
    {"slug": "manda",          "dai": "企業法務", "supervisor": "和氣 良浩"},
    {"slug": "employee",       "dai": "企業法務", "supervisor": "和氣 良浩"},
]

CORP_CONTENTS = {
    "company": "顧問・会社法務", "keiyaku": "契約書", "roumu": "労務",
    "customer-harassment": "カスハラ", "syohisya": "消費者問題",
    "saiken": "債権回収", "enjyo": "助成金", "media": "メディア・IT",
}


def get_sho_cat(post: dict, cpt: str) -> str:
    path  = urlparse(post.get("link", "")).path
    slug  = path.rstrip("/").split("/")[-1]
    parts = [p for p in path.strip("/").split("/") if p]

    if cpt == "labor-accident":
        if "jirei" in slug or "jirei" in path: return "解決事例"
        if "form" in slug:                     return "申請書類"
        return "基礎知識"

    if cpt == "kotuziko":
        if slug.startswith("kt-") or "koui-shogai" in slug:           return "後遺障害"
        if any(k in slug for k in ("commute","tsukin","tsukinsaigai")): return "通勤災害×交通事故"
        if "rosai" in slug:                                             return "労災×交通事故"
        if any(k in slug for k in ("appaku","kossetsu","lumbar","daitai","sekitsui","sakotsu","fracture")): return "骨折・圧迫骨折"
        if any(k in slug for k in ("muchiuchi","keitsui","whiplash")):  return "むちうち"
        if any(k in slug for k in ("kashitsu","kasitu")):               return "過失割合"
        if any(k in slug for k in ("isharyo","compensation","-soba")):  return "慰謝料・相場"
        return "交通事故（一般）"

    if cpt == "corporationlaw":
        if len(parts) >= 3 and parts[1] == "contents":
            return CORP_CONTENTS.get(parts[2], parts[2])
        if "minna-no-houmubu" in path: return "みんなの法務部"
        return "ピラー・概要"

    if cpt == "legaladvisor":
        sub = parts[1] if len(parts) >= 2 else ""
        return {"preventive":"予防法務","dispute":"紛争解決","guide":"選び方ガイド",
                "strategic":"事業承継・戦略","cases":"解決事例"}.get(sub, "その他")

    return {"manda": "M&A", "employee": "問題社員"}.get(cpt, "")


def fetch_all_articles_wp() -> list:
    """WP REST API から記事管理対象CPTの全記事を取得"""
    all_articles = []
    for info in ARTICLE_CPTS:
        slug, count = info["slug"], 0
        page = 1
        while True:
            try:
                r = requests.get(
                    f"{WP_BASE}/wp-json/wp/v2/{slug}",
                    params={"status":"publish","per_page":100,"page":page,
                            "_fields":"id,title,link,date,featured_media"},
                    auth=AUTH, timeout=30,
                )
                if r.status_code in (400, 404): break
                r.raise_for_status()
                data = r.json()
                if not data: break
                for post in data:
                    all_articles.append({
                        "id":         post["id"],
                        "title":      post["title"]["rendered"],
                        "link":       post["link"],
                        "date":       post["date"][:10],
                        "eyecatch":   post.get("featured_media", 0) != 0,
                        "cpt":        slug,
                        "dai":        info["dai"],
                        "sho":        get_sho_cat(post, slug),
                        "supervisor": info["supervisor"],
                    })
                count += len(data)
                if len(data) < 100: break
                page += 1
            except Exception as e:
                print(f"    WP エラー ({slug} p{page}): {e}")
                break
        print(f"  [{info['dai']:5s}] {slug}: {count}本")
    return all_articles


def fetch_draft_articles_wp() -> list:
    """WP REST API から記事管理対象CPTの下書き記事を全件取得"""
    all_drafts = []
    for info in ARTICLE_CPTS:
        slug, count = info["slug"], 0
        page = 1
        while True:
            try:
                r = requests.get(
                    f"{WP_BASE}/wp-json/wp/v2/{slug}",
                    params={"status": "draft", "per_page": 100, "page": page,
                            "_fields": "id,title,link,date,modified,featured_media"},
                    auth=AUTH, timeout=30,
                )
                if r.status_code in (400, 404): break
                r.raise_for_status()
                data = r.json()
                if not data: break
                for post in data:
                    all_drafts.append({
                        "id":       post["id"],
                        "title":    post["title"]["rendered"],
                        "modified": post.get("modified", post["date"])[:10],
                        "created":  post["date"][:10],
                        "eyecatch": post.get("featured_media", 0) != 0,
                        "cpt":      slug,
                        "dai":      info["dai"],
                        "sho":      get_sho_cat(post, slug),
                    })
                count += len(data)
                if len(data) < 100: break
                page += 1
            except Exception as e:
                print(f"    WP 下書きエラー ({slug} p{page}): {e}")
                break
        print(f"  [{info['dai']:5s}] {slug} draft: {count}本")
    return all_drafts


def fetch_gsc_for_articles(days: int = 30):
    """記事管理用 GSC データ（当月・前月・上位クエリ）を全ページ分取得"""
    if not HAS_GOOGLE:
        return {}, {}, {}
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        creds.refresh(google.auth.transport.requests.Request())
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

        end    = date.today() - timedelta(days=2)
        start  = end   - timedelta(days=days - 1)
        p_end  = start - timedelta(days=1)
        p_start= p_end - timedelta(days=days - 1)

        def page_stats(s, e):
            resp = svc.searchanalytics().query(
                siteUrl="https://law-bright.com/",
                body={"startDate": s.isoformat(), "endDate": e.isoformat(),
                      "dimensions": ["page"], "rowLimit": 25000},
            ).execute()
            return {row["keys"][0]: {"clicks": int(row["clicks"]),
                                     "impressions": int(row["impressions"]),
                                     "position": round(row["position"], 1)}
                    for row in resp.get("rows", [])}

        curr = page_stats(start, end)
        prev = page_stats(p_start, p_end)

        resp_pq = svc.searchanalytics().query(
            siteUrl="https://law-bright.com/",
            body={"startDate": start.isoformat(), "endDate": end.isoformat(),
                  "dimensions": ["page", "query"], "rowLimit": 25000},
        ).execute()
        pq = defaultdict(list)
        for row in resp_pq.get("rows", []):
            url, q = row["keys"]
            pq[url].append((int(row["clicks"]), q))
        top_q = {url: sorted(ql, reverse=True)[0][1] for url, ql in pq.items() if ql}

        print(f"  GSC記事: 当月{len(curr)}件, 前月{len(prev)}件")
        return curr, prev, top_q
    except Exception as e:
        print(f"  GSC記事 APIエラー: {e}")
        return {}, {}, {}


def calc_article_change(curr: dict, prev: dict) -> tuple:
    c_pos = curr.get("position")
    p_pos = prev.get("position")
    c_clk = curr.get("clicks", 0)
    p_clk = prev.get("clicks", 0)

    if c_pos is not None and p_pos is None: return "新規", "新規", "🆕 新規流入"
    if c_pos is None:                       return "—",   "—",   "—"

    pos_delta = round(p_pos - c_pos, 1) if p_pos is not None else 0.0
    pos_str   = (f"+{pos_delta}" if pos_delta > 0 else str(pos_delta)) if p_pos else "—"
    clk_pct   = (c_clk - p_clk) / p_clk * 100 if p_clk > 0 else 0.0
    clk_str   = (f"+{clk_pct:.0f}%" if clk_pct >= 0 else f"{clk_pct:.0f}%") if p_clk > 0 else "—"

    if   pos_delta >= 5  or clk_pct >= 50:  status = "🚀 急上昇"
    elif pos_delta >= 2  or clk_pct >= 20:  status = "📈 改善"
    elif pos_delta <= -5 or clk_pct <= -50: status = "💥 急落"
    elif pos_delta <= -2 or clk_pct <= -20: status = "📉 悪化"
    else:                                    status = "—"

    return pos_str, clk_str, status


def fetch_inquiry_data():
    """AppSheet問合せアプリ（a9703058）のPROJECT_inquiriesを取得して集計する。
    失敗時はキャッシュにフォールバック。"""
    cache_path = Path.home() / "bright-seo-report" / "data" / "appsheet_cache" / "inquiries.json"
    env_path   = Path.home() / "bright-seo-report" / ".env"

    # 環境変数読み込み
    app_id = key = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k == "APPSHEET_INQUIRY_APP_ID":
                app_id = v
            elif k == "APPSHEET_INQUIRY_ACCESS_KEY":
                key = v

    rows = None
    if app_id and key:
        try:
            url = f"https://api.appsheet.com/api/v2/apps/{app_id}/tables/PROJECT_inquiries/Action"
            headers = {"ApplicationAccessKey": key, "Content-Type": "application/json"}
            body = {"Action": "Find", "Properties": {}, "Rows": []}
            r = requests.post(url, json=body, headers=headers, timeout=60)
            r.raise_for_status()
            data = r.json()
            rows = data if isinstance(data, list) else []
            print(f"  AppSheet問合せ: {len(rows)}件取得")
            # キャッシュ更新
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        except Exception as e:
            print(f"  AppSheet問合せ APIエラー（キャッシュにフォールバック）: {e}")

    if rows is None:
        if cache_path.exists():
            try:
                rows = json.loads(cache_path.read_text(encoding="utf-8"))
                print(f"  AppSheet問合せ: キャッシュから{len(rows)}件")
            except Exception:
                pass

    if not rows:
        print("  AppSheet問合せ: データなし")
        return None

    def parse_date(s):
        """MM/DD/YYYY HH:MM:SS または MM/DD/YYYY → date"""
        if not s:
            return None
        try:
            return datetime.strptime(s.strip()[:10], "%m/%d/%Y").date()
        except Exception:
            return None

    def inq_status(r):
        if r.get("contracted_on", ""):
            return "受任済"
        lose = r.get("lose_reason", "") or r.get("not_contract_reason", "")
        prog = r.get("project_progress", "")
        if lose or "不成立" in prog or "クローズ" in prog:
            return "不成立"
        if "相談" in prog:
            return "相談中"
        return "問い合わせ中"

    def inq_cat(r):
        cat = r.get("case_category_large", "")
        if "労災" in cat:
            return "rosai"
        if "交通" in cat:
            return "kotsu"
        if any(k in cat for k in ("顧問", "企業", "法務")):
            return "komon"
        return "other"

    today = date.today()
    this_month_key = today.strftime("%Y-%m")
    prev_month_date = (today.replace(day=1) - timedelta(days=1))
    prev_month_key  = prev_month_date.strftime("%Y-%m")

    # 直近12ヶ月のリスト
    months = []
    for i in range(11, -1, -1):
        d = (today.replace(day=1) - timedelta(days=i * 30))
        months.append(d.strftime("%Y-%m"))
    # 重複除去・ソート
    months = sorted(set(months))[-12:]

    monthly_inq  = {m: {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0} for m in months}
    monthly_cont = {m: {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0} for m in months}

    status_summary = {
        "問い合わせ中": {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0, "total": 0},
        "相談中":       {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0, "total": 0},
        "受任済":       {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0, "total": 0},
        "不成立":       {"komon": 0, "rosai": 0, "kotsu": 0, "other": 0, "total": 0},
    }

    source_counter = defaultdict(int)
    contracted_total = 0
    this_month_cnt = prev_month_cnt = 0

    recent_rows = []

    for r in rows:
        rec_date = parse_date(r.get("recepted_on", ""))
        cont_date = parse_date(r.get("contracted_on", ""))
        cat = inq_cat(r)
        st  = inq_status(r)

        # 月次問い合わせ集計（recepted_on基準）
        if rec_date:
            mk = rec_date.strftime("%Y-%m")
            if mk in monthly_inq:
                monthly_inq[mk][cat] += 1
            if mk == this_month_key:
                this_month_cnt += 1
            if mk == prev_month_key:
                prev_month_cnt += 1

        # 月次受任集計（contracted_on基準）
        if cont_date:
            mk = cont_date.strftime("%Y-%m")
            if mk in monthly_cont:
                monthly_cont[mk][cat] += 1
            contracted_total += 1

        # ステータス×ジャンル（is_archive != 'Y' のみ）
        if r.get("is_archive", "") != "Y":
            if st in status_summary:
                status_summary[st][cat]     += 1
                status_summary[st]["total"] += 1

        # 流入経路
        src = (r.get("source_label", "") or r.get("source_how", "") or "不明").strip() or "不明"
        source_counter[src] += 1

        # 最新30件用
        recent_rows.append({
            "_date": rec_date,
            "date":   r.get("recepted_on", "")[:10] if r.get("recepted_on") else "",
            "name":   r.get("label", "").split("_")[0] if r.get("label") else "",
            "cat":    r.get("case_category_large", "その他"),
            "cat_key": cat,
            "source": src,
            "status": st,
            "lawyer": r.get("consulted_lawyer_id", ""),   # IDのみ（名前解決は省略）
            "url":    r.get("drive_url", "") or r.get("chat_url", ""),
        })

    # 直近30件（受付日降順）
    recent_sorted = sorted(
        [x for x in recent_rows if x["_date"]],
        key=lambda x: x["_date"],
        reverse=True
    )[:30]
    recent = [{k: v for k, v in r.items() if k != "_date"} for r in recent_sorted]

    top_sources = sorted(
        [{"src": k, "cnt": v} for k, v in source_counter.items()],
        key=lambda x: -x["cnt"]
    )[:8]

    total = len(rows)
    cont_rate = round(contracted_total / total * 100, 1) if total else 0.0

    return {
        "total":          total,
        "contracted":     contracted_total,
        "cont_rate":      cont_rate,
        "this_month":     this_month_cnt,
        "prev_month":     prev_month_cnt,
        "synced_at":      datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "months":         months,
        "monthly_inq":    monthly_inq,
        "monthly_cont":   monthly_cont,
        "status_summary": status_summary,
        "top_sources":    top_sources,
        "recent":         recent,
    }


def generate_html(cpt_data, ga4_data, gsc_data, gsc_pages, articles_data=None, ga4_cat=None,
                  ga4_ts_cat=None, gsc_ts_cat=None, ga4_ts_prev=None, gsc_ts_prev=None,
                  inquiry_data=None,
                  ga4_ts_1y=None, gsc_ts_1y=None,
                  ga4_ts_2y=None, ga4_ts_3y=None,
                  ga4_monthly=None, gsc_monthly=None,
                  draft_articles=None):
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
        s  = ga4_cat["sessions"].get(cat, 0) if ga4_cat else (ga4_sessions if cat == "all" else 0)
        cv = ga4_cat["conv"].get(cat, 0)    if ga4_cat else 0
        cat_metrics[cat] = {"clicks": cl, "imps": im, "ctr": ctr, "pos": pos,
                            "pub": pub, "draft": dft, "sessions": s, "conv": cv}
    cat_metrics_js = json.dumps(cat_metrics)

    # 記事ステータス行（クリックで記事一覧展開）
    cpt_rows = ""
    for c in sorted(cpt_data, key=lambda x: -x["publish"]):
        if c["total"] == 0:
            continue
        pct = round(c["publish"] / c["total"] * 100) if c["total"] else 0
        bar = f'<div class="w-full bg-gray-100 rounded-full h-2"><div class="h-2 rounded-full" style="width:{pct}%;background:{c["color"]}"></div></div>'
        cat_label = {"komon":"企業法務","rosai":"労災","kotsu":"交通事故","other":"その他"}[c["cat"]]
        cat_colors = {"komon":"bg-emerald-100 text-emerald-700","rosai":"bg-red-100 text-red-700","kotsu":"bg-amber-100 text-amber-700","other":"bg-slate-100 text-slate-600"}
        badge_cls = cat_colors[c["cat"]]
        wp_post_type = {"pages": "page", "posts": "post"}.get(c["slug"], c["slug"])
        cpt_rows += f"""
        <tr class="hover:bg-indigo-50 transition-colors cpt-row cursor-pointer select-none" data-cat="{c['cat']}" onclick="toggleCptArticles('{c['slug']}', this)">
          <td class="px-4 py-3">
            <span class="cpt-expand-icon text-gray-400 mr-2 inline-block w-3 text-xs transition-transform">▶</span>
            <span class="font-medium text-gray-800">{c['label']}</span>
          </td>
          <td class="px-4 py-3"><span class="inline-block {badge_cls} text-xs font-semibold px-2 py-1 rounded-full">{cat_label}</span></td>
          <td class="px-4 py-3 text-center">
            <a href="https://law-bright.com/wp-admin/edit.php?post_type={wp_post_type}&post_status=publish" target="_blank" onclick="event.stopPropagation()" class="inline-block bg-green-100 text-green-800 text-xs font-semibold px-2 py-1 rounded-full hover:bg-green-200 transition-colors" title="WP管理で公開記事を見る">{c['publish']}</a>
          </td>
          <td class="px-4 py-3 text-center">
            <a href="https://law-bright.com/wp-admin/edit.php?post_type={wp_post_type}&post_status=draft" target="_blank" onclick="event.stopPropagation()" class="inline-block bg-yellow-100 text-yellow-800 text-xs font-semibold px-2 py-1 rounded-full hover:bg-yellow-200 transition-colors" title="WP管理で下書きを見る">{c['draft']}</a>
          </td>
          <td class="px-4 py-3 text-sm text-gray-600 w-40">{bar}</td>
          <td class="px-4 py-3 text-center text-xs text-gray-500">{pct}%</td>
        </tr>
        <tr class="cpt-expand-row" id="cpt-expand-row-{c['slug']}" data-cat="{c['cat']}" data-open="false" style="display:none">
          <td colspan="6" class="px-0 py-0 border-l-4 border-indigo-400">
            <div id="cpt-expand-{c['slug']}" class="px-8 py-4 bg-indigo-50 text-xs"></div>
          </td>
        </tr>"""

    # 上位ページ行（WP編集リンク付き）
    page_rows = ""
    for i, p in enumerate(gsc_pages[:20], 1):
        url = p["page"]
        short = url.replace("https://law-bright.com", "")
        slug_last = url.rstrip("/").split("/")[-1]
        wp_search_url = f"https://law-bright.com/wp-admin/edit.php?s={slug_last}&post_type=any"
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
          <td class="px-3 py-2 text-xs font-mono">
            <a href="{url}" target="_blank" class="text-blue-700 hover:underline">{short}</a>
          </td>
          <td class="px-3 py-2"><span class="inline-block {badge_cls} text-xs font-semibold px-2 py-1 rounded-full">{cat_label}</span></td>
          <td class="px-3 py-2 text-center font-semibold">{p['clicks']:,}</td>
          <td class="px-3 py-2 text-center text-gray-500">{p['impressions']:,}</td>
          <td class="px-3 py-2 text-center {ctr_color}">{ctr_pct}%</td>
          <td class="px-3 py-2 text-center {pos_color}">{p['position']}</td>
          <td class="px-3 py-2 text-center whitespace-nowrap">
            <a href="{url}" target="_blank" class="text-blue-600 hover:text-blue-800 text-xs mr-2" title="記事を表示">↗ 表示</a>
            <a href="{wp_search_url}" target="_blank" class="text-orange-600 hover:text-orange-800 text-xs" title="WP管理で検索">✏️ 編集</a>
          </td>
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
  .am-filter-btn.active {{ background: #4f46e5; color: white; border-color: #4f46e5; }}
  .amview-btn.active {{ background: #4f46e5; color: white; border-color: #4f46e5; }}
  .dr-filter-btn.active {{ background: #d97706; color: white; border-color: #d97706; }}
  .sm-view-btn.active {{ background: #4f46e5; color: white; border-color: #4f46e5; }}
  /* ── サイトマップ ツリー ── */
  .sm-tree-node {{ line-height: 1.6; }}
  .sm-tree-node details > summary {{ cursor: pointer; list-style: none; display: flex; align-items: center; gap: 4px; padding: 2px 4px; border-radius: 4px; }}
  .sm-tree-node details > summary::-webkit-details-marker {{ display: none; }}
  .sm-tree-node details > summary:hover {{ background: #f1f5f9; }}
  .sm-tree-node details[open] > summary .sm-arrow {{ transform: rotate(90deg); }}
  .sm-arrow {{ display: inline-block; transition: transform .15s; color: #94a3b8; font-size: 10px; width: 12px; }}
  .sm-leaf {{ display: flex; align-items: center; gap: 4px; padding: 2px 4px; border-radius: 4px; cursor: default; }}
  .sm-leaf:hover {{ background: #f8fafc; }}
  .sm-leaf a {{ color: #3b82f6; text-decoration: none; }}
  .sm-leaf a:hover {{ text-decoration: underline; }}
  .sm-badge {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 9999px; margin-left: 4px; }}
  .sm-cpt-rosai    {{ color: #dc2626; }}
  .sm-cpt-kotsu    {{ color: #d97706; }}
  .sm-cpt-komon    {{ color: #059669; }}
  .sm-cpt-manda    {{ color: #0891b2; }}
  .sm-cpt-emp      {{ color: #7c3aed; }}
  .sm-cpt-bk       {{ color: #6b7280; }}
  .sm-cpt-page     {{ color: #1d4ed8; }}
  .sm-cpt-other    {{ color: #475569; }}
  .sm-hl {{ background: #fef08a; border-radius: 2px; }}
  .sm-url-box::-webkit-scrollbar {{ width: 4px; }}
  .sm-url-box::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 2px; }}
  .period-btn {{ transition: all .12s; }}
  .period-btn.active {{ background: #4f46e5; color: white; border-color: #4f46e5; }}
  .cmp-btn {{ transition: all .12s; }}
  .cmp-btn.active {{ background: #7c3aed; color: white; border-color: #7c3aed; }}
  #monthly-toggle {{ transition: all .12s; }}
  #monthly-toggle.monthly-on {{ background: #9333ea; color: white; border-color: #9333ea; }}
  .kpi-delta {{ font-size: 0.7rem; font-weight: 700; }}
  .kpi-delta.up {{ color: #16a34a; }}
  .kpi-delta.dn {{ color: #dc2626; }}
  .compare-info {{ font-size: 0.65rem; color: #6366f1; margin-top: 2px; display: none; }}
  .compare-info.visible {{ display: block; }}
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

<!-- ジャンルフィルター + 期間セレクター（グローバル） -->
<div class="bg-white border-b border-gray-100 sticky top-[57px] z-40">
  <div class="max-w-7xl mx-auto px-4 py-2 flex items-center gap-2 flex-wrap">
    <span class="text-xs text-gray-500 mr-1">ジャンル：</span>
    <button class="filter-btn active px-3 py-1 rounded-full text-xs font-semibold border border-gray-300" onclick="setFilter('all', this)">全体</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-emerald-300 text-emerald-700" onclick="setFilter('komon', this)">🏢 企業法務</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-red-300 text-red-700" onclick="setFilter('rosai', this)">⚠️ 労災</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-amber-300 text-amber-700" onclick="setFilter('kotsu', this)">🚗 交通事故</button>
    <button class="filter-btn px-3 py-1 rounded-full text-xs font-semibold border border-slate-300 text-slate-600" onclick="setFilter('other', this)">📋 その他</button>
    <span class="text-gray-300 select-none">｜</span>
    <span class="text-xs text-gray-500">期間：</span>
    <button class="period-btn px-3 py-1 rounded-full text-xs font-semibold border border-gray-300 text-gray-600" onclick="setPeriod(7,this)">7日</button>
    <button class="period-btn px-3 py-1 rounded-full text-xs font-semibold border border-gray-300 text-gray-600" onclick="setPeriod(14,this)">14日</button>
    <button class="period-btn active px-3 py-1 rounded-full text-xs font-semibold border border-gray-300 text-gray-600" onclick="setPeriod(30,this)">30日</button>
    <span class="text-gray-300 select-none">｜</span>
    <span class="text-xs text-gray-500">比較：</span>
    <button class="cmp-btn active px-3 py-1 rounded-full text-xs font-semibold border border-gray-300 text-gray-600" onclick="setCompare('none',this)">なし</button>
    <button class="cmp-btn px-3 py-1 rounded-full text-xs font-semibold border border-indigo-300 text-indigo-600" onclick="setCompare('prev',this)">前期</button>
    <button class="cmp-btn px-3 py-1 rounded-full text-xs font-semibold border border-indigo-300 text-indigo-600" onclick="setCompare('month',this)">前月</button>
    <button class="cmp-btn px-3 py-1 rounded-full text-xs font-semibold border border-indigo-300 text-indigo-600" onclick="setCompare('1y',this)">前年</button>
    <button class="cmp-btn px-3 py-1 rounded-full text-xs font-semibold border border-indigo-300 text-indigo-600" onclick="setCompare('2y',this)">2年前</button>
    <button class="cmp-btn px-3 py-1 rounded-full text-xs font-semibold border border-indigo-300 text-indigo-600" onclick="setCompare('3y',this)">3年前</button>
    <span class="text-gray-300 select-none">｜</span>
    <button id="monthly-toggle" class="px-3 py-1 rounded-full text-xs font-semibold border border-purple-300 text-purple-600" onclick="toggleMonthly(this)">📅 月次グラフ</button>
  </div>
</div>

<div class="max-w-7xl mx-auto px-4 py-5">

  <!-- KPIカード -->
  <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-5">
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1" id="kpi-sessions-label">セッション（30日）</div>
      <div class="flex items-baseline gap-1.5 flex-wrap">
        <div class="text-2xl font-bold text-gray-900" id="kpi-sessions">{ga4_sessions:,}</div>
        <span class="kpi-delta" id="kpi-sessions-delta"></span>
      </div>
      <div class="compare-info" id="kpi-sessions-prev"></div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-sessions-sub">GA4 · 全ジャンル計</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1" id="kpi-conv-label">コンバージョン（30日）</div>
      <div class="flex items-baseline gap-1.5 flex-wrap">
        <div class="text-2xl font-bold text-gray-900" id="kpi-conv">{ga4_conversions:,}</div>
        <span class="kpi-delta" id="kpi-conv-delta"></span>
      </div>
      <div class="compare-info" id="kpi-conv-prev"></div>
      <div class="text-xs text-green-600 mt-1" id="kpi-conv-sub">GA4 · 全ジャンル計</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1" id="kpi-clicks-label">クリック（28日）</div>
      <div class="flex items-baseline gap-1.5 flex-wrap">
        <div class="text-2xl font-bold text-gray-900" id="kpi-clicks">{gsc_total_clicks:,}</div>
        <span class="kpi-delta" id="kpi-clicks-delta"></span>
      </div>
      <div class="compare-info" id="kpi-clicks-prev"></div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-clicks-sub">GSC · 平均順位 {gsc_avg_pos}位</div>
    </div>
    <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1" id="kpi-imps-label">表示回数（28日）</div>
      <div class="flex items-baseline gap-1.5 flex-wrap">
        <div class="text-2xl font-bold text-gray-900" id="kpi-imps">{gsc_total_imps:,}</div>
        <span class="kpi-delta" id="kpi-imps-delta"></span>
      </div>
      <div class="compare-info" id="kpi-imps-prev"></div>
      <div class="text-xs text-indigo-600 mt-1" id="kpi-imps-sub">GSC · CTR {gsc_avg_ctr}%</div>
    </div>
    <div class="kpi-card col-span-2 md:col-span-1 bg-white rounded-xl shadow-sm p-4 border border-gray-100">
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
      <button class="tab-btn active px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('kpi',this)">📊 KPI</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('articles',this)">📝 記事ステータス</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('pages',this)">🏆 上位ページ</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('artmgr',this)">📋 記事管理</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('tasks',this)">✅ タスク</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('info',this)">ℹ️ 基本情報</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('inquiry',this)">📞 問い合わせ</button>
      <button class="tab-btn px-5 py-3 text-sm whitespace-nowrap" onclick="switchTab('sitemap',this)">🗺️ サイトマップ</button>
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
                <th class="px-4 py-3 text-left">カテゴリ <span class="normal-case text-gray-400 font-normal">（クリックで記事一覧）</span></th>
                <th class="px-4 py-3 text-left">ジャンル</th>
                <th class="px-4 py-3 text-center">公開 <span class="normal-case text-gray-400 font-normal">↗WP</span></th>
                <th class="px-4 py-3 text-center">下書き <span class="normal-case text-gray-400 font-normal">↗WP</span></th>
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
                <th class="px-3 py-2 text-center">操作</th>
              </tr>
            </thead>
            <tbody id="pages-tbody" class="divide-y divide-gray-100">{page_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 記事管理タブ -->
    <div id="tab-artmgr" class="tab-content">
      <div class="p-4">

        <!-- 公開済/下書き ビュー切り替え -->
        <div class="flex gap-2 mb-4">
          <button id="amview-pub" class="amview-btn active px-4 py-1.5 rounded-full text-xs font-bold border border-green-400 text-green-700 bg-green-50" onclick="setArtView('pub',this)">📰 公開済</button>
          <button id="amview-draft" class="amview-btn px-4 py-1.5 rounded-full text-xs font-bold border border-yellow-400 text-yellow-700 bg-yellow-50" onclick="setArtView('draft',this)">📝 下書き <span id="draft-count-badge" class="ml-1 bg-yellow-400 text-white rounded-full px-1.5 py-0.5 text-xs"></span></button>
        </div>

        <!-- 公開済ビュー -->
        <div id="amview-pub-content">
          <!-- サマリ行 -->
          <div id="am-summary" class="grid grid-cols-4 gap-3 mb-4 text-center">
            <div class="bg-white rounded-lg border border-gray-100 shadow-sm p-3">
              <div class="text-xs text-gray-500">総記事数</div>
              <div class="text-xl font-bold text-gray-800" id="am-total">—</div>
            </div>
            <div class="bg-indigo-50 rounded-lg border border-indigo-100 p-3 cursor-pointer hover:bg-indigo-100 transition-colors" onclick="setArtFilter('top10',this)">
              <div class="text-xs text-indigo-600">🔝 上位10位圏内</div>
              <div class="text-xl font-bold text-indigo-700" id="am-top10">—</div>
            </div>
            <div class="bg-yellow-50 rounded-lg border border-yellow-100 p-3 cursor-pointer hover:bg-yellow-100 transition-colors" onclick="setArtFilter('rewrite',this)">
              <div class="text-xs text-yellow-600">✏️ リライト推奨</div>
              <div class="text-xl font-bold text-yellow-700" id="am-rewrite">—</div>
            </div>
            <div class="bg-red-50 rounded-lg border border-red-100 p-3 cursor-pointer hover:bg-red-100 transition-colors" onclick="setArtFilter('drop',this)">
              <div class="text-xs text-red-600">💥 急落記事</div>
              <div class="text-xl font-bold text-red-700" id="am-drop">—</div>
            </div>
          </div>

          <!-- フィルター行 -->
          <div class="flex flex-wrap items-center gap-2 mb-3">
            <span class="text-xs text-gray-500">フィルター：</span>
            <button class="am-filter-btn active text-xs px-3 py-1 rounded-full border border-gray-300 font-semibold" onclick="setArtFilter('all',this)">全て</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-indigo-300 text-indigo-700 font-semibold" onclick="setArtFilter('top10',this)">🔝 上位10位</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-yellow-300 text-yellow-700 font-semibold" onclick="setArtFilter('rewrite',this)">✏️ リライト推奨</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-green-300 text-green-700 font-semibold" onclick="setArtFilter('rise',this)">🚀 急上昇</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-red-300 text-red-700 font-semibold" onclick="setArtFilter('drop',this)">💥 急落</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-gray-300 text-gray-600 font-semibold" onclick="setArtFilter('noimg',this)">🖼️ アイキャッチなし</button>
            <button class="am-filter-btn text-xs px-3 py-1 rounded-full border border-orange-300 text-orange-700 font-semibold" onclick="setArtFilter('new',this)">🆕 新規流入</button>
            <input type="text" id="am-search" placeholder="タイトル・クエリで絞り込み..." oninput="renderArtTable()"
              class="ml-auto border border-gray-200 rounded-lg px-3 py-1.5 text-xs w-52 focus:outline-none focus:border-indigo-400">
          </div>

          <!-- 件数表示 -->
          <div class="text-xs text-gray-400 mb-2" id="am-count">読み込み中...</div>

          <!-- テーブル -->
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead>
                <tr class="bg-gray-50 text-gray-500 uppercase tracking-wide select-none">
                  <th class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100" onclick="toggleArtSort('title')">タイトル <span id="s-title"></span></th>
                  <th class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100 w-20" onclick="toggleArtSort('sho')">小カテゴリ <span id="s-sho"></span></th>
                  <th class="px-3 py-2 text-center cursor-pointer hover:bg-gray-100 w-20" onclick="toggleArtSort('date')">公開日 <span id="s-date"></span></th>
                  <th class="px-3 py-2 text-center cursor-pointer hover:bg-gray-100 w-14" onclick="toggleArtSort('eyecatch')">👁 <span id="s-eyecatch"></span></th>
                  <th class="px-3 py-2 text-center cursor-pointer hover:bg-gray-100 w-14" onclick="toggleArtSort('position')">順位 <span id="s-position"></span></th>
                  <th class="px-3 py-2 text-center cursor-pointer hover:bg-gray-100 w-16" onclick="toggleArtSort('clicks')">クリック <span id="s-clicks"></span></th>
                  <th class="px-3 py-2 text-left w-36">上位クエリ</th>
                  <th class="px-3 py-2 text-center cursor-pointer hover:bg-gray-100 w-20" onclick="toggleArtSort('status')">変化 <span id="s-status"></span></th>
                  <th class="px-3 py-2 text-center w-16">操作</th>
                </tr>
              </thead>
              <tbody id="am-tbody" class="divide-y divide-gray-100"></tbody>
            </table>
          </div>
        </div>

        <!-- 下書きビュー -->
        <div id="amview-draft-content" class="hidden">
          <!-- 下書きサマリ -->
          <div class="grid grid-cols-4 gap-3 mb-4 text-center" id="draft-summary">
            <div class="bg-yellow-50 rounded-lg border border-yellow-100 p-3">
              <div class="text-xs text-yellow-700">下書き合計</div>
              <div class="text-xl font-bold text-yellow-800" id="dr-total">—</div>
            </div>
            <div class="bg-red-50 rounded-lg border border-red-100 p-3">
              <div class="text-xs text-red-600">🖼️ アイキャッチなし</div>
              <div class="text-xl font-bold text-red-700" id="dr-noimg">—</div>
            </div>
            <div class="bg-amber-50 rounded-lg border border-amber-100 p-3">
              <div class="text-xs text-amber-700">🚗 交通事故</div>
              <div class="text-xl font-bold text-amber-800" id="dr-kotsu">—</div>
            </div>
            <div class="bg-orange-50 rounded-lg border border-orange-100 p-3">
              <div class="text-xs text-orange-700">⚠️ 労災</div>
              <div class="text-xl font-bold text-orange-800" id="dr-rosai">—</div>
            </div>
          </div>

          <!-- 下書きフィルター -->
          <div class="flex flex-wrap items-center gap-2 mb-3">
            <span class="text-xs text-gray-500">フィルター：</span>
            <button class="dr-filter-btn active text-xs px-3 py-1 rounded-full border border-gray-300 font-semibold" onclick="setDraftFilter('all',this)">全て</button>
            <button class="dr-filter-btn text-xs px-3 py-1 rounded-full border border-red-300 text-red-700 font-semibold" onclick="setDraftFilter('noimg',this)">🖼️ アイキャッチなし</button>
            <button class="dr-filter-btn text-xs px-3 py-1 rounded-full border border-amber-300 text-amber-700 font-semibold" onclick="setDraftFilter('kotsu',this)">🚗 交通事故</button>
            <button class="dr-filter-btn text-xs px-3 py-1 rounded-full border border-red-300 text-red-700 font-semibold" onclick="setDraftFilter('rosai',this)">⚠️ 労災</button>
            <button class="dr-filter-btn text-xs px-3 py-1 rounded-full border border-emerald-300 text-emerald-700 font-semibold" onclick="setDraftFilter('komon',this)">🏢 企業法務</button>
            <input type="text" id="dr-search" placeholder="タイトルで絞り込み..." oninput="renderDraftTable()"
              class="ml-auto border border-gray-200 rounded-lg px-3 py-1.5 text-xs w-52 focus:outline-none focus:border-yellow-400">
          </div>
          <div class="text-xs text-gray-400 mb-2" id="dr-count"></div>

          <!-- 下書きテーブル -->
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead>
                <tr class="bg-yellow-50 text-gray-500 uppercase tracking-wide select-none">
                  <th class="px-3 py-2 text-left cursor-pointer hover:bg-yellow-100" onclick="toggleDraftSort('title')">タイトル <span id="ds-title"></span></th>
                  <th class="px-3 py-2 text-left w-20 cursor-pointer hover:bg-yellow-100" onclick="toggleDraftSort('sho')">小カテゴリ <span id="ds-sho"></span></th>
                  <th class="px-3 py-2 text-center w-16">ジャンル</th>
                  <th class="px-3 py-2 text-center w-20 cursor-pointer hover:bg-yellow-100" onclick="toggleDraftSort('modified')">最終更新 <span id="ds-modified"></span></th>
                  <th class="px-3 py-2 text-center w-20 cursor-pointer hover:bg-yellow-100" onclick="toggleDraftSort('created')">作成日 <span id="ds-created"></span></th>
                  <th class="px-3 py-2 text-center w-14 cursor-pointer hover:bg-yellow-100" onclick="toggleDraftSort('eyecatch')">👁 <span id="ds-eyecatch"></span></th>
                  <th class="px-3 py-2 text-center w-16">WP編集</th>
                </tr>
              </thead>
              <tbody id="dr-tbody" class="divide-y divide-gray-100"></tbody>
            </table>
          </div>
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

    <!-- 問い合わせタブ -->
    <div id="tab-inquiry" class="tab-content">
      <div class="p-5">
        <div id="inq-nodata" class="hidden text-center text-gray-400 py-10">問い合わせデータなし</div>
        <div id="inq-main">
          <!-- KPIカード4枚 -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
            <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-blue-100">
              <div class="text-xs text-gray-500 mb-1">今月問い合わせ</div>
              <div class="flex items-baseline gap-1.5 flex-wrap">
                <div class="text-2xl font-bold text-gray-900" id="inq-kpi-this">—</div>
                <span class="text-xs font-bold" id="inq-kpi-delta"></span>
              </div>
              <div class="text-xs text-blue-600 mt-1">前月: <span id="inq-kpi-prev">—</span>件</div>
            </div>
            <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-purple-100">
              <div class="text-xs text-gray-500 mb-1">現在 相談中</div>
              <div class="text-2xl font-bold text-purple-700" id="inq-kpi-consult">—</div>
              <div class="text-xs text-purple-500 mt-1">アクティブ案件</div>
            </div>
            <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-green-100">
              <div class="text-xs text-gray-500 mb-1">受任済累計</div>
              <div class="text-2xl font-bold text-green-700" id="inq-kpi-contracted">—</div>
              <div class="text-xs text-green-500 mt-1">全期間</div>
            </div>
            <div class="kpi-card bg-white rounded-xl shadow-sm p-4 border border-indigo-100">
              <div class="text-xs text-gray-500 mb-1">受任率</div>
              <div class="text-2xl font-bold text-indigo-700" id="inq-kpi-rate">—</div>
              <div class="text-xs text-indigo-500 mt-1">全問い合わせ対比</div>
            </div>
          </div>

          <!-- グラフ2本 -->
          <div class="grid md:grid-cols-2 gap-5 mb-5">
            <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
              <div class="text-sm font-semibold text-gray-700 mb-3">月次問い合わせ数（ジャンル別）</div>
              <canvas id="chartInqMonthly" height="200"></canvas>
            </div>
            <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
              <div class="text-sm font-semibold text-gray-700 mb-3">月次受任数（ジャンル別）</div>
              <canvas id="chartContMonthly" height="200"></canvas>
            </div>
          </div>

          <!-- ステータス×ジャンル テーブル -->
          <div class="bg-white rounded-xl shadow-sm border border-gray-100 mb-5">
            <div class="px-4 pt-4 pb-2 text-sm font-semibold text-gray-700">ステータス × ジャンル（アーカイブ除く）</div>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                    <th class="px-4 py-2 text-left">ステータス</th>
                    <th class="px-4 py-2 text-center">全体</th>
                    <th class="px-4 py-2 text-center">🏢 企業法務</th>
                    <th class="px-4 py-2 text-center">⚠️ 労災</th>
                    <th class="px-4 py-2 text-center">🚗 交通事故</th>
                    <th class="px-4 py-2 text-center">📋 その他</th>
                  </tr>
                </thead>
                <tbody id="inq-status-tbody" class="divide-y divide-gray-100"></tbody>
              </table>
            </div>
          </div>

          <!-- 流入経路トップ8 -->
          <div class="bg-white rounded-xl shadow-sm border border-gray-100 mb-5 p-4">
            <div class="text-sm font-semibold text-gray-700 mb-3">流入経路トップ8</div>
            <div id="inq-sources" class="space-y-2"></div>
          </div>

          <!-- 最新30件テーブル -->
          <div class="bg-white rounded-xl shadow-sm border border-gray-100">
            <div class="px-4 pt-4 pb-2 text-sm font-semibold text-gray-700">最新30件</div>
            <div class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="bg-gray-50 text-gray-500 uppercase tracking-wide">
                    <th class="px-3 py-2 text-left">受付日</th>
                    <th class="px-3 py-2 text-left">氏名</th>
                    <th class="px-3 py-2 text-left">ジャンル</th>
                    <th class="px-3 py-2 text-left">流入経路</th>
                    <th class="px-3 py-2 text-left">ステータス</th>
                    <th class="px-3 py-2 text-left">担当</th>
                    <th class="px-3 py-2 text-center">リンク</th>
                  </tr>
                </thead>
                <tbody id="inq-tbody" class="divide-y divide-gray-100"></tbody>
              </table>
            </div>
          </div>

          <div class="text-xs text-gray-400 mt-2 text-right">取得日時: <span id="inq-synced"></span></div>
        </div>
      </div>
    </div>

    <!-- サイトマップタブ -->
    <div id="tab-sitemap" class="tab-content">
      <div class="p-5">
        <div class="flex items-center gap-3 mb-4 flex-wrap">
          <button id="sm-loadBtn"
            class="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors cursor-pointer disabled:cursor-not-allowed"
            onclick="smLoadSitemap()">サイトマップを取得</button>
          <span class="text-xs text-gray-400" id="sm-lastChecked"></span>
        </div>
        <div id="sm-status" class="text-sm text-gray-600 mb-2 min-h-[20px]"></div>
        <div class="w-full h-1 bg-gray-100 rounded mb-4 overflow-hidden"><div id="sm-progressFill" class="h-full bg-indigo-500 rounded transition-all" style="width:0%"></div></div>

        <div id="sm-summary" class="grid grid-cols-3 gap-4 mb-4 hidden">
          <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
            <div class="text-xs text-gray-500 mb-1">サブサイトマップ数</div>
            <div class="text-2xl font-bold text-indigo-600" id="sm-sumCount">-</div>
          </div>
          <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
            <div class="text-xs text-gray-500 mb-1">総URL数</div>
            <div class="text-2xl font-bold text-indigo-600" id="sm-sumUrls">-</div>
          </div>
          <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
            <div class="text-xs text-gray-500 mb-1">最終更新</div>
            <div class="text-lg font-bold text-indigo-600 pt-1" id="sm-sumLatest">-</div>
          </div>
        </div>

        <div id="sm-filterBar" class="flex items-center gap-3 mb-3 hidden">
          <input type="text" id="sm-filterInput"
            class="border border-gray-200 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:border-indigo-400"
            placeholder="サイトマップ名で絞り込み..." oninput="smFilterTable()">
          <span id="sm-filteredCount" class="text-xs text-gray-500"></span>
        </div>

        <!-- 表示切替 -->
        <div id="sm-viewToggle" class="hidden flex gap-2 mb-3">
          <button id="sm-viewList" class="sm-view-btn active px-3 py-1.5 text-xs font-semibold rounded-full border border-indigo-300 text-indigo-700 bg-indigo-50" onclick="smSetView('list',this)">📋 一覧</button>
          <button id="sm-viewTree" class="sm-view-btn px-3 py-1.5 text-xs font-semibold rounded-full border border-gray-300 text-gray-600" onclick="smSetView('tree',this)">🌳 ツリー</button>
        </div>

        <!-- 一覧ビュー -->
        <div class="overflow-x-auto hidden" id="sm-tableWrap">
          <table class="w-full text-sm bg-white rounded-xl shadow-sm overflow-hidden">
            <thead>
              <tr class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
                <th class="px-3 py-3 text-center cursor-pointer hover:bg-gray-100 select-none" onclick="smSortTable(0)">#</th>
                <th class="px-3 py-3 text-left cursor-pointer hover:bg-gray-100 select-none" onclick="smSortTable(1)">サイトマップ</th>
                <th class="px-3 py-3 text-center cursor-pointer hover:bg-gray-100 select-none" onclick="smSortTable(2)">URL数</th>
                <th class="px-3 py-3 text-center cursor-pointer hover:bg-gray-100 select-none" onclick="smSortTable(3)">最終更新</th>
                <th class="px-3 py-3 text-center">操作</th>
              </tr>
            </thead>
            <tbody id="sm-tableBody" class="divide-y divide-gray-100"></tbody>
          </table>
        </div>

        <!-- ツリービュー -->
        <div id="sm-treeWrap" class="hidden">
          <div class="flex items-center gap-3 mb-3">
            <input type="text" id="sm-treeSearch" placeholder="URLで絞り込み..."
              class="border border-gray-200 rounded-lg px-3 py-2 text-xs w-64 focus:outline-none focus:border-indigo-400"
              oninput="smRenderTree()">
            <button onclick="smExpandAll(true)"  class="text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50">全て展開</button>
            <button onclick="smExpandAll(false)" class="text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50">全て閉じる</button>
            <span class="text-xs text-gray-400" id="sm-treeCount"></span>
          </div>
          <div id="sm-tree" class="bg-white rounded-xl shadow-sm border border-gray-100 p-4 font-mono text-xs overflow-x-auto"></div>
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
const ARTICLES    = {json.dumps(articles_data or [])};
const DRAFTS      = {json.dumps(draft_articles or [])};
const GA4_TS      = {json.dumps(ga4_ts_cat  or {})};
const GSC_TS      = {json.dumps(gsc_ts_cat  or {})};
const GA4_TS_PREV = {json.dumps(ga4_ts_prev or {})};
const GSC_TS_PREV = {json.dumps(gsc_ts_prev or {})};
const GA4_TS_1Y   = {json.dumps(ga4_ts_1y  or {})};
const GSC_TS_1Y   = {json.dumps(gsc_ts_1y  or {})};
const GA4_TS_2Y   = {json.dumps(ga4_ts_2y  or {})};
const GA4_TS_3Y   = {json.dumps(ga4_ts_3y  or {})};
const GA4_MONTHLY = {json.dumps(ga4_monthly or {})};
const GSC_MONTHLY = {json.dumps(gsc_monthly or {})};
const INQ = {json.dumps(inquiry_data or {})};

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

// ── KPI更新・期間比較 ──────────────────────────────────────────
function fmt(n) {{ return Number(n).toLocaleString('ja-JP'); }}

let selectedPeriod = 30;
// 比較モード: 'none' | 'prev' | 'month' | '1y' | '2y' | '3y'
let compareMode = 'none';
let monthlyOn = false;

function sliceLast(arr, n) {{
  if (!arr || !arr.length) return [];
  return arr.slice(-Math.min(n, arr.length));
}}
function sumSlice(arr, n) {{
  return sliceLast(arr, n).reduce((a, b) => a + b, 0);
}}

function setPeriod(n, btn) {{
  selectedPeriod = n;
  document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  updateKpiCards(currentFilter);
}}

function setCompare(mode, btn) {{
  compareMode = mode;
  document.querySelectorAll('.cmp-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.compare-info').forEach(el =>
    el.classList.toggle('visible', mode !== 'none'));
  updateKpiCards(currentFilter);
}}

function toggleMonthly(btn) {{
  monthlyOn = !monthlyOn;
  btn.classList.toggle('monthly-on', monthlyOn);
  btn.textContent = monthlyOn ? '📅 月次グラフ ON' : '📅 月次グラフ';
  updateCharts(currentFilter);
}}

// 比較モードに対応する prev データセットを返す
function getPrevTs(cat) {{
  const ga4ts = GA4_TS[cat] || GA4_TS['all'] || null;
  const gscTs = GSC_TS[cat] || GSC_TS['all'] || null;
  let ga4prev = null, gscPrev = null, label = '';
  if (compareMode === 'prev') {{
    ga4prev = GA4_TS_PREV[cat] || GA4_TS_PREV['all'];
    gscPrev = GSC_TS_PREV[cat] || GSC_TS_PREV['all'];
    label = '前期';
  }} else if (compareMode === 'month') {{
    const gm = GA4_MONTHLY[cat] || GA4_MONTHLY['all'];
    const sm = GSC_MONTHLY[cat] || GSC_MONTHLY['all'];
    if (gm && gm.labels.length >= 2) {{
      const idx = gm.labels.length - 2;
      ga4prev = {{ labels: [gm.labels[idx]], sessions: [gm.sessions[idx]], conv: [gm.conv[idx]] }};
    }}
    if (sm && sm.labels.length >= 2) {{
      const idx = sm.labels.length - 2;
      gscPrev = {{ labels: [sm.labels[idx]], clicks: [sm.clicks[idx]], imps: [sm.imps[idx]] }};
    }}
    label = '前月';
  }} else if (compareMode === '1y') {{
    ga4prev = GA4_TS_1Y[cat] || GA4_TS_1Y['all'];
    gscPrev = GSC_TS_1Y[cat] || GSC_TS_1Y['all'];
    label = '前年同期';
  }} else if (compareMode === '2y') {{
    ga4prev = GA4_TS_2Y[cat] || GA4_TS_2Y['all'];
    label = '2年前同期';
  }} else if (compareMode === '3y') {{
    ga4prev = GA4_TS_3Y[cat] || GA4_TS_3Y['all'];
    label = '3年前同期';
  }}
  return {{ ga4ts, gscTs, ga4prev, gscPrev, label }};
}}

function setDelta(id, curr, prev, label) {{
  const el = document.getElementById('kpi-'+id+'-delta');
  const pi = document.getElementById('kpi-'+id+'-prev');
  if (!el) return;
  if (compareMode === 'none' || prev == null || prev === 0) {{
    el.textContent = '';
    el.className = 'kpi-delta';
    if (pi) pi.textContent = '';
    return;
  }}
  const pct = ((curr - prev) / prev * 100).toFixed(1);
  const sign = curr >= prev ? '▲' : '▼';
  el.textContent = `${{sign}}${{Math.abs(pct)}}%`;
  el.className = 'kpi-delta ' + (curr >= prev ? 'up' : 'dn');
  if (pi) pi.textContent = `${{label}}: ${{fmt(prev)}}`;
}}

function updateKpiCards(cat) {{
  const m     = catMetrics[cat];
  const label = CAT_LABELS[cat];
  const p     = selectedPeriod;
  const {{ ga4ts, gscTs, ga4prev, gscPrev, label: cmpLabel }} = getPrevTs(cat);

  // ── 比較モードによる前期数値取得
  let sessPrev = 0, convPrev = 0, clicksPrev = 0, impsPrev = 0;
  if (compareMode === 'month') {{
    // 月次比較: GA4_MONTHLY/GSC_MONTHLY の最後と最後から2番目を比較
    const gm = GA4_MONTHLY[cat] || GA4_MONTHLY['all'];
    const sm = GSC_MONTHLY[cat] || GSC_MONTHLY['all'];
    if (gm && gm.labels.length >= 2) {{
      sessPrev = gm.sessions[gm.sessions.length - 2] || 0;
      convPrev = gm.conv[gm.conv.length - 2] || 0;
    }}
    if (sm && sm.labels.length >= 2) {{
      clicksPrev = sm.clicks[sm.clicks.length - 2] || 0;
      impsPrev   = sm.imps[sm.imps.length - 2] || 0;
    }}
  }} else if (compareMode !== 'none') {{
    sessPrev   = ga4prev ? sumSlice(ga4prev.sessions, p) : 0;
    convPrev   = ga4prev ? sumSlice(ga4prev.conv,     p) : 0;
    clicksPrev = gscPrev ? sumSlice(gscPrev.clicks,   p) : 0;
    impsPrev   = gscPrev ? sumSlice(gscPrev.imps,     p) : 0;
  }}

  // ── セッション
  let sess = ga4ts ? sumSlice(ga4ts.sessions, p) : m.sessions;
  if (compareMode === 'month') {{
    const gm = GA4_MONTHLY[cat] || GA4_MONTHLY['all'];
    if (gm && gm.sessions.length) sess = gm.sessions[gm.sessions.length - 1];
  }}
  document.getElementById('kpi-sessions').textContent       = fmt(sess);
  document.getElementById('kpi-sessions-label').textContent = `セッション（${{compareMode === 'month' ? '今月' : p+'日'}}）`;
  document.getElementById('kpi-sessions-sub').textContent   = `GA4 · ${{label}}`;
  setDelta('sessions', sess, sessPrev, cmpLabel);

  // ── コンバージョン
  let conv = ga4ts ? sumSlice(ga4ts.conv, p) : m.conv;
  if (compareMode === 'month') {{
    const gm = GA4_MONTHLY[cat] || GA4_MONTHLY['all'];
    if (gm && gm.conv.length) conv = gm.conv[gm.conv.length - 1];
  }}
  document.getElementById('kpi-conv').textContent       = fmt(conv);
  document.getElementById('kpi-conv-label').textContent = `CV（${{compareMode === 'month' ? '今月' : p+'日'}}）`;
  document.getElementById('kpi-conv-sub').textContent   = `GA4 · ${{label}}`;
  setDelta('conv', conv, convPrev, cmpLabel);

  // ── クリック
  let clicks = gscTs ? sumSlice(gscTs.clicks, p) : m.clicks;
  if (compareMode === 'month') {{
    const sm = GSC_MONTHLY[cat] || GSC_MONTHLY['all'];
    if (sm && sm.clicks.length) clicks = sm.clicks[sm.clicks.length - 1];
  }}
  document.getElementById('kpi-clicks').textContent       = fmt(clicks);
  document.getElementById('kpi-clicks-label').textContent = `クリック（${{compareMode === 'month' ? '今月' : p+'日'}}）`;
  document.getElementById('kpi-clicks-sub').textContent   = `GSC · ${{label}} 順位${{m.pos}}位`;
  setDelta('clicks', clicks, clicksPrev, cmpLabel);

  // ── 表示回数
  let imps = gscTs ? sumSlice(gscTs.imps, p) : m.imps;
  if (compareMode === 'month') {{
    const sm = GSC_MONTHLY[cat] || GSC_MONTHLY['all'];
    if (sm && sm.imps.length) imps = sm.imps[sm.imps.length - 1];
  }}
  document.getElementById('kpi-imps').textContent       = fmt(imps);
  document.getElementById('kpi-imps-label').textContent = `表示回数（${{compareMode === 'month' ? '今月' : p+'日'}}）`;
  document.getElementById('kpi-imps-sub').textContent   = `GSC · ${{label}} CTR${{m.ctr}}%`;
  setDelta('imps', imps, impsPrev, cmpLabel);

  // ── 記事数（比較なし）
  document.getElementById('kpi-pub').textContent     = fmt(m.pub);
  document.getElementById('kpi-pub-sub').textContent = `draft ${{m.draft}}本 残`;

  // ── チャート更新
  updateCharts(cat);

  // ── ドーナツハイライト
  const catIdx = {{ all: -1, komon: 0, rosai: 1, kotsu: 2, other: 3 }}[cat];
  chartCpt.data.datasets[0].backgroundColor = cptColors.map((c, i) =>
    catIdx === -1 ? c : (i === catIdx ? c : c + '44')
  );
  chartCpt.data.datasets[0].borderWidth = cptColors.map((c, i) =>
    catIdx === -1 ? 1 : (i === catIdx ? 3 : 1)
  );
  chartCpt.update();
}}

function updateCharts(cat) {{
  if (monthlyOn) {{
    updateMonthlyCharts(cat);
  }} else {{
    updateDailyCharts(cat);
  }}
}}

function updateMonthlyCharts(cat) {{
  const gm = GA4_MONTHLY[cat] || GA4_MONTHLY['all'] || null;
  const sm = GSC_MONTHLY[cat] || GSC_MONTHLY['all'] || null;
  const n  = 12; // 最近12ヶ月

  if (gm) {{
    const labels   = sliceLast(gm.labels,   n);
    const sessions = sliceLast(gm.sessions, n);
    const conv     = sliceLast(gm.conv,     n);

    chartSessions.config.type = 'bar';
    chartSessions.data.labels = labels;
    chartSessions.data.datasets = [{{
      label: 'セッション', data: sessions,
      backgroundColor: '#6366f180', borderColor: '#6366f1', borderWidth: 1
    }}];
    // 前年同月比（GA4_MONTHLY から -12ヶ月スライスで近似）
    if (compareMode === '1y' && gm.sessions.length > n) {{
      const prev12s = gm.sessions.slice(-(n * 2), -n);
      if (prev12s.length > 0) {{
        chartSessions.data.datasets.push({{
          label: '前年', data: prev12s,
          backgroundColor: '#6366f130', borderColor: '#6366f180', borderWidth: 1
        }});
      }}
    }}
    chartSessions.options.plugins.legend.display = chartSessions.data.datasets.length > 1;
    chartSessions.update();

    chartConv.config.type = 'bar';
    chartConv.data.labels = labels;
    chartConv.data.datasets = [{{ label: 'CV', data: conv, backgroundColor: '#10b981aa' }}];
    chartConv.options.plugins.legend.display = false;
    chartConv.update();
  }}

  if (sm) {{
    const labels = sliceLast(sm.labels,  n);
    const clicks = sliceLast(sm.clicks,  n);

    chartClicks.config.type = 'bar';
    chartClicks.data.labels = labels;
    chartClicks.data.datasets = [{{
      label: 'クリック', data: clicks,
      backgroundColor: '#f59e0b80', borderColor: '#f59e0b', borderWidth: 1
    }}];
    chartClicks.options.plugins.legend.display = false;
    chartClicks.update();
  }}
}}

function updateDailyCharts(cat) {{
  const N = selectedPeriod;
  const {{ ga4ts, gscTs, ga4prev, gscPrev, label: cmpLabel }} = getPrevTs(cat);

  if (ga4ts && ga4ts.labels && ga4ts.labels.length) {{
    const currLabels   = sliceLast(ga4ts.labels,   N);
    const currSessions = sliceLast(ga4ts.sessions,  N);
    const currConv     = sliceLast(ga4ts.conv,      N);

    chartSessions.config.type = 'line';
    chartSessions.data.labels = currLabels;
    chartSessions.data.datasets[0].data = currSessions;
    chartSessions.data.datasets[0].label = `セッション（現在${{N}}日）`;
    if (compareMode !== 'none' && ga4prev && ga4prev.sessions) {{
      const prevSess = sliceLast(ga4prev.sessions, N);
      if (chartSessions.data.datasets.length < 2) {{
        chartSessions.data.datasets.push({{
          label: cmpLabel, data: prevSess,
          borderColor: '#94a3b8', borderDash: [5, 5], backgroundColor: 'transparent',
          fill: false, tension: 0.3, pointRadius: 1, order: 2
        }});
      }} else {{
        chartSessions.data.datasets[1].data  = prevSess;
        chartSessions.data.datasets[1].label = cmpLabel;
      }}
    }} else {{ chartSessions.data.datasets.splice(1); }}
    chartSessions.options.plugins.legend.display = compareMode !== 'none' && chartSessions.data.datasets.length > 1;
    chartSessions.update('none');

    chartConv.config.type = 'bar';
    chartConv.data.labels = currLabels;
    chartConv.data.datasets[0].data = currConv;
    chartConv.data.datasets[0].label = `CV（現在${{N}}日）`;
    if (compareMode !== 'none' && ga4prev && ga4prev.conv) {{
      const prevConv = sliceLast(ga4prev.conv, N);
      if (chartConv.data.datasets.length < 2) {{
        chartConv.data.datasets.push({{
          type: 'bar', label: cmpLabel, data: prevConv, backgroundColor: '#94a3b833', order: 2
        }});
      }} else {{
        chartConv.data.datasets[1].data  = prevConv;
        chartConv.data.datasets[1].label = cmpLabel;
      }}
    }} else {{ chartConv.data.datasets.splice(1); }}
    chartConv.options.plugins.legend.display = compareMode !== 'none' && chartConv.data.datasets.length > 1;
    chartConv.update('none');
  }}

  if (gscTs && gscTs.labels && gscTs.labels.length) {{
    const currLabels = sliceLast(gscTs.labels,  N);
    const currClicks = sliceLast(gscTs.clicks,  N);
    const currImps   = sliceLast(gscTs.imps,    N).map(v => Math.round(v / 100));

    chartClicks.config.type = 'line';
    chartClicks.data.labels = currLabels;
    chartClicks.data.datasets[0].data = currClicks;
    chartClicks.data.datasets[0].label = `クリック（現在${{N}}日）`;
    chartClicks.data.datasets[1].data = currImps;

    if (compareMode !== 'none' && gscPrev && gscPrev.clicks) {{
      const prevClicks = sliceLast(gscPrev.clicks, N);
      if (chartClicks.data.datasets.length < 3) {{
        chartClicks.data.datasets.push({{
          label: `${{cmpLabel}}クリック`, data: prevClicks,
          borderColor: '#fbbf2488', borderDash: [5, 5], tension: 0.3, pointRadius: 1, fill: false
        }});
      }} else {{
        chartClicks.data.datasets[2].data  = prevClicks;
        chartClicks.data.datasets[2].label = `${{cmpLabel}}クリック`;
      }}
    }} else {{ chartClicks.data.datasets.splice(2); }}
    chartClicks.options.plugins.legend.display = true;
    chartClicks.update('none');
  }}
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

  // 記事ステータス（メイン行）
  let cptVisible = 0;
  document.querySelectorAll('.cpt-row').forEach(row => {{
    const show = cat === 'all' || row.dataset.cat === cat;
    row.style.display = show ? '' : 'none';
    if (show) cptVisible++;
  }});
  // 記事ステータス（展開行）- 開いているものだけ表示
  document.querySelectorAll('.cpt-expand-row').forEach(row => {{
    const matchesCat = cat === 'all' || row.dataset.cat === cat;
    const isOpen = row.dataset.open === 'true';
    row.style.display = (matchesCat && isOpen) ? '' : 'none';
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

  // 記事管理タブが表示中なら再描画
  if (document.getElementById('tab-artmgr').classList.contains('active')) {{
    renderArtTable();
  }}
}}

function switchTab(name, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (btn) btn.classList.add('active');
  applyFilter();  // タブ切替時にも現在のフィルターを再適用
  if (name === 'artmgr') renderArtTable();
}}

// ── 記事一覧展開（WP REST API） ──────────────────────────────────────
function toggleCptArticles(slug, rowEl) {{
  const expandRow = document.getElementById('cpt-expand-row-' + slug);
  const container = document.getElementById('cpt-expand-' + slug);
  const icon = rowEl.querySelector('.cpt-expand-icon');

  if (expandRow.dataset.open === 'true') {{
    expandRow.dataset.open = 'false';
    expandRow.style.display = 'none';
    if (icon) icon.textContent = '▶';
    return;
  }}

  if (icon) icon.textContent = '⏳';

  (async () => {{
    try {{
      const base = 'https://law-bright.com/wp-json/wp/v2/';
      const pubUrl = base + slug + '?per_page=30&orderby=modified&order=desc&_fields=id,title,link,modified,status';
      const dftUrl = base + slug + '?per_page=10&orderby=modified&order=desc&_fields=id,title,link,modified,status&status=draft';

      const [pubRes, dftRes] = await Promise.allSettled([fetch(pubUrl), fetch(dftUrl)]);
      const pubList = pubRes.status === 'fulfilled' && pubRes.value.ok ? await pubRes.value.json() : [];
      const dftList = dftRes.status === 'fulfilled' && dftRes.value.ok ? await dftRes.value.json() : [];

      const makeRows = (items, statusLabel, rowCls) =>
        items.map(a => `<tr class="hover:bg-indigo-100 transition-colors ${{rowCls}}">
          <td class="py-1.5 pr-3 max-w-xs">
            ${{statusLabel === '公開' ? `<a href="${{a.link}}" target="_blank" class="text-blue-700 hover:underline">${{a.title.rendered}}</a>` : `<span class="text-gray-600">${{a.title.rendered}}</span>`}}
          </td>
          <td class="py-1.5 pr-2 text-center text-gray-400 whitespace-nowrap">${{(a.modified||'').slice(0,10)}}</td>
          <td class="py-1.5 text-center whitespace-nowrap">
            <span class="${{statusLabel === '公開' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}} text-xs px-1.5 py-0.5 rounded-full mr-1">${{statusLabel}}</span>
            ${{statusLabel === '公開' ? `<a href="${{a.link}}" target="_blank" class="text-blue-500 hover:underline mr-1" title="記事を表示">↗</a>` : ''}}
            <a href="https://law-bright.com/wp-admin/post.php?post=${{a.id}}&action=edit" target="_blank" class="text-orange-500 hover:underline" title="WPで編集">✏️</a>
          </td>
        </tr>`).join('');

      if (pubList.length === 0 && dftList.length === 0) {{
        container.innerHTML = '<div class="text-gray-400 py-2 text-center">記事を取得できませんでした（WP REST API 非公開CPTの可能性）</div>';
      }} else {{
        container.innerHTML =
          '<table class="w-full text-xs">' +
          '<thead><tr class="text-gray-500 border-b border-indigo-200 text-left">' +
          '<th class="py-1 pr-3 font-semibold">タイトル</th>' +
          '<th class="py-1 pr-2 text-center font-semibold w-24">更新日</th>' +
          '<th class="py-1 text-center font-semibold w-28">操作</th>' +
          '</tr></thead>' +
          '<tbody class="divide-y divide-indigo-100">' +
          makeRows(pubList, '公開', '') +
          makeRows(dftList, '下書き', 'opacity-70') +
          '</tbody></table>' +
          '<div class="text-right text-gray-400 mt-1.5">公開 ' + pubList.length + '件 · 下書き ' + dftList.length + '件（更新日順）</div>';
      }}

      expandRow.dataset.open = 'true';
      expandRow.style.display = '';
      if (icon) icon.textContent = '▼';
    }} catch(e) {{
      container.innerHTML = '<div class="text-red-500 py-2">取得エラー: ' + e.message + '</div>';
      expandRow.dataset.open = 'true';
      expandRow.style.display = '';
      if (icon) icon.textContent = '❌';
    }}
  }})();
}}

// ── サイトマップビューア（西田紗知さん作成） ──────────────────────────
const SM_SITEMAP_INDEX = 'https://law-bright.com/sitemap.xml';
const SM_PROXIES = [
  url => `https://api.allorigins.win/raw?url=${{encodeURIComponent(url)}}`,
  url => `https://corsproxy.io/?${{encodeURIComponent(url)}}`,
  url => `https://api.codetabs.com/v1/proxy?quest=${{encodeURIComponent(url)}}`,
];
let smAllRows = [];
let smAllUrls = []; // url/sitemap の全URL一覧
let smSortCol = -1, smSortAsc = true;
let smView = 'list'; // 'list' | 'tree'

function smSetStatus(msg, type='') {{
  const el = document.getElementById('sm-status');
  el.textContent = msg;
  el.style.color = type === 'err' ? '#dc2626' : type === 'ok' ? '#16a34a' : '#4a5568';
}}

function smSetProgress(pct) {{
  document.getElementById('sm-progressFill').style.width = pct + '%';
}}

async function smFetchXML(url) {{
  let lastErr;
  for (const proxy of SM_PROXIES) {{
    try {{
      const res = await fetch(proxy(url), {{ signal: AbortSignal.timeout(8000) }});
      if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
      const text = await res.text();
      if (!text.trim().startsWith('<')) throw new Error('XMLではないレスポンス');
      return new DOMParser().parseFromString(text, 'text/xml');
    }} catch (e) {{ lastErr = e; }}
  }}
  throw lastErr;
}}

function smFormatDate(str) {{
  if (!str) return '-';
  try {{
    const d = new Date(str);
    return d.toLocaleDateString('ja-JP', {{year:'numeric',month:'2-digit',day:'2-digit'}})
      + ' ' + d.toLocaleTimeString('ja-JP', {{hour:'2-digit',minute:'2-digit'}});
  }} catch {{ return str; }}
}}

async function smLoadSitemap() {{
  const btn = document.getElementById('sm-loadBtn');
  btn.disabled = true;
  document.getElementById('sm-tableWrap').classList.add('hidden');
  document.getElementById('sm-summary').classList.add('hidden');
  document.getElementById('sm-filterBar').classList.add('hidden');
  smSetProgress(5);
  smSetStatus('sitemap.xml を取得中...');

  try {{
    const indexDoc = await smFetchXML(SM_SITEMAP_INDEX);
    const sitemaps = [...indexDoc.querySelectorAll('sitemap')];
    smSetProgress(15);
    smSetStatus(`${{sitemaps.length}} 件のサブサイトマップを確認。URL数を取得中...`);

    smAllRows = [];
    smAllUrls = [];
    let totalUrls = 0;
    let latestDate = '';

    for (let i = 0; i < sitemaps.length; i++) {{
      const locEl = sitemaps[i].querySelector('loc');
      const lastmodEl = sitemaps[i].querySelector('lastmod');
      if (!locEl) continue;
      const smUrl = locEl.textContent.trim();
      const lastmod = lastmodEl ? lastmodEl.textContent.trim() : '';
      const name = smUrl.replace('https://law-bright.com/', '').replace('.xml', '');

      let count = '-';
      try {{
        const subDoc = await smFetchXML(smUrl);
        const urlEls = subDoc.querySelectorAll('url');
        count = urlEls.length;
        totalUrls += count;
        urlEls.forEach(el => {{
          const loc = el.querySelector('loc');
          if (loc) smAllUrls.push({{ url: loc.textContent.trim(), sitemap: name }});
        }});
      }} catch (e) {{ count = 'エラー'; }}

      if (lastmod && lastmod > latestDate) latestDate = lastmod;
      smAllRows.push({{ url: smUrl, name, count, lastmod }});
      smSetProgress(15 + Math.round((i + 1) / sitemaps.length * 80));
      smSetStatus(`取得中... (${{i + 1}}/${{sitemaps.length}}) ${{name}}`);
      smRenderTable(smAllRows);
    }}

    document.getElementById('sm-sumCount').textContent = smAllRows.length;
    document.getElementById('sm-sumUrls').textContent = totalUrls.toLocaleString();
    document.getElementById('sm-sumLatest').textContent = smFormatDate(latestDate).split(' ')[0];
    document.getElementById('sm-summary').classList.remove('hidden');
    document.getElementById('sm-filterBar').classList.remove('hidden');
    document.getElementById('sm-filteredCount').textContent = `${{smAllRows.length}} 件`;
    document.getElementById('sm-lastChecked').textContent = '最終取得: ' + new Date().toLocaleString('ja-JP');
    document.getElementById('sm-viewToggle').classList.remove('hidden');
    smSetProgress(100);
    smSetStatus(`完了 — ${{smAllRows.length}} サイトマップ、合計 ${{totalUrls.toLocaleString()}} URL`, 'ok');
    smRenderTree();
  }} catch (e) {{
    smSetStatus('取得エラー: ' + e.message, 'err');
    console.error(e);
  }}

  btn.disabled = false;
  setTimeout(() => smSetProgress(0), 1000);
}}

function smRenderTable(rows) {{
  const tbody = document.getElementById('sm-tableBody');
  const filter = (document.getElementById('sm-filterInput')?.value || '').toLowerCase();
  const filtered = filter ? rows.filter(r => r.name.toLowerCase().includes(filter)) : rows;

  tbody.innerHTML = filtered.map((r, i) => `
    <tr class="hover:bg-gray-50 transition-colors">
      <td class="px-3 py-2 text-center text-gray-400 text-xs">${{i + 1}}</td>
      <td class="px-3 py-2">
        <a href="${{r.url}}" target="_blank" class="text-blue-700 font-mono text-xs hover:underline">${{r.name}}</a>
        ${{r.name.includes('cat') ? '<span class="inline-block ml-1 px-1 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded">カテゴリ</span>' : ''}}
        ${{r.name === 'addl-sitemap' ? '<span class="inline-block ml-1 px-1 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded">追加</span>' : ''}}
      </td>
      <td class="px-3 py-2 text-center">
        ${{typeof r.count === 'number'
          ? `<span class="inline-block bg-blue-100 text-blue-800 text-xs font-semibold px-2 py-1 rounded-full">${{r.count.toLocaleString()}} URLs</span>`
          : `<span class="text-red-600 text-xs">${{r.count}}</span>`}}
      </td>
      <td class="px-3 py-2 text-center text-gray-500 text-xs">${{smFormatDate(r.lastmod)}}</td>
      <td class="px-3 py-2 text-center">
        <button class="bg-gray-100 hover:bg-gray-200 text-gray-600 border border-gray-200 px-2 py-1 rounded text-xs cursor-pointer transition-colors"
          onclick="window.open('${{r.url}}','_blank')">開く</button>
      </td>
    </tr>
  `).join('');

  document.getElementById('sm-tableWrap').classList.remove('hidden');
  const fc = document.getElementById('sm-filteredCount');
  if (fc) fc.textContent = `${{filtered.length}} 件`;
}}

function smFilterTable() {{ smRenderTable(smAllRows); }}

// ── サイトマップ ツリービュー ─────────────────────────────
const SM_CPT_MAP = {{
  'labor-accident':   {{ label: '⚠️ 労災',    cls: 'sm-cpt-rosai', bg: '#fef2f2', badge: '#fee2e2', tx: '#dc2626' }},
  'kotuziko':         {{ label: '🚗 交通事故', cls: 'sm-cpt-kotsu', bg: '#fffbeb', badge: '#fde68a', tx: '#d97706' }},
  'corporationlaw':   {{ label: '🏢 企業法務', cls: 'sm-cpt-komon', bg: '#f0fdf4', badge: '#bbf7d0', tx: '#059669' }},
  'legaladvisor':     {{ label: '🏢 顧問',    cls: 'sm-cpt-komon', bg: '#f0fdf4', badge: '#bbf7d0', tx: '#059669' }},
  'manda':            {{ label: '🤝 M&A',      cls: 'sm-cpt-manda', bg: '#ecfeff', badge: '#a5f3fc', tx: '#0891b2' }},
  'employee':         {{ label: '👤 問題社員', cls: 'sm-cpt-emp',   bg: '#faf5ff', badge: '#e9d5ff', tx: '#7c3aed' }},
  'bankruptcy':       {{ label: '🏛️ 破産・倒産', cls: 'sm-cpt-bk', bg: '#f9fafb', badge: '#e5e7eb', tx: '#6b7280' }},
  'inheritance':      {{ label: '🏛️ 相続',    cls: 'sm-cpt-bk',   bg: '#f9fafb', badge: '#e5e7eb', tx: '#6b7280' }},
  'page':             {{ label: '📄 固定ページ', cls: 'sm-cpt-page', bg: '#eff6ff', badge: '#bfdbfe', tx: '#1d4ed8' }},
  'post':             {{ label: '📝 ブログ',   cls: 'sm-cpt-page', bg: '#eff6ff', badge: '#bfdbfe', tx: '#1d4ed8' }},
  'glossary':         {{ label: '📚 用語集',   cls: 'sm-cpt-other', bg: '#f8fafc', badge: '#e2e8f0', tx: '#475569' }},
  'download':         {{ label: '📥 資料DL',   cls: 'sm-cpt-other', bg: '#f8fafc', badge: '#e2e8f0', tx: '#475569' }},
}};

function smCptOf(path) {{
  const seg = path.replace(/^\\//, '').split('/')[0];
  return SM_CPT_MAP[seg] || {{ label: '📋 ' + seg, cls: 'sm-cpt-other', bg: '#f8fafc', badge: '#e2e8f0', tx: '#475569' }};
}}

function smSetView(view, btn) {{
  smView = view;
  document.querySelectorAll('.sm-view-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('sm-tableWrap').classList.toggle('hidden', view !== 'list');
  document.getElementById('sm-treeWrap').classList.toggle('hidden', view !== 'tree');
  document.getElementById('sm-filterBar').classList.toggle('hidden', view !== 'list');
  if (view === 'tree') smRenderTree();
}}

function smBuildTree(urls, query) {{
  const root = {{}};
  const q = (query || '').toLowerCase();
  let matched = 0;
  for (const {{url}} of urls) {{
    const path = url.replace('https://law-bright.com', '');
    if (q && !path.toLowerCase().includes(q)) continue;
    matched++;
    const parts = path.replace(/^\\//, '').split('/').filter(Boolean);
    let node = root;
    for (let i = 0; i < parts.length; i++) {{
      const p = parts[i];
      if (!node[p]) node[p] = {{ _children: {{}}, _urls: [] }};
      if (i === parts.length - 1) node[p]._urls.push(url);
      node = node[p]._children;
    }}
  }}
  return {{ tree: root, matched }};
}}

function smCountUrls(node) {{
  let n = node._urls ? node._urls.length : 0;
  for (const k of Object.keys(node._children || {{}})) n += smCountUrls(node._children[k]);
  return n;
}}

function smHighlight(text, q) {{
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return text.slice(0, i) + '<mark class="sm-hl">' + text.slice(i, i + q.length) + '</mark>' + text.slice(i + q.length);
}}

// 直接の子URL（記事リスト）を折りたたみボックスで表示
function smRenderUrlBox(urls, cpt, q) {{
  if (!urls || urls.length === 0) return '';
  const MAX_SHOW = 50;
  const shown = urls.slice(0, MAX_SHOW);
  const more = urls.length - shown.length;
  const items = shown.map(u => {{
    const slug = u.replace(/\/$/, '').split('/').pop();
    const hl = smHighlight(slug, q);
    return `<a href="${{u}}" target="_blank" class="block px-2 py-0.5 rounded hover:bg-white text-blue-600 hover:underline truncate" title="${{u}}">${{hl}}</a>`;
  }}).join('');
  const moreHtml = more > 0 ? `<div class="text-gray-400 px-2 py-1 text-xs">… 他 ${{more}} 件</div>` : '';
  return `<div class="sm-url-box ml-6 mt-1 mb-2 bg-gray-50 border border-gray-200 rounded-lg p-2 max-h-48 overflow-y-auto text-xs leading-5">${{items}}${{moreHtml}}</div>`;
}}

function smRenderNodeHtml(name, node, depth, q, cptCtx) {{
  const count = smCountUrls(node);
  if (count === 0) return '';
  const cpt = depth === 0 ? smCptOf('/' + name) : cptCtx;
  const childKeys = Object.keys(node._children || {{}}).sort();
  const hasChildren = childKeys.length > 0;
  const directUrls = node._urls || [];

  const outerStyle = depth === 0
    ? `background:${{cpt.bg}};border-left:3px solid ${{cpt.tx}};border-radius:6px;margin:4px 0;padding:2px 6px 2px 6px;`
    : '';
  const indent = depth === 0 ? 0 : (depth - 1) * 18;
  const hl = smHighlight(name, q);
  const badgeStyle = `background:${{cpt.badge}};color:${{cpt.tx}};`;
  const label = depth === 0 ? `${{cpt.label}}&nbsp;&nbsp;<span class="font-mono">${{hl}}/</span>` : `<span class="font-mono">${{hl}}/</span>`;

  // ディレクトリノード（子あり）→ details で折りたたみ
  if (hasChildren) {{
    const openAttr = (depth < 1 || q) ? ' open' : '';
    const childHtml = childKeys.map(k => smRenderNodeHtml(k, node._children[k], depth + 1, q, cpt)).join('');
    // 同ディレクトリに直接URLもある場合はボックスで末尾に追加
    const directBox = directUrls.length > 0 ? smRenderUrlBox(directUrls, cpt, q) : '';
    return `<div class="sm-tree-node" style="padding-left:${{indent}}px">
  <details${{openAttr}} style="${{outerStyle}}">
    <summary>
      <span class="sm-arrow">▶</span>
      <span class="${{cpt.cls}} font-semibold">${{label}}</span>
      <span class="sm-badge" style="${{badgeStyle}}">${{count}}</span>
    </summary>
    <div class="pl-4">${{childHtml}}${{directBox}}</div>
  </details></div>`;
  }}

  // 末端ディレクトリ（子ディレクトリなし・直接URLのみ）→ 件数バッジ＋URLボックス
  if (directUrls.length > 0) {{
    const openAttr = q ? ' open' : '';
    const urlBox = smRenderUrlBox(directUrls, cpt, q);
    return `<div class="sm-tree-node" style="padding-left:${{indent}}px">
  <details${{openAttr}} style="${{outerStyle}}">
    <summary>
      <span class="sm-arrow">▶</span>
      <span class="${{cpt.cls}}">${{label}}</span>
      <span class="sm-badge" style="${{badgeStyle}}">${{directUrls.length}} 記事</span>
    </summary>
    ${{urlBox}}
  </details></div>`;
  }}

  return '';
}}

function smRenderTree() {{
  const container = document.getElementById('sm-tree');
  if (!container || smAllUrls.length === 0) return;
  const q = (document.getElementById('sm-treeSearch')?.value || '');
  const {{ tree, matched }} = smBuildTree(smAllUrls, q);
  const countEl = document.getElementById('sm-treeCount');
  if (countEl) countEl.textContent = q ? `${{matched.toLocaleString()}} / ${{smAllUrls.length.toLocaleString()}} URL` : `${{smAllUrls.length.toLocaleString()}} URL`;

  const topKeys = Object.keys(tree).sort((a, b) => {{
    const order = ['labor-accident','kotuziko','corporationlaw','legaladvisor','manda','employee','bankruptcy','inheritance','page','post','glossary','download'];
    const ai = order.indexOf(a), bi = order.indexOf(b);
    if (ai < 0 && bi < 0) return a.localeCompare(b);
    if (ai < 0) return 1; if (bi < 0) return -1;
    return ai - bi;
  }});

  container.innerHTML = topKeys.map(k => smRenderNodeHtml(k, tree[k], 0, q, null)).join('') ||
    '<div class="text-gray-400 py-8 text-center">該当URLなし</div>';
}}

function smExpandAll(open) {{
  document.querySelectorAll('#sm-tree details').forEach(d => d.open = open);
}}

// ── 記事管理タブ ──────────────────────────────────────
const DAI_CAT = {{'労災':'rosai','交通事故':'kotsu','企業法務':'komon'}};
let artFilter  = 'all';
let artSortCol = 'date';
let artSortAsc = false;

function setArtFilter(f, btn) {{
  artFilter = f;
  document.querySelectorAll('.am-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderArtTable();
}}

function toggleArtSort(col) {{
  if (artSortCol === col) artSortAsc = !artSortAsc;
  else {{ artSortCol = col; artSortAsc = true; }}
  ['title','sho','date','eyecatch','position','clicks','status'].forEach(c => {{
    const el = document.getElementById('s-' + c);
    if (el) el.textContent = '';
  }});
  const el = document.getElementById('s-' + col);
  if (el) el.textContent = artSortAsc ? ' ▲' : ' ▼';
  renderArtTable();
}}

function renderArtTable() {{
  const tbody = document.getElementById('am-tbody');
  if (!tbody) return;
  const cat    = currentFilter;
  const search = (document.getElementById('am-search')?.value || '').toLowerCase();

  let items = ARTICLES.filter(a => {{
    if (cat !== 'all') {{
      const ac = DAI_CAT[a.dai] || 'other';
      if (ac !== cat) return false;
    }}
    if (artFilter === 'top10'   && (!a.position || a.position > 10))              return false;
    if (artFilter === 'rewrite' && (!a.position || a.position <= 20 || (a.clicks||0) >= 10)) return false;
    if (artFilter === 'rise'    && !(a.status||'').includes('急上昇'))              return false;
    if (artFilter === 'drop'    && !(a.status||'').includes('急落'))               return false;
    if (artFilter === 'noimg'   && a.eyecatch)                                     return false;
    if (artFilter === 'new'     && !(a.status||'').includes('新規'))               return false;
    if (search) {{
      const hay = ((a.title||'') + ' ' + (a.top_query||'')).toLowerCase();
      if (!hay.includes(search)) return false;
    }}
    return true;
  }});

  items.sort((a, b) => {{
    let va, vb;
    if      (artSortCol === 'title')    {{ va = a.title   ||''; vb = b.title   ||''; }}
    else if (artSortCol === 'sho')      {{ va = a.sho     ||''; vb = b.sho     ||''; }}
    else if (artSortCol === 'date')     {{ va = a.date    ||''; vb = b.date    ||''; }}
    else if (artSortCol === 'eyecatch') {{ va = a.eyecatch? 1:0; vb = b.eyecatch? 1:0; }}
    else if (artSortCol === 'position') {{ va = a.position||999; vb = b.position||999; }}
    else if (artSortCol === 'clicks')   {{ va = a.clicks  ||0;  vb = b.clicks  ||0; }}
    else if (artSortCol === 'status')   {{ va = a.status  ||''; vb = b.status  ||''; }}
    else {{ va = 0; vb = 0; }}
    if (va < vb) return artSortAsc ? -1 : 1;
    if (va > vb) return artSortAsc ? 1 : -1;
    return 0;
  }});

  tbody.innerHTML = items.map(a => {{
    const pos    = a.position;
    const posStr = pos ? pos.toFixed(1) : '—';
    const posCls = !pos ? 'text-gray-300'
      : pos <= 3  ? 'text-green-700 font-bold'
      : pos <= 10 ? 'text-green-600'
      : pos <= 20 ? 'text-yellow-600' : 'text-red-600';
    const st    = a.status || '—';
    const stCls = st.includes('急上昇') ? 'text-green-600 font-bold'
      : st.includes('改善')   ? 'text-green-500'
      : st.includes('急落')   ? 'text-red-600 font-bold'
      : st.includes('悪化')   ? 'text-orange-500'
      : st.includes('新規')   ? 'text-blue-600' : 'text-gray-400';
    const eye  = a.eyecatch ? '✅' : '<span class="text-red-400">✗</span>';
    const clks = a.clicks   ? a.clicks.toLocaleString('ja-JP') : '—';
    const wpEd = 'https://law-bright.com/wp-admin/post.php?post=' + a.id + '&action=edit';
    const tq   = a.top_query || '—';
    return `<tr class="hover:bg-gray-50 transition-colors">
      <td class="px-3 py-2 max-w-xs">
        <a href="${{a.link}}" target="_blank" class="text-blue-700 hover:underline">${{a.title}}</a>
        <span class="text-gray-400 text-xs ml-1">${{a.dai}}</span>
      </td>
      <td class="px-3 py-2 text-gray-600 text-xs">${{a.sho}}</td>
      <td class="px-3 py-2 text-center text-gray-500 whitespace-nowrap">${{a.date}}</td>
      <td class="px-3 py-2 text-center">${{eye}}</td>
      <td class="px-3 py-2 text-center ${{posCls}}">${{posStr}}</td>
      <td class="px-3 py-2 text-center font-semibold">${{clks}}</td>
      <td class="px-3 py-2 text-gray-500 text-xs truncate max-w-[9rem]" title="${{tq}}">${{tq}}</td>
      <td class="px-3 py-2 text-center ${{stCls}} whitespace-nowrap text-xs">${{st}}</td>
      <td class="px-3 py-2 text-center whitespace-nowrap">
        <a href="${{a.link}}" target="_blank" class="text-blue-500 text-xs hover:underline mr-1" title="表示">↗</a>
        <a href="${{wpEd}}" target="_blank" class="text-orange-500 text-xs hover:underline" title="WP編集">✏️</a>
      </td>
    </tr>`;
  }}).join('');

  const countEl = document.getElementById('am-count');
  if (countEl) countEl.textContent = items.length.toLocaleString('ja-JP') + ' 件 / 全 ' + ARTICLES.length.toLocaleString('ja-JP') + ' 件';
  const setCard = (id, val) => {{ const el = document.getElementById(id); if (el) el.textContent = val; }};
  setCard('am-total',   ARTICLES.length.toLocaleString('ja-JP'));
  setCard('am-top10',   ARTICLES.filter(a => a.position && a.position <= 10).length);
  setCard('am-rewrite', ARTICLES.filter(a => a.position && a.position > 20 && (a.clicks||0) < 10).length);
  setCard('am-drop',    ARTICLES.filter(a => (a.status||'').includes('急落')).length);
}}

document.addEventListener('DOMContentLoaded', () => {{
  renderArtTable();
  renderDraftTable();
  // バッジ更新
  const badge = document.getElementById('draft-count-badge');
  if (badge) badge.textContent = DRAFTS.length;
}});

// ── 下書きビュー ──────────────────────────────────────────
let artView     = 'pub'; // 'pub' | 'draft'
let draftFilter = 'all';
let draftSortCol = 'modified';
let draftSortAsc = false;

function setArtView(view, btn) {{
  artView = view;
  document.querySelectorAll('.amview-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('amview-pub-content').classList.toggle('hidden', view !== 'pub');
  document.getElementById('amview-draft-content').classList.toggle('hidden', view !== 'draft');
}}

function setDraftFilter(f, btn) {{
  draftFilter = f;
  document.querySelectorAll('.dr-filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderDraftTable();
}}

function toggleDraftSort(col) {{
  if (draftSortCol === col) draftSortAsc = !draftSortAsc;
  else {{ draftSortCol = col; draftSortAsc = false; }}
  ['title','sho','modified','created','eyecatch'].forEach(c => {{
    const el = document.getElementById('ds-' + c);
    if (el) el.textContent = '';
  }});
  const el = document.getElementById('ds-' + col);
  if (el) el.textContent = draftSortAsc ? ' ▲' : ' ▼';
  renderDraftTable();
}}

function renderDraftTable() {{
  const tbody  = document.getElementById('dr-tbody');
  if (!tbody) return;
  const cat    = currentFilter;
  const search = (document.getElementById('dr-search')?.value || '').toLowerCase();
  const DAI_MAP = {{ '労災':'rosai', '交通事故':'kotsu', '企業法務':'komon' }};

  let items = DRAFTS.filter(d => {{
    const dc = DAI_MAP[d.dai] || 'other';
    if (cat !== 'all' && dc !== cat) return false;
    if (draftFilter === 'noimg'  && d.eyecatch)   return false;
    if (draftFilter === 'kotsu'  && dc !== 'kotsu')  return false;
    if (draftFilter === 'rosai'  && dc !== 'rosai')  return false;
    if (draftFilter === 'komon'  && dc !== 'komon')  return false;
    if (search && !(d.title||'').toLowerCase().includes(search)) return false;
    return true;
  }});

  items.sort((a, b) => {{
    let va, vb;
    if      (draftSortCol === 'title')    {{ va = a.title   ||''; vb = b.title   ||''; }}
    else if (draftSortCol === 'sho')      {{ va = a.sho     ||''; vb = b.sho     ||''; }}
    else if (draftSortCol === 'modified') {{ va = a.modified||''; vb = b.modified||''; }}
    else if (draftSortCol === 'created')  {{ va = a.created ||''; vb = b.created ||''; }}
    else if (draftSortCol === 'eyecatch') {{ va = a.eyecatch?1:0; vb = b.eyecatch?1:0; }}
    else {{ va = ''; vb = ''; }}
    if (va < vb) return draftSortAsc ? -1 : 1;
    if (va > vb) return draftSortAsc ? 1 : -1;
    return 0;
  }});

  // サマリ更新
  const setV = (id, v) => {{ const el=document.getElementById(id); if(el) el.textContent=v; }};
  setV('dr-total', DRAFTS.length.toLocaleString('ja-JP'));
  setV('dr-noimg', DRAFTS.filter(d => !d.eyecatch).length);
  setV('dr-kotsu', DRAFTS.filter(d => d.dai === '交通事故').length);
  setV('dr-rosai', DRAFTS.filter(d => d.dai === '労災').length);

  const countEl = document.getElementById('dr-count');
  if (countEl) countEl.textContent = items.length.toLocaleString('ja-JP') + ' 件 / 全 ' + DRAFTS.length.toLocaleString('ja-JP') + ' 件';

  const DAI_STYLE = {{
    '労災':    'bg-red-100 text-red-700',
    '交通事故':'bg-amber-100 text-amber-700',
    '企業法務':'bg-emerald-100 text-emerald-700',
  }};

  tbody.innerHTML = items.map(d => {{
    const eye   = d.eyecatch ? '✅' : '<span class="text-red-400 font-bold">✗</span>';
    const wpEd  = 'https://law-bright.com/wp-admin/post.php?post=' + d.id + '&action=edit';
    const dstyle = DAI_STYLE[d.dai] || 'bg-gray-100 text-gray-600';
    const mod   = d.modified || '—';
    const modCls = !d.modified ? '' :
      d.modified >= new Date(Date.now()-7*86400000).toISOString().slice(0,10)
        ? 'text-green-700 font-semibold' : '';
    return `<tr class="hover:bg-yellow-50 transition-colors">
      <td class="px-3 py-2 max-w-xs">
        <a href="${{wpEd}}" target="_blank" class="text-gray-800 hover:text-indigo-700 hover:underline">${{d.title}}</a>
      </td>
      <td class="px-3 py-2 text-gray-500 text-xs">${{d.sho || '—'}}</td>
      <td class="px-3 py-2 text-center"><span class="text-xs px-2 py-0.5 rounded-full ${{dstyle}}">${{d.dai}}</span></td>
      <td class="px-3 py-2 text-center text-xs ${{modCls}}">${{mod}}</td>
      <td class="px-3 py-2 text-center text-xs text-gray-400">${{d.created || '—'}}</td>
      <td class="px-3 py-2 text-center">${{eye}}</td>
      <td class="px-3 py-2 text-center">
        <a href="${{wpEd}}" target="_blank" class="text-orange-500 text-xs hover:underline font-semibold">✏️ 編集</a>
      </td>
    </tr>`;
  }}).join('');
}}

function smSortTable(col) {{
  if (smSortCol === col) smSortAsc = !smSortAsc;
  else {{ smSortCol = col; smSortAsc = true; }}
  smAllRows.sort((a, b) => {{
    if (col === 0) return 0;
    let va, vb;
    if (col === 1) {{ va = a.name; vb = b.name; }}
    else if (col === 2) {{ va = typeof a.count === 'number' ? a.count : -1; vb = typeof b.count === 'number' ? b.count : -1; }}
    else if (col === 3) {{ va = a.lastmod || ''; vb = b.lastmod || ''; }}
    if (va < vb) return smSortAsc ? -1 : 1;
    if (va > vb) return smSortAsc ? 1 : -1;
    return 0;
  }});
  smRenderTable(smAllRows);
}}

// ── 問い合わせタブ初期化 ──────────────────────────────────────
(function initInquiry() {{
  if (!INQ || !INQ.recent) {{
    const nd = document.getElementById('inq-nodata');
    const mn = document.getElementById('inq-main');
    if (nd) nd.classList.remove('hidden');
    if (mn) mn.classList.add('hidden');
    return;
  }}

  // KPIカード更新
  const setEl = (id, val) => {{ const el = document.getElementById(id); if (el) el.textContent = val; }};
  setEl('inq-kpi-this',       INQ.this_month ?? '—');
  setEl('inq-kpi-prev',       INQ.prev_month ?? '—');
  setEl('inq-kpi-contracted', INQ.contracted ?? '—');
  setEl('inq-kpi-rate',       (INQ.cont_rate ?? '—') + '%');
  setEl('inq-synced',         INQ.synced_at ?? '');

  // 今月前月差分バッジ
  const deltaEl = document.getElementById('inq-kpi-delta');
  if (deltaEl && INQ.prev_month > 0) {{
    const d = (INQ.this_month || 0) - (INQ.prev_month || 0);
    deltaEl.textContent = (d >= 0 ? '▲+' : '▼') + d + '件';
    deltaEl.className = 'text-xs font-bold ' + (d >= 0 ? 'text-green-600' : 'text-red-600');
  }}

  // 相談中件数
  const ss = INQ.status_summary || {{}};
  const consultTotal = (ss['相談中'] || {{}}).total || 0;
  setEl('inq-kpi-consult', consultTotal);

  // グラフ
  const months = INQ.months || [];
  const catColors = {{komon:'#10b981', rosai:'#ef4444', kotsu:'#f59e0b', other:'#94a3b8'}};
  const catLabels = {{komon:'企業法務', rosai:'労災', kotsu:'交通事故', other:'その他'}};
  const stackedOpts = {{
    responsive: true,
    scales: {{ x: {{ stacked: true, ticks: {{ font: {{ size: 10 }} }} }}, y: {{ stacked: true, ticks: {{ font: {{ size: 10 }} }} }} }},
    plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }},
                tooltip: {{ mode: 'index', intersect: false }} }}
  }};

  const makeDatasets = (monthlyObj) =>
    ['komon','rosai','kotsu','other'].map(c => ({{
      label: catLabels[c],
      data: months.map(m => ((monthlyObj[m] || {{}})[c] || 0)),
      backgroundColor: catColors[c] + 'cc',
      stack: 's'
    }}));

  const inqCanvas = document.getElementById('chartInqMonthly');
  if (inqCanvas) {{
    new Chart(inqCanvas, {{
      type: 'bar',
      data: {{ labels: months, datasets: makeDatasets(INQ.monthly_inq || {{}}) }},
      options: stackedOpts
    }});
  }}

  const contCanvas = document.getElementById('chartContMonthly');
  if (contCanvas) {{
    new Chart(contCanvas, {{
      type: 'bar',
      data: {{ labels: months, datasets: makeDatasets(INQ.monthly_cont || {{}}) }},
      options: stackedOpts
    }});
  }}

  // ステータス×ジャンル テーブル
  const statusTbody = document.getElementById('inq-status-tbody');
  if (statusTbody) {{
    const statuses = ['問い合わせ中','相談中','受任済','不成立'];
    const statusColors = {{
      '問い合わせ中': 'bg-blue-100 text-blue-700',
      '相談中':       'bg-purple-100 text-purple-700',
      '受任済':       'bg-green-100 text-green-700',
      '不成立':       'bg-gray-100 text-gray-600',
    }};
    statusTbody.innerHTML = statuses.map(st => {{
      const row = ss[st] || {{}};
      const cls = statusColors[st] || 'bg-gray-100 text-gray-600';
      return `<tr class="hover:bg-gray-50 transition-colors">
        <td class="px-4 py-2"><span class="inline-block ${{cls}} text-xs font-semibold px-2 py-1 rounded-full">${{st}}</span></td>
        <td class="px-4 py-2 text-center font-bold text-gray-800">${{row.total ?? 0}}</td>
        <td class="px-4 py-2 text-center text-emerald-700">${{row.komon ?? 0}}</td>
        <td class="px-4 py-2 text-center text-red-700">${{row.rosai ?? 0}}</td>
        <td class="px-4 py-2 text-center text-amber-700">${{row.kotsu ?? 0}}</td>
        <td class="px-4 py-2 text-center text-gray-600">${{row.other ?? 0}}</td>
      </tr>`;
    }}).join('');
  }}

  // 流入経路トップ8
  const srcEl = document.getElementById('inq-sources');
  if (srcEl && INQ.top_sources) {{
    const maxCnt = Math.max(...INQ.top_sources.map(s => s.cnt), 1);
    srcEl.innerHTML = INQ.top_sources.map(s => {{
      const pct = Math.round(s.cnt / maxCnt * 100);
      return `<div class="flex items-center gap-3">
        <div class="w-28 text-xs text-gray-600 text-right truncate flex-shrink-0" title="${{s.src}}">${{s.src}}</div>
        <div class="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
          <div class="h-4 bg-indigo-400 rounded-full transition-all" style="width:${{pct}}%"></div>
        </div>
        <div class="w-8 text-xs text-gray-600 font-semibold text-right">${{s.cnt}}</div>
      </div>`;
    }}).join('');
  }}

  // 最新30件テーブル
  const tbody = document.getElementById('inq-tbody');
  if (tbody && INQ.recent) {{
    const catBadge = {{
      komon: 'bg-emerald-100 text-emerald-700',
      rosai: 'bg-red-100 text-red-700',
      kotsu: 'bg-amber-100 text-amber-700',
      other: 'bg-gray-100 text-gray-600',
    }};
    const catLabel = {{komon:'企業法務', rosai:'労災', kotsu:'交通事故', other:'その他'}};
    const stBadge = {{
      '問い合わせ中': 'bg-blue-100 text-blue-700',
      '相談中':       'bg-purple-100 text-purple-700',
      '受任済':       'bg-green-100 text-green-700',
      '不成立':       'bg-gray-100 text-gray-600',
    }};
    tbody.innerHTML = INQ.recent.map(r => {{
      const cb = catBadge[r.cat_key] || 'bg-gray-100 text-gray-600';
      const cl = catLabel[r.cat_key] || r.cat;
      const sb = stBadge[r.status]   || 'bg-gray-100 text-gray-600';
      const link = r.url
        ? `<a href="${{r.url}}" target="_blank" class="inline-block bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded hover:bg-indigo-200 transition-colors">開く</a>`
        : '<span class="text-gray-300">—</span>';
      return `<tr class="hover:bg-gray-50 transition-colors">
        <td class="px-3 py-2 whitespace-nowrap text-gray-600">${{r.date}}</td>
        <td class="px-3 py-2 text-gray-800">${{r.name || '—'}}</td>
        <td class="px-3 py-2"><span class="inline-block ${{cb}} text-xs font-semibold px-2 py-0.5 rounded-full">${{cl}}</span></td>
        <td class="px-3 py-2 text-gray-600 truncate max-w-[8rem]" title="${{r.source}}">${{r.source}}</td>
        <td class="px-3 py-2"><span class="inline-block ${{sb}} text-xs font-semibold px-2 py-0.5 rounded-full">${{r.status}}</span></td>
        <td class="px-3 py-2 text-gray-600">${{r.lawyer || '—'}}</td>
        <td class="px-3 py-2 text-center">${{link}}</td>
      </tr>`;
    }}).join('');
  }}
}})();
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

    # GA4/GSC: APIから取得 → 失敗時はフォールバックデータを使用
    print("⏳ GA4/GSCデータを取得中...")
    GA4_LIVE        = fetch_ga4(days=30)
    GA4_CAT_LIVE    = fetch_ga4_by_cat(days=30)
    GA4_TS_LIVE     = fetch_ga4_timeseries_cat(days=30)
    GA4_TS_PREV     = fetch_ga4_ts_offset(days=30, offset_days=30, label="前期")
    GSC_LIVE        = fetch_gsc_daily(days=28)
    GSC_PAGES_LIVE  = fetch_gsc_pages(days=28, limit=20)
    GSC_TS_LIVE     = fetch_gsc_timeseries_cat(days=28)
    GSC_TS_PREV     = fetch_gsc_ts_offset(days=28, offset_days=28, label="前期")
    GA4_TS_1Y       = fetch_ga4_ts_offset(days=30, offset_days=365, label="前年")
    GSC_TS_1Y       = fetch_gsc_ts_offset(days=28, offset_days=365, label="前年")
    GA4_TS_2Y       = fetch_ga4_ts_offset(days=30, offset_days=730, label="2年前")
    GA4_TS_3Y       = fetch_ga4_ts_offset(days=30, offset_days=1095, label="3年前")
    GA4_MONTHLY     = fetch_ga4_monthly(months=36)
    GSC_MONTHLY     = fetch_gsc_monthly(months=16)

    # ── フォールバックデータ（APIが使えない場合） ──────────────
    GA4_DATA = GA4_LIVE or [
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
    GSC_DAILY_FALLBACK = [
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
    GSC_PAGES_FALLBACK = [
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

    GSC_DAILY  = GSC_LIVE  or GSC_DAILY_FALLBACK
    GSC_PAGES  = GSC_PAGES_LIVE or GSC_PAGES_FALLBACK

    # AppSheet問い合わせデータ取得
    print("⏳ AppSheet問い合わせデータ取得中...")
    inquiry_data = fetch_inquiry_data()

    # 記事管理データ取得
    print("⏳ 記事管理データ取得中...")
    wp_articles = fetch_all_articles_wp()
    draft_articles = fetch_draft_articles_wp()
    gsc_curr, gsc_prev, top_queries = fetch_gsc_for_articles(days=30)
    articles_data = []
    for art in wp_articles:
        url = art["link"]
        curr = gsc_curr.get(url, {})
        prev = gsc_prev.get(url, {})
        pos_ch, clk_ch, status = calc_article_change(curr, prev)
        articles_data.append({**art,
            "clicks":     curr.get("clicks", 0),
            "imps":       curr.get("impressions", 0),
            "position":   curr.get("position"),
            "top_query":  top_queries.get(url, ""),
            "pos_change": pos_ch,
            "clk_change": clk_ch,
            "status":     status,
        })
    print(f"  記事管理: {len(articles_data)}本 マージ完了")

    print("⏳ HTML生成中...")
    print(f"  下書き記事: {len(draft_articles)}本")
    html = generate_html(cpt_data, GA4_DATA, GSC_DAILY, GSC_PAGES, articles_data,
                         GA4_CAT_LIVE, GA4_TS_LIVE, GSC_TS_LIVE,
                         GA4_TS_PREV, GSC_TS_PREV,
                         inquiry_data=inquiry_data,
                         ga4_ts_1y=GA4_TS_1Y, gsc_ts_1y=GSC_TS_1Y,
                         ga4_ts_2y=GA4_TS_2Y, ga4_ts_3y=GA4_TS_3Y,
                         ga4_monthly=GA4_MONTHLY, gsc_monthly=GSC_MONTHLY,
                         draft_articles=draft_articles)
    out_path = Path(__file__).parent / "docs" / "index.html"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 生成完了 → {out_path} ({out_path.stat().st_size:,} bytes)")
