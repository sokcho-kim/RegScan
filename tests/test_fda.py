"""FDA 파이프라인 테스트"""

import pytest
from datetime import datetime

from regscan.models import SourceType, ChangeType, ImpactLevel
from regscan.parse.fda_parser import FDADrugParser
from regscan.scan.why_it_matters import WhyItMattersGenerator


# =============================================================================
# FDA Parser 테스트
# =============================================================================

class TestFDADrugParser:
    """FDA 파서 테스트"""

    def test_parse_approval_basic(self):
        """기본 파싱 테스트"""
        raw = {
            "application_number": "NDA215678",
            "sponsor_name": "NOVO NORDISK",
            "products": [
                {
                    "brand_name": "WEGOVY",
                    "active_ingredients": [{"name": "SEMAGLUTIDE"}],
                    "dosage_form": "INJECTION",
                    "marketing_status": "Prescription",
                }
            ],
            "submissions": [
                {
                    "submission_type": "SUPPL",
                    "submission_status": "AP",
                    "submission_status_date": "20260125",
                }
            ],
        }

        parser = FDADrugParser()
        result = parser.parse_approval(raw)

        assert result["application_number"] == "NDA215678"
        assert result["brand_name"] == "WEGOVY"
        assert result["generic_name"] == "SEMAGLUTIDE"
        assert result["sponsor"] == "NOVO NORDISK"
        assert result["submission_type"] == "SUPPL"
        assert result["submission_status_date"] == "20260125"

    def test_parse_approval_missing_products(self):
        """제품 정보 없는 경우"""
        raw = {
            "application_number": "NDA999999",
            "sponsor_name": "TEST PHARMA",
            "products": [],
            "submissions": [],
        }

        parser = FDADrugParser()
        result = parser.parse_approval(raw)

        assert result["brand_name"] == ""
        assert result["generic_name"] == ""

    def test_build_source_url(self):
        """URL 생성 테스트"""
        parser = FDADrugParser()

        url = parser._build_source_url("NDA215678")
        assert "215678" in url
        assert "accessdata.fda.gov" in url


# =============================================================================
# WhyItMatters 테스트
# =============================================================================

class TestWhyItMattersGenerator:
    """why_it_matters 생성기 테스트"""

    @pytest.fixture
    def generator(self):
        """LLM 없는 생성기"""
        return WhyItMattersGenerator(use_llm=False)

    @pytest.mark.asyncio
    async def test_template_orig(self, generator):
        """신규 승인 템플릿"""
        data = {
            "submission_type": "ORIG",
            "pharm_class": [],
            "generic_name": "test drug",
        }

        text, method = await generator.generate(data)

        assert method == "template"
        assert "국내" in text or "급여" in text

    @pytest.mark.asyncio
    async def test_template_oncology(self, generator):
        """항암제 템플릿"""
        data = {
            "submission_type": "SUPPL",
            "pharm_class": ["Antineoplastic Agent"],
            "generic_name": "pembrolizumab",
        }

        text, method = await generator.generate(data)

        assert method == "template"
        assert "항암" in text or "급여" in text

    @pytest.mark.asyncio
    async def test_template_diabetes(self, generator):
        """당뇨병 템플릿"""
        data = {
            "submission_type": "SUPPL",
            "pharm_class": ["GLP-1 Receptor Agonist"],
            "generic_name": "semaglutide",
        }

        text, method = await generator.generate(data)

        assert method == "template"

    @pytest.mark.asyncio
    async def test_template_default(self, generator):
        """기본 템플릿"""
        data = {
            "submission_type": "UNKNOWN",
            "pharm_class": [],
            "generic_name": "unknown drug",
        }

        text, method = await generator.generate(data)

        assert method == "template"
        assert len(text) <= 80


# =============================================================================
# 통합 테스트
# =============================================================================

class TestIntegration:
    """통합 테스트"""

    @pytest.mark.asyncio
    async def test_parse_and_generate(self):
        """파싱 → 변환 통합 테스트"""
        from regscan.scan import SignalGenerator

        raw = {
            "application_number": "NDA215678",
            "sponsor_name": "NOVO NORDISK",
            "products": [
                {
                    "brand_name": "WEGOVY",
                    "active_ingredients": [{"name": "SEMAGLUTIDE"}],
                    "dosage_form": "INJECTION",
                    "marketing_status": "Prescription",
                }
            ],
            "submissions": [
                {
                    "submission_type": "ORIG",
                    "submission_status": "AP",
                    "submission_status_date": "20260125",
                }
            ],
            "openfda": {
                "pharm_class_epc": ["GLP-1 Receptor Agonist"],
            },
        }

        # 파싱
        parser = FDADrugParser()
        parsed = parser.parse_approval(raw)

        # 변환
        generator = SignalGenerator(use_llm=False)
        card = await generator.generate(parsed, SourceType.FDA_APPROVAL)

        # 검증
        assert card.source_type == SourceType.FDA_APPROVAL
        assert "WEGOVY" in card.title
        assert card.change_type == ChangeType.NEW  # ORIG
        assert card.impact_level == ImpactLevel.HIGH  # ORIG는 HIGH
        assert "NOVO NORDISK" in card.tags
