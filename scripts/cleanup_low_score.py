"""저점 약물 정리 — global_score < MIN_SCORE_FOR_DB 인 약물과 관련 레코드 삭제

기본은 dry-run (리포트만 출력). 실제 삭제는 --execute 플래그 필요.
CASCADE FK이므로 drugs 삭제 시 관련 테이블도 자동 정리.

사용:
    python scripts/cleanup_low_score.py              # dry-run
    python scripts/cleanup_low_score.py --execute     # 실제 삭제
    python scripts/cleanup_low_score.py --threshold 20  # 20점 미만 삭제
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from regscan.db.database import get_sync_engine
from regscan.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

RELATED_TABLES = [
    "regulatory_events",
    "hira_reimbursements",
    "clinical_trials",
    "briefing_reports",
    "preprints",
    "market_reports",
    "expert_opinions",
    "ai_insights",
    "articles",
]


def report(threshold: int):
    """삭제 대상 리포트를 출력한다."""
    engine = get_sync_engine()
    with engine.connect() as conn:
        # 대상 약물
        drugs = conn.execute(
            text(
                "SELECT id, inn, global_score FROM drugs "
                "WHERE COALESCE(global_score, 0) < :threshold "
                "ORDER BY global_score ASC"
            ),
            {"threshold": threshold},
        ).mappings().fetchall()

        total_drugs = conn.execute(text("SELECT COUNT(*) FROM drugs")).scalar()

        print(f"\n{'='*60}")
        print(f"  저점 약물 정리 리포트 (threshold: global_score < {threshold})")
        print(f"{'='*60}")
        print(f"  전체 약물: {total_drugs}건")
        print(f"  삭제 대상: {len(drugs)}건")
        print(f"  잔여 예상: {total_drugs - len(drugs)}건")
        print(f"{'='*60}")

        if not drugs:
            print("  삭제 대상 약물 없음.")
            return []

        # 관련 레코드 카운트
        drug_ids = [d["id"] for d in drugs]
        placeholders = ", ".join(str(did) for did in drug_ids)

        print(f"\n  관련 레코드 (CASCADE 삭제 예정):")
        for table in RELATED_TABLES:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE drug_id IN ({placeholders})")
            ).scalar()
            if count > 0:
                print(f"    {table}: {count}건")

        print(f"\n  삭제 대상 약물 목록:")
        for d in drugs:
            print(f"    #{d['id']:>4d}  score={d['global_score'] or 0:>3d}  {d['inn']}")

        print()
        return drug_ids


def execute_cleanup(threshold: int):
    """실제 삭제를 수행한다."""
    engine = get_sync_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "DELETE FROM drugs WHERE COALESCE(global_score, 0) < :threshold"
            ),
            {"threshold": threshold},
        )
        deleted = result.rowcount
        logger.info("삭제 완료: %d건 (CASCADE로 관련 레코드도 삭제됨)", deleted)
        return deleted


def main():
    parser = argparse.ArgumentParser(description="저점 약물 정리")
    parser.add_argument(
        "--threshold", type=int,
        default=settings.MIN_SCORE_FOR_DB,
        help=f"이 점수 미만 약물 삭제 (기본: {settings.MIN_SCORE_FOR_DB})",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="실제 삭제 수행 (기본은 dry-run)",
    )
    args = parser.parse_args()

    drug_ids = report(args.threshold)

    if not drug_ids:
        return

    if args.execute:
        deleted = execute_cleanup(args.threshold)
        print(f"  실제 삭제 완료: {deleted}건")
    else:
        print("  [DRY-RUN] 실제 삭제하려면 --execute 플래그를 추가하세요.")


if __name__ == "__main__":
    main()
