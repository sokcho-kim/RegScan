"""DB 저장 로직 테스트"""

import asyncio
import sys
import io
from datetime import date
from pathlib import Path

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.db import SnapshotRepository, GlobalStatusRepository
from regscan.map.global_status import (
    GlobalRegulatoryStatus,
    RegulatoryApproval,
    ApprovalStatus,
    HotIssueLevel,
)


async def test_snapshot_repository():
    """스냅샷 저장소 테스트"""
    print("\n" + "=" * 50)
    print("1. SnapshotRepository 테스트")
    print("=" * 50)

    db_url = "sqlite+aiosqlite:///data/test_storage.db"
    repo = SnapshotRepository(db_url)
    await repo.init_db()

    # 테스트 데이터
    test_data = {
        "application_number": "NDA123456",
        "brand_name": "TestDrug",
        "active_ingredient": "testinib",
        "approval_date": "2025-01-15",
    }

    # 저장 테스트
    print("\n[저장 테스트]")
    result = await repo.save("FDA", "NDA123456", test_data)
    print(f"  - 첫 번째 저장: {'신규/변경' if result else '변경없음'}")

    # 동일 데이터 재저장 (변경 없음)
    result = await repo.save("FDA", "NDA123456", test_data)
    print(f"  - 동일 데이터 재저장: {'신규/변경' if result else '변경없음'}")

    # 데이터 변경 후 저장
    test_data["brand_name"] = "TestDrugUpdated"
    result = await repo.save("FDA", "NDA123456", test_data)
    print(f"  - 변경된 데이터 저장: {'신규/변경' if result else '변경없음'}")

    # 조회 테스트
    print("\n[조회 테스트]")
    latest = await repo.get_latest("FDA", "NDA123456")
    print(f"  - 최신 데이터: {latest.get('brand_name') if latest else 'None'}")

    # 히스토리 조회
    history = await repo.get_history("FDA", "NDA123456")
    print(f"  - 히스토리 수: {len(history)}건")

    # 대량 저장 테스트
    print("\n[대량 저장 테스트]")
    bulk_data = [
        {"application_number": f"NDA{i:06d}", "brand_name": f"Drug{i}"}
        for i in range(100, 110)
    ]
    stats = await repo.save_many("FDA", bulk_data, "application_number")
    print(f"  - 결과: {stats}")

    # 소스별 카운트
    count = await repo.count_by_source("FDA")
    print(f"  - FDA 스냅샷 총 수: {count}건")

    print("\n  [OK] SnapshotRepository 테스트 완료")


async def test_global_status_repository():
    """GlobalStatus 저장소 테스트"""
    print("\n" + "=" * 50)
    print("2. GlobalStatusRepository 테스트")
    print("=" * 50)

    db_url = "sqlite+aiosqlite:///data/test_storage.db"
    repo = GlobalStatusRepository(db_url)
    await repo.init_db()

    # 테스트 GlobalRegulatoryStatus 생성
    fda_approval = RegulatoryApproval(
        agency="FDA",
        status=ApprovalStatus.APPROVED,
        approval_date=date(2023, 7, 6),
        application_number="BLA761269",
        brand_name="Leqembi",
        is_breakthrough=True,
    )

    ema_approval = RegulatoryApproval(
        agency="EMA",
        status=ApprovalStatus.APPROVED,
        approval_date=date(2025, 11, 14),
        application_number="EMEA/H/C/005981",
        brand_name="Leqembi",
        is_prime=True,
        is_accelerated=True,
    )

    global_status = GlobalRegulatoryStatus(
        inn="lecanemab",
        normalized_name="lecanemab",
        atc_code="N07XX",
        fda=fda_approval,
        ema=ema_approval,
        global_score=60,
        hot_issue_level=HotIssueLevel.HIGH,
        hot_issue_reasons=["FDA 승인", "FDA Breakthrough", "EMA 승인", "EMA PRIME"],
    )

    # 저장 테스트
    print("\n[저장 테스트]")
    await repo.save(global_status)
    print("  - Lecanemab 저장 완료")

    # 추가 데이터 저장
    test_drugs = [
        ("semaglutide", 55, HotIssueLevel.MID, ["FDA 승인", "EMA 승인"]),
        ("pembrolizumab", 70, HotIssueLevel.HOT, ["FDA Breakthrough", "희귀의약품", "다중 승인"]),
        ("adalimumab", 45, HotIssueLevel.MID, ["FDA 승인", "EMA 승인"]),
        ("trastuzumab", 50, HotIssueLevel.MID, ["FDA 승인", "바이오시밀러 경쟁"]),
    ]

    for inn, score, level, reasons in test_drugs:
        status = GlobalRegulatoryStatus(
            inn=inn,
            normalized_name=inn,
            fda=RegulatoryApproval(
                agency="FDA",
                status=ApprovalStatus.APPROVED,
                approval_date=date(2020, 1, 1),
            ),
            global_score=score,
            hot_issue_level=level,
            hot_issue_reasons=reasons,
        )
        await repo.save(status)
    print(f"  - 추가 {len(test_drugs)}건 저장 완료")

    # 조회 테스트
    print("\n[조회 테스트]")

    # INN으로 조회
    result = await repo.get_by_inn("lecanemab")
    if result:
        print(f"  - INN 조회 (lecanemab):")
        print(f"      Score: {result.global_score}, Level: {result.hot_issue_level.value}")
        print(f"      FDA: {result.fda.status.value if result.fda else 'N/A'}")
        print(f"      EMA: {result.ema.status.value if result.ema else 'N/A'}")

    # 핫이슈 조회
    hot_issues = await repo.get_hot_issues(min_score=50)
    print(f"\n  - 핫이슈 (score >= 50): {len(hot_issues)}건")
    for item in hot_issues[:3]:
        print(f"      {item.inn}: {item.global_score}점 ({item.hot_issue_level.value})")

    # 등급별 조회
    hot_level = await repo.get_by_level(HotIssueLevel.HOT)
    print(f"\n  - HOT 등급: {len(hot_level)}건")

    high_level = await repo.get_by_level(HotIssueLevel.HIGH)
    print(f"  - HIGH 등급: {len(high_level)}건")

    # 다중 승인 조회
    multi = await repo.get_multi_approved()
    print(f"\n  - 다중 승인 (FDA+EMA): {len(multi)}건")

    # 검색 테스트
    print("\n[검색 테스트]")
    search_results = await repo.search("leca")
    print(f"  - 'leca' 검색: {len(search_results)}건")
    for item in search_results:
        print(f"      {item.inn}")

    # 통계
    stats = await repo.count()
    print(f"\n[통계]")
    print(f"  - 전체: {stats['total']}건")
    print(f"  - 등급별: {stats['by_level']}")

    print("\n  [OK] GlobalStatusRepository 테스트 완료")


async def test_integration():
    """실제 데이터 연동 테스트"""
    print("\n" + "=" * 50)
    print("3. 실제 데이터 연동 테스트")
    print("=" * 50)

    import json

    # EMA 데이터 로드
    ema_path = Path("data/ema/medicines_20260203.json")
    if not ema_path.exists():
        print("  - EMA 데이터 없음, 스킵")
        return

    with open(ema_path, "r", encoding="utf-8") as f:
        ema_data = json.load(f)

    print(f"  - EMA 데이터 로드: {len(ema_data)}건")

    # 스냅샷 저장
    db_url = "sqlite+aiosqlite:///data/test_storage.db"
    snapshot_repo = SnapshotRepository(db_url)
    await snapshot_repo.init_db()

    # 샘플 10건만 저장
    sample = ema_data[:10]
    stats = await snapshot_repo.save_many(
        "EMA_MEDICINE",
        sample,
        "ema_product_number",
    )
    print(f"  - 스냅샷 저장: {stats}")

    # GlobalStatus 변환 및 저장
    from regscan.parse.ema_parser import EMAMedicineParser
    from regscan.map.global_status import GlobalStatusBuilder

    parser = EMAMedicineParser()
    builder = GlobalStatusBuilder()
    global_repo = GlobalStatusRepository(db_url)
    await global_repo.init_db()

    saved_count = 0
    for item in sample:
        parsed = parser.parse_medicine(item)
        if parsed and parsed.get("inn"):
            global_status = builder.from_ema(parsed)
            await global_repo.save(global_status)
            saved_count += 1

    print(f"  - GlobalStatus 저장: {saved_count}건")

    # 확인
    final_stats = await global_repo.count()
    print(f"  - 최종 GlobalStatus 수: {final_stats['total']}건")

    print("\n  [OK] 실제 데이터 연동 테스트 완료")


async def main():
    print("=" * 50)
    print("DB 저장 로직 테스트")
    print("=" * 50)

    # data 디렉토리 확인
    Path("data").mkdir(exist_ok=True)

    await test_snapshot_repository()
    await test_global_status_repository()
    await test_integration()

    print("\n" + "=" * 50)
    print("모든 테스트 완료!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
