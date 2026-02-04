"""
MFDS ↔ HIRA 매칭 실험 v2
약가마스터 상세 분석 및 매칭 전략 재검토
"""
import json
import csv
from pathlib import Path
from collections import defaultdict, Counter
import re

# 경로 설정
DATA_DIR = Path("C:/Jimin/RegScan/data")
BRIDGE_DIR = DATA_DIR / "bridge"

def load_csv(path: Path) -> list[dict]:
    """CSV 로드 (cp949)"""
    rows = []
    with open(path, "r", encoding="cp949", errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def load_json(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

print("=" * 70)
print("MFDS ↔ HIRA 매칭 실험 v2")
print("=" * 70)

# === 1. 데이터 로드 ===
print("\n[1] 데이터 로드")
yakga_master = load_csv(BRIDGE_DIR / "yakga_master_latest.csv")
atc_mapping = load_csv(BRIDGE_DIR / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv")
hira_data = load_json(DATA_DIR / "hira" / "drug_prices_20260204.json")
mfds_data = load_json(DATA_DIR / "mfds" / "permits_full_20260203.json")

print(f"  약가마스터: {len(yakga_master):,}건")
print(f"  ATC 매핑: {len(atc_mapping):,}건")
print(f"  HIRA 적용약가: {len(hira_data):,}건")
print(f"  MFDS 허가정보: {len(mfds_data):,}건")

# === 2. 약가마스터 상세 분석 ===
print("\n[2] 약가마스터 상세 분석")

# 컬럼명 확인
cols = list(yakga_master[0].keys())
print(f"  전체 컬럼 ({len(cols)}개):")
for i, col in enumerate(cols):
    print(f"    {i+1}. {col}")

# 핵심 컬럼 식별
# 일반명코드(성분명코드), 제품코드(보험코드), 국제표준코드(ATC코드)
ingredient_col = None
product_col = None
atc_col = None
name_col = None

for col in cols:
    if "일반명코드" in col or "성분명코드" in col:
        ingredient_col = col
    if "제품코드" in col and "보험" in col:
        product_col = col
    if "ATC" in col:
        atc_col = col
    if "한글" in col and "성분" in col:
        name_col = col

print(f"\n  핵심 컬럼 매핑:")
print(f"    일반명코드(성분명코드): {ingredient_col}")
print(f"    제품코드(보험코드): {product_col}")
print(f"    국제표준코드(ATC코드): {atc_col}")
print(f"    한글성분명: {name_col}")

# 일반명코드 현황
ingredient_codes = []
empty_count = 0
for row in yakga_master:
    code = row.get(ingredient_col, "").strip() if ingredient_col else ""
    if code:
        ingredient_codes.append(code)
    else:
        empty_count += 1

print(f"\n  일반명코드 현황:")
print(f"    채워진 행: {len(ingredient_codes):,}건")
print(f"    비어있는 행: {empty_count:,}건 ({empty_count/len(yakga_master)*100:.1f}%)")
print(f"    고유 코드: {len(set(ingredient_codes)):,}개")

# === 3. 대체 키 탐색 ===
print("\n[3] 대체 키 탐색")

# 제품코드(보험코드) 분석
if product_col:
    product_codes = [row.get(product_col, "").strip() for row in yakga_master if row.get(product_col, "").strip()]
    print(f"  제품코드(보험코드): {len(set(product_codes)):,}개 고유값")
    if product_codes:
        print(f"    샘플: {product_codes[:3]}")

# 품목허가코드 분석
permit_col = None
for col in cols:
    if "품목" in col and "코드" in col:
        permit_col = col
        break

if permit_col:
    permit_codes = [row.get(permit_col, "").strip() for row in yakga_master if row.get(permit_col, "").strip()]
    print(f"  {permit_col}: {len(set(permit_codes)):,}개 고유값")
    if permit_codes:
        print(f"    샘플: {permit_codes[:3]}")

# 대표코드 분석
rep_col = None
for col in cols:
    if "대표코드" in col:
        rep_col = col
        break

if rep_col:
    rep_codes = [row.get(rep_col, "").strip() for row in yakga_master if row.get(rep_col, "").strip()]
    print(f"  {rep_col}: {len(set(rep_codes)):,}개 고유값")
    if rep_codes:
        print(f"    샘플: {rep_codes[:3]}")

# === 4. HIRA 의성분코드 형식 분석 ===
print("\n[4] HIRA 의성분코드 형식 분석")

hira_codes = [row.get("ingredient_code", "").strip() for row in hira_data if row.get("ingredient_code", "")]
print(f"  HIRA 고유 의성분코드: {len(set(hira_codes)):,}개")
print(f"  샘플:")
for code in list(set(hira_codes))[:5]:
    print(f"    {code}")

# 코드 길이 분포
code_lengths = Counter(len(c) for c in set(hira_codes))
print(f"  코드 길이 분포: {dict(code_lengths)}")

# === 5. ATC 매핑 분석 ===
print("\n[5] ATC 매핑 상세 분석")

atc_cols = list(atc_mapping[0].keys())
print(f"  컬럼: {atc_cols}")

# 주성분코드 현황
atc_ingredient_col = None
for col in atc_cols:
    if "주성분코드" in col:
        atc_ingredient_col = col
        break

if atc_ingredient_col:
    atc_ingredients = [row.get(atc_ingredient_col, "").strip() for row in atc_mapping if row.get(atc_ingredient_col, "")]
    print(f"  주성분코드: {len(set(atc_ingredients)):,}개 고유값")
    print(f"  샘플:")
    for code in list(set(atc_ingredients))[:5]:
        print(f"    {code}")

# 주성분코드 길이 분포
atc_lengths = Counter(len(c) for c in set(atc_ingredients))
print(f"  코드 길이 분포: {dict(atc_lengths)}")

# === 6. 코드 매칭 테스트 ===
print("\n[6] 코드 매칭 테스트")

hira_set = set(hira_codes)
atc_set = set(atc_ingredients) if atc_ingredient_col else set()

# 약가마스터 일반명코드 vs HIRA
yakga_ingredient_set = set(ingredient_codes)
match_yakga_hira = yakga_ingredient_set & hira_set
print(f"  약가마스터 일반명코드 ∩ HIRA: {len(match_yakga_hira):,}개")

# ATC 주성분코드 vs HIRA
match_atc_hira = atc_set & hira_set
print(f"  ATC 주성분코드 ∩ HIRA: {len(match_atc_hira):,}개")

# 약가마스터 일반명코드 vs ATC 주성분코드
match_yakga_atc = yakga_ingredient_set & atc_set
print(f"  약가마스터 일반명코드 ∩ ATC: {len(match_yakga_atc):,}개")

# === 7. 한글성분명 매핑 시도 ===
print("\n[7] 성분명 기반 매핑")

# 약가마스터 성분명 → 일반명코드 매핑
if name_col:
    name_to_code = defaultdict(set)
    for row in yakga_master:
        name = row.get(name_col, "").strip()
        code = row.get(ingredient_col, "").strip() if ingredient_col else ""
        if name and code:
            name_to_code[name.lower()].add(code)

    print(f"  약가마스터 한글성분명 → 일반명코드 매핑: {len(name_to_code):,}개")
    print(f"  샘플:")
    for name, codes in list(name_to_code.items())[:3]:
        print(f"    {name} → {codes}")

# 대표성분명일반기준 분석
gen_name_col = None
for col in cols:
    if "일반" in col and "기준" in col:
        gen_name_col = col
        break

if gen_name_col:
    gen_names = [row.get(gen_name_col, "").strip() for row in yakga_master if row.get(gen_name_col, "").strip()]
    print(f"\n  {gen_name_col}: {len(set(gen_names)):,}개 고유값")
    print(f"  샘플: {list(set(gen_names))[:5]}")

# === 8. 종합 분석 및 전략 ===
print("\n" + "=" * 70)
print("[결론] 매칭 전략 재검토")
print("=" * 70)

print("""
1. 약가마스터 일반명코드(성분명코드)의 대부분이 비어있음
   - 305,522건 중 빈 값이 많음
   - 채워진 값으로만 HIRA 67.4% 커버리지

2. 핵심 발견:
   - HIRA 의성분코드 형식: 8자리 (예: 130830ASY, 149203ATB)
   - ATC 매핑 주성분코드: 동일 형식
   - 약가마스터 일반명코드: 비어있는 경우 많음

3. 대안 전략:
   - 품목허가코드 → MFDS ITEM_SEQ 매칭 시도
   - 대표코드(KD코드) 활용
   - ATC 매핑을 주 브릿지로, 약가마스터는 보조로 활용
""")

# === 9. MFDS ITEM_SEQ 형식 확인 ===
print("\n[8] MFDS ITEM_SEQ 형식 확인")
mfds_seqs = [row.get("ITEM_SEQ", "") for row in mfds_data if row.get("ITEM_SEQ")]
print(f"  MFDS ITEM_SEQ 샘플: {mfds_seqs[:5]}")
print(f"  MFDS ITEM_SEQ 길이 분포: {Counter(len(str(s)) for s in mfds_seqs[:1000])}")

# 품목허가코드와 MFDS ITEM_SEQ 비교
if permit_col:
    yakga_permits = set(row.get(permit_col, "").strip() for row in yakga_master if row.get(permit_col, "").strip())
    mfds_seq_set = set(str(s) for s in mfds_seqs)

    match = yakga_permits & mfds_seq_set
    print(f"\n  약가마스터 품목허가코드 ∩ MFDS ITEM_SEQ: {len(match):,}개")

    # 공백 제거 후 재시도
    yakga_permits_clean = set(p.replace(" ", "") for p in yakga_permits)
    match_clean = yakga_permits_clean & mfds_seq_set
    print(f"  (공백 제거 후): {len(match_clean):,}개")

# === 10. 최종 전략 ===
print("\n" + "=" * 70)
print("[최종 전략]")
print("=" * 70)
print("""
Path A: MFDS → HIRA (신규 승인약 급여 확인)
  1. MFDS ITEM_SEQ → 약가마스터 품목허가코드 → 일반명코드 → HIRA
  2. MFDS INN → ATC 매핑 INN → 주성분코드 → HIRA

Path B: 글로벌(FDA/EMA) → HIRA (글로벌 승인약 국내 급여)
  1. INN 정규화 → ATC 매핑 → 주성분코드 → HIRA

브릿지 통합:
  - ATC 매핑 (4,415 주성분코드) + 약가마스터 품목허가코드 활용
  - 커버리지: 67-70% (exact match)
""")
