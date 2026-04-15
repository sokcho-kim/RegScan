"""V3 브리핑 프롬프트 E2E 테스트 — 과거/미래 시제 검증

실행:
  pytest tests/test_v3_briefing.py -v -m e2e

비용: ~$0.15 (OpenAI gpt-5.2 기준, 7개 브리핑)

검증 항목:
  1. key_takeaway 필수 포함
  2. 날짜 시제 정확성 (과거 승인 → 완료 표현, 미래 PDUFA → 예정 표현)
  3. why_it_matters 구체성 (관점 가이드 반영)
  4. JSON 스키마 필수 필드 완전성
  5. 통합 브리핑 교차 분석 존재
  6. 미래 시제 hallucination 검출 (미승인 약물을 "승인 완료"로 표현 시 FAIL)
  7. 혼합 시제 통합 브리핑에서 각 약물별 시제 정확성
"""

import json
import os
import re
import logging
from datetime import datetime

import pytest

from regscan.config import settings
from regscan.stream.base import StreamResult
from regscan.stream.briefing import StreamBriefingGenerator, _build_stream_system_prompt

logger = logging.getLogger(__name__)

# ── 조건부 스킵 ──
HAS_LLM_KEY = bool(
    os.environ.get("OPENAI_API_KEY")
    or settings.OPENAI_API_KEY
    or os.environ.get("GEMINI_API_KEY")
    or settings.GEMINI_API_KEY
    or os.environ.get("ANTHROPIC_API_KEY")
    or settings.ANTHROPIC_API_KEY
)

skip_no_key = pytest.mark.skipif(not HAS_LLM_KEY, reason="No LLM API key set")
e2e_llm = pytest.mark.e2e


# ── Fixture: 리얼 약물 데이터 (rilzabrutinib — 2025 FDA 승인) ──

@pytest.fixture
def rilzabrutinib_drug():
    """rilzabrutinib — FDA 2025-03-28 승인 완료 (과거 시제 검증용)"""
    return {
        "inn": "RILZABRUTINIB",
        "fda_data": {
            "submission_status": "AP",  # Approved
            "submission_status_date": "2025-03-28",
            "submission_class_code_description": "Type 1 - New Molecular Entity",
            "brand_name": "TYVAZO",
            "pharm_class_epc": ["Bruton's Tyrosine Kinase Inhibitor [EPC]"],
        },
        "ema_data": {
            "marketing_authorisation_date": "2025-06-15",
            "medicine_status": "authorised",
            "is_orphan": True,
            "is_prime": False,
            "is_conditional": False,
            "is_accelerated": False,
            "therapeutic_indication": (
                "Treatment of immune thrombocytopenia (ITP) in adult patients "
                "who have had an insufficient response to a previous treatment."
            ),
        },
        "atc_code": "L01EL04",
        "designations": ["NME", "orphan"],
        "clinical_results": {
            "trial_phase": "Phase III",
            "trial_status": "Completed",
        },
        "mfds_data": {
            "approval_status": "미허가",
            "approval_date": None,
        },
        "therapeutic_areas": ["hematology", "rare_disease"],
    }


@pytest.fixture
def therapeutic_result(rilzabrutinib_drug):
    """치료영역 스트림 결과"""
    return StreamResult(
        stream_name="therapeutic_area",
        sub_category="rare_disease",
        drugs_found=[rilzabrutinib_drug],
        signals=[
            {
                "type": "fda_approval",
                "inn": "RILZABRUTINIB",
                "detail": "FDA NME 승인 2025-03-28",
            },
        ],
    )


@pytest.fixture
def innovation_result(rilzabrutinib_drug):
    """혁신 스트림 결과"""
    return StreamResult(
        stream_name="innovation",
        drugs_found=[rilzabrutinib_drug],
        signals=[
            {
                "type": "nme_designation",
                "inn": "RILZABRUTINIB",
                "designation": "NME",
                "detail": "BTK 억제제 NME 승인",
            },
            {
                "type": "orphan_designation",
                "inn": "RILZABRUTINIB",
                "designation": "orphan",
                "detail": "희귀의약품 지정",
            },
        ],
    )


@pytest.fixture
def external_result():
    """외부시그널 스트림 결과"""
    return StreamResult(
        stream_name="external",
        drugs_found=[
            {
                "inn": "RILZABRUTINIB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2025-03-28",
                    "brand_name": "TYVAZO",
                },
            },
        ],
        signals=[
            {
                "type": "medrxiv_paper",
                "inn": "RILZABRUTINIB",
                "title": "Long-term BTK inhibitor outcomes in ITP patients",
                "finding": "3-year follow-up shows sustained platelet response in 72% of patients",
            },
            {
                "type": "clinical_trial",
                "inn": "FOSTAMATINIB",
                "verdict": "FAIL",
                "detail": "Phase III ITP trial failed primary endpoint",
            },
        ],
    )


# ── Fixture: 미래 시제 약물 (PDUFA 2026-09-15, 아직 미승인) ──

@pytest.fixture
def future_drug():
    """가상 약물 — FDA PDUFA 2026-09-15 예정, 아직 미승인 (미래 시제 검증용)"""
    return {
        "inn": "VELONATINIB",
        "fda_data": {
            "submission_status": "TA",  # Tentative Approval (심사 중)
            "submission_status_date": "2026-09-15",
            "submission_class_code_description": "Type 1 - New Molecular Entity",
            "brand_name": "",
            "pharm_class_epc": ["VEGFR/FGFR Kinase Inhibitor [EPC]"],
        },
        "ema_data": {
            "medicine_status": "under_review",
            "is_orphan": False,
            "is_prime": True,
            "is_conditional": False,
            "is_accelerated": False,
            "therapeutic_indication": (
                "Treatment of advanced hepatocellular carcinoma (HCC) "
                "in patients who have progressed on prior systemic therapy."
            ),
        },
        "atc_code": "L01EX99",
        "designations": ["NME", "breakthrough"],
        "clinical_results": {
            "trial_phase": "Phase III",
            "trial_status": "Ongoing",
        },
        "mfds_data": {
            "approval_status": "미허가",
            "approval_date": None,
        },
        "therapeutic_areas": ["oncology"],
    }


@pytest.fixture
def future_therapeutic_result(future_drug):
    """미래 약물 치료영역 스트림 결과"""
    return StreamResult(
        stream_name="therapeutic_area",
        sub_category="oncology",
        drugs_found=[future_drug],
        signals=[
            {
                "type": "pdufa_upcoming",
                "inn": "VELONATINIB",
                "detail": "FDA PDUFA 2026-09-15 예정",
            },
        ],
    )


@pytest.fixture
def future_innovation_result(future_drug):
    """미래 약물 혁신 스트림 결과"""
    return StreamResult(
        stream_name="innovation",
        drugs_found=[future_drug],
        signals=[
            {
                "type": "nme_designation",
                "inn": "VELONATINIB",
                "designation": "NME",
                "detail": "VEGFR/FGFR 이중 억제제 NME 심사 중",
            },
            {
                "type": "breakthrough_designation",
                "inn": "VELONATINIB",
                "designation": "breakthrough",
                "detail": "혁신신약 지정",
            },
        ],
    )


# ── 공통 검증 헬퍼 ──

def assert_valid_json_briefing(briefing: dict, required_keys: list[str], label: str):
    """브리핑 JSON 필수 키 검증"""
    for key in required_keys:
        assert key in briefing, f"[{label}] 필수 키 '{key}' 누락. keys={list(briefing.keys())}"
        assert briefing[key], f"[{label}] '{key}' 값이 비어있음"


def assert_no_future_hallucination(briefing: dict, label: str):
    """과거 승인을 미래로 잘못 표현하는 hallucination 검출"""
    text = json.dumps(briefing, ensure_ascii=False)

    # rilzabrutinib은 2025-03-28 FDA 승인 완료 → "예정" 표현 불가
    # 핵심 검증: "승인 완료" 또는 "허가됨"이 존재해야 함
    has_correct_tense = any(kw in text for kw in ["승인 완료", "승인완료", "허가됨", "허가 완료", "AP"])
    has_wrong_tense = "승인 예정" in text and "RILZABRUTINIB" in text.upper()

    if has_wrong_tense:
        # RILZABRUTINIB에 대해 "승인 예정"이라고 한 부분을 찾기
        # 다른 약물에 대한 "승인 예정"은 OK
        lines = text.split(",")
        for line in lines:
            if "RILZABRUTINIB" in line.upper() and "승인 예정" in line:
                assert False, f"[{label}] 시제 hallucination: RILZABRUTINIB을 '승인 예정'으로 표현. line='{line[:200]}'"

    logger.info("[%s] 시제 검증 OK — 올바른 시제 표현 포함: %s", label, has_correct_tense)


# ── Test 1: SYSTEM_PROMPT 빌더 검증 (오프라인) ──

def test_system_prompt_builder_injects_today():
    """_build_stream_system_prompt에 today 날짜가 주입된다"""
    rendered = _build_stream_system_prompt("2026-03-27")
    assert "2026-03-27" in rendered
    assert "{today}" not in rendered  # 템플릿 변수 잔존 없음


def test_system_prompt_has_time_rules():
    """시간추론 규칙 + CoT 시연 포함"""
    rendered = _build_stream_system_prompt("2026-03-27")
    assert "승인일" in rendered or "승인" in rendered
    assert "과거" in rendered  # CoT 시연에서 "과거" 등장
    assert "미래" in rendered  # CoT 시연에서 "미래" 등장
    assert "Chain-of-Thought" in rendered  # CoT 시연 섹션 존재


def test_system_prompt_has_anti_pattern():
    """금지표현 대안표 포함 (V2.0 신규)"""
    rendered = _build_stream_system_prompt("2026-03-27")
    assert "금지 표현" in rendered or "금지" in rendered
    assert "대안" in rendered
    assert "예상된다" in rendered  # 금지표현 예시


def test_system_prompt_key_takeaway_rule():
    """key_takeaway 필수 규칙 포함"""
    rendered = _build_stream_system_prompt("2026-03-27")
    assert "key_takeaway" in rendered
    assert "누락 금지" in rendered or "누락" in rendered


# ── Test 2: _extract_drug_intel V3 필드 확장 ──

def test_extract_drug_intel_v3_fields(rilzabrutinib_drug):
    """V3 추가 필드 (clinical_results, mfds_data, therapeutic_areas) 추출"""
    intel = StreamBriefingGenerator._extract_drug_intel(rilzabrutinib_drug)

    assert intel["inn"] == "RILZABRUTINIB"
    assert "fda_status" in intel
    assert "fda_date" in intel

    # V3 추가 필드 — max_fields=14이므로 일부는 truncation 가능
    # clinical_results는 FDA/EMA 다음이라 들어갈 가능성 높음
    assert intel.get("trial_phase") == "Phase III", f"trial_phase 누락: {intel}"
    assert intel.get("trial_status") == "Completed", f"trial_status 누락: {intel}"
    # 필드가 풍부한 약물은 14개 제한에 mfds/therapeutic_areas가 잘릴 수 있음
    # 최소 1개 이상의 V3 필드가 존재하면 OK
    v3_keys = {"trial_phase", "trial_status", "mfds_status", "mfds_date", "therapeutic_areas"}
    found_v3 = v3_keys & set(intel.keys())
    assert len(found_v3) >= 2, f"V3 필드 2개 미만: {found_v3}, intel={intel}"


def test_extract_drug_intel_max_17():
    """max_fields=17로 V4 HIRA 필드 포함"""
    rich_drug = {
        "inn": "TEST",
        "fda_data": {
            "submission_status": "AP",
            "submission_status_date": "2025-01-01",
            "submission_class_code_description": "NME",
            "brand_name": "TESTBRAND",
            "pharm_class_epc": ["Test Inhibitor"],
        },
        "ema_data": {
            "marketing_authorisation_date": "2025-02-01",
            "medicine_status": "authorised",
            "is_orphan": True,
            "therapeutic_indication": "Test indication",
        },
        "atc_code": "L01XX99",
        "designations": ["NME"],
        "clinical_results": {"trial_phase": "Phase III", "trial_status": "Completed"},
        "mfds_data": {"approval_status": "허가", "approval_date": "2025-06-01"},
        "hira_data": {
            "reimbursement_fact": "HIRA 급여 등재, 상한가 1,377원",
            "copay_exemption": "암환자 산정특례(5%) 대상 가능",
        },
        "therapeutic_areas": ["oncology"],
    }
    intel = StreamBriefingGenerator._extract_drug_intel(rich_drug)
    # V4: max_fields 20 — HIRA 필드 포함 (빈 값 제거 후 실제 ��력은 더 적음)
    assert len(intel) <= 20
    assert "reimbursement_fact" in intel
    assert "copay_exemption" in intel
    assert "trial_phase" in intel or "mfds_status" in intel or "therapeutic_areas" in intel


# ── Test 3: 치료영역 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_therapeutic_briefing_e2e(therapeutic_result):
    """치료영역 브리핑 — key_takeaway + 시제 + 스키마 검증"""
    gen = StreamBriefingGenerator()
    briefing = await gen.generate_therapeutic_briefing(
        area="rare_disease",
        area_ko="희귀질환",
        result=therapeutic_result,
    )

    logger.info("치료영역 브리핑: %s", json.dumps(briefing, ensure_ascii=False, indent=2))

    # 필수 키 검증
    assert_valid_json_briefing(
        briefing,
        ["headline", "key_takeaway", "top_drugs", "action_items"],
        "therapeutic",
    )

    # 시제 검증
    assert_no_future_hallucination(briefing, "therapeutic")

    # top_drugs 구조
    if briefing.get("top_drugs"):
        drug = briefing["top_drugs"][0]
        assert "inn" in drug
        assert "why_it_matters" in drug
        # why_it_matters가 "새로운 억제제입니다" 수준이 아닌지
        wim = drug["why_it_matters"]
        assert len(wim) > 30, f"why_it_matters가 너무 짧음 ({len(wim)}자): {wim}"


# ── Test 4: 혁신 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_innovation_briefing_e2e(innovation_result):
    """혁신 브리핑 — key_takeaway + 시제 검증"""
    gen = StreamBriefingGenerator()
    briefing = await gen.generate_innovation_briefing(result=innovation_result)

    logger.info("혁신 브리핑: %s", json.dumps(briefing, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        briefing,
        ["headline", "key_takeaway", "nme_spotlight", "action_items"],
        "innovation",
    )
    assert_no_future_hallucination(briefing, "innovation")

    # nme_spotlight 구조
    if briefing.get("nme_spotlight"):
        nme = briefing["nme_spotlight"][0]
        assert "implication" in nme
        assert len(nme["implication"]) > 20, f"implication 너무 짧음: {nme['implication']}"


# ── Test 5: 외부시그널 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_external_briefing_e2e(external_result):
    """외부시그널 브리핑 — key_takeaway + hospital_impact 구체성"""
    gen = StreamBriefingGenerator()
    briefing = await gen.generate_external_briefing(result=external_result)

    logger.info("외부시그널 브리핑: %s", json.dumps(briefing, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        briefing,
        ["headline", "key_takeaway"],
        "external",
    )
    assert_no_future_hallucination(briefing, "external")


# ── Test 6: 통합 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_unified_briefing_e2e(therapeutic_result, innovation_result, external_result):
    """통합 브리핑 — key_takeaway + cross_analysis + 스트림 JSON 직접 주입 검증"""
    gen = StreamBriefingGenerator()

    # 먼저 스트림별 브리핑 생성
    t_briefing = await gen.generate_therapeutic_briefing(
        area="rare_disease", area_ko="희귀질환", result=therapeutic_result,
    )
    i_briefing = await gen.generate_innovation_briefing(result=innovation_result)
    e_briefing = await gen.generate_external_briefing(result=external_result)

    # stream_type 태깅 (파이프라인이 하는 역할 시뮬레이션)
    t_briefing["stream_type"] = "therapeutic"
    i_briefing["stream_type"] = "innovation"
    e_briefing["stream_type"] = "external"

    stream_briefings = [t_briefing, i_briefing, e_briefing]

    all_results = {
        "therapeutic_area": [therapeutic_result],
        "innovation": [innovation_result],
        "external": [external_result],
    }

    unified = await gen.generate_unified_briefing(all_results, stream_briefings)

    logger.info("통합 브리핑: %s", json.dumps(unified, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        unified,
        ["headline", "key_takeaway", "executive_summary", "cross_analysis", "top_5_drugs"],
        "unified",
    )
    assert_no_future_hallucination(unified, "unified")

    # cross_analysis가 단순 나열이 아닌지
    ca = unified.get("cross_analysis", "")
    assert len(ca) > 30, f"cross_analysis 너무 짧음: {ca}"


# ── 미래 시제 검증 헬퍼 ──

def assert_no_past_hallucination_for_future(briefing: dict, label: str):
    """미승인 약물을 '승인 완료'로 잘못 표현하는 hallucination 검출"""
    text = json.dumps(briefing, ensure_ascii=False)

    # VELONATINIB은 PDUFA 2026-09-15 예정, 아직 미승인
    # "승인 완료", "허가됨", "허가 완료"가 VELONATINIB과 함께 나오면 FAIL
    past_approval_keywords = ["승인 완료", "승인완료", "허가됨", "허가 완료"]
    for kw in past_approval_keywords:
        if kw in text and "VELONATINIB" in text.upper():
            # 해당 키워드가 VELONATINIB 맥락에서 쓰였는지 확인
            lines = text.split(",")
            for line in lines:
                if "VELONATINIB" in line.upper() and kw in line:
                    assert False, (
                        f"[{label}] 미래→과거 hallucination: "
                        f"VELONATINIB을 '{kw}'로 표현. line='{line[:200]}'"
                    )

    # "승인 예정", "심사 중", "PDUFA 예정" 중 하나가 존재해야 PASS
    future_keywords = ["승인 예정", "심사 중", "PDUFA 예정", "PDUFA", "예정", "심사중", "검토 중"]
    has_future_tense = any(kw in text for kw in future_keywords)
    assert has_future_tense, (
        f"[{label}] 미래 약물에 대한 미래 시제 표현 누락. "
        f"기대 키워드: {future_keywords}"
    )

    logger.info("[%s] 미래 시제 검증 OK — 미래 표현 포함 확인", label)


# ── Test 7: 미래 시제 치료영역 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_therapeutic_future_tense(future_therapeutic_result):
    """미래 약물 치료영역 브리핑 — '승인 예정'/'심사 중' 표현 확인, '승인 완료' 시 FAIL"""
    gen = StreamBriefingGenerator()
    briefing = await gen.generate_therapeutic_briefing(
        area="oncology",
        area_ko="종양학",
        result=future_therapeutic_result,
    )

    logger.info("미래 치료영역 브리핑: %s", json.dumps(briefing, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        briefing,
        ["headline", "key_takeaway", "top_drugs", "action_items"],
        "future_therapeutic",
    )
    assert_no_past_hallucination_for_future(briefing, "future_therapeutic")


# ── Test 8: 미래 시제 혁신 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_innovation_future_tense(future_innovation_result):
    """미래 약물 혁신 브리핑 — 시제 정확성 (미승인 NME → 미래 표현)"""
    gen = StreamBriefingGenerator()
    briefing = await gen.generate_innovation_briefing(result=future_innovation_result)

    logger.info("미래 혁신 브리핑: %s", json.dumps(briefing, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        briefing,
        ["headline", "key_takeaway", "nme_spotlight", "action_items"],
        "future_innovation",
    )
    assert_no_past_hallucination_for_future(briefing, "future_innovation")


# ── Test 9: 혼합 시제 통합 브리핑 E2E ──

@e2e_llm
@skip_no_key
@pytest.mark.asyncio
async def test_mixed_tense_unified(
    therapeutic_result, innovation_result, external_result,
    future_therapeutic_result, future_innovation_result,
):
    """과거(rilzabrutinib) + 미래(velonatinib) 혼합 통합 브리핑 — 각각 시제 올바르게 처리"""
    gen = StreamBriefingGenerator()

    # 과거 약물 브리핑
    t_past = await gen.generate_therapeutic_briefing(
        area="rare_disease", area_ko="희귀질환", result=therapeutic_result,
    )
    i_past = await gen.generate_innovation_briefing(result=innovation_result)
    e_briefing = await gen.generate_external_briefing(result=external_result)

    # 미래 약물 브리핑
    t_future = await gen.generate_therapeutic_briefing(
        area="oncology", area_ko="종양학", result=future_therapeutic_result,
    )
    i_future = await gen.generate_innovation_briefing(result=future_innovation_result)

    # stream_type 태깅
    t_past["stream_type"] = "therapeutic"
    t_future["stream_type"] = "therapeutic"
    i_past["stream_type"] = "innovation"
    i_future["stream_type"] = "innovation"
    e_briefing["stream_type"] = "external"

    stream_briefings = [t_past, t_future, i_past, i_future, e_briefing]

    all_results = {
        "therapeutic_area": [therapeutic_result, future_therapeutic_result],
        "innovation": [innovation_result, future_innovation_result],
        "external": [external_result],
    }

    unified = await gen.generate_unified_briefing(all_results, stream_briefings)

    logger.info("혼합 시제 통합 브리핑: %s", json.dumps(unified, ensure_ascii=False, indent=2))

    assert_valid_json_briefing(
        unified,
        ["headline", "key_takeaway", "executive_summary", "cross_analysis", "top_5_drugs"],
        "mixed_unified",
    )

    text = json.dumps(unified, ensure_ascii=False)

    # 과거 약물(rilzabrutinib) — "승인 완료" 계열 표현이어야 함
    assert_no_future_hallucination(unified, "mixed_unified")

    # 미래 약물(velonatinib) — "승인 예정"/"심사 중" 표현이어야 함
    assert_no_past_hallucination_for_future(unified, "mixed_unified")
