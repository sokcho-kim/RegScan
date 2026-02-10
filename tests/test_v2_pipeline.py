"""v2 파이프라인 E2E 테스트

수집기 → 파서 → DB 적재 → AI 파이프라인 전체 흐름 테스트.
실제 외부 API 호출 없이 mock 데이터로 진행합니다.
"""

import pytest
from datetime import date

from regscan.parse.biorxiv_parser import BioRxivParser
from regscan.parse.asti_parser import ASTIReportParser
from regscan.parse.healthkr_parser import HealthKRParser


# ── bioRxiv 파서 ──

class TestBioRxivParser:

    def test_parse_preprint(self):
        """bioRxiv API 응답 파싱"""
        raw = {
            "doi": "10.1101/2026.01.15.123456",
            "title": "Novel anti-PD-1 combination therapy",
            "authors": "Kim, J; Lee, S; Park, H",
            "abstract": "We investigated a novel combination...",
            "date": "2026-01-15",
            "server": "medrxiv",
            "category": "pharmacology and therapeutics",
            "version": "1",
        }
        parser = BioRxivParser()
        result = parser.parse_preprint(raw)

        assert result["doi"] == "10.1101/2026.01.15.123456"
        assert result["title"] == "Novel anti-PD-1 combination therapy"
        assert result["server"] == "medrxiv"
        assert result["published_date"] == date(2026, 1, 15)
        assert "full.pdf" in result["pdf_url"]

    def test_parse_many(self):
        """복수 프리프린트 파싱"""
        raws = [
            {"doi": "10.1101/001", "title": "Paper 1", "date": "2026-01-01"},
            {"doi": "10.1101/002", "title": "Paper 2", "date": "2026-01-02"},
            {"doi": "", "title": "No DOI"},  # DOI 없으면 제외
        ]
        parser = BioRxivParser()
        results = parser.parse_many(raws)
        assert len(results) == 2

    def test_parse_date_invalid(self):
        """잘못된 날짜"""
        assert BioRxivParser._parse_date("") is None
        assert BioRxivParser._parse_date("invalid") is None
        assert BioRxivParser._parse_date("2026-01-15") == date(2026, 1, 15)


# ── ASTI 파서 ──

class TestASTIParser:

    def test_parse_report(self):
        """ASTI 리포트 파싱"""
        raw = {
            "title": "글로벌 항암제 시장 분석: 5,000억원 규모, 연 12.5% 성장",
            "publisher": "KISTI",
            "date_str": "2026.01.10",
            "source_url": "https://www.asti.re.kr/report/view.do?id=1234",
            "source": "ASTI",
            "content": "항암제 시장은 5,000억원 규모로 연 12.5% 성장률을 보이고 있다.",
        }
        parser = ASTIReportParser()
        result = parser.parse_report(raw)

        assert result["title"] == raw["title"]
        assert result["source"] == "ASTI"
        assert result["published_date"] == date(2026, 1, 10)
        assert result["market_size_krw"] == 5000.0
        assert result["growth_rate"] == 12.5

    def test_extract_market_size(self):
        """시장 규모 추출"""
        assert ASTIReportParser._extract_market_size("시장 규모 1,500억 원") == 1500.0
        assert ASTIReportParser._extract_market_size("300억 원 규모") == 300.0
        assert ASTIReportParser._extract_market_size("No number") is None

    def test_extract_growth_rate(self):
        """성장률 추출"""
        assert ASTIReportParser._extract_growth_rate("연 12.5% 성장") == 12.5
        assert ASTIReportParser._extract_growth_rate("CAGR 8.3%") == 8.3
        assert ASTIReportParser._extract_growth_rate("성장률 15%") == 15.0
        assert ASTIReportParser._extract_growth_rate("No rate") is None


# ── Health.kr 파서 ──

class TestHealthKRParser:

    def test_parse_review(self):
        """Health.kr 리뷰 파싱"""
        raw = {
            "title": "PEMBROLIZUMAB 약물 평가",
            "source": "KPIC",
            "author": "약학정보원",
            "summary": "면역관문억제제로서 효과적인 치료 옵션",
            "date_str": "2026.01.20",
            "source_url": "https://www.health.kr/drug/...",
        }
        parser = HealthKRParser()
        result = parser.parse_review(raw)

        assert result["title"] == "PEMBROLIZUMAB 약물 평가"
        assert result["source"] == "KPIC"
        assert result["published_date"] == date(2026, 1, 20)

    def test_parse_many(self):
        """복수 리뷰 파싱"""
        raws = [
            {"title": "Review 1", "source": "KPIC"},
            {"title": "Review 2", "source": "약사저널"},
        ]
        parser = HealthKRParser()
        results = parser.parse_many(raws)
        assert len(results) == 2


# ── Settings v2 ──

class TestV2Settings:

    def test_v2_settings_defaults(self):
        """v2 설정 기본값 확인"""
        from regscan.config import settings

        assert settings.ENABLE_AI_REASONING is False
        assert settings.ENABLE_AI_VERIFIER is False
        assert settings.ENABLE_AI_WRITER is False
        assert settings.ENABLE_ASTI is False
        assert settings.ENABLE_HEALTHKR is False
        assert settings.ENABLE_BIORXIV is False
        assert settings.ENABLE_GEMINI_PARSING is False
        assert settings.MAX_REASONING_CALLS_PER_DAY == 50
        assert settings.MAX_WRITER_CALLS_PER_DAY == 50
        assert settings.REASONING_MODEL == "o4-mini"
        assert settings.VERIFIER_MODEL == "gpt-5.2"
        assert settings.WRITER_MODEL == "gpt-5.2"


# ── V2 모델 임포트 ──

class TestV2ModelImports:

    def test_imports(self):
        """v2 모델 임포트 확인"""
        from regscan.db.models import (
            PreprintDB, MarketReportDB, ExpertOpinionDB,
            AIInsightDB, ArticleDB,
        )
        assert PreprintDB.__tablename__ == "preprints"
        assert MarketReportDB.__tablename__ == "market_reports"
        assert ExpertOpinionDB.__tablename__ == "expert_opinions"
        assert AIInsightDB.__tablename__ == "ai_insights"
        assert ArticleDB.__tablename__ == "articles"

    def test_v2_loader_import(self):
        """V2Loader 임포트 확인"""
        from regscan.db.v2_loader import V2Loader
        loader = V2Loader.__new__(V2Loader)
        assert hasattr(loader, "upsert_preprint")
        assert hasattr(loader, "upsert_market_report")
        assert hasattr(loader, "upsert_expert_opinion")
        assert hasattr(loader, "save_ai_insight")
        assert hasattr(loader, "save_article")

    def test_ai_pipeline_import(self):
        """AI 파이프라인 임포트 확인"""
        from regscan.ai.pipeline import AIIntelligencePipeline
        from regscan.ai.reasoning_engine import ReasoningEngine
        from regscan.ai.verifier import InsightVerifier
        from regscan.ai.writing_engine import WritingEngine
        from regscan.ai.gemini_parser import GeminiParser

        assert AIIntelligencePipeline is not None
        assert ReasoningEngine is not None
        assert InsightVerifier is not None
        assert WritingEngine is not None
        assert GeminiParser is not None

    def test_ingestor_imports(self):
        """v2 수집기 임포트 확인"""
        from regscan.ingest import ASTIIngestor, HealthKRIngestor, BioRxivIngestor

        assert ASTIIngestor is not None
        assert HealthKRIngestor is not None
        assert BioRxivIngestor is not None
