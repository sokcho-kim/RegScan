"""FDA approval_date NULL 약물 일괄 Backfill 스크립트

_search_fda_pharm_class가 submission_status_date를 추출하지 않던 버그로 인해
FDA approval_date가 NULL로 저장된 약물들을 FDA API에서 재조회하여 일괄 업데이트.

Usage:
    python -m regscan.scripts.backfill_fda_dates [--dry-run] [--limit N]
"""

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "regscan.db"


def get_null_fda_drugs(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """FDA approval_date가 NULL인 (drug_id, inn) 목록 반환."""
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, d.inn
        FROM drugs d
        JOIN regulatory_events re ON d.id = re.drug_id
        WHERE re.agency = 'fda'
          AND (re.approval_date IS NULL OR re.approval_date = '')
        ORDER BY d.inn
    """)
    return cur.fetchall()


async def lookup_fda_date(inn: str) -> dict | None:
    """FDA API에서 INN으로 조회 → ORIG+AP 우선순위 submission 추출."""
    from regscan.ingest.fda import FDAClient
    from regscan.parse.fda_parser import FDADrugParser

    parser = FDADrugParser()

    async with FDAClient() as client:
        # 1차: generic_name 검색
        fda_result = None
        for search_fn, name in [
            (client.search_by_generic_name, inn),
            (client.search_by_substance_name, inn.upper()),
        ]:
            try:
                response = await search_fn(name, limit=5)
                results = response.get("results", [])
                if results:
                    fda_result = results[0]
                    break
            except Exception:
                continue

        if not fda_result:
            return None

        submissions = fda_result.get("submissions", [])
        if not submissions:
            return None

        sub_info = parser._extract_latest_submission(submissions)
        date_str = sub_info.get("submission_status_date", "")
        if not date_str:
            return None

        app_number = fda_result.get("application_number", "")

        return {
            "submission_status_date": date_str,
            "application_number": app_number,
            "submission_type": sub_info.get("submission_type", ""),
            "submission_status": sub_info.get("submission_status", ""),
        }


async def backfill(dry_run: bool = False, limit: int = 0):
    """메인 Backfill 로직."""
    conn = sqlite3.connect(str(DB_PATH))
    targets = get_null_fda_drugs(conn)
    total = len(targets)
    logger.info("FDA approval_date NULL 약물: %d건", total)

    if limit > 0:
        targets = targets[:limit]
        logger.info("  --limit %d 적용 → %d건만 처리", limit, len(targets))

    updated = 0
    skipped = 0
    failed = 0
    results_log: list[str] = []

    for i, (drug_id, inn) in enumerate(targets, 1):
        try:
            info = await lookup_fda_date(inn)

            if not info:
                skipped += 1
                results_log.append(f"  SKIP  [{drug_id}] {inn} — FDA API 결과 없음")
                logger.debug("[%d/%d] SKIP %s", i, len(targets), inn)
            else:
                raw_date = info["submission_status_date"]
                # YYYYMMDD → YYYY-MM-DD
                formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                app_number = info["application_number"]
                sub_type = info["submission_type"]

                if not dry_run:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE regulatory_events
                        SET approval_date = ?, application_number = ?
                        WHERE drug_id = ? AND agency = 'fda'
                          AND (approval_date IS NULL OR approval_date = '')
                    """, (formatted_date, app_number, drug_id))

                updated += 1
                results_log.append(
                    f"  UPDATE [{drug_id}] {inn} → {formatted_date} "
                    f"({sub_type}+AP) {app_number}"
                )
                logger.info(
                    "[%d/%d] UPDATE %s → %s (%s)",
                    i, len(targets), inn, formatted_date, app_number,
                )

        except Exception as e:
            failed += 1
            results_log.append(f"  ERROR [{drug_id}] {inn} — {e}")
            logger.warning("[%d/%d] ERROR %s: %s", i, len(targets), inn, e)

        # FDA API rate limit (0.3초 간격)
        await asyncio.sleep(0.3)

    if not dry_run:
        conn.commit()

    conn.close()

    # 결과 보고
    mode = "DRY-RUN" if dry_run else "COMMITTED"
    print(f"\n{'='*60}")
    print(f"FDA Backfill 결과 ({mode})")
    print(f"{'='*60}")
    print(f"  대상:   {total}건")
    print(f"  처리:   {len(targets)}건")
    print(f"  UPDATE: {updated}건")
    print(f"  SKIP:   {skipped}건 (FDA API 결과 없음)")
    print(f"  ERROR:  {failed}건")
    print(f"{'='*60}")
    print()
    for line in results_log:
        print(line)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    asyncio.run(backfill(dry_run=dry_run, limit=limit))
