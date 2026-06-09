"""
아임웹 API CORS 프록시 + 고객분석 API
포트: 7777

엔드포인트:
  GET  /ping                → 헬스체크
  GET  /api/customers       → DB에서 고객 리스트 반환
  POST /api/customers/update → 아임웹 API 전체 수집 → DB 업데이트
  기타 → 아임웹 API 프록시
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, urllib.error, json, os, sqlite3, time, threading
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from urllib.parse import urlencode, parse_qs, urlparse

load_dotenv()
API_KEY    = os.getenv('IMWEB_API_KEY', '')
SECRET_KEY = os.getenv('IMWEB_SECRET_KEY', '')
IMWEB_BASE = 'https://api.imweb.me'
OMS_BASE   = 'https://api.oms.imweb.me/admin/v1'
DB         = Path(__file__).parent / 'jarvis' / 'jarvis.db'
_TOKEN_CACHE = Path(__file__).parent / '.oms_token.json'
TAB_DELIVERY_WAIT = 't202407045444dde9a5ed1'

# 업데이트 진행 상태 (동시 실행 방지)
_update_lock   = threading.Lock()
_update_status = {'running': False, 'progress': '', 'last_done': '', 'last_error': ''}


# ── OMS 배송대기 API ────────────────────────────────────────────────
def _oms_load_token():
    """토큰 파일에서 로드. 로컬 만료와 무관하게 반환하고 실제 API 오류로 판단."""
    try:
        if _TOKEN_CACHE.exists():
            data = json.loads(_TOKEN_CACHE.read_text(encoding='utf-8'))
            return data.get('token')
    except Exception:
        pass
    return None

def _oms_save_token(token):
    try:
        _TOKEN_CACHE.write_text(
            json.dumps({'token': token, 'expires': time.time() + 86400 * 30}),
            encoding='utf-8'
        )
    except Exception:
        pass

def _oms_fetch_delivery_waiting(date_from=None, date_to=None):
    token = _oms_load_token()
    if not token:
        return None, 'OMS 토큰 없음 — fetch_orders_oms.py 또는 check_delivery.py를 먼저 실행하세요.'

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Referer': 'https://app.oms.imweb.me/',
    }

    all_items, page = [], 1
    while True:
        params = {'page': page, 'sort': 'wtime', 'tabCode': TAB_DELIVERY_WAIT}
        if date_from:
            params['orderDateFrom'] = f'{date_from}T00:00:00.000Z'
        if date_to:
            params['orderDateTo']   = f'{date_to}T23:59:59.000Z'

        url = OMS_BASE + '/order?' + urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, 'OMS 토큰 만료 — fetch_orders_oms.py를 실행해 토큰을 갱신하세요.'
            return None, f'OMS API 오류 (HTTP {e.code}): {e.reason}'
        except Exception as e:
            return None, f'OMS API 오류: {e}'

        data_block = body.get('data') or {}
        orders = data_block.get('list', [])
        if not orders:
            break

        for order in orders:
            for section in order.get('orderSectionList', []):
                for item in section.get('orderSectionItemList', []):
                    opts = ', '.join(
                        f"{o['key']}:{o['value']}"
                        for o in (item.get('optionInfo') or [])
                    )
                    all_items.append({
                        'orderNo':   str(order['orderNo']),
                        'orderDate': order['orderDate'][:10],
                        'orderer':   order.get('ordererName', ''),
                        'receiver':  order.get('receiverName', ''),
                        'phone':     order.get('receiverPhone', ''),
                        'prodName':  item.get('prodName', ''),
                        'option':    opts,
                        'qty':       item.get('qty', 1),
                        'itemPrice': item.get('itemPrice', 0),
                        'channel':   order.get('saleChannelName', ''),
                    })

        pagination  = data_block.get('pagenation', {})
        total_pages = pagination.get('totalPage', 1)
        if page >= total_pages:
            break
        page += 1

    return all_items, None

# ── 아임웹 API 헬퍼 ─────────────────────────────────────────────────
def _get_token():
    url  = f'{IMWEB_BASE}/v2/auth'
    body = json.dumps({'key': API_KEY, 'secret': SECRET_KEY}).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())
    if res.get('code') != 200:
        raise RuntimeError(f'인증 실패: {res}')
    return res['access_token']

def _fetch_page(token, page, limit=100):
    url = f'{IMWEB_BASE}/v2/shop/orders?limit={limit}&offset={page}'
    req = urllib.request.Request(url, headers={'access-token': token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def _collect_all_orders(token):
    all_orders, page, total_page = [], 0, None
    retry_delay = 3.0
    while True:
        try:
            res = _fetch_page(token, page)
        except Exception as e:
            _update_status['progress'] = f'API 오류: {e}'
            break
        code = res.get('code')
        if code == -7:
            _update_status['progress'] = f'rate limit, {retry_delay:.0f}s 대기...'
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
            continue
        if code != 200:
            _update_status['progress'] = f'오류: {res}'
            break
        retry_delay = 3.0
        data   = res['data']
        orders = data.get('list', [])
        pagi   = data.get('pagenation', {})
        if total_page is None:
            total_page = pagi.get('total_page', 1)
            total_cnt  = pagi.get('data_count', 0)
            _update_status['progress'] = f'총 {total_cnt:,}건 수집 시작'
        all_orders.extend(orders)
        _update_status['progress'] = f'{len(all_orders):,}건 수집 중 (page {page+1}/{total_page})'
        page += 1
        if page >= total_page or not orders:
            break
        time.sleep(3.5)
    return all_orders

def _analyze_and_save(orders):
    cmap = defaultdict(lambda: {
        'name':'','phone':'','email':'','member_code':'',
        'total_amount':0,'order_count':0,'first_order':'','last_order':''
    })
    for o in orders:
        pay = o.get('payment', {})
        if not pay.get('payment_time') or pay.get('payment_amount', 0) <= 0:
            continue
        orderer = o.get('orderer', {})
        phone   = str(orderer.get('call','') or '').strip()
        email   = str(orderer.get('email','') or '').strip()
        name    = str(orderer.get('name','') or '').strip()
        mc      = str(orderer.get('member_code','') or '').strip()
        key     = phone or email or mc
        if not key:
            continue
        amount = int(pay['payment_amount'])
        ts     = o.get('order_time', 0)
        date_s = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts > 0 else ''
        c = cmap[key]
        if not c['name'] and name:   c['name']        = name
        if not c['phone'] and phone: c['phone']        = phone
        if not c['email'] and email: c['email']        = email
        if not c['member_code'] and mc: c['member_code'] = mc
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
            'key':key,'name':c['name'],'phone':c['phone'],'email':c['email'],
            'member_code':c['member_code'],'total_amount':amt,'order_count':cnt,
            'first_order':c['first_order'],'last_order':c['last_order'],
            'amount_tier':atier,'count_tier':ctier
        })

    conn = sqlite3.connect(str(DB))
    conn.execute('DROP TABLE IF EXISTS customer_summary')
    conn.execute('''CREATE TABLE customer_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cust_key TEXT, name TEXT, phone TEXT, email TEXT, member_code TEXT,
        total_amount INTEGER, order_count INTEGER,
        first_order TEXT, last_order TEXT, amount_tier TEXT, count_tier TEXT
    )''')
    conn.executemany(
        'INSERT INTO customer_summary (cust_key,name,phone,email,member_code,'
        'total_amount,order_count,first_order,last_order,amount_tier,count_tier)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        [(r['key'],r['name'],r['phone'],r['email'],r['member_code'],
          r['total_amount'],r['order_count'],r['first_order'],r['last_order'],
          r['amount_tier'],r['count_tier']) for r in result]
    )
    conn.commit()
    conn.close()
    return len(result)

def _do_update():
    """백그라운드 스레드에서 실행"""
    global _update_status
    try:
        _update_status['progress'] = 'API 인증 중...'
        token  = _get_token()
        _update_status['progress'] = '주문 수집 중...'
        orders = _collect_all_orders(token)
        _update_status['progress'] = f'고객 집계 중 ({len(orders):,}건)...'
        n      = _analyze_and_save(orders)
        now    = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _update_status.update({'running':False,'progress':'완료','last_done':now,'last_error':''})
        _update_status['result'] = {'customers': n, 'orders': len(orders), 'updated_at': now}
    except Exception as e:
        _update_status.update({'running':False,'progress':'오류','last_error':str(e)})

# ── DB 조회 ────────────────────────────────────────────────────────
def _load_customers():
    if not DB.exists():
        return []
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT name,phone,email,total_amount,order_count,'
        'first_order,last_order,amount_tier,count_tier'
        ' FROM customer_summary ORDER BY total_amount DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── HTTP 핸들러 ────────────────────────────────────────────────────
class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'access-token, content-type, *')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/ping':
            return self._json(200, {'ok': True})

        if self.path == '/api/customers':
            return self._json(200, {
                'ok': True,
                'customers': _load_customers(),
                'status': _update_status
            })

        if self.path == '/api/customers/status':
            return self._json(200, _update_status)

        if self.path.startswith('/api/delivery-waiting'):
            parsed = urlparse(self.path)
            qs     = parse_qs(parsed.query)
            date_from = qs.get('from', [None])[0]
            date_to   = qs.get('to',   [None])[0]
            items, err = _oms_fetch_delivery_waiting(date_from, date_to)
            if err:
                return self._json(200, {'ok': False, 'msg': err})
            return self._json(200, {'ok': True, 'items': items, 'count': len(items)})

        self._proxy('GET')

    def do_POST(self):
        if self.path == '/api/customers/update':
            global _update_status
            if _update_status['running']:
                return self._json(200, {'ok': False, 'msg': '이미 업데이트 중입니다.'})
            _update_status.update({'running': True, 'progress': '시작 중...', 'last_error': ''})
            t = threading.Thread(target=_do_update, daemon=True)
            t.start()
            return self._json(200, {'ok': True, 'msg': '업데이트 시작됨'})
        self._proxy('POST')

    def _proxy(self, method):
        target  = IMWEB_BASE + self.path
        headers = {}
        if self.headers.get('access-token'):
            headers['access-token'] = self.headers['access-token']
        if self.headers.get('content-type'):
            headers['content-type'] = self.headers['content-type']
        body = None
        if method == 'POST':
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length) if length else None
        try:
            req = urllib.request.Request(target, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._cors()
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == '__main__':
    server = HTTPServer(('localhost', 7777), ProxyHandler)
    print('프록시 + 고객 API 실행 중: http://localhost:7777')
    print('종료: Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n종료')
