"""DB 모델 — 6개 정규화 테이블 + FeedCardDB(레거시)

테이블 구조:
  drugs              — 약물 마스터 (INN 기준 1행)
  regulatory_events  — FDA/EMA/MFDS 승인 이벤트
  hira_reimbursements — HIRA 급여 정보
  clinical_trials    — CRIS 임상시험
  briefing_reports   — LLM 브리핑
  scan_snapshots     — 수집 메타 (GCS 경로)
  feed_cards         — 피드 카드 (레거시, 이번 범위 외)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, DateTime, Text, Index, Integer,
    Boolean, Float, Date, ForeignKey, JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy Base"""
    pass


# ──────────────────────────────────────────────
# 1. drugs — 약물 마스터
# ──────────────────────────────────────────────

class DrugDB(Base):
    """약물 마스터 (INN 기준 1행)"""

    __tablename__ = "drugs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inn = Column(String(200), nullable=False, unique=True, index=True)
    normalized_name = Column(String(200), index=True)
    atc_code = Column(String(20), index=True)

    # 분석 결과
    global_score = Column(Integer, default=0)
    hot_issue_level = Column(String(10))       # HOT / HIGH / MID / LOW
    hot_issue_reasons = Column(JSON, default=list)
    domestic_status = Column(String(30))       # DomesticStatus enum value
    who_eml = Column(Boolean, default=False)

    # 메타
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships
    events = relationship("RegulatoryEventDB", back_populates="drug", cascade="all, delete-orphan")
    hira = relationship("HIRAReimbursementDB", back_populates="drug", cascade="all, delete-orphan")
    trials = relationship("ClinicalTrialDB", back_populates="drug", cascade="all, delete-orphan")
    briefings = relationship("BriefingReportDB", back_populates="drug", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_drugs_score", "global_score", "hot_issue_level"),
    )


# ──────────────────────────────────────────────
# 2. regulatory_events — 규제 이벤트
# ──────────────────────────────────────────────

class RegulatoryEventDB(Base):
    """규제기관 승인 이벤트 (FDA/EMA/MFDS 각각 별도 행)"""

    __tablename__ = "regulatory_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    agency = Column(String(10), nullable=False, index=True)   # fda / ema / mfds
    status = Column(String(20))                                # approved / pending / ...
    approval_date = Column(Date)
    application_number = Column(String(50))
    brand_name = Column(String(200))

    # 특수 지정
    is_orphan = Column(Boolean, default=False)
    is_breakthrough = Column(Boolean, default=False)
    is_accelerated = Column(Boolean, default=False)
    is_priority = Column(Boolean, default=False)
    is_prime = Column(Boolean, default=False)
    is_conditional = Column(Boolean, default=False)
    is_fast_track = Column(Boolean, default=False)

    source_url = Column(String(500))
    raw_data = Column(JSON)
    collected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="events")

    __table_args__ = (
        Index("idx_event_agency_drug", "drug_id", "agency", unique=True),
    )


# ──────────────────────────────────────────────
# 3. hira_reimbursements — 급여 정보
# ──────────────────────────────────────────────

class HIRAReimbursementDB(Base):
    """HIRA 급여 정보"""

    __tablename__ = "hira_reimbursements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20))                  # reimbursed / deleted / not_covered / not_found
    ingredient_code = Column(String(20))
    price_ceiling = Column(Float)
    criteria = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="hira")


# ──────────────────────────────────────────────
# 4. clinical_trials — CRIS 임상
# ──────────────────────────────────────────────

class ClinicalTrialDB(Base):
    """CRIS 임상시험"""

    __tablename__ = "clinical_trials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    trial_id = Column(String(50), index=True)
    title = Column(Text)
    phase = Column(String(20))
    status = Column(String(30))
    indication = Column(Text)
    sponsor = Column(String(200))

    drug = relationship("DrugDB", back_populates="trials")

    __table_args__ = (
        Index("idx_trial_drug_id", "drug_id", "trial_id", unique=True),
    )


# ──────────────────────────────────────────────
# 5. briefing_reports — LLM 브리핑
# ──────────────────────────────────────────────

class BriefingReportDB(Base):
    """LLM 브리핑 리포트"""

    __tablename__ = "briefing_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    inn = Column(String(200), index=True)      # 조회 편의용 비정규화
    headline = Column(Text)
    subtitle = Column(Text)
    key_points = Column(JSON, default=list)
    global_section = Column(Text)
    domestic_section = Column(Text)
    medclaim_section = Column(Text)
    generated_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="briefings")


# ──────────────────────────────────────────────
# 6. scan_snapshots — 수집 메타
# ──────────────────────────────────────────────

class ScanSnapshotDB(Base):
    """수집 스냅샷 메타 (GCS 경로 참조)"""

    __tablename__ = "scan_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(30), nullable=False, index=True)   # fda / ema / mfds / cris
    scan_date = Column(Date, nullable=False, index=True)
    record_count = Column(Integer, default=0)
    gcs_path = Column(String(500))              # gs://bucket/raw/fda/2026-02-06.json
    checksum = Column(String(64))
    collected_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_snapshot_source_date", "source_type", "scan_date"),
    )


# ──────────────────────────────────────────────
# 레거시: feed_cards (기존 FeedCardDB 유지)
# ──────────────────────────────────────────────

class FeedCardDB(Base):
    """Feed Card DB 모델 (레거시 — 피드 시스템용)"""

    __tablename__ = "feed_cards"

    id = Column(String(50), primary_key=True)
    source_type = Column(String(30), nullable=False, index=True)

    title = Column(String(100), nullable=False)
    summary = Column(String(200))
    why_it_matters = Column(String(100))
    why_it_matters_method = Column(String(20))

    change_type = Column(String(20))
    domain = Column(Text)
    impact_level = Column(String(10), index=True)

    published_at = Column(DateTime, index=True)
    effective_at = Column(DateTime)
    collected_at = Column(DateTime, index=True)

    citation_source_id = Column(String(100))
    citation_source_url = Column(String(500))
    citation_source_title = Column(String(200))
    citation_version = Column(String(50))
    citation_snapshot_date = Column(String(20))

    tags = Column(Text)
    target_roles = Column(Text)

    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_source_published", "source_type", "published_at"),
    )

    def __repr__(self):
        return f"<FeedCardDB {self.id}: {self.title[:30]}...>"
