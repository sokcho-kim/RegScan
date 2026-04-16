"""팩트 검증기 — Step 4: 브리핑 본문 vs 팩트카드 교차 검증 (LLM 없음)

2단계 검증:
  1) 하드 체크 — 날짜/가격/상태 exact match. 위반 시 문단 폐기.
  2) 소프트 체크 — 팩트 문구 포함 여부. 누락 시 경고 로그.

자동 교정 금지 — 위반 시 fallback fact-only 문단 삽입 + 로그.

Usage:
    result = validate_briefing(briefing_json, fact_cards)
    if result.has_violations:
        briefing_json = result.corrected_briefing  # 위반 문단 → fallback
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from regscan.stream.fact_card import FactCard

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 위반 레코드
# ════════════════════════════════════════════════════════════════════

@dataclass
class Violation:
    """단일 위반 기록."""
    inn: str
    check_type: str          # "hard" | "soft"
    category: str            # "date" | "price" | "status" | "guardrail" | "phrase_missing"
    detail: str              # 위반 상세
    field_path: str = ""     # 위반이 발견된 JSON 경로


@dataclass
class ValidationResult:
    """검증 결과."""
    violations: list[Violation] = field(default_factory=list)
    corrected_briefing: dict = field(default_factory=dict)
    fallback_count: int = 0  # fallback으로 교체된 문단 수

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.check_type == "hard"]

    @property
    def soft_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.check_type == "soft"]


# ════════════════════════════════════════════════════════════════════
# 상태 키워드 — 하드 체크 대상
# ════════════════════════════════════════════════════════════════════

# 팩트카드에 없는 상태 단정문이 본문에 나타나면 위반
_ASSERTIVE_PATTERNS: list[tuple[str, str]] = [
    (r"급여\s*등재", "hira_reimbursed"),
    (r"비급여", "hira_non_reimbursed"),
    (r"급여\s*삭제", "hira_delisted"),
    (r"식약처\s*미허가", "mfds_unapproved"),
    (r"식약처\s*허가\s*완료", "mfds_approved"),
    (r"FDA\s*승인\s*완료", "fda_approved"),
    (r"FDA\s*승인\s*예정", "fda_pending"),
    (r"EMA\s*허가\s*완료", "ema_approved"),
]

# 가드레일 약물에서 사용 금지되는 단정 패턴
_GUARDRAIL_FORBIDDEN: list[str] = [
    r"확인됨",
    r"확인\s*완료",
    r"등재\s*확인",
    r"미허가\s*확인",
    r"미허가$",
    r"승인\s*완료",
    r"허가\s*완료",
]

# 날짜 패턴
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

# 가격 패턴 (콤마 포함 숫자 + "원")
_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원")

# 브리핑 JSON 스키마 키 — 약물 리스트 / 텍스트 필드
_DRUG_LIST_KEYS = ["top_drugs", "nme_spotlight", "trial_failures", "top_5_drugs"]
_TEXT_FIELD_KEYS = [
    "headline", "key_takeaway", "executive_summary",
    "trend_analysis", "cross_analysis", "strategic_implications",
]


# ════════════════════════════════════════════════════════════════════
# 하드 체크
# ════════════════════════════════════════════════════════════════════

def _hard_check_dates(text: str, card: FactCard) -> list[Violation]:
    """본문의 YYYY-MM-DD가 팩트카드에 있는 날짜인지 검증."""
    violations = []
    allowed_dates = set()
    for d in [card.fda_date, card.ema_date, card.mfds_date]:
        if d:
            allowed_dates.add(d)

    found_dates = _DATE_PATTERN.findall(text)
    for date_str in found_dates:
        if date_str not in allowed_dates:
            violations.append(Violation(
                inn=card.inn,
                check_type="hard",
                category="date",
                detail=f"팩트카드에 없는 날짜: {date_str} (허용: {allowed_dates or 'none'})",
            ))
    return violations


def _hard_check_prices(text: str, card: FactCard) -> list[Violation]:
    """본문의 가격이 팩트카드 가격과 일치하는지 검증."""
    violations = []
    if card.hira_price is None:
        # 가격 정보 없는데 본문에 가격 언급 → 위반
        found_prices = _PRICE_PATTERN.findall(text)
        if found_prices:
            violations.append(Violation(
                inn=card.inn,
                check_type="hard",
                category="price",
                detail=f"팩트카드에 가격 없으나 본문에 가격 언급: {found_prices}",
            ))
    else:
        expected = f"{card.hira_price:,.0f}"
        found_prices = _PRICE_PATTERN.findall(text)
        for price_str in found_prices:
            normalized = price_str.replace(",", "")
            expected_raw = str(int(card.hira_price))
            if normalized != expected_raw:
                violations.append(Violation(
                    inn=card.inn,
                    check_type="hard",
                    category="price",
                    detail=f"가격 불일치: 본문 '{price_str}원' vs 팩트카드 '{expected}원'",
                ))
    return violations


def _hard_check_status(text: str, card: FactCard) -> list[Violation]:
    """본문의 상태 단정문이 팩트카드와 일치하는지 검증."""
    violations = []
    card_phrases_lower = " ".join(card.all_fact_phrases).lower()

    for pattern, status_key in _ASSERTIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if not matches:
            continue

        # 팩트카드에 해당 상태가 없는데 본문에서 단정 → 위반
        pattern_in_card = re.search(pattern, card_phrases_lower)
        if not pattern_in_card:
            violations.append(Violation(
                inn=card.inn,
                check_type="hard",
                category="status",
                detail=f"팩트카드에 없는 상태 단정: '{matches[0]}' (key: {status_key})",
            ))
    return violations


def _hard_check_guardrail(text: str, card: FactCard) -> list[Violation]:
    """가드레일 약물에 단정문 사용 여부 검증."""
    if not card.is_guardrailed:
        return []

    violations = []
    for pattern in _GUARDRAIL_FORBIDDEN:
        matches = re.findall(pattern, text)
        if matches:
            violations.append(Violation(
                inn=card.inn,
                check_type="hard",
                category="guardrail",
                detail=f"가드레일 약물에 단정문: '{matches[0]}' (guardrail: {card.guardrail_notes})",
            ))
    return violations


# ════════════════════════════════════════════════════════════════════
# 소프트 체크
# ════════════════════════════════════════════════════════════════════

def _soft_check_phrase_inclusion(text: str, card: FactCard) -> list[Violation]:
    """팩트카드의 핵심 문구가 본문에 포함되었는지 검증.

    verbatim이 아니라 핵심 키워드 포함 여부로 판단.
    한국어 조사/어순 차이를 감안.
    """
    violations = []
    for phrase in card.all_fact_phrases:
        # 핵심 키워드 추출 (숫자, 기관명, 상태)
        keywords = _extract_keywords(phrase)
        if not keywords:
            continue

        # 키워드 중 절반 이상 포함되면 OK
        found_count = sum(1 for kw in keywords if kw in text)
        threshold = max(1, len(keywords) // 2)
        if found_count < threshold:
            violations.append(Violation(
                inn=card.inn,
                check_type="soft",
                category="phrase_missing",
                detail=f"팩트 문구 누락 의심: '{phrase}' (키워드 {found_count}/{len(keywords)} 포함)",
            ))
    return violations


def _extract_keywords(phrase: str) -> list[str]:
    """팩트 문구에서 검증용 핵심 키워드 추출."""
    keywords = []

    # 날짜
    dates = _DATE_PATTERN.findall(phrase)
    keywords.extend(dates)

    # 가격 (숫자부분)
    prices = _PRICE_PATTERN.findall(phrase)
    keywords.extend(prices)

    # 기관명
    for org in ["FDA", "EMA", "식약처", "심평원"]:
        if org in phrase:
            keywords.append(org)

    # 상태 키워드
    for status in ["승인", "허가", "급여", "비급여", "삭제", "미확인", "확인 필요", "매핑 실패"]:
        if status in phrase:
            keywords.append(status)

    return keywords


# ════════════════════════════════════════════════════════════════════
# Fallback 문단 생성
# ════════════════════════════════════════════════════════════════════

def _build_fallback_drug_entry(card: FactCard) -> dict:
    """위반 약물의 fallback fact-only 엔트리."""
    phrases = card.all_fact_phrases
    status_line = ". ".join(phrases) if phrases else "데이터 확인 필요"

    entry: dict[str, Any] = {
        "inn": card.inn,
        "status": status_line,
        "why_it_matters": "팩트카드 기반 자동 생성 (검증 위반으로 원문 폐기)",
    }
    if card.is_guardrailed:
        entry["guardrail"] = "; ".join(card.guardrail_notes)
    return entry


# ════════════════════════════════════════════════════════════════════
# 메인 검증 함수
# ════════════════════════════════════════════════════════════════════

def validate_briefing(
    briefing: dict,
    fact_cards: list[FactCard],
) -> ValidationResult:
    """브리핑 JSON vs 팩트카드 교차 검증.

    Args:
        briefing: Step 3에서 생성된 브리핑 JSON
        fact_cards: Step 1에서 생성된 FactCard 리스트

    Returns:
        ValidationResult — 위반 목록 + 교정된 브리핑
    """
    result = ValidationResult()
    result.corrected_briefing = copy.deepcopy(briefing)

    # INN → FactCard 매핑
    card_map: dict[str, FactCard] = {c.inn: c for c in fact_cards}

    # 약물 엔트리 검증
    for list_key in _DRUG_LIST_KEYS:
        drug_list = briefing.get(list_key)
        if not isinstance(drug_list, list):
            continue

        corrected_list = []
        for i, entry in enumerate(drug_list):
            inn = (entry.get("inn") or "").strip().upper()
            card = card_map.get(inn)

            if card is None:
                # 팩트카드에 없는 약물 → 경고만
                corrected_list.append(entry)
                continue

            # 엔트리 텍스트 조립 (검증 대상)
            entry_text = _entry_to_text(entry)

            # 하드 체크
            hard_violations = []
            hard_violations.extend(_hard_check_dates(entry_text, card))
            hard_violations.extend(_hard_check_prices(entry_text, card))
            hard_violations.extend(_hard_check_status(entry_text, card))
            hard_violations.extend(_hard_check_guardrail(entry_text, card))

            if hard_violations:
                # field_path 설정 후 append
                for v in hard_violations:
                    v.field_path = f"{list_key}[{i}]"
                result.violations.extend(hard_violations)
                # 위반 → 문단 폐기 + fallback 삽입
                fallback = _build_fallback_drug_entry(card)
                corrected_list.append(fallback)
                result.fallback_count += 1
                logger.warning(
                    "[Validator] %s 하드 위반 %d건 → fallback 교체 (field: %s[%d])",
                    inn, len(hard_violations), list_key, i,
                )
            else:
                # 소프트 체크
                soft_violations = _soft_check_phrase_inclusion(entry_text, card)
                if soft_violations:
                    for v in soft_violations:
                        v.field_path = f"{list_key}[{i}]"
                    result.violations.extend(soft_violations)
                    logger.info(
                        "[Validator] %s 소프트 위반 %d건 (유지, 로그만)",
                        inn, len(soft_violations),
                    )
                corrected_list.append(entry)

        result.corrected_briefing[list_key] = corrected_list

    # 전체 텍스트 레벨 검증
    for text_key in _TEXT_FIELD_KEYS:
        text_val = briefing.get(text_key, "")
        if not isinstance(text_val, str) or not text_val:
            continue

        for card in fact_cards:
            hard_v = []
            hard_v.extend(_hard_check_dates(text_val, card))
            hard_v.extend(_hard_check_guardrail(text_val, card))
            for v in hard_v:
                v.field_path = text_key
            result.violations.extend(hard_v)

    # 검증 메타데이터
    result.corrected_briefing["_validation"] = {
        "total_violations": len(result.violations),
        "hard_violations": len(result.hard_violations),
        "soft_violations": len(result.soft_violations),
        "fallback_count": result.fallback_count,
        "validated": True,
    }

    if result.violations:
        logger.warning(
            "[Validator] 검증 완료 — 위반 %d건 (하드: %d, 소프트: %d), fallback: %d건",
            len(result.violations),
            len(result.hard_violations),
            len(result.soft_violations),
            result.fallback_count,
        )
    else:
        logger.info("[Validator] 검증 통과 — 위반 없음")

    return result


def _entry_to_text(entry: dict) -> str:
    """약물 엔트리의 모든 텍스트 필드를 하나의 문자열로 결합."""
    parts = []
    for key in ["status", "why_it_matters", "implication", "verdict",
                 "hospital_impact", "reason", "action"]:
        val = entry.get(key, "")
        if isinstance(val, str) and val:
            parts.append(val)
    return " ".join(parts)
