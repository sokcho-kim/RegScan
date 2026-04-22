"""Stream Briefing Generator — 공통 기반 + 스트림 전용 프롬프트

stream-briefing 2.0.0 (2026-03-30):
  - 공통 기반: regscan.prompts.shared (Persona, 시간추론+CoT, 금지표현, 도메인지식, 생애주기)
  - P0 적용: Few-shot 완전 입출력 (치료영역 1쌍 + 혁신 1쌍)
  - P0 적용: CoT 추론 시연 (shared.TIME_REASONING_RULES에 포함)
  - P0 적용: 금지표현 대안표 (shared.ANTI_PATTERN_TABLE)
  - P1 적용: 생애주기 분기 (shared.LIFECYCLE_BRANCHES)
  - P1 적용: 스트림별 분석 프레임 (3-4단계)
  - P1 적용: Persona 확장 (shared.PERSONA)
  - P1 적용: 도메인 지식 주입 (shared.DOMAIN_KNOWLEDGE_*)
  - 롤백: V1.2.0은 SYSTEM_PROMPT_V1_2로 보존

이전 버전:
  V1.2.0: 시간추론 규칙 + GOOD/BAD 톤 예시 + 14필드 인텔리전스
  V1.1.0: Executive Tone 적용
  V1.0.0: 스트림 브리핑 신규 생성
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from regscan.config import settings
from regscan.prompts.shared import build_system_prompt
from regscan.stream.base import StreamResult

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────
# HIRA Enrichment — DB에서 급여 정보를 조회하여 drug dict에 주입
# ────────────────────────────────────────────────────────

async def enrich_drugs_with_hira(drugs: list[dict]) -> int:
    """drugs_found 리스트에 HIRA 급여 데이터를 주입한다.

    1차: DB에서 INN 기준으로 hira_reimbursements 조회 (PostgreSQL 환경)
    2차: DB 미사용 or 미매칭 → IngredientBridge JSON 직접 조회 (fallback)

    Returns:
        enriched count
    """
    if not drugs:
        return 0

    enriched = 0

    # ── 1차: DB 경유 ──
    try:
        from sqlalchemy import select
        from regscan.db.database import get_async_session
        from regscan.db.models import DrugDB, HIRAReimbursementDB

        inn_to_drugs: dict[str, list[dict]] = {}
        for d in drugs:
            inn = (d.get("inn") or "").strip().upper()
            if inn:
                inn_to_drugs.setdefault(inn, []).append(d)

        if inn_to_drugs:
            session_factory = get_async_session()
            async with session_factory() as session:
                stmt = (
                    select(DrugDB.inn, HIRAReimbursementDB)
                    .join(HIRAReimbursementDB, DrugDB.id == HIRAReimbursementDB.drug_id)
                    .where(DrugDB.inn.in_([inn for inn in inn_to_drugs]))
                )
                result = await session.execute(stmt)
                rows = result.all()

                for drug_inn, hira_row in rows:
                    norm_inn = drug_inn.strip().upper()
                    targets = inn_to_drugs.get(norm_inn, [])
                    if not targets:
                        for key in inn_to_drugs:
                            if key == norm_inn:
                                targets = inn_to_drugs[key]
                                break
                    if not targets:
                        continue
                    hira_dict = _build_hira_intel(hira_row)
                    for drug_dict in targets:
                        drug_dict["hira_data"] = hira_dict
                        enriched += 1
    except Exception as e:
        logger.debug("HIRA DB 경로 스킵: %s", e)

    # ── 2차: IngredientBridge JSON fallback (DB 미주입 약물 대상) ──
    remaining = [d for d in drugs if "hira_data" not in d]
    if remaining:
        bridge_count = _enrich_via_bridge(remaining)
        enriched += bridge_count

    if enriched:
        logger.info("[HIRA Enrichment] %d/%d 약물에 급여 데이터 주입", enriched, len(drugs))
    return enriched


# ── IngredientBridge 기반 JSON 직접 조회 ──

_bridge_instance = None


def _get_bridge():
    """IngredientBridge 싱글턴 (최초 1회 로드)"""
    global _bridge_instance
    if _bridge_instance is not None:
        return _bridge_instance

    from pathlib import Path
    from regscan.map.ingredient_bridge import IngredientBridge

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    bridge = IngredientBridge()

    master = data_dir / "bridge" / "yakga_ingredient_master.csv"
    atc = data_dir / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"

    # HIRA 약가 JSON — 최신 파일 자동 탐색
    hira_dir = data_dir / "hira"
    hira_files = sorted(hira_dir.glob("drug_prices_*.json"), reverse=True) if hira_dir.exists() else []

    if not master.exists():
        logger.warning("IngredientBridge 마스터 없음: %s", master)
        return None

    bridge.load_master(master)
    if atc.exists():
        bridge.load_atc_mapping(atc)
    if hira_files:
        bridge.load_hira(hira_files[0])
        logger.info("[HIRA Bridge] 로드: %s", hira_files[0].name)
    else:
        logger.warning("HIRA 약가 JSON 없음 — 급여 상태만 제공")

    _bridge_instance = bridge
    return bridge


def _extract_dosage_from_raw(raw: dict) -> str:
    """HIRA raw_data에서 용량/규격 추출.

    제품명 예: "키트루다주(펨브롤리주맙,유전자재조합)_(0.1g/4mL)"
    → "(100mg/4mL)"
    """
    product_name = raw.get("제품명") or ""
    # 제품명 끝의 _(용량) 패턴
    import re
    m = re.search(r"_\(([^)]+)\)\s*$", product_name)
    if m:
        return m.group(1)
    return ""


def _get_hira_source_date() -> str:
    """현재 사용 중인 HIRA 약가 JSON의 기준일."""
    from pathlib import Path
    data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "hira"
    files = sorted(data_dir.glob("drug_prices_*.json"), reverse=True)
    if files:
        import re
        m = re.search(r"(\d{8})", files[0].name)
        return m.group(1) if m else "unknown"
    return "unknown"


# 확정 문장 금지 가드레일
_GUARDRAIL_TEMPLATES: dict[str, str] = {
    "bridge_unmatched": "심평원 매핑 실패 — 급여/가격 정보 확인 불가 (수동 확인 필요)",
    "not_found_ambiguous": "심평원 원천 데이터에 없음 — 미등재 또는 수집 누락 가능 (단정 불가)",
    "mfds_not_found": "국내 허가 여부 미확인 (수집 데이터 부재, '미허가' 단정 불가)",
}


def _enrich_via_bridge(drugs: list[dict]) -> int:
    """IngredientBridge로 INN → HIRA 직접 매칭

    심평원 상태 7단계 + confidence + source date + 가드레일:
      - reimbursed: 급여 등재 (상한가+규격 포함)
      - non_reimbursed / not_covered: 비급여
      - delisted / deleted: 급여 삭제 (과거 이력)
      - not_found_in_source / not_found: 원천에 없음 (단정 불가)
      - bridge_unmatched: 매칭 실패 (수동 확인 필요)
    """
    bridge = _get_bridge()
    if bridge is None:
        return 0

    source_date = _get_hira_source_date()

    enriched = 0
    for drug_dict in drugs:
        inn = (drug_dict.get("inn") or "").strip()
        if not inn:
            continue

        result = bridge.lookup(inn)

        # match confidence 판정
        method = result.match_method
        if method == "unmatched":
            # bridge_unmatched도 기록 (가드레일용)
            drug_dict["hira_data"] = {
                "reimbursement_fact": _GUARDRAIL_TEMPLATES["bridge_unmatched"],
                "match_confidence": "unmatched",
                "match_method": method,
                "is_guardrailed": True,
                "source_date": source_date,
            }
            enriched += 1
            continue

        if method == "normalized":
            confidence = "exact_match"
        elif method == "decomposed_variant":
            confidence = "normalized_match"
        elif method == "decomposed_base_fallback":
            confidence = "base_fallback_match"
        elif method == "atc":
            confidence = "atc_fallback"
        else:
            confidence = method

        status = result.status.value
        price = result.price_ceiling
        code = result.ingredient_code or ""
        raw = result.raw_data or {}

        # 용량/규격 추출
        dosage = _extract_dosage_from_raw(raw)
        dosage_str = f" ({dosage})" if dosage else ""
        price_str = f", 상한가 {price:,.0f}원{dosage_str}" if price and status == "reimbursed" else ""

        if status == "reimbursed":
            fact = f"심평원 급여 등재{price_str}"
        elif status in ("not_covered", "non_reimbursed"):
            fact = "심평원 비급여 (전액 환자부담)"
        elif status in ("deleted", "delisted"):
            fact = "심평원 급여 삭제 (과거 등재 이력)"
        elif status == "herbal":
            fact = "한약재/생약 (별도 급여 체계)"
        else:
            fact = _GUARDRAIL_TEMPLATES["not_found_ambiguous"]

        # 가드레일 판정
        is_guardrailed = confidence in ("base_fallback_match", "atc_fallback", "unmatched")

        hira_data: dict[str, Any] = {
            "reimbursement_fact": fact,
            "match_method": method,
            "match_confidence": confidence,
            "source_date": source_date,
            "is_guardrailed": is_guardrailed,
        }
        if price and status == "reimbursed":
            hira_data["price_ceiling"] = price
            if dosage:
                hira_data["dosage_spec"] = dosage
        if code:
            hira_data["ingredient_code"] = code
        if status in ("not_found", "not_covered", "not_found_in_source"):
            hira_data["access_routes"] = "KODC 긴급도입 / 제약사 EAP / 비급여 처방"
        if is_guardrailed:
            hira_data["guardrail_note"] = "낮은 매칭 신뢰도 — 급여/가격 단정 금지"

        drug_dict["hira_data"] = hira_data
        enriched += 1

    if enriched:
        logger.info("[HIRA Bridge] %d개 약물 JSON 직접 매칭 성공", enriched)
    return enriched


def _build_hira_intel(hira: Any) -> dict:
    """HIRAReimbursementDB row → 브리핑용 dict 변환.

    3개 파생 필드 생성:
    - reimbursement_fact: 급여 상태 한 줄 요약
    - copay_exemption: 산정특례 대상 여부 (해당 시)
    - access_routes: 미허가 시 접근 경로 (해당 시)
    """
    status = getattr(hira, "status", None) or "unknown"
    price = getattr(hira, "price_ceiling", None)
    criteria = getattr(hira, "criteria", None) or ""
    ingredient_code = getattr(hira, "ingredient_code", None) or ""

    # 1) reimbursement_fact
    if status == "reimbursed":
        price_str = f", 상한가 {price:,.0f}원" if price else ""
        fact = f"심평원 급여 등재{price_str}"
    elif status == "not_covered":
        fact = "심평원 비급여 (전액 환자부담)"
    elif status == "deleted":
        fact = "심평원 급여 삭제 (과거 등재 이력)"
    elif status == "not_found":
        fact = "심평원 급여목록 미등재"
    else:
        fact = f"심평원 상태: {status}"

    # 2) copay_exemption — criteria 텍스트에서 산정특례 키워드 탐지
    copay = None
    if status == "reimbursed" and criteria:
        criteria_lower = criteria.lower()
        if "산정특례" in criteria_lower or "본인부담" in criteria_lower:
            if "암" in criteria_lower or "항암" in criteria_lower:
                copay = "암환자 산정특례(5%) 대상 가능"
            elif "희귀" in criteria_lower:
                copay = "희귀질환 산정특례(10%) 대상 가능"
            else:
                copay = "산정특례 대상 가능 (세부 확인 필요)"

    # 3) access_routes — 미등재 시 접근 경로
    access = None
    if status in ("not_found", "not_covered"):
        access = "KODC 긴급도입 / 제약사 EAP / 비급여 처방"

    result = {"reimbursement_fact": fact}
    if copay:
        result["copay_exemption"] = copay
    if access:
        result["access_routes"] = access
    if price and status == "reimbursed":
        result["price_ceiling"] = price
    if ingredient_code:
        result["ingredient_code"] = ingredient_code

    return result

# ────────────────────────────────────────────────────────
# 시스템 프롬프트 V1.2 (롤백용 보존)
# ────────────────────────────────────────────────────────

SYSTEM_PROMPT_V1_2 = """당신은 제약·바이오 산업의 규제 인텔리전스 전문 분석가이며,
국내 종합병원 약제팀·경영진을 위한 Executive Briefing을 작성합니다.

오늘 날짜: {today}

## 원칙
1. **BLUF**: 첫 문장에서 "그래서 뭐?"에 대한 답을 제시하라.
2. **Fact/Insight 분리**: 아래 [FACT DATA]는 검증된 사실이다. LLM이 할 일은 사실을 기반으로 인사이트와 시사점을 도출하는 것이다.
3. **기사체**: 병원장이 출근길 1분 만에 읽는 톤. 짧은 문장(40자 이내), 능동태, 전문용어 최소화.
4. **숫자는 구체적으로**: "많은" 대신 "17건", "최근" 대신 "2026-03-17 기준".
5. **행동 지향**: 각 섹션 끝에 "So What" — 약제팀이 내일 할 일을 명시.
6. **허위 생성 금지**: [FACT DATA]에 없는 승인일, 점수, 임상 결과를 절대 만들지 마라.

## 시간 추론 규칙 (필수)
- 승인일/허가일 < 오늘({today}) → "승인 완료", "허가됨" (과거형)
- 승인일/허가일 > 오늘({today}) → "승인 예정", "심사 중" (미래형)
- 승인일이 없으면 → "승인일 미정", "일정 미공개"
- 절대로 [FACT DATA]에 없는 날짜를 추정하거나 생성하지 마라.

## 필수 필드 규칙
- 출력 JSON 스키마에 명시된 모든 필드를 반드시 포함하라.
- 특히 `key_takeaway`는 절대 누락 금지.
- 필드 값을 채울 수 없으면 "데이터 부족"으로 표기하라.

## 톤 예시

### GOOD (이렇게 써라)
"headline": "FDA, KRAS G12C 이중억제제 sotorasib 병용요법 2026-02-14 승인 완료"
"why_it_matters": "국내 비소세포폐암 2차 치료 시장(연 4,200명)에서 기존 docetaxel 대비 PFS 2.8개월 우위. 급여 등재 시 약제비 연 15억 원 증가 예상."

### BAD (이렇게 쓰지 마라)
"headline": "새로운 항암제가 승인될 예정입니다"
"why_it_matters": "새로운 Kinase 억제제로 환자에게 도움이 될 것입니다."

## 출력
- 반드시 순수 JSON만 출력 (코드블록/마크다운 금지).
- 한글로 작성."""

# ────────────────────────────────────────────────────────
# 시스템 프롬프트 V2.0 — shared 기반 + 스트림 전용 확장
# ────────────────────────────────────────────────────────

_STREAM_EXTRA = [
    """## 스트림 브리핑 전용 규칙

### 필수 필드 규칙
- 출력 JSON 스키마에 명시된 모든 필드를 반드시 포함하라.
- 특히 `key_takeaway`는 절대 누락 금지.
- 필드 값을 채울 수 없으면 "데이터 부족"으로 표기하라.

### 스트림 요약 톤
- 개별 약물 심층 분석이 아닌 **스트림 전체의 트렌드와 시사점**에 초점.
- 약물별 why_it_matters는 4관점 중 **최소 2개 관점**을 포함하라:
  (a) 경쟁구도 — 기존 약물 대비 포지셔닝
  (b) 급여/가격 — 약가·급여 등재 영향
  (c) 환자규모 — 국내 대상 환자 수
  (d) 처방변화 — 기존 처방 패턴에 미치는 영향""",
]


def _build_stream_system_prompt(today: str) -> str:
    """스트림 브리핑용 시스템 프롬프트 조립 (shared 기반 + 스트림 전용)"""
    return build_system_prompt(
        today,
        include_reimbursement=True,
        include_regulatory=True,
        include_lifecycle=True,
        extra_sections=_STREAM_EXTRA,
    )


# 활성 시스템 프롬프트 — _call_llm에서 사용
# (V1.2.0과 달리 {today} 템플릿이 아닌, _build_stream_system_prompt() 함수로 조립)
SYSTEM_PROMPT = "{today}"  # 하위 호환용 placeholder — 실제는 _call_llm에서 build

# ────────────────────────────────────────────────────────
# 치료영역 브리핑 프롬프트
# ────────────────────────────────────────────────────────

THERAPEUTIC_BRIEFING_PROMPT = """[FACT DATA]
치료영역: {area_ko} ({area})
오늘 날짜: {date}
총 수집 약물: {drug_count}건

## 주요 약물 상세 (상위 {top_n}건)
{drug_details}

## 수집 에러
{errors}

[ANALYSIS FRAME — 내부 추론용, 출력에는 JSON만]
아래 순서로 사고하되, 출력은 JSON만 작성하라.
1. **약물 분류**: 각 약물의 기전·적응증·경쟁약을 파악
2. **시제 판단**: 승인일 vs 오늘({date}) 비교 → 과거/미래 결정
3. **트렌드 도출**: 이번 수집에서 반복되는 패턴 (적응증 집중, NME 증가, 미허가 장기화 등)
4. **액션 도출**: 약제팀이 이번 주 실행할 구체적 행동

[TASK]
위 데이터를 기반으로 {area_ko} 치료영역 주간 Executive Briefing을 작성하라.
시간 추론 규칙과 금지표현 대안표를 반드시 준수하라.

[FEW-SHOT 예시]

입력 (요약):
{{"area": "oncology", "drug_count": 3, "top_drugs": [
  {{"inn": "RILZABRUTINIB", "fda_status": "AP", "fda_date": "2025-03-28", "mfds_status": "미허가", "reimbursement_fact": "심평원 급여목록 미등재", "access_routes": "KODC 긴급도입 / 제약사 EAP / 비급여 처방"}},
  {{"inn": "SOTORASIB", "fda_status": "AP", "fda_date": "2026-02-14", "mfds_status": "허가", "reimbursement_fact": "심평원 급여 등재, 상한가 285,000원", "copay_exemption": "암환자 산정특례(5%) 대상 가능"}},
  {{"inn": "EXAMPLE_PENDING", "fda_status": "", "fda_date": "", "mfds_status": ""}}
]}}

출력:
{{
  "headline": "KRAS 표적 + BTK 억제제 잇단 승인 — 급여 격차 심화",
  "key_takeaway": "oncology 영역에서 sotorasib은 급여 등재(상한가 285,000원)로 처방 가능하나, rilzabrutinib은 심평원 미등재로 긴급도입 절차가 필요하다.",
  "top_drugs": [
    {{
      "inn": "RILZABRUTINIB",
      "status": "2025-03-28 FDA 승인 완료, 국내 식약처 미허가",
      "why_it_matters": "(a)경쟁구도: BTK 억제제 시장에서 ibrutinib·acalabrutinib 대비 안전성 차별화. (b)급여/가격: 심평원 미등재 — KODC 긴급도입 또는 비급여 처방 필요. (c)환자규모: 국내 CLL 신규 환자 연 약 500명."
    }},
    {{
      "inn": "SOTORASIB",
      "status": "2026-02-14 FDA 승인 완료, 국내 식약처 허가",
      "why_it_matters": "(a)경쟁구도: KRAS G12C 억제제 최초 병용요법 승인, adagrasib 대비 선점 효과. (b)급여/가격: 심평원 급여 등재(상한가 285,000원), 암환자 산정특례 5% 적용. (c)환자규모: 국내 NSCLC 환자 중 KRAS G12C 변이 약 13%(연 4,200명)."
    }},
    {{
      "inn": "EXAMPLE_PENDING",
      "status": "FDA 승인일 미공개, 국내 허가 정보 없음",
      "why_it_matters": "(a)경쟁구도: 데이터 부족으로 포지셔닝 분석 불가. 후속 데이터 확보 시 재평가 필요."
    }}
  ],
  "trend_analysis": "이번 수집 oncology 3건 중 FDA 승인 2건은 표적치료제(BTK, KRAS). sotorasib은 급여 등재까지 완료된 반면 rilzabrutinib은 미등재로 약가 접근성 격차 존재. EXAMPLE_PENDING은 허가·급여 정보 모두 부재하여 모니터링 대상.",
  "action_items": [
    "rilzabrutinib KODC 긴급도입 사전 안내 체계 마련 — 미등재 약물 도입 절차 확인",
    "sotorasib 산정특례 적용 기준 확인 — 급여 등재 완료 약물 처방 최적화",
    "EXAMPLE_PENDING 허가 동향 추적 — 현재 데이터 부족, 추가 정보 확보 시 재평가"
  ]
}}

출력 JSON:
{{
  "headline": "40자 이내 BLUF 헤드라인 — 이번 주 가장 중요한 한 가지",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "top_drugs": [
    {{
      "inn": "약물명",
      "status": "FDA/EMA 승인 현황 1줄 (과거/미래 시제 정확히)",
      "why_it_matters": "4관점 중 최소 2개: (a)경쟁구도, (b)급여/가격, (c)환자규모, (d)처방변화. 구체적 수치 활용."
    }}
  ],
  "trend_analysis": "이번 수집에서 드러난 치료영역 트렌드 (3-5줄, 숫자 기반)",
  "action_items": [
    "약제팀 후속 조치 (확인 필요 / 검토 권고 / 수동 점검 필요 톤)"
  ]
}}

[출력 규칙 — 반드시 준수]

1. MFDS 상태 표기:
   - 확정 근거가 있으면: "국내 식약처 미허가"
   - 수집 데이터에 없거나 미확인이면: "국내 식약처 허가 여부는 추가 확인 필요"
   - "미허가"와 "미확인"을 동시에 쓰지 마라.
   - hira_guardrail 또는 mfds_guardrail 필드가 있으면 해당 문구를 우선 사용하라.

2. Action item 톤:
   - 데이터 불완전 시 명령형 금지. "~하라", "~확정하라" 대신:
     "확인 필요", "검토 권고", "수동 점검 필요", "후속 검증 권장"
   - "이번 주 내 확정" 같은 확정 기한은 데이터가 충분할 때만 사용.

3. orphan 표현:
   - "희귀질환 N건" 대신 "orphan 지정 약물 N건" 사용.
   - "희귀질환 계열", "희귀 적응증 중심" 정도까지 허용."""

# ────────────────────────────────────────────────────────
# 혁신 시그널 브리핑 프롬프트
# ────────────────────────────────────────────────────────

INNOVATION_BRIEFING_PROMPT = """[FACT DATA]
오늘 날짜: {date}
총 약물: {drug_count}건
NME(신규물질) 수: {nme_count}건
PRIME 지정: {prime_count}건
희귀의약품 지정: {orphan_count}건
조건부 승인: {conditional_count}건

## NME 및 혁신 지정 약물 (상위 {top_n}건)
{drug_details}

## 시그널 상세 (상위 20건)
{signals}

[ANALYSIS FRAME — 내부 추론용, 출력에는 JSON만]
1. **지정 분류**: NME/PRIME/orphan/conditional 각 약물의 지정 의미 파악
2. **혁신성 평가**: 기존 표준치료 대비 MOA 차별점, 임상 근거 수준
3. **도입 타임라인**: PDUFA 일정, 허가 경로(GIFT 가능성) 추정
4. **전략 도출**: 대형 병원 선점 경쟁, 약제팀 사전 준비 포인트

[TASK]
위 데이터를 기반으로 혁신 시그널 Executive Briefing을 작성하라.
NME, PRIME, 희귀의약품 등 규제 지정이 병원 약물 도입에 미치는 영향에 초점.
시간 추론 규칙과 금지표현 대안표를 반드시 준수하라.

[FEW-SHOT 예시]

입력 (요약):
{{"drug_count": 2, "nme_count": 1, "orphan_count": 1, "drugs": [
  {{"inn": "VELONATINIB", "designations": ["NME", "orphan"], "fda_date": "", "ema_status": "under_review", "pdufa_date": "2026-09-15", "reimbursement_fact": "심평원 급여목록 미등재", "access_routes": "KODC 긴급도입 / 제약사 EAP / 비급여 처방"}},
  {{"inn": "RILZABRUTINIB", "designations": ["NME"], "fda_status": "AP", "fda_date": "2025-03-28", "reimbursement_fact": "심평원 급여 등재, 상한가 1,850,000원", "copay_exemption": "희귀질환 산정특례(10%) 대상 가능"}}
]}}

출력:
{{
  "headline": "NME 2건 + 희귀의약품 1건 — 혁신 파이프라인 강세",
  "key_takeaway": "VELONATINIB(PDUFA 2026-09-15)이 희귀의약품+NME 이중 지정으로 GIFT 대상 가능성이 높다. 약제팀은 허가 전 도입 경로를 사전 검토해야 한다.",
  "nme_spotlight": [
    {{
      "inn": "VELONATINIB",
      "designation": "NME + orphan",
      "implication": "(a)혁신성: 기존 치료제 대비 새로운 기전(NME)으로 미충족 수요 해소 기대. (b)도입 시점: PDUFA 2026-09-15 심사 예정, 희귀의약품 지정 시 GIFT 경로로 국내 심사 기간 단축 가능. (c)급여/가격: 심평원 미등재 — 허가 전이므로 KODC 긴급도입 또는 EAP를 통한 사전 접근 필요."
    }},
    {{
      "inn": "RILZABRUTINIB",
      "designation": "NME",
      "implication": "(a)혁신성: BTK 억제제 중 가역적 결합 기전으로 안전성 차별화. (b)급여/가격: 심평원 급여 등재(상한가 1,850,000원), 희귀질환 산정특례 10% 적용 가능 — 환자 부담 대폭 경감. (c)포지셔닝: 2025-03-28 FDA 승인 완료, ibrutinib 대비 후발이나 부작용 프로파일에서 우위."
    }}
  ],
  "pdufa_watch": ["VELONATINIB — 2026-09-15 PDUFA 심사 예정"],
  "strategic_implications": "NME 2건 중 1건은 FDA 승인 + 심평원 급여 등재 완료(RILZABRUTINIB, 산정특례 적용), 1건은 PDUFA 대기 + 심평원 미등재(VELONATINIB). 급여 등재 약물은 즉시 처방 최적화, 미등재 약물은 긴급도입 경로 사전 준비가 필요하다.",
  "action_items": ["VELONATINIB PDUFA 결과(2026-09-15) 추적 — 승인 시 GIFT 지정 신청 + KODC 긴급도입 준비", "RILZABRUTINIB 산정특례 적용 기준 확인 — 급여 등재 완료, 처방 최적화"]
}}

출력 JSON:
{{
  "headline": "40자 이내 BLUF — 이번 주 혁신 시그널의 핵심",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "nme_spotlight": [
    {{
      "inn": "약물명",
      "designation": "NME/PRIME/orphan 등",
      "implication": "3관점 중 최소 2개: (a)기존 치료 대비 혁신성, (b)도입 시점, (c)경쟁약물 대비 포지셔닝."
    }}
  ],
  "pdufa_watch": ["PDUFA 일정 주시 대상 (있으면)"],
  "strategic_implications": "전략적 시사점 — 혁신 약물이 기존 치료 패러다임에 미칠 영향 (3-5줄)",
  "action_items": ["약제팀 후속 조치"]
}}"""

# ────────────────────────────────────────────────────────
# 외부시그널 브리핑 프롬프트
# ────────────────────────────────────────────────────────

EXTERNAL_BRIEFING_PROMPT = """[FACT DATA]
오늘 날짜: {date}
총 약물: {drug_count}건

임상시험 시그널:
  - 임상실패 (FAIL): {fail_count}건
  - 결과대기 (PENDING): {pending_count}건
  - AI판독대기 (NEEDS_AI): {needs_ai_count}건
medRxiv 논문: {medrxiv_count}건

## 주요 임상실패 약물
{fail_details}

## medRxiv 핵심 논문
{medrxiv_details}

## 시그널 상세 (상위 20건)
{signals}

[ANALYSIS FRAME — 내부 추론용, 출력에는 JSON만]
1. **임상실패 영향**: FAIL 약물이 현재 병원 재고/처방에 미치는 즉각 영향 판단
2. **대체약물 식별**: 실패 약물의 대안이 될 기존 치료제 파악
3. **medRxiv 해석**: 논문의 임상 적용 시점 추정 (단기/중기/장기)
4. **리스크 도출**: 즉각 대응 필요 리스크 vs 향후 주시 대상 분류

[TASK]
위 데이터를 기반으로 외부시그널 Future Trend Report를 작성하라.
임상실패 약물이 현재 병원 처방에 미치는 즉각적 영향과, medRxiv 논문이 시사하는 미래 변화에 초점.
시간 추론 규칙과 금지표현 대안표를 반드시 준수하라.

출력 JSON:
{{
  "headline": "40자 이내 BLUF — 이번 주 외부시그널 핵심",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "trial_failures": [
    {{
      "inn": "약물명",
      "verdict": "FAIL 사유 1줄",
      "hospital_impact": "3관점 구체화: (a)재고영향 — 현재 보유 재고 처리 방안, (b)대체약물 — 즉시 전환 가능한 대안, (c)보험청구 — 급여 기준 변경 가능성. 해당 관점만 기술."
    }}
  ],
  "medrxiv_insights": [
    {{
      "topic": "논문 주제",
      "finding": "핵심 발견",
      "timeline": "임상 적용까지 예상 시간"
    }}
  ],
  "watch_list": ["향후 주시 대상 약물 INN"],
  "action_items": ["약제팀 후속 조치"]
}}"""

# ────────────────────────────────────────────────────────
# 통합 브리핑 프롬프트
# ────────────────────────────────────────────────────────

UNIFIED_BRIEFING_PROMPT = """[FACT DATA]
오늘 날짜: {date}

## 치료영역 스트림 브리핑 (drug_count: {therapeutic_drug_count}, signal_count: {therapeutic_signal_count})
{therapeutic_summary}

## 혁신지표 스트림 브리핑 (drug_count: {innovation_drug_count}, signal_count: {innovation_signal_count})
{innovation_summary}

## 외부시그널 스트림 브리핑 (drug_count: {external_drug_count}, signal_count: {external_signal_count})
{external_summary}

## 스트림별 Top 약물 (교차 등장)
{cross_stream_drugs}

[ANALYSIS FRAME — 내부 추론용, 출력에는 JSON만]
1. **교차 신호 추출**: 2개 이상 스트림에 등장하는 약물 식별 → 강한 신호
2. **모순/보완 분석**: 스트림 간 모순되는 정보 또는 보완 관계 파악
3. **급여/접근성 분석**: reimbursement_fact, copay_exemption, access_routes 정보가 있으면 국내 시장 진입 단계를 평가하라
4. **Top 5 선정**: 교차 등장 빈도 + 규제 단계 + 급여 상태 + 환자 영향 기준으로 순위
5. **리스크/기회 분류**: 즉각 대응 필요 리스크 vs 선제 대응 기회 분리

[TASK]
3개 스트림을 종합한 오늘의 RegScan Executive Daily Briefing을 작성하라.
경영진이 30초 만에 핵심을 파악할 수 있는 BLUF 톤.
시간 추론 규칙과 금지표현 대안표를 반드시 준수하라.

**중요**: 위 스트림 브리핑을 단순 반복·요약하지 마라. 스트림 간 교차·종합 인사이트를 도출하라.
- 같은 약물이 여러 스트림에 등장하면 신호가 강하다는 의미.
- 스트림 간 모순/보완 관계를 분석하라.
- 개별 스트림에서 놓친 큰 그림을 제시하라.

출력 JSON:
{{
  "headline": "50자 이내 — 오늘의 RegScan 한 줄 요약",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "executive_summary": "5줄 이내, BLUF 톤. 오늘 가장 중요한 것 3가지.",
  "cross_analysis": "스트림 간 교차 신호 분석 (3-5줄)",
  "top_5_drugs": [
    {{
      "rank": 1,
      "inn": "약물명",
      "reason": "선정 이유 (어떤 스트림에서 어떤 신호)",
      "action": "약제팀 즉각 행동"
    }}
  ],
  "risk_alerts": ["즉각 대응 필요 리스크"],
  "opportunities": ["선제 대응 기회"],
  "tomorrow_watch": "내일 주시할 것 1줄"
}}"""


# ════════════════════════════════════════════════════════
# V2 프롬프트 — 팩트카드 기반 Article Writer
# ════════════════════════════════════════════════════════

V2_ARTICLE_SYSTEM_PROMPT = """당신은 "메드클레임 인사이트"의 수석 의약 전문기자입니다.
10년간 FDA/EMA/MFDS 규제 동향을 취재해 온 베테랑으로,
"이번 주 무슨 일이 있었고, 왜 중요한가"를 독자(병원 약제팀, 의료전문직)에게 전달합니다.

## 기사 작성 원칙

1. **"무슨 일이 있었는가"를 먼저 써라.**
   - 헤드라인은 구체적 이벤트다. "FDA, quizartinib AML 1차 치료 승인" 수준.
   - "확인 필요", "공백", "미확인" 같은 표현은 헤드라인이나 리드에 절대 쓰지 마라.

2. **있는 것을 쓰고, 없는 것은 쓰지 마라.**
   - 데이터가 있는 약물에 대해 기사를 써라.
   - EMA 정보가 없으면 EMA를 언급하지 마라. "정보 없음"을 보도하지 마라.
   - MFDS/HIRA 미확인이면 해당 부분을 생략하거나 국내 현황 파트에서 짧게만 언급하라.

3. **적응증과 경쟁구도를 활용하라.**
   - [INDICATIONS]의 disease, biomarker, line_of_therapy를 구체적으로 기술하라.
   - [COMPETITIONS]의 same_class, same_indication 약물을 경쟁 맥락으로 활용하라.
   - "표적치료제"가 아니라 "FLT3-ITD 변이 AML 1차 치료에서 midostaurin 이후 두 번째 옵션" 수준.

4. **뉴스 가치가 있는 약물만 기사화하라.**
   - 제네릭 승인, 라벨 소폭 변경은 한 줄 요약으로 처리하거나 생략.
   - 신약 승인, 적응증 확대, 주요 약물 변경이 리드다.
   - 11건 중 기사 가치가 없으면 상위 2-3건만 심도 있게 다뤄라.

5. **팩트 정확성은 지켜라.**
   - 날짜, 가격, 승인 상태는 [FACT CARDS] 기반. 없는 걸 만들지 마라.
   - 하지만 기사체로 자연스럽게 녹여라. 팩트 문구를 그대로 복붙하지 마라.

## 출력
- 순수 JSON만. 코드블록/마크다운 금지.
- 한글로 작성하되, **약물명(INN)은 영문 그대로** 유지. fosfomycin, quizartinib, faricimab — 한글 음차 금지.

오늘 날짜: {today}
"""

V2_THERAPEUTIC_PROMPT = """[이번 주 수집 약물 — {n}건]
{fact_cards}

[적응증 구조화]
{indications}

[경쟁구도 (HemOnc)]
{competitions}

[트렌드 분석]
{trends}

[국내 규제/급여 팩트]
{fact_phrases}

[TASK]
위 데이터로 이번 주 {area_ko} 규제 동향 기사를 작성하라.

규칙:
- 뉴스 가치가 높은 약물 2-3건을 선별하여 심도 있게 다뤄라.
- 각 약물에 대해: (1)무슨 일이 있었나, (2)왜 중요한가, (3)기존 치료 대비 어떤 의미인가.
- 적응증·바이오마커·치료라인·경쟁약을 구체적으로 활용하라.
- "확인 필요", "공백", "미확인"은 리드나 헤드라인에 절대 쓰지 마라.
- 데이터 없는 항목은 생략하라. "정보 없음"을 보도하지 마라.
- 제네릭 승인은 별도 간략 요약으로 분리하라.

출력 JSON:
{{
  "headline": "종합 헤드라인 — 반드시 약물명(영문 INN) 포함. 예: 'fosfomycin FDA 승인 예정, quizartinib·faricimab 국내 급여 유지 확인'",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장",
  "top_stories": [
    {{
      "inn": "약물명",
      "event": "무슨 일이 있었나 (FDA 승인/적응증 확대/etc)",
      "indication": "질환명 + 바이오마커 + 치료라인",
      "competition": "경쟁약 대비 포지셔닝",
      "domestic_impact": "국내 허가/급여 현황 (있으면)"
    }}
  ],
  "brief_updates": ["제네릭/라벨 변경 등 간략 1줄 요약"],
  "outlook": "향후 주시할 점 1-2문장"
}}"""

V2_INNOVATION_PROMPT = """[FACT CARDS — {n}건, 혁신 시그널]
{fact_cards}

[FACT PHRASES — 반드시 verbatim 사용]
{fact_phrases}

[TREND ANALYSIS]
{trends}

[GUARDRAILED DRUGS — 단정 금지]
{guardrailed}

[INDICATIONS]
{indications}

[COMPETITIONS]
{competitions}

[SIGNAL STATS]
NME: {nme_count}건, PRIME: {prime_count}건, orphan: {orphan_count}건, conditional: {conditional_count}건

[TASK]
위 팩트카드와 트렌드를 기반으로 혁신 시그널 Executive Briefing을 작성하라.

출력 JSON:
{{
  "headline": "40자 이내 BLUF",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수)",
  "nme_spotlight": [
    {{
      "inn": "약물명",
      "designation": "NME/PRIME/orphan 등",
      "implication": "팩트 문구 기반 — (a)혁신성, (b)도입 시점, (c)포지셔닝"
    }}
  ],
  "pdufa_watch": ["PDUFA 일정 주시 대상"],
  "strategic_implications": "전략적 시사점 3-5줄",
  "action_items": ["약제팀 후속 조치"]
}}"""

V2_EXTERNAL_PROMPT = """[FACT CARDS — {n}건, 외부시그널]
{fact_cards}

[FACT PHRASES — 반드시 verbatim 사용]
{fact_phrases}

[TREND ANALYSIS]
{trends}

[GUARDRAILED DRUGS — 단정 금지]
{guardrailed}

[INDICATIONS]
{indications}

[COMPETITIONS]
{competitions}

[SIGNAL STATS]
임상실패: {fail_count}건, 결과대기: {pending_count}건, medRxiv: {medrxiv_count}건

[TASK]
위 팩트카드와 트렌드를 기반으로 외부시그널 Future Trend Report를 작성하라.

출력 JSON:
{{
  "headline": "40자 이내 BLUF",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수)",
  "trial_failures": [
    {{
      "inn": "약물명",
      "verdict": "FAIL 사유 1줄",
      "hospital_impact": "(a)재고영향, (b)대체약물, (c)보험청구"
    }}
  ],
  "medrxiv_insights": [
    {{
      "topic": "논문 주제",
      "finding": "핵심 발견",
      "timeline": "임상 적용 예상 시간"
    }}
  ],
  "watch_list": ["향후 주시 대상 INN"],
  "action_items": ["약제팀 후속 조치"]
}}"""

V2_UNIFIED_PROMPT = """[이번 주 주요 약물 — {n}건]
{fact_cards}

[적응증]
{indications}

[경쟁구도]
{competitions}

[스트림별 주요 소식]
{stream_trends}

[교차 신호]
{cross_signals}

[국내 규제/급여]
{fact_phrases}

[TASK]
위 데이터로 이번 주 RegScan Weekly Briefing을 작성하라.

규칙:
- "이번 주 가장 중요한 규제 이벤트"가 헤드라인이다. 구체적 약물명+이벤트.
- 데이터가 있는 약물에 대해서만 써라. "정보 없음"을 보도하지 마라.
- 각 Top 약물: 무슨 일이 있었고, 어떤 질환/바이오마커 대상이며, 경쟁약 대비 어떤 의미인지.
- 국내 현황은 있는 약물만 간결하게. 없으면 생략.

출력 JSON:
{{
  "headline": "종합 헤드라인 — 약물명(영문 INN) 포함 필수",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장",
  "executive_summary": "이번 주 일어난 일 3-5줄. 구체적 약물명과 이벤트.",
  "top_stories": [
    {{
      "rank": 1,
      "inn": "약물명",
      "event": "무슨 일이 있었나",
      "significance": "왜 중요한가 — 적응증, 경쟁약, 국내 영향",
      "domestic": "국내 현황 (있으면)"
    }}
  ],
  "brief_updates": ["기타 변경 1줄 요약"],
  "outlook": "다음 주 주시할 점"
}}"""


# ────────────────────────────────────────────────────────
# Generator
# ────────────────────────────────────────────────────────

class StreamBriefingGenerator:
    """스트림별 + 통합 브리핑 생성기 (V3: 시간추론 + few-shot + 풍부한 인텔리전스)"""

    # ── 약물 인텔리전스 추출 헬퍼 ──

    @staticmethod
    def _extract_drug_intel(drug: dict, max_fields: int = 20) -> dict:
        """drugs_found 항목에서 브리핑에 필요한 핵심 정보 추출

        V4: HIRA 급여 데이터 3필드 추가 (reimbursement_fact, copay_exemption, access_routes)
        max_fields 14 → 20 (빈 값은 제거되므로 실제 출력은 12~18개)
        """
        intel: dict[str, Any] = {"inn": drug.get("inn", "UNKNOWN")}

        # FDA 데이터
        fda = drug.get("fda_data") or {}
        if fda:
            intel["fda_status"] = fda.get("submission_status", "")
            intel["fda_date"] = fda.get("submission_status_date", "")
            intel["fda_type"] = fda.get("submission_class_code_description", "") or fda.get("submission_class_code", "")
            intel["brand_name"] = fda.get("brand_name", "")
            pharm = fda.get("pharm_class_epc", [])
            if pharm:
                intel["moa"] = pharm[0] if isinstance(pharm, list) else str(pharm)

        # EMA 데이터
        ema = drug.get("ema_data") or {}
        if ema:
            intel["ema_date"] = ema.get("marketing_authorisation_date", "")
            intel["ema_status"] = ema.get("medicine_status", "")
            flags = []
            if ema.get("is_orphan"):
                flags.append("orphan")
            if ema.get("is_prime"):
                flags.append("PRIME")
            if ema.get("is_conditional"):
                flags.append("conditional")
            if ema.get("is_accelerated"):
                flags.append("accelerated")
            if flags:
                intel["ema_designations"] = flags
            indication = ema.get("therapeutic_indication", "")
            if indication:
                intel["indication"] = indication[:200]

        # ATC / 지정
        if drug.get("atc_code"):
            intel["atc_code"] = drug["atc_code"]
        if drug.get("designations"):
            intel["designations"] = drug["designations"]

        # 임상시험 결과 (V3 추가)
        clinical = drug.get("clinical_results") or drug.get("clinical_data") or {}
        if clinical:
            if clinical.get("trial_phase"):
                intel["trial_phase"] = clinical["trial_phase"]
            if clinical.get("trial_status"):
                intel["trial_status"] = clinical["trial_status"]

        # MFDS 한국 허가 데이터 (V3 추가)
        mfds = drug.get("mfds_data") or {}
        if mfds:
            if mfds.get("approval_status"):
                intel["mfds_status"] = mfds["approval_status"]
            if mfds.get("approval_date"):
                intel["mfds_date"] = mfds["approval_date"]

        # HIRA 급여 데이터 (V5: confidence + source_date + guardrail)
        hira = drug.get("hira_data") or {}
        if hira:
            if hira.get("reimbursement_fact"):
                intel["reimbursement_fact"] = hira["reimbursement_fact"]
            if hira.get("copay_exemption"):
                intel["copay_exemption"] = hira["copay_exemption"]
            if hira.get("access_routes"):
                intel["access_routes"] = hira["access_routes"]
            if hira.get("match_confidence"):
                intel["hira_confidence"] = hira["match_confidence"]
            if hira.get("source_date"):
                intel["hira_source_date"] = hira["source_date"]
            if hira.get("is_guardrailed"):
                intel["hira_guardrail"] = "낮은 신뢰도 — 급여/가격 단정 금지"
            if hira.get("guardrail_note"):
                intel["hira_guardrail"] = hira["guardrail_note"]

        # MFDS 상태 가드레일 (V5) — "미허가"/"미확인" 충돌 방지
        mfds_raw = drug.get("mfds_data") or {}
        mfds_status = mfds_raw.get("approval_status", "")
        if mfds_status == "미허가":
            # 확정 근거(approval_date 존재 등)가 없으면 "미확인"으로 완화
            has_evidence = bool(mfds_raw.get("approval_date"))
            if not has_evidence:
                intel["mfds_status"] = "허가 여부 추가 확인 필요"
                intel["mfds_guardrail"] = "수집 데이터에 MFDS 정보 부재 — '미허가' 단정 불가"

        # 치료영역 (V3 추가)
        areas = drug.get("therapeutic_areas") or drug.get("therapeutic_area")
        if areas:
            intel["therapeutic_areas"] = areas if isinstance(areas, list) else [areas]

        # 필드 수 제한
        trimmed = {}
        for i, (k, v) in enumerate(intel.items()):
            if i >= max_fields:
                break
            if v:  # 빈 값 제거
                trimmed[k] = v
        return trimmed

    @staticmethod
    def _top_drugs_detail(result: StreamResult, n: int = 10) -> str:
        """상위 N개 약물의 인텔리전스를 텍스트로 변환"""
        if not result.drugs_found:
            return f"(drugs_found 비어있음 — INN만 확인: {', '.join(result.inn_list[:10])})"
        lines = []
        for i, drug in enumerate(result.drugs_found[:n]):
            intel = StreamBriefingGenerator._extract_drug_intel(drug)
            lines.append(f"{i+1}. {json.dumps(intel, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    @staticmethod
    def _count_designations(drugs: list[dict]) -> dict[str, int]:
        """NME/orphan/PRIME/conditional 지정 통계"""
        counts = {"nme": 0, "orphan": 0, "prime": 0, "conditional": 0}
        for d in drugs:
            desig = d.get("designations", [])
            if "NME" in desig:
                counts["nme"] += 1
            if "orphan" in desig:
                counts["orphan"] += 1
            if "PRIME" in desig:
                counts["prime"] += 1
            if "conditional" in desig:
                counts["conditional"] += 1
        return counts

    # ── 인텔리전스 시그널 브리핑 ──

    async def generate_intelligence_briefing(
        self,
        source_type: str,
        signals: list[dict],
    ) -> dict[str, Any] | None:
        """소스별 인텔리전스 브리핑 — 시그널 있을 때만 생성.

        Args:
            source_type: "PMDA_APPROVAL", "NICE_TA" 등
            signals: extract_signals()에서 추출한 시그널 리스트
        """
        from regscan.stream.intelligence_signals import (
            SOURCE_META, format_for_prompt,
        )

        meta = SOURCE_META.get(source_type, {})
        label = meta.get("label", source_type)
        description = meta.get("description", "")
        today = datetime.now().strftime("%Y-%m-%d")

        signal_text = format_for_prompt(source_type, signals)

        system_prompt = build_system_prompt(
            stream_name="intelligence",
            stream_specific_rules=f"""
당신은 '{label}' 전문 분석가입니다.
{description}

## 분석 원칙
- 수집된 시그널 데이터를 기반으로 핵심 동향을 분석합니다
- 국내 의약품 시장에 미치는 영향을 중심으로 서술합니다
- 데이터에 없는 내용은 추측하지 않습니다
- 날짜, 약물명, 기관명 등 팩트는 원문 그대로 인용합니다
""",
        )

        user_prompt = f"""오늘 날짜: {today}

다음은 최근 수집된 {label} 데이터입니다.

{signal_text}

위 데이터를 분석하여 다음 JSON 형식으로 브리핑을 작성해주세요:

```json
{{
  "headline": "한 줄 제목 (50자 이내)",
  "key_takeaway": "핵심 메시지 (100자 이내)",
  "analysis": "상세 분석 (3~5개 단락, 각 2~3문장)",
  "impact_on_korea": "국내 시장 영향 분석 (2~3문장)",
  "action_items": ["후속 모니터링 포인트 1", "포인트 2"]
}}
```"""

        try:
            response_text = await self._call_llm(system_prompt, user_prompt)
            briefing = self._parse_json_response(response_text)

            briefing.update({
                "source_type": source_type,
                "label": label,
                "signal_count": len(signals),
                "date": today,
                "generated_at": datetime.now().isoformat(),
            })

            logger.info(
                "[Intelligence] %s 브리핑 생성: %s (%d건)",
                source_type, briefing.get("headline", "")[:40], len(signals),
            )
            return briefing

        except Exception as e:
            logger.warning(
                "[Intelligence] %s 브리핑 생성 실패: %s", source_type, e,
            )
            # 폴백: LLM 없이 요약만
            return {
                "source_type": source_type,
                "label": label,
                "headline": f"{label} ({len(signals)}건)",
                "key_takeaway": f"최근 {len(signals)}건의 시그널이 수집되었습니다.",
                "signal_count": len(signals),
                "signals_summary": [
                    s.get("title", "")[:60] for s in signals[:10]
                ],
                "date": today,
                "generated_at": datetime.now().isoformat(),
                "is_fallback": True,
            }

    # ── 스트림별 브리핑 생성 ──

    async def generate_therapeutic_briefing(
        self,
        area: str,
        area_ko: str,
        result: StreamResult,
    ) -> dict[str, Any]:
        """치료영역 Executive Briefing"""
        if settings.ENABLE_FACT_CARD_PIPELINE:
            return await self._v2_therapeutic(area, area_ko, result)

        # ── 레거시 경로 ──
        await enrich_drugs_with_hira(result.drugs_found)

        top_n = min(10, result.drug_count) if result.drug_count else 0
        prompt = THERAPEUTIC_BRIEFING_PROMPT.format(
            area=area,
            area_ko=area_ko,
            date=datetime.now().strftime("%Y-%m-%d"),
            drug_count=result.drug_count,
            top_n=top_n,
            drug_details=self._top_drugs_detail(result, n=10),
            errors=", ".join(result.errors) if result.errors else "없음",
        )

        try:
            content = await self._call_llm(prompt)
            return self._parse_json_response(content, fallback_headline=f"{area_ko} 치료영역 브리핑")
        except Exception as e:
            logger.warning("치료영역 브리핑 생성 실패 (%s): %s", area, e)
            return self._fallback_therapeutic(area, area_ko, result)

    async def generate_innovation_briefing(
        self,
        result: StreamResult,
    ) -> dict[str, Any]:
        """혁신 시그널 Executive Briefing"""
        if settings.ENABLE_FACT_CARD_PIPELINE:
            return await self._v2_innovation(result)

        # ── 레거시 경로 ──
        await enrich_drugs_with_hira(result.drugs_found)

        # 지정 통계 계산
        nme_count = orphan_count = prime_count = conditional_count = 0
        for d in result.drugs_found:
            desig = d.get("designations", [])
            if "NME" in desig:
                nme_count += 1
            if "orphan" in desig:
                orphan_count += 1
            if "PRIME" in desig:
                prime_count += 1
            if "conditional" in desig:
                conditional_count += 1

        top_n = min(10, result.drug_count) if result.drug_count else 0
        prompt = INNOVATION_BRIEFING_PROMPT.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            drug_count=result.drug_count,
            nme_count=nme_count,
            prime_count=prime_count,
            orphan_count=orphan_count,
            conditional_count=conditional_count,
            top_n=top_n,
            drug_details=self._top_drugs_detail(result, n=10),
            signals=json.dumps(result.signals[:20], ensure_ascii=False, default=str),
        )

        try:
            content = await self._call_llm(prompt)
            return self._parse_json_response(content, fallback_headline="혁신 시그널 브리핑")
        except Exception as e:
            logger.warning("혁신 브리핑 생성 실패: %s", e)
            return {"headline": "혁신 시그널 브리핑", "signals": result.signals[:10]}

    async def generate_external_briefing(
        self,
        result: StreamResult,
    ) -> dict[str, Any]:
        """외부시그널 Future Trend Report"""
        if settings.ENABLE_FACT_CARD_PIPELINE:
            return await self._v2_external(result)

        # ── 레거시 경로 ──
        await enrich_drugs_with_hira(result.drugs_found)

        fail_count = sum(1 for s in result.signals if s.get("verdict") == "FAIL")
        pending_count = sum(1 for s in result.signals if s.get("verdict") == "PENDING")
        needs_ai_count = sum(1 for s in result.signals if s.get("verdict") == "NEEDS_AI")
        medrxiv_count = sum(1 for s in result.signals if s.get("type") == "medrxiv_paper")

        # 실패 약물 상세
        fail_details_list = [
            s for s in result.signals if s.get("verdict") == "FAIL"
        ][:5]
        fail_details = json.dumps(fail_details_list, ensure_ascii=False, default=str) if fail_details_list else "없음"

        # medRxiv 상세
        medrxiv_list = [
            s for s in result.signals if s.get("type") == "medrxiv_paper"
        ][:5]
        medrxiv_details = json.dumps(medrxiv_list, ensure_ascii=False, default=str) if medrxiv_list else "없음"

        prompt = EXTERNAL_BRIEFING_PROMPT.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            drug_count=result.drug_count,
            fail_count=fail_count,
            pending_count=pending_count,
            needs_ai_count=needs_ai_count,
            medrxiv_count=medrxiv_count,
            fail_details=fail_details,
            medrxiv_details=medrxiv_details,
            signals=json.dumps(result.signals[:20], ensure_ascii=False, default=str),
        )

        try:
            content = await self._call_llm(prompt)
            return self._parse_json_response(content, fallback_headline="미래 트렌드 리포트")
        except Exception as e:
            logger.warning("외부시그널 브리핑 생성 실패: %s", e)
            return {"headline": "미래 트렌드 리포트", "signals": result.signals[:10]}

    async def generate_unified_briefing(
        self,
        all_results: dict[str, list[StreamResult]],
        stream_briefings: list[dict],
    ) -> dict[str, Any]:
        """통합 Executive Daily Briefing"""
        if settings.ENABLE_FACT_CARD_PIPELINE:
            return await self._v2_unified(all_results, stream_briefings)

        # ── 레거시 경로 ──
        truncation_cap = 4000  # 토큰 예산 보호

        # 스트림 브리핑을 카테고리별로 분류
        therapeutic_briefs = []
        innovation_briefs = []
        external_briefs = []
        for sb in stream_briefings:
            stype = sb.get("stream_type", "")
            if "therapeutic" in stype or "치료" in sb.get("headline", ""):
                therapeutic_briefs.append(sb)
            elif "innovation" in stype or "혁신" in sb.get("headline", ""):
                innovation_briefs.append(sb)
            elif "external" in stype or "외부" in sb.get("headline", "") or "트렌드" in sb.get("headline", ""):
                external_briefs.append(sb)

        # 스트림 브리핑 JSON 직접 주입 (truncation cap 적용)
        def _truncate_json(data: list[dict]) -> str:
            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) > truncation_cap:
                text = text[:truncation_cap] + "...(truncated)"
            return text if data else "브리핑 없음"

        therapeutic_summary = _truncate_json(therapeutic_briefs)
        innovation_summary = _truncate_json(innovation_briefs)
        external_summary = _truncate_json(external_briefs)

        # 스트림별 통계
        def _stream_stats(results: list[StreamResult]) -> tuple[int, int]:
            return (
                sum(r.drug_count for r in results),
                sum(r.signal_count for r in results),
            )

        t_drugs, t_signals = _stream_stats(all_results.get("therapeutic_area", []))
        i_drugs, i_signals = _stream_stats(all_results.get("innovation", []))
        e_drugs, e_signals = _stream_stats(all_results.get("external", []))

        # 스트림 간 교차 약물 추출
        cross_drugs = self._find_cross_stream_drugs(all_results)

        prompt = UNIFIED_BRIEFING_PROMPT.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            therapeutic_summary=therapeutic_summary,
            therapeutic_drug_count=t_drugs,
            therapeutic_signal_count=t_signals,
            innovation_summary=innovation_summary,
            innovation_drug_count=i_drugs,
            innovation_signal_count=i_signals,
            external_summary=external_summary,
            external_drug_count=e_drugs,
            external_signal_count=e_signals,
            cross_stream_drugs=cross_drugs,
        )

        try:
            content = await self._call_llm(prompt)
            return self._parse_json_response(content, fallback_headline="RegScan 데일리 브리핑")
        except Exception as e:
            logger.warning("통합 브리핑 생성 실패: %s", e)
            return {
                "headline": "RegScan 데일리 브리핑",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "stream_count": len(all_results),
            }

    # ── 통합 브리핑용 헬퍼 ──

    def _rich_summarize(
        self,
        results: list[StreamResult],
        stream_briefings: list[dict],
        stream_key: str,
    ) -> str:
        """스트림 결과 + 이미 생성된 브리핑을 결합한 풍부한 요약"""
        if not results:
            return "수집 없음"

        total_drugs = sum(r.drug_count for r in results)
        total_signals = sum(r.signal_count for r in results)
        categories = [r.sub_category for r in results if r.sub_category]
        top_inns = []
        for r in results:
            top_inns.extend(r.inn_list[:5])

        base = (
            f"약물 {total_drugs}건, 시그널 {total_signals}건. "
            f"카테고리: {', '.join(categories) if categories else 'N/A'}. "
            f"주요 INN: {', '.join(top_inns[:10])}"
        )

        # 이미 생성된 스트림 브리핑에서 headline + key_takeaway 추출
        for sb in stream_briefings:
            headline = sb.get("headline", "")
            takeaway = sb.get("key_takeaway", "")
            if takeaway:
                base += f"\n브리핑 요약: {headline} — {takeaway}"
                break

        return base

    def _find_cross_stream_drugs(self, all_results: dict[str, list[StreamResult]]) -> str:
        """여러 스트림에 동시 등장하는 약물 찾기"""
        inn_streams: dict[str, list[str]] = {}
        for sname, sresults in all_results.items():
            for sr in sresults:
                for inn in sr.inn_list[:50]:
                    inn_upper = inn.upper()
                    if inn_upper not in inn_streams:
                        inn_streams[inn_upper] = []
                    if sname not in inn_streams[inn_upper]:
                        inn_streams[inn_upper].append(sname)

        # 2개 이상 스트림에 등장하는 약물
        cross = {inn: streams for inn, streams in inn_streams.items() if len(streams) >= 2}
        if not cross:
            return "교차 등장 약물 없음"

        lines = []
        for inn, streams in sorted(cross.items(), key=lambda x: -len(x[1]))[:10]:
            lines.append(f"- {inn}: {', '.join(streams)} ({len(streams)}개 스트림)")
        return "\n".join(lines)

    # ── V2 팩트카드 기반 메서드 ──

    def _v2_build_card_context(
        self, cards: list, today: str,
        indication_cards: dict | None = None,
        competition_cards: dict | None = None,
    ) -> tuple[str, str, str, str, str]:
        """팩트카드 + 적응증 + 경쟁구도 → JSON strings

        Returns:
            (fact_cards_json, fact_phrases_json, guardrailed_json,
             indications_json, competitions_json)
        """
        compact = [c.to_compact_dict() for c in cards]
        fact_cards_json = json.dumps(compact, ensure_ascii=False, indent=2)
        phrases = {c.inn: c.all_fact_phrases for c in cards}
        fact_phrases_json = json.dumps(phrases, ensure_ascii=False, indent=2)
        guardrailed = [c.inn for c in cards if c.is_guardrailed]
        guardrailed_json = json.dumps(guardrailed, ensure_ascii=False)

        # IndicationCard
        ind_dict = {}
        if indication_cards:
            for inn, ic in indication_cards.items():
                ind_dict[inn] = ic.to_compact_dict()
        indications_json = json.dumps(ind_dict, ensure_ascii=False, indent=2) if ind_dict else "{}"

        # CompetitionCard
        comp_dict = {}
        if competition_cards:
            for inn, cc in competition_cards.items():
                comp_dict[inn] = cc.to_compact_dict()
        competitions_json = json.dumps(comp_dict, ensure_ascii=False, indent=2) if comp_dict else "{}"

        return fact_cards_json, fact_phrases_json, guardrailed_json, indications_json, competitions_json

    @staticmethod
    def _v2_validate(briefing_json: dict, cards: list) -> dict:
        """Step 4 Validator 호출 — 위반 시 fallback 교체."""
        from regscan.stream.fact_validator import validate_briefing
        vr = validate_briefing(briefing_json, cards)
        return vr.corrected_briefing

    async def _v2_generate_cards_and_trends(
        self,
        result: StreamResult,
        stream_name: str,
        today: str,
    ) -> tuple[list, dict, dict, dict]:
        """공통: HIRA enrichment → 팩트카드 → IndicationCard → CompetitionCard → 트렌드 분석

        Returns:
            (fact_cards, trends, indication_cards, competition_cards)
        """
        from regscan.stream.fact_card import generate_fact_cards
        from regscan.stream.trend_analyzer import analyze_trends

        await enrich_drugs_with_hira(result.drugs_found)
        cards = generate_fact_cards(result.drugs_found, today=today)
        trends = await analyze_trends(cards, stream_name=stream_name, today=today)

        # IndicationCard 생성 (Phase 1)
        indication_cards: dict = {}
        try:
            from regscan.map.indication_card import generate_indication_cards
            indication_cards = await generate_indication_cards(result.drugs_found)
        except Exception as e:
            logger.debug("[V2] IndicationCard 생성 실패: %s", e)

        # CompetitionCard 생성 (Phase 2 — HemOnc 데이터 있을 때만)
        competition_cards: dict = {}
        try:
            from regscan.map.hemonc import get_hemonc_index
            hemonc = get_hemonc_index()
            if hemonc:
                for drug in result.drugs_found:
                    inn = (drug.get("inn") or "").strip().upper()
                    if inn:
                        comp = hemonc.get_competition_card(inn)
                        if comp.compared_drugs or comp.diseases:
                            competition_cards[inn] = comp
                if competition_cards:
                    logger.info("[V2] CompetitionCard: %d건 (HemOnc)", len(competition_cards))
        except Exception as e:
            logger.debug("[V2] CompetitionCard 생성 실패: %s", e)

        return cards, trends, indication_cards, competition_cards

    async def _v2_therapeutic(
        self, area: str, area_ko: str, result: StreamResult,
        today: str | None = None,
    ) -> dict[str, Any]:
        """V2 치료영역 브리핑 — 팩트카드 기반"""
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")
        cards, trends, ind_cards, comp_cards = await self._v2_generate_cards_and_trends(
            result, f"therapeutic_{area}", today,
        )
        if not cards:
            return self._fallback_therapeutic(area, area_ko, result)

        fc_json, fp_json, gr_json, ind_json, comp_json = self._v2_build_card_context(
            cards, today, ind_cards, comp_cards,
        )
        system = V2_ARTICLE_SYSTEM_PROMPT.format(today=today)
        prompt = V2_THERAPEUTIC_PROMPT.format(
            n=len(cards), area=area, area_ko=area_ko,
            fact_cards=fc_json, fact_phrases=fp_json,
            trends=json.dumps(trends, ensure_ascii=False, default=str),
            guardrailed=gr_json,
            indications=ind_json,
            competitions=comp_json,
        )

        try:
            content = await self._call_llm(prompt, system_prompt=system)
            result_json = self._parse_json_response(content, fallback_headline=f"{area_ko} 치료영역 브리핑")
            result_json = self._v2_validate(result_json, cards)
            result_json["_v2"] = True
            result_json["_card_count"] = len(cards)
            return result_json
        except Exception as e:
            logger.warning("[V2] 치료영역 브리핑 실패 (%s): %s", area, e)
            return self._fallback_therapeutic(area, area_ko, result)

    async def _v2_innovation(self, result: StreamResult, today: str | None = None) -> dict[str, Any]:
        """V2 혁신 시그널 브리핑 — 팩트카드 기반"""
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")
        cards, trends, ind_cards, comp_cards = await self._v2_generate_cards_and_trends(
            result, "innovation", today,
        )
        if not cards:
            return {"headline": "혁신 시그널 브리핑", "signals": result.signals[:10]}

        dc = self._count_designations(result.drugs_found)

        fc_json, fp_json, gr_json, ind_json, comp_json = self._v2_build_card_context(
            cards, today, ind_cards, comp_cards,
        )
        system = V2_ARTICLE_SYSTEM_PROMPT.format(today=today)
        prompt = V2_INNOVATION_PROMPT.format(
            n=len(cards),
            fact_cards=fc_json, fact_phrases=fp_json,
            trends=json.dumps(trends, ensure_ascii=False, default=str),
            guardrailed=gr_json,
            indications=ind_json,
            competitions=comp_json,
            nme_count=dc["nme"], prime_count=dc["prime"],
            orphan_count=dc["orphan"], conditional_count=dc["conditional"],
        )

        try:
            content = await self._call_llm(prompt, system_prompt=system)
            result_json = self._parse_json_response(content, fallback_headline="혁신 시그널 브리핑")
            result_json = self._v2_validate(result_json, cards)
            result_json["_v2"] = True
            result_json["_card_count"] = len(cards)
            return result_json
        except Exception as e:
            logger.warning("[V2] 혁신 브리핑 실패: %s", e)
            return {"headline": "혁신 시그널 브리핑", "signals": result.signals[:10]}

    async def _v2_external(self, result: StreamResult, today: str | None = None) -> dict[str, Any]:
        """V2 외부시그널 브리핑 — 팩트카드 기반"""
        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")
        cards, trends, ind_cards, comp_cards = await self._v2_generate_cards_and_trends(
            result, "external", today,
        )
        if not cards:
            return {"headline": "미래 트렌드 리포트", "signals": result.signals[:10]}

        fail_count = sum(1 for s in result.signals if s.get("verdict") == "FAIL")
        pending_count = sum(1 for s in result.signals if s.get("verdict") == "PENDING")
        medrxiv_count = sum(1 for s in result.signals if s.get("type") == "medrxiv_paper")

        fc_json, fp_json, gr_json, ind_json, comp_json = self._v2_build_card_context(
            cards, today, ind_cards, comp_cards,
        )
        system = V2_ARTICLE_SYSTEM_PROMPT.format(today=today)
        prompt = V2_EXTERNAL_PROMPT.format(
            n=len(cards),
            fact_cards=fc_json, fact_phrases=fp_json,
            trends=json.dumps(trends, ensure_ascii=False, default=str),
            guardrailed=gr_json,
            indications=ind_json,
            competitions=comp_json,
            fail_count=fail_count, pending_count=pending_count,
            medrxiv_count=medrxiv_count,
        )

        try:
            content = await self._call_llm(prompt, system_prompt=system)
            result_json = self._parse_json_response(content, fallback_headline="미래 트렌드 리포트")
            result_json = self._v2_validate(result_json, cards)
            result_json["_v2"] = True
            result_json["_card_count"] = len(cards)
            return result_json
        except Exception as e:
            logger.warning("[V2] 외부시그널 브리핑 실패: %s", e)
            return {"headline": "미래 트렌드 리포트", "signals": result.signals[:10]}

    async def _v2_unified(
        self,
        all_results: dict[str, list[StreamResult]],
        stream_briefings: list[dict],
    ) -> dict[str, Any]:
        """V2 통합 브리핑 — 전체 팩트카드 Top N 기반"""
        from regscan.stream.fact_card import generate_fact_cards
        from regscan.stream.trend_analyzer import analyze_trends

        today = datetime.now().strftime("%Y-%m-%d")  # unified는 외부 주입 불필요

        # 전체 스트림에서 약물 수집 → 배치 1회 enrichment
        all_drugs: list[dict] = []
        for sresults in all_results.values():
            for sr in sresults:
                all_drugs.extend(sr.drugs_found)
        await enrich_drugs_with_hira(all_drugs)

        cards = generate_fact_cards(all_drugs, today=today)
        if not cards:
            return {
                "headline": "RegScan 데일리 브리핑",
                "date": today,
                "stream_count": len(all_results),
            }

        # 상위 약물 선별 (가드레일 아닌 것 우선, 최대 15개)
        sorted_cards = sorted(cards, key=lambda c: (c.is_guardrailed, not bool(c.fda_phrase)))
        top_cards = sorted_cards[:15]

        # 트렌드 분석
        trends = await analyze_trends(top_cards, stream_name="unified", today=today)

        # 스트림별 트렌드 요약 (이미 생성된 브리핑에서 추출)
        stream_trend_lines = []
        for sb in stream_briefings:
            headline = sb.get("headline", "")
            takeaway = sb.get("key_takeaway", "")
            if headline and takeaway:
                stream_trend_lines.append(f"- {headline}: {takeaway}")
        stream_trends_text = "\n".join(stream_trend_lines) if stream_trend_lines else "스트림 브리핑 없음"

        # 교차 약물
        cross_drugs = self._find_cross_stream_drugs(all_results)

        fc_json, fp_json, gr_json, ind_json, comp_json = self._v2_build_card_context(top_cards, today)
        system = V2_ARTICLE_SYSTEM_PROMPT.format(today=today)
        prompt = V2_UNIFIED_PROMPT.format(
            n=len(top_cards),
            fact_cards=fc_json, fact_phrases=fp_json,
            stream_trends=stream_trends_text,
            cross_signals=cross_drugs,
            guardrailed=gr_json,
            indications=ind_json,
            competitions=comp_json,
        )

        try:
            content = await self._call_llm(prompt, system_prompt=system)
            result_json = self._parse_json_response(content, fallback_headline="RegScan 데일리 브리핑")
            result_json = self._v2_validate(result_json, top_cards)
            result_json["_v2"] = True
            result_json["_card_count"] = len(top_cards)
            return result_json
        except Exception as e:
            logger.warning("[V2] 통합 브리핑 실패: %s", e)
            return {
                "headline": "RegScan 데일리 브리핑",
                "date": today,
                "stream_count": len(all_results),
            }

    def _fallback_therapeutic(self, area: str, area_ko: str, result: StreamResult) -> dict:
        """LLM 실패 시 구조화 데이터 기반 브리핑"""
        return {
            "headline": f"{area_ko} 치료영역 브리핑",
            "drug_count": result.drug_count,
            "top_drugs": [{"inn": inn} for inn in result.inn_list[:10]],
            "errors": result.errors,
        }

    # ── LLM 호출 ──

    # 마지막 LLM 호출의 프롬프트 캡처 (디버깅/스냅샷용)
    _last_system_prompt: str = ""
    _last_user_prompt: str = ""
    _last_model_used: str = ""

    async def _call_llm(self, prompt: str, system_prompt: str | None = None) -> str:
        """LLM 호출 — system_prompt가 None이면 기존 shared 기반 조립"""
        today = datetime.now().strftime("%Y-%m-%d")
        if system_prompt is None:
            system_prompt = _build_stream_system_prompt(today)

        # 프롬프트 캡처
        self._last_system_prompt = system_prompt
        self._last_user_prompt = prompt

        # 1차: OpenAI (gpt-5.2 — V4.1 검증 완료 모델)
        if settings.OPENAI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                response = await client.chat.completions.create(
                    model=settings.WRITER_MODEL,  # gpt-5.2
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    max_completion_tokens=3500,
                    temperature=0.3,
                )
                self._last_model_used = settings.WRITER_MODEL
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.debug("OpenAI 브리핑 호출 실패: %s", e)

        # 2차: Gemini
        if settings.GEMINI_API_KEY:
            try:
                from google import genai
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"
                response = client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=full_prompt,
                )
                self._last_model_used = settings.GEMINI_MODEL
                return response.text or ""
            except Exception as e:
                logger.debug("Gemini 브리핑 호출 실패: %s", e)

        # 3차: Anthropic
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
                response = await client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=3500,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                self._last_model_used = "claude-sonnet-4-5-20250929"
                return response.content[0].text
            except Exception as e:
                logger.debug("Anthropic 브리핑 호출 실패: %s", e)

        raise RuntimeError("LLM API 키 미설정 (OPENAI/GEMINI/ANTHROPIC)")

    def _parse_json_response(self, text: str, fallback_headline: str = "") -> dict:
        """LLM JSON 응답 파싱"""
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"headline": fallback_headline, "raw_text": text[:500]}
