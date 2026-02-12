"""DB 모델 — 12개 정규화 테이블 + FeedCardDB(레거시)

테이블 구조:
  drugs              — 약물 마스터 (INN 기준 1행)
  regulatory_events  — FDA/EMA/MFDS 승인 이벤트
  hira_reimbursements — HIRA 급여 정보
  clinical_trials    — CRIS 임상시험
  briefing_reports   — LLM 브리핑
  scan_snapshots     — 수집 메타 (GCS 경로)
  drug_change_log    — 변경 감지 로그 (이벤트 트리거)
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
    korea_relevance_score = Column(Integer, default=0)  # 국내 연관성 점수 (0~100)
    hot_issue_level = Column(String(10))       # HOT / HIGH / MID / LOW
    hot_issue_reasons = Column(JSON, default=list)
    domestic_status = Column(String(30))       # DomesticStatus enum value
    who_eml = Column(Boolean, default=False)

    # v3: Stream 메타데이터
    therapeutic_areas = Column(String(200), default="")   # 콤마 구분 ("oncology,rare_disease")
    stream_sources = Column(JSON, default=list)           # ["therapeutic_area", "innovation"]

    # 메타
    first_seen_at = Column(DateTime, default=datetime.utcnow)   # 최초 발견 시각 (불변)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationships — v1
    events = relationship("RegulatoryEventDB", back_populates="drug", cascade="all, delete-orphan")
    hira = relationship("HIRAReimbursementDB", back_populates="drug", cascade="all, delete-orphan")
    trials = relationship("ClinicalTrialDB", back_populates="drug", cascade="all, delete-orphan")
    briefings = relationship("BriefingReportDB", back_populates="drug", cascade="all, delete-orphan")

    change_logs = relationship("DrugChangeLogDB", back_populates="drug", cascade="all, delete-orphan")

    # relationships — v2
    preprints = relationship("PreprintDB", back_populates="drug", cascade="all, delete-orphan")
    market_reports = relationship("MarketReportDB", back_populates="drug", cascade="all, delete-orphan")
    expert_opinions = relationship("ExpertOpinionDB", back_populates="drug", cascade="all, delete-orphan")
    ai_insights = relationship("AIInsightDB", back_populates="drug", cascade="all, delete-orphan")
    articles = relationship("ArticleDB", back_populates="drug", cascade="all, delete-orphan")

    # relationships — v3
    competitors = relationship("DrugCompetitorDB", back_populates="drug", cascade="all, delete-orphan")
    ct_gov_trials = relationship("ClinicalTrialGovDB", back_populates="drug", cascade="all, delete-orphan")

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
    created_at = Column(DateTime, default=datetime.utcnow)    # INSERT 시각 (불변)
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
# 7. drug_change_log — 변경 감지 로그
# ──────────────────────────────────────────────

class DrugChangeLogDB(Base):
    """약물 변경 감지 로그 (이벤트 트리거)"""

    __tablename__ = "drug_change_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    change_type = Column(String(30), nullable=False, index=True)
    # new_drug / score_change / status_change / new_event / designation_change / new_preprint
    field_name = Column(String(50))              # 변경된 필드명
    old_value = Column(String(200))              # 이전 값 (NULL이면 새 항목)
    new_value = Column(String(200))              # 새 값
    pipeline_run_id = Column(String(36))         # 파이프라인 실행 ID (UUID)
    detected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="change_logs")

    __table_args__ = (
        Index("idx_changelog_drug_type", "drug_id", "change_type"),
        Index("idx_changelog_detected", "detected_at"),
        Index("idx_changelog_run", "pipeline_run_id"),
    )


# ──────────────────────────────────────────────
# 8. preprints — bioRxiv/medRxiv 논문 (v2)
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


# ══════════════════════════════════════════════
# v3: 3-Stream Architecture 테이블
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# v3-1. stream_snapshots — 스트림 실행 스냅샷
# ──────────────────────────────────────────────

class StreamSnapshotDB(Base):
    """스트림 실행 스냅샷 (영역별 수집 결과 메타)"""

    __tablename__ = "stream_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stream_name = Column(String(50), nullable=False, index=True)  # therapeutic_area / innovation / external
    sub_category = Column(String(50), default="")                 # oncology, rare_disease, ...
    drug_count = Column(Integer, default=0)
    signal_count = Column(Integer, default=0)
    inn_list = Column(JSON, default=list)
    pipeline_run_id = Column(String(36), index=True)
    collected_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_stream_snap_name_date", "stream_name", "collected_at"),
    )


# ──────────────────────────────────────────────
# v3-2. drug_competitors — 경쟁약물 매핑
# ──────────────────────────────────────────────

class DrugCompetitorDB(Base):
    """경쟁약물 매핑 (제네릭/바이오시밀러/동일 ATC)"""

    __tablename__ = "drug_competitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True)
    competitor_inn = Column(String(200), nullable=False)
    relationship_type = Column(String(30), nullable=False)  # generic / biosimilar / same_atc
    atc_code = Column(String(20), default="")
    te_code = Column(String(20), default="")
    source = Column(String(30), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="competitors")

    __table_args__ = (
        Index("idx_competitor_drug_type", "drug_id", "relationship_type"),
    )


# ──────────────────────────────────────────────
# v3-3. pdufa_dates — PDUFA 일정
# ──────────────────────────────────────────────

class PdufaDateDB(Base):
    """PDUFA 타겟 일정 (수동 관리 + 향후 스크래핑)"""

    __tablename__ = "pdufa_dates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inn = Column(String(200), nullable=False, index=True)
    brand_name = Column(String(200), default="")
    company = Column(String(200), default="")
    pdufa_date = Column(Date, nullable=False, index=True)
    indication = Column(Text, default="")
    application_type = Column(String(10), default="")  # NDA / BLA
    status = Column(String(20), default="pending")     # pending / approved / crl
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_pdufa_date_status", "pdufa_date", "status"),
    )


# ──────────────────────────────────────────────
# v3-4. clinical_trials_gov — ClinicalTrials.gov Phase 3
# ──────────────────────────────────────────────

class ClinicalTrialGovDB(Base):
    """ClinicalTrials.gov Phase 3 임상시험 (외부시그널)"""

    __tablename__ = "clinical_trials_gov"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="SET NULL"), nullable=True, index=True)
    nct_id = Column(String(20), nullable=False, unique=True, index=True)
    title = Column(Text, default="")
    conditions = Column(JSON, default=list)
    interventions = Column(JSON, default=list)
    phase = Column(String(20), default="")
    status = Column(String(30), default="")           # COMPLETED / TERMINATED / SUSPENDED
    completion_date = Column(Date, nullable=True)
    results_posted_date = Column(Date, nullable=True)
    why_stopped = Column(Text, default="")
    sponsor = Column(String(300), default="")
    enrollment = Column(Integer, nullable=True)

    # Triage 결과
    verdict = Column(String(20), nullable=True)       # FAIL / PENDING / SUCCESS / FAIL_BY_AI
    verdict_summary = Column(Text, default="")
    verdict_confidence = Column(Float, nullable=True)
    verdicted_at = Column(DateTime, nullable=True)

    # 수집 메타
    search_condition = Column(String(200), default="")
    collected_at = Column(DateTime, default=datetime.utcnow)

    drug = relationship("DrugDB", back_populates="ct_gov_trials")

    __table_args__ = (
        Index("idx_ctgov_status_verdict", "status", "verdict"),
    )


# ──────────────────────────────────────────────
# v3-5. stream_briefings — 스트림별 브리핑
# ──────────────────────────────────────────────

class StreamBriefingDB(Base):
    """스트림별 / 통합 브리핑 리포트"""

    __tablename__ = "stream_briefings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stream_name = Column(String(50), nullable=False, index=True)
    sub_category = Column(String(50), default="")
    briefing_type = Column(String(20), nullable=False)  # stream / unified
    headline = Column(Text, default="")
    content_json = Column(JSON, default=dict)
    generated_at = Column(DateTime, default=datetime.utcnow)
    pipeline_run_id = Column(String(36), index=True)

    __table_args__ = (
        Index("idx_briefing_stream_type", "stream_name", "briefing_type"),
    )
