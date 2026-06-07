"""
SQLite 데이터 저장/조회 모듈
briefing.py 실행 시 수집된 데이터를 날짜별로 저장
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "jarvis.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            spend REAL DEFAULT 0,
            meta_roas REAL DEFAULT 0,
            meta_purchases REAL DEFAULT 0,
            meta_cpa REAL DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0,
            add_to_cart REAL DEFAULT 0,
            imweb_order_count INTEGER DEFAULT 0,
            imweb_revenue INTEGER DEFAULT 0,
            imweb_aov REAL DEFAULT 0,
            imweb_roas REAL DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            campaign_name TEXT,
            spend REAL DEFAULT 0,
            roas REAL DEFAULT 0,
            purchases REAL DEFAULT 0,
            cpa REAL DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS competitor_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            product_type TEXT,
            name TEXT,
            price INTEGER DEFAULT 0,
            sale_rate INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            review_score REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS competitor_analysis (
            date TEXT PRIMARY KEY,
            competitor_highlight TEXT,
            codegraphy_strength TEXT,
            akro_gap TEXT,
            immediate_action TEXT,
            benchmark_products TEXT
        );

        CREATE TABLE IF NOT EXISTS briefing_analysis (
            date TEXT PRIMARY KEY,
            overall_assessment TEXT,
            weekly_trends TEXT,
            action_items TEXT,
            optimization_suggestions TEXT
        );
        """)


def save_daily_stats(date, account, imweb, helpers):
    """Meta 광고 + 아임웹 일별 통계 저장"""
    spend = float(account.get("spend", 0))
    r = helpers["roas"](account.get("action_values"), spend)
    act = helpers["parse_actions"](account.get("actions"))
    purchases = act["purchase"]
    cpa_val = helpers["cpa"](spend, purchases)

    imweb_order = imweb["order_count"] if imweb else 0
    imweb_rev = imweb["revenue"] if imweb else 0
    imweb_aov = imweb["aov"] if imweb else 0
    imweb_roas = round(imweb_rev / spend, 2) if imweb and spend > 0 else 0

    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_stats
            (date, spend, meta_roas, meta_purchases, meta_cpa,
             clicks, impressions, ctr, add_to_cart,
             imweb_order_count, imweb_revenue, imweb_aov, imweb_roas, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                date, spend, r, purchases, cpa_val,
                int(account.get("clicks", 0)),
                int(account.get("impressions", 0)),
                float(account.get("ctr", 0)),
                act["add_to_cart"],
                imweb_order, imweb_rev, imweb_aov, imweb_roas,
                datetime.now().isoformat(),
            ),
        )


def save_campaigns(date, campaigns, helpers):
    """캠페인별 성과 저장"""
    with get_conn() as conn:
        conn.execute("DELETE FROM campaigns WHERE date = ?", (date,))
        for c in campaigns:
            c_spend = float(c.get("spend", 0))
            c_pur = helpers["parse_actions"](c.get("actions"))["purchase"]
            c_roas = helpers["roas"](c.get("action_values"), c_spend)
            c_cpa = helpers["cpa"](c_spend, c_pur)
            conn.execute(
                """INSERT INTO campaigns
                (date, campaign_name, spend, roas, purchases, cpa, clicks, impressions, ctr)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    date, c.get("campaign_name", ""),
                    c_spend, c_roas, c_pur, c_cpa,
                    int(c.get("clicks", 0)),
                    int(c.get("impressions", 0)),
                    float(c.get("ctr", 0)),
                ),
            )


def save_competitor(date, codegraphy_data, competitor_analysis):
    """경쟁사(코드그라피) 데이터 및 AI 분석 저장"""
    with get_conn() as conn:
        conn.execute("DELETE FROM competitor_products WHERE date = ?", (date,))
        for p in codegraphy_data.get("best_sellers", []):
            conn.execute(
                """INSERT INTO competitor_products
                (date, product_type, name, price, sale_rate, review_count, review_score)
                VALUES (?,?,?,?,?,?,?)""",
                (date, "best_seller", p["name"],
                 p.get("price", 0), p.get("sale_rate", 0),
                 p.get("review_count", 0), p.get("review_score", 0)),
            )
        for p in codegraphy_data.get("new_products", []):
            conn.execute(
                """INSERT INTO competitor_products
                (date, product_type, name, price, sale_rate, review_count, review_score)
                VALUES (?,?,?,?,?,?,?)""",
                (date, "new_product", p["name"],
                 p.get("price", 0), p.get("sale_rate", 0),
                 p.get("review_count", 0), p.get("review_score", 0)),
            )
        if competitor_analysis:
            conn.execute(
                """INSERT OR REPLACE INTO competitor_analysis
                (date, competitor_highlight, codegraphy_strength, akro_gap,
                 immediate_action, benchmark_products)
                VALUES (?,?,?,?,?,?)""",
                (
                    date,
                    competitor_analysis.get("competitor_highlight", ""),
                    competitor_analysis.get("codegraphy_strength", ""),
                    competitor_analysis.get("akro_gap", ""),
                    competitor_analysis.get("immediate_action", ""),
                    json.dumps(
                        competitor_analysis.get("benchmark_products", []),
                        ensure_ascii=False,
                    ),
                ),
            )


def save_briefing_analysis(date, analysis):
    """Claude AI 분석 결과 저장"""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO briefing_analysis
            (date, overall_assessment, weekly_trends, action_items, optimization_suggestions)
            VALUES (?,?,?,?,?)""",
            (
                date,
                analysis.get("overall_assessment", ""),
                json.dumps(analysis.get("weekly_trends", []), ensure_ascii=False),
                json.dumps(analysis.get("action_items", []), ensure_ascii=False),
                json.dumps(
                    analysis.get("optimization_suggestions", []), ensure_ascii=False
                ),
            ),
        )


# ── 조회 함수 ──────────────────────────────────────────────────────

def get_latest_stats(n=7):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_campaigns(date=None):
    with get_conn() as conn:
        if not date:
            row = conn.execute("SELECT MAX(date) FROM campaigns").fetchone()
            date = row[0] if row else None
        if not date:
            return []
        rows = conn.execute(
            "SELECT * FROM campaigns WHERE date = ? ORDER BY spend DESC", (date,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_competitor_data(date=None):
    with get_conn() as conn:
        if not date:
            row = conn.execute(
                "SELECT MAX(date) FROM competitor_products"
            ).fetchone()
            date = row[0] if row else None
        if not date:
            return {"best_sellers": [], "new_products": [], "analysis": None, "date": None}

        products = conn.execute(
            "SELECT * FROM competitor_products WHERE date = ?", (date,)
        ).fetchall()
        analysis = conn.execute(
            "SELECT * FROM competitor_analysis WHERE date = ?", (date,)
        ).fetchone()

        best = [dict(p) for p in products if p["product_type"] == "best_seller"]
        new = [dict(p) for p in products if p["product_type"] == "new_product"]
        ana = dict(analysis) if analysis else None
        if ana and ana.get("benchmark_products"):
            try:
                ana["benchmark_products"] = json.loads(ana["benchmark_products"])
            except Exception:
                ana["benchmark_products"] = []

        return {"date": date, "best_sellers": best, "new_products": new, "analysis": ana}


def get_briefing_analysis(date=None):
    with get_conn() as conn:
        if not date:
            row = conn.execute(
                "SELECT MAX(date) FROM briefing_analysis"
            ).fetchone()
            date = row[0] if row else None
        if not date:
            return None
        row = conn.execute(
            "SELECT * FROM briefing_analysis WHERE date = ?", (date,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("weekly_trends", "action_items", "optimization_suggestions"):
            try:
                result[key] = json.loads(result.get(key) or "[]")
            except Exception:
                result[key] = []
        return result
