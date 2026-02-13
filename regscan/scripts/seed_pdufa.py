"""PDUFA 시드 데이터 투입 스크립트

Usage:
    python -m regscan.scripts.seed_pdufa
    python -m regscan.scripts.seed_pdufa --file data/fda/pdufa_dates_2026.json
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from regscan.config import settings

logger = logging.getLogger(__name__)


async def seed_pdufa(json_path: Path | None = None) -> int:
    """JSON 파일에서 PDUFA 일정을 DB에 upsert.

    Args:
        json_path: JSON 시드 파일 경로. None이면 기본 경로 사용.

    Returns:
        upsert된 건수
    """
    if json_path is None:
        json_path = settings.DATA_DIR / "fda" / "pdufa_dates_2026.json"

    if not json_path.exists():
        logger.warning("PDUFA 시드 파일 없음: %s", json_path)
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not items:
        logger.info("PDUFA 시드 데이터 0건")
        return 0

    from regscan.db.database import init_db, get_async_session
    from regscan.db.models import PdufaDateDB
    from sqlalchemy import select

    await init_db()

    count = 0
    async with get_async_session()() as session:
        async with session.begin():
            for item in items:
                inn = item.get("inn", "")
                pdufa_date_str = item.get("pdufa_date", "")
                if not inn or not pdufa_date_str:
                    continue

                pdufa_date = datetime.strptime(pdufa_date_str, "%Y-%m-%d").date()

                # 기존 데이터 확인 (inn + pdufa_date 기준)
                stmt = select(PdufaDateDB).where(
                    PdufaDateDB.inn == inn,
                    PdufaDateDB.pdufa_date == pdufa_date,
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # update
                    existing.brand_name = item.get("brand_name", "")
                    existing.company = item.get("company", "")
                    existing.indication = item.get("indication", "")
                    existing.application_type = item.get("application_type", "")
                    existing.status = item.get("status", "pending")
                    existing.updated_at = datetime.utcnow()
                else:
                    # insert
                    row = PdufaDateDB(
                        inn=inn,
                        brand_name=item.get("brand_name", ""),
                        company=item.get("company", ""),
                        pdufa_date=pdufa_date,
                        indication=item.get("indication", ""),
                        application_type=item.get("application_type", ""),
                        status=item.get("status", "pending"),
                    )
                    session.add(row)

                count += 1

    logger.info("PDUFA 시드 완료: %d건 upsert", count)
    return count


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    json_path = None
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        json_path = Path(sys.argv[2])

    count = asyncio.run(seed_pdufa(json_path))
    print(f"PDUFA 시드 완료: {count}건")


if __name__ == "__main__":
    main()
