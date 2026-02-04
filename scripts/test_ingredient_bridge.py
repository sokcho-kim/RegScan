"""IngredientBridge 테스트"""

import sys
import io
from pathlib import Path

# UTF-8 출력 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.map.ingredient_bridge import (
    IngredientBridge,
    ReimbursementStatus,
    normalize_ingredient_name,
    is_herbal_ingredient,
)

DATA_DIR = Path("C:/Jimin/RegScan/data")


def test_normalization():
    """정규화 테스트"""
    print("=" * 60)
    print("[1] 정규화 테스트")
    print("=" * 60)

    test_cases = [
        ("Amlodipine Besylate", "amlodipine besilate"),
        ("Atorvastatin Calcium Trihydrate", "atorvastatin calcium"),
        ("Esomeprazole Magnesium Trihydrate", "esomeprazole magnesium"),
        ("Rivastigmine Tartarate", "rivastigmine tartrate"),
        ("amlodipine besylate (as amlodipine)", "amlodipine besilate"),
    ]

    for input_name, expected in test_cases:
        result = normalize_ingredient_name(input_name)
        status = "OK" if result == expected else "FAIL"
        print(f"  {status} {input_name}")
        print(f"    → {result}")
        if result != expected:
            print(f"    Expected: {expected}")
    print()


def test_herbal_detection():
    """한약재 감지 테스트"""
    print("=" * 60)
    print("[2] 한약재 감지 테스트")
    print("=" * 60)

    herbals = [
        "Ginkgo Biloba Leaf Dried Extract",
        "Angelica Gigas Root",
        "Artemisiae Argyi Folium 95% Ethanol Soft Extract (20→1)",
        "Alisma Rhizome",
    ]

    non_herbals = [
        "Amlodipine Besylate",
        "Pembrolizumab",
        "Metformin Hydrochloride",
    ]

    print("  한약재 (True 기대):")
    for name in herbals:
        result = is_herbal_ingredient(name)
        status = "OK" if result else "FAIL"
        print(f"    {status} {name}: {result}")

    print("\n  양약 (False 기대):")
    for name in non_herbals:
        result = is_herbal_ingredient(name)
        status = "OK" if not result else "FAIL"
        print(f"    {status} {name}: {result}")
    print()


def test_bridge_lookup():
    """브릿지 조회 테스트"""
    print("=" * 60)
    print("[3] 브릿지 조회 테스트")
    print("=" * 60)

    bridge = IngredientBridge()

    # 데이터 로드
    master_path = DATA_DIR / "bridge" / "yakga_ingredient_master.csv"
    hira_path = DATA_DIR / "hira" / "drug_prices_20260204.json"
    atc_path = DATA_DIR / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"

    print(f"  Loading master: {master_path.name}")
    master_count = bridge.load_master(master_path)
    print(f"    → {master_count:,} records")

    print(f"  Loading ATC: {atc_path.name}")
    atc_count = bridge.load_atc_mapping(atc_path)
    print(f"    → {atc_count:,} records")

    print(f"  Loading HIRA: {hira_path.name}")
    hira_count = bridge.load_hira(hira_path)
    print(f"    → {hira_count:,} records")

    print(f"\n  Bridge stats: {bridge.get_stats()}")
    print()

    # 테스트 케이스
    test_cases = [
        # 급여 약물
        ("Amlodipine Besylate", ReimbursementStatus.REIMBURSED),
        ("Pembrolizumab", ReimbursementStatus.REIMBURSED),
        ("Nivolumab", ReimbursementStatus.REIMBURSED),
        ("Semaglutide", ReimbursementStatus.REIMBURSED),
        # 비급여 약물
        ("Tadalafil", ReimbursementStatus.NOT_COVERED),
        # 한약재
        ("Ginkgo Biloba Leaf Dried Extract", ReimbursementStatus.HERBAL),
        ("Angelica Gigas Root", ReimbursementStatus.HERBAL),
    ]

    print("  조회 결과:")
    for name, expected_status in test_cases:
        result = bridge.lookup(name)
        status_match = result.status == expected_status
        status = "OK" if status_match else "FAIL"
        print(f"    {status} {name}")
        print(f"       Status: {result.status.value} (expected: {expected_status.value})")
        if result.ingredient_code:
            print(f"       Code: {result.ingredient_code}")
        if result.reimbursement_criteria:
            print(f"       급여기준: {result.reimbursement_criteria}")
        if result.price_ceiling:
            print(f"       상한가: {result.price_ceiling:,}원")
        print(f"       Method: {result.match_method}")
    print()


def test_batch_matching():
    """전체 MFDS 매칭 테스트"""
    print("=" * 60)
    print("[4] 전체 MFDS 매칭 통계")
    print("=" * 60)

    import json

    bridge = IngredientBridge()
    bridge.load_master(DATA_DIR / "bridge" / "yakga_ingredient_master.csv")
    bridge.load_atc_mapping(DATA_DIR / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv")
    bridge.load_hira(DATA_DIR / "hira" / "drug_prices_20260204.json")

    # MFDS 데이터 로드
    mfds_path = DATA_DIR / "mfds" / "permits_full_20260203.json"
    with open(mfds_path, encoding="utf-8") as f:
        mfds_data = json.load(f)

    # 매칭
    from collections import Counter
    status_counts = Counter()
    method_counts = Counter()

    for item in mfds_data:
        inn = item.get("ITEM_INGR_NAME", "")
        result = bridge.lookup(inn)
        status_counts[result.status.value] += 1
        method_counts[result.match_method] += 1

    total = len(mfds_data)
    reimbursed = status_counts.get("reimbursed", 0)
    deleted = status_counts.get("deleted", 0)
    hira_connected = reimbursed + deleted

    print(f"\n  전체: {total:,}건")
    print(f"  HIRA 연결: {hira_connected:,}건 ({hira_connected/total*100:.1f}%)")
    print(f"\n  상태별:")
    for status, count in status_counts.most_common():
        print(f"    {status}: {count:,}건 ({count/total*100:.1f}%)")
    print(f"\n  매칭방법:")
    for method, count in method_counts.most_common():
        print(f"    {method}: {count:,}건 ({count/total*100:.1f}%)")


if __name__ == "__main__":
    test_normalization()
    test_herbal_detection()
    test_bridge_lookup()
    test_batch_matching()
