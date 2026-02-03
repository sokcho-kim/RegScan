"""GlobalRegulatoryStatus 저장소"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from regscan.map.global_status import (
    GlobalRegulatoryStatus,
    RegulatoryApproval,
    ApprovalStatus,
    HotIssueLevel,
)
from .models import GlobalStatusDB, Base


class GlobalStatusRepository:
    """GlobalRegulatoryStatus 저장소"""

    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self) -> None:
        """DB 테이블 생성"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save(self, status: GlobalRegulatoryStatus) -> None:
        """GlobalRegulatoryStatus 저장 (upsert by INN)"""
        async with self.async_session() as session:
            # 기존 레코드 확인 (normalized_name으로)
            stmt = select(GlobalStatusDB).where(
                GlobalStatusDB.normalized_name == status.normalized_name
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            db_status = existing or GlobalStatusDB()

            # 기본 정보
            db_status.inn = status.inn
            db_status.normalized_name = status.normalized_name
            db_status.atc_code = status.atc_code

            # FDA
            if status.fda:
                db_status.fda_status = status.fda.status.value
                db_status.fda_approval_date = status.fda.approval_date
                db_status.fda_application_number = status.fda.application_number
                db_status.fda_brand_name = status.fda.brand_name
                db_status.fda_is_orphan = status.fda.is_orphan
                db_status.fda_is_breakthrough = status.fda.is_breakthrough
                db_status.fda_is_accelerated = status.fda.is_accelerated
                db_status.fda_source_url = status.fda.source_url

            # EMA
            if status.ema:
                db_status.ema_status = status.ema.status.value
                db_status.ema_approval_date = status.ema.approval_date
                db_status.ema_product_number = status.ema.application_number
                db_status.ema_brand_name = status.ema.brand_name
                db_status.ema_is_orphan = status.ema.is_orphan
                db_status.ema_is_prime = status.ema.is_prime
                db_status.ema_is_accelerated = status.ema.is_accelerated
                db_status.ema_is_conditional = status.ema.is_conditional
                db_status.ema_source_url = status.ema.source_url

            # MFDS
            if status.mfds:
                db_status.mfds_status = status.mfds.status.value
                db_status.mfds_approval_date = status.mfds.approval_date
                db_status.mfds_item_seq = status.mfds.application_number

            # 분석 결과
            db_status.global_score = status.global_score
            db_status.hot_issue_level = status.hot_issue_level.value
            db_status.hot_issue_reasons = json.dumps(status.hot_issue_reasons, ensure_ascii=False)

            # WHO
            db_status.who_eml = status.who_eml

            if not existing:
                session.add(db_status)

            await session.commit()

    async def save_many(self, statuses: list[GlobalRegulatoryStatus]) -> int:
        """여러 GlobalRegulatoryStatus 저장"""
        for status in statuses:
            await self.save(status)
        return len(statuses)

    async def get_by_inn(self, inn: str) -> Optional[GlobalRegulatoryStatus]:
        """INN으로 조회"""
        from regscan.map.matcher import IngredientMatcher
        matcher = IngredientMatcher()
        normalized = matcher.normalize(inn)

        async with self.async_session() as session:
            stmt = select(GlobalStatusDB).where(
                GlobalStatusDB.normalized_name == normalized
            )
            result = await session.execute(stmt)
            db_status = result.scalar_one_or_none()

            if db_status:
                return self._to_global_status(db_status)
            return None

    async def get_hot_issues(
        self,
        min_score: int = 60,
        limit: int = 20,
    ) -> list[GlobalRegulatoryStatus]:
        """핫이슈 목록 조회"""
        async with self.async_session() as session:
            stmt = (
                select(GlobalStatusDB)
                .where(GlobalStatusDB.global_score >= min_score)
                .order_by(GlobalStatusDB.global_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            db_statuses = result.scalars().all()

            return [self._to_global_status(db) for db in db_statuses]

    async def get_by_level(
        self,
        level: HotIssueLevel,
        limit: int = 50,
    ) -> list[GlobalRegulatoryStatus]:
        """등급별 조회"""
        async with self.async_session() as session:
            stmt = (
                select(GlobalStatusDB)
                .where(GlobalStatusDB.hot_issue_level == level.value)
                .order_by(GlobalStatusDB.global_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            db_statuses = result.scalars().all()

            return [self._to_global_status(db) for db in db_statuses]

    async def get_multi_approved(self, min_agencies: int = 2) -> list[GlobalRegulatoryStatus]:
        """다중 승인 약물 조회"""
        async with self.async_session() as session:
            # FDA와 EMA 모두 승인된 경우
            stmt = (
                select(GlobalStatusDB)
                .where(
                    and_(
                        GlobalStatusDB.fda_status == 'approved',
                        GlobalStatusDB.ema_status == 'approved',
                    )
                )
                .order_by(GlobalStatusDB.global_score.desc())
            )
            result = await session.execute(stmt)
            db_statuses = result.scalars().all()

            return [self._to_global_status(db) for db in db_statuses]

    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[GlobalRegulatoryStatus]:
        """검색 (INN, 브랜드명)"""
        async with self.async_session() as session:
            pattern = f"%{query.lower()}%"
            stmt = (
                select(GlobalStatusDB)
                .where(
                    or_(
                        GlobalStatusDB.inn.ilike(pattern),
                        GlobalStatusDB.normalized_name.ilike(pattern),
                        GlobalStatusDB.fda_brand_name.ilike(pattern),
                        GlobalStatusDB.ema_brand_name.ilike(pattern),
                    )
                )
                .order_by(GlobalStatusDB.global_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            db_statuses = result.scalars().all()

            return [self._to_global_status(db) for db in db_statuses]

    async def count(self) -> dict:
        """통계"""
        async with self.async_session() as session:
            from sqlalchemy import func

            # 전체 수
            total_stmt = select(func.count(GlobalStatusDB.id))
            total = (await session.execute(total_stmt)).scalar() or 0

            # 등급별 수
            level_counts = {}
            for level in ['HOT', 'HIGH', 'MID', 'LOW']:
                stmt = select(func.count(GlobalStatusDB.id)).where(
                    GlobalStatusDB.hot_issue_level == level
                )
                count = (await session.execute(stmt)).scalar() or 0
                level_counts[level] = count

            return {
                'total': total,
                'by_level': level_counts,
            }

    def _to_global_status(self, db: GlobalStatusDB) -> GlobalRegulatoryStatus:
        """DB 모델 → GlobalRegulatoryStatus 변환"""
        fda = None
        if db.fda_status:
            fda = RegulatoryApproval(
                agency="FDA",
                status=ApprovalStatus(db.fda_status),
                approval_date=db.fda_approval_date,
                application_number=db.fda_application_number or "",
                brand_name=db.fda_brand_name or "",
                is_orphan=db.fda_is_orphan or False,
                is_breakthrough=db.fda_is_breakthrough or False,
                is_accelerated=db.fda_is_accelerated or False,
                source_url=db.fda_source_url or "",
            )

        ema = None
        if db.ema_status:
            ema = RegulatoryApproval(
                agency="EMA",
                status=ApprovalStatus(db.ema_status),
                approval_date=db.ema_approval_date,
                application_number=db.ema_product_number or "",
                brand_name=db.ema_brand_name or "",
                is_orphan=db.ema_is_orphan or False,
                is_prime=db.ema_is_prime or False,
                is_accelerated=db.ema_is_accelerated or False,
                is_conditional=db.ema_is_conditional or False,
                source_url=db.ema_source_url or "",
            )

        mfds = None
        if db.mfds_status:
            mfds = RegulatoryApproval(
                agency="MFDS",
                status=ApprovalStatus(db.mfds_status),
                approval_date=db.mfds_approval_date,
                application_number=db.mfds_item_seq or "",
            )

        return GlobalRegulatoryStatus(
            inn=db.inn,
            normalized_name=db.normalized_name or "",
            atc_code=db.atc_code or "",
            fda=fda,
            ema=ema,
            mfds=mfds,
            who_eml=db.who_eml or False,
            global_score=db.global_score or 0,
            hot_issue_level=HotIssueLevel(db.hot_issue_level) if db.hot_issue_level else HotIssueLevel.LOW,
            hot_issue_reasons=json.loads(db.hot_issue_reasons or "[]"),
            last_updated=db.updated_at or datetime.now(),
        )
