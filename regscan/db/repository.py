"""Feed Card 저장소"""

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from regscan.models import FeedCard
from .models import FeedCardDB, Base


class FeedCardRepository:
    """Feed Card 저장소"""

    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self) -> None:
        """DB 테이블 생성"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save(self, card: FeedCard, raw_data: Optional[dict] = None) -> None:
        """카드 저장 (upsert)"""
        async with self.async_session() as session:
            # 기존 레코드 확인
            existing = await session.get(FeedCardDB, card.id)

            db_card = existing or FeedCardDB(id=card.id)

            # 필드 매핑
            db_card.source_type = card.source_type.value
            db_card.title = card.title
            db_card.summary = card.summary
            db_card.why_it_matters = card.why_it_matters
            db_card.change_type = card.change_type.value
            db_card.domain = json.dumps([d.value for d in card.domain])
            db_card.impact_level = card.impact_level.value
            db_card.published_at = card.published_at
            db_card.effective_at = card.effective_at
            db_card.collected_at = card.collected_at

            # Citation
            db_card.citation_source_id = card.citation.source_id
            db_card.citation_source_url = card.citation.source_url
            db_card.citation_source_title = card.citation.source_title
            db_card.citation_version = card.citation.version
            db_card.citation_snapshot_date = card.citation.snapshot_date

            # 개인화
            db_card.tags = json.dumps(card.tags)
            db_card.target_roles = json.dumps([r.value for r in card.target_roles])

            # 원본 데이터
            if raw_data:
                db_card.raw_data = json.dumps(raw_data, ensure_ascii=False)

            if not existing:
                session.add(db_card)

            await session.commit()

    async def save_many(self, cards: list[FeedCard], raw_data_list: Optional[list[dict]] = None) -> int:
        """여러 카드 저장"""
        raw_data_list = raw_data_list or [None] * len(cards)
        for card, raw_data in zip(cards, raw_data_list):
            await self.save(card, raw_data)
        return len(cards)

    async def get_by_id(self, card_id: str) -> Optional[FeedCard]:
        """ID로 조회"""
        async with self.async_session() as session:
            db_card = await session.get(FeedCardDB, card_id)
            if db_card:
                return self._to_feed_card(db_card)
            return None

    async def get_recent(
        self,
        limit: int = 10,
        source_type: Optional[str] = None,
        impact_level: Optional[str] = None,
    ) -> list[FeedCard]:
        """최근 카드 조회"""
        async with self.async_session() as session:
            stmt = select(FeedCardDB).order_by(FeedCardDB.published_at.desc())

            if source_type:
                stmt = stmt.where(FeedCardDB.source_type == source_type)
            if impact_level:
                stmt = stmt.where(FeedCardDB.impact_level == impact_level)

            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            db_cards = result.scalars().all()

            return [self._to_feed_card(db) for db in db_cards]

    async def get_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        source_type: Optional[str] = None,
    ) -> list[FeedCard]:
        """날짜 범위로 조회"""
        async with self.async_session() as session:
            stmt = select(FeedCardDB).where(
                and_(
                    FeedCardDB.published_at >= start_date,
                    FeedCardDB.published_at <= end_date,
                )
            ).order_by(FeedCardDB.published_at.desc())

            if source_type:
                stmt = stmt.where(FeedCardDB.source_type == source_type)

            result = await session.execute(stmt)
            db_cards = result.scalars().all()

            return [self._to_feed_card(db) for db in db_cards]

    async def get_by_source(
        self,
        source_type,
        limit: int = 20,
    ) -> list[FeedCard]:
        """소스 타입별 조회"""
        async with self.async_session() as session:
            stmt = (
                select(FeedCardDB)
                .where(FeedCardDB.source_type == source_type.value)
                .order_by(FeedCardDB.published_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            db_cards = result.scalars().all()

            return [self._to_feed_card(db) for db in db_cards]

    async def count(self, source_type=None) -> int:
        """카드 수 조회"""
        async with self.async_session() as session:
            from sqlalchemy import func
            stmt = select(func.count(FeedCardDB.id))
            if source_type:
                stmt = stmt.where(FeedCardDB.source_type == source_type.value)
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def get_today(self, source_type: Optional[str] = None) -> list[FeedCard]:
        """오늘 수집된 카드 조회"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        async with self.async_session() as session:
            stmt = select(FeedCardDB).where(
                and_(
                    FeedCardDB.collected_at >= today_start,
                    FeedCardDB.collected_at < today_end,
                )
            ).order_by(FeedCardDB.impact_level)

            if source_type:
                stmt = stmt.where(FeedCardDB.source_type == source_type)

            result = await session.execute(stmt)
            db_cards = result.scalars().all()

            return [self._to_feed_card(db) for db in db_cards]

    def _to_feed_card(self, db_card: FeedCardDB) -> FeedCard:
        """DB 모델 → FeedCard 변환"""
        from regscan.models import (
            Citation, ChangeType, Domain, ImpactLevel, SourceType, Role
        )

        return FeedCard(
            id=db_card.id,
            source_type=SourceType(db_card.source_type),
            title=db_card.title,
            summary=db_card.summary or "",
            why_it_matters=db_card.why_it_matters or "",
            change_type=ChangeType(db_card.change_type) if db_card.change_type else ChangeType.INFO,
            domain=[Domain(d) for d in json.loads(db_card.domain or "[]")],
            impact_level=ImpactLevel(db_card.impact_level) if db_card.impact_level else ImpactLevel.LOW,
            published_at=db_card.published_at or datetime.now(),
            effective_at=db_card.effective_at,
            collected_at=db_card.collected_at or datetime.now(),
            citation=Citation(
                source_id=db_card.citation_source_id or "",
                source_url=db_card.citation_source_url or "",
                source_title=db_card.citation_source_title or "",
                version=db_card.citation_version,
                snapshot_date=db_card.citation_snapshot_date or "",
            ),
            tags=json.loads(db_card.tags or "[]"),
            target_roles=[Role(r) for r in json.loads(db_card.target_roles or "[]")],
        )
