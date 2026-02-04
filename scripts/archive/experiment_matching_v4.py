"""
MFDS ↔ HIRA 매칭 실험 v4
수정된 필드명으로 매칭
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
print("MFDS ↔ HIRA 매칭 실험 v4")
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

# 2.3 HIRA: 의성분코드 → 급여정보 (급여기준 필드 사용)
hira_by_code = defaultdict(list)
for row in hira_data:
    code = row.get("ingredient_code", "").strip()
    if code:
        hira_by_code[code].append(row)

print(f"  HIRA 의성분코드 인덱스: {len(hira_by_code):,}개")

# === 3. MFDS → HIRA 매칭 ===
print("\n[3] MFDS → HIRA 매칭")

matched_permit = 0
matched_hira = 0
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
        "hira_price": None,
        "match_path": None
    }

    # Path A: 품목기준코드 → 일반명코드 → HIRA
    ingredient_code = permit_to_ingredient.get(item_seq)
    if ingredient_code:
        matched_permit += 1
        result["ingredient_code"] = ingredient_code
        result["match_path"] = "permit_code"

        if ingredient_code in hira_by_code:
            matched_hira += 1
            hira_info = hira_by_code[ingredient_code][0]
            result["hira_status"] = hira_info.get("급여기준")  # 수정된 필드명
            result["hira_price"] = hira_info.get("price_ceiling")
    else:
        # Path B: INN → 주성분코드 → HIRA (fallback)
        if inn:
            inn_lower = inn.lower().split("/")[0].split(";")[0].strip()
            code = inn_to_code.get(inn_lower)
            if code:
                result["ingredient_code"] = code
                result["match_path"] = "inn"
                if code in hira_by_code:
                    matched_hira += 1
                    hira_info = hira_by_code[code][0]
                    result["hira_status"] = hira_info.get("급여기준")
                    result["hira_price"] = hira_info.get("price_ceiling")

    results.append(result)

print(f"\n  매칭 결과:")
print(f"    품목기준코드 매칭: {matched_permit:,}건 ({matched_permit/len(mfds_data)*100:.1f}%)")
print(f"    HIRA 급여정보 연결: {matched_hira:,}건 ({matched_hira/len(mfds_data)*100:.1f}%)")

# === 4. 급여 현황 분석 ===
print("\n[4] 급여 현황 분석")

status_counts = Counter()
for r in results:
    status = r.get("hira_status") or "미연결"
    status_counts[status] += 1

print(f"  급여 상태 분포:")
for status, count in status_counts.most_common():
    pct = count / len(results) * 100
    print(f"    {status}: {count:,}건 ({pct:.1f}%)")

# === 5. 글로벌 핵심 약물 테스트 ===
print("\n[5] 글로벌 핵심 약물 매칭 테스트")

test_drugs = [
    "pembrolizumab", "nivolumab", "semaglutide", "adalimumab",
    "trastuzumab", "bevacizumab", "rituximab", "osimertinib"
]

for drug in test_drugs:
    code = inn_to_code.get(drug)
    if code and code in hira_by_code:
        info = hira_by_code[code][0]
        status = info.get("급여기준", "N/A")
        price = info.get("price_ceiling", "N/A")
        if isinstance(price, (int, float)):
            print(f"    {drug}: {code} -> {status} (W{price:,.0f})")
        else:
            print(f"    {drug}: {code} -> {status}")
    else:
        print(f"    {drug}: not matched")

# === 6. 샘플 출력 (매칭 성공 건) ===
print("\n[6] 매칭 성공 샘플 (상위 10건)")
matched_samples = [r for r in results if r.get("hira_status")][:10]
for i, r in enumerate(matched_samples):
    print(f"\n  [{i+1}] {r['item_name'][:40]}...")
    print(f"      ITEM_SEQ: {r['item_seq']}")
    print(f"      INN: {r['inn']}")
    print(f"      의성분코드: {r['ingredient_code']}")
    print(f"      급여상태: {r['hira_status']}")
    print(f"      상한가: {r['hira_price']}")

# === 7. 결과 저장 ===
print("\n[7] 결과 저장")
output = {
    "summary": {
        "total_mfds": len(mfds_data),
        "matched_permit": matched_permit,
        "matched_hira": matched_hira,
        "match_rate_permit": f"{matched_permit/len(mfds_data)*100:.1f}%",
        "match_rate_hira": f"{matched_hira/len(mfds_data)*100:.1f}%",
        "status_counts": dict(status_counts)
    },
    "results": results
}
output_path = DATA_DIR / "matching_results_v4_20260204.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"  저장됨: {output_path}")

# === 8. 종합 결론 ===
print("\n" + "=" * 70)
print("[종합 결론]")
print("=" * 70)
print(f"""
MFDS → HIRA 매칭 결과:
  - 품목기준코드 매칭: {matched_permit:,}건 ({matched_permit/len(mfds_data)*100:.1f}%)
  - HIRA 급여 연결: {matched_hira:,}건 ({matched_hira/len(mfds_data)*100:.1f}%)

급여 현황:""")
for status, count in status_counts.most_common():
    print(f"  - {status}: {count:,}건")

print("""
한계점:
  - 약가마스터 일반명코드 약 55% 미채움 → 매칭률 제한
  - 구형 품목기준코드(1950-60년대)는 일반명코드 없음
  - INN fallback은 ATC 매핑 1,382건으로 제한적

개선 방향:
  1. 제품코드(보험코드) 직접 매칭 시도
  2. HIRA 제품코드 ↔ 약가마스터 제품코드 연결
  3. 품목명 기반 보조 매칭 (신뢰도 주의)
""")
