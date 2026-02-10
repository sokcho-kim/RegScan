"""AI 3단 파이프라인 단위 테스트

Reasoning → Verifier → Writer 각 단계와 오케스트레이터 테스트.
실제 API 호출 없이 fallback 경로를 테스트합니다.
"""

import pytest

from regscan.ai.reasoning_engine import ReasoningEngine
from regscan.ai.verifier import InsightVerifier
from regscan.ai.writing_engine import WritingEngine
from regscan.ai.pipeline import AIIntelligencePipeline


@pytest.fixture
def sample_drug():
    """테스트용 약물 데이터"""
    return {
        "inn": "PEMBROLIZUMAB",
        "fda_approved": True,
        "fda_date": "2025-06-15",
        "ema_approved": True,
        "ema_date": "2025-08-01",
        "mfds_approved": False,
        "mfds_date": None,
        "hira_status": None,
        "hira_price": None,
        "global_score": 85,
    }


@pytest.fixture
def sample_preprints():
    return [
        {
            "doi": "10.1101/2026.01.01.000001",
            "title": "Novel PD-1 combination therapy results",
            "abstract": "We report improved outcomes...",
            "server": "medrxiv",
        }
    ]


@pytest.fixture
def sample_market_reports():
    return [
        {
            "title": "면역항암제 시장 분석 2026",
            "source": "ASTI",
            "market_size_krw": 5000.0,
            "growth_rate": 15.2,
        }
    ]


# ── ReasoningEngine fallback ──

async def test_reasoning_fallback(sample_drug):
    """API 키 없을 때 fallback 결과 반환"""
    engine = ReasoningEngine(api_key=None)
    # api_key가 None이면 settings.OPENAI_API_KEY 사용 → 대부분 None
    result = engine._fallback_result(sample_drug)

    assert result["impact_score"] == 85  # global_score 그대로
    assert result["reasoning_model"] == "fallback"
    assert result["reasoning_tokens"] == 0


# ── InsightVerifier fallback ──

async def test_verifier_fallback():
    """검증 fallback 결과"""
    verifier = InsightVerifier(api_key=None)
    reasoning = {"impact_score": 85, "risk_factors": ["test"]}
    result = verifier._fallback_result(reasoning)

    assert result["verified_score"] == 85
    assert result["confidence_level"] == "low"
    assert result["verifier_model"] == "fallback"


# ── WritingEngine fallback ──

async def test_writing_fallback(sample_drug):
    """기사 작성 fallback 결과"""
    writer = WritingEngine(api_key=None)
    result = writer._fallback_result(sample_drug, "briefing")

    assert result["article_type"] == "briefing"
    assert "PEMBROLIZUMAB" in result["headline"]
    assert result["writer_model"] == "fallback"


# ── Pipeline 통합 (모든 단계 비활성화) ──

async def test_pipeline_all_disabled(sample_drug, monkeypatch):
    """모든 AI 단계 비활성화 시 graceful 처리"""
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_REASONING", False)
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_VERIFIER", False)
    monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_WRITER", False)

    pipeline = AIIntelligencePipeline()
    insight, article = await pipeline.run(drug=sample_drug)

    assert insight.get("reasoning_model") == "disabled"
    assert article == {}


# ── Pipeline 일일 사용량 조회 ──

def test_daily_usage():
    """일일 API 사용량 조회"""
    usage = AIIntelligencePipeline.get_daily_usage()
    assert "reasoning_calls" in usage
    assert "writer_calls" in usage
    assert "reasoning_limit" in usage
    assert "writer_limit" in usage


# ── ReasoningEngine 포맷터 ──

def test_format_regulatory(sample_drug):
    """규제 데이터 포맷팅"""
    text = ReasoningEngine._format_regulatory(sample_drug)
    assert "FDA: 승인" in text
    assert "EMA: 승인" in text
    assert "MFDS: 미승인" in text


def test_format_preprints_empty():
    """프리프린트 없을 때"""
    text = ReasoningEngine._format_preprints([])
    assert "없음" in text


def test_format_preprints(sample_preprints):
    """프리프린트 포맷팅"""
    text = ReasoningEngine._format_preprints(sample_preprints)
    assert "PD-1" in text


def test_format_market(sample_market_reports):
    """시장 데이터 포맷팅"""
    text = ReasoningEngine._format_market(sample_market_reports)
    assert "면역항암제" in text
    assert "5000" in text
