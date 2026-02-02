"""복지부 입법/행정예고 수집 스크립트

사용법:
    python -m regscan.scripts.collect_mohw
    python -m regscan.scripts.collect_mohw --max-pages 3
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from regscan.ingest.hira import CrawlConfig
from regscan.ingest.mohw import MOHWPreAnnouncementIngestor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_mohw(
    max_pages: int = 5,
    headless: bool = True,
    output_dir: Path | None = None,
) -> dict:
    """
    복지부 입법/행정예고 수집

    Args:
        max_pages: 최대 수집 페이지 수
        headless: 헤드리스 모드
        output_dir: 결과 저장 디렉토리

    Returns:
        수집 결과 통계
    """
    stats = {
        "start_time": datetime.now().isoformat(),
        "max_pages": max_pages,
        "total_count": 0,
        "in_progress_count": 0,
        "completed_count": 0,
        "errors": [],
    }

    config = CrawlConfig(
        headless=headless,
        max_pages=max_pages,
    )

    try:
        async with MOHWPreAnnouncementIngestor(config) as ingestor:
            records = await ingestor.fetch()

        stats["total_count"] = len(records)
        stats["in_progress_count"] = sum(
            1 for r in records if r.get("status") == "진행"
        )
        stats["completed_count"] = sum(
            1 for r in records if r.get("status") == "완료"
        )

        # 결과 저장
        if output_dir and records:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"mohw_pre_announcement_{timestamp}.json"

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

            logger.info(f"결과 저장: {output_file}")
            stats["output_file"] = str(output_file)

    except Exception as e:
        logger.error(f"수집 실패: {e}")
        stats["errors"].append(str(e))

    stats["end_time"] = datetime.now().isoformat()
    return stats


async def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(description="복지부 입법/행정예고 수집")
    parser.add_argument(
        "--max-pages", "-m",
        type=int,
        default=5,
        help="최대 수집 페이지 수 (기본: 5)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="브라우저 표시 (디버깅용)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/mohw"),
        help="결과 저장 디렉토리",
    )

    args = parser.parse_args()

    stats = await collect_mohw(
        max_pages=args.max_pages,
        headless=not args.no_headless,
        output_dir=args.output,
    )

    # 결과 출력
    print("\n" + "=" * 50)
    print("복지부 입법/행정예고 수집 결과")
    print("=" * 50)
    print(f"총 수집: {stats['total_count']}건")
    print(f"  - 진행 중: {stats['in_progress_count']}건")
    print(f"  - 완료: {stats['completed_count']}건")

    if stats.get("output_file"):
        print(f"\n저장 파일: {stats['output_file']}")

    if stats["errors"]:
        print(f"\n오류: {len(stats['errors'])}건")
        for err in stats["errors"]:
            print(f"  - {err}")

    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
