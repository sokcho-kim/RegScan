"""
MFDS ↔ HIRA 매칭 실험
약가마스터 브릿지를 활용한 의성분코드 기반 매칭
"""
import json
import csv
from pathlib import Path
from collections import defaultdict
import re

# 경로 설정
DATA_DIR = Path("C:/Jimin/RegScan/data")
BRIDGE_DIR = DATA_DIR / "bridge"

def load_json(path: Path) -> list:
    """JSON 파일 로드"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_csv(path: Path) -> list[dict]:
    """CSV 로드 (여러 인코딩 시도)"""
    encodings = ['cp949', 'euc-kr', 'utf-8', 'utf-8-sig']
    for enc in encodings:
        try:
            rows = []
            with open(path, "r", encoding=enc, errors='replace') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            print(f"  로드 성공 ({enc})")
            return rows
        except Exception as e:
            continue
    raise ValueError(f"모든 인코딩 실패: {path}")

# === 1. 데이터 로드 ===
print("=" * 60)
print("1. 데이터 로드")
print("=" * 60)

# 약가마스터
yakga_master_path = BRIDGE_DIR / "yakga_master_latest.csv"
print(f"약가마스터 로드 중...")
yakga_master = load_csv(yakga_master_path)
print(f"약가마스터: {len(yakga_master):,}건")
if yakga_master:
    print(f"  컬럼: {list(yakga_master[0].keys())[:5]}...")

# ATC 매핑
atc_path = BRIDGE_DIR / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"
print(f"ATC 매핑 로드 중...")
atc_mapping = load_csv(atc_path)
print(f"ATC 매핑: {len(atc_mapping):,}건")
if atc_mapping:
    print(f"  컬럼: {list(atc_mapping[0].keys())}")

# HIRA 적용약가
hira_path = DATA_DIR / "hira" / "drug_prices_20260204.json"
hira_data = load_json(hira_path)
print(f"HIRA 적용약가: {len(hira_data):,}건")

# MFDS 허가정보
mfds_path = DATA_DIR / "mfds" / "permits_full_20260203.json"
mfds_data = load_json(mfds_path)
print(f"MFDS 허가정보: {len(mfds_data):,}건")

# === 2. 약가마스터 구조 분석 ===
print("\n" + "=" * 60)
print("2. 약가마스터 구조 분석")
print("=" * 60)

# 샘플 출력
sample = yakga_master[0]
for k, v in sample.items():
    print(f"  {k}: {v}")

# === 3. 브릿지 테이블 구축 ===
print("\n" + "=" * 60)
print("3. 브릿지 테이블 구축")
print("=" * 60)

# 약가마스터에서 일반명코드(성분명코드) 추출
# 컬럼명 확인 후 적절한 키 사용
yakga_columns = list(yakga_master[0].keys())
print(f"약가마스터 전체 컬럼: {yakga_columns}")

# 일반명코드(성분명코드) 컬럼 찾기
ingredient_code_col = None
for col in yakga_columns:
    if "일반명코드" in col or "성분명코드" in col:
        ingredient_code_col = col
        break

# 제품코드(보험코드) 컬럼 찾기
product_code_col = None
for col in yakga_columns:
    if "제품코드" in col and "보험" in col:
        product_code_col = col
        break

# ATC코드 컬럼 찾기
atc_code_col = None
for col in yakga_columns:
    if "ATC" in col and "코드" in col:
        atc_code_col = col
        break

print(f"\n핵심 컬럼:")
print(f"  일반명코드(성분명코드): {ingredient_code_col}")
print(f"  제품코드(보험코드): {product_code_col}")
print(f"  ATC코드: {atc_code_col}")

# === 4. 의성분코드 통계 ===
print("\n" + "=" * 60)
print("4. 의성분코드(일반명코드) 통계")
print("=" * 60)

# 약가마스터에서 고유 의성분코드 추출
yakga_ingredient_codes = set()
for row in yakga_master:
    code = row.get(ingredient_code_col, "").strip()
    if code:
        yakga_ingredient_codes.add(code)
print(f"약가마스터 고유 일반명코드: {len(yakga_ingredient_codes):,}개")

# ATC 매핑에서 고유 주성분코드 추출
atc_columns = list(atc_mapping[0].keys())
print(f"\nATC 매핑 컬럼: {atc_columns}")

atc_ingredient_col = None
for col in atc_columns:
    if "주성분코드" in col:
        atc_ingredient_col = col
        break

atc_ingredient_codes = set()
for row in atc_mapping:
    code = row.get(atc_ingredient_col, "").strip()
    if code:
        atc_ingredient_codes.add(code)
print(f"ATC 매핑 고유 주성분코드: {len(atc_ingredient_codes):,}개")

# HIRA에서 고유 의성분코드 추출
hira_ingredient_codes = set()
for row in hira_data:
    code = row.get("ingredient_code", "").strip()
    if code:
        hira_ingredient_codes.add(code)
print(f"HIRA 적용약가 고유 의성분코드: {len(hira_ingredient_codes):,}개")

# === 5. 커버리지 분석 ===
print("\n" + "=" * 60)
print("5. 커버리지 분석 (HIRA 기준)")
print("=" * 60)

# HIRA ∩ 약가마스터
hira_yakga_intersection = hira_ingredient_codes & yakga_ingredient_codes
print(f"HIRA ∩ 약가마스터: {len(hira_yakga_intersection):,}개 ({len(hira_yakga_intersection)/len(hira_ingredient_codes)*100:.1f}%)")

# HIRA ∩ ATC매핑
hira_atc_intersection = hira_ingredient_codes & atc_ingredient_codes
print(f"HIRA ∩ ATC매핑: {len(hira_atc_intersection):,}개 ({len(hira_atc_intersection)/len(hira_ingredient_codes)*100:.1f}%)")

# HIRA - 약가마스터 (미매칭)
hira_unmatched = hira_ingredient_codes - yakga_ingredient_codes
print(f"HIRA 미매칭 (약가마스터에 없음): {len(hira_unmatched):,}개")

# === 6. MFDS 성분명 분석 ===
print("\n" + "=" * 60)
print("6. MFDS 성분명(INN) 분석")
print("=" * 60)

# MFDS 고유 성분명 추출
mfds_ingredients = set()
for row in mfds_data:
    ingr = row.get("ITEM_INGR_NAME", "")
    if ingr:
        # 복합제 분리 (/, ; 등)
        parts = re.split(r'[/;,]', ingr)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                mfds_ingredients.add(cleaned.lower())
print(f"MFDS 고유 성분명: {len(mfds_ingredients):,}개")

# ATC 매핑에서 INN 추출
atc_inn_col = None
for col in atc_columns:
    if "명칭" in col and "ATC" in col:
        atc_inn_col = col
        break

print(f"ATC INN 컬럼: {atc_inn_col}")

# INN → 주성분코드 매핑 구축
inn_to_code = {}
for row in atc_mapping:
    inn = row.get(atc_inn_col, "").strip().lower()
    code = row.get(atc_ingredient_col, "").strip()
    if inn and code:
        inn_to_code[inn] = code

print(f"INN → 주성분코드 매핑: {len(inn_to_code):,}개")

# === 7. MFDS → HIRA 매칭 테스트 ===
print("\n" + "=" * 60)
print("7. MFDS → HIRA 매칭 테스트")
print("=" * 60)

def normalize_inn(name: str) -> str:
    """INN 정규화 (간단 버전)"""
    if not name:
        return ""
    name = name.lower().strip()
    # 염 형태 제거
    salts = ['hydrochloride', 'hcl', 'sodium', 'potassium', 'sulfate',
             'acetate', 'maleate', 'fumarate', 'citrate', 'tartrate',
             'mesylate', 'besylate', 'succinate', 'lactate']
    for salt in salts:
        name = name.replace(salt, '')
    # 특수문자 제거
    name = re.sub(r'[^a-z]', '', name)
    return name

# MFDS 성분 → INN → 주성분코드 → HIRA 급여
matched_count = 0
unmatched_samples = []

for mfds_row in mfds_data[:1000]:  # 샘플 1000건
    ingr = mfds_row.get("ITEM_INGR_NAME", "")
    if not ingr:
        continue

    # 첫 번째 성분 추출 (복합제)
    first_ingr = re.split(r'[/;,]', ingr)[0].strip()
    normalized = normalize_inn(first_ingr)

    # INN → 주성분코드
    code = inn_to_code.get(first_ingr.lower()) or inn_to_code.get(normalized)

    if code and code in hira_ingredient_codes:
        matched_count += 1
    else:
        if len(unmatched_samples) < 10:
            unmatched_samples.append((first_ingr, normalized, code))

print(f"매칭 성공: {matched_count:,}건 / 1,000건 ({matched_count/10:.1f}%)")
print(f"\n미매칭 샘플 (상위 10건):")
for orig, norm, code in unmatched_samples:
    print(f"  {orig} → {norm} → {code}")

# === 8. 약가마스터 성분명 활용 ===
print("\n" + "=" * 60)
print("8. 약가마스터 성분명 매핑 구축")
print("=" * 60)

# 약가마스터에서 성분명 컬럼 찾기
name_cols = [col for col in yakga_columns if "성분" in col or "일반" in col or "명" in col]
print(f"이름 관련 컬럼: {name_cols}")

# 샘플 확인
print("\n샘플 데이터:")
for i, row in enumerate(yakga_master[:3]):
    print(f"\n[{i+1}]")
    for col in name_cols:
        print(f"  {col}: {row.get(col, '')}")

# === 9. 결론 ===
print("\n" + "=" * 60)
print("9. 결론")
print("=" * 60)

print("""
커버리지 분석 결과:
- 약가마스터: HIRA 의성분코드의 높은 커버리지 확인 필요
- ATC 매핑: 제한적 (주성분코드 4,415개)

다음 단계:
1. 약가마스터 성분명 필드 활용한 매핑 테이블 구축
2. MFDS INN → 약가마스터 성분명 → 의성분코드 → HIRA 급여
""")
