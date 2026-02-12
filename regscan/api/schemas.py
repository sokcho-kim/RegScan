"""API 응답 스키마"""

import math
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, field_validator


def _nan_to_none(v: Optional[float]) -> Optional[float]:
    """NaN을 None으로 변환"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


class StatsResponse(BaseModel):
    """전체 통계"""
    fda_count: int
    ema_count: int
    mfds_count: int
    cris_count: int
    hot_issues_count: int
    imminent_count: int
    reimbursed_count: int
    last_updated: datetime


class DrugSummary(BaseModel):
    """약물 요약 (목록용)"""
    inn: str
    fda_approved: bool
    ema_approved: bool
    mfds_approved: bool
    hira_reimbursed: bool
    hira_price: Optional[float] = None
    global_score: int
    korea_relevance_score: int = 0
    hot_issue_level: str
    domestic_status: str
    quadrant: str = "normal"  # top_priority / watch / track / normal

    _normalize_price = field_validator("hira_price", mode="before")(_nan_to_none)


class DrugDetail(BaseModel):
    """약물 상세"""
    inn: str

    # 글로벌 승인
    fda_approved: bool
    fda_date: Optional[date] = None
    fda_brand_name: str = ""

    ema_approved: bool
    ema_date: Optional[date] = None
    ema_brand_name: str = ""

    # 국내 현황
    mfds_approved: bool
    mfds_date: Optional[date] = None
    mfds_brand_name: str = ""

    # HIRA 급여
    hira_status: Optional[str] = None
    hira_code: str = ""
    hira_criteria: str = ""
    hira_price: Optional[float] = None

    # CRIS 임상
    cris_trial_count: int = 0
    cris_trials: list[dict] = []

    # 분석
    global_score: int
    korea_relevance_score: int = 0
    hot_issue_level: str
    hot_issue_reasons: list[str] = []
    domestic_status: str
    quadrant: str = "normal"
    analysis_notes: list[str] = []
    summary: str = ""

    _normalize_price = field_validator("hira_price", mode="before")(_nan_to_none)


class HotIssueItem(BaseModel):
    """핫이슈 항목"""
    inn: str
    global_score: int
    hot_issue_level: str
    reasons: list[str]
    fda_approved: bool
    ema_approved: bool
    mfds_approved: bool
    hira_reimbursed: bool


class ImminentDrugItem(BaseModel):
    """국내 도입 임박 약물"""
    inn: str
    global_score: int
    fda_date: Optional[date] = None
    ema_date: Optional[date] = None
    hira_status: Optional[str] = None
    hira_price: Optional[float] = None
    cris_trial_count: int
    days_since_global_approval: Optional[int] = None
    analysis_notes: list[str] = []

    _normalize_price = field_validator("hira_price", mode="before")(_nan_to_none)


class MedclaimInsight(BaseModel):
    """메드클레임 시사점"""
    inn: str

    # 급여 현황
    hira_status: Optional[str] = None
    hira_criteria: str = ""
    hira_price: Optional[float] = None

    # 분석
    is_orphan_drug: bool = False
    is_high_cost: bool = False
    estimated_burden: str = ""  # 예상 본인부담

    # 시사점
    insights: list[str] = []

    _normalize_price = field_validator("hira_price", mode="before")(_nan_to_none)


class ReportData(BaseModel):
    """브리핑 리포트 데이터"""
    inn: str
    brand_name: str = ""
    indication: str = ""

    # 핵심 요약
    key_points: list[str] = []

    # 글로벌 현황
    global_status: dict = {}

    # 국내 현황
    domestic_status: dict = {}

    # 메드클레임 시사점
    medclaim_insight: MedclaimInsight

    # 메타
    generated_at: datetime
    data_sources: list[str] = []


class BriefingReportResponse(BaseModel):
    """LLM 브리핑 리포트 응답"""
    inn: str
    headline: str
    subtitle: str
    key_points: list[str]
    global_section: str
    domestic_section: str
    medclaim_section: str
    generated_at: datetime
    markdown: str  # 마크다운 형식 전체 리포트


# ── v2 스키마 ──

class PreprintResponse(BaseModel):
    """프리프린트 논문 응답"""
    doi: str
    title: str
    authors: str = ""
    abstract: str = ""
    server: str = ""
    category: str = ""
    published_date: Optional[date] = None
    pdf_url: str = ""
    gemini_parsed: bool = False
    extracted_facts: Optional[dict] = None


class MarketReportResponse(BaseModel):
    """시장 리포트 응답"""
    source: str
    title: str
    publisher: str = ""
    published_date: Optional[date] = None
    market_size_krw: Optional[float] = None
    growth_rate: Optional[float] = None
    summary: str = ""
    source_url: str = ""


class ExpertOpinionResponse(BaseModel):
    """전문가 리뷰 응답"""
    source: str
    title: str
    author: str = ""
    summary: str = ""
    published_date: Optional[date] = None
    source_url: str = ""


class AIInsightResponse(BaseModel):
    """AI 인사이트 응답"""
    impact_score: Optional[int] = None
    risk_factors: list[str] = []
    opportunity_factors: list[str] = []
    reasoning_chain: str = ""
    market_forecast: str = ""
    reasoning_model: str = ""
    verified_score: Optional[int] = None
    corrections: list[dict] = []
    confidence_level: str = ""
    generated_at: Optional[datetime] = None


class ArticleResponse(BaseModel):
    """AI 기사 응답"""
    article_type: str
    headline: str
    subtitle: str = ""
    lead_paragraph: str = ""
    body_html: str = ""
    tags: list[str] = []
    writer_model: str = ""
    generated_at: Optional[datetime] = None


class ChangeLogResponse(BaseModel):
    """변경 감지 로그 응답"""
    id: int
    drug_id: int
    inn: str = ""
    change_type: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    detected_at: Optional[datetime] = None
