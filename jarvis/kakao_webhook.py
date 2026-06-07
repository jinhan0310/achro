"""
카카오 챗봇 webhook 처리 모듈
카카오 오픈빌더 스킬 서버 형식 지원
"""


def classify_question(text: str) -> str:
    """키워드 기반 질문 유형 분류"""
    t = text

    imweb_keywords = ["매출", "주문", "판매", "결제", "객단가", "아임웹", "AOV", "aov"]
    meta_keywords = [
        "광고", "ROAS", "roas", "CPA", "cpa", "메타", "캠페인",
        "클릭", "노출", "CTR", "ctr", "전환", "광고비",
    ]
    competitor_keywords = ["경쟁사", "코드그라피", "codegraphy", "무신사", "경쟁", "벤치마킹"]
    briefing_keywords = ["브리핑", "오늘", "어제", "요약", "전체", "현황", "리포트", "보고"]

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
