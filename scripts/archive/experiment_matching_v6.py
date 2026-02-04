"""
MFDS ↔ HIRA 매칭 실험 v6
정규화 개선: (as ...) 괄호 제거
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

def normalize_name(name: str) -> str:
    """성분명 정규화 - 괄호/수화물/염 제거"""
    if not name:
        return ""
    # 소문자
    name = name.lower().strip()
    # (as ...) 괄호 부분 제거
    name = re.sub(r'\s*\(as[^)]*\)', '', name)
    name = re.sub(r'\s*\([^)]*\)', '', name)
    # 수화물 형태 제거
    hydrates = ['trihydrate', 'dihydrate', 'monohydrate', 'hydrate',
                'pentahydrate', 'tetrahydrate', 'hemihydrate', 'anhydrous']
    for h in hydrates:
        name = name.replace(h, '')
    # 공백 정리
    name = ' '.join(name.split())
    return name.strip()

print("=" * 70)
print("MFDS ↔ HIRA 매칭 실험 v6")
print("정규화 개선: (as ...) 괄호 제거")
print("=" * 70)

# === 1. 데이터 로드 ===
print("\n[1] 데이터 로드")
ingredient_master = load_csv(BRIDGE_DIR / "yakga_ingredient_master.csv")
atc_mapping = load_csv(BRIDGE_DIR / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv")
hira_data = load_json(DATA_DIR / "hira" / "drug_prices_20260204.json")
mfds_data = load_json(DATA_DIR / "mfds" / "permits_full_20260203.json")

print(f"  의약품주성분 마스터: {len(ingredient_master):,}건")
print(f"  HIRA 적용약가: {len(hira_data):,}건")
print(f"  MFDS 허가정보: {len(mfds_data):,}건")

# === 2. 브릿지 테이블 구축 (정규화 적용) ===
print("\n[2] 브릿지 테이블 구축 (정규화 적용)")

# 정규화된 일반명 → 일반명코드
name_to_codes = defaultdict(set)
code_to_info = {}

for row in ingredient_master:
    name_raw = row.get('일반명', '').strip()
    code = row.get('일반명코드', '').strip()
    if name_raw and code:
        # 정규화
        name_norm = normalize_name(name_raw)
        name_to_codes[name_norm].add(code)

        # 원본도 추가 (소문자만)
        name_lower = name_raw.lower().strip()
        name_to_codes[name_lower].add(code)

        if code not in code_to_info:
            code_to_info[code] = {'name': name_raw}

print(f"  정규화된 일반명 → 일반명코드: {len(name_to_codes):,}개")

# ATC 매핑
inn_to_code = {}
for row in atc_mapping:
    inn = row.get("ATC코드 명칭", "").strip().lower()
    code = row.get("주성분코드", "").strip()
    if inn and code:
        inn_to_code[inn] = code

# HIRA 인덱스
hira_by_code = defaultdict(list)
for row in hira_data:
    code = row.get("ingredient_code", "").strip()
    if code:
        hira_by_code[code].append(row)

print(f"  HIRA 의성분코드 인덱스: {len(hira_by_code):,}개")

# === 3. 매칭 테스트 ===
print("\n[3] 정규화 테스트")
test_cases = [
    "Amlodipine Besylate",
    "Atorvastatin Calcium Trihydrate",
    "Montelukast Sodium",
    "Esomeprazole Magnesium Trihydrate"
]

for test in test_cases:
    norm = normalize_name(test)
    codes = name_to_codes.get(norm, set())
    hira_codes = [c for c in codes if c in hira_by_code]
    print(f"  {test}")
    print(f"    → 정규화: '{norm}'")
    print(f"    → 코드: {len(codes)}개, HIRA: {len(hira_codes)}개")

# === 4. 전체 매칭 ===
print("\n[4] MFDS → HIRA 매칭")

results = []
match_stats = Counter()

for mfds in mfds_data:
    item_seq = str(mfds.get("ITEM_SEQ", "")).strip()
    item_name = mfds.get("ITEM_NAME", "")
    inn_raw = mfds.get("ITEM_INGR_NAME", "") or ""

    result = {
        "item_seq": item_seq,
        "item_name": item_name,
        "inn_raw": inn_raw,
        "ingredient_code": None,
        "hira_status": None,
        "hira_price": None,
        "match_method": None
    }

    # 첫 번째 성분 추출
    inn = inn_raw.split("/")[0].split(";")[0].split(",")[0].strip() if inn_raw else ""
    matched = False

    if inn:
        # Method 1: 정규화 매칭
        inn_norm = normalize_name(inn)
        if inn_norm in name_to_codes:
            codes = name_to_codes[inn_norm]
            for code in codes:
                if code in hira_by_code:
                    result["ingredient_code"] = code
                    result["match_method"] = "normalized"
                    hira_info = hira_by_code[code][0]
                    result["hira_status"] = hira_info.get("급여기준")
                    result["hira_price"] = hira_info.get("price_ceiling")
                    matched = True
                    match_stats["normalized"] += 1
                    break

        # Method 2: ATC fallback
        if not matched:
            inn_lower = inn.lower()
            code = inn_to_code.get(inn_lower)
            if code and code in hira_by_code:
                result["ingredient_code"] = code
                result["match_method"] = "atc"
                hira_info = hira_by_code[code][0]
                result["hira_status"] = hira_info.get("급여기준")
                result["hira_price"] = hira_info.get("price_ceiling")
                matched = True
                match_stats["atc"] += 1

    if not matched:
        match_stats["unmatched"] += 1

    results.append(result)

# === 5. 결과 ===
print("\n[5] 매칭 결과")
total = len(results)
matched_total = sum(1 for r in results if r.get("hira_status"))

print(f"\n  전체 MFDS: {total:,}건")
print(f"  HIRA 연결: {matched_total:,}건 ({matched_total/total*100:.1f}%)")

print(f"\n  매칭 방법:")
for method, count in match_stats.most_common():
    print(f"    {method}: {count:,}건 ({count/total*100:.1f}%)")

# 급여 상태
print("\n[6] 급여 현황")
status_counts = Counter(r.get("hira_status") or "미연결" for r in results)
for status, count in status_counts.most_common():
    print(f"    {status}: {count:,}건 ({count/total*100:.1f}%)")

# === 6. 결과 저장 ===
output = {
    "summary": {
        "total": total,
        "matched": matched_total,
        "rate": f"{matched_total/total*100:.1f}%",
        "methods": dict(match_stats),
        "status": dict(status_counts)
    },
    "results": results
}

output_path = DATA_DIR / "matching_results_v6_20260204.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n저장: {output_path}")

# === 7. 비교 ===
print("\n" + "=" * 70)
print("[v5 vs v6 비교]")
print("=" * 70)
print(f"""
v5 (기존): 27,618건 / 44,035건 (62.7%)
v6 (개선): {matched_total:,}건 / {total:,}건 ({matched_total/total*100:.1f}%)

개선: +{matched_total - 27618:,}건 (+{(matched_total - 27618)/total*100:.1f}%)
""")
