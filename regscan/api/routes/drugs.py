"""약물 조회 API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from regscan.api.deps import get_data_store, DataStore
from regscan.api.schemas import (
    DrugSummary, DrugDetail, MedclaimInsight, BriefingReportResponse,
    PreprintResponse, MarketReportResponse, ExpertOpinionResponse,
    AIInsightResponse, ArticleResponse,
)
from regscan.map.ingredient_bridge import ReimbursementStatus
from regscan.report import LLMBriefingGenerator

router = APIRouter()

# LLM 생성기 (싱글톤)
_llm_generator: LLMBriefingGenerator | None = None


def get_llm_generator() -> LLMBriefingGenerator:
    global _llm_generator
    if _llm_generator is None:
        # OpenAI 키가 있으면 OpenAI 사용, 없으면 Anthropic
        from regscan.config import settings
        if settings.OPENAI_API_KEY:
            _llm_generator = LLMBriefingGenerator(provider="openai")
        else:
            _llm_generator = LLMBriefingGenerator(provider="anthropic")
    return _llm_generator


@router.get("", response_model=list[DrugSummary])
def list_drugs(
    offset: int = 0,
    limit: int = Query(default=50, le=200),
    status: str = None,  # reimbursed, imminent, hot 등
    store: DataStore = Depends(get_data_store),
):
    """약물 목록"""
    items = store.impacts

    # 필터링
    if status == "reimbursed":
        items = [i for i in items if i.hira_status == ReimbursementStatus.REIMBURSED]
    elif status == "imminent":
        items = store.get_imminent()
    elif status == "hot":
        items = store.get_hot_issues(min_score=60)
    elif status == "high_value":
        items = store.get_high_value()

    # 페이지네이션
    items = items[offset:offset + limit]

    return [
        DrugSummary(
            inn=i.inn,
            fda_approved=i.fda_approved,
            ema_approved=i.ema_approved,
            mfds_approved=i.mfds_approved,
            hira_reimbursed=i.hira_status == ReimbursementStatus.REIMBURSED,
            hira_price=i.hira_price,
            global_score=i.global_score,
            hot_issue_level="HOT" if i.global_score >= 80 else "HIGH" if i.global_score >= 60 else "MID" if i.global_score >= 40 else "LOW",
            domestic_status=i.domestic_status.value,
        )
        for i in items
    ]


@router.get("/search", response_model=list[DrugSummary])
def search_drugs(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=20, le=100),
    store: DataStore = Depends(get_data_store),
):
    """약물 검색"""
    items = store.search(q, limit=limit)

    return [
        DrugSummary(
            inn=i.inn,
            fda_approved=i.fda_approved,
            ema_approved=i.ema_approved,
            mfds_approved=i.mfds_approved,
            hira_reimbursed=i.hira_status == ReimbursementStatus.REIMBURSED,
            hira_price=i.hira_price,
            global_score=i.global_score,
            hot_issue_level="HOT" if i.global_score >= 80 else "HIGH" if i.global_score >= 60 else "MID" if i.global_score >= 40 else "LOW",
            domestic_status=i.domestic_status.value,
        )
        for i in items
    ]


@router.get("/{inn}", response_model=DrugDetail)
def get_drug_detail(
    inn: str,
    store: DataStore = Depends(get_data_store),
):
    """약물 상세"""
    impact = store.get_by_inn(inn)
    if not impact:
        raise HTTPException(status_code=404, detail=f"Drug not found: {inn}")

    return DrugDetail(
        inn=impact.inn,
        fda_approved=impact.fda_approved,
        fda_date=impact.fda_date,
        ema_approved=impact.ema_approved,
        ema_date=impact.ema_date,
        mfds_approved=impact.mfds_approved,
        mfds_date=impact.mfds_date,
        mfds_brand_name=impact.mfds_brand_name,
        hira_status=impact.hira_status.value if impact.hira_status else None,
        hira_code=impact.hira_code,
        hira_criteria=impact.hira_criteria,
        hira_price=impact.hira_price,
        cris_trial_count=len(impact.cris_trials),
        cris_trials=[
            {
                "trial_id": t.trial_id,
                "title": t.title,
                "phase": t.phase,
                "status": t.status,
            }
            for t in impact.cris_trials
        ],
        global_score=impact.global_score,
        hot_issue_level="HOT" if impact.global_score >= 80 else "HIGH" if impact.global_score >= 60 else "MID" if impact.global_score >= 40 else "LOW",
        hot_issue_reasons=impact.hot_issue_reasons,
        domestic_status=impact.domestic_status.value,
        analysis_notes=impact.analysis_notes,
        summary=impact.summary,
    )


@router.get("/{inn}/medclaim", response_model=MedclaimInsight)
def get_medclaim_insight(
    inn: str,
    store: DataStore = Depends(get_data_store),
):
    """메드클레임 시사점"""
    impact = store.get_by_inn(inn)
    if not impact:
        raise HTTPException(status_code=404, detail=f"Drug not found: {inn}")

    insights = []

    # 급여 현황 분석
    if impact.hira_status == ReimbursementStatus.REIMBURSED:
        insights.append("건강보험 급여 적용 중")
        if impact.hira_price and impact.hira_price >= 1_000_000:
            insights.append(f"고가 약제 - 상한가 ₩{impact.hira_price:,.0f}")
            insights.append("사전심사 또는 요양급여 적정성 평가 대상 가능")
    elif impact.hira_status == ReimbursementStatus.NOT_COVERED:
        insights.append("비급여 - 전액 환자 부담")
        insights.append("실손보험 청구 가능 여부 확인 필요")
    elif impact.hira_status == ReimbursementStatus.DELETED:
        insights.append("급여 삭제됨 - 이전 급여 이력 있음")

    # 희귀의약품 분석
    is_orphan = any("희귀" in r or "Orphan" in r for r in impact.hot_issue_reasons)
    if is_orphan:
        insights.append("희귀의약품 지정 - 산정특례 적용 가능성")
        insights.append("본인부담률 10% 예상")

    # 임상시험 분석
    if impact.has_active_trial and not impact.mfds_approved:
        insights.append(f"국내 임상시험 {len(impact.cris_trials)}건 진행 중")
        insights.append("임상시험 참여를 통한 약물 접근 가능")

    # 고가 약물 본인부담
    estimated_burden = ""
    if impact.hira_price:
        if is_orphan:
            burden = impact.hira_price * 0.1
            estimated_burden = f"희귀질환 산정특례 시 약 ₩{burden:,.0f} (10%)"
        else:
            burden = impact.hira_price * 0.3
            estimated_burden = f"일반 급여 시 약 ₩{burden:,.0f} (30%)"

    return MedclaimInsight(
        inn=impact.inn,
        hira_status=impact.hira_status.value if impact.hira_status else None,
        hira_criteria=impact.hira_criteria,
        hira_price=impact.hira_price,
        is_orphan_drug=is_orphan,
        is_high_cost=impact.hira_price and impact.hira_price >= 1_000_000,
        estimated_burden=estimated_burden,
        insights=insights,
    )


@router.get("/{inn}/briefing", response_model=BriefingReportResponse)
async def get_briefing_report(
    inn: str,
    use_llm: bool = Query(default=True, description="LLM 사용 여부 (False면 템플릿 기반)"),
    store: DataStore = Depends(get_data_store),
):
    """LLM 브리핑 리포트 생성

    약물의 글로벌 규제 현황과 국내 도입 전망을 분석한 브리핑 리포트를 생성합니다.
    LLM(Claude)을 사용하여 자연어 리포트를 생성하거나, 템플릿 기반 리포트를 반환합니다.
    """
    impact = store.get_by_inn(inn)
    if not impact:
        raise HTTPException(status_code=404, detail=f"Drug not found: {inn}")

    generator = get_llm_generator()

    if use_llm:
        report = await generator.generate(impact)
    else:
        report = generator._generate_fallback(impact)

    return BriefingReportResponse(
        inn=report.inn,
        headline=report.headline,
        subtitle=report.subtitle,
        key_points=report.key_points,
        global_section=report.global_section,
        domestic_section=report.domestic_section,
        medclaim_section=report.medclaim_section,
        generated_at=report.generated_at,
        markdown=report.to_markdown(),
    )


# ── v2 엔드포인트 ──


@router.get("/{inn}/insight", response_model=AIInsightResponse)
async def get_ai_insight(inn: str):
    """AI 추론·검증 결과 조회 (v2)"""
    from regscan.config import settings
    if not settings.is_postgres:
        raise HTTPException(status_code=501, detail="PostgreSQL 모드에서만 지원됩니다")

    from regscan.db.database import get_async_session
    from regscan.db.models import AIInsightDB, DrugDB
    from sqlalchemy import select

    async with get_async_session()() as session:
        stmt = (
            select(AIInsightDB)
            .join(DrugDB, AIInsightDB.drug_id == DrugDB.id)
            .where(DrugDB.inn == inn)
            .order_by(AIInsightDB.generated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            raise HTTPException(status_code=404, detail=f"AI insight not found: {inn}")

        return AIInsightResponse(
            impact_score=row.impact_score,
            risk_factors=row.risk_factors or [],
            opportunity_factors=row.opportunity_factors or [],
            reasoning_chain=row.reasoning_chain or "",
            market_forecast=row.market_forecast or "",
            reasoning_model=row.reasoning_model or "",
            verified_score=row.verified_score,
            corrections=row.corrections or [],
            confidence_level=row.confidence_level or "",
            generated_at=row.generated_at,
        )


@router.get("/{inn}/article", response_model=ArticleResponse)
async def get_ai_article(
    inn: str,
    article_type: str = Query(default="briefing", description="기사 유형"),
):
    """AI 기사 조회 (v2)"""
    from regscan.config import settings
    if not settings.is_postgres:
        raise HTTPException(status_code=501, detail="PostgreSQL 모드에서만 지원됩니다")

    from regscan.db.database import get_async_session
    from regscan.db.models import ArticleDB, DrugDB
    from sqlalchemy import select

    async with get_async_session()() as session:
        stmt = (
            select(ArticleDB)
            .join(DrugDB, ArticleDB.drug_id == DrugDB.id)
            .where(DrugDB.inn == inn, ArticleDB.article_type == article_type)
            .order_by(ArticleDB.generated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            raise HTTPException(status_code=404, detail=f"Article not found: {inn}")

        return ArticleResponse(
            article_type=row.article_type,
            headline=row.headline or "",
            subtitle=row.subtitle or "",
            lead_paragraph=row.lead_paragraph or "",
            body_html=row.body_html or "",
            tags=row.tags or [],
            writer_model=row.writer_model or "",
            generated_at=row.generated_at,
        )


@router.get("/{inn}/preprints", response_model=list[PreprintResponse])
async def get_preprints(
    inn: str,
    limit: int = Query(default=20, le=100),
):
    """관련 프리프린트 논문 조회 (v2)"""
    from regscan.config import settings
    if not settings.is_postgres:
        raise HTTPException(status_code=501, detail="PostgreSQL 모드에서만 지원됩니다")

    from regscan.db.database import get_async_session
    from regscan.db.models import PreprintDB, DrugDB
    from sqlalchemy import select

    async with get_async_session()() as session:
        stmt = (
            select(PreprintDB)
            .join(DrugDB, PreprintDB.drug_id == DrugDB.id)
            .where(DrugDB.inn == inn)
            .order_by(PreprintDB.published_date.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        return [
            PreprintResponse(
                doi=r.doi or "",
                title=r.title or "",
                authors=r.authors or "",
                abstract=r.abstract or "",
                server=r.server or "",
                category=r.category or "",
                published_date=r.published_date,
                pdf_url=r.pdf_url or "",
                gemini_parsed=r.gemini_parsed or False,
                extracted_facts=r.extracted_facts,
            )
            for r in rows
        ]


@router.get("/{inn}/market", response_model=list[MarketReportResponse])
async def get_market_reports(
    inn: str,
    limit: int = Query(default=20, le=100),
):
    """시장 리포트 조회 (v2)"""
    from regscan.config import settings
    if not settings.is_postgres:
        raise HTTPException(status_code=501, detail="PostgreSQL 모드에서만 지원됩니다")

    from regscan.db.database import get_async_session
    from regscan.db.models import MarketReportDB, DrugDB
    from sqlalchemy import select

    async with get_async_session()() as session:
        stmt = (
            select(MarketReportDB)
            .join(DrugDB, MarketReportDB.drug_id == DrugDB.id)
            .where(DrugDB.inn == inn)
            .order_by(MarketReportDB.published_date.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        return [
            MarketReportResponse(
                source=r.source or "",
                title=r.title or "",
                publisher=r.publisher or "",
                published_date=r.published_date,
                market_size_krw=r.market_size_krw,
                growth_rate=r.growth_rate,
                summary=r.summary or "",
                source_url=r.source_url or "",
            )
            for r in rows
        ]
