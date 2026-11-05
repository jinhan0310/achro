#!/usr/bin/env python3
"""
아임웹 Open API(OAuth2) 토큰 발급 — 이 컴퓨터용 토큰을 .env 에 저장한다.
실행: python imweb_token_issue.py            (같은 폴더의 .env 사용)
      python imweb_token_issue.py --env 경로  (다른 .env 지정)
필요한 .env 값: IMWEB_GROUND_CLIENT_ID, IMWEB_GROUND_CLIENT_SECRET, IMWEB_SITE_CODE
토큰 값은 화면에 출력하지 않는다.
"""
import os
import sys
import urllib.parse
from pathlib import Path

try:
    import requests
    from dotenv import load_dotenv, set_key
except ImportError:
    print("[ERR] 패키지가 없습니다. 먼저 '다른PC설치.bat' 을 실행하세요.")
    sys.exit(1)

ENV = Path(sys.argv[sys.argv.index("--env") + 1]) if "--env" in sys.argv else Path(__file__).parent / ".env"
if not ENV.exists():
    print(f"[ERR] {ENV} 파일이 없습니다. .env.example 을 .env 로 복사해 값을 채우세요.")
    sys.exit(1)
load_dotenv(ENV)

CID = os.getenv("IMWEB_GROUND_CLIENT_ID", "")
SEC = os.getenv("IMWEB_GROUND_CLIENT_SECRET", "")
SITE = os.getenv("IMWEB_SITE_CODE", "")
if not (CID and SEC and SITE):
    print("[ERR] .env 에 IMWEB_GROUND_CLIENT_ID / IMWEB_GROUND_CLIENT_SECRET / IMWEB_SITE_CODE 를 채워주세요.")
    sys.exit(1)

REDIRECT = "http://127.0.0.1:9999/callback"
SCOPE = "site-info:write order:read"   # 아임웹이 인가 코드 발급 시 site-info:write 를 필수로 요구함 (코드는 조회만 사용)

auth_url = (
    "https://openapi.imweb.me/oauth2/authorize?responseType=code"
    f"&clientId={CID}&redirectUri={urllib.parse.quote(REDIRECT, safe='')}"
    f"&scope={urllib.parse.quote(SCOPE, safe='')}&state=achro&siteCode={SITE}"
)
r = requests.get(auth_url, allow_redirects=False, timeout=15)
q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers.get("Location", "")).query)
if "code" not in q:
    print("[FAIL] 인가 코드를 받지 못했습니다:", (q.get("message") or ["알 수 없음"])[0])
    sys.exit(1)

t = requests.post(
    "https://openapi.imweb.me/oauth2/token",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={"clientId": CID, "clientSecret": SEC, "code": q["code"][0],
          "grantType": "authorization_code", "redirectUri": REDIRECT},
    timeout=15,
)
j = t.json()
d = j.get("data", j)
at, rt = d.get("accessToken"), d.get("refreshToken")
if not at:
    print("[FAIL] 토큰 발급 실패 (HTTP %s)" % t.status_code)
    sys.exit(1)

set_key(str(ENV), "IMWEB_GROUND_ACCESS_TOKEN", at)
set_key(str(ENV), "IMWEB_GROUND_REFRESH_TOKEN", rt or "")
print("[OK] 토큰을 %s 에 저장했습니다. (access %d자 / refresh %d자)" % (ENV.name, len(at), len(rt or "")))
