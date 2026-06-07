#!/usr/bin/env python3
"""
아크로 쇼핑몰 Daily 브리핑 시스템
실행: python briefing.py
"""

import os
import sys
import json
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("[ERR] requests가 없습니다. pip install requests 실행 후 재시도하세요.")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERR] python-dotenv가 없습니다. pip install python-dotenv 실행 후 재시도하세요.")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("[ERR] anthropic이 없습니다. pip install anthropic 실행 후 재시도하세요.")
    sys.exit(1)


# ── Jarvis DB 연동 (선택적) ──────────────────────────────────────
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent / "jarvis"))
    import db as _jarvis_db
    _JARVIS_OK = True
except ImportError:
    _JARVIS_OK = False

# ── 환경변수 로드 ────────────────────────────────────────────────
load_dotenv()
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN")
IMWEB_API_KEY      = os.getenv("IMWEB_API_KEY")
IMWEB_SECRET_KEY   = os.getenv("IMWEB_SECRET_KEY")

if not all([ANTHROPIC_API_KEY, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID]):
    print("[ERR] .env 파일에 ANTHROPIC_API_KEY, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID 세 항목이 필요합니다.")
    sys.exit(1)

# ── 날짜 ────────────────────────────────────────────────────────
now        = datetime.now()
yesterday  = (now - timedelta(days=1)).strftime("%Y-%m-%d")
yesterday_d = (now - timedelta(days=1)).strftime("%Y%m%d")   # 아임웹용 YYYYMMDD
week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

META_BASE     = "https://graph.facebook.com/v19.0"
KAKAO_MEMO    = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
IMWEB_BASE    = "https://api.imweb.me/v2"
COMMON_FIELDS = "spend,impressions,reach,clicks,ctr,cpc,actions,action_values"

# 결제 완료로 간주하는 아임웹 주문 상태
PAID_STATUSES = {"payment_complete", "ready", "ing", "delivery", "done"}

# ── 코드그라피 경쟁사 정보 ────────────────────────────────────────
CODEGRAPHY = {
    "name": "코드그라피",
    "platform": "무신사 입점 유틸리티 스트릿웨어",
    "revenue_2025": "600억대",
    "female_ratio": "70%",
    "strengths": "K팝 셀럽 마케팅(세븐틴 호시) · CGP 로고 IP화 · 프리미엄 소재+가성비 · 셋업 스테디셀러",
    "url": "https://www.musinsa.com/brand/codegraphy",
}

_MUSINSA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.musinsa.com/",
}


# ── Meta Ads API ─────────────────────────────────────────────────
def _meta_get(url, params):
    params["access_token"] = META_ACCESS_TOKEN
    r = requests.get(url, params=params, timeout=30)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        print(f"  [WARN] Meta API {r.status_code}: {r.text[:200]}")
        raise
    return r.json()


def fetch_account_insights():
    data = _meta_get(
        f"{META_BASE}/{META_AD_ACCOUNT_ID}/insights",
        {"date_preset": "yesterday", "fields": COMMON_FIELDS, "level": "account"},
    )
    return data.get("data", [{}])[0] if data.get("data") else {}


def fetch_campaign_insights():
    data = _meta_get(
        f"{META_BASE}/{META_AD_ACCOUNT_ID}/insights",
        {
            "date_preset": "yesterday",
            "fields": f"campaign_name,{COMMON_FIELDS}",
            "level": "campaign",
            "filtering": json.dumps([{"field": "spend", "operator": "GREATER_THAN", "value": "0"}]),
            "limit": 30,
        },
    )
    return data.get("data", [])


def fetch_weekly_insights():
    data = _meta_get(
        f"{META_BASE}/{META_AD_ACCOUNT_ID}/insights",
        {
            "time_range": json.dumps({"since": week_start, "until": yesterday}),
            "fields": COMMON_FIELDS,
            "level": "account",
            "time_increment": "1",
        },
    )
    return data.get("data", [])


# ── 아임웹 API ───────────────────────────────────────────────────
def get_imweb_token():
    r = requests.post(
        f"{IMWEB_BASE}/auth",
        json={"key": IMWEB_API_KEY, "secret": IMWEB_SECRET_KEY},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 200:
        raise Exception(f"아임웹 인증 실패: {body}")
    # 응답 구조: {"code":200, "access_token":"..."}  (data 중첩 없음)
    return body["access_token"]


def fetch_imweb_orders(token):
    """전체 주문 수집 후 어제 날짜로 클라이언트 필터링
    (아임웹 API date 필터 미작동으로 인해 order_time 기준 직접 필터)"""
    import time
    from datetime import date as date_cls

    headers  = {"access-token": token}
    all_orders = []
    page     = 1
    pagesize = 100  # API 최대 100건

    # 어제의 Unix timestamp 범위 (로컬 자정 기준)
    yd           = (now - timedelta(days=1)).date()
    yd_start_ts  = int(datetime.combine(yd, datetime.min.time()).timestamp())
    yd_end_ts    = int(datetime.combine(yd, datetime.max.time()).timestamp())

    while True:
        for attempt in range(3):
            r = requests.get(
                f"{IMWEB_BASE}/shop/orders",
                headers=headers,
                params={"limit": pagesize, "page": page},
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") == -7:
                wait = (attempt + 1) * 10
                print(f"  [WAIT] 아임웹 Rate Limit — {wait}초 대기 후 재시도...")
                time.sleep(wait)
                continue
            if body.get("code") != 200:
                raise Exception(f"아임웹 주문 조회 실패: {body}")
            break
        else:
            raise Exception("아임웹 API Rate Limit 초과 — 잠시 후 재시도하세요.")

        items = body["data"].get("list", [])

        # 어제 날짜 + 결제금액 있는 주문만 추가
        for o in items:
            ot = o.get("order_time", 0)
            paid = int(o.get("payment", {}).get("payment_amount", 0))
            if yd_start_ts <= ot <= yd_end_ts and paid > 0:
                all_orders.append(o)

        paging     = body["data"].get("pagenation", {})
        total_page = paging.get("total_page", 1)
        last_ts    = items[-1].get("order_time", 0) if items else 0
        if page >= total_page or last_ts < yd_start_ts:
            break
        page += 1
        time.sleep(0.2)

    return all_orders


def parse_imweb_stats(orders):
    """결제 금액 합산 — payment.payment_amount 사용"""
    order_count = len(orders)
    revenue     = sum(int(o.get("payment", {}).get("payment_amount", 0)) for o in orders)
    aov         = round(revenue / order_count, 0) if order_count > 0 else 0
    return {"order_count": order_count, "revenue": revenue, "aov": aov}


# ── Meta 데이터 파싱 헬퍼 ────────────────────────────────────────
def parse_actions(lst):
    result = {"purchase": 0, "add_to_cart": 0, "initiate_checkout": 0}
    for item in (lst or []):
        t = item.get("action_type", "")
        v = float(item.get("value", 0))
        if "purchase" in t:
            result["purchase"] += v
        elif "add_to_cart" in t:
            result["add_to_cart"] += v
        elif "initiate_checkout" in t:
            result["initiate_checkout"] += v
    return result


def purchase_value(action_values_list):
    total = 0.0
    for av in (action_values_list or []):
        if "purchase" in av.get("action_type", ""):
            total += float(av.get("value", 0))
    return total


def roas(action_values_list, spend):
    spend_f = float(spend or 0)
    if spend_f == 0:
        return 0.0
    return round(purchase_value(action_values_list) / spend_f, 2)


def cpa(spend, count):
    return round(float(spend) / count, 0) if count > 0 else 0


# ── 코드그라피 무신사 크롤링 ─────────────────────────────────────
def fetch_codegraphy():
    """무신사 코드그라피 베스트셀러·신상품 수집"""
    result = {"best_sellers": [], "new_products": [], "error": None}

    _BASE = "https://api.musinsa.com/api2/dp/v2/plp/goods"
    _HEADERS = {
        **_MUSINSA_HEADERS,
        "Referer": "https://www.musinsa.com/brand/codegraphy/products",
        "Origin":  "https://www.musinsa.com",
    }

    def _fetch(sort_code, size=5):
        r = requests.get(
            _BASE,
            params={"gf": "A", "sortCode": sort_code, "brand": "codegraphy",
                    "page": 1, "size": size, "caller": "FLAGSHIP"},
            headers=_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("list", [])

    def _parse(it):
        price = it.get("normalPrice") or it.get("price") or 0
        return {
            "name":         it.get("goodsName", ""),
            "price":        price,
            "sale_rate":    it.get("saleRate") or 0,
            "review_count": it.get("reviewCount") or 0,
            "review_score": it.get("reviewScore") or 0,
        }

    try:
        items = _fetch("POPULAR", 5)
        result["best_sellers"] = [_parse(it) for it in items]
        print(f"  [OK] 코드그라피 베스트셀러 {len(result['best_sellers'])}건")
    except Exception as e:
        result["error"] = str(e)
        print(f"  [WARN] 코드그라피 베스트셀러 수집 실패: {e}")

    try:
        new_items = _fetch("NEWEST", 3)
        result["new_products"] = [_parse(it) for it in new_items]
        print(f"  [OK] 코드그라피 신상품 {len(result['new_products'])}건")
    except Exception as e:
        print(f"  [WARN] 코드그라피 신상품 수집 실패: {e}")

    return result


# ── 코드그라피 AI 벤치마킹 분석 ──────────────────────────────────
def get_competitor_analysis(codegraphy_data, account, imweb):
    spend     = float(account.get("spend", 0))
    r         = roas(account.get("action_values"), spend)

    best = codegraphy_data.get("best_sellers", [])
    new  = codegraphy_data.get("new_products", [])

    best_str = (
        "\n".join(
            f"  {i+1}. {p['name']} / {int(p.get('price',0)):,}원"
            f" / 리뷰 {int(p.get('review_count',0)):,}개 ({p.get('review_score',0)}점)"
            for i, p in enumerate(best)
        )
        if best else "  (수집 실패 — 무신사 API 미응답)"
    )
    new_str = (
        " · ".join(f"{p['name']}({int(p.get('price',0)):,}원)" for p in new)
        if new else "없음"
    )

    imweb_str = (
        f"실제 주문 {imweb['order_count']:,}건 / 매출 {imweb['revenue']:,}원"
        if imweb and imweb["order_count"] > 0 else "데이터 없음"
    )

    prompt = f"""당신은 패션 이커머스 전략 전문가입니다. 아크로와 경쟁사 코드그라피를 비교 분석하세요.

[코드그라피 기본 정보]
- {CODEGRAPHY['platform']} / 2025년 매출 {CODEGRAPHY['revenue_2025']} / 여성 비중 {CODEGRAPHY['female_ratio']}
- 핵심 강점: {CODEGRAPHY['strengths']}

[코드그라피 무신사 베스트셀러 Top5 (오늘 기준)]
{best_str}

[코드그라피 이번 주 신상품]
{new_str}

[아크로 어제({yesterday}) 성과]
- 광고비: {spend:,.0f}원 / 광고 ROAS: {r}x
- {imweb_str}

아래 JSON 형식으로만 응답하세요(마크다운 코드블록 제외):

{{
  "competitor_highlight": "이번 주 코드그라피 핵심 한 줄 (20자 이내, 카카오톡용)",
  "codegraphy_strength": "이번 주 코드그라피가 잘 하고 있는 것 (2~3문장)",
  "akro_gap": "아크로가 놓치고 있는 포인트 (2~3문장)",
  "immediate_action": "아크로가 당장 따라할 수 있는 액션 1가지 (구체적으로)",
  "benchmark_products": [
    {{"name": "주목 상품명", "reason": "주목 이유 1~2문장"}}
  ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "competitor_highlight": "분석 데이터 부족",
            "codegraphy_strength": "분석 실패",
            "akro_gap": "",
            "immediate_action": "",
            "benchmark_products": [],
        }


# ── 한줄 요약 생성 ───────────────────────────────────────────────
def build_summary_line(account, imweb):
    spend     = float(account.get("spend", 0))
    r         = roas(account.get("action_values"), spend)

    if imweb and imweb["order_count"] > 0:
        return (
            f"어제 {spend:,.0f}원 광고비 집행 · "
            f"실제 주문 {imweb['order_count']:,}건 · 실제 매출 {imweb['revenue']:,}원 · "
            f"객단가 {imweb['aov']:,.0f}원 · 광고 ROAS {r}x"
        )
    else:
        act       = parse_actions(account.get("actions"))
        purchases = act["purchase"]
        cpa_val   = cpa(spend, purchases)
        rev       = purchase_value(account.get("action_values"))
        if purchases > 0:
            return (
                f"어제 {spend:,.0f}원 광고비로 {purchases:.0f}명이 구매했고, "
                f"1명당 {cpa_val:,.0f}원 들었으며, 광고비 대비 {r}배 매출 발생 (매출 {rev:,.0f}원)"
            )
        return f"어제 {spend:,.0f}원 광고비 집행 · 클릭수 {int(account.get('clicks', 0)):,}회"


# ── 카카오톡 나에게 보내기 ────────────────────────────────────────
def send_kakao(account, campaigns, imweb, competitor=None):
    if not KAKAO_ACCESS_TOKEN or not KAKAO_ACCESS_TOKEN.isascii() or KAKAO_ACCESS_TOKEN.startswith("여기에"):
        print("  [SKIP] KAKAO_ACCESS_TOKEN 미설정 — 카카오 알림 건너뜀")
        return

    spend     = float(account.get("spend", 0))
    act       = parse_actions(account.get("actions"))
    r         = roas(account.get("action_values"), spend)
    purchases = act["purchase"]
    cpa_val   = cpa(spend, purchases)
    roas_status = "양호" if r >= 3 else "주의" if r >= 1.5 else "위험"

    # 아임웹 실제 데이터
    imweb_line = ""
    if imweb and imweb["order_count"] > 0:
        imweb_line = (
            f"\n[실제 주문 (아임웹)]\n"
            f"주문수: {imweb['order_count']:,}건\n"
            f"매출: {imweb['revenue']:,}원\n"
            f"객단가: {imweb['aov']:,.0f}원\n"
        )

    top_camps = sorted(campaigns, key=lambda x: float(x.get("spend", 0)), reverse=True)[:3]
    camp_lines = ""
    for c in top_camps:
        c_spend = float(c.get("spend", 0))
        c_roas  = roas(c.get("action_values"), c_spend)
        camp_lines += f"\n  · {c.get('campaign_name','')[:20]} / {c_spend:,.0f}원 / ROAS {c_roas}x"

    competitor_line = ""
    if competitor and competitor.get("competitor_highlight"):
        competitor_line = f"\n[경쟁사] 코드그라피 이번주: {competitor['competitor_highlight']}"

    msg = (
        f"[아크로] {yesterday} 광고 브리핑\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"[메타광고]\n"
        f"지출: {spend:,.0f}원\n"
        f"ROAS: {r}x ({roas_status})\n"
        f"전환: {purchases:.0f}건 / CPA: {cpa_val:,.0f}원"
        f"{imweb_line}"
        f"\n[캠페인 TOP]{camp_lines}\n"
        f"━━━━━━━━━━━━━━━━━━"
        f"{competitor_line}\n"
        f"상세 리포트는 reports 폴더 확인"
    )

    template = json.dumps({
        "object_type": "text",
        "text": msg,
        "link": {"web_url": "", "mobile_web_url": ""},
    }, ensure_ascii=False)

    resp = requests.post(
        KAKAO_MEMO,
        headers={
            "Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=urlencode({"template_object": template}).encode("utf-8"),
        timeout=15,
    )

    if resp.status_code == 200 and resp.json().get("result_code") == 0:
        print("  [OK] 카카오톡 발송 완료")
    else:
        print(f"  [WARN] 카카오톡 발송 실패: {resp.status_code} {resp.text[:150]}")


# ── Claude AI 분석 ───────────────────────────────────────────────
def get_claude_analysis(account, campaigns, weekly, imweb):
    spend     = float(account.get("spend", 0))
    act       = parse_actions(account.get("actions"))
    r         = roas(account.get("action_values"), spend)
    purchases = act["purchase"]

    camp_list = []
    for c in campaigns:
        c_spend = float(c.get("spend", 0))
        c_act   = parse_actions(c.get("actions"))
        camp_list.append({
            "name":        c.get("campaign_name", ""),
            "spend":       c_spend,
            "roas":        roas(c.get("action_values"), c_spend),
            "purchases":   c_act["purchase"],
            "clicks":      int(c.get("clicks", 0)),
            "impressions": int(c.get("impressions", 0)),
            "ctr":         float(c.get("ctr", 0)),
        })

    weekly_list = []
    for d in weekly:
        weekly_list.append({
            "date":      d.get("date_start"),
            "spend":     float(d.get("spend", 0)),
            "purchases": parse_actions(d.get("actions"))["purchase"],
            "roas":      roas(d.get("action_values"), d.get("spend", 0)),
        })

    # 아임웹 데이터 섹션
    imweb_section = ""
    if imweb and imweb["order_count"] > 0:
        imweb_section = f"""
[아임웹 실제 주문 데이터 (어제)]
- 실제 주문수: {imweb['order_count']:,}건
- 실제 매출: {imweb['revenue']:,}원
- 객단가 (AOV): {imweb['aov']:,.0f}원
- 메타광고 기여도 참고: 메타 전환수 {purchases:.0f}건 vs 실제 주문 {imweb['order_count']:,}건
"""

    prompt = f"""당신은 이커머스 퍼포먼스 마케팅 전문가입니다. 아크로 쇼핑몰의 메타광고 및 실제 쇼핑몰 데이터를 분석해 주세요.

[어제({yesterday}) 메타광고 성과]
- 총 광고비: {spend:,.0f}원
- ROAS: {r}
- 전환(구매) 건수: {purchases:.0f}건
- CPA: {cpa(spend, purchases):,.0f}원
- 클릭수: {int(account.get('clicks', 0)):,}
- 노출수: {int(account.get('impressions', 0)):,}
- CTR: {float(account.get('ctr', 0)):.2f}%
- 장바구니: {act['add_to_cart']:.0f}건
{imweb_section}
[캠페인별 성과]
{json.dumps(camp_list, ensure_ascii=False, indent=2)}

[이번주 일별 트렌드]
{json.dumps(weekly_list, ensure_ascii=False, indent=2)}

위 데이터를 바탕으로 아래 JSON 형식으로만 응답하세요(마크다운 코드블록 제외):

{{
  "overall_assessment": "어제 성과 총평 (3~4문장, 메타광고+실제주문 수치 포함)",
  "weekly_trends": [
    {{"rank": 1, "title": "제목", "description": "2~3문장 설명"}},
    {{"rank": 2, "title": "제목", "description": "2~3문장 설명"}},
    {{"rank": 3, "title": "제목", "description": "2~3문장 설명"}}
  ],
  "action_items": [
    {{"priority": 1, "action": "실행 항목", "reason": "이유와 기대 효과"}},
    {{"priority": 2, "action": "실행 항목", "reason": "이유와 기대 효과"}},
    {{"priority": 3, "action": "실행 항목", "reason": "이유와 기대 효과"}}
  ],
  "optimization_suggestions": [
    "구체적인 최적화 제안 1",
    "구체적인 최적화 제안 2",
    "구체적인 최적화 제안 3"
  ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        last_brace = text.rfind("\n}")
        if last_brace != -1:
            text = text[:last_brace + 2]
            open_brackets = text.count("[") - text.count("]")
            open_braces   = text.count("{") - text.count("}")
            text += "]" * open_brackets + "}" * open_braces
            return json.loads(text)
        raise


# ── HTML 생성 ────────────────────────────────────────────────────
def _build_competitor_section(competitor, codegraphy_data):
    if not competitor:
        return ""

    best = (codegraphy_data or {}).get("best_sellers", [])
    new  = (codegraphy_data or {}).get("new_products", [])

    # 베스트셀러 행
    best_rows = ""
    for i, p in enumerate(best, 1):
        price = int(p.get("price", 0))
        rv    = int(p.get("review_count", 0))
        sc    = p.get("review_score") or 0
        sr    = int(p.get("sale_rate", 0))
        disc  = f' <span style="color:#f87171;font-size:11px">-{sr}%</span>' if sr else ""
        best_rows += f"""
        <tr>
          <td style="color:#94a3b8;width:28px">{i}</td>
          <td style="color:#e2e8f0;font-weight:500">{p.get('name','')}</td>
          <td>&#8361;{price:,}{disc}</td>
          <td style="color:#94a3b8">{rv:,} ({sc}점)</td>
        </tr>"""
    if not best_rows:
        best_rows = '<tr><td colspan="4" style="color:#475569;text-align:center">무신사 API 미응답 — 수동 확인 필요</td></tr>'

    # 신상품 뱃지
    new_badges = " ".join(
        f'<span style="background:#164e63;color:#67e8f9;padding:3px 10px;border-radius:20px;font-size:12px">{p["name"]} &#8361;{int(p.get("price",0)):,}</span>'
        for p in new
    ) if new else '<span style="color:#475569">없음</span>'

    # 벤치마킹 상품
    bench_items = ""
    for bp in (competitor.get("benchmark_products") or []):
        bench_items += f"""
        <div style="padding:10px 0;border-bottom:1px solid #1e293b">
          <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:3px">{bp.get('name','')}</div>
          <div style="font-size:12px;color:#94a3b8;line-height:1.5">{bp.get('reason','')}</div>
        </div>"""
    if not bench_items:
        bench_items = '<div style="color:#475569;font-size:13px">데이터 없음</div>'

    strength  = competitor.get("codegraphy_strength", "")
    gap       = competitor.get("akro_gap", "")
    action    = competitor.get("immediate_action", "")

    return f"""
<div class="container" style="padding-top:0">

  <div class="section-label" style="margin-top:8px">경쟁사 분석 — 코드그라피 (무신사)</div>

  <!-- 하이라이트 + 신상품 -->
  <div class="grid-2" style="margin-bottom:14px">
    <div class="comp-highlight">
      <div class="comp-highlight-label">이번 주 코드그라피 핵심</div>
      <div class="comp-highlight-text">{competitor.get('competitor_highlight','')}</div>
    </div>
    <div class="card" style="justify-content:flex-start">
      <div class="card-title" style="color:#22d3ee">이번 주 신상품</div>
      <div style="line-height:2">{new_badges}</div>
    </div>
  </div>

  <!-- 베스트셀러 테이블 -->
  <div class="tbl-wrap" style="margin-bottom:14px">
    <div class="tbl-head">
      <span class="comp-badge">MUSINSA</span>
      <span class="tbl-head-title" style="margin-left:8px">코드그라피 베스트셀러 Top5</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th><th>상품명</th><th>판매가</th><th>리뷰수 (평점)</th>
        </tr>
      </thead>
      <tbody class="comp-table">{best_rows}</tbody>
    </table>
  </div>

  <!-- 분석 카드 -->
  <div class="grid-2" style="margin-bottom:14px">
    <div class="card">
      <div class="card-title" style="color:#22d3ee">코드그라피가 잘 하는 것</div>
      <div style="font-size:13px;color:#cbd5e1;line-height:1.7">{strength}</div>
    </div>
    <div class="card">
      <div class="card-title" style="color:#f87171">아크로가 놓치는 포인트</div>
      <div style="font-size:13px;color:#cbd5e1;line-height:1.7">{gap}</div>
    </div>
  </div>

  <!-- 주목 상품 + 액션 -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title" style="color:#22d3ee">이번 주 주목 상품</div>
      {bench_items}
    </div>
    <div class="action-star">
      <div class="action-star-label">이번 주 벤치마킹 액션</div>
      <div class="action-star-text">{action}</div>
    </div>
  </div>

</div>"""


def build_html(account, campaigns, analysis, summary_line, imweb, competitor=None, codegraphy_data=None):
    spend       = float(account.get("spend", 0))
    act         = parse_actions(account.get("actions"))
    r           = roas(account.get("action_values"), spend)
    purchases   = act["purchase"]
    add_cart    = act["add_to_cart"]
    clicks      = int(account.get("clicks", 0))
    ctr_val     = float(account.get("ctr", 0))
    cpa_val     = cpa(spend, purchases)

    roas_color = "#10b981" if r >= 3 else "#f59e0b" if r >= 1.5 else "#ef4444"
    roas_label = "양호" if r >= 3 else "주의" if r >= 1.5 else "위험"

    # ── 실제 주문 현황 섹션 ──
    if imweb and imweb["order_count"] > 0:
        conv_gap = imweb["order_count"] - int(purchases)
        gap_note = f"메타 전환 대비 +{conv_gap:,}건 (직접 유입 등)" if conv_gap > 0 else \
                   f"메타 전환 대비 {conv_gap:,}건" if conv_gap < 0 else "메타 전환수와 일치"
        imweb_section_html = f"""
  <!-- 실제 주문 현황 -->
  <div class="section-label">실제 주문 현황 (아임웹)</div>
  <div class="kpi-grid" style="margin-bottom:28px">
    <div class="kpi-card" style="--a:#06b6d4">
      <div class="kpi-label">실제 주문수</div>
      <div class="kpi-val">{imweb['order_count']:,}<span style="font-size:15px;color:#94a3b8">건</span></div>
      <div class="kpi-sub">{gap_note}</div>
    </div>
    <div class="kpi-card" style="--a:#10b981">
      <div class="kpi-label">실제 매출</div>
      <div class="kpi-val">&#8361;{imweb['revenue']:,}</div>
      <div class="kpi-sub">아임웹 결제완료 기준</div>
    </div>
    <div class="kpi-card" style="--a:#8b5cf6">
      <div class="kpi-label">객단가 (AOV)</div>
      <div class="kpi-val">&#8361;{imweb['aov']:,.0f}</div>
      <div class="kpi-sub">매출 ÷ 주문수</div>
    </div>
    <div class="kpi-card" style="--a:#f59e0b">
      <div class="kpi-label">실제 ROAS</div>
      <div class="kpi-val" style="color:#10b981">{round(imweb['revenue']/spend,2) if spend>0 else 0}x</div>
      <div class="kpi-sub">실제매출 ÷ 광고비</div>
    </div>
  </div>"""
    else:
        imweb_section_html = ""

    # 캠페인 테이블
    camp_rows = ""
    for c in sorted(campaigns, key=lambda x: float(x.get("spend", 0)), reverse=True):
        c_spend  = float(c.get("spend", 0))
        c_act    = parse_actions(c.get("actions"))
        c_pur    = c_act["purchase"]
        c_roas   = roas(c.get("action_values"), c_spend)
        c_cpa    = cpa(c_spend, c_pur)
        c_rc     = "#10b981" if c_roas >= 3 else "#f59e0b" if c_roas >= 1.5 else "#ef4444"
        cpa_cell = f"&#8361;{c_cpa:,.0f}" if c_pur > 0 else "&#8212;"
        pur_cell = f"{c_pur:.0f}건" if c_pur > 0 else "&#8212;"
        camp_rows += f"""
        <tr>
          <td class="camp-name">{c.get('campaign_name','')}</td>
          <td>&#8361;{c_spend:,.0f}</td>
          <td style="color:{c_rc};font-weight:700">{c_roas}x</td>
          <td>{pur_cell}</td>
          <td>{cpa_cell}</td>
          <td>{int(c.get('impressions',0)):,}</td>
          <td>{float(c.get('ctr',0)):.2f}%</td>
        </tr>"""

    # 트렌드
    trend_cards = ""
    for t in analysis.get("weekly_trends", []):
        trend_cards += f"""
        <div class="trend-card">
          <div class="trend-rank">TOP {t['rank']}</div>
          <div class="trend-title">{t['title']}</div>
          <div class="trend-desc">{t['description']}</div>
        </div>"""

    # 액션
    action_items = ""
    colors = ["#ef4444", "#f59e0b", "#3b82f6"]
    for a in analysis.get("action_items", []):
        col = colors[a["priority"] - 1]
        action_items += f"""
        <div class="action-item">
          <div class="action-badge" style="background:{col}">P{a['priority']}</div>
          <div>
            <div class="action-title">{a['action']}</div>
            <div class="action-reason">{a['reason']}</div>
          </div>
        </div>"""

    # 최적화
    opt_items = ""
    for i, opt in enumerate(analysis.get("optimization_suggestions", []), 1):
        opt_items += f"""
        <li>
          <span class="opt-num">{i}</span>
          <span>{opt}</span>
        </li>"""

    overall = analysis.get("overall_assessment", "")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>아크로 쇼핑몰 Daily 브리핑 &mdash; {yesterday}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}

/* ── Header ── */
.header{{background:linear-gradient(135deg,#1e3a8a,#2563eb);padding:28px 40px 0}}
.header-inner{{max-width:1200px;margin:0 auto;display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:24px}}
.brand{{font-size:11px;color:#93c5fd;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px}}
.title{{font-size:26px;font-weight:700;color:#fff}}
.subtitle{{font-size:13px;color:#bfdbfe;margin-top:4px}}
.gen-time{{font-size:11px;color:#93c5fd;text-align:right;line-height:1.6}}

/* ── 한줄 요약 배너 ── */
.summary-bar{{background:rgba(0,0,0,.25);border-top:1px solid rgba(255,255,255,.1);padding:12px 40px}}
.summary-bar-inner{{max-width:1200px;margin:0 auto;font-size:14px;color:#e0f2fe;font-weight:500;line-height:1.5}}
.summary-bar-label{{display:inline-block;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#93c5fd;margin-right:10px;font-weight:700}}

/* ── Layout ── */
.container{{max-width:1200px;margin:0 auto;padding:28px 24px}}
.section-label{{font-size:10px;color:#475569;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:14px}}

/* ── KPI ── */
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px}}
.kpi-card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;position:relative;overflow:hidden}}
.kpi-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--a,#3b82f6)}}
.kpi-label{{font-size:11px;color:#94a3b8;margin-bottom:8px}}
.kpi-val{{font-size:26px;font-weight:700;color:#f1f5f9;line-height:1}}
.kpi-sub{{font-size:11px;color:#64748b;margin-top:5px}}
.kpi-badge{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:20px;margin-top:5px;font-weight:700}}

/* ── Table ── */
.tbl-wrap{{background:#1e293b;border:1px solid #334155;border-radius:12px;overflow:hidden;margin-bottom:28px}}
.tbl-head{{padding:14px 18px;border-bottom:1px solid #334155}}
.tbl-head-title{{font-size:13px;font-weight:600;color:#f1f5f9}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:#0f172a}}
th{{text-align:left;padding:10px 14px;font-size:10px;color:#64748b;font-weight:700;letter-spacing:1px;text-transform:uppercase}}
td{{padding:11px 14px;font-size:13px;color:#cbd5e1;border-top:1px solid #1e293b}}
tr:hover td{{background:#263448}}
.camp-name{{color:#e2e8f0;font-weight:500;max-width:300px}}

/* ── Analysis ── */
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:28px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px}}
.card.full{{grid-column:1/-1}}
.card-title{{font-size:12px;font-weight:700;color:#93c5fd;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.card-title::before{{content:'';width:3px;height:14px;background:#3b82f6;border-radius:2px;display:inline-block}}
.overall{{font-size:14px;line-height:1.75;color:#cbd5e1}}

/* ── Trends ── */
.trends-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.trend-card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:14px}}
.trend-rank{{font-size:9px;color:#3b82f6;font-weight:800;letter-spacing:1px;margin-bottom:5px}}
.trend-title{{font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:6px}}
.trend-desc{{font-size:12px;color:#94a3b8;line-height:1.55}}

/* ── Actions ── */
.action-item{{display:flex;gap:12px;align-items:flex-start;padding:11px 0;border-bottom:1px solid #0f172a}}
.action-item:last-child{{border-bottom:none}}
.action-badge{{width:30px;height:30px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#fff;flex-shrink:0}}
.action-title{{font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:3px}}
.action-reason{{font-size:12px;color:#94a3b8;line-height:1.5}}

/* ── Opt ── */
.opt-list{{list-style:none}}
.opt-list li{{display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid #0f172a;font-size:13px;color:#cbd5e1;line-height:1.55}}
.opt-list li:last-child{{border-bottom:none}}
.opt-num{{width:22px;height:22px;border-radius:50%;background:#1d4ed8;color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px}}

/* ── Competitor ── */
.comp-badge{{display:inline-block;background:#0e7490;color:#e0f2fe;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:1px;margin-bottom:10px}}
.comp-table td{{font-size:13px}}
.comp-highlight{{background:#0f2937;border:1px solid #0e7490;border-radius:10px;padding:16px 20px;margin-bottom:14px}}
.comp-highlight-label{{font-size:10px;color:#22d3ee;letter-spacing:1px;font-weight:700;margin-bottom:6px}}
.comp-highlight-text{{font-size:15px;font-weight:600;color:#e0f2fe}}
.action-star{{background:linear-gradient(135deg,#1d4ed8,#0e7490);border-radius:10px;padding:18px 20px}}
.action-star-label{{font-size:10px;color:#bae6fd;letter-spacing:1px;font-weight:700;margin-bottom:8px}}
.action-star-text{{font-size:14px;font-weight:600;color:#fff;line-height:1.6}}

/* ── Footer ── */
.footer{{text-align:center;padding:20px;font-size:11px;color:#475569;border-top:1px solid #1e293b}}

@media(max-width:768px){{
  .kpi-grid{{grid-template-columns:repeat(2,1fr)}}
  .grid-2{{grid-template-columns:1fr}}
  .trends-grid{{grid-template-columns:1fr}}
  .header-inner{{flex-direction:column;gap:12px}}
  .summary-bar{{padding:12px 20px}}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div>
      <div class="brand">AKRO SHOPPING MALL</div>
      <div class="title">Daily 마케팅 브리핑</div>
      <div class="subtitle">기준일: {yesterday} &nbsp;&middot;&nbsp; 메타광고 + 아임웹 + Claude AI 분석</div>
    </div>
    <div class="gen-time">
      생성: {now.strftime('%Y-%m-%d %H:%M')}<br>
      Powered by Claude AI
    </div>
  </div>
  <div class="summary-bar">
    <div class="summary-bar-inner">
      <span class="summary-bar-label">요약</span>{summary_line}
    </div>
  </div>
</div>

<div class="container">

  {imweb_section_html}

  <!-- 메타광고 KPI -->
  <div class="section-label">메타광고 핵심 지표</div>
  <div class="kpi-grid">
    <div class="kpi-card" style="--a:#3b82f6">
      <div class="kpi-label">총 광고비 지출</div>
      <div class="kpi-val">&#8361;{spend:,.0f}</div>
      <div class="kpi-sub">어제 기준</div>
    </div>
    <div class="kpi-card" style="--a:{roas_color}">
      <div class="kpi-label">광고 ROAS</div>
      <div class="kpi-val" style="color:{roas_color}">{r}x</div>
      <span class="kpi-badge" style="background:{roas_color}22;color:{roas_color}">{roas_label}</span>
    </div>
    <div class="kpi-card" style="--a:#8b5cf6">
      <div class="kpi-label">메타 전환수</div>
      <div class="kpi-val">{purchases:.0f}<span style="font-size:15px;color:#94a3b8">건</span></div>
      <div class="kpi-sub">장바구니 추가 {add_cart:.0f}건</div>
    </div>
    <div class="kpi-card" style="--a:#f59e0b">
      <div class="kpi-label">전환당 비용 (CPA)</div>
      <div class="kpi-val">&#8361;{cpa_val:,.0f}</div>
      <div class="kpi-sub">CTR {ctr_val:.2f}% &nbsp;&middot;&nbsp; 클릭 {clicks:,}</div>
    </div>
  </div>

  <!-- 캠페인 테이블 -->
  <div class="section-label">캠페인별 성과</div>
  <div class="tbl-wrap">
    <div class="tbl-head"><span class="tbl-head-title">어제 활동한 캠페인</span></div>
    <table>
      <thead>
        <tr>
          <th>캠페인명</th><th>지출</th><th>ROAS</th>
          <th>구매수</th><th>CPA</th><th>노출수</th><th>CTR</th>
        </tr>
      </thead>
      <tbody>{camp_rows}</tbody>
    </table>
  </div>

  <!-- AI 분석 -->
  <div class="section-label">Claude AI 분석</div>
  <div class="grid-2">

    <div class="card full">
      <div class="card-title">어제 성과 총평</div>
      <div class="overall">{overall}</div>
    </div>

    <div class="card full">
      <div class="card-title">이번주 주목할 트렌드 Top 3</div>
      <div class="trends-grid">{trend_cards}</div>
    </div>

    <div class="card">
      <div class="card-title">이번주 실행 액션 3가지</div>
      {action_items}
    </div>

    <div class="card">
      <div class="card-title">메타광고 최적화 제안</div>
      <ul class="opt-list">{opt_items}</ul>
    </div>

  </div>
</div>

{_build_competitor_section(competitor, codegraphy_data)}

<div class="footer">
  아크로 쇼핑몰 Daily 브리핑 &nbsp;&middot;&nbsp; {yesterday} 기준 &nbsp;&middot;&nbsp; 메타광고 + 아임웹 + Claude AI (claude-sonnet-4-6)
</div>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 50)
    print("  아크로 쇼핑몰 Daily 브리핑")
    print(f"  기준일: {yesterday}")
    print("=" * 50)

    print("\n[1/5] 메타광고 데이터 수집 중...")
    try:
        account   = fetch_account_insights()
        campaigns = fetch_campaign_insights()
        weekly    = fetch_weekly_insights()
        spend = float(account.get("spend", 0))
        print(f"  [OK] 계정 지출: {spend:,.0f}원")
        print(f"  [OK] 활동 캠페인: {len(campaigns)}개")
        print(f"  [OK] 이번주 일별 데이터: {len(weekly)}일")
    except Exception as e:
        print(f"  [ERR] Meta API 오류: {e}")
        sys.exit(1)

    print("\n[2/5] 아임웹 실제 주문 수집 중...")
    imweb = None
    if IMWEB_API_KEY and IMWEB_SECRET_KEY:
        try:
            token  = get_imweb_token()
            orders = fetch_imweb_orders(token)
            imweb  = parse_imweb_stats(orders)
            print(f"  [OK] 주문수: {imweb['order_count']:,}건 / 매출: {imweb['revenue']:,}원 / 객단가: {imweb['aov']:,.0f}원")
        except Exception as e:
            print(f"  [WARN] 아임웹 API 오류 (건너뜀): {e}")
    else:
        print("  [SKIP] IMWEB_API_KEY / IMWEB_SECRET_KEY 미설정")

    print("\n[3/5] Claude AI 분석 중...")
    try:
        analysis = get_claude_analysis(account, campaigns, weekly, imweb)
        print("  [OK] 분석 완료")
    except Exception as e:
        print(f"  [ERR] Claude API 오류: {e}")
        sys.exit(1)

    print("\n[3.5/5] 코드그라피 경쟁사 데이터 수집 중...")
    codegraphy_data = fetch_codegraphy()

    print("\n[3.7/5] 경쟁사 AI 벤치마킹 분석 중...")
    competitor = None
    try:
        competitor = get_competitor_analysis(codegraphy_data, account, imweb)
        print(f"  [OK] 경쟁사 분석 완료: {competitor.get('competitor_highlight', '')}")
    except Exception as e:
        print(f"  [WARN] 경쟁사 분석 실패 (건너뜀): {e}")

    print("\n[4/5] HTML 리포트 생성 중...")
    summary_line = build_summary_line(account, imweb)
    print(f"  >> {summary_line}")
    html = build_html(account, campaigns, analysis, summary_line, imweb, competitor, codegraphy_data)

    report_dir  = Path(__file__).parent / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"briefing_{yesterday}.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"  [OK] 저장: {report_path}")

    try:
        import subprocess
        subprocess.Popen(f'start chrome "{report_path.as_uri()}"', shell=True)
    except Exception:
        webbrowser.open(report_path.as_uri())

    print("\n[5/5] 카카오톡 알림 발송 중...")
    send_kakao(account, campaigns, imweb, competitor)

    # ── Jarvis SQLite 저장 ─────────────────────────────────────────
    if _JARVIS_OK:
        print("\n[Jarvis] SQLite에 데이터 저장 중...")
        try:
            _jarvis_db.init_db()
            _helpers = {
                "roas": roas,
                "parse_actions": parse_actions,
                "cpa": cpa,
                "purchase_value": purchase_value,
            }
            _jarvis_db.save_daily_stats(yesterday, account, imweb, _helpers)
            _jarvis_db.save_campaigns(yesterday, campaigns, _helpers)
            if codegraphy_data:
                _jarvis_db.save_competitor(yesterday, codegraphy_data, competitor)
            _jarvis_db.save_briefing_analysis(yesterday, analysis)
            print("  [OK] Jarvis DB 저장 완료 → jarvis/jarvis.db")
        except Exception as _e:
            print(f"  [WARN] Jarvis DB 저장 실패 (브리핑은 정상): {_e}")

    print("\n[완료] 브리핑 생성! 브라우저에서 확인하세요.\n")


if __name__ == "__main__":
    main()
