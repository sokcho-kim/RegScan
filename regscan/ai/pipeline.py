"""AI Intelligence Pipeline — 3단계 오케스트레이터

[o4-mini] Reasoning → [GPT-5.2] Verifier → [GPT-5.2] Writer

각 단계 실패 시 fallback (기존 v1 LLM 브리핑으로 대체).
일일 API 호출 제한 체크.
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any, Optional

from regscan.config import settings
from regscan.ai.reasoning_engine import ReasoningEngine
from regscan.ai.verifier import InsightVerifier
from regscan.ai.writing_engine import WritingEngine

logger = logging.getLogger(__name__)

# 일일 호출 카운터
_daily_counts: dict[str, dict[str, int]] = {}


def _get_daily_count(key: str) -> int:
    """오늘 날짜의 호출 수 조회"""
    today = date.today().isoformat()
    if today not in _daily_counts:
        _daily_counts.clear()
        _daily_counts[today] = {}
    return _daily_counts[today].get(key, 0)


def _increment_daily_count(key: str) -> int:
    """오늘 날짜의 호출 수 증가"""
    today = date.today().isoformat()
    if today not in _daily_counts:
        _daily_counts.clear()
        _daily_counts[today] = {}
    _daily_counts[today][key] = _daily_counts[today].get(key, 0) + 1
    return _daily_counts[today][key]


class AIIntelligencePipeline:
    """3단 AI 파이프라인 오케스트레이터

    Usage:
        pipeline = AIIntelligencePipeline()
        insight, article = await pipeline.run(drug, preprints, reports, opinions)
    """

    def __init__(
        self,
        reasoning_engine: Optional[ReasoningEngine] = None,
        verifier: Optional[InsightVerifier] = None,
        writer: Optional[WritingEngine] = None,
    ):
        self.reasoning = reasoning_engine or ReasoningEngine()
        self.verifier = verifier or InsightVerifier()
        self.writer = writer or WritingEngine()

    async def run(
        self,
        drug: dict[str, Any],
        preprints: list[dict] | None = None,
        market_reports: list[dict] | None = None,
        expert_opinions: list[dict] | None = None,
        article_type: str = "briefing",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """3단 AI 파이프라인 실행

        Args:
            drug: 약물 데이터 dict
            preprints: bioRxiv 프리프린트 목록
            market_reports: ASTI 시장 리포트 목록
            expert_opinions: Health.kr 전문가 리뷰 목록
            article_type: 기사 유형

        Returns:
            (insight_dict, article_dict)
        """
        inn = drug.get("inn", "Unknown")
        logger.info("=== AI 파이프라인 시작: %s ===", inn)

        # ── Step 1: Reasoning (o4-mini) ──
        reasoning_result = {}
        if settings.ENABLE_AI_REASONING:
            count = _get_daily_count("reasoning")
            if count >= settings.MAX_REASONING_CALLS_PER_DAY:
                logger.warning(
                    "Reasoning 일일 한도 초과 (%d/%d)",
                    count, settings.MAX_REASONING_CALLS_PER_DAY,
                )
            else:
                try:
                    reasoning_result = await self.reasoning.analyze_impact(
                        drug=drug,
                        preprints=preprints,
                        market_reports=market_reports,
                        expert_opinions=expert_opinions,
                    )
                    _increment_daily_count("reasoning")
                    logger.info(
                        "[1/3] Reasoning 완료: impact=%d",
                        reasoning_result.get("impact_score", 0),
                    )
                except Exception as e:
                    logger.error("[1/3] Reasoning 실패: %s", e)
        else:
            logger.info("[1/3] Reasoning 비활성화 (ENABLE_AI_REASONING=false)")
            reasoning_result = {
                "impact_score": drug.get("global_score", 0),
                "risk_factors": [],
                "opportunity_factors": [],
                "reasoning_chain": "Reasoning 비활성화 — v1 점수 사용",
                "reasoning_model": "disabled",
                "reasoning_tokens": 0,
            }

        # ── Step 2: Verification (GPT-5.2) ──
        verification_result = {}
        if settings.ENABLE_AI_VERIFIER and reasoning_result:
            try:
                raw_sources = {
                    "preprints": preprints or [],
                    "market_reports": market_reports or [],
                    "expert_opinions": expert_opinions or [],
                }
                verification_result = await self.verifier.verify(
                    drug=drug,
                    reasoning_result=reasoning_result,
                    raw_sources=raw_sources,
                )
                logger.info(
                    "[2/3] Verification 완료: verified=%d, confidence=%s",
                    verification_result.get("verified_score", 0),
                    verification_result.get("confidence_level", "?"),
                )
            except Exception as e:
                logger.error("[2/3] Verification 실패: %s", e)
        else:
            logger.info("[2/3] Verification 비활성화 또는 reasoning 결과 없음")

        # insight 결과 조합
        insight = {
            **reasoning_result,
            **{k: v for k, v in verification_result.items()
               if k in ("verified_score", "corrections", "confidence_level",
                         "verifier_model", "verifier_tokens")},
        }

        # ── Step 3: Writing (GPT-5.2) ──
        article = {}
        if settings.ENABLE_AI_WRITER:
            count = _get_daily_count("writer")
            if count >= settings.MAX_WRITER_CALLS_PER_DAY:
                logger.warning(
                    "Writer 일일 한도 초과 (%d/%d)",
                    count, settings.MAX_WRITER_CALLS_PER_DAY,
                )
            else:
                try:
                    article = await self.writer.write_article(
                        drug=drug,
                        verified_insight=insight,
                        article_type=article_type,
                    )
                    _increment_daily_count("writer")
                    logger.info(
                        "[3/3] Writing 완료: headline=%s",
                        article.get("headline", "?")[:30],
                    )
                except Exception as e:
                    logger.error("[3/3] Writing 실패: %s", e)
        else:
            logger.info("[3/3] Writing 비활성화 (ENABLE_AI_WRITER=false)")

        logger.info("=== AI 파이프라인 완료: %s ===", inn)
        return insight, article

    @staticmethod
    def get_daily_usage() -> dict[str, int]:
        """오늘의 API 호출 사용량 조회"""
        today = date.today().isoformat()
        counts = _daily_counts.get(today, {})
        return {
            "reasoning_calls": counts.get("reasoning", 0),
            "writer_calls": counts.get("writer", 0),
            "reasoning_limit": settings.MAX_REASONING_CALLS_PER_DAY,
            "writer_limit": settings.MAX_WRITER_CALLS_PER_DAY,
        }
