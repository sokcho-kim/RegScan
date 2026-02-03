"""GlobalRegulatoryStatus 테스트"""

import asyncio
import sys
import io
from pathlib import Path

# Windows 콘솔 UTF-8 출력
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.ema import EMAClient
from regscan.ingest.fda import FDAClient
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.parse.fda_parser import FDADrugParser
from regscan.map.global_status import (
    GlobalStatusBuilder,
    HotIssueScorer,
    merge_by_inn,
    HotIssueLevel,
)


async def test_single_drug():
    """단일 약물 테스트"""
    print("=" * 60)
    print("Single Drug Test - Lecanemab (Leqembi)")
    print("=" * 60)

    builder = GlobalStatusBuilder()

    # 가상 FDA 데이터
    fda_data = {
        "application_number": "BLA761269",
        "brand_name": "Leqembi",
        "generic_name": "lecanemab",
        "submission_status_date": "20230706",
        "submission_status": "AP",
        "submission_class_code": "1",  # Priority
        "pharm_class": ["Amyloid Beta-Directed Antibody"],
        "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/appletter/2023/761269Orig1s000ltr.pdf",
    }

    # 가상 EMA 데이터
    ema_data = {
        "name": "Leqembi",
        "inn": "lecanemab",
        "ema_product_number": "EMEA/H/C/005981",
        "medicine_status": "Authorised",
        "marketing_authorisation_date": "2025-11-14",
        "therapeutic_area": "Alzheimer Disease",
        "atc_code": "N07XX23",
        "is_orphan": False,
        "is_accelerated": True,
        "is_prime": True,
        "source_url": "https://www.ema.europa.eu/en/medicines/human/EPAR/leqembi",
    }

    status = builder.build_from_fda_ema(fda_data, ema_data)

    print(f"\nINN: {status.inn}")
    print(f"ATC Code: {status.atc_code}")
    print(f"\nFDA:")
    print(f"  - Status: {status.fda.status.value}")
    print(f"  - Approval Date: {status.fda.approval_date}")
    print(f"  - Priority Review: {status.fda.is_priority}")
    print(f"\nEMA:")
    print(f"  - Status: {status.ema.status.value}")
    print(f"  - Approval Date: {status.ema.approval_date}")
    print(f"  - PRIME: {status.ema.is_prime}")
    print(f"  - Accelerated: {status.ema.is_accelerated}")
    print(f"\nGlobal Analysis:")
    print(f"  - Approved Agencies: {status.approved_agencies}")
    print(f"  - Global Score: {status.global_score}")
    print(f"  - Hot Issue Level: {status.hot_issue_level.value}")
    print(f"  - Reasons: {status.hot_issue_reasons}")


async def test_merge_fda_ema():
    """FDA + EMA 데이터 병합 테스트"""
    print("\n" + "=" * 60)
    print("FDA + EMA Data Merge Test")
    print("=" * 60)

    # FDA 데이터 수집
    print("\n[1] Fetching FDA approvals (last 90 days)...")
    async with FDAClient() as client:
        fda_response = await client.search_drug_approvals(days_back=90, limit=50)

    fda_raw = fda_response.get("results", [])
    print(f"    -> {len(fda_raw)} FDA records")

    # EMA 데이터 수집
    print("\n[2] Fetching EMA medicines...")
    async with EMAClient() as client:
        ema_raw = await client.fetch_medicines()

    print(f"    -> {len(ema_raw)} EMA records")

    # 파싱
    print("\n[3] Parsing...")
    fda_parser = FDADrugParser()
    ema_parser = EMAMedicineParser()

    fda_parsed = fda_parser.parse_many(fda_raw)
    ema_parsed = ema_parser.parse_many(ema_raw)

    print(f"    -> FDA: {len(fda_parsed)}, EMA: {len(ema_parsed)}")

    # 병합
    print("\n[4] Merging by INN...")
    merged = merge_by_inn(fda_parsed, ema_parsed)
    print(f"    -> {len(merged)} GlobalRegulatoryStatus records")

    # 통계
    print("\n" + "=" * 60)
    print("Statistics")
    print("=" * 60)

    # 다중 승인
    multi_approved = [s for s in merged if s.approval_count >= 2]
    print(f"\nMulti-approved (2+ agencies): {len(multi_approved)}")

    # Hot Issue 등급별
    level_counts = {}
    for status in merged:
        level = status.hot_issue_level.value
        level_counts[level] = level_counts.get(level, 0) + 1

    print("\nHot Issue Level Distribution:")
    for level in ["HOT", "HIGH", "MID", "LOW"]:
        count = level_counts.get(level, 0)
        print(f"  {level}: {count}")

    # HOT/HIGH 목록
    hot_high = [s for s in merged if s.hot_issue_level in (HotIssueLevel.HOT, HotIssueLevel.HIGH)]
    if hot_high:
        print(f"\nHOT/HIGH Items ({len(hot_high)}):")
        for status in hot_high[:10]:
            print(f"\n  [{status.hot_issue_level.value}] {status.inn}")
            print(f"      Score: {status.global_score}")
            print(f"      Agencies: {status.approved_agencies}")
            print(f"      Reasons: {', '.join(status.hot_issue_reasons[:3])}")

    return merged


async def test_scorer():
    """HotIssueScorer 테스트"""
    print("\n" + "=" * 60)
    print("HotIssueScorer Test")
    print("=" * 60)

    scorer = HotIssueScorer()
    builder = GlobalStatusBuilder()

    test_cases = [
        {
            "name": "Breakthrough + Orphan",
            "fda": {
                "generic_name": "test_drug_1",
                "submission_class_code": "5",  # Breakthrough
                "pharm_class": ["orphan drug"],
                "submission_status_date": "20250101",
            },
            "ema": {
                "inn": "test_drug_1",
                "medicine_status": "Authorised",
                "marketing_authorisation_date": "2025-02-01",
                "is_prime": True,
            },
        },
        {
            "name": "Standard approval (FDA only)",
            "fda": {
                "generic_name": "test_drug_2",
                "submission_class_code": "3",  # Standard
                "pharm_class": [],
                "submission_status_date": "20250101",
            },
            "ema": None,
        },
        {
            "name": "Cancer drug (EMA only)",
            "fda": None,
            "ema": {
                "inn": "test_drug_3",
                "medicine_status": "Authorised",
                "marketing_authorisation_date": "2025-01-01",
                "therapeutic_area": "Neoplasms; Breast Cancer",
                "is_accelerated": True,
            },
        },
    ]

    for case in test_cases:
        status = builder.build_from_fda_ema(case.get("fda"), case.get("ema"))
        print(f"\n{case['name']}:")
        print(f"  Score: {status.global_score}")
        print(f"  Level: {status.hot_issue_level.value}")
        print(f"  Reasons: {status.hot_issue_reasons}")


async def main():
    await test_single_drug()
    await test_scorer()
    await test_merge_fda_ema()


if __name__ == "__main__":
    asyncio.run(main())
