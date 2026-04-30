"""보조 인텔리전스 → 브리핑용 시그널 추출

Step 4.8에서 수집한 aux_data를 소스별 시그널로 변환.
시그널이 있는 소스만 브리핑 발행 대상.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 소스별 브리핑 메타
SOURCE_META = {
    "PMDA_APPROVAL": {
        "label": "일본 PMDA 승인 동향",
        "description": "일본 의약품의료기기종합기구(PMDA) 신약 승인 현황",
        "priority": 1,
    },
    "NICE_TA": {
        "label": "영국 NICE HTA 권고 분석",
        "description": "영국 국립보건의료연구원(NICE) Technology Appraisal 권고",
        "priority": 2,
    },
    "ASSEMBLY_BILL": {
        "label": "보건의료 입법 동향",
        "description": "국회 보건의료 관련 법안 발의·심의 현황",
        "priority": 3,
    },
    "MOHW_HEALTH_INSURANCE": {
        "label": "건강보험 급여 변동",
        "description": "보건복지부 건강보험정책 관련 보도자료",
        "priority": 4,
    },
    "MFDS_SAFETY_LETTER": {
        "label": "의약품 안전성 경보",
        "description": "식약처 안전성 서한·속보 발행 현황",
        "priority": 5,
    },
    "DART_DISCLOSURE": {
        "label": "제약 기업 공시 동향",
        "description": "DART 전자공시 중 제약·바이오 관련 공시",
        "priority": 6,
    },
    "KIPRIS_PATENT": {
        "label": "의약품 특허 동향",
        "description": "KIPRIS 의약품 관련 특허 공개·등록 현황",
        "priority": 7,
    },
    "MFDS_PRESS": {
        "label": "식약처 보도자료",
        "description": "식품의약품안전처 보도자료·공지사항",
        "priority": 2,
    },
    "KHIDI_PHARMA_NEWS": {
        "label": "제약산업 뉴스 동향",
        "description": "KHIDI 제약산업정보포털 국내외 뉴스",
        "priority": 3,
    },
    "PMDA_REVIEW": {
        "label": "일본 PMDA 심사 동향",
        "description": "PMDA 승인심사 관련 RSS 업데이트",
        "priority": 8,
    },
    "PMDA_SAFETY": {
        "label": "일본 PMDA 안전성 정보",
        "description": "PMDA 안전성 관련 RSS + 보고서",
        "priority": 9,
    },
    "GNW_PRESS": {
        "label": "글로벌 제약·바이오 보도자료",
        "description": "GlobeNewsWire 제약·바이오 기업 발표 (승인, 임상, 파이프라인)",
        "priority": 1,
    },
}

# 발행 최소 기준
MIN_SIGNALS = {
    "PMDA_APPROVAL": 1,
    "NICE_TA": 3,
    "ASSEMBLY_BILL": 2,
    "MOHW_HEALTH_INSURANCE": 1,
    "MFDS_SAFETY_LETTER": 1,
    "DART_DISCLOSURE": 1,
    "KIPRIS_PATENT": 5,
    "MFDS_PRESS": 5,
    "KHIDI_PHARMA_NEWS": 5,
    "PMDA_REVIEW": 2,
    "PMDA_SAFETY": 2,
    "GNW_PRESS": 1,
}


def extract_signals(
    aux_data: dict[str, list],
) -> dict[str, list[dict[str, Any]]]:
    """소스별 시그널 추출. 빈 소스는 생략.

    Args:
        aux_data: Step 4.8 수집 결과 (키: 소스명 소문자, 값: 수집 데이터 list)

    Returns:
        {SOURCE_TYPE: [signal_dicts]} — 시그널 있는 소스만
    """
    result: dict[str, list[dict]] = {}

    # PMDA 승인
    _extract_pmda_approval(aux_data, result)
    # NICE HTA
    _extract_nice_ta(aux_data, result)
    # 국회 법안
    _extract_assembly(aux_data, result)
    # MOHW 건강보험
    _extract_mohw(aux_data, result)
    # MFDS 안전성
    _extract_mfds_safety(aux_data, result)
    # DART
    _extract_dart(aux_data, result)
    # KIPRIS
    _extract_kipris(aux_data, result)
    # MFDS 보도자료
    _extract_mfds_press(aux_data, result)
    # KHIDI 뉴스
    _extract_khidi_news(aux_data, result)
    # GlobeNewsWire
    _extract_gnw_press(aux_data, result)
    # PMDA RSS
    _extract_pmda_rss(aux_data, result)

    return result


def should_publish(source_type: str, signals: list[dict]) -> bool:
    """발행 기준: 최소 N건 이상."""
    min_count = MIN_SIGNALS.get(source_type, 1)
    return len(signals) >= min_count


def format_for_prompt(
    source_type: str,
    signals: list[dict],
) -> str:
    """LLM 프롬프트용 텍스트 포맷."""
    meta = SOURCE_META.get(source_type, {})
    label = meta.get("label", source_type)

    lines = [f"## {label}", f"총 {len(signals)}건", ""]
    for i, sig in enumerate(signals[:15], 1):
        title = sig.get("title", "")
        date = sig.get("date", "")
        detail = sig.get("detail", "")
        line = f"{i}. [{date}] {title}"
        if detail:
            line += f"\n   {detail[:150]}"

        # 법안 상세 (제안이유/주요내용/조문)
        if sig.get("statute_articles"):
            line += f"\n   [조문] {sig['statute_articles']}"
        if sig.get("proposal_reason"):
            line += f"\n   [제안이유] {sig['proposal_reason'][:300]}"
        if sig.get("main_content"):
            line += f"\n   [주요내용] {sig['main_content'][:500]}"
        if sig.get("related_bills_context"):
            line += f"\n   ⚠ [동일 법명 관련] {sig['related_bills_context']}"

        # 엔리칭 컨텍스트 (있으면 추가)
        for ctx_key in ("fda_context", "mfds_context"):
            ctx = sig.get(ctx_key, "")
            if ctx:
                for ctx_line in ctx.split("\n"):
                    line += f"\n   {ctx_line[:200]}"

        lines.append(line)

    if len(signals) > 15:
        lines.append(f"... +{len(signals) - 15}건 추가")

    return "\n".join(lines)


# ── 소스별 시그널 추출 ──


def _extract_pmda_approval(
    aux_data: dict, result: dict,
) -> None:
    data = aux_data.get("pmda_approval", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("ingredient", ""),
            "detail": f"{item.get('product_name', '')} — {item.get('indication', '')[:100]}",
            "date": item.get("date", ""),
            "area": item.get("area", ""),
            "company": item.get("company", ""),
        })
    if signals:
        result["PMDA_APPROVAL"] = signals


def _extract_nice_ta(aux_data: dict, result: dict) -> None:
    data = aux_data.get("nice_ta", [])
    if not data:
        return
    signals = []
    for item in data:
        technology = item.get("Technology", "") or item.get("title", "")
        indication = item.get("Indication", "")
        category = item.get("Categorisation (for specific recommendation)", "")
        ta_id = item.get("TA ID", "")
        comment = item.get("Comment", "")
        if not technology:
            continue
        signals.append({
            "title": f"{technology} ({ta_id})" if ta_id else technology,
            "detail": f"{indication} — {category}. {comment[:100]}" if indication else category,
            "date": item.get("Year of Publication", ""),
            "ref": ta_id,
            "category": category,
        })
    if signals:
        result["NICE_TA"] = signals


def _extract_assembly(aux_data: dict, result: dict) -> None:
    data = aux_data.get("assembly_bill", [])
    if not data:
        return
    signals = []
    for item in data:
        sig = {
            "title": item.get("title", ""),
            "detail": f"발의: {item.get('proposer', '')}",
            "date": item.get("date", ""),
            "status": item.get("proc_result", "") or "계류 중",
            "keyword": item.get("matched_keyword", ""),
            "url": item.get("url", ""),
        }
        # 법안 상세 (lawmake.kr에서 수집)
        if item.get("proposal_reason"):
            sig["proposal_reason"] = item["proposal_reason"][:1000]
        if item.get("main_content"):
            sig["main_content"] = item["main_content"][:1500]
        if item.get("statute_articles"):
            sig["statute_articles"] = item["statute_articles"]
        if item.get("related_bills_context"):
            sig["related_bills_context"] = item["related_bills_context"]
        signals.append(sig)
    if signals:
        result["ASSEMBLY_BILL"] = signals


def _extract_mohw(aux_data: dict, result: dict) -> None:
    data = aux_data.get("mohw_health_insurance", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("title", ""),
            "detail": f"담당: {item.get('department', '')}",
            "date": item.get("date", ""),
            "department": item.get("department", ""),
        })
    if signals:
        result["MOHW_HEALTH_INSURANCE"] = signals


def _extract_mfds_safety(aux_data: dict, result: dict) -> None:
    data = aux_data.get("mfds_safety_letter", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("title", ""),
            "detail": item.get("summary", "")[:150],
            "date": item.get("date", ""),
            "department": item.get("department", ""),
        })
    if signals:
        result["MFDS_SAFETY_LETTER"] = signals


def _extract_dart(aux_data: dict, result: dict) -> None:
    data = aux_data.get("dart_disclosure", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("title", ""),
            "detail": f"{item.get('corp_name', '')} — {item.get('matched_keyword', '')}",
            "date": item.get("date", ""),
            "corp_name": item.get("corp_name", ""),
        })
    if signals:
        result["DART_DISCLOSURE"] = signals


def _extract_kipris(aux_data: dict, result: dict) -> None:
    data = aux_data.get("kipris_patent", [])
    if not data:
        return
    # IPC 의약 관련만 필터
    pharma = [d for d in data if d.get("is_pharma_ipc")]
    signals = []
    for item in pharma[:20]:
        signals.append({
            "title": item.get("title", ""),
            "detail": f"출원인: {item.get('applicant', '')} | IPC: {item.get('ipc_code', '')[:15]}",
            "date": item.get("date", ""),
            "register_status": item.get("register_status", ""),
        })
    if signals:
        result["KIPRIS_PATENT"] = signals


def _extract_mfds_press(aux_data: dict, result: dict) -> None:
    data = aux_data.get("mfds_press", [])
    if not data:
        return
    signals = []
    for item in data:
        sig = {
            "title": item.get("title", ""),
            "detail": f"{item.get('department', '')} | {item.get('board', '')}",
            "date": item.get("date", ""),
        }
        if item.get("url"):
            sig["url"] = item["url"]
        signals.append(sig)
    if signals:
        result["MFDS_PRESS"] = signals


def _extract_khidi_news(aux_data: dict, result: dict) -> None:
    data = aux_data.get("khidi_pharma_news", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("title", ""),
            "detail": f"{item.get('news_source', '')} | {item.get('board', '')}",
            "date": item.get("date", ""),
            "url": item.get("url", ""),
        })
    if signals:
        result["KHIDI_PHARMA_NEWS"] = signals


def _extract_gnw_press(aux_data: dict, result: dict) -> None:
    data = aux_data.get("gnw_press", [])
    if not data:
        return
    signals = []
    for item in data:
        signals.append({
            "title": item.get("title", ""),
            "detail": item.get("description", "")[:300],
            "date": item.get("date", ""),
            "url": item.get("url", ""),
            "board": item.get("board", ""),
        })
    if signals:
        result["GNW_PRESS"] = signals


def _extract_pmda_rss(aux_data: dict, result: dict) -> None:
    # Review RSS
    review = aux_data.get("pmda_review", [])
    if review and len(review) >= 2:
        signals = [
            {
                "title": item.get("title", ""),
                "date": item.get("date", ""),
                "category": item.get("category", ""),
            }
            for item in review
        ]
        result["PMDA_REVIEW"] = signals

    # Safety RSS (HTML 테이블 제외, RSS만)
    safety = [
        item for item in aux_data.get("pmda_safety", [])
        if item.get("source_type") == "PMDA_SAFETY"
    ]
    if safety and len(safety) >= 2:
        signals = [
            {
                "title": item.get("title", ""),
                "date": item.get("date", ""),
            }
            for item in safety
        ]
        result["PMDA_SAFETY"] = signals
