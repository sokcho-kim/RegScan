"""v2 스키마 테스트 — 5개 신규 테이블 생성·CRUD 확인"""

import asyncio
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from regscan.db.models import (
    Base,
    DrugDB,
    PreprintDB,
    MarketReportDB,
    ExpertOpinionDB,
    AIInsightDB,
    ArticleDB,
)


@pytest.fixture
async def async_session():
    """인메모리 SQLite 비동기 세션"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def drug_id(async_session: AsyncSession):
    """테스트용 약물 생성"""
    drug = DrugDB(inn="TESTDRUG", global_score=80, hot_issue_level="HOT")
    async_session.add(drug)
    await async_session.flush()
    return drug.id


# ── 테이블 생성 확인 ──

async def test_all_tables_created():
    """v2 테이블 5개가 모두 생성되었는지 확인"""
    from sqlalchemy import inspect

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        table_names = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    await engine.dispose()

    expected = [
        "drugs", "regulatory_events", "hira_reimbursements",
        "clinical_trials", "briefing_reports", "scan_snapshots",
        "feed_cards",
        # v2
        "preprints", "market_reports", "expert_opinions",
        "ai_insights", "articles",
    ]
    for table in expected:
        assert table in table_names, f"테이블 누락: {table}"


# ── PreprintDB CRUD ──

async def test_preprint_crud(async_session: AsyncSession, drug_id: int):
    """프리프린트 생성·조회·수정"""
    # Create
    row = PreprintDB(
        drug_id=drug_id,
        doi="10.1101/2026.01.01.000001",
        title="Test Preprint",
        authors="Author A; Author B",
        abstract="Test abstract",
        server="biorxiv",
        category="pharmacology",
        published_date=date(2026, 1, 15),
        pdf_url="https://www.biorxiv.org/content/10.1101/2026.01.01.000001v1.full.pdf",
    )
    async_session.add(row)
    await async_session.flush()
    assert row.id is not None

    # Read
    stmt = select(PreprintDB).where(PreprintDB.doi == "10.1101/2026.01.01.000001")
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.title == "Test Preprint"
    assert fetched.server == "biorxiv"

    # Update
    fetched.gemini_parsed = True
    fetched.extracted_facts = {"drug_names": ["TESTDRUG"]}
    await async_session.flush()

    result2 = await async_session.execute(stmt)
    updated = result2.scalar_one()
    assert updated.gemini_parsed is True
    assert updated.extracted_facts["drug_names"] == ["TESTDRUG"]


# ── MarketReportDB CRUD ──

async def test_market_report_crud(async_session: AsyncSession, drug_id: int):
    """시장 리포트 생성·조회"""
    row = MarketReportDB(
        drug_id=drug_id,
        source="ASTI",
        title="글로벌 항암제 시장 분석",
        publisher="KISTI",
        published_date=date(2026, 1, 10),
        market_size_krw=15000.0,
        growth_rate=12.5,
        summary="항암제 시장은 2030년까지 연평균 12.5% 성장 전망",
    )
    async_session.add(row)
    await async_session.flush()
    assert row.id is not None

    stmt = select(MarketReportDB).where(MarketReportDB.drug_id == drug_id)
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.market_size_krw == 15000.0
    assert fetched.growth_rate == 12.5


# ── ExpertOpinionDB CRUD ──

async def test_expert_opinion_crud(async_session: AsyncSession, drug_id: int):
    """전문가 리뷰 생성·조회"""
    row = ExpertOpinionDB(
        drug_id=drug_id,
        source="KPIC",
        title="TESTDRUG 약물 평가",
        author="약학정보원",
        summary="효과적인 치료 옵션으로 평가됨",
        published_date=date(2026, 1, 20),
    )
    async_session.add(row)
    await async_session.flush()

    stmt = select(ExpertOpinionDB).where(ExpertOpinionDB.drug_id == drug_id)
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.source == "KPIC"
    assert fetched.author == "약학정보원"


# ── AIInsightDB CRUD ──

async def test_ai_insight_crud(async_session: AsyncSession, drug_id: int):
    """AI 인사이트 생성·조회"""
    row = AIInsightDB(
        drug_id=drug_id,
        impact_score=85,
        risk_factors=["경쟁 약물 존재", "가격 경쟁"],
        opportunity_factors=["희귀질환 지정", "임상 결과 우수"],
        reasoning_chain="Step 1→2→3 분석",
        market_forecast="2027년까지 시장 점유율 20% 예상",
        reasoning_model="o4-mini",
        reasoning_tokens=1500,
        verified_score=82,
        corrections=[],
        confidence_level="high",
        verifier_model="gpt-5.2",
        verifier_tokens=800,
    )
    async_session.add(row)
    await async_session.flush()

    stmt = select(AIInsightDB).where(AIInsightDB.drug_id == drug_id)
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.impact_score == 85
    assert fetched.verified_score == 82
    assert fetched.confidence_level == "high"
    assert len(fetched.risk_factors) == 2


# ── ArticleDB CRUD ──

async def test_article_crud(async_session: AsyncSession, drug_id: int):
    """AI 기사 생성·조회"""
    row = ArticleDB(
        drug_id=drug_id,
        article_type="briefing",
        headline="TESTDRUG 규제 동향 분석",
        subtitle="FDA 승인 후 국내 시장 영향",
        lead_paragraph="TESTDRUG가 FDA 승인을 받았다...",
        body_html="<h2>규제 현황</h2><p>...</p>",
        tags=["FDA", "승인", "항암제"],
        writer_model="gpt-5.2",
        writer_tokens=2000,
    )
    async_session.add(row)
    await async_session.flush()

    stmt = select(ArticleDB).where(
        ArticleDB.drug_id == drug_id,
        ArticleDB.article_type == "briefing",
    )
    result = await async_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.headline == "TESTDRUG 규제 동향 분석"
    assert "FDA" in fetched.tags


# ── DrugDB relationships ──

async def test_drug_v2_relationships(async_session: AsyncSession, drug_id: int):
    """DrugDB → v2 테이블 relationship 확인"""
    from sqlalchemy.orm import selectinload

    # 각 테이블에 데이터 추가
    async_session.add(PreprintDB(
        drug_id=drug_id, doi="10.1101/test", title="Paper"
    ))
    async_session.add(MarketReportDB(
        drug_id=drug_id, source="ASTI", title="Report"
    ))
    async_session.add(ExpertOpinionDB(
        drug_id=drug_id, source="KPIC", title="Review"
    ))
    async_session.add(AIInsightDB(
        drug_id=drug_id, impact_score=70
    ))
    async_session.add(ArticleDB(
        drug_id=drug_id, article_type="briefing", headline="Article"
    ))
    await async_session.flush()

    # Drug 로드 + relationship 확인 (eager loading for async)
    stmt = (
        select(DrugDB)
        .where(DrugDB.id == drug_id)
        .options(
            selectinload(DrugDB.preprints),
            selectinload(DrugDB.market_reports),
            selectinload(DrugDB.expert_opinions),
            selectinload(DrugDB.ai_insights),
            selectinload(DrugDB.articles),
        )
    )
    result = await async_session.execute(stmt)
    drug = result.scalar_one()

    assert len(drug.preprints) == 1
    assert len(drug.market_reports) == 1
    assert len(drug.expert_opinions) == 1
    assert len(drug.ai_insights) == 1
    assert len(drug.articles) == 1
