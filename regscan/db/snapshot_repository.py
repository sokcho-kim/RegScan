"""스냅샷 저장소 - 원본 데이터 버전 관리"""

import hashlib
import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from .models import SnapshotDB, Base


class SnapshotRepository:
    """원본 데이터 스냅샷 저장소"""

    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self) -> None:
        """DB 테이블 생성"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def _compute_checksum(self, data: dict) -> str:
        """데이터 체크섬 계산"""
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode()).hexdigest()

    async def save(
        self,
        source_type: str,
        source_id: str,
        raw_data: dict,
        snapshot_date: Optional[date] = None,
    ) -> bool:
        """
        스냅샷 저장

        Returns:
            True if new/changed, False if unchanged
        """
        snapshot_date = snapshot_date or date.today()
        checksum = self._compute_checksum(raw_data)

        async with self.async_session() as session:
            # 기존 스냅샷 확인 (같은 날짜)
            stmt = select(SnapshotDB).where(
                and_(
                    SnapshotDB.source_type == source_type,
                    SnapshotDB.source_id == source_id,
                    SnapshotDB.snapshot_date == snapshot_date,
                )
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # 변경 확인
                if existing.checksum == checksum:
                    return False  # 변경 없음

                # 업데이트
                existing.raw_data = json.dumps(raw_data, ensure_ascii=False)
                existing.checksum = checksum
                existing.collected_at = datetime.utcnow()
            else:
                # 신규 생성
                snapshot = SnapshotDB(
                    source_type=source_type,
                    source_id=source_id,
                    snapshot_date=snapshot_date,
                    raw_data=json.dumps(raw_data, ensure_ascii=False),
                    checksum=checksum,
                )
                session.add(snapshot)

            await session.commit()
            return True

    async def save_many(
        self,
        source_type: str,
        items: list[dict],
        id_field: str,
        snapshot_date: Optional[date] = None,
    ) -> dict:
        """
        여러 스냅샷 저장

        Args:
            source_type: 소스 타입 (FDA, EMA 등)
            items: 원본 데이터 목록
            id_field: ID 필드명 (예: 'application_number', 'ema_product_number')
            snapshot_date: 스냅샷 날짜

        Returns:
            {'new': int, 'changed': int, 'unchanged': int}
        """
        snapshot_date = snapshot_date or date.today()
        stats = {'new': 0, 'changed': 0, 'unchanged': 0}

        for item in items:
            source_id = item.get(id_field, "")
            if not source_id:
                continue

            changed = await self.save(source_type, source_id, item, snapshot_date)
            if changed:
                stats['new'] += 1  # new or changed
            else:
                stats['unchanged'] += 1

        return stats

    async def get_latest(
        self,
        source_type: str,
        source_id: str,
    ) -> Optional[dict]:
        """최신 스냅샷 조회"""
        async with self.async_session() as session:
            stmt = (
                select(SnapshotDB)
                .where(
                    and_(
                        SnapshotDB.source_type == source_type,
                        SnapshotDB.source_id == source_id,
                    )
                )
                .order_by(SnapshotDB.snapshot_date.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot:
                return json.loads(snapshot.raw_data)
            return None

    async def get_history(
        self,
        source_type: str,
        source_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """스냅샷 히스토리 조회"""
        async with self.async_session() as session:
            stmt = (
                select(SnapshotDB)
                .where(
                    and_(
                        SnapshotDB.source_type == source_type,
                        SnapshotDB.source_id == source_id,
                    )
                )
                .order_by(SnapshotDB.snapshot_date.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

            return [
                {
                    'snapshot_date': s.snapshot_date.isoformat(),
                    'collected_at': s.collected_at.isoformat() if s.collected_at else None,
                    'data': json.loads(s.raw_data),
                }
                for s in snapshots
            ]

    async def get_by_date(
        self,
        source_type: str,
        snapshot_date: date,
        limit: int = 1000,
    ) -> list[dict]:
        """특정 날짜 스냅샷 조회"""
        async with self.async_session() as session:
            stmt = (
                select(SnapshotDB)
                .where(
                    and_(
                        SnapshotDB.source_type == source_type,
                        SnapshotDB.snapshot_date == snapshot_date,
                    )
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            snapshots = result.scalars().all()

            return [json.loads(s.raw_data) for s in snapshots]

    async def count_by_source(self, source_type: str) -> int:
        """소스별 스냅샷 수"""
        async with self.async_session() as session:
            from sqlalchemy import func
            stmt = select(func.count(SnapshotDB.id)).where(
                SnapshotDB.source_type == source_type
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
