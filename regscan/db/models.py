"""DB 모델"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, DateTime, Text, Index, Integer, Boolean, Float, Date
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy Base"""
    pass


class SnapshotDB(Base):
    """원본 데이터 스냅샷"""

    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(30), nullable=False, index=True)  # FDA, EMA, HIRA 등
    source_id = Column(String(100), nullable=False, index=True)   # application_number, ema_product_number 등
    snapshot_date = Column(Date, nullable=False, index=True)

    # 원본 데이터
    raw_data = Column(Text, nullable=False)  # JSON

    # 메타
    collected_at = Column(DateTime, default=datetime.utcnow)
    checksum = Column(String(64))  # 데이터 변경 감지용

    __table_args__ = (
        Index("idx_snapshot_source", "source_type", "source_id", "snapshot_date"),
    )


class GlobalStatusDB(Base):
    """글로벌 규제 현황"""

    __tablename__ = "global_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inn = Column(String(200), nullable=False, index=True)           # INN (International Nonproprietary Name)
    normalized_name = Column(String(200), index=True)               # 정규화된 성분명
    atc_code = Column(String(20), index=True)                       # ATC 분류 코드

    # FDA
    fda_status = Column(String(20))           # approved, pending, withdrawn 등
    fda_approval_date = Column(Date)
    fda_application_number = Column(String(50))
    fda_brand_name = Column(String(200))
    fda_is_orphan = Column(Boolean, default=False)
    fda_is_breakthrough = Column(Boolean, default=False)
    fda_is_accelerated = Column(Boolean, default=False)
    fda_source_url = Column(String(500))

    # EMA
    ema_status = Column(String(20))
    ema_approval_date = Column(Date)
    ema_product_number = Column(String(50))
    ema_brand_name = Column(String(200))
    ema_is_orphan = Column(Boolean, default=False)
    ema_is_prime = Column(Boolean, default=False)
    ema_is_accelerated = Column(Boolean, default=False)
    ema_is_conditional = Column(Boolean, default=False)
    ema_source_url = Column(String(500))

    # MFDS (한국)
    mfds_status = Column(String(20))
    mfds_approval_date = Column(Date)
    mfds_item_seq = Column(String(50))

    # 분석 결과
    global_score = Column(Integer, default=0)           # 0-100
    hot_issue_level = Column(String(10))                # HOT, HIGH, MID, LOW
    hot_issue_reasons = Column(Text)                    # JSON array

    # WHO
    who_eml = Column(Boolean, default=False)

    # 메타
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_global_score", "global_score", "hot_issue_level"),
    )


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
