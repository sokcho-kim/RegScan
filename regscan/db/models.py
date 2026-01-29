"""DB 모델"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy Base"""
    pass


class FeedCardDB(Base):
    """Feed Card DB 모델"""

    __tablename__ = "feed_cards"

    # 식별
    id = Column(String(50), primary_key=True)
    source_type = Column(String(30), nullable=False, index=True)

    # 콘텐츠
    title = Column(String(100), nullable=False)
    summary = Column(String(200))
    why_it_matters = Column(String(100))
    why_it_matters_method = Column(String(20))  # 'llm' or 'template'

    # 분류
    change_type = Column(String(20))
    domain = Column(Text)  # JSON array string
    impact_level = Column(String(10), index=True)

    # 시간
    published_at = Column(DateTime, index=True)
    effective_at = Column(DateTime)
    collected_at = Column(DateTime, index=True)

    # 출처 (JSON string)
    citation_source_id = Column(String(100))
    citation_source_url = Column(String(500))
    citation_source_title = Column(String(200))
    citation_version = Column(String(50))
    citation_snapshot_date = Column(String(20))

    # 개인화
    tags = Column(Text)  # JSON array string
    target_roles = Column(Text)  # JSON array string

    # 메타
    raw_data = Column(Text)  # 원본 JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_source_published", "source_type", "published_at"),
    )

    def __repr__(self):
        return f"<FeedCardDB {self.id}: {self.title[:30]}...>"
