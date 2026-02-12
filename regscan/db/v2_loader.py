"""V2 데이터 로더 — 신규 5개 테이블 upsert

v1 DBLoader의 upsert 패턴(SELECT → UPDATE or INSERT)을 그대로 따름.

사용법:
    loader = V2Loader()
    await loader.upsert_preprint(drug_id, data)
    await loader.upsert_market_report(drug_id, data)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regscan.db.database import get_async_session
from regscan.db.models import (
    DrugDB,
    PreprintDB,
    MarketReportDB,
    ExpertOpinionDB,
    AIInsightDB,
    ArticleDB,
)

logger = logging.getLogger(__name__)


class V2Loader:
    """Async loader for RegScan v2 테이블.

    모든 퍼블릭 메서드는 자체 세션을 열어 처리하므로
    외부에서 세션 관리가 필요하지 않습니다.
    """

    def __init__(self) -> None:
        self._session_factory = get_async_session()

    # ------------------------------------------------------------------ #
    #  Preprint (bioRxiv/medRxiv)
    # ------------------------------------------------------------------ #

    async def upsert_preprint(self, drug_id: int, data: dict) -> tuple[PreprintDB, bool]:
        """프리프린트 논문 upsert. DOI가 unique key.

        Returns:
            (PreprintDB, is_new) — is_new=True면 새로 INSERT된 프리프린트
        """
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(PreprintDB).where(PreprintDB.doi == data["doi"])
                result = await session.execute(stmt)
                existing: Optional[PreprintDB] = result.scalar_one_or_none()

                if existing:
                    existing.drug_id = drug_id
                    existing.title = data.get("title", existing.title)
                    existing.authors = data.get("authors", existing.authors)
                    existing.abstract = data.get("abstract", existing.abstract)
                    existing.server = data.get("server", existing.server)
                    existing.category = data.get("category", existing.category)
                    existing.published_date = data.get("published_date", existing.published_date)
                    existing.pdf_url = data.get("pdf_url", existing.pdf_url)
                    row = existing
                    is_new = False
                else:
                    row = PreprintDB(
                        drug_id=drug_id,
                        doi=data["doi"],
                        title=data["title"],
                        authors=data.get("authors"),
                        abstract=data.get("abstract"),
                        server=data.get("server", "biorxiv"),
                        category=data.get("category"),
                        published_date=data.get("published_date"),
                        pdf_url=data.get("pdf_url"),
                    )
                    session.add(row)
                    await session.flush()
                    is_new = True

                logger.debug("프리프린트 upsert: %s (new=%s)", data["doi"], is_new)
                return row, is_new

    # ------------------------------------------------------------------ #
    #  Market Report (ASTI/KISTI)
    # ------------------------------------------------------------------ #

    async def upsert_market_report(self, drug_id: int, data: dict) -> MarketReportDB:
        """시장 리포트 upsert. (drug_id, source, title) 기준."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(MarketReportDB).where(
                    MarketReportDB.drug_id == drug_id,
                    MarketReportDB.source == data["source"],
                    MarketReportDB.title == data["title"],
                )
                result = await session.execute(stmt)
                existing: Optional[MarketReportDB] = result.scalar_one_or_none()

                if existing:
                    existing.publisher = data.get("publisher", existing.publisher)
                    existing.published_date = data.get("published_date", existing.published_date)
                    existing.market_size_krw = data.get("market_size_krw", existing.market_size_krw)
                    existing.growth_rate = data.get("growth_rate", existing.growth_rate)
                    existing.summary = data.get("summary", existing.summary)
                    existing.source_url = data.get("source_url", existing.source_url)
                    existing.raw_data = data.get("raw_data", existing.raw_data)
                    row = existing
                else:
                    row = MarketReportDB(
                        drug_id=drug_id,
                        source=data["source"],
                        title=data["title"],
                        publisher=data.get("publisher"),
                        published_date=data.get("published_date"),
                        market_size_krw=data.get("market_size_krw"),
                        growth_rate=data.get("growth_rate"),
                        summary=data.get("summary"),
                        source_url=data.get("source_url"),
                        raw_data=data.get("raw_data"),
                    )
                    session.add(row)
                    await session.flush()

                logger.debug("시장 리포트 upsert: %s - %s", data["source"], data["title"][:50])
                return row

    # ------------------------------------------------------------------ #
    #  Expert Opinion (Health.kr)
    # ------------------------------------------------------------------ #

    async def upsert_expert_opinion(self, drug_id: int, data: dict) -> ExpertOpinionDB:
        """전문가 리뷰 upsert. (drug_id, source, title) 기준."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(ExpertOpinionDB).where(
                    ExpertOpinionDB.drug_id == drug_id,
                    ExpertOpinionDB.source == data["source"],
                    ExpertOpinionDB.title == data["title"],
                )
                result = await session.execute(stmt)
                existing: Optional[ExpertOpinionDB] = result.scalar_one_or_none()

                if existing:
                    existing.author = data.get("author", existing.author)
                    existing.summary = data.get("summary", existing.summary)
                    existing.published_date = data.get("published_date", existing.published_date)
                    existing.source_url = data.get("source_url", existing.source_url)
                    existing.raw_data = data.get("raw_data", existing.raw_data)
                    row = existing
                else:
                    row = ExpertOpinionDB(
                        drug_id=drug_id,
                        source=data["source"],
                        title=data["title"],
                        author=data.get("author"),
                        summary=data.get("summary"),
                        published_date=data.get("published_date"),
                        source_url=data.get("source_url"),
                        raw_data=data.get("raw_data"),
                    )
                    session.add(row)
                    await session.flush()

                logger.debug("전문가 리뷰 upsert: %s - %s", data["source"], data["title"][:50])
                return row

    # ------------------------------------------------------------------ #
    #  AI Insight (Reasoning + Verification)
    # ------------------------------------------------------------------ #

    async def save_ai_insight(self, drug_id: int, insight: dict) -> AIInsightDB:
        """AI 추론·검증 결과 저장. 항상 새 행 추가 (이력 보존)."""
        async with self._session_factory() as session:
            async with session.begin():
                row = AIInsightDB(
                    drug_id=drug_id,
                    # Reasoning
                    impact_score=insight.get("impact_score"),
                    risk_factors=insight.get("risk_factors", []),
                    opportunity_factors=insight.get("opportunity_factors", []),
                    reasoning_chain=insight.get("reasoning_chain"),
                    market_forecast=insight.get("market_forecast"),
                    reasoning_model=insight.get("reasoning_model"),
                    reasoning_tokens=insight.get("reasoning_tokens"),
                    # Verification
                    verified_score=insight.get("verified_score"),
                    corrections=insight.get("corrections", []),
                    confidence_level=insight.get("confidence_level"),
                    verifier_model=insight.get("verifier_model"),
                    verifier_tokens=insight.get("verifier_tokens"),
                )
                session.add(row)
                await session.flush()

                logger.info(
                    "AI 인사이트 저장: drug_id=%d, impact=%s, verified=%s",
                    drug_id,
                    insight.get("impact_score"),
                    insight.get("verified_score"),
                )
                return row

    # ------------------------------------------------------------------ #
    #  Article (GPT-5.2 Writer)
    # ------------------------------------------------------------------ #

    async def save_article(self, drug_id: int, article: dict) -> ArticleDB:
        """AI 기사 저장. (drug_id, article_type) 기준 upsert."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(ArticleDB).where(
                    ArticleDB.drug_id == drug_id,
                    ArticleDB.article_type == article["article_type"],
                )
                result = await session.execute(stmt)
                existing: Optional[ArticleDB] = result.scalar_one_or_none()

                if existing:
                    existing.headline = article["headline"]
                    existing.subtitle = article.get("subtitle")
                    existing.lead_paragraph = article.get("lead_paragraph")
                    existing.body_html = article.get("body_html")
                    existing.tags = article.get("tags", [])
                    existing.writer_model = article.get("writer_model")
                    existing.writer_tokens = article.get("writer_tokens")
                    existing.generated_at = datetime.utcnow()
                    row = existing
                else:
                    row = ArticleDB(
                        drug_id=drug_id,
                        article_type=article["article_type"],
                        headline=article["headline"],
                        subtitle=article.get("subtitle"),
                        lead_paragraph=article.get("lead_paragraph"),
                        body_html=article.get("body_html"),
                        tags=article.get("tags", []),
                        writer_model=article.get("writer_model"),
                        writer_tokens=article.get("writer_tokens"),
                    )
                    session.add(row)
                    await session.flush()

                logger.info(
                    "기사 저장: drug_id=%d, type=%s, headline=%s",
                    drug_id,
                    article["article_type"],
                    article["headline"][:50],
                )
                return row

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    async def get_drug_id(self, inn: str) -> Optional[int]:
        """drugs 테이블에서 INN으로 drug_id 조회. 없으면 최소 레코드 생성."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(DrugDB.id).where(DrugDB.inn == inn)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is not None:
                    return row

                drug = DrugDB(inn=inn, hot_issue_level="LOW")
                session.add(drug)
                await session.flush()
                return drug.id

    async def update_preprint_gemini(
        self, doi: str, extracted_facts: dict
    ) -> None:
        """Gemini 파싱 결과를 프리프린트에 업데이트."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(PreprintDB).where(PreprintDB.doi == doi)
                result = await session.execute(stmt)
                row: Optional[PreprintDB] = result.scalar_one_or_none()
                if row:
                    row.gemini_parsed = True
                    row.extracted_facts = extracted_facts
                    logger.debug("Gemini 결과 업데이트: %s", doi)
