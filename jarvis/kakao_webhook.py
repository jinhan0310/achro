"""
카카오 챗봇 webhook 처리 모듈
카카오 오픈빌더 스킬 서버 형식 지원
"""


def classify_question(text: str) -> str:
    """키워드 기반 질문 유형 분류"""
    t = text

    stock_keywords = ["재고", "입고", "출고", "재입고", "상품코드", "창고"]
    products_keywords = [
        "베스트셀러", "잘 팔리는", "잘팔리는", "인기 아이템", "인기아이템",
        "인기 상품", "인기상품", "많이 팔린", "많이팔린", "TOP 상품", "탑 상품",
        "시즌 인기", "시즌별", "연도별", "판매 순위", "판매순위",
        "어떤 상품", "어떤상품", "뭐가 잘", "뭐가잘",
    ]
    delivery_keywords = [
        "배송대기", "배송 대기", "출고대기", "출고 대기", "발송대기", "발송 대기",
        "아직 안 보낸", "안보낸", "미발송",
    ]
    imweb_keywords = [
        "매출", "주문", "판매", "결제", "객단가", "아임웹", "AOV", "aov",
        "몇건", "평균 주문", "평균주문",
    ]
    meta_keywords = [
        "광고", "ROAS", "roas", "로아스", "CPA", "cpa", "메타", "캠페인",
        "클릭", "노출", "CTR", "ctr", "전환", "광고비",
        "알마만", "ASCO", "asco",
    ]
    competitor_keywords = [
        "경쟁사", "코드그라피", "codegraphy", "무신사", "경쟁업체", "경쟁",
        "벤치마킹", "트렌드",
    ]
    briefing_keywords = ["브리핑", "요약", "전체", "리포트", "보고", "현황"]

    if any(k in t for k in stock_keywords):
        return "stock"
    if any(k in t for k in delivery_keywords):
        return "delivery"
    if any(k in t for k in products_keywords):
        return "products"
    if any(k in t for k in imweb_keywords):
        return "imweb"
    if any(k in t for k in meta_keywords):
        return "meta"
    if any(k in t for k in competitor_keywords):
        return "competitor"
    if any(k in t for k in briefing_keywords):
        return "briefing"
    return "ai"


def build_kakao_response(text: str) -> dict:
    """카카오 오픈빌더 스킬 응답 형식 생성"""
    # 카카오 텍스트 최대 1000자 제한
    if len(text) > 950:
        text = text[:947] + "..."

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": text
                    }
                }
            ]
        },
    }


def parse_kakao_request(body: dict) -> tuple[str, str]:
    """카카오 webhook 요청에서 발화문과 유저 ID 추출"""
    try:
        utterance = body.get("userRequest", {}).get("utterance", "").strip()
        user_id = (
            body.get("userRequest", {})
            .get("user", {})
            .get("id", "unknown")
        )
        return utterance, user_id
    except Exception:
        return "", "unknown"
