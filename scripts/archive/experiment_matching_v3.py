"""
MFDS ↔ HIRA 매칭 실험 v3
품목기준코드 경유 매칭
"""
import json
import csv
from pathlib import Path
from collections import defaultdict, Counter
import re

DATA_DIR = Path("C:/Jimin/RegScan/data")
BRIDGE_DIR = DATA_DIR / "bridge"

def load_csv(path: Path) -> list[dict]:
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
print("MFDS ↔ HIRA 매칭 실험 v3: 품목기준코드 경유")
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

# === 2. 브릿지 테이블 구축 ===
print("\n[2] 브릿지 테이블 구축")

# 2.1 약가마스터: 품목기준코드 → 일반명코드
permit_to_ingredient = {}
for row in yakga_master:
    permit_code = row.get("품목기준코드", "").strip()
    ingredient_code = row.get("일반명코드(성분명코드)", "").strip()
    if permit_code and ingredient_code:
        permit_to_ingredient[permit_code] = ingredient_code

print(f"  품목기준코드 → 일반명코드: {len(permit_to_ingredient):,}건")

# 2.2 ATC 매핑: INN → 주성분코드
inn_to_code = {}
for row in atc_mapping:
    inn = row.get("ATC코드 명칭", "").strip().lower()
    code = row.get("주성분코드", "").strip()
    if inn and code:
        inn_to_code[inn] = code

print(f"  INN → 주성분코드: {len(inn_to_code):,}건")

# 2.3 HIRA: 의성분코드 → 급여정보
hira_by_code = defaultdict(list)
for row in hira_data:
    code = row.get("ingredient_code", "").strip()
    if code:
        hira_by_code[code].append(row)

print(f"  HIRA 의성분코드 인덱스: {len(hira_by_code):,}개")

# === 3. MFDS → HIRA 매칭 (품목기준코드 경유) ===
print("\n[3] MFDS → HIRA 매칭 (품목기준코드 경유)")

matched_permit = 0
matched_hira = 0
no_permit_match = 0
no_ingredient = 0
no_hira = 0

results = []

for mfds in mfds_data:
    item_seq = str(mfds.get("ITEM_SEQ", "")).strip()
    item_name = mfds.get("ITEM_NAME", "")
    inn = mfds.get("ITEM_INGR_NAME", "")

    result = {
        "item_seq": item_seq,
        "item_name": item_name,
        "inn": inn,
        "ingredient_code": None,
        "hira_status": None,
        "match_path": None
    }

    # Path A: 품목기준코드 경유
    ingredient_code = permit_to_ingredient.get(item_seq)
    if ingredient_code:
        matched_permit += 1
        result["ingredient_code"] = ingredient_code
        result["match_path"] = "permit_code"

        if ingredient_code in hira_by_code:
            matched_hira += 1
            hira_info = hira_by_code[ingredient_code][0]
            result["hira_status"] = hira_info.get("reimbursement_type")
        else:
            no_hira += 1
    else:
        no_permit_match += 1

        # Path B: INN 경유 (fallback)
        if inn:
            inn_lower = inn.lower().split("/")[0].split(";")[0].strip()
            code = inn_to_code.get(inn_lower)
            if code:
                result["ingredient_code"] = code
                result["match_path"] = "inn"
                if code in hira_by_code:
                    matched_hira += 1
                    hira_info = hira_by_code[code][0]
                    result["hira_status"] = hira_info.get("reimbursement_type")

    results.append(result)

print(f"\n  매칭 결과:")
print(f"    품목기준코드 매칭: {matched_permit:,}건 ({matched_permit/len(mfds_data)*100:.1f}%)")
print(f"    HIRA 급여정보 연결: {matched_hira:,}건 ({matched_hira/len(mfds_data)*100:.1f}%)")
print(f"    품목기준코드 미매칭: {no_permit_match:,}건")

# === 4. 급여 현황 분석 ===
print("\n[4] 급여 현황 분석")

status_counts = Counter()
for r in results:
    status = r.get("hira_status") or "미연결"
    status_counts[status] += 1

print(f"  급여 상태 분포:")
for status, count in status_counts.most_common():
    print(f"    {status}: {count:,}건 ({count/len(results)*100:.1f}%)")

# === 5. INN 매칭 테스트 (글로벌 약물용) ===
print("\n[5] INN 직접 매칭 테스트")

def normalize_inn(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    salts = ['hydrochloride', 'hcl', 'sodium', 'potassium', 'sulfate',
             'acetate', 'maleate', 'fumarate', 'citrate', 'tartrate']
    for salt in salts:
        name = name.replace(salt, '')
    name = re.sub(r'[^a-z]', '', name)
    return name

# 테스트 약물 (글로벌 핵심 약물)
test_drugs = [
    "pembrolizumab",
    "nivolumab",
    "semaglutide",
    "adalimumab",
    "trastuzumab",
    "bevacizumab",
    "rituximab",
    "osimertinib",
    "lenvatinib",
    "atezolizumab"
]

print(f"\n  글로벌 핵심 약물 매칭 테스트:")
for drug in test_drugs:
    code = inn_to_code.get(drug)
    if code:
        hira_status = "급여" if code in hira_by_code else "미등재"
        print(f"    {drug}: {code} → {hira_status}")
    else:
        # 정규화 후 재시도
        normalized = normalize_inn(drug)
        for inn, c in inn_to_code.items():
            if normalize_inn(inn) == normalized:
                code = c
                break
        if code:
            hira_status = "급여" if code in hira_by_code else "미등재"
            print(f"    {drug}: {code} → {hira_status} (정규화)")
        else:
            print(f"    {drug}: 미매칭")

# === 6. 커버리지 분석 ===
print("\n[6] 커버리지 분석")

# MFDS 기준
mfds_with_hira = sum(1 for r in results if r.get("hira_status"))
print(f"  MFDS → HIRA 연결률: {mfds_with_hira:,}/{len(mfds_data):,} ({mfds_with_hira/len(mfds_data)*100:.1f}%)")

# 의성분코드 기준
yakga_ingredient_codes = set(permit_to_ingredient.values())
atc_ingredient_codes = set(inn_to_code.values())
combined_codes = yakga_ingredient_codes | atc_ingredient_codes
hira_codes = set(hira_by_code.keys())

print(f"\n  의성분코드 커버리지:")
print(f"    약가마스터 제공: {len(yakga_ingredient_codes):,}개")
print(f"    ATC 매핑 제공: {len(atc_ingredient_codes):,}개")
print(f"    합집합: {len(combined_codes):,}개")
print(f"    HIRA 전체: {len(hira_codes):,}개")
print(f"    커버리지: {len(combined_codes & hira_codes):,}/{len(hira_codes):,} ({len(combined_codes & hira_codes)/len(hira_codes)*100:.1f}%)")

# === 7. 샘플 출력 ===
print("\n[7] 매칭 샘플 (상위 10건)")
for i, r in enumerate(results[:10]):
    print(f"\n  [{i+1}] {r['item_name'][:30]}...")
    print(f"      ITEM_SEQ: {r['item_seq']}")
    print(f"      INN: {r['inn']}")
    print(f"      의성분코드: {r['ingredient_code']}")
    print(f"      급여상태: {r['hira_status']}")
    print(f"      매칭경로: {r['match_path']}")

# === 8. 결과 저장 ===
print("\n[8] 결과 저장")

# 매칭 결과 저장
output_path = DATA_DIR / "matching_results_20260204.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"  저장됨: {output_path}")

# === 9. 종합 결론 ===
print("\n" + "=" * 70)
print("[종합 결론]")
print("=" * 70)
print(f"""
1. MFDS → HIRA 매칭 성공률: {mfds_with_hira/len(mfds_data)*100:.1f}%
   - 품목기준코드 경유: {matched_permit:,}건
   - INN 경유 추가: {matched_hira - matched_permit:,}건 (있는 경우)

2. 의성분코드 커버리지:
   - 브릿지 테이블 합집합: {len(combined_codes):,}개
   - HIRA 대비: {len(combined_codes & hira_codes)/len(hira_codes)*100:.1f}%

3. 급여 현황:
   - 급여: {status_counts.get('급여', 0):,}건
   - 비급여: {status_counts.get('비급여', 0):,}건
   - 미연결: {status_counts.get('미연결', 0):,}건

4. 개선 방안:
   - 약가마스터 일반명코드 빈 값 채우기 (55.4% 비어있음)
   - INN 정규화 로직 고도화 (염 형태, 조합제 처리)
   - MFDS 품목기준코드 최신화
""")
