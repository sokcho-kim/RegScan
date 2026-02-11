"""OpenAI E2E 테스트 — 실제 API 호출로 3단 AI 파이프라인 검증

실행 조건:
  - OPENAI_API_KEY 환경변수 필요
  - pytest tests/test_e2e_openai.py -v -m e2e

비용 참고:
  - o4-mini reasoning: ~$0.02/call
  - GPT-5.2 verification + writing: ~$0.05/call each
  - 전체 5개 테스트 총 ~$0.20 이하
"""

import os
import logging

import pytest

from regscan.config import settings
from regscan.ai.reasoning_engine import ReasoningEngine
from regscan.ai.verifier import InsightVerifier
from regscan.ai.writing_engine import WritingEngine
from regscan.ai.pipeline import AIIntelligencePipeline

logger = logging.getLogger(__name__)

# ── 조건부 스킵 ──
# .env 파일의 키도 인식하도록 settings에서 확인
HAS_OPENAI_KEY = bool(os.environ.get("OPENAI_API_KEY") or settings.OPENAI_API_KEY)
skip_no_key = pytest.mark.skipif(not HAS_OPENAI_KEY, reason="OPENAI_API_KEY not set")

pytestmark = [pytest.mark.e2e, skip_no_key]


# ── Test 1: ReasoningEngine 단독 ──

async def test_reasoning_engine_real(
    sample_drug, sample_preprints, sample_market_reports, sample_expert_opinions,
):
    """실제 o4-mini 호출 → JSON 응답 파싱 검증"""
    engine = ReasoningEngine()
    result = await engine.analyze_impact(
        drug=sample_drug,
        preprints=sample_preprints,
        market_reports=sample_market_reports,
        expert_opinions=sample_expert_opinions,
    )

    logger.info("Reasoning result: %s", result)

    # 필수 필드 존재
    assert "impact_score" in result
    assert "risk_factors" in result
    assert "opportunity_factors" in result
    assert "reasoning_chain" in result
    assert "reasoning_model" in result
    assert "reasoning_tokens" in result

    # impact_score 범위 검증
    assert 0 <= result["impact_score"] <= 100

    # 모델 정보 검증 (fallback이 아닌 실제 모델 사용)
    assert result["reasoning_model"] != "fallback"
    assert result["reasoning_tokens"] > 0

    # risk/opportunity는 리스트
    assert isinstance(result["risk_factors"], list)
    assert isinstance(result["opportunity_factors"], list)

    # reasoning_chain은 비어있지 않아야 함
    assert len(result.get("reasoning_chain", "")) > 10


# ── Test 2: InsightVerifier 단독 ──

async def test_verifier_real(sample_drug):
    """실제 GPT-5.2 호출 → 검증 결과 구조 확인"""
    # 먼저 mock reasoning 결과 생성
    mock_reasoning = {
        "impact_score": 78,
        "risk_factors": ["MFDS 허가 미확보", "HIRA 급여 확대 불확실"],
        "opportunity_factors": ["FDA 승인 완료", "Phase III PFS 개선 확인"],
        "reasoning_chain": "FDA/EMA 승인 → MFDS 허가 예상 → 급여 확대 가능성",
        "market_forecast": "면역항암제 시장 성장 지속, 2030년까지 연 15% 성장",
        "reasoning_model": "o4-mini",
        "reasoning_tokens": 1500,
    }

    verifier = InsightVerifier()
    result = await verifier.verify(
        drug=sample_drug,
        reasoning_result=mock_reasoning,
        raw_sources={
            "preprints": [],
            "market_reports": [],
            "expert_opinions": [],
        },
    )

    logger.info("Verifier result: %s", result)

    # 필수 필드 존재
    assert "verified_score" in result
    assert "confidence_level" in result
    assert "verifier_model" in result
    assert "verifier_tokens" in result

    # verified_score 범위
    assert 0 <= result["verified_score"] <= 100

    # confidence_level은 high/medium/low 중 하나
    assert result["confidence_level"] in ("high", "medium", "low")

    # 실제 모델 사용
    assert result["verifier_model"] != "fallback"
    assert result["verifier_tokens"] > 0

    # corrections는 리스트
    assert isinstance(result.get("corrections", []), list)


# ── Test 3: WritingEngine 단독 ──

async def test_writing_engine_real(sample_drug):
    """실제 GPT-5.2 호출 → 기사 생성 구조 확인"""
    mock_insight = {
        "impact_score": 78,
        "verified_score": 75,
        "risk_factors": ["MFDS 허가 미확보"],
        "opportunity_factors": ["FDA 승인 완료", "PFS 개선"],
        "reasoning_chain": "FDA/EMA 승인 → 국내 급여 영향",
        "confidence_level": "medium",
    }

    writer = WritingEngine()
    result = await writer.write_article(
        drug=sample_drug,
        verified_insight=mock_insight,
        article_type="briefing",
    )

    logger.info("Writer result headline: %s", result.get("headline"))

    # 필수 필드 존재
    assert "headline" in result
    assert "subtitle" in result
    assert "lead_paragraph" in result
    assert "body_html" in result
    assert "tags" in result
    assert "writer_model" in result
    assert "writer_tokens" in result

    # 한글 기사 생성 여부 — headline 또는 lead_paragraph에 한글 포함
    combined = result["headline"] + result.get("lead_paragraph", "")
    has_korean = any("\uac00" <= c <= "\ud7a3" for c in combined)
    assert has_korean, f"한글이 포함되지 않음: {combined[:100]}"

    # body_html에 HTML 태그 포함
    body = result.get("body_html", "")
    assert "<" in body and ">" in body, "body_html에 HTML 태그가 없음"

    # tags는 리스트
    assert isinstance(result["tags"], list)
    assert len(result["tags"]) > 0

    # 실제 모델 사용
    assert result["writer_model"] != "fallback"
    assert result["writer_tokens"] > 0


# ── Test 4: Full Pipeline E2E ──

async def test_full_pipeline_e2e(
    sample_drug, sample_preprints, sample_market_reports, sample_expert_opinions,
    monkeypatch,
):
    """3단 파이프라인 전체 흐름: Reasoning → Verifier → Writer"""
    # 모든 AI 단계 활성화
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_REASONING", True)
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_VERIFIER", True)
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_WRITER", True)

    pipeline = AIIntelligencePipeline()
    insight, article = await pipeline.run(
        drug=sample_drug,
        preprints=sample_preprints,
        market_reports=sample_market_reports,
        expert_opinions=sample_expert_opinions,
        article_type="briefing",
    )

    logger.info("Pipeline insight keys: %s", list(insight.keys()))
    logger.info("Pipeline article keys: %s", list(article.keys()))

    # ── Insight 검증 ──
    assert "impact_score" in insight
    assert 0 <= insight["impact_score"] <= 100

    # Verifier 결과가 병합되었는지 확인
    assert "verified_score" in insight
    assert 0 <= insight["verified_score"] <= 100
    assert "confidence_level" in insight
    assert insight["confidence_level"] in ("high", "medium", "low")

    # 토큰 사용량 추적
    assert insight.get("reasoning_tokens", 0) > 0
    assert insight.get("verifier_tokens", 0) > 0

    # ── Article 검증 ──
    assert article.get("article_type") == "briefing"
    assert len(article.get("headline", "")) > 0
    assert len(article.get("body_html", "")) > 0
    assert article.get("writer_tokens", 0) > 0


# ── Test 5: 응답 품질 검증 ──

async def test_response_quality(
    sample_drug, sample_preprints, sample_market_reports, sample_expert_opinions,
):
    """Reasoning 응답의 내용 품질 검증"""
    engine = ReasoningEngine()
    result = await engine.analyze_impact(
        drug=sample_drug,
        preprints=sample_preprints,
        market_reports=sample_market_reports,
        expert_opinions=sample_expert_opinions,
    )

    # impact_score가 데이터 맥락에 합리적 (FDA+EMA 승인 약물 → 높은 점수 예상)
    assert result["impact_score"] >= 50, (
        f"FDA+EMA 승인 약물인데 점수가 너무 낮음: {result['impact_score']}"
    )

    # risk_factors / opportunity_factors가 1개 이상
    assert len(result.get("risk_factors", [])) >= 1, "리스크 요인이 0개"
    assert len(result.get("opportunity_factors", [])) >= 1, "기회 요인이 0개"

    # reasoning_chain에 약물명 또는 관련 키워드 포함
    chain = result.get("reasoning_chain", "").upper()
    assert any(kw in chain for kw in ["PEMBROLIZUMAB", "PD-1", "FDA", "면역"]), (
        f"reasoning_chain에 관련 키워드 없음: {chain[:200]}"
    )

    # market_forecast가 비어있지 않을 것
    forecast = result.get("market_forecast", "")
    assert len(forecast) > 10, f"market_forecast가 너무 짧음: {forecast}"
