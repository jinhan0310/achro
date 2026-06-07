"""
아크로 쇼핑몰 상품별 판매 분석
여러 플랫폼 엑셀 → SQLite 저장 + TOP 상품 리포트

파일 형식 자동 감지:
  - 아임웹 XLSX (38컬럼): 주문번호=col[1], 상품명=col[17], 수량=col[16], 주문일=col[36]
  - 이전 플랫폼 XLS  (59컬럼): 주문번호=col[0], 상품명=col[19], 수량=col[22], 주문일=col[14]
"""
import sys
import re
import sqlite3
import pandas as pd
from pathlib import Path

FILES = [
    r"C:\Users\user\Downloads\기본_양식_20260607203037.xlsx",   # 아임웹 (2024.07~)
    r"C:\Users\user\Downloads\모든 상태 주문_KR (3).xls",       # 이전 플랫폼 (2022.07~2024.07)
    # 추가 파일은 여기에 계속 넣으면 됩니다
]
DB = Path(__file__).parent / "jarvis" / "jarvis.db"


# ── 파일 형식별 파서 ─────────────────────────────────────────────

def parse_imweb(path: str) -> pd.DataFrame:
    """아임웹 XLSX (38컬럼 기준)"""
    df = pd.read_excel(path, dtype=str)
    cols = list(df.columns)
    out = pd.DataFrame({
        "주문번호": df[cols[1]],
        "주문일":   df[cols[36]],
        "상품명":   df[cols[17]],
        "옵션명":   df[cols[18]],
        "수량":     df[cols[16]],
        "판매가":   df[cols[19]],
        "주문상태": df[cols[2]],
    })
    return out


def parse_legacy(path: str) -> pd.DataFrame:
    """이전 플랫폼 XLS (59컬럼 기준)
    날짜 컬럼은 dtype=str 없이 읽어야 엑셀 직렬값 오파싱을 막는다.
    """
    # 날짜를 제대로 읽기 위해 dtype 지정 없이 로드
    df = pd.read_excel(path, engine="xlrd",
                       engine_kwargs={"ignore_workbook_corruption": True})
    cols = list(df.columns)
    out = pd.DataFrame({
        "주문번호": df[cols[0]].astype(str),
        "주문일":   pd.to_datetime(df[cols[14]], errors="coerce"),
        "상품명":   df[cols[19]].astype(str),
        "옵션명":   df[cols[20]].astype(str),
        "수량":     pd.to_numeric(df[cols[22]], errors="coerce").fillna(1),
        "판매가":   pd.to_numeric(df[cols[21]], errors="coerce").fillna(0),
        "주문상태": df[cols[13]].astype(str),
    })
    return out


def load_file(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        print(f"  [SKIP] 파일 없음: {p.name}")
        return None
    print(f"  로딩: {p.name} ...", end=" ")
    # 컬럼 수로 형식 자동 감지
    probe = pd.read_excel(path, nrows=1, dtype=str,
                          engine=("xlrd" if path.endswith(".xls") else None),
                          engine_kwargs=({"ignore_workbook_corruption": True}
                                         if path.endswith(".xls") else {}))
    n_cols = len(probe.columns)
    if n_cols >= 55:       # 이전 플랫폼 (59컬럼)
        df = parse_legacy(path)
        fmt = "이전플랫폼"
    else:                  # 아임웹 (38컬럼)
        df = parse_imweb(path)
        fmt = "아임웹"
    print(f"{len(df):,}행 [{fmt}]")
    return df


# ── 1. 로드 & 병합 ──────────────────────────────────────────────
print("=" * 55)
print("  아크로 판매 데이터 로드")
print("=" * 55)
frames = [df for f in FILES if (df := load_file(f)) is not None]

if not frames:
    print("[ERR] 로드할 파일이 없습니다.")
    sys.exit(1)

df = pd.concat(frames, ignore_index=True)
print(f"\n  병합 합계: {len(df):,}행")


# ── 2. 타입 변환 & 정제 ─────────────────────────────────────────
df["주문일"] = pd.to_datetime(df["주문일"], errors="coerce")
df["수량"]   = pd.to_numeric(df["수량"], errors="coerce").fillna(1).astype(int)
df["판매가"] = pd.to_numeric(df["판매가"], errors="coerce").fillna(0).astype(int)
df["상품명"] = df["상품명"].str.strip()
df["연도"]   = df["주문일"].dt.year
df["월"]     = df["주문일"].dt.month
df["연월"]   = df["주문일"].dt.to_period("M").astype(str)

# 상품코드 추출 (예: [ACH261BO127])
def extract_code(name):
    m = re.search(r'\[([A-Z]{2,}[\d\w]*)\]', str(name))
    return m.group(1) if m else ""

df["상품코드"] = df["상품명"].apply(extract_code)

# 유효 행만 (주문일+상품명 필수)
df = df.dropna(subset=["주문일", "상품명"]).copy()

# 중복 제거: 같은 주문번호+상품명+옵션이 두 파일에 겹칠 경우
before = len(df)
df = df.drop_duplicates(subset=["주문번호", "상품명", "옵션명"])
dedup = before - len(df)

print(f"  유효: {len(df):,}행 (중복 제거 {dedup:,}건)")
print(f"  기간: {df['주문일'].min().date()} ~ {df['주문일'].max().date()}")
print(f"  연도: {sorted(df['연도'].dropna().astype(int).unique().tolist())}")


# ── 3. 분석 출력 ────────────────────────────────────────────────
print("\n" + "=" * 55)
print("  전체 기간 TOP 30 (판매수량 기준)")
print("=" * 55)
top = (
    df.groupby("상품명")
    .agg(총수량=("수량", "sum"),
         주문건=("주문번호", "nunique"),
         총매출=("판매가", lambda x: (x * df.loc[x.index, "수량"]).sum()))
    .sort_values("총수량", ascending=False)
    .head(30)
)
for i, (name, row) in enumerate(top.iterrows(), 1):
    short = name[:52] + "..." if len(name) > 52 else name
    print(f"  {i:2d}. {short}")
    print(f"      {row['총수량']:,}개 / {row['주문건']:,}건 / {row['총매출']:,.0f}원")

print("\n" + "=" * 55)
print("  연도별 TOP 10")
print("=" * 55)
for year in sorted(df["연도"].dropna().astype(int).unique()):
    sub = df[df["연도"] == year]
    yt = sub.groupby("상품명")["수량"].sum().sort_values(ascending=False).head(10)
    print(f"\n  [{year}년] 주문 {sub['주문번호'].nunique():,}건")
    for i, (name, qty) in enumerate(yt.items(), 1):
        short = name[:48] + "..." if len(name) > 48 else name
        print(f"    {i:2d}. {short} [{qty:,}개]")

print("\n" + "=" * 55)
print("  월별 판매수량 트렌드")
print("=" * 55)
monthly = df.groupby(["연도", "월"])["수량"].sum().reset_index()
for year in sorted(df["연도"].dropna().astype(int).unique()):
    sub = monthly[monthly["연도"] == year]
    parts = " | ".join(f"{int(r['월']):02d}월:{int(r['수량']):,}"
                       for _, r in sub.iterrows())
    print(f"  {year}년: {parts}")


# ── 4. SQLite 저장 ──────────────────────────────────────────────
print("\nDB 저장 중...")
conn = sqlite3.connect(DB)
conn.execute("DROP TABLE IF EXISTS product_sales")
conn.execute("""
CREATE TABLE product_sales (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no     TEXT,
    order_date   TEXT,
    year         INTEGER,
    month        INTEGER,
    yearmonth    TEXT,
    product      TEXT,
    product_code TEXT,
    option_name  TEXT,
    qty          INTEGER,
    price        INTEGER,
    status       TEXT
)
""")

records = [
    (
        r["주문번호"],
        str(r["주문일"].date()) if pd.notnull(r["주문일"]) else None,
        int(r["연도"]) if pd.notnull(r["연도"]) else None,
        int(r["월"])   if pd.notnull(r["월"])   else None,
        r["연월"], r["상품명"], r["상품코드"],
        str(r.get("옵션명", "") or ""),
        int(r["수량"]), int(r["판매가"]),
        str(r.get("주문상태", "") or ""),
    )
    for _, r in df.iterrows()
]

conn.executemany(
    """INSERT INTO product_sales
       (order_no,order_date,year,month,yearmonth,product,product_code,
        option_name,qty,price,status)
       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
    records,
)
conn.commit()
saved = conn.execute("SELECT COUNT(*) FROM product_sales").fetchone()[0]
print(f"  저장 완료: {saved:,}행 → jarvis/jarvis.db")
conn.close()
print("\n완료!")
