"""RegScan 통합 데이터 수집 파이프라인

모든 데이터 소스를 한 번에 수집하고 FeedCard로 변환합니다.

사용법:
    python -m regscan.scripts.collect_all
    python -m regscan.scripts.collect_all --days 7 --no-llm
    python -m regscan.scripts.collect_all --sources fda hira mohw
"""

import argparse
import asyncio
import logging
from datetime import datetime
from typing import Literal

from regscan.config import settings
from regscan.db import FeedCardRepository
from regscan.ingest.fda import FDAApprovalIngestor
from regscan.ingest.hira import HIRAInsuranceCriteriaIngestor, CrawlConfig
from regscan.ingest.mohw import MOHWPreAnnouncementIngestor
from regscan.models import SourceType
from regscan.parse import FDADrugParser, HIRAParser
from regscan.scan import SignalGenerator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


SourceName = Literal["fda", "hira", "mohw"]


async def collect_fda(days_back: int) -> list[dict]:
    """FDA 데이터 수집"""
    logger.info(f"[FDA] 수집 시작 (최근 {days_back}일)")
    try:
        ingestor = FDAApprovalIngestor(days_back=days_back)
        async with ingestor:
            raw_data = await ingestor.fetch()
        logger.info(f"[FDA] {len(raw_data)}건 수집 완료")

        # 파싱
        parser = FDADrugParser()
        parsed = parser.parse_many(raw_data)

        # source_type 추가
        for item in parsed:
            item["_source_type"] = SourceType.FDA_APPROVAL

        return parsed
    except Exception as e:
        logger.error(f"[FDA] 수집 실패: {e}")
        return []


async def collect_hira(days_back: int) -> list[dict]:
    """HIRA 보험인정기준 수집"""
    logger.info(f"[HIRA] 수집 시작 (최근 {days_back}일)")
    try:
        config = CrawlConfig(days_back=days_back)
        async with HIRAInsuranceCriteriaIngestor(config) as ingestor:
            raw_data = await ingestor.fetch()
        logger.info(f"[HIRA] {len(raw_data)}건 수집 완료")

        # 파싱
        parser = HIRAParser()
        parsed = parser.parse_many(raw_data)

        # source_type 추가
        for item in parsed:
            item["_source_type"] = SourceType.HIRA_NOTICE

        return parsed
    except Exception as e:
        logger.error(f"[HIRA] 수집 실패: {e}")
        return []


async def collect_mohw(max_pages: int = 3) -> list[dict]:
    """복지부 행정예고 수집"""
    logger.info(f"[MOHW] 수집 시작 (최대 {max_pages} 페이지)")
    try:
        config = CrawlConfig(max_pages=max_pages)
        async with MOHWPreAnnouncementIngestor(config) as ingestor:
            raw_data = await ingestor.fetch()
        logger.info(f"[MOHW] {len(raw_data)}건 수집 완료")

        # source_type 추가 (파서는 추후 구현)
        for item in raw_data:
            item["_source_type"] = SourceType.MOHW_ADMIN_NOTICE
            # 필수 필드 매핑
            item["source_id"] = item.get("url", "")
            item["source_url"] = item.get("url", "")

        return raw_data
    except Exception as e:
        logger.error(f"[MOHW] 수집 실패: {e}")
        return []


async def run_pipeline(
    sources: list[SourceName],
    days_back: int = 7,
    use_llm: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    통합 파이프라인 실행

    Args:
        sources: 수집할 소스 목록
        days_back: 수집 기간 (일)
        use_llm: LLM 사용 여부
        dry_run: DB 저장 건너뛰기

    Returns:
        수집 결과 통계
    """
    stats = {
        "start_time": datetime.now().isoformat(),
        "sources": sources,
        "days_back": days_back,
        "collected": {},
        "total_cards": 0,
        "saved": 0,
        "errors": [],
    }

    all_parsed = []

    # =========================================================================
    # Step 1: 데이터 수집
    # =========================================================================
    logger.info("=" * 60)
    logger.info("Step 1: 데이터 수집")
    logger.info("=" * 60)

    # 병렬 수집
    tasks = []
    if "fda" in sources:
        tasks.append(("fda", collect_fda(days_back)))
    if "hira" in sources:
        tasks.append(("hira", collect_hira(days_back)))
    if "mohw" in sources:
        tasks.append(("mohw", collect_mohw(max_pages=3)))

    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for (source_name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.error(f"[{source_name.upper()}] 수집 실패: {result}")
            stats["errors"].append(f"{source_name}: {result}")
            stats["collected"][source_name] = 0
        else:
            stats["collected"][source_name] = len(result)
            all_parsed.extend(result)

    total_collected = sum(stats["collected"].values())
    logger.info(f"총 {total_collected}건 수집 완료")

    if not all_parsed:
        logger.warning("수집된 데이터 없음")
        return stats

    # =========================================================================
    # Step 2: FeedCard 생성
    # =========================================================================
    logger.info("=" * 60)
    logger.info("Step 2: FeedCard 생성")
    logger.info("=" * 60)

    generator = SignalGenerator(use_llm=use_llm)
    cards = []

    for i, data in enumerate(all_parsed):
        try:
            source_type = data.pop("_source_type", SourceType.HIRA_NOTICE)
            card = await generator.generate(data, source_type)
            cards.append((card, data))

            if (i + 1) % 10 == 0:
                logger.info(f"  → {i + 1}/{len(all_parsed)} 변환 완료")
        except Exception as e:
            logger.warning(f"FeedCard 변환 실패: {e}")
            stats["errors"].append(f"Card generation: {e}")

    stats["total_cards"] = len(cards)
    logger.info(f"총 {len(cards)}건 FeedCard 생성 완료")

    # =========================================================================
    # Step 3: DB 저장
    # =========================================================================
    if dry_run:
        logger.info("=" * 60)
        logger.info("Step 3: Dry run - DB 저장 건너뜀")
        logger.info("=" * 60)
        stats["saved"] = len(cards)
    else:
        logger.info("=" * 60)
        logger.info("Step 3: DB 저장")
        logger.info("=" * 60)

        repo = FeedCardRepository(settings.DB_URL)
        await repo.init_db()

        saved_count = 0
        for card, raw in cards:
            try:
                await repo.save(card, raw_data=raw.get("raw"))
                saved_count += 1
            except Exception as e:
                logger.warning(f"저장 실패 ({card.id}): {e}")
                stats["errors"].append(f"Save: {e}")

        stats["saved"] = saved_count
        logger.info(f"총 {saved_count}건 저장 완료")

    stats["end_time"] = datetime.now().isoformat()
    return stats


async def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(
        description="RegScan 통합 데이터 수집 파이프라인"
    )
    parser.add_argument(
        "--sources", "-s",
        nargs="+",
        choices=["fda", "hira", "mohw"],
        default=["fda", "hira", "mohw"],
        help="수집할 데이터 소스 (기본: 전체)",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=settings.COLLECT_DAYS_BACK,
        help="수집 기간 (기본: 7일)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="LLM 사용 안 함 (템플릿만 사용)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 저장 안 함",
    )

    args = parser.parse_args()

    stats = await run_pipeline(
        sources=args.sources,
        days_back=args.days,
        use_llm=not args.no_llm,
        dry_run=args.dry_run,
    )

    # 결과 출력
    print("\n" + "=" * 60)
    print("RegScan 수집 결과")
    print("=" * 60)
    print(f"수집 기간: 최근 {stats['days_back']}일")
    print(f"데이터 소스: {', '.join(stats['sources'])}")
    print()
    print("수집 현황:")
    for source, count in stats["collected"].items():
        print(f"  - {source.upper()}: {count}건")
    print()
    print(f"FeedCard 생성: {stats['total_cards']}건")
    print(f"DB 저장: {stats['saved']}건")

    if stats["errors"]:
        print(f"\n오류: {len(stats['errors'])}건")
        for err in stats["errors"][:5]:
            print(f"  - {err}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
