"""
Claude API 기반 질문 답변 생성 모듈
DB에서 문맥 데이터를 읽어 간결한 카카오톡용 답변 생성
"""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
_API_KEY = os.getenv("ANTHROPIC_API_KEY")


def _client():
    return anthropic.Anthropic(api_key=_API_KEY)


def _ask(prompt: str, max_tokens: int = 350) -> str:
    msg = _client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── 질문 유형별 답변 함수 ──────────────────────────────────────────

def answer_imweb(question: str, db) -> str:
    stats = db.get_latest_stats(7)
    if not stats:
        return "아직 수집된 아임웹 데이터가 없습니다.\nbriefing.py를 먼저 실행해주세요."

    latest = stats[0]

    # 최신 데이터로 빠른 직접 답변
    if latest["imweb_revenue"] > 0 and any(k in question for k in ["어제", "오늘", "최근", "매출", "주문"]):
        return (
            f"📦 {latest['date']} 주문/매출\n"
            f"━━━━━━━━━━━━\n"
            f"실제 주문: {latest['imweb_order_count']:,}건\n"
            f"실제 매출: {latest['imweb_revenue']:,}원\n"
            f"객단가: {latest['imweb_aov']:,.0f}원\n"
            f"실제 ROAS: {latest['imweb_roas']}x"
        )

    days = len(stats)
    period_label = f"{stats[0]['date']} 하루" if days == 1 else f"{stats[-1]['date']} ~ {stats[0]['date']} ({days}일간)"

    rows = "\n".join(
        f"{s['date']}: 주문 {s['imweb_order_count']}건 / 매출 {s['imweb_revenue']:,}원 / 객단가 {s['imweb_aov']:,.0f}원"
        for s in stats
        if s["imweb_revenue"] > 0
    )
    if not rows:
        return "수집된 아임웹 주문 데이터가 없습니다."

    return _ask(
        f"아크로 쇼핑몰 아임웹 주문/매출 데이터 ({period_label}):\n{rows}\n\n"
        f"질문: {question}\n\n"
        f"중요: 데이터가 {days}일치만 있으므로 '{period_label}' 기준으로만 답변하세요. "
        f"'7일' 같은 기간 표현은 절대 쓰지 마세요.\n"
        f"카카오톡용으로 50단어 이내, 핵심만 답변."
    )


def answer_meta(question: str, db) -> str:
    stats = db.get_latest_stats(7)
    campaigns = db.get_latest_campaigns()

    if not stats:
        return "아직 수집된 광고 데이터가 없습니다.\nbriefing.py를 먼저 실행해주세요."

    latest = stats[0]

    # ROAS나 CPA 단순 질문 → 빠른 직접 답변
    if any(k in question for k in ["ROAS", "roas"]) and "캠페인" not in question:
        status = "양호" if latest["meta_roas"] >= 3 else "주의" if latest["meta_roas"] >= 1.5 else "위험"
        return (
            f"📊 {latest['date']} 광고 ROAS\n"
            f"━━━━━━━━━━━━\n"
            f"ROAS: {latest['meta_roas']}x ({status})\n"
            f"광고비: {int(latest['spend']):,}원\n"
            f"전환: {int(latest['meta_purchases']):,}건\n"
            f"CPA: {int(latest['meta_cpa']):,}원"
        )

    # 실제 보유 날짜 수로 레이블 결정
    days = len(stats)
    if days == 1:
        period_label = f"{stats[0]['date']} 하루"
    else:
        period_label = f"{stats[-1]['date']} ~ {stats[0]['date']} ({days}일간)"

    stats_text = "\n".join(
        f"{s['date']}: 광고비 {int(s['spend']):,}원 / ROAS {s['meta_roas']}x / "
        f"전환 {int(s['meta_purchases']):,}건 / CPA {int(s['meta_cpa']):,}원"
        for s in stats
    )
    camp_text = "\n".join(
        f"- {c['campaign_name']}: {c['spend']:,}원 / ROAS {c['roas']}x / 전환 {c['purchases']:.0f}건"
        for c in campaigns[:5]
    ) if campaigns else "캠페인 데이터 없음"

    return _ask(
        f"아크로 메타광고 데이터 ({period_label}):\n{stats_text}\n\n"
        f"[캠페인별]\n{camp_text}\n\n"
        f"질문: {question}\n\n"
        f"중요: 데이터가 {days}일치만 있으므로 '{period_label}' 기준으로만 답변하세요. "
        f"'7일', '최근 7일' 같은 표현은 절대 쓰지 마세요.\n"
        f"카카오톡용으로 60단어 이내, 핵심만 답변."
    )


def answer_competitor(question: str, db) -> str:
    data = db.get_competitor_data()

    if not data["date"]:
        return "아직 수집된 경쟁사 데이터가 없습니다.\nbriefing.py를 먼저 실행해주세요."

    best_text = "\n".join(
        f"{i+1}. {p['name']} / {p['price']:,}원 / 리뷰 {p['review_count']:,}개 ({p['review_score']}점)"
        for i, p in enumerate(data["best_sellers"][:5])
    ) or "데이터 없음"

    ana = data["analysis"]
    ana_text = ""
    if ana:
        ana_text = (
            f"핵심: {ana.get('competitor_highlight', '')}\n"
            f"강점: {ana.get('codegraphy_strength', '')}\n"
            f"아크로 기회: {ana.get('akro_gap', '')}\n"
            f"추천 액션: {ana.get('immediate_action', '')}"
        )

    return _ask(
        f"코드그라피(경쟁사) 데이터 ({data['date']} 기준):\n"
        f"[무신사 베스트셀러]\n{best_text}\n\n"
        f"[AI 분석]\n{ana_text}\n\n"
        f"질문: {question}\n\n카카오톡용으로 60단어 이내, 핵심만 답변."
    )


def answer_briefing(question: str, db) -> str:
    stats = db.get_latest_stats(1)
    analysis = db.get_briefing_analysis()

    if not stats:
        return "아직 수집된 브리핑 데이터가 없습니다.\nbriefing.py를 먼저 실행해주세요."

    s = stats[0]
    roas_status = "양호" if s["meta_roas"] >= 3 else "주의" if s["meta_roas"] >= 1.5 else "위험"
    lines = [
        f"📊 {s['date']} 아크로 브리핑",
        "━━━━━━━━━━━━━━",
    ]

    if s["imweb_revenue"] > 0:
        lines += [
            "[실제 주문]",
            f"주문 {s['imweb_order_count']:,}건 / 매출 {s['imweb_revenue']:,}원",
            f"객단가 {s['imweb_aov']:,.0f}원",
            "",
        ]

    lines += [
        "[메타광고]",
        f"광고비 {int(s['spend']):,}원 / ROAS {s['meta_roas']}x ({roas_status})",
        f"전환 {int(s['meta_purchases']):,}건 / CPA {int(s['meta_cpa']):,}원",
    ]

    if analysis and analysis.get("overall_assessment"):
        lines += ["", "[AI 총평]", analysis["overall_assessment"]]

    return "\n".join(lines)


def answer_products(question: str, db) -> str:
    if not db.has_product_sales_data():
        return "아직 상품 판매 데이터가 없습니다.\nanalyze_sales.py를 먼저 실행해주세요."

    # 질문에서 연도/시즌 파싱
    import re
    year  = None
    season = None
    year_m = re.search(r"(20\d{2})년?", question)
    if year_m:
        year = int(year_m.group(1))
    for kw, s in [("봄","봄"),("여름","여름"),("가을","가을"),("겨울","겨울"),
                  ("spring","summer"),("summer","summer"),("fall","가을"),("winter","겨울")]:
        if kw in question:
            season = s
            break

    top = db.get_top_products(limit=10, year=year, season=season)
    years = db.get_product_years()

    if not top:
        return "해당 조건의 판매 데이터가 없습니다."

    label = ""
    if year and season:
        label = f"{year}년 {season} "
    elif year:
        label = f"{year}년 "
    elif season:
        label = f"{season} "

    lines = [
        f"🏆 아크로 {label}인기 상품 TOP {len(top)}",
        f"(데이터: {min(years)}~{max(years)}년)",
        "━━━━━━━━━━━━━━",
    ]
    for i, p in enumerate(top, 1):
        name = p["product"]
        # 상품명 줄이기: 60자 초과 시 자름
        short = name[:55] + "..." if len(name) > 55 else name
        lines.append(f"{i}. {short}")
        lines.append(f"   {p['total_qty']:,}개 판매 / {int(p['total_revenue']):,}원")

    return "\n".join(lines)


def answer_stock(question: str, db) -> str:
    return (
        "🗂 재고 현황은 아크로 시스템 상단 [재고현황] 탭에서 확인하세요.\n\n"
        "자비스는 매출·광고·경쟁사·브리핑 데이터를 답변합니다.\n"
        "예) '어제 매출', '광고 ROAS', '오늘 브리핑'"
    )


def answer_free(question: str, db) -> str:
    stats = db.get_latest_stats(3)

    context = ""
    if stats:
        s = stats[0]
        context = (
            f"\n[최근 아크로 데이터 - {s['date']}]\n"
            f"광고비: {int(s['spend']):,}원 / ROAS: {s['meta_roas']}x\n"
            f"실제 주문: {s['imweb_order_count']:,}건 / 매출: {s['imweb_revenue']:,}원\n"
        )

    return _ask(
        f"당신은 아크로 쇼핑몰의 AI 어시스턴트 자비스입니다.{context}\n"
        f"사용자 질문: {question}\n\n"
        f"친절하고 간결하게 카카오톡용으로 60단어 이내 답변."
    )


# ── 라우터 ────────────────────────────────────────────────────────

def get_answer(question: str, question_type: str, db) -> str:
    try:
        dispatch = {
            "stock":    answer_stock,
            "products": answer_products,
            "imweb":    answer_imweb,
            "meta":     answer_meta,
            "competitor": answer_competitor,
            "briefing": answer_briefing,
        }
        fn = dispatch.get(question_type, answer_free)
        return fn(question, db)
    except anthropic.APIConnectionError:
        return "Claude API 연결 실패. 네트워크 상태를 확인해주세요."
    except anthropic.AuthenticationError:
        return "ANTHROPIC_API_KEY가 올바르지 않습니다. .env 파일을 확인해주세요."
    except Exception as e:
        return f"답변 생성 오류: {str(e)[:80]}"
