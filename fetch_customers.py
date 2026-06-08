"""
아임웹 API → customers_data.json 생성
GitHub Actions 및 로컬 실행 모두 지원

환경변수: IMWEB_API_KEY, IMWEB_SECRET_KEY
"""
import os, json, time, sys, urllib.request
from datetime import datetime
from collections import defaultdict
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY    = os.getenv('IMWEB_API_KEY', '')
SECRET_KEY = os.getenv('IMWEB_SECRET_KEY', '')
IMWEB_BASE = 'https://api.imweb.me'
OUT_JSON   = Path(__file__).parent / 'customers_data.json'

def get_token():
    url  = f'{IMWEB_BASE}/v2/auth'
    body = json.dumps({'key': API_KEY, 'secret': SECRET_KEY}).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())
    if res.get('code') != 200:
        raise RuntimeError(f'인증 실패: {res}')
    return res['access_token']

def fetch_all_orders(token):
    all_orders, page, total_page = [], 0, None
    retry_delay = 3.0
    while True:
        url = f'{IMWEB_BASE}/v2/shop/orders?limit=100&offset={page}'
        req = urllib.request.Request(url, headers={'access-token': token})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.loads(r.read())
        except Exception as e:
            print(f'  API 오류 (page={page}): {e}')
            break
        code = res.get('code')
        if code == -7:
            print(f'  rate limit, {retry_delay:.0f}s 대기...')
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
            continue
        if code != 200:
            print(f'  오류: {res}')
            break
        retry_delay = 3.0
        data   = res['data']
        orders = data.get('list', [])
        pagi   = data.get('pagenation', {})
        if total_page is None:
            total_page = pagi.get('total_page', 1)
            print(f'  총 {pagi.get("data_count",0):,}건 / {total_page}페이지')
        all_orders.extend(orders)
        print(f'  [{len(all_orders):,}건] page {page+1}/{total_page}', end='\r')
        page += 1
        if page >= total_page or not orders:
            break
        time.sleep(3.5)
    print(f'\n  수집 완료: {len(all_orders):,}건')
    return all_orders

def analyze(orders):
    cmap = defaultdict(lambda: {
        'name':'','phone':'','email':'','member_code':'',
        'total_amount':0,'order_count':0,'first_order':'','last_order':''
    })
    for o in orders:
        pay = o.get('payment', {})
        if not pay.get('payment_time') or pay.get('payment_amount', 0) <= 0:
            continue
        orderer = o.get('orderer', {})
        phone = str(orderer.get('call','') or '').strip()
        email = str(orderer.get('email','') or '').strip()
        name  = str(orderer.get('name','') or '').strip()
        mc    = str(orderer.get('member_code','') or '').strip()
        key   = phone or email or mc
        if not key: continue
        amount = int(pay['payment_amount'])
        ts     = o.get('order_time', 0)
        date_s = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts > 0 else ''
        c = cmap[key]
        if not c['name'] and name:      c['name']        = name
        if not c['phone'] and phone:    c['phone']        = phone
        if not c['email'] and email:    c['email']        = email
        if not c['member_code'] and mc: c['member_code']  = mc
        c['total_amount'] += amount
        c['order_count']  += 1
        if date_s:
            if not c['first_order'] or date_s < c['first_order']: c['first_order'] = date_s
            if not c['last_order']  or date_s > c['last_order']:  c['last_order']  = date_s

    result = []
    for key, c in cmap.items():
        amt, cnt = c['total_amount'], c['order_count']
        if   amt < 100_000: atier = '10만원미만'
        elif amt < 200_000: atier = '10-20만원'
        elif amt < 300_000: atier = '20-30만원'
        elif amt < 400_000: atier = '30-40만원'
        else:               atier = '40만원이상'
        if   cnt == 1: ctier = '1회'
        elif cnt == 2: ctier = '2회'
        elif cnt == 3: ctier = '3회'
        elif cnt <= 5: ctier = '4-5회'
        else:          ctier = '6회이상'
        result.append({
            'name':c['name'],'phone':c['phone'],'email':c['email'],
            'total_amount':amt,'order_count':cnt,
            'first_order':c['first_order'],'last_order':c['last_order'],
            'amount_tier':atier,'count_tier':ctier
        })
    result.sort(key=lambda x: -x['total_amount'])
    return result

if __name__ == '__main__':
    print('=' * 50)
    print('  아임웹 고객 데이터 수집')
    print('=' * 50)
    print('  API 인증 중...')
    token     = get_token()
    print('  인증 성공')
    print('  주문 수집 중...')
    orders    = fetch_all_orders(token)
    print('  고객 집계 중...')
    customers = analyze(orders)
    updated   = datetime.now().strftime('%Y-%m-%d %H:%M')
    output    = {'updated_at': updated, 'customers': customers}
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    print(f'  저장: {OUT_JSON} ({len(customers):,}명)')
    print('완료!')
