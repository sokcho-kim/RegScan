"""FDA 데이터 일일 수집 스크립트

사용법:
    python -m regscan.scripts.collect_fda
    python -m regscan.scripts.collect_fda --days 7 --no-llm
"""

import argparse
import asyncio
import logging
from datetime import datetime

from regscan.config import settings
from regscan.db import FeedCardRepository
from regscan.ingest.fda import FDAApprovalIngestor
from regscan.models import SourceType
from regscan.parse import FDADrugParser
from regscan.scan import SignalGenerator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_fda_approvals(
    days_back: int = 7,
    use_llm: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    FDA 승인 정보 수집 및 저장

    Args:
        days_back: 수집할 일수
        use_llm: LLM 사용 여부
        dry_run: True면 DB 저장 안 함

    Returns:
        수집 결과 통계
    """
    stats = {
        "start_time": datetime.now().isoformat(),
        "days_back": days_back,
        "use_llm": use_llm,
        "total_fetched": 0,
        "total_parsed": 0,
        "total_saved": 0,
        "llm_count": 0,
        "template_count": 0,
        "errors": [],
    }

    logger.info(f"FDA 수집 시작: 최근 {days_back}일")

    # 1. 데이터 수집
    logger.info("Step 1: FDA API에서 데이터 수집 중...")
    try:
        ingestor = FDAApprovalIngestor(days_back=days_back)
        async with ingestor:
            raw_data = await ingestor.fetch()
        stats["total_fetched"] = len(raw_data)
        logger.info(f"  → {len(raw_data)}건 수집 완료")
    except Exception as e:
        logger.error(f"수집 실패: {e}")
        stats["errors"].append(f"Fetch error: {e}")
        return stats

    if not raw_data:
        logger.info("수집된 데이터 없음")
        return stats

    # 2. 파싱
    logger.info("Step 2: 데이터 파싱 중...")
    parser = FDADrugParser()
    parsed_data = parser.parse_many(raw_data)
    stats["total_parsed"] = len(parsed_data)
    logger.info(f"  → {len(parsed_data)}건 파싱 완료")

    # 3. FeedCard 변환
    logger.info("Step 3: FeedCard 변환 중...")
    generator = SignalGenerator(use_llm=use_llm)
    cards_with_method = []

    for i, data in enumerate(parsed_data):
        try:
            card = await generator.generate(data, SourceType.FDA_APPROVAL)
            method = generator.last_why_method

            cards_with_method.append((card, method, data))

            if method == "llm":
                stats["llm_count"] += 1
            else:
                stats["template_count"] += 1

            if (i + 1) % 10 == 0:
                logger.info(f"  → {i + 1}/{len(parsed_data)} 변환 완료")

        except Exception as e:
            logger.warning(f"변환 실패 ({data.get('application_number', 'unknown')}): {e}")
            stats["errors"].append(f"Convert error: {e}")

    logger.info(f"  → 총 {len(cards_with_method)}건 변환 완료")
    logger.info(f"     LLM: {stats['llm_count']}건, 템플릿: {stats['template_count']}건")

    # 4. DB 저장
    if dry_run:
        logger.info("Step 4: Dry run - DB 저장 건너뜀")
        stats["total_saved"] = len(cards_with_method)
    else:
        logger.info("Step 4: DB 저장 중...")
        repo = FeedCardRepository(settings.DB_URL)
        await repo.init_db()

        saved_count = 0
        for card, method, raw in cards_with_method:
            try:
                await repo.save(card, raw_data=raw.get("raw"))
                saved_count += 1
            except Exception as e:
                logger.warning(f"저장 실패 ({card.id}): {e}")
                stats["errors"].append(f"Save error: {e}")

        stats["total_saved"] = saved_count
        logger.info(f"  → {saved_count}건 저장 완료")

    stats["end_time"] = datetime.now().isoformat()
    return stats


async def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(description="FDA 데이터 수집")
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=settings.COLLECT_DAYS_BACK,
        help="수집할 일수 (기본: 7)",
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

    stats = await collect_fda_approvals(
        days_back=args.days,
        use_llm=not args.no_llm,
        dry_run=args.dry_run,
    )

    # 결과 출력
    print("\n" + "=" * 50)
    print("FDA 수집 결과")
    print("=" * 50)
    print(f"수집 기간: 최근 {stats['days_back']}일")
    print(f"API 수집: {stats['total_fetched']}건")
    print(f"파싱: {stats['total_parsed']}건")
    print(f"저장: {stats['total_saved']}건")
    print(f"  - LLM 생성: {stats['llm_count']}건")
    print(f"  - 템플릿: {stats['template_count']}건")

    if stats["errors"]:
        print(f"\n오류: {len(stats['errors'])}건")
        for err in stats["errors"][:5]:
            print(f"  - {err}")

    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
