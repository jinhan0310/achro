"""
아임웹 API → 고객 분석 리포트
누적 구매금액별 / 반복 구매횟수별 고객 리스트

실행: python customer_analysis.py
출력: customers.html (브라우저로 열기)
"""
import os, json, time, sqlite3, urllib.request, urllib.error, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("IMWEB_API_KEY", "")
SECRET_KEY = os.getenv("IMWEB_SECRET_KEY", "")
IMWEB_BASE = "https://api.imweb.me"
DB         = Path(__file__).parent / "jarvis" / "jarvis.db"
OUT_HTML   = Path(__file__).parent / "customers.html"

# ── 인증 ────────────────────────────────────────────────────────────────
def get_token() -> str:
    url  = f"{IMWEB_BASE}/v2/auth"
    body = json.dumps({"key": API_KEY, "secret": SECRET_KEY}).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/json"},
                                   method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())
    if res.get("code") != 200:
        raise RuntimeError(f"인증 실패: {res}")
    return res["access_token"]

# ── 주문 수집 ────────────────────────────────────────────────────────────
def fetch_page(token: str, offset: int, limit: int = 100) -> dict:
    url = f"{IMWEB_BASE}/v2/shop/orders?limit={limit}&offset={offset}"
    req = urllib.request.Request(url, headers={"access-token": token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def fetch_all_orders(token: str) -> list:
    """
    아임웹 v2 API: offset = 페이지 번호(0-indexed), limit = 페이지당 건수
    총 페이지수는 첫 응답의 pagenation.total_page 참조
    """
    all_orders = []
    page       = 0        # offset = 페이지 번호
    limit      = 100
    total_page = None
    total_cnt  = None
    retry_delay = 3.0

    while True:
        try:
            res = fetch_page(token, page, limit)
        except Exception as e:
            print(f"\n  [ERROR] API 오류 (page={page}): {e}")
            break

        code = res.get("code")

        if code == -7:
            print(f"\n  [WAIT] rate limit, {retry_delay:.0f}s wait...", flush=True)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
            continue

        if code != 200:
            print(f"\n  [ERROR] resp error: {res}")
            break

        retry_delay = 3.0
        data   = res["data"]
        orders = data.get("list", [])
        pagi   = data.get("pagenation", {})

        if total_page is None:
            total_page = pagi.get("total_page", 1)
            total_cnt  = pagi.get("data_count", 0)
            print(f"  total {total_cnt:,} orders / {total_page} pages", flush=True)

        all_orders.extend(orders)
        done = len(all_orders)
        print(f"  [page {page+1}/{total_page}] {done:,} orders...", end="\r", flush=True)

        page += 1
        if page >= total_page or not orders:
            break

        time.sleep(3.5)

    print(f"  done: {len(all_orders):,} orders          ")
    return all_orders

# ── 고객 집계 ────────────────────────────────────────────────────────────
def analyze_customers(orders: list) -> list:
    cmap = defaultdict(lambda: {
        "name": "", "phone": "", "email": "", "member_code": "",
        "total_amount": 0, "order_count": 0,
        "first_order": "", "last_order": "", "orders": []
    })

    for o in orders:
        pay = o.get("payment", {})
        # 결제 완료 기준: payment_time > 0 AND payment_amount > 0
        if not pay.get("payment_time") or pay.get("payment_amount", 0) <= 0:
            continue

        orderer = o.get("orderer", {})
        phone   = str(orderer.get("call", "") or "").strip()
        email   = str(orderer.get("email", "") or "").strip()
        name    = str(orderer.get("name", "") or "").strip()
        mc      = str(orderer.get("member_code", "") or "").strip()

        # 고객 키: 전화번호 → 이메일 → member_code 순
        key = phone or email or mc
        if not key:
            continue

        amount  = int(pay["payment_amount"])
        ts      = o.get("order_time", 0)
        date_s  = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts > 0 else ""

        c = cmap[key]
        if not c["name"] and name:    c["name"]        = name
        if not c["phone"] and phone:  c["phone"]       = phone
        if not c["email"] and email:  c["email"]       = email
        if not c["member_code"] and mc: c["member_code"] = mc

        c["total_amount"] += amount
        c["order_count"]  += 1
        c["orders"].append({"order_no": o.get("order_no",""), "date": date_s, "amount": amount})

        if date_s:
            if not c["first_order"] or date_s < c["first_order"]: c["first_order"] = date_s
            if not c["last_order"]  or date_s > c["last_order"]:  c["last_order"]  = date_s

    result = []
    for key, c in cmap.items():
        amt = c["total_amount"]
        cnt = c["order_count"]

        if   amt < 100_000:                  amount_tier = "10만원미만"
        elif amt < 200_000:                  amount_tier = "10-20만원"
        elif amt < 300_000:                  amount_tier = "20-30만원"
        elif amt < 400_000:                  amount_tier = "30-40만원"
        else:                                amount_tier = "40만원이상"

        if   cnt == 1:  count_tier = "1회"
        elif cnt == 2:  count_tier = "2회"
        elif cnt == 3:  count_tier = "3회"
        elif cnt <= 5:  count_tier = "4-5회"
        else:           count_tier = "6회이상"

        result.append({
            "key": key, "name": c["name"], "phone": c["phone"],
            "email": c["email"], "member_code": c["member_code"],
            "total_amount": amt, "order_count": cnt,
            "first_order": c["first_order"], "last_order": c["last_order"],
            "amount_tier": amount_tier, "count_tier": count_tier,
        })

    result.sort(key=lambda x: -x["total_amount"])
    return result

# ── DB 저장 ─────────────────────────────────────────────────────────────
def save_to_db(customers: list):
    conn = sqlite3.connect(DB)
    conn.execute("DROP TABLE IF EXISTS customer_summary")
    conn.execute("""
    CREATE TABLE customer_summary (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        cust_key     TEXT,
        name         TEXT,
        phone        TEXT,
        email        TEXT,
        member_code  TEXT,
        total_amount INTEGER,
        order_count  INTEGER,
        first_order  TEXT,
        last_order   TEXT,
        amount_tier  TEXT,
        count_tier   TEXT
    )""")
    conn.executemany(
        """INSERT INTO customer_summary
           (cust_key,name,phone,email,member_code,
            total_amount,order_count,first_order,last_order,
            amount_tier,count_tier)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(c["key"],c["name"],c["phone"],c["email"],c["member_code"],
          c["total_amount"],c["order_count"],c["first_order"],c["last_order"],
          c["amount_tier"],c["count_tier"]) for c in customers]
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM customer_summary").fetchone()[0]
    conn.close()
    print(f"  DB 저장: {n:,}명 → jarvis/jarvis.db")

# ── HTML 생성 ─────────────────────────────────────────────────────────────
def generate_html(customers: list):
    # 구간별 통계
    amt_tiers  = ["10만원미만","10-20만원","20-30만원","30-40만원","40만원이상"]
    cnt_tiers  = ["1회","2회","3회","4-5회","6회이상"]
    amt_counts = {t: sum(1 for c in customers if c["amount_tier"]==t) for t in amt_tiers}
    cnt_counts = {t: sum(1 for c in customers if c["count_tier"]==t) for t in cnt_tiers}
    total_cust = len(customers)
    total_amt  = sum(c["total_amount"] for c in customers)

    data_json = json.dumps(customers, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ACHRO 고객 분석</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Pretendard','Apple SD Gothic Neo',sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}}
  .header{{background:linear-gradient(135deg,#1e293b,#0f172a);border-bottom:1px solid #334155;padding:20px 32px;display:flex;align-items:center;gap:16px}}
  .header h1{{font-size:1.4rem;font-weight:700;color:#f8fafc;letter-spacing:-.5px}}
  .header .sub{{font-size:.85rem;color:#94a3b8;margin-top:2px}}
  .badge{{background:#3b82f6;color:#fff;font-size:.75rem;padding:3px 10px;border-radius:20px;font-weight:600}}
  .container{{max-width:1400px;margin:0 auto;padding:24px 24px}}
  .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:28px}}
  .stat-card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px 20px;text-align:center}}
  .stat-card .val{{font-size:1.6rem;font-weight:700;color:#60a5fa}}
  .stat-card .lbl{{font-size:.78rem;color:#94a3b8;margin-top:4px}}
  .tabs{{display:flex;gap:0;border-bottom:2px solid #334155;margin-bottom:24px}}
  .tab{{padding:10px 24px;cursor:pointer;font-size:.9rem;font-weight:500;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s}}
  .tab.active{{color:#60a5fa;border-bottom-color:#60a5fa}}
  .tab:hover:not(.active){{color:#cbd5e1}}
  .panel{{display:none}}.panel.active{{display:block}}
  .tier-tabs{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}}
  .tier-btn{{padding:6px 18px;border-radius:20px;border:1px solid #475569;background:transparent;color:#94a3b8;cursor:pointer;font-size:.82rem;font-weight:500;transition:all .2s}}
  .tier-btn.active{{background:#3b82f6;border-color:#3b82f6;color:#fff}}
  .tier-btn:hover:not(.active){{border-color:#94a3b8;color:#e2e8f0}}
  .tier-badge{{display:inline-block;background:#1e3a5f;color:#93c5fd;font-size:.7rem;padding:1px 7px;border-radius:10px;margin-left:4px}}
  .toolbar{{display:flex;gap:12px;align-items:center;margin-bottom:14px;flex-wrap:wrap}}
  .search-box{{flex:1;min-width:200px;max-width:360px;background:#1e293b;border:1px solid #475569;border-radius:8px;padding:8px 14px;color:#e2e8f0;font-size:.88rem;outline:none}}
  .search-box:focus{{border-color:#60a5fa}}
  .search-box::placeholder{{color:#64748b}}
  .btn{{padding:7px 16px;border-radius:8px;border:1px solid #475569;background:#1e293b;color:#94a3b8;cursor:pointer;font-size:.82rem;font-weight:500;transition:all .2s}}
  .btn:hover{{background:#334155;color:#e2e8f0}}
  .btn.primary{{background:#3b82f6;border-color:#3b82f6;color:#fff}}
  .btn.primary:hover{{background:#2563eb}}
  .count-info{{font-size:.82rem;color:#64748b;margin-left:auto}}
  .table-wrap{{overflow-x:auto;border-radius:12px;border:1px solid #334155}}
  table{{width:100%;border-collapse:collapse;font-size:.85rem}}
  thead tr{{background:#1e293b;border-bottom:1px solid #334155}}
  thead th{{padding:11px 14px;text-align:left;font-weight:600;color:#94a3b8;font-size:.78rem;letter-spacing:.5px;cursor:pointer;user-select:none;white-space:nowrap}}
  thead th:hover{{color:#e2e8f0}}
  thead th.sorted-asc::after{{content:" ↑"}}
  thead th.sorted-desc::after{{content:" ↓"}}
  tbody tr{{border-bottom:1px solid #1e293b;transition:background .15s}}
  tbody tr:hover{{background:#1e3a5f22}}
  tbody td{{padding:10px 14px;color:#cbd5e1;vertical-align:middle}}
  .rank{{color:#64748b;font-size:.78rem;font-weight:600}}
  .amount{{color:#34d399;font-weight:600}}
  .cnt{{color:#a78bfa;font-weight:600}}
  .phone{{color:#60a5fa;font-family:monospace;font-size:.82rem}}
  .email{{color:#94a3b8;font-size:.78rem}}
  .date{{color:#64748b;font-size:.78rem;white-space:nowrap}}
  .tier-chip{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.72rem;font-weight:600}}
  .chip-10미만{{background:#1e3a5f;color:#93c5fd}}
  .chip-10-20{{background:#1c3a2e;color:#6ee7b7}}
  .chip-20-30{{background:#2a2820;color:#fcd34d}}
  .chip-30-40{{background:#2a1f20;color:#fca5a5}}
  .chip-40이상{{background:#2d1b4e;color:#c4b5fd}}
  .chip-1회{{background:#1e3a5f;color:#93c5fd}}
  .chip-2회{{background:#1c3a2e;color:#6ee7b7}}
  .chip-3회{{background:#2a2820;color:#fcd34d}}
  .chip-4-5{{background:#2a1f20;color:#fca5a5}}
  .chip-6이상{{background:#2d1b4e;color:#c4b5fd}}
  .empty{{text-align:center;padding:60px;color:#475569;font-size:.9rem}}
  .bar-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:28px}}
  .bar-card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px 20px}}
  .bar-card h3{{font-size:.85rem;font-weight:600;color:#94a3b8;margin-bottom:14px;letter-spacing:.5px}}
  .bar-item{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
  .bar-label{{font-size:.8rem;color:#cbd5e1;width:80px;flex-shrink:0}}
  .bar-track{{flex:1;background:#0f172a;border-radius:4px;height:18px;overflow:hidden;position:relative}}
  .bar-fill{{height:100%;border-radius:4px;transition:width .6s ease}}
  .bar-value{{font-size:.78rem;color:#94a3b8;width:50px;text-align:right;flex-shrink:0}}
</style>
</head>
<body>
<div class="header">
  <div>
    <div style="display:flex;align-items:center;gap:12px">
      <h1>ACHRO 고객 분석</h1>
      <span class="badge">API 직접 수집</span>
    </div>
    <div class="sub">아임웹 전체 기간 주문 데이터 기반 · 생성: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  </div>
</div>

<div class="container">
  <!-- 요약 카드 -->
  <div class="stats-grid">
    <div class="stat-card"><div class="val">{total_cust:,}</div><div class="lbl">전체 고객수</div></div>
    <div class="stat-card"><div class="val">{total_amt:,.0f}<span style="font-size:.9rem">원</span></div><div class="lbl">누적 총 매출</div></div>
    <div class="stat-card"><div class="val">{(total_amt//total_cust if total_cust else 0):,}<span style="font-size:.9rem">원</span></div><div class="lbl">고객 평균 구매액</div></div>
    <div class="stat-card"><div class="val" style="color:#a78bfa">{sum(1 for c in customers if c['order_count']>=2):,}</div><div class="lbl">재구매 고객수</div></div>
    <div class="stat-card"><div class="val" style="color:#34d399">{sum(1 for c in customers if c['total_amount']>=400000):,}</div><div class="lbl">40만원+ 우수고객</div></div>
  </div>

  <!-- 분포 차트 -->
  <div class="bar-grid">
    <div class="bar-card">
      <h3>누적금액별 고객 분포</h3>
      {"".join(f'''<div class="bar-item">
        <span class="bar-label">{t}</span>
        <div class="bar-track"><div class="bar-fill" style="width:{(amt_counts[t]/total_cust*100 if total_cust else 0):.1f}%;background:{"#3b82f6" if i==0 else "#10b981" if i==1 else "#f59e0b" if i==2 else "#ef4444" if i==3 else "#8b5cf6"}"></div></div>
        <span class="bar-value">{amt_counts[t]:,}명</span>
      </div>''' for i,t in enumerate(amt_tiers))}
    </div>
    <div class="bar-card">
      <h3>재구매횟수별 고객 분포</h3>
      {"".join(f'''<div class="bar-item">
        <span class="bar-label">{t}</span>
        <div class="bar-track"><div class="bar-fill" style="width:{(cnt_counts[t]/total_cust*100 if total_cust else 0):.1f}%;background:{"#3b82f6" if i==0 else "#10b981" if i==1 else "#f59e0b" if i==2 else "#ef4444" if i==3 else "#8b5cf6"}"></div></div>
        <span class="bar-value">{cnt_counts[t]:,}명</span>
      </div>''' for i,t in enumerate(cnt_tiers))}
    </div>
  </div>

  <!-- 탭 -->
  <div class="tabs">
    <div class="tab active" onclick="switchTab('amount')">누적 구매금액별</div>
    <div class="tab" onclick="switchTab('count')">반복 구매횟수별</div>
  </div>

  <!-- 누적금액 패널 -->
  <div id="panel-amount" class="panel active">
    <div class="tier-tabs" id="amt-tier-tabs">
      <button class="tier-btn active" onclick="filterAmt('all')">전체 <span class="tier-badge">{total_cust}</span></button>
      {"".join(f'<button class="tier-btn" onclick="filterAmt(\'{t}\')">{t} <span class="tier-badge">{amt_counts[t]}</span></button>' for t in amt_tiers)}
    </div>
    <div class="toolbar">
      <input class="search-box" id="amt-search" placeholder="이름 / 전화번호 / 이메일 검색..." oninput="renderTable()">
      <button class="btn primary" onclick="exportCSV('amount')">CSV 내보내기</button>
      <span class="count-info" id="amt-count"></span>
    </div>
    <div class="table-wrap">
      <table id="amt-table">
        <thead><tr>
          <th onclick="sortTable('amount','rank')">#</th>
          <th onclick="sortTable('amount','name')">이름</th>
          <th onclick="sortTable('amount','phone')">전화번호</th>
          <th onclick="sortTable('amount','email')">이메일</th>
          <th onclick="sortTable('amount','total_amount')">누적금액 ▼</th>
          <th onclick="sortTable('amount','order_count')">구매횟수</th>
          <th onclick="sortTable('amount','first_order')">첫구매일</th>
          <th onclick="sortTable('amount','last_order')">최근구매일</th>
          <th>구간</th>
        </tr></thead>
        <tbody id="amt-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- 구매횟수 패널 -->
  <div id="panel-count" class="panel">
    <div class="tier-tabs" id="cnt-tier-tabs">
      <button class="tier-btn active" onclick="filterCnt('all')">전체 <span class="tier-badge">{total_cust}</span></button>
      {"".join(f'<button class="tier-btn" onclick="filterCnt(\'{t}\')">{t} <span class="tier-badge">{cnt_counts[t]}</span></button>' for t in cnt_tiers)}
    </div>
    <div class="toolbar">
      <input class="search-box" id="cnt-search" placeholder="이름 / 전화번호 / 이메일 검색..." oninput="renderTable()">
      <button class="btn primary" onclick="exportCSV('count')">CSV 내보내기</button>
      <span class="count-info" id="cnt-count"></span>
    </div>
    <div class="table-wrap">
      <table id="cnt-table">
        <thead><tr>
          <th>#</th>
          <th onclick="sortTable('count','name')">이름</th>
          <th onclick="sortTable('count','phone')">전화번호</th>
          <th onclick="sortTable('count','email')">이메일</th>
          <th onclick="sortTable('count','order_count')">구매횟수 ▼</th>
          <th onclick="sortTable('count','total_amount')">누적금액</th>
          <th onclick="sortTable('count','first_order')">첫구매일</th>
          <th onclick="sortTable('count','last_order')">최근구매일</th>
          <th>구간</th>
        </tr></thead>
        <tbody id="cnt-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const ALL_DATA = {data_json};

let curTab      = 'amount';
let amtFilter   = 'all';
let cntFilter   = 'all';
let amtSort     = {{key:'total_amount', dir:-1}};
let cntSort     = {{key:'order_count',  dir:-1}};

const CHIP = {{
  '10만원미만':'chip-10미만','10-20만원':'chip-10-20','20-30만원':'chip-20-30',
  '30-40만원':'chip-30-40','40만원이상':'chip-40이상',
  '1회':'chip-1회','2회':'chip-2회','3회':'chip-3회','4-5회':'chip-4-5','6회이상':'chip-6이상'
}};

function fmt(n){{return n.toLocaleString('ko-KR')+'원'}}
function fmtPhone(s){{
  if(!s) return '-';
  s = s.replace(/[^0-9]/g,'');
  if(s.length===11) return s.replace(/(\\d{{3}})(\\d{{4}})(\\d{{4}})/,'$1-$2-$3');
  if(s.length===10) return s.replace(/(\\d{{3}})(\\d{{3,4}})(\\d{{4}})/,'$1-$2-$3');
  return s;
}}

function switchTab(t){{
  curTab = t;
  document.querySelectorAll('.tab').forEach((el,i)=>el.classList.toggle('active',i==(t=='amount'?0:1)));
  document.getElementById('panel-amount').classList.toggle('active',t=='amount');
  document.getElementById('panel-count').classList.toggle('active',t=='count');
  renderTable();
}}

function filterAmt(t){{
  amtFilter=t;
  document.querySelectorAll('#amt-tier-tabs .tier-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  renderTable();
}}
function filterCnt(t){{
  cntFilter=t;
  document.querySelectorAll('#cnt-tier-tabs .tier-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  renderTable();
}}

function sortTable(tab, key){{
  if(tab==='amount'){{
    if(amtSort.key===key) amtSort.dir*=-1; else amtSort={{key,dir:-1}};
  }} else {{
    if(cntSort.key===key) cntSort.dir*=-1; else cntSort={{key,dir:-1}};
  }}
  document.querySelectorAll(`#${{tab==='amount'?'amt':'cnt'}}-table thead th`).forEach(th=>{{
    th.classList.remove('sorted-asc','sorted-desc');
  }});
  renderTable();
}}

function renderTable(){{
  renderAmt(); renderCnt();
}}

function getFiltered(tier_key, tier_val, search_id){{
  const q = document.getElementById(search_id)?.value.toLowerCase()||'';
  return ALL_DATA.filter(c=>{{
    if(tier_val!=='all' && c[tier_key]!==tier_val) return false;
    if(q) return (c.name||'').toLowerCase().includes(q)||
                 (c.phone||'').includes(q)||
                 (c.email||'').toLowerCase().includes(q);
    return true;
  }});
}}

function renderAmt(){{
  let data = getFiltered('amount_tier', amtFilter, 'amt-search');
  data.sort((a,b)=>{{
    let va=a[amtSort.key]||0, vb=b[amtSort.key]||0;
    if(typeof va==='string') return amtSort.dir*(va<vb?-1:va>vb?1:0);
    return amtSort.dir*(va-vb);
  }});
  document.getElementById('amt-count').textContent = `${{data.length.toLocaleString()}}명`;
  const tb = document.getElementById('amt-tbody');
  if(!data.length){{ tb.innerHTML='<tr><td colspan="9" class="empty">해당하는 고객이 없습니다</td></tr>'; return; }}
  tb.innerHTML = data.map((c,i)=>`
    <tr>
      <td class="rank">${{i+1}}</td>
      <td>${{c.name||'<span style="color:#475569">-</span>'}}</td>
      <td class="phone">${{fmtPhone(c.phone)}}</td>
      <td class="email">${{c.email||'-'}}</td>
      <td class="amount">${{fmt(c.total_amount)}}</td>
      <td class="cnt">${{c.order_count}}회</td>
      <td class="date">${{c.first_order||'-'}}</td>
      <td class="date">${{c.last_order||'-'}}</td>
      <td><span class="tier-chip ${{CHIP[c.amount_tier]||''}}">${{c.amount_tier}}</span></td>
    </tr>`).join('');
}}

function renderCnt(){{
  let data = getFiltered('count_tier', cntFilter, 'cnt-search');
  data.sort((a,b)=>{{
    let va=a[cntSort.key]||0, vb=b[cntSort.key]||0;
    if(typeof va==='string') return cntSort.dir*(va<vb?-1:va>vb?1:0);
    return cntSort.dir*(va-vb);
  }});
  document.getElementById('cnt-count').textContent = `${{data.length.toLocaleString()}}명`;
  const tb = document.getElementById('cnt-tbody');
  if(!data.length){{ tb.innerHTML='<tr><td colspan="9" class="empty">해당하는 고객이 없습니다</td></tr>'; return; }}
  tb.innerHTML = data.map((c,i)=>`
    <tr>
      <td class="rank">${{i+1}}</td>
      <td>${{c.name||'<span style="color:#475569">-</span>'}}</td>
      <td class="phone">${{fmtPhone(c.phone)}}</td>
      <td class="email">${{c.email||'-'}}</td>
      <td class="cnt">${{c.order_count}}회</td>
      <td class="amount">${{fmt(c.total_amount)}}</td>
      <td class="date">${{c.first_order||'-'}}</td>
      <td class="date">${{c.last_order||'-'}}</td>
      <td><span class="tier-chip ${{CHIP[c.count_tier]||''}}">${{c.count_tier}}</span></td>
    </tr>`).join('');
}}

function exportCSV(tab){{
  const isAmt = tab==='amount';
  let data = getFiltered(
    isAmt?'amount_tier':'count_tier',
    isAmt?amtFilter:cntFilter,
    isAmt?'amt-search':'cnt-search'
  );
  const header = '이름,전화번호,이메일,누적금액(원),구매횟수,첫구매일,최근구매일,구간';
  const rows = data.map(c=>[
    c.name||'', c.phone||'', c.email||'',
    c.total_amount, c.order_count,
    c.first_order||'', c.last_order||'',
    isAmt?c.amount_tier:c.count_tier
  ].join(','));
  const csv = '\\uFEFF' + header + '\\n' + rows.join('\\n');
  const a = document.createElement('a');
  a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
  a.download = `ACHRO_고객분석_${{tab}}_${{new Date().toISOString().slice(0,10)}}.csv`;
  a.click();
}}

renderTable();
</script>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"  HTML 생성: {OUT_HTML}")

# ── 메인 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 58)
    print("  ACHRO 아임웹 고객 분석")
    print("=" * 58)

    print("\n[1] API 인증 중...")
    try:
        token = get_token()
        print("  인증 성공!")
    except Exception as e:
        print(f"  [ERROR] {e}")
        sys.exit(1)

    print("\n[2] 주문 데이터 수집 중...")
    orders = fetch_all_orders(token)

    print(f"\n[3] 고객 집계 중...")
    customers = analyze_customers(orders)
    print(f"  유효 고객: {len(customers):,}명")

    paid = sum(1 for o in orders if o.get("payment",{}).get("payment_time",0) > 0)
    print(f"  결제완료 주문: {paid:,}건 / 전체: {len(orders):,}건")

    print(f"\n[4] DB 저장 중...")
    save_to_db(customers)

    print(f"\n[5] HTML 리포트 생성 중...")
    generate_html(customers)

    # 구간별 요약 출력
    print("\n" + "=" * 58)
    print("  누적금액별 고객 분포")
    print("=" * 58)
    tiers = ["10만원미만","10-20만원","20-30만원","30-40만원","40만원이상"]
    for t in tiers:
        n = sum(1 for c in customers if c["amount_tier"] == t)
        bar = "#" * int(n / max(1, len(customers)) * 40)
        print(f"  {t:10s}: {n:5,}명  {bar}")

    print("\n" + "=" * 58)
    print("  반복 구매횟수별 고객 분포")
    print("=" * 58)
    ctiers = ["1회","2회","3회","4-5회","6회이상"]
    for t in ctiers:
        n = sum(1 for c in customers if c["count_tier"] == t)
        bar = "#" * int(n / max(1, len(customers)) * 40)
        print(f"  {t:8s}: {n:5,}명  {bar}")

    print(f"\n완료! 브라우저에서 열기: customers.html\n")
