"""HIRA 약제 기준정보 로더 — hira_drug_info 테이블 upsert

사용법:
    loader = HIRADrugInfoLoader()
    stats = await loader.upsert_batch(records)
    # stats = {"inserted": 5, "updated": 2, "skipped": 0}
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regscan.db.database import get_async_session
from regscan.db.models import HIRADrugInfoDB

logger = logging.getLogger(__name__)


class HIRADrugInfoLoader:
    """HIRA 약제 기준정보 DB 적재기"""

    def __init__(self) -> None:
        self._session_factory = get_async_session()

    async def upsert_batch(self, records: list[dict]) -> dict:
        """레코드 배치 upsert. post_id + board 조합이 unique key.

        Returns:
            {"inserted": N, "updated": N, "skipped": N}
        """
        stats = {"inserted": 0, "updated": 0, "skipped": 0}

        async with self._session_factory() as session:
            async with session.begin():
                for record in records:
                    try:
                        result = await self._upsert_one(session, record)
                        stats[result] += 1
                    except Exception as e:
                        logger.error(f"upsert 실패: {record.get('title', '')[:50]}: {e}")
                        stats["skipped"] += 1

        logger.info(
            f"[HIRADrugInfoLoader] 적재 완료: "
            f"+{stats['inserted']} / ~{stats['updated']} / x{stats['skipped']}"
        )
        return stats

    async def _upsert_one(self, session: AsyncSession, record: dict) -> str:
        """단건 upsert. Returns 'inserted' | 'updated' | 'skipped'"""
        board = record.get("board", "")
        # post_id가 없으��� title + date 조합으로 식별
        post_id = record.get("post_id", "") or record.get("metadata", {}).get("post_id", "")

        if not board:
            return "skipped"

        # 기존 레코드 조회
        if post_id:
            stmt = select(HIRADrugInfoDB).where(
                HIRADrugInfoDB.board == board,
                HIRADrugInfoDB.post_id == post_id,
            )
        else:
            stmt = select(HIRADrugInfoDB).where(
                HIRADrugInfoDB.board == board,
                HIRADrugInfoDB.title == record.get("title", ""),
            )

        result = await session.execute(stmt)
        existing: Optional[HIRADrugInfoDB] = result.scalar_one_or_none()

        # 공통 필드
        pub_date = self._parse_date(record.get("publication_date", ""))
        metadata = record.get("metadata", {})

        if existing:
            existing.content = record.get("content", existing.content)
            existing.publication_date = pub_date or existing.publication_date
            existing.url = record.get("url", existing.url)
            existing.attachments = record.get("files", existing.attachments)
            existing.raw_metadata = metadata
            # 평가위 필드 업데이트
            if metadata.get("ingredient"):
                existing.ingredient = metadata["ingredient"]
                existing.product_name = metadata.get("product", existing.product_name)
                existing.company = metadata.get("company", existing.company)
                existing.evaluation_result = metadata.get("result", existing.evaluation_result)
                existing.session = metadata.get("session", existing.session)
            return "updated"

        # 신규 INSERT
        row = HIRADrugInfoDB(
            board=board,
            source_type=record.get("source_type", "HIRA_DRUG_INFO"),
            post_id=post_id,
            title=record.get("title", ""),
            content=record.get("content", ""),
            publication_date=pub_date,
            url=record.get("url", ""),
            ingredient=metadata.get("ingredient"),
            product_name=metadata.get("product"),
            company=metadata.get("company"),
            evaluation_result=metadata.get("result"),
            session=metadata.get("session"),
            attachments=record.get("files", []),
            department=metadata.get("department"),
            raw_metadata=metadata,
        )
        session.add(row)
        return "inserted"

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """날짜 문자열 → date"""
        if not date_str:
            return None
        date_str = date_str.replace(".", "-").strip()
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None
