#!/usr/bin/env python3
"""
아임웹 OMS API로 주문 + 제품명 + 옵션 수집
실행: python fetch_orders_oms.py
"""

import os, sys, json, time, re
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("[ERR] pip install requests"); sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERR] pip install python-dotenv"); sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERR] pip install playwright && playwright install chromium"); sys.exit(1)

load_dotenv()

# 로그인은 보이는 브라우저 창에서 사용자가 직접 한다 (비밀번호를 코드/.env 로 자동 입력하지 않음)
_TOKEN_CACHE   = Path(__file__).parent / ".oms_token.json"


def _load_cached_token() -> str:
    """캐시된 OMS 토큰 반환 (만료 시 None)"""
    try:
        if _TOKEN_CACHE.exists():
            data = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
            if data.get("expires", 0) > time.time():
                return data["token"]
    except Exception:
        pass
    return None


def _save_token(token: str):
    """OMS 토큰 파일에 캐시 (30일 유효)"""
    try:
        _TOKEN_CACHE.write_text(
            json.dumps({"token": token, "expires": time.time() + 86400 * 30}),
            encoding="utf-8"
        )
    except Exception:
        pass
OMS_API_BASE   = "https://api.oms.imweb.me/admin/v1"
OMS_ORDER_URL  = "https://achro.imweb.me/admin/shopping/order-v1?subPath=L29yZGVycy90YWIvdDIwMjQwNzA0NTQ0NGRkZTlhNWVkMS8x"

# 탭 코드 (아임웹 OMS 관리자 탭)
TAB_ALL             = "t2024070464f0691fbfdc9"
TAB_READY           = "t202407041ccb06b9550b1"   # 상품준비중 (OSS01)
TAB_DELIVERY_WAIT   = "t202407045444dde9a5ed1"   # 배송대기 (OSS02)
TAB_RETURN          = "t20240704092aa03216ae3"    # 반품접수 (OSS08)
TAB_SHIPPING        = "t20240704d30a853b0c218"    # 배송중 (OSS03)
TAB_DONE            = "t202407043d72764704e3a"    # 배송완료 (OSS04)


OMS_PROFILE    = Path(__file__).parent / ".oms_profile"   # 로그인 세션 보관 폴더 (git 제외, 쿠키 포함)


def _capture_oms_token(headless: bool, manual_login: bool):
    """저장된 로그인 세션으로 OMS 페이지를 열어 Bearer 토큰을 잡는다.
    manual_login=True 이면 보이는 창에서 사용자가 직접 로그인(추가 인증 포함)할 때까지 기다린다.
    반환: (token, diag, final_url)"""
    token_holder, diag = {}, {}

    def on_request(request):
        auth = request.headers.get("authorization", "")
        try:
            host = request.url.split("/")[2]
        except Exception:
            host = "?"
        if "imweb" in host and auth:
            d = diag.setdefault(host, set())
            d.add("/" + "/".join(request.url.split("?")[0].split("/")[3:5]))
        if auth.startswith("Bearer ") and "oms.imweb.me" in request.url:
            token_holder["token"] = auth.replace("Bearer ", "")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(OMS_PROFILE), headless=headless,
                                                   viewport={"width": 1280, "height": 860})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", on_request)

        def open_admin():
            page.goto(OMS_ORDER_URL, wait_until="domcontentloaded", timeout=60000)
            for _ in range(20):                       # 최대 ~20초: 토큰 요청이 보일 때까지
                if token_holder.get("token"):
                    break
                page.wait_for_timeout(1000)

        open_admin()
        if not token_holder.get("token") and manual_login:
            print("   ▶ 열린 브라우저 창에서 아임웹 관리자에 직접 로그인하세요 (추가 인증이 뜨면 그것도 직접 진행).")
            print("   ▶ 로그인이 끝나면 자동으로 이어집니다. 최대 5분 대기...")
            page.goto("https://imweb.me/login", wait_until="domcontentloaded", timeout=60000)
            for _ in range(150):                      # 2초 × 150 = 5분
                page.wait_for_timeout(2000)
                if "/mysite" in page.url or "/admin" in page.url:
                    break
            open_admin()
        final_url = page.url
        ctx.close()
    return token_holder.get("token", ""), diag, final_url


def get_oms_token() -> str:
    """OMS Bearer 토큰 반환 (캐시 → 저장된 세션으로 자동 → 안 되면 직접 로그인 창)"""
    cached = _load_cached_token()
    if cached:
        print("   [토큰 캐시 사용]")
        return cached

    OMS_PROFILE.mkdir(exist_ok=True)
    print("[1] 저장된 로그인 세션으로 OMS 접속 중...")
    token, diag, final_url = _capture_oms_token(headless=True, manual_login=False)
    if not token:
        print("   저장된 로그인이 없거나 만료되었습니다. 로그인 창을 엽니다.")
        token, diag, final_url = _capture_oms_token(headless=False, manual_login=True)
    if not token:
        print("   [진단] 최종 페이지:", final_url.split("?")[0])
        for h, paths in sorted(diag.items()):
            print(f"   [진단] 인증 요청 {h}: {sorted(paths)[:6]}")
        raise RuntimeError("OMS Bearer 토큰을 가져오지 못했습니다.")
    print(f"   토큰 획득 (길이 {len(token)})")
    _save_token(token)
    return token


def fetch_orders(token: str, date_from: str = None, date_to: str = None) -> list:
    """OMS API로 주문 목록 수집 (제품명 + 옵션 포함)"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Referer": "https://app.oms.imweb.me/",
    }

    if not date_from:
        date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    all_orders = []
    page = 1

    print(f"[3] 주문 수집 중 ({date_from} ~ {date_to})...")

    while True:
        params = {
            "page": page,
            "sort": "wtime",
            "orderDateFrom": f"{date_from}T00:00:00.000Z",
            "orderDateTo":   f"{date_to}T23:59:59.000Z",
        }
        r = requests.get(f"{OMS_API_BASE}/order", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()

        orders = body.get("data", {}).get("list", [])
        if not orders:
            break

        for order in orders:
            all_orders.extend(_parse_order_items(order))

        print(f"   page {page}: {len(orders)}건")

        # 다음 페이지 확인
        pagination = body.get("data", {}).get("pagenation", {})
        total_pages = pagination.get("totalPage", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)

    return all_orders


def _parse_order_items(order, status_override=None):
    """주문 객체에서 item 목록 추출 (공통 파서)"""
    items = []
    for section in order.get("orderSectionList", []):
        for item in section.get("orderSectionItemList", []):
            option_str = ", ".join(
                f"{o['key']}:{o['value']}"
                for o in (item.get("optionInfo") or [])
            )
            items.append({
                "orderNo":    order["orderNo"],
                "orderDate":  order["orderDate"][:10],
                "orderer":    order.get("ordererName", ""),
                "receiver":   order.get("receiverName", ""),
                "phone":      order.get("receiverPhone", ""),
                "address":    order.get("receiverAddress", ""),
                "channel":    order.get("saleChannelName", ""),
                "prodName":   item.get("prodName", ""),
                "option":     option_str,
                "qty":        item.get("qty", 1),
                "itemPrice":  item.get("itemPrice", 0),
                "status":     status_override or order.get("sectionStatusCd", ""),
            })
    return items


def fetch_by_tab(token: str, tab_code: str,
                 date_from: str = None, date_to: str = None,
                 max_pages: int = 0) -> list:
    """탭 코드로 주문 수집 (배송대기 등 상태별 필터링)"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Referer": "https://app.oms.imweb.me/",
    }
    all_items = []
    page = 1

    while True:
        params = {"page": page, "sort": "wtime", "tabCode": tab_code}
        if date_from:
            params["orderDateFrom"] = f"{date_from}T00:00:00.000Z"
        if date_to:
            params["orderDateTo"]   = f"{date_to}T23:59:59.000Z"

        r = requests.get(f"{OMS_API_BASE}/order", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        body = r.json()

        orders = body.get("data", {}).get("list", [])
        if not orders:
            break

        for order in orders:
            all_items.extend(_parse_order_items(order))

        pagination  = body.get("data", {}).get("pagenation", {})
        total_pages = pagination.get("totalPage", 1)
        print(f"   page {page}/{total_pages}: {len(orders)}건")

        if page >= total_pages:
            break
        if max_pages and page >= max_pages:
            print(f"   (max_pages={max_pages}로 중단)")
            break
        page += 1
        time.sleep(0.3)

    return all_items


def fetch_delivery_waiting(token: str,
                           date_from: str = None,
                           date_to: str = None,
                           max_pages: int = 0) -> list:
    """배송대기(OSS02) 주문 수집"""
    print(f"[배송대기 수집] 날짜: {date_from or '전체'} ~ {date_to or '전체'}")
    return fetch_by_tab(token, TAB_DELIVERY_WAIT, date_from, date_to, max_pages)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", default=None, help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--to",   dest="date_to",   default=None, help="종료일 (YYYY-MM-DD)")
    parser.add_argument("--out",  default="orders_with_products.json", help="출력 파일")
    args = parser.parse_args()

    token  = get_oms_token()
    orders = fetch_orders(token, args.date_from, args.date_to)

    out_path = Path(__file__).parent / args.out
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] {len(orders)}건 저장 → {out_path}")
    print("\n샘플 (상위 5건):")
    for o in orders[:5]:
        print(f"  {o['orderDate']} | {o['prodName'][:30]} | {o['option']} | {o['qty']}개")


if __name__ == "__main__":
    main()
