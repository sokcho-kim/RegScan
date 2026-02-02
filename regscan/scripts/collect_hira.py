"""HIRA 데이터 일일 수집 스크립트

사용법:
    python -m regscan.scripts.collect_hira
    python -m regscan.scripts.collect_hira --days 7 --type criteria
    python -m regscan.scripts.collect_hira --type notice --no-headless
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from regscan.ingest.hira import (
    CrawlConfig,
    HIRAInsuranceCriteriaIngestor,
    HIRANoticeIngestor,
    CATEGORY_MAP,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def collect_hira(
    collect_type: str = "all",
    days_back: int = 7,
    headless: bool = True,
    categories: list[str] | None = None,
    output_dir: Path | None = None,
) -> dict:
    """
    HIRA 데이터 수집

    Args:
        collect_type: "criteria" | "notice" | "all"
        days_back: 수집할 일수
        headless: 헤드리스 모드
        categories: 수집할 카테고리 코드 (criteria만 해당)
        output_dir: 결과 저장 디렉토리

    Returns:
        수집 결과 통계
    """
    stats = {
        "start_time": datetime.now().isoformat(),
        "collect_type": collect_type,
        "days_back": days_back,
        "criteria_count": 0,
        "notice_count": 0,
        "errors": [],
    }

    config = CrawlConfig(
        headless=headless,
        days_back=days_back,
        categories=categories or list(CATEGORY_MAP.keys()),
    )

    all_records = []

    # 보험인정기준 수집
    if collect_type in ("criteria", "all"):
        logger.info("=" * 50)
        logger.info("HIRA 보험인정기준 수집 시작")
        logger.info(f"카테고리: {[CATEGORY_MAP.get(c, c) for c in config.categories]}")
        logger.info("=" * 50)

        try:
            async with HIRAInsuranceCriteriaIngestor(config) as ingestor:
                records = await ingestor.fetch()
                stats["criteria_count"] = len(records)
                for r in records:
                    r["source_type"] = "HIRA_CRITERIA"
                all_records.extend(records)
        except Exception as e:
            logger.error(f"보험인정기준 수집 실패: {e}")
            stats["errors"].append(f"Criteria error: {e}")

    # 공지사항 수집
    if collect_type in ("notice", "all"):
        logger.info("=" * 50)
        logger.info("HIRA 공지사항 수집 시작")
        logger.info("=" * 50)

        try:
            async with HIRANoticeIngestor(config) as ingestor:
                records = await ingestor.fetch()
                stats["notice_count"] = len(records)
                for r in records:
                    r["source_type"] = "HIRA_NOTICE"
                all_records.extend(records)
        except Exception as e:
            logger.error(f"공지사항 수집 실패: {e}")
            stats["errors"].append(f"Notice error: {e}")

    stats["total_count"] = len(all_records)
    stats["end_time"] = datetime.now().isoformat()

    # 결과 저장
    if output_dir and all_records:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"hira_{collect_type}_{timestamp}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)

        logger.info(f"결과 저장: {output_file}")
        stats["output_file"] = str(output_file)

    return stats


async def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(description="HIRA 데이터 수집")
    parser.add_argument(
        "--type", "-t",
        choices=["criteria", "notice", "all"],
        default="all",
        help="수집 유형 (기본: all)",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=7,
        help="수집할 일수 (기본: 7)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="브라우저 표시 (디버깅용)",
    )
    parser.add_argument(
        "--categories", "-c",
        nargs="+",
        choices=list(CATEGORY_MAP.keys()),
        help="수집할 카테고리 코드 (01:고시, 02:행정해석, 09:심사지침, 10:심의사례공개, 17:심사사례지침)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/hira"),
        help="결과 저장 디렉토리",
    )

    args = parser.parse_args()

    stats = await collect_hira(
        collect_type=args.type,
        days_back=args.days,
        headless=not args.no_headless,
        categories=args.categories,
        output_dir=args.output,
    )

    # 결과 출력
    print("\n" + "=" * 50)
    print("HIRA 수집 결과")
    print("=" * 50)
    print(f"수집 유형: {stats['collect_type']}")
    print(f"수집 기간: 최근 {stats['days_back']}일")
    print(f"보험인정기준: {stats['criteria_count']}건")
    print(f"공지사항: {stats['notice_count']}건")
    print(f"총 수집: {stats['total_count']}건")

    if stats.get("output_file"):
        print(f"\n저장 파일: {stats['output_file']}")

    if stats["errors"]:
        print(f"\n오류: {len(stats['errors'])}건")
        for err in stats["errors"]:
            print(f"  - {err}")

    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
