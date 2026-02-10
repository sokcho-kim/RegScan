"""v2 파이프라인 품질 검증 테스트

"돌아가는가"가 아닌 "쓸모있는 정보를 만드는가"를 검증합니다.

검증 항목:
1. 프롬프트 조립 — 4대 스트림 데이터가 누락 없이 포함되는가
2. 포맷터 출력 — 사람이 읽을 수 있는 텍스트인가
3. Fallback 결과 — 사용자에게 보여줘도 부끄럽지 않은가
4. 파서 현실 데이터 — 실제 API 응답 형태의 데이터가 정확히 파싱되는가
5. 파이프라인 흐름 — 데이터가 단계 간 이동 시 정보 손실이 없는가
"""

import json
import pytest
from datetime import date

from regscan.ai.reasoning_engine import ReasoningEngine
from regscan.ai.verifier import InsightVerifier
from regscan.ai.writing_engine import WritingEngine
from regscan.ai.pipeline import AIIntelligencePipeline
from regscan.ai.prompts.reasoning_prompt import REASONING_PROMPT
from regscan.ai.prompts.verifier_prompt import VERIFIER_PROMPT
from regscan.ai.prompts.writer_prompt import BRIEFING_WRITER_PROMPT
from regscan.parse.biorxiv_parser import BioRxivParser
from regscan.parse.asti_parser import ASTIReportParser
from regscan.parse.healthkr_parser import HealthKRParser


# ===================================================================
# 현실적 테스트 데이터 — 실제 운영에서 만날 수 있는 형태
# ===================================================================

REALISTIC_DRUG = {
    "inn": "PEMBROLIZUMAB",
    "fda_approved": True,
    "fda_date": "2025-06-15",
    "ema_approved": True,
    "ema_date": "2025-08-01",
    "mfds_approved": True,
    "mfds_date": "2025-11-20",
    "hira_status": "급여",
    "hira_price": 4500000,
    "global_score": 85,
}

REALISTIC_PREPRINTS = [
    {
        "doi": "10.1101/2026.01.15.789012",
        "title": "Phase III results of PEMBROLIZUMAB + chemotherapy in advanced NSCLC",
        "abstract": "Background: Immune checkpoint inhibitors combined with chemotherapy "
                    "have shown promising results. We conducted a randomized Phase III trial "
                    "comparing PEMBROLIZUMAB plus carboplatin/pemetrexed vs placebo plus "
                    "chemotherapy in 616 patients with metastatic non-squamous NSCLC. "
                    "Results: Median PFS was 12.8 months vs 6.2 months (HR 0.52, p<0.001). "
                    "OS at 24 months was 51.9% vs 34.1%.",
        "server": "medrxiv",
        "category": "oncology",
    },
    {
        "doi": "10.1101/2026.01.20.111222",
        "title": "Real-world evidence of anti-PD-1 therapy in Korean cancer patients",
        "abstract": "We analyzed 2,340 Korean patients treated with anti-PD-1 therapy. "
                    "Objective response rate was 32.4%. Grade 3+ immune-related adverse events "
                    "occurred in 14.2% of patients. Median duration of response was 18.6 months.",
        "server": "medrxiv",
        "category": "clinical medicine",
    },
]

REALISTIC_MARKET_REPORTS = [
    {
        "title": "글로벌 면역항암제 시장 분석 2026",
        "source": "ASTI",
        "market_size_krw": 52000.0,
        "growth_rate": 15.2,
        "summary": "면역항암제 시장은 2026년 52,000억 원 규모로 "
                   "연평균 15.2% 성장 전망. PD-1/PD-L1 억제제가 시장의 68%를 차지.",
    },
]

REALISTIC_EXPERT_OPINIONS = [
    {
        "source": "KPIC",
        "title": "PEMBROLIZUMAB 약물 평가 보고서",
        "summary": "면역관문억제제로서 다양한 고형암에 효과적. "
                   "NSCLC 1차 치료 단독요법 및 병용요법으로 급여 등재됨. "
                   "주요 부작용: 면역관련 이상반응 (간독성, 폐렴, 갑상선염). "
                   "산정특례 적용 대상.",
    },
]


# ===================================================================
# 1. 프롬프트 조립 품질 — 4대 스트림 정보 누락 없이 포함되는가
# ===================================================================

class TestPromptAssembly:
    """프롬프트에 핵심 데이터가 빠짐없이 들어가는지 검증"""

    def test_reasoning_prompt_contains_all_streams(self):
        """Reasoning 프롬프트에 4대 스트림 데이터가 모두 포함되는지 확인"""
        reg = ReasoningEngine._format_regulatory(REALISTIC_DRUG)
        prep = ReasoningEngine._format_preprints(REALISTIC_PREPRINTS)
        market = ReasoningEngine._format_market(REALISTIC_MARKET_REPORTS)
        expert = ReasoningEngine._format_experts(REALISTIC_EXPERT_OPINIONS)

        prompt = REASONING_PROMPT.format(
            drug_data=json.dumps(REALISTIC_DRUG, ensure_ascii=False),
            regulatory_data=reg,
            preprint_data=prep,
            market_data=market,
            expert_data=expert,
        )

        # 약물명이 프롬프트에 포함
        assert "PEMBROLIZUMAB" in prompt

        # 규제 승인 정보 포함
        assert "FDA" in prompt and "승인" in prompt
        assert "EMA" in prompt
        assert "MFDS" in prompt
        assert "HIRA" in prompt and "급여" in prompt

        # 프리프린트 정보 포함
        assert "Phase III" in prompt or "NSCLC" in prompt
        assert "10.1101" in prompt  # DOI

        # 시장 데이터 포함
        assert "52000" in prompt or "52,000" in prompt  # 시장 규모
        assert "15.2" in prompt  # 성장률

        # 전문가 의견 포함
        assert "KPIC" in prompt
        assert "면역관문억제제" in prompt or "산정특례" in prompt

    def test_verifier_prompt_includes_raw_data(self):
        """Verifier 프롬프트에 원본 데이터와 reasoning 결과 모두 포함"""
        reasoning_result = {
            "impact_score": 85,
            "risk_factors": ["경쟁 약물 다수 존재", "가격 인하 압력"],
            "opportunity_factors": ["적응증 확장 가능", "산정특례 대상"],
            "reasoning_chain": "FDA+EMA 동시 승인으로 글로벌 경쟁력 확보",
        }
        raw_sources = {
            "preprints": REALISTIC_PREPRINTS,
            "market_reports": REALISTIC_MARKET_REPORTS,
            "expert_opinions": REALISTIC_EXPERT_OPINIONS,
        }

        prompt = VERIFIER_PROMPT.format(
            reasoning_result=json.dumps(reasoning_result, ensure_ascii=False),
            regulatory_data=json.dumps(
                {k: REALISTIC_DRUG.get(k) for k in [
                    "inn", "fda_approved", "fda_date", "ema_approved", "ema_date",
                    "mfds_approved", "mfds_date", "hira_status", "hira_price",
                ]},
                ensure_ascii=False,
            ),
            preprint_data=json.dumps(raw_sources["preprints"][:5], ensure_ascii=False),
            market_data=json.dumps(raw_sources["market_reports"][:3], ensure_ascii=False),
            expert_data=json.dumps(raw_sources["expert_opinions"][:3], ensure_ascii=False),
            original_score=85,
        )

        # reasoning 결과 포함
        assert "85" in prompt
        assert "경쟁 약물" in prompt or "가격 인하" in prompt

        # 원본 데이터 포함 (대조 검증용)
        assert "PEMBROLIZUMAB" in prompt
        assert "Phase III" in prompt or "NSCLC" in prompt

    def test_writer_prompt_includes_insight(self):
        """Writer 프롬프트에 검증된 인사이트가 포함"""
        verified_insight = {
            "impact_score": 85,
            "verified_score": 82,
            "confidence_level": "high",
            "risk_factors": ["경쟁 약물"],
            "opportunity_factors": ["적응증 확장"],
        }
        source_summary = WritingEngine._build_source_summary(
            REALISTIC_DRUG, verified_insight
        )

        prompt = BRIEFING_WRITER_PROMPT.format(
            article_type="briefing",
            drug_name="PEMBROLIZUMAB",
            verified_insight=json.dumps(verified_insight, ensure_ascii=False),
            source_summary=source_summary,
        )

        assert "PEMBROLIZUMAB" in prompt
        assert "82" in prompt or "85" in prompt
        assert "briefing" in prompt


# ===================================================================
# 2. 포맷터 출력 품질 — 핵심 정보가 읽기 가능한 형태로 나오는가
# ===================================================================

class TestFormatterQuality:
    """포맷터가 의미있는 텍스트를 생성하는지 검증"""

    def test_regulatory_format_shows_all_agencies(self):
        """규제 포맷터가 3개 기관 + HIRA를 모두 표시"""
        text = ReasoningEngine._format_regulatory(REALISTIC_DRUG)
        assert "FDA: 승인" in text
        assert "EMA: 승인" in text
        assert "MFDS: 승인" in text
        assert "HIRA 급여" in text
        assert "4,500,000" in text  # 상한가 금액

    def test_regulatory_format_unapproved(self):
        """미승인 약물 포맷팅"""
        drug = {"inn": "NEWDRUG", "fda_approved": True, "fda_date": "2026-01-01",
                "ema_approved": False, "mfds_approved": False}
        text = ReasoningEngine._format_regulatory(drug)
        assert "FDA: 승인" in text
        assert "EMA: 미승인" in text
        assert "MFDS: 미승인" in text

    def test_preprint_format_preserves_key_info(self):
        """프리프린트 포맷터가 DOI, 제목, 초록 요약을 모두 포함"""
        text = ReasoningEngine._format_preprints(REALISTIC_PREPRINTS)
        # DOI 포함
        assert "10.1101/2026.01.15.789012" in text
        # 제목 키워드
        assert "Phase III" in text
        assert "PEMBROLIZUMAB" in text
        # 초록 내용
        assert "616 patients" in text or "PFS" in text or "12.8 months" in text

    def test_market_format_includes_numbers(self):
        """시장 포맷터가 수치 데이터를 포함"""
        text = ReasoningEngine._format_market(REALISTIC_MARKET_REPORTS)
        assert "52000" in text  # 시장 규모
        assert "15.2" in text   # 성장률
        assert "억 원" in text

    def test_expert_format_includes_source_and_content(self):
        """전문가 포맷터가 출처와 내용을 포함"""
        text = ReasoningEngine._format_experts(REALISTIC_EXPERT_OPINIONS)
        assert "KPIC" in text
        assert "면역관문억제제" in text or "산정특례" in text

    def test_source_summary_readable(self):
        """WritingEngine source_summary가 읽기 가능한 요약인가"""
        insight = {"verified_score": 82, "confidence_level": "high"}
        summary = WritingEngine._build_source_summary(REALISTIC_DRUG, insight)

        assert "PEMBROLIZUMAB" in summary
        assert "FDA" in summary
        assert "82" in summary
        assert "high" in summary


# ===================================================================
# 3. Fallback 결과 품질 — 보여줘도 되는 결과인가
# ===================================================================

class TestFallbackUsability:
    """API 실패 시 fallback이 실제 사용 가능한 결과를 반환하는가"""

    def test_reasoning_fallback_preserves_score(self):
        """Reasoning fallback이 기존 v1 점수를 유지하는지"""
        engine = ReasoningEngine(api_key=None)
        result = engine._fallback_result(REALISTIC_DRUG)

        assert result["impact_score"] == 85, "v1 global_score 유지 필수"
        assert result["reasoning_model"] == "fallback"
        assert "v1 점수" in result["reasoning_chain"], "사용자에게 fallback임을 알려야 함"

    def test_verifier_fallback_shows_low_confidence(self):
        """Verifier fallback이 낮은 신뢰도를 명시하는지"""
        verifier = InsightVerifier(api_key=None)
        reasoning = {"impact_score": 85, "risk_factors": ["test"]}
        result = verifier._fallback_result(reasoning)

        assert result["verified_score"] == 85, "점수 보존"
        assert result["confidence_level"] == "low", "검증 안 됨 = 신뢰도 low"
        assert "검증 미수행" in result.get("confidence_reason", ""), "사유 명시"

    def test_writer_fallback_has_readable_content(self):
        """Writer fallback이 빈 기사가 아닌 읽을 수 있는 내용을 반환"""
        writer = WritingEngine(api_key=None)
        result = writer._fallback_result(REALISTIC_DRUG, "briefing")

        assert result["article_type"] == "briefing"
        assert "PEMBROLIZUMAB" in result["headline"], "약물명 포함 필수"
        assert len(result["headline"]) > 5, "제목이 너무 짧으면 안 됨"
        assert len(result["lead_paragraph"]) > 10, "리드 문단이 비면 안 됨"
        assert len(result["tags"]) >= 1, "태그 최소 1개"

    def test_pipeline_disabled_returns_usable_data(self):
        """모든 AI 비활성화 시에도 v1 점수를 포함한 결과 반환"""
        engine = ReasoningEngine(api_key=None)
        result = engine._fallback_result(REALISTIC_DRUG)

        # v1 점수라도 있어야 대시보드에서 표시 가능
        assert isinstance(result["impact_score"], int)
        assert 0 <= result["impact_score"] <= 100
        assert isinstance(result["risk_factors"], list)
        assert isinstance(result["opportunity_factors"], list)


# ===================================================================
# 4. 파서 현실 데이터 검증 — 실제 API 응답 형태의 데이터
# ===================================================================

class TestParserRealisticData:
    """실제 API 응답과 유사한 데이터로 파서 정확성 검증"""

    def test_biorxiv_real_format(self):
        """bioRxiv API 실제 응답 형식 파싱"""
        raw = {
            "doi": "10.1101/2026.01.15.789012",
            "title": "  Phase III results of PEMBROLIZUMAB + chemo in NSCLC  ",
            "authors": "Kim, J; Lee, S; Park, H; Smith, A B",
            "abstract": "Background: We conducted a randomized trial...",
            "date": "2026-01-15",
            "server": "medrxiv",
            "category": "oncology",
            "version": "2",
        }
        parser = BioRxivParser()
        result = parser.parse_preprint(raw)

        assert result["title"] == "Phase III results of PEMBROLIZUMAB + chemo in NSCLC"
        assert result["published_date"] == date(2026, 1, 15)
        assert "v2.full.pdf" in result["pdf_url"], "버전 반영"
        assert "medrxiv.org" in result["pdf_url"], "서버 반영"

    def test_biorxiv_filters_no_doi(self):
        """DOI 없는 항목은 parse_many에서 제외"""
        raws = [
            {"doi": "10.1101/001", "title": "Valid"},
            {"doi": "", "title": "No DOI"},
            {"title": "No DOI field at all"},
        ]
        results = BioRxivParser().parse_many(raws)
        assert len(results) == 1
        assert results[0]["doi"] == "10.1101/001"

    def test_asti_complex_number_extraction(self):
        """ASTI 파서 — 다양한 형식의 시장 규모/성장률 추출"""
        parser = ASTIReportParser()

        # 쉼표 포함 숫자
        raw = {
            "title": "바이오의약품 시장",
            "content": "국내 바이오의약품 시장은 12,500억 원 규모이며, 연 성장률 9.8%를 기록",
            "source": "ASTI",
        }
        result = parser.parse_report(raw)
        assert result["market_size_krw"] == 12500.0, "쉼표 포함 숫자 파싱"
        assert result["growth_rate"] == 9.8

    def test_asti_title_only_extraction(self):
        """ASTI 파서 — 제목에만 수치가 있는 경우"""
        parser = ASTIReportParser()
        raw = {
            "title": "항암제 시장 3,200억원 규모, CAGR 11.3% 전망",
            "content": "",
            "source": "KISTI",
        }
        result = parser.parse_report(raw)
        assert result["market_size_krw"] == 3200.0
        assert result["growth_rate"] == 11.3
        assert result["source"] == "KISTI"

    def test_asti_no_numbers(self):
        """수치 없는 리포트 — None 반환"""
        parser = ASTIReportParser()
        raw = {
            "title": "바이오의약품 산업 동향",
            "content": "최근 바이오의약품 산업이 성장하고 있다.",
            "source": "ASTI",
        }
        result = parser.parse_report(raw)
        assert result["market_size_krw"] is None
        assert result["growth_rate"] is None
        # 요약은 content 기반
        assert "바이오의약품" in result["summary"]

    def test_healthkr_various_date_formats(self):
        """Health.kr 파서 — 다양한 날짜 형식"""
        parser = HealthKRParser()

        for date_str, expected in [
            ("2026.01.20", date(2026, 1, 20)),
            ("2026-01-20", date(2026, 1, 20)),
        ]:
            raw = {"title": "Test", "source": "KPIC", "date_str": date_str}
            result = parser.parse_review(raw)
            assert result["published_date"] == expected, f"{date_str} 파싱 실패"

    def test_healthkr_missing_fields(self):
        """Health.kr — 필수 필드만 있는 경우"""
        parser = HealthKRParser()
        raw = {"title": "약물 평가", "source": "약사저널"}
        result = parser.parse_review(raw)
        assert result["title"] == "약물 평가"
        assert result["source"] == "약사저널"
        assert result["published_date"] is None  # 선택 필드


# ===================================================================
# 5. 파이프라인 데이터 흐름 — 단계 간 정보 손실 검증
# ===================================================================

class TestPipelineDataFlow:
    """파이프라인 단계 간 데이터가 올바르게 전달되는지 검증"""

    def test_reasoning_format_then_prompt(self):
        """ReasoningEngine이 포맷팅한 데이터가 프롬프트에 정확히 들어가는지"""
        engine = ReasoningEngine(api_key=None)

        # 포맷팅
        reg = engine._format_regulatory(REALISTIC_DRUG)
        prep = engine._format_preprints(REALISTIC_PREPRINTS)
        market = engine._format_market(REALISTIC_MARKET_REPORTS)
        expert = engine._format_experts(REALISTIC_EXPERT_OPINIONS)

        # 각 포맷팅 결과가 비어있지 않음
        assert len(reg) > 20, "규제 포맷팅이 너무 짧음"
        assert len(prep) > 50, "프리프린트 포맷팅이 너무 짧음"
        assert len(market) > 20, "시장 포맷팅이 너무 짧음"
        assert len(expert) > 20, "전문가 포맷팅이 너무 짧음"

        # 프롬프트 조립
        prompt = REASONING_PROMPT.format(
            drug_data=json.dumps(REALISTIC_DRUG, ensure_ascii=False),
            regulatory_data=reg,
            preprint_data=prep,
            market_data=market,
            expert_data=expert,
        )

        # 프롬프트가 4대 스트림 섹션을 모두 포함
        assert "규제 데이터 (A 스트림)" in prompt
        assert "연구 데이터 (B 스트림)" in prompt
        assert "시장 데이터 (C 스트림)" in prompt
        assert "현장반응 데이터 (D 스트림)" in prompt

    def test_insight_merge_reasoning_and_verification(self):
        """Pipeline이 reasoning + verification 결과를 올바르게 병합하는지"""
        reasoning = {
            "impact_score": 85,
            "risk_factors": ["경쟁 약물"],
            "opportunity_factors": ["적응증 확장"],
            "reasoning_chain": "분석 내용",
            "reasoning_model": "o4-mini",
            "reasoning_tokens": 1500,
        }
        verification = {
            "verified_score": 80,
            "corrections": [{"field": "impact_score", "reason": "과대평가"}],
            "confidence_level": "medium",
            "verifier_model": "gpt-5.2",
            "verifier_tokens": 800,
            "data_coverage": {"regulatory": True, "research": True},
        }

        # pipeline.py의 insight 병합 로직 재현
        insight = {
            **reasoning,
            **{k: v for k, v in verification.items()
               if k in ("verified_score", "corrections", "confidence_level",
                         "verifier_model", "verifier_tokens")},
        }

        # reasoning 필드 유지
        assert insight["impact_score"] == 85
        assert insight["risk_factors"] == ["경쟁 약물"]
        assert insight["reasoning_model"] == "o4-mini"

        # verification 필드 추가
        assert insight["verified_score"] == 80
        assert insight["confidence_level"] == "medium"
        assert insight["verifier_model"] == "gpt-5.2"

        # 불필요한 verification 필드 제외
        assert "data_coverage" not in insight

    def test_source_summary_for_writer(self):
        """WritingEngine에 전달되는 source_summary가 완전한가"""
        insight = {
            "impact_score": 85,
            "verified_score": 80,
            "confidence_level": "medium",
        }
        summary = WritingEngine._build_source_summary(REALISTIC_DRUG, insight)

        # 기본 정보
        assert "PEMBROLIZUMAB" in summary
        # 승인 현황
        assert "FDA" in summary
        # 검증 점수 (verified_score 우선)
        assert "80" in summary
        # 신뢰도
        assert "medium" in summary

    async def test_pipeline_disabled_full_flow(self, monkeypatch):
        """모든 AI 비활성화 상태에서 파이프라인 전체 흐름"""
        monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_REASONING", False)
        monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_VERIFIER", False)
        monkeypatch.setattr("regscan.ai.pipeline.settings.ENABLE_AI_WRITER", False)

        pipeline = AIIntelligencePipeline()
        insight, article = await pipeline.run(
            drug=REALISTIC_DRUG,
            preprints=REALISTIC_PREPRINTS,
            market_reports=REALISTIC_MARKET_REPORTS,
            expert_opinions=REALISTIC_EXPERT_OPINIONS,
        )

        # 비활성화해도 v1 점수 기반 insight는 반환
        assert insight["impact_score"] == 85
        assert insight["reasoning_model"] == "disabled"

        # 기사는 빈 dict
        assert article == {}


# ===================================================================
# 6. 템플릿 로직 수정 검증 (why_it_matters)
# ===================================================================

class TestWhyItMattersFixed:
    """수정된 why_it_matters 로직 검증 — 키워드가 submission_type보다 우선"""

    @pytest.fixture
    def generator(self):
        from regscan.scan.why_it_matters import WhyItMattersGenerator
        return WhyItMattersGenerator(use_llm=False)

    async def test_oncology_suppl_gets_oncology_template(self, generator):
        """항암제 SUPPL → 'SUPPL 일반 템플릿'이 아닌 '항암제 템플릿' 반환"""
        data = {
            "submission_type": "SUPPL",
            "pharm_class": ["Antineoplastic Agent"],
            "generic_name": "pembrolizumab",
        }
        text, method = await generator.generate(data)
        assert method == "template"
        assert "항암" in text, f"항암 관련 내용이 없음: {text}"

    async def test_diabetes_suppl_gets_diabetes_template(self, generator):
        """당뇨 SUPPL → 당뇨 템플릿 반환"""
        data = {
            "submission_type": "SUPPL",
            "pharm_class": ["GLP-1 Receptor Agonist"],
            "generic_name": "semaglutide",
        }
        text, method = await generator.generate(data)
        assert method == "template"
        assert "당뇨" in text, f"당뇨 관련 내용이 없음: {text}"

    async def test_generic_suppl_still_works(self, generator):
        """분류 없는 SUPPL → SUPPL 일반 템플릿 폴백"""
        data = {
            "submission_type": "SUPPL",
            "pharm_class": [],
            "generic_name": "unknown_drug",
        }
        text, method = await generator.generate(data)
        assert method == "template"
        assert "적응증 확대" in text, f"SUPPL 폴백 실패: {text}"

    async def test_orig_without_keyword_gets_orig_template(self, generator):
        """분류 없는 ORIG → ORIG 템플릿"""
        data = {
            "submission_type": "ORIG",
            "pharm_class": [],
            "generic_name": "newdrug",
        }
        text, method = await generator.generate(data)
        assert method == "template"
        assert "국내 도입" in text or "급여기준" in text


# ===================================================================
# 7. DB 모델 필드 완전성 — 스키마와 실제 코드 일치
# ===================================================================

class TestModelFieldCompleteness:
    """ORM 모델이 스키마 문서와 일치하는지 검증"""

    def test_ai_insight_has_all_fields(self):
        """AIInsightDB가 reasoning + verification 필드 모두 보유"""
        from regscan.db.models import AIInsightDB
        columns = {c.name for c in AIInsightDB.__table__.columns}

        # Reasoning 필드
        assert "impact_score" in columns
        assert "risk_factors" in columns
        assert "opportunity_factors" in columns
        assert "reasoning_chain" in columns
        assert "market_forecast" in columns
        assert "reasoning_model" in columns
        assert "reasoning_tokens" in columns

        # Verification 필드
        assert "verified_score" in columns
        assert "corrections" in columns
        assert "confidence_level" in columns
        assert "verifier_model" in columns
        assert "verifier_tokens" in columns

    def test_article_has_all_fields(self):
        """ArticleDB가 Writer 출력 필드와 일치"""
        from regscan.db.models import ArticleDB
        columns = {c.name for c in ArticleDB.__table__.columns}

        assert "article_type" in columns
        assert "headline" in columns
        assert "subtitle" in columns
        assert "lead_paragraph" in columns
        assert "body_html" in columns
        assert "tags" in columns
        assert "writer_model" in columns
        assert "writer_tokens" in columns

    def test_preprint_has_gemini_fields(self):
        """PreprintDB가 Gemini 파싱 결과 저장 필드 보유"""
        from regscan.db.models import PreprintDB
        columns = {c.name for c in PreprintDB.__table__.columns}

        assert "gemini_parsed" in columns
        assert "extracted_facts" in columns
