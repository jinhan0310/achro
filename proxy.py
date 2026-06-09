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
import openpyxl

load_dotenv()
API_KEY    = os.getenv('IMWEB_API_KEY', '')
SECRET_KEY = os.getenv('IMWEB_SECRET_KEY', '')
IMWEB_BASE = 'https://api.imweb.me'
OMS_BASE   = 'https://api.oms.imweb.me/admin/v1'

# OMS 읽기 전용 허용 엔드포인트 (이 외 모든 OMS 요청은 차단)
OMS_READONLY_PATHS = {'/order'}
OMS_READONLY_METHOD = 'GET'
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

def _oms_get(path, params=None, timeout=20):
    """OMS API GET 전용 호출 — POST/PUT/DELETE 는 코드 레벨에서 불가."""
    token = _oms_load_token()
    if not token:
        raise RuntimeError('OMS 토큰 없음')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Referer': 'https://app.oms.imweb.me/',
    }
    url = OMS_BASE + path
    if params:
        url += '?' + urlencode(params)
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _oms_save_token(token):
    try:
        _TOKEN_CACHE.write_text(
            json.dumps({'token': token, 'expires': time.time() + 86400 * 30}),
            encoding='utf-8'
        )
    except Exception:
        pass

DELIVERY_STATUSES = {'OSS02'}  # 배송대기만 (OSS01 상품준비중 제외)

STATUS_LABEL = {
    'OSS01': '상품준비중', 'OSS02': '배송대기', 'OSS03': '배송중',
    'OSS04': '배송완료', 'OSS05': '구매확정', 'OSS06': '취소',
    'OSS07': '교환', 'OSS08': '반품', 'OSS09': '환불',
    'PARTIAL_SHIPPED': '부분배송', 'SHIPPED': '배송중',
    'PARTIAL_CANCEL': '부분취소', 'PARTIAL_EXCHANGE': '부분교환',
    'PARTIAL_CANCEL_RETURN': '부분취소반품', 'PARTIAL_RETURN': '부분반품',
}

def _oms_scan_pages(max_pages=10):
    """OMS /order 를 GET 전용으로 최대 max_pages 페이지 스캔. (list, error) 반환."""
    all_orders = []
    for page in range(1, max_pages + 1):
        try:
            body = _oms_get('/order', {'page': page, 'sort': 'wtime', 'pageSize': 100})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, 'OMS 토큰 만료 — fetch_orders_oms.py를 실행해 토큰을 갱신하세요.'
            return None, f'OMS API 오류 (HTTP {e.code}): {e.reason}'
        except RuntimeError as e:
            return None, str(e)
        except Exception as e:
            return None, f'OMS API 오류: {e}'
        orders = (body.get('data') or {}).get('list', [])
        if not orders:
            break
        all_orders.extend(orders)
    return all_orders, None

def _oms_fetch_delivery_waiting(date_from=None, date_to=None):
    orders, err = _oms_scan_pages()
    if err:
        return None, err

    all_items = []
    for order in orders:
        if order.get('sectionStatusCd') not in DELIVERY_STATUSES:
            continue
        dl = (order.get('orderDeliveryList') or [{}])[0]
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
                    'receiver':  dl.get('receiverName', ''),
                    'phone':     dl.get('receiverCall', ''),
                    'zipcode':   dl.get('zipcode', ''),
                    'address':   (dl.get('addr1', '') + ' ' + dl.get('addr2', '')).strip(),
                    'prodName':  item.get('prodName', ''),
                    'option':    opts,
                    'qty':       item.get('qty', 1),
                    'itemPrice': item.get('itemPrice', 0),
                    'channel':   order.get('saleChannelName', ''),
                })
    return all_items, None

def _oms_fetch_order_memos():
    """관리자 메모가 있는 주문 목록 반환 (최근 10페이지 GET 전용 스캔)"""
    orders, err = _oms_scan_pages()
    if err:
        return None, err

    result = []
    for order in orders:
        memos = order.get('orderMemos') or []
        if not memos:
            continue
        active_memos = [m for m in memos if m.get('isDel') != 'Y']
        if not active_memos:
            continue

        for order in orders:
            memos = order.get('orderMemos') or []
            if not memos:
                continue
            active_memos = [m for m in memos if m.get('isDel') != 'Y']
            if not active_memos:
                continue

            status_cd = order.get('sectionStatusCd', '')
            dl = (order.get('orderDeliveryList') or [{}])[0]

            # 결제수단 추출
            pay_method = ''
            pi = order.get('paymentInfo') or {}
            for pl in pi.get('paymentList') or []:
                for d in pl.get('data') or []:
                    easy = d.get('easy') or {}
                    bd = easy.get('bodyData') or {}
                    if bd.get('paymentMethod'):
                        pay_method = bd['paymentMethod']
                        break

            # 상품 목록
            items = []
            for section in order.get('orderSectionList') or []:
                for item in section.get('orderSectionItemList') or []:
                    opts = ' / '.join(
                        f"{o['key']}: {o['value']}"
                        for o in (item.get('optionInfo') or [])
                    )
                    items.append({
                        'name':      item.get('prodName', ''),
                        'option':    opts,
                        'qty':       item.get('qty', 1),
                        'price':     item.get('itemPrice', 0),
                        'origPrice': item.get('baseItemPrice', 0),
                        'image':     item.get('imageUrl', ''),
                        'itemNo':    item.get('orderSectionItemNo', ''),
                    })

            result.append({
                'orderNo':      str(order['orderNo']),
                'orderDate':    order['orderDate'][:16].replace('T', ' '),
                'orderer':      order.get('ordererName', ''),
                'ordererCall':  order.get('ordererCall', ''),
                'status':       STATUS_LABEL.get(status_cd, status_cd),
                'channel':      order.get('saleChannelName', ''),
                'paymentPrice': order.get('paymentPrice', 0),
                'prodPrice':    pi.get('totalPrice', 0),
                'deliveryFee':  pi.get('totalDeliveryPrice', 0),
                'discountPrice':pi.get('totalDiscountPrice', 0),
                'payMethod':    pay_method,
                'receiver':     dl.get('receiverName', ''),
                'receiverCall': dl.get('receiverCall', ''),
                'zipcode':      dl.get('zipcode', ''),
                'address':      (dl.get('addr1', '') + ' ' + dl.get('addr2', '')).strip(),
                'deliveryMemo': dl.get('memo') or '',
                'items':        items,
                'memos': [{
                    'memo':   m.get('memo', ''),
                    'author': m.get('name', ''),
                    'time':   m.get('wtime', '')[:16].replace('T', ' ') if m.get('wtime') else '',
                    'isDone': m.get('isDone', 'N'),
                } for m in active_memos],
            })

    return result, None


# ── 아임웹 API 헬퍼 ─────────────────────────────────────────────────
def _save_delivery_excel(items):
    """배송대기 아이템 목록을 Excel로 생성해 Downloads 폴더에 저장"""
    downloads = Path.home() / 'Downloads'
    fname = f'배송대기_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    fpath = downloads / fname

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '배송대기'

    headers = ['주문번호', '주문일', '채널', '주문자명', '수령자명', '전화번호',
               '우편번호', '주소', '상품명', '옵션명', '구매수량', '단가']
    ws.append(headers)

    for item in items:
        ws.append([
            item.get('orderNo', ''),
            item.get('orderDate', ''),
            item.get('channel', ''),
            item.get('orderer', ''),
            item.get('receiver', ''),
            item.get('phone', ''),
            item.get('zipcode', ''),
            item.get('address', ''),
            item.get('prodName', ''),
            item.get('option', ''),
            item.get('qty', 1),
            item.get('itemPrice', 0),
        ])

    wb.save(str(fpath))
    return fname

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

        if self.path == '/api/delivery-waiting/save-excel':
            items, err = _oms_fetch_delivery_waiting()
            if err:
                return self._json(200, {'ok': False, 'msg': err})
            try:
                fname = _save_delivery_excel(items)
                order_cnt = len(set(i['orderNo'] for i in items))
                return self._json(200, {'ok': True, 'file': fname, 'orders': order_cnt, 'items': len(items)})
            except Exception as e:
                return self._json(200, {'ok': False, 'msg': f'Excel 생성 오류: {e}'})

        if self.path.startswith('/api/delivery-waiting'):
            parsed = urlparse(self.path)
            qs     = parse_qs(parsed.query)
            date_from = qs.get('from', [None])[0]
            date_to   = qs.get('to',   [None])[0]
            items, err = _oms_fetch_delivery_waiting(date_from, date_to)
            if err:
                return self._json(200, {'ok': False, 'msg': err})
            return self._json(200, {'ok': True, 'items': items, 'count': len(items)})

        if self.path.startswith('/api/order-memos'):
            orders, err = _oms_fetch_order_memos()
            if err:
                return self._json(200, {'ok': False, 'msg': err})
            return self._json(200, {'ok': True, 'orders': orders, 'count': len(orders)})

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
        # OMS 도메인으로의 직접 프록시 요청은 모두 차단
        if 'oms.imweb.me' in self.path:
            return self._json(403, {'ok': False, 'msg': 'OMS 직접 프록시 차단 — 읽기 전용 API만 허용됩니다.'})

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
