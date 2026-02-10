"""DB 모델 — 11개 정규화 테이블 + FeedCardDB(레거시)

테이블 구조:
  drugs              — 약물 마스터 (INN 기준 1행)
  regulatory_events  — FDA/EMA/MFDS 승인 이벤트
  hira_reimbursements — HIRA 급여 정보
  clinical_trials    — CRIS 임상시험
  briefing_reports   — LLM 브리핑
  scan_snapshots     — 수집 메타 (GCS 경로)
  feed_cards         — 피드 카드 (레거시, 이번 범위 외)

  # v2 신규 테이블
  preprints          — bioRxiv/medRxiv 프리프린트 논문
  market_reports     — ASTI/KISTI 시장 리포트
  expert_opinions    — Health.kr 전문가 리뷰
  ai_insights        — AI 3단 파이프라인 추론·검증 결과
  articles           — AI 기사 (GPT-5.2 Writer)
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

    # relationships — v1
    events = relationship("RegulatoryEventDB", back_populates="drug", cascade="all, delete-orphan")
    hira = relationship("HIRAReimbursementDB", back_populates="drug", cascade="all, delete-orphan")
    trials = relationship("ClinicalTrialDB", back_populates="drug", cascade="all, delete-orphan")
    briefings = relationship("BriefingReportDB", back_populates="drug", cascade="all, delete-orphan")

    # relationships — v2
    preprints = relationship("PreprintDB", back_populates="drug", cascade="all, delete-orphan")
    market_reports = relationship("MarketReportDB", back_populates="drug", cascade="all, delete-orphan")
    expert_opinions = relationship("ExpertOpinionDB", back_populates="drug", cascade="all, delete-orphan")
    ai_insights = relationship("AIInsightDB", back_populates="drug", cascade="all, delete-orphan")
    articles = relationship("ArticleDB", back_populates="drug", cascade="all, delete-orphan")

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
# 7. preprints — bioRxiv/medRxiv 논문 (v2)
# ──────────────────────────────────────────────

class PreprintDB(Base):
    """bioRxiv/medRxiv 프리프린트 논문"""

    __tablename__ = "preprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    doi = Column(String(200), unique=True, index=True)
    title = Column(Text, nullable=False)
    authors = Column(Text)                    # 세미콜론 구분
    abstract = Column(Text)
    server = Column(String(20))               # biorxiv / medrxiv
    category = Column(String(100))
    published_date = Column(Date)
    pdf_url = Column(String(500))
    gemini_parsed = Column(Boolean, default=False)
    extracted_facts = Column(JSON)            # Gemini 파싱 결과
    collected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="preprints")

    __table_args__ = (
        Index("idx_preprint_drug_date", "drug_id", "published_date"),
    )


# ──────────────────────────────────────────────
# 8. market_reports — ASTI/KISTI 시장 리포트 (v2)
# ──────────────────────────────────────────────

class MarketReportDB(Base):
    """ASTI/KISTI 시장 리포트"""

    __tablename__ = "market_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(30), nullable=False)       # ASTI / KISTI
    title = Column(Text, nullable=False)
    publisher = Column(String(200))
    published_date = Column(Date)
    market_size_krw = Column(Float)                    # 시장 규모 (억 원)
    growth_rate = Column(Float)                        # 성장률 (%)
    summary = Column(Text)
    source_url = Column(String(500))
    raw_data = Column(JSON)
    collected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="market_reports")

    __table_args__ = (
        Index("idx_market_drug_source", "drug_id", "source"),
    )


# ──────────────────────────────────────────────
# 9. expert_opinions — Health.kr 전문가 리뷰 (v2)
# ──────────────────────────────────────────────

class ExpertOpinionDB(Base):
    """Health.kr 전문가 리뷰"""

    __tablename__ = "expert_opinions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(30), nullable=False)       # KPIC / 약사저널 등
    title = Column(Text, nullable=False)
    author = Column(String(200))
    summary = Column(Text)
    published_date = Column(Date)
    source_url = Column(String(500))
    raw_data = Column(JSON)
    collected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="expert_opinions")

    __table_args__ = (
        Index("idx_expert_drug_source", "drug_id", "source"),
    )


# ──────────────────────────────────────────────
# 10. ai_insights — AI 추론·검증 결과 (v2)
# ──────────────────────────────────────────────

class AIInsightDB(Base):
    """AI 3단 파이프라인 추론 + 검증 결과"""

    __tablename__ = "ai_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Reasoning (o4-mini)
    impact_score = Column(Integer)
    risk_factors = Column(JSON, default=list)
    opportunity_factors = Column(JSON, default=list)
    reasoning_chain = Column(Text)
    market_forecast = Column(Text)
    reasoning_model = Column(String(50))
    reasoning_tokens = Column(Integer)

    # Verification (GPT-5.2)
    verified_score = Column(Integer)
    corrections = Column(JSON, default=list)
    confidence_level = Column(String(20))     # high / medium / low
    verifier_model = Column(String(50))
    verifier_tokens = Column(Integer)

    generated_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="ai_insights")

    __table_args__ = (
        Index("idx_insight_drug_date", "drug_id", "generated_at"),
    )


# ──────────────────────────────────────────────
# 11. articles — AI 기사 (v2)
# ──────────────────────────────────────────────

class ArticleDB(Base):
    """GPT-5.2 Writer가 생성한 기사"""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    article_type = Column(String(30), nullable=False)  # briefing / newsletter / press_release
    headline = Column(Text, nullable=False)
    subtitle = Column(Text)
    lead_paragraph = Column(Text)
    body_html = Column(Text)
    tags = Column(JSON, default=list)
    writer_model = Column(String(50))
    writer_tokens = Column(Integer)
    generated_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="articles")

    __table_args__ = (
        Index("idx_article_drug_type", "drug_id", "article_type"),
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
