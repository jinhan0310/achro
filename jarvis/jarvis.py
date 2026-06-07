#!/usr/bin/env python3
"""
자비스 - 아크로 쇼핑몰 AI 어시스턴트
카카오 오픈빌더 스킬 서버 (포트 5000)

실행: python jarvis/jarvis.py
테스트: http://localhost:5000/test?q=어제매출
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
except ImportError:
    print("[ERR] flask 또는 flask-cors가 없습니다. pip install flask flask-cors 실행 후 재시도하세요.")
    sys.exit(1)

from dotenv import load_dotenv
import db
import kakao_webhook
import ai_answer

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ── 허용 user_id 목록 (.env의 KAKAO_OWNER_ID, 쉼표 구분) ──────────
_raw = os.getenv("KAKAO_OWNER_ID", "").strip()
ALLOWED_IDS: set[str] = {uid.strip() for uid in _raw.split(",") if uid.strip()}
SETUP_MODE = len(ALLOWED_IDS) == 0   # KAKAO_OWNER_ID 미설정 시 ID 안내 모드

app = Flask(__name__)
app.json.ensure_ascii = False
CORS(app, resources={r"/chat": {"origins": "*"}, r"/": {"origins": "*"}})
db.init_db()


@app.after_request
def skip_ngrok_warning(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


def _is_allowed(user_id: str) -> bool:
    return user_id in ALLOWED_IDS


@app.route("/", methods=["GET"])
def health():
    stats = db.get_latest_stats(1)
    last_date = stats[0]["date"] if stats else "없음"
    return jsonify({
        "status": "ok",
        "service": "자비스 - 아크로 AI 어시스턴트",
        "last_briefing_date": last_date,
        "security": "setup_mode" if SETUP_MODE else f"active ({len(ALLOWED_IDS)}명 허용)",
        "endpoints": {
            "webhook": "POST /webhook  (카카오 오픈빌더 연결)",
            "test": "GET /test?q=질문내용",
        },
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    """카카오 오픈빌더 스킬 서버 엔드포인트"""
    try:
        body = request.get_json(force=True, silent=True) or {}
        utterance, user_id = kakao_webhook.parse_kakao_request(body)

        # ── 보안: user_id 검증 ──────────────────────────────────────
        if SETUP_MODE:
            # KAKAO_OWNER_ID 미설정 → 카카오 채팅으로 본인 ID 안내
            print(f"[SETUP] 요청 user_id: {user_id}")
            return jsonify(kakao_webhook.build_kakao_response(
                f"[자비스 설정 모드]\n"
                f"아래 ID를 .env에 추가하세요:\n\n"
                f"KAKAO_OWNER_ID={user_id}\n\n"
                f"저장 후 서버를 재시작하면 보안이 활성화됩니다."
            ))

        if not _is_allowed(user_id):
            print(f"[BLOCKED] 차단된 user_id: {user_id}")
            return jsonify(kakao_webhook.build_kakao_response("서비스 준비중입니다."))

        # ── 정상 처리 ───────────────────────────────────────────────
        print(f"[OK] user_id={user_id} / 질문={utterance}")

        if not utterance:
            return jsonify(kakao_webhook.build_kakao_response(
                "질문을 입력해주세요.\n예) 어제 매출 알려줘"
            ))

        question_type = kakao_webhook.classify_question(utterance)
        answer = ai_answer.get_answer(utterance, question_type, db)
        return jsonify(kakao_webhook.build_kakao_response(answer))

    except Exception as e:
        print(f"[ERR] webhook 오류: {e}")
        return jsonify(kakao_webhook.build_kakao_response(
            "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        ))


@app.route("/chat", methods=["POST"])
def chat():
    """index.html 자비스 탭 전용 엔드포인트 (보안 검증 없음 — 로컬 전용)"""
    try:
        body = request.get_json(force=True, silent=True) or {}
        message = body.get("message", "").strip()
        if not message:
            return jsonify({"answer": "질문을 입력해주세요."})
        question_type = kakao_webhook.classify_question(message)
        answer = ai_answer.get_answer(message, question_type, db)
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"[ERR] chat 오류: {e}")
        return jsonify({"answer": "오류가 발생했습니다. 잠시 후 다시 시도해주세요."})


@app.route("/test", methods=["GET"])
def test():
    """로컬 테스트용 엔드포인트 (보안 검증 없음)"""
    question = request.args.get("q", "오늘 브리핑 요약해줘")
    question_type = kakao_webhook.classify_question(question)
    answer = ai_answer.get_answer(question, question_type, db)
    return jsonify({
        "question": question,
        "type": question_type,
        "answer": answer,
    })


if __name__ == "__main__":
    port = int(os.getenv("JARVIS_PORT", 5000))

    print("=" * 50)
    print("  자비스 - 아크로 AI 어시스턴트")
    print("=" * 50)
    print(f"  서버: http://localhost:{port}")
    print(f"  카카오 webhook: POST http://localhost:{port}/webhook")
    print(f"  테스트: http://localhost:{port}/test?q=오늘매출")
    print(f"  DB 위치: {db.DB_PATH}")
    if SETUP_MODE:
        print("  [보안] SETUP MODE - 카카오에서 아무 메시지 보내면 user_id 안내")
    else:
        print(f"  [보안] ACTIVE - 허용된 user_id {len(ALLOWED_IDS)}명")
    print("=" * 50)

    app.run(host="0.0.0.0", port=port, debug=False)
