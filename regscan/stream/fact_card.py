"""팩트카드 생성기 — Step 1: 코드가 팩트를 만든다 (LLM 없음)

모든 팩트 문구는 ALLOWED_PHRASES 매트릭스에서 결정된다.
LLM이 팩트를 생성하면 hallucination. 코드가 팩트를 만들고 LLM은 문장으로 바꾸기만.

Usage:
    card = generate_fact_card(drug_dict, today="2026-04-16")
    compact = card.to_compact_dict()  # LLM 입력용 ~10줄
    phrases = card.all_fact_phrases    # 최종 기사에 반드시 포함
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ════════════════════════════════════════════════════════════════════
# ALLOWED_PHRASES — (상태 × 신뢰도) → 고정 문구
# ════════════════════════════════════════════════════════════════════

# HIRA: (ReimbursementStatus, MatchConfidence) → phrase
# {price}, {dosage} 는 런타임 치환
HIRA_PHRASES: dict[tuple[str, str], str] = {
    # 급여 등재 — 신뢰도별 분기
    ("reimbursed", "exact_match"):       "심평원 급여 등재 확인 (상한가 {price}원, {dosage})",
    ("reimbursed", "normalized_match"):  "심평원 급여 등재 확인 (상한가 {price}원, 정규화 매칭)",
    ("reimbursed", "base_fallback_match"): "심평원 급여 등재 추정 — 매칭 신뢰도 낮음, 수동 확인 필요",
    ("reimbursed", "atc_fallback"):      "심평원 급여 등재 추정 — ATC 기반 매칭, 수동 확인 필요",
    # 비급여
    ("non_reimbursed", "_default"):      "심평원 비급여 (전액 환자부담)",
    ("not_covered", "_default"):         "심평원 비급여 (전액 환자부담)",
    # 삭제
    ("delisted", "_default"):            "심평원 급여 삭제 (과거 등재 이력)",
    ("deleted", "_default"):             "심평원 급여 삭제 (과거 등재 이력)",
    # 평가 이력
    ("evaluation_history", "_default"):  "심평원 급여평가 이력 있음 (등재 여부 별도 확인 필요)",
    # 미확인
    ("not_found_in_source", "_default"): "심평원 원천 데이터 미확인 — 미등재 또는 수집 누락 가능",
    ("not_found", "_default"):           "심평원 원천 데이터 미확인 — 미등재 또는 수집 누락 가능",
    # 매핑 실패
    ("bridge_unmatched", "_default"):    "심평원 매핑 실패 — 급여/가격 정보 확인 불가",
    # 한약재
    ("herbal", "_default"):              "한약재/생약 (별도 급여 체계)",
    # 수동 확인
    ("manual_review_required", "_default"): "심평원 급여 상태 수동 확인 필요",
}

# MFDS: (MFDSStatus, has_date) → phrase
MFDS_PHRASES: dict[tuple[str, bool], str] = {
    ("approved", True):                  "국내 식약처 허가 완료 ({date})",
    ("approved", False):                 "국내 식약처 허가 확인 (허가일 미확인)",
    ("unapproved_confirmed", True):      "국내 식약처 미허가 확인",
    ("unapproved_confirmed", False):     "국내 식약처 미허가 확인",
    ("not_found", True):                 "국내 식약처 허가 여부 추가 확인 필요",
    ("not_found", False):                "국내 식약처 허가 여부 추가 확인 필요",
    ("ambiguous_match", True):           "국내 식약처 허가 정보 모호 — 수동 확인 필요",
    ("ambiguous_match", False):          "국내 식약처 허가 정보 모호 — 수동 확인 필요",
    ("manual_review_required", True):    "국내 식약처 허가 상태 수동 확인 필요",
    ("manual_review_required", False):   "국내 식약처 허가 상태 수동 확인 필요",
}

# FDA: (status, time_relation) → phrase
# time_relation: "past" | "future" | "unknown"
FDA_PHRASES: dict[tuple[str, str], str] = {
    ("AP", "past"):      "{date} FDA 승인 완료",
    ("AP", "future"):    "{date} FDA 승인 예정",
    ("AP", "unknown"):   "FDA 승인 확인 (승인일 미확인)",
    ("TA", "past"):      "{date} FDA 잠정 승인",
    ("TA", "future"):    "{date} FDA 잠정 승인 예정",
    ("TA", "unknown"):   "FDA 잠정 승인 확인",
    ("", "pdufa"):       "PDUFA {pdufa_date} 심사 예정",
    ("", "unknown"):     "FDA 승인일 미정",
}

# EMA: 단순화
EMA_PHRASES: dict[str, str] = {
    "Authorised":          "{date} EMA 허가 완료",
    "Authorised_no_date":  "EMA 허가 확인 (허가일 미확인)",
    "Withdrawn":           "EMA 허가 철회",
    "Refused":             "EMA 허가 거부",
    "unknown":             "EMA 허가 정보 없음",
}


# ════════════════════════════════════════════════════════════════════
# FactCard 데이터클래스
# ════════════════════════════════════════════════════════════════════

@dataclass
class FactCard:
    """약물별 팩트카드 — 모든 팩트가 코드에 의해 결정됨."""

    inn: str
    generated_at: str

    # 기관별 코드 확정 문구
    fda_phrase: str = ""
    ema_phrase: str = ""
    mfds_phrase: str = ""
    hira_phrase: str = ""

    # 상세 데이터
    fda_date: Optional[str] = None
    ema_date: Optional[str] = None
    ema_designations: list[str] = field(default_factory=list)
    mfds_date: Optional[str] = None
    hira_price: Optional[float] = None
    hira_dosage: str = ""
    hira_confidence: str = ""
    hira_source_date: str = ""
    hira_evidence_type: str = ""  # exact_price_match / board_missing / bridge_unmatched / source_not_loaded
    copay_phrase: Optional[str] = None
    access_phrase: Optional[str] = None

    # 가드레일
    is_guardrailed: bool = False
    guardrail_notes: list[str] = field(default_factory=list)

    # LLM 컨텍스트용 (팩트 아닌 배경 정보)
    brand_name: str = ""
    moa: str = ""
    indication: str = ""
    therapeutic_areas: list[str] = field(default_factory=list)
    atc_code: str = ""

    def to_compact_dict(self) -> dict:
        """LLM 입력용 ~10줄 JSON. 빈 값 제거."""
        d: dict[str, Any] = {"inn": self.inn}

        if self.fda_phrase:
            d["fda"] = self.fda_phrase
        if self.ema_phrase:
            d["ema"] = self.ema_phrase
        if self.ema_designations:
            d["designations"] = self.ema_designations
        if self.mfds_phrase:
            d["mfds"] = self.mfds_phrase
        if self.hira_phrase:
            d["hira"] = self.hira_phrase
        if self.copay_phrase:
            d["copay"] = self.copay_phrase
        if self.access_phrase:
            d["access"] = self.access_phrase
        if self.is_guardrailed:
            d["guardrail"] = "; ".join(self.guardrail_notes) if self.guardrail_notes else "수동 확인 필요"
        if self.indication:
            d["indication"] = self.indication[:100]
        if self.moa:
            d["moa"] = self.moa
        if self.hira_source_date:
            d["hira_기준일"] = self.hira_source_date

        return d

    @property
    def all_fact_phrases(self) -> list[str]:
        """최종 기사에 포함되어야 할 핵심 문구 목록."""
        phrases = []
        for p in [self.fda_phrase, self.ema_phrase, self.mfds_phrase, self.hira_phrase]:
            if p:
                phrases.append(p)
        return phrases

    @property
    def hard_check_values(self) -> dict:
        """Validator 하드 체크 대상 — 날짜/가격/상태."""
        values: dict[str, Any] = {}
        if self.fda_date:
            values["fda_date"] = self.fda_date
        if self.ema_date:
            values["ema_date"] = self.ema_date
        if self.mfds_date:
            values["mfds_date"] = self.mfds_date
        if self.hira_price is not None:
            values["hira_price"] = self.hira_price
        return values


# ════════════════════════════════════════════════════════════════════
# 팩트카드 생성 함수
# ════════════════════════════════════════════════════════════════════

def _get_hira_source_date() -> str:
    """현재 사용 중인 HIRA 약가 JSON의 기준일."""
    data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "hira"
    files = sorted(data_dir.glob("drug_prices_*.json"), reverse=True)
    if files:
        m = re.search(r"(\d{8})", files[0].name)
        return m.group(1) if m else "unknown"
    return "unknown"


def _resolve_fda_phrase(fda_data: dict, today: str) -> tuple[str, Optional[str]]:
    """FDA 상태 → (phrase, date)."""
    status = fda_data.get("submission_status", "")
    date = fda_data.get("submission_status_date", "")
    pdufa = fda_data.get("pdufa_date", "")

    if not status and not date:
        if pdufa:
            phrase = FDA_PHRASES.get(("", "pdufa"), "").format(pdufa_date=pdufa)
            return phrase, None
        return FDA_PHRASES.get(("", "unknown"), "FDA 승인일 미정"), None

    if status == "AP" or status == "TA":
        if date:
            if date <= today:
                time_rel = "past"
            else:
                time_rel = "future"
        else:
            time_rel = "unknown"
        phrase = FDA_PHRASES.get((status, time_rel), "")
        if phrase and date:
            phrase = phrase.format(date=date)
        return phrase, date if date else None

    return FDA_PHRASES.get(("", "unknown"), ""), None


def _resolve_ema_phrase(ema_data: dict) -> tuple[str, Optional[str], list[str]]:
    """EMA 상태 → (phrase, date, designations)."""
    status = ema_data.get("medicine_status", "")
    date = ema_data.get("marketing_authorisation_date", "")
    indication = ema_data.get("therapeutic_indication", "")

    designations = []
    if ema_data.get("is_orphan"):
        designations.append("orphan")
    if ema_data.get("is_prime"):
        designations.append("PRIME")
    if ema_data.get("is_conditional"):
        designations.append("conditional")
    if ema_data.get("is_accelerated"):
        designations.append("accelerated")

    if status == "Authorised":
        if date:
            phrase = EMA_PHRASES["Authorised"].format(date=date)
        else:
            phrase = EMA_PHRASES["Authorised_no_date"]
    elif status == "Withdrawn":
        phrase = EMA_PHRASES["Withdrawn"]
    elif status == "Refused":
        phrase = EMA_PHRASES["Refused"]
    else:
        phrase = EMA_PHRASES["unknown"]

    return phrase, date if date else None, designations


def _resolve_mfds_phrase(mfds_data: dict) -> tuple[str, Optional[str]]:
    """MFDS 상태 → (phrase, date)."""
    status_raw = mfds_data.get("approval_status", "")
    date = mfds_data.get("approval_date", "")
    has_date = bool(date)

    if status_raw == "허가":
        mfds_status = "approved"
    elif status_raw == "미허가":
        # 허가일이 없으면 → 수집 데이터 부재일 수 있음 → not_found
        if has_date:
            mfds_status = "unapproved_confirmed"
        else:
            mfds_status = "not_found"
    else:
        mfds_status = "not_found"

    phrase = MFDS_PHRASES.get((mfds_status, has_date), "국내 식약처 허가 여부 추가 확인 필요")
    if date and "{date}" in phrase:
        phrase = phrase.format(date=date)

    return phrase, date if date else None


def _resolve_hira(drug_dict: dict, hira_source_date: str) -> dict:
    """HIRA enrichment → phrase + evidence_type + 가드레일.

    기존 _enrich_via_bridge의 로직을 팩트카드용으로 재구성.
    IngredientBridge를 직접 호출한다.
    """
    from regscan.stream.briefing import _get_bridge, _extract_dosage_from_raw

    inn = (drug_dict.get("inn") or "").strip()
    if not inn:
        return {
            "phrase": "심평원 매핑 실패 — 급여/가격 정보 확인 불가",
            "confidence": "unmatched",
            "evidence_type": "bridge_unmatched",
            "is_guardrailed": True,
            "price": None,
            "dosage": "",
            "access": None,
            "copay": None,
        }

    bridge = _get_bridge()
    if bridge is None:
        return {
            "phrase": "심평원 원천 데이터 미확인 — 미등재 또는 수집 누락 가능",
            "confidence": "unmatched",
            "evidence_type": "source_not_loaded",
            "is_guardrailed": True,
            "price": None,
            "dosage": "",
            "access": None,
            "copay": None,
        }

    result = bridge.lookup(inn)
    method = result.match_method
    status = result.status.value
    price = result.price_ceiling
    raw = result.raw_data or {}

    # confidence 매핑
    confidence_map = {
        "normalized": "exact_match",
        "decomposed_variant": "normalized_match",
        "decomposed_base_fallback": "base_fallback_match",
        "atc": "atc_fallback",
        "unmatched": "unmatched",
    }
    confidence = confidence_map.get(method, method)

    # evidence_type 결정
    if method == "unmatched":
        evidence_type = "bridge_unmatched"
    elif price is not None:
        evidence_type = "exact_price_match"
    else:
        evidence_type = "board_missing"

    # ALLOWED_PHRASES 조회
    phrase_key = (status, confidence)
    phrase = HIRA_PHRASES.get(phrase_key)
    if not phrase:
        # confidence fallback → _default
        phrase = HIRA_PHRASES.get((status, "_default"), "심평원 급여 상태 확인 필요")

    # 치환
    dosage = _extract_dosage_from_raw(raw)
    if "{price}" in phrase and price is not None:
        price_str = f"{price:,.0f}"
        dosage_str = dosage if dosage else ""
        phrase = phrase.format(price=price_str, dosage=dosage_str)
    # 잔여 플레이스홀더 제거
    phrase = re.sub(r"\s*,\s*\)", ")", phrase)
    phrase = re.sub(r"\(\s*,\s*", "(", phrase)

    is_guardrailed = confidence in ("base_fallback_match", "atc_fallback", "unmatched")

    # access_routes
    access = None
    if status in ("not_found", "not_covered", "not_found_in_source", "bridge_unmatched"):
        access = "KODC 긴급도입 / 제약사 EAP / 비급여 처방"

    # copay
    copay = None
    criteria = result.reimbursement_criteria or ""
    if status == "reimbursed" and criteria:
        criteria_lower = criteria.lower()
        if "산정특례" in criteria_lower or "본인부담" in criteria_lower:
            if "암" in criteria_lower or "항암" in criteria_lower:
                copay = "암환자 산정특례(5%) 대상 가능"
            elif "희귀" in criteria_lower:
                copay = "희귀질환 산정특례(10%) 대상 가능"
            else:
                copay = "산정특례 대상 가능 (세부 확인 필요)"

    return {
        "phrase": phrase,
        "confidence": confidence,
        "evidence_type": evidence_type,
        "is_guardrailed": is_guardrailed,
        "price": price,
        "dosage": dosage,
        "access": access,
        "copay": copay,
    }


def generate_fact_card(drug: dict, today: str | None = None) -> FactCard:
    """약물 dict → FactCard. 순수 코드, LLM 없음.

    Args:
        drug: StreamResult.drugs_found[i] 형태의 dict
        today: YYYY-MM-DD 형식. None이면 현재 날짜.

    Returns:
        FactCard — 모든 팩트가 코드에 의해 결정됨
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    inn = (drug.get("inn") or "UNKNOWN").strip().upper()

    # FDA
    fda_data = drug.get("fda_data") or {}
    fda_phrase, fda_date = _resolve_fda_phrase(fda_data, today)

    # EMA
    ema_data = drug.get("ema_data") or {}
    ema_phrase, ema_date, ema_designations = _resolve_ema_phrase(ema_data)

    # MFDS
    mfds_data = drug.get("mfds_data") or {}
    mfds_phrase, mfds_date = _resolve_mfds_phrase(mfds_data)

    # HIRA
    hira_source_date = _get_hira_source_date()
    hira = _resolve_hira(drug, hira_source_date)

    # 가드레일 종합
    guardrail_notes = []
    if hira["is_guardrailed"]:
        guardrail_notes.append("HIRA: " + hira["evidence_type"])
    if "추가 확인 필요" in mfds_phrase:
        guardrail_notes.append("MFDS: 수집 데이터 부재")

    is_guardrailed = bool(guardrail_notes)

    # 배경 정보 (팩트 아님)
    brand_name = fda_data.get("brand_name", "")
    pharm = fda_data.get("pharm_class_epc", [])
    moa = pharm[0] if isinstance(pharm, list) and pharm else str(pharm) if pharm else ""
    indication = ema_data.get("therapeutic_indication", "")[:200]
    areas = drug.get("therapeutic_areas") or []
    if isinstance(areas, str):
        areas = [areas]
    atc_code = drug.get("atc_code", "")

    # scan 데이터의 designations도 반영
    scan_desig = drug.get("designations") or []
    for d in scan_desig:
        if d not in ema_designations:
            ema_designations.append(d)

    return FactCard(
        inn=inn,
        generated_at=datetime.now().isoformat(),
        fda_phrase=fda_phrase,
        ema_phrase=ema_phrase,
        mfds_phrase=mfds_phrase,
        hira_phrase=hira["phrase"],
        fda_date=fda_date,
        ema_date=ema_date,
        ema_designations=ema_designations,
        mfds_date=mfds_date,
        hira_price=hira["price"],
        hira_dosage=hira["dosage"],
        hira_confidence=hira["confidence"],
        hira_source_date=hira_source_date,
        hira_evidence_type=hira["evidence_type"],
        copay_phrase=hira["copay"],
        access_phrase=hira["access"],
        is_guardrailed=is_guardrailed,
        guardrail_notes=guardrail_notes,
        brand_name=brand_name,
        moa=moa,
        indication=indication,
        therapeutic_areas=areas,
        atc_code=atc_code,
    )


def generate_fact_cards(drugs: list[dict], today: str | None = None) -> list[FactCard]:
    """여러 약물 일괄 팩트카드 생성."""
    return [generate_fact_card(d, today) for d in drugs]
