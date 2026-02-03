"""통합 파이프라인 E2E 테스트

FDA + EMA + HIRA → Parse → FeedCard → DB 전체 흐름 테스트
"""

import asyncio
import sys
import io
import json
from datetime import date, datetime
from pathlib import Path

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.db import (
    FeedCardRepository,
    SnapshotRepository,
    GlobalStatusRepository,
)
from regscan.parse.fda_parser import FDADrugParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.scan.signal_generator import SignalGenerator
from regscan.models.feed_card import SourceType
from regscan.map.global_status import GlobalStatusBuilder, merge_by_inn


DB_URL = "sqlite+aiosqlite:///data/e2e_test.db"


async def init_repositories():
    """저장소 초기화"""
    print("\n[저장소 초기화]")

    feed_repo = FeedCardRepository(DB_URL)
    snapshot_repo = SnapshotRepository(DB_URL)
    global_repo = GlobalStatusRepository(DB_URL)

    await feed_repo.init_db()
    await snapshot_repo.init_db()
    await global_repo.init_db()

    print("  - 모든 저장소 초기화 완료")
    return feed_repo, snapshot_repo, global_repo


async def test_fda_pipeline(feed_repo, snapshot_repo, global_repo):
    """FDA 파이프라인 테스트"""
    print("\n" + "=" * 50)
    print("1. FDA 파이프라인")
    print("=" * 50)

    # 샘플 FDA 데이터 로드
    fda_path = Path("data/fda/approvals_20260131.json")
    if not fda_path.exists():
        print("  - FDA 데이터 없음, 스킵")
        return []

    with open(fda_path, "r", encoding="utf-8") as f:
        fda_data = json.load(f)

    results = fda_data.get("results", fda_data) if isinstance(fda_data, dict) else fda_data
    print(f"  - FDA 데이터 로드: {len(results)}건")

    # 스냅샷 저장
    sample = results[:20]  # 20건 샘플
    stats = await snapshot_repo.save_many(
        "FDA",
        sample,
        "application_number",
    )
    print(f"  - 스냅샷 저장: {stats}")

    # 파싱
    parser = FDADrugParser()
    parsed_list = parser.parse_many(sample)
    print(f"  - 파싱 완료: {len(parsed_list)}건")

    # FeedCard 생성
    generator = SignalGenerator()
    feed_cards = []
    for parsed in parsed_list:
        try:
            card = await generator.generate(parsed, SourceType.FDA_DRUGS)
            feed_cards.append(card)
        except Exception as e:
            print(f"    - 오류: {e}")

    print(f"  - FeedCard 생성: {len(feed_cards)}건")

    # FeedCard 저장
    saved = await feed_repo.save_many(feed_cards)
    print(f"  - FeedCard 저장: {saved}건")

    # Impact 분포
    impact_counts = {}
    for card in feed_cards:
        level = card.impact_level.value
        impact_counts[level] = impact_counts.get(level, 0) + 1
    print(f"  - Impact 분포: {impact_counts}")

    print("  [OK] FDA 파이프라인 완료")
    return parsed_list


async def test_ema_pipeline(feed_repo, snapshot_repo, global_repo):
    """EMA 파이프라인 테스트"""
    print("\n" + "=" * 50)
    print("2. EMA 파이프라인")
    print("=" * 50)

    # EMA 데이터 로드
    ema_path = Path("data/ema/medicines_20260203.json")
    if not ema_path.exists():
        print("  - EMA 데이터 없음, 스킵")
        return []

    with open(ema_path, "r", encoding="utf-8") as f:
        ema_data = json.load(f)

    print(f"  - EMA 데이터 로드: {len(ema_data)}건")

    # 스냅샷 저장
    sample = ema_data[:20]  # 20건 샘플
    stats = await snapshot_repo.save_many(
        "EMA_MEDICINE",
        sample,
        "ema_product_number",
    )
    print(f"  - 스냅샷 저장: {stats}")

    # 파싱
    parser = EMAMedicineParser()
    parsed_list = parser.parse_many(sample)
    print(f"  - 파싱 완료: {len(parsed_list)}건")

    # FeedCard 생성
    generator = SignalGenerator()
    feed_cards = []
    for parsed in parsed_list:
        try:
            card = await generator.generate(parsed, SourceType.EMA_MEDICINE)
            feed_cards.append(card)
        except Exception as e:
            print(f"    - 오류: {e}")

    print(f"  - FeedCard 생성: {len(feed_cards)}건")

    # FeedCard 저장
    saved = await feed_repo.save_many(feed_cards)
    print(f"  - FeedCard 저장: {saved}건")

    # Impact 분포
    impact_counts = {}
    for card in feed_cards:
        level = card.impact_level.value
        impact_counts[level] = impact_counts.get(level, 0) + 1
    print(f"  - Impact 분포: {impact_counts}")

    print("  [OK] EMA 파이프라인 완료")
    return parsed_list


async def test_global_status_pipeline(fda_parsed, ema_parsed, global_repo):
    """GlobalRegulatoryStatus 통합 테스트"""
    print("\n" + "=" * 50)
    print("3. GlobalRegulatoryStatus 통합")
    print("=" * 50)

    if not fda_parsed and not ema_parsed:
        print("  - 입력 데이터 없음, 스킵")
        return

    # INN 기준 병합
    merged = merge_by_inn(fda_parsed, ema_parsed)
    print(f"  - INN 기준 병합: {len(merged)}건")

    # DB 저장
    saved = await global_repo.save_many(merged)
    print(f"  - GlobalStatus 저장: {saved}건")

    # 통계
    stats = await global_repo.count()
    print(f"  - 전체: {stats['total']}건")
    print(f"  - 등급별: {stats['by_level']}")

    # 핫이슈 상위 5건
    hot_issues = await global_repo.get_hot_issues(min_score=40, limit=5)
    print("\n  [핫이슈 Top 5]")
    for item in hot_issues:
        fda_status = item.fda.status.value if item.fda else "N/A"
        ema_status = item.ema.status.value if item.ema else "N/A"
        print(f"    - {item.inn}: {item.global_score}점 ({item.hot_issue_level.value})")
        print(f"        FDA: {fda_status}, EMA: {ema_status}")

    print("\n  [OK] GlobalRegulatoryStatus 통합 완료")


async def test_feed_query(feed_repo):
    """FeedCard 조회 테스트"""
    print("\n" + "=" * 50)
    print("4. FeedCard 조회 테스트")
    print("=" * 50)

    # 최신 피드 조회
    recent = await feed_repo.get_recent(limit=10)
    print(f"  - 최신 피드: {len(recent)}건")

    # 전체 통계
    total = await feed_repo.count()
    print(f"  - 전체 FeedCard 수: {total}건")

    # 샘플 출력
    print("\n  [샘플 피드]")
    for card in recent[:3]:
        print(f"    - [{card.source_type.value}] {card.title[:50]}...")
        print(f"      Impact: {card.impact_level.value}")

    print("\n  [OK] FeedCard 조회 테스트 완료")


async def main():
    print("=" * 60)
    print("통합 파이프라인 E2E 테스트")
    print("=" * 60)
    print(f"테스트 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # data 디렉토리 확인
    Path("data").mkdir(exist_ok=True)

    # 저장소 초기화
    feed_repo, snapshot_repo, global_repo = await init_repositories()

    # 파이프라인 테스트
    fda_parsed = await test_fda_pipeline(feed_repo, snapshot_repo, global_repo)
    ema_parsed = await test_ema_pipeline(feed_repo, snapshot_repo, global_repo)

    # GlobalStatus 통합
    await test_global_status_pipeline(fda_parsed, ema_parsed, global_repo)

    # 조회 테스트
    await test_feed_query(feed_repo)

    print("\n" + "=" * 60)
    print("E2E 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
