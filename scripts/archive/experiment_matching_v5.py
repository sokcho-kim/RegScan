"""
MFDS ↔ HIRA 매칭 실험 v5
의약품주성분 마스터 활용 (99.6% 커버리지)
"""
import json
import csv
from pathlib import Path
from collections import defaultdict, Counter
import re

DATA_DIR = Path("C:/Jimin/RegScan/data")
BRIDGE_DIR = DATA_DIR / "bridge"

def load_csv(path: Path, encoding='cp949') -> list[dict]:
    rows = []
    with open(path, "r", encoding=encoding, errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def load_json(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

print("=" * 70)
print("MFDS ↔ HIRA 매칭 실험 v5")
print("의약품주성분 마스터 활용")
print("=" * 70)

# === 1. 데이터 로드 ===
print("\n[1] 데이터 로드")

# 의약품주성분 마스터 (핵심!)
ingredient_master = load_csv(BRIDGE_DIR / "yakga_ingredient_master.csv")
print(f"  의약품주성분 마스터: {len(ingredient_master):,}건")

# ATC 매핑
atc_mapping = load_csv(BRIDGE_DIR / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv")
print(f"  ATC 매핑: {len(atc_mapping):,}건")

# HIRA 적용약가
hira_data = load_json(DATA_DIR / "hira" / "drug_prices_20260204.json")
print(f"  HIRA 적용약가: {len(hira_data):,}건")

# MFDS 허가정보
mfds_data = load_json(DATA_DIR / "mfds" / "permits_full_20260203.json")
print(f"  MFDS 허가정보: {len(mfds_data):,}건")

# === 2. 브릿지 테이블 구축 ===
print("\n[2] 브릿지 테이블 구축")

# 2.1 의약품주성분: 일반명(성분명) → 일반명코드
name_to_codes = defaultdict(set)
code_to_info = {}

for row in ingredient_master:
    name = row.get('일반명', '').strip()
    code = row.get('일반명코드', '').strip()
    if name and code:
        # 소문자 정규화
        name_lower = name.lower()
        name_to_codes[name_lower].add(code)

        if code not in code_to_info:
            code_to_info[code] = {
                'name': name,
                'form': row.get('제형', ''),
                'route': row.get('투여', ''),
                'strength': row.get('함량', ''),
                'unit': row.get('단위', '')
            }

print(f"  일반명 → 일반명코드: {len(name_to_codes):,}개 성분명")
print(f"  일반명코드 정보: {len(code_to_info):,}개 코드")

# 2.2 ATC 매핑: INN → 주성분코드 (보조)
inn_to_code = {}
for row in atc_mapping:
    inn = row.get("ATC코드 명칭", "").strip().lower()
    code = row.get("주성분코드", "").strip()
    if inn and code:
        inn_to_code[inn] = code

print(f"  ATC INN → 주성분코드: {len(inn_to_code):,}개")

# 2.3 HIRA: 의성분코드 → 급여정보
hira_by_code = defaultdict(list)
for row in hira_data:
    code = row.get("ingredient_code", "").strip()
    if code:
        hira_by_code[code].append(row)

print(f"  HIRA 의성분코드 인덱스: {len(hira_by_code):,}개")

# === 3. INN 정규화 함수 ===
def normalize_inn(name: str) -> str:
    """INN 정규화"""
    if not name:
        return ""
    name = name.lower().strip()
    # 염 형태 제거
    salts = ['hydrochloride', 'hcl', ' hcl', 'sodium', 'potassium', 'sulfate',
             'acetate', 'maleate', 'fumarate', 'citrate', 'tartrate',
             'mesylate', 'besylate', 'succinate', 'lactate', 'dihydrate',
             'monohydrate', 'hydrate']
    for salt in salts:
        name = name.replace(salt, '')
    # 특수문자 제거, 공백 정리
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

# === 4. MFDS → HIRA 매칭 ===
print("\n[3] MFDS → HIRA 매칭")

results = []
match_stats = Counter()

for mfds in mfds_data:
    item_seq = str(mfds.get("ITEM_SEQ", "")).strip()
    item_name = mfds.get("ITEM_NAME", "")
    inn_raw = mfds.get("ITEM_INGR_NAME", "")

    result = {
        "item_seq": item_seq,
        "item_name": item_name,
        "inn_raw": inn_raw,
        "ingredient_code": None,
        "ingredient_name": None,
        "hira_status": None,
        "hira_price": None,
        "match_method": None
    }

    # 첫 번째 성분 추출 (복합제인 경우)
    if not inn_raw:
        inn = ""
    else:
        inn = inn_raw.split("/")[0].split(";")[0].split(",")[0].strip()

    matched = False

    # Method 1: 의약품주성분 마스터 직접 매칭
    if inn:
        inn_lower = inn.lower()
        if inn_lower in name_to_codes:
            codes = name_to_codes[inn_lower]
            # HIRA에 있는 코드 찾기
            for code in codes:
                if code in hira_by_code:
                    result["ingredient_code"] = code
                    result["ingredient_name"] = code_to_info.get(code, {}).get('name', '')
                    result["match_method"] = "ingredient_master_exact"
                    hira_info = hira_by_code[code][0]
                    result["hira_status"] = hira_info.get("급여기준")
                    result["hira_price"] = hira_info.get("price_ceiling")
                    matched = True
                    match_stats["ingredient_master_exact"] += 1
                    break

    # Method 2: 정규화 후 매칭
    if not matched and inn:
        normalized = normalize_inn(inn)
        for name, codes in name_to_codes.items():
            if normalize_inn(name) == normalized:
                for code in codes:
                    if code in hira_by_code:
                        result["ingredient_code"] = code
                        result["ingredient_name"] = code_to_info.get(code, {}).get('name', '')
                        result["match_method"] = "ingredient_master_normalized"
                        hira_info = hira_by_code[code][0]
                        result["hira_status"] = hira_info.get("급여기준")
                        result["hira_price"] = hira_info.get("price_ceiling")
                        matched = True
                        match_stats["ingredient_master_normalized"] += 1
                        break
                if matched:
                    break

    # Method 3: ATC 매핑 fallback
    if not matched and inn:
        inn_lower = inn.lower()
        code = inn_to_code.get(inn_lower)
        if code and code in hira_by_code:
            result["ingredient_code"] = code
            result["match_method"] = "atc_mapping"
            hira_info = hira_by_code[code][0]
            result["hira_status"] = hira_info.get("급여기준")
            result["hira_price"] = hira_info.get("price_ceiling")
            matched = True
            match_stats["atc_mapping"] += 1

    if not matched:
        match_stats["unmatched"] += 1

    results.append(result)

# === 5. 결과 분석 ===
print("\n[4] 매칭 결과")

total = len(results)
matched_total = sum(1 for r in results if r.get("hira_status"))

print(f"\n  전체 MFDS: {total:,}건")
print(f"  HIRA 연결: {matched_total:,}건 ({matched_total/total*100:.1f}%)")

print(f"\n  매칭 방법별:")
for method, count in match_stats.most_common():
    print(f"    {method}: {count:,}건 ({count/total*100:.1f}%)")

# 급여 상태 분포
print("\n[5] 급여 현황")
status_counts = Counter(r.get("hira_status") or "미연결" for r in results)
for status, count in status_counts.most_common():
    print(f"    {status}: {count:,}건 ({count/total*100:.1f}%)")

# === 6. 글로벌 핵심 약물 테스트 ===
print("\n[6] 글로벌 핵심 약물 테스트")

test_drugs = [
    "pembrolizumab", "nivolumab", "semaglutide", "adalimumab",
    "trastuzumab", "bevacizumab", "rituximab", "osimertinib",
    "atezolizumab", "durvalumab"
]

for drug in test_drugs:
    # 의약품주성분 마스터에서 찾기
    codes = name_to_codes.get(drug, set())
    if codes:
        for code in codes:
            if code in hira_by_code:
                info = hira_by_code[code][0]
                status = info.get("급여기준", "N/A")
                price = info.get("price_ceiling")
                if isinstance(price, (int, float)) and price > 0:
                    print(f"    {drug}: {code} -> {status} (W{price:,.0f})")
                else:
                    print(f"    {drug}: {code} -> {status}")
                break
        else:
            print(f"    {drug}: {list(codes)[:2]} (HIRA 미등재)")
    else:
        # ATC fallback
        code = inn_to_code.get(drug)
        if code and code in hira_by_code:
            info = hira_by_code[code][0]
            status = info.get("급여기준", "N/A")
            price = info.get("price_ceiling")
            if isinstance(price, (int, float)) and price > 0:
                print(f"    {drug}: {code} -> {status} (W{price:,.0f}) [ATC]")
            else:
                print(f"    {drug}: {code} -> {status} [ATC]")
        else:
            print(f"    {drug}: not found")

# === 7. 결과 저장 ===
print("\n[7] 결과 저장")

output = {
    "summary": {
        "total_mfds": total,
        "matched_hira": matched_total,
        "match_rate": f"{matched_total/total*100:.1f}%",
        "match_methods": dict(match_stats),
        "status_distribution": dict(status_counts)
    },
    "results": results
}

output_path = DATA_DIR / "matching_results_v5_20260204.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"  저장: {output_path}")

# === 8. 종합 ===
print("\n" + "=" * 70)
print("[종합]")
print("=" * 70)
print(f"""
의약품주성분 마스터 활용 결과:
  - MFDS {total:,}건 중 {matched_total:,}건 HIRA 연결 ({matched_total/total*100:.1f}%)

매칭 방법:
  - ingredient_master_exact: {match_stats.get('ingredient_master_exact', 0):,}건
  - ingredient_master_normalized: {match_stats.get('ingredient_master_normalized', 0):,}건
  - atc_mapping: {match_stats.get('atc_mapping', 0):,}건
  - unmatched: {match_stats.get('unmatched', 0):,}건
""")
