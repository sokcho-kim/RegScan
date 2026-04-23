"""기사 데이터 엔리칭 — 시그널에 취재 컨텍스트 추가

시그널(제목+날짜)만으로는 기사를 못 쓴다.
이 모듈이 공공 API를 호출해서 약물별 맥락 데이터를 붙여준다.

소스:
  1. openFDA drug/label — 적응증, 용법, 부작용, 임상시험 결과
  2. 식약처 e약은요 — 한글 효능/용법/부작용 평문
  3. openFDA drug/event (FAERS) — 부작용 보고 통계
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from regscan.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


# ══════════════════════════════════════════════
# 1. openFDA drug/label — 확장 필드
# ══════════════════════════════════════════════

async def fetch_fda_label_full(inn: str) -> dict[str, str]:
    """openFDA drug/label에서 기사용 필드 전체 가져오기.

    Returns:
        {
            "indications": "...",
            "dosage": "...",
            "adverse_reactions": "...",
            "clinical_studies": "...",
            "boxed_warning": "...",
        }
    """
    url = "https://api.fda.gov/drug/label.json"
    params = {
        "search": f'openfda.generic_name:"{inn}"',
        "limit": 1,
    }
    if settings.FDA_API_KEY:
        params["api_key"] = settings.FDA_API_KEY

    result: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return result
            data = r.json()
            results = data.get("results", [])
            if not results:
                return result
            label = results[0]

            field_map = {
                "indications": "indications_and_usage",
                "dosage": "dosage_and_administration",
                "adverse_reactions": "adverse_reactions",
                "clinical_studies": "clinical_studies",
                "boxed_warning": "boxed_warning",
            }
            for key, fda_key in field_map.items():
                val = label.get(fda_key, [])
                if val:
                    text = val[0] if isinstance(val, list) else str(val)
                    result[key] = _truncate(text, 1000)

    except Exception as e:
        logger.debug("[Enrichment] FDA label 실패 (%s): %s", inn, e)

    return result


# ══════════════════════════════════════════════
# 2. 식약처 e약은요 — 한글 효능/용법/부작용
# ══════════════════════════════════════════════

async def fetch_easy_drug_info(drug_name: str) -> dict[str, str]:
    """식약처 e약은요 API에서 한글 의약품 정보 가져오기.

    Args:
        drug_name: 품목명 또는 성분명 (한글/영문)

    Returns:
        {
            "item_name": "타이레놀정500밀리그램",
            "efcy_qesitm": "효능",
            "use_method_qesitm": "용법",
            "atpn_warn_qesitm": "주의사항 경고",
            "se_qesitm": "부작용",
        }
    """
    if not settings.DATA_GO_KR_API_KEY:
        return {}

    url = "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
    params = {
        "serviceKey": settings.DATA_GO_KR_API_KEY,
        "itemName": drug_name,
        "type": "json",
        "numOfRows": 1,
        "pageNo": 1,
    }

    result: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return result
            data = r.json()
            items = (
                data.get("body", {}).get("items", [])
                or []
            )
            if not items:
                return result
            item = items[0]

            field_map = {
                "item_name": "itemName",
                "efcy_qesitm": "efcyQesitm",
                "use_method_qesitm": "useMethodQesitm",
                "atpn_warn_qesitm": "atpnWarnQesitm",
                "se_qesitm": "seQesitm",
            }
            for key, api_key in field_map.items():
                val = item.get(api_key, "")
                if val:
                    result[key] = _clean_html(str(val))

    except Exception as e:
        logger.debug("[Enrichment] e약은요 실패 (%s): %s", drug_name, e)

    return result


# ══════════════════════════════════════════════
# 3. openFDA drug/event (FAERS) — 부작용 통계
# ══════════════════════════════════════════════

async def fetch_faers_summary(inn: str) -> dict[str, Any]:
    """openFDA FAERS에서 부작용 보고 통계 가져오기.

    Returns:
        {
            "total_reports": 45000,
            "serious_count": 12000,
            "death_count": 500,
            "top_reactions": ["nausea", "fatigue", "diarrhoea"],
        }
    """
    url = "https://api.fda.gov/drug/event.json"
    params: dict[str, Any] = {
        "search": f'patient.drug.openfda.generic_name:"{inn}"',
        "count": "patient.reaction.reactionmeddrapt.exact",
        "limit": 5,
    }
    if settings.FDA_API_KEY:
        params["api_key"] = settings.FDA_API_KEY

    result: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Top reactions
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                reactions = data.get("results", [])
                result["top_reactions"] = [
                    r["term"] for r in reactions[:5]
                ]

            # Total count + serious
            count_params: dict[str, Any] = {
                "search": f'patient.drug.openfda.generic_name:"{inn}"',
                "limit": 1,
            }
            if settings.FDA_API_KEY:
                count_params["api_key"] = settings.FDA_API_KEY

            r2 = await client.get(url, params=count_params)
            if r2.status_code == 200:
                data2 = r2.json()
                meta = data2.get("meta", {}).get("results", {})
                result["total_reports"] = meta.get("total", 0)

            # Serious outcomes
            serious_params: dict[str, Any] = {
                "search": f'patient.drug.openfda.generic_name:"{inn}"+AND+serious:1',
                "limit": 1,
            }
            if settings.FDA_API_KEY:
                serious_params["api_key"] = settings.FDA_API_KEY

            r3 = await client.get(url, params=serious_params)
            if r3.status_code == 200:
                data3 = r3.json()
                meta3 = data3.get("meta", {}).get("results", {})
                result["serious_count"] = meta3.get("total", 0)

    except Exception as e:
        logger.debug("[Enrichment] FAERS 실패 (%s): %s", inn, e)

    return result


# ══════════════════════════════════════════════
# 4. 통합 엔리칭 — 시그널에 컨텍스트 추가
# ══════════════════════════════════════════════

async def enrich_signals(
    signals: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """시그널에 API 데이터를 붙여서 반환.

    약물명이 있는 시그널(PMDA, MFDS 등)은 openFDA/e약은요로 보강.
    법안/특허 등 약물 무관 시그널은 그대로 통과.
    """
    enriched = {}

    for src_type, sigs in signals.items():
        if src_type in ("PMDA_APPROVAL", "MFDS_SAFETY_LETTER"):
            enriched[src_type] = await _enrich_drug_signals(sigs)
        elif src_type == "MFDS_PRESS":
            enriched[src_type] = await _enrich_mfds_press(sigs)
        else:
            enriched[src_type] = sigs

    return enriched


async def _enrich_drug_signals(
    sigs: list[dict],
) -> list[dict]:
    """약물명이 있는 시그널에 FDA label + e약은요 데이터 추가."""
    enriched = []
    seen_inns: set[str] = set()

    for sig in sigs:
        inn = sig.get("title", "").strip().upper()
        if not inn or inn in seen_inns:
            enriched.append(sig)
            continue
        seen_inns.add(inn)

        # FDA label
        label = await fetch_fda_label_full(inn)
        if label:
            context_parts = []
            if label.get("indications"):
                context_parts.append(f"[적응증] {label['indications'][:300]}")
            if label.get("dosage"):
                context_parts.append(f"[용법] {label['dosage'][:200]}")
            if label.get("clinical_studies"):
                context_parts.append(f"[임상시험] {label['clinical_studies'][:500]}")
            if label.get("adverse_reactions"):
                context_parts.append(f"[부작용] {label['adverse_reactions'][:200]}")
            if context_parts:
                sig["fda_context"] = "\n".join(context_parts)

        enriched.append(sig)

    return enriched


async def _enrich_mfds_press(
    sigs: list[dict],
) -> list[dict]:
    """식약처 보도자료에서 약물명 추출 → e약은요로 보강."""
    enriched = []
    for sig in sigs:
        title = sig.get("title", "")
        # 허가/승인 관련 보도자료에서 약물명 추출 시도
        drug_match = re.search(r"['\"]([가-힣A-Za-z]+(?:정|캡슐|주|주사)[^'\"]*)['\"]", title)
        if drug_match:
            drug_name = drug_match.group(1)
            easy_info = await fetch_easy_drug_info(drug_name)
            if easy_info:
                context_parts = []
                if easy_info.get("efcy_qesitm"):
                    context_parts.append(f"[효능] {easy_info['efcy_qesitm'][:300]}")
                if easy_info.get("use_method_qesitm"):
                    context_parts.append(f"[용법] {easy_info['use_method_qesitm'][:200]}")
                if easy_info.get("se_qesitm"):
                    context_parts.append(f"[부작용] {easy_info['se_qesitm'][:200]}")
                if context_parts:
                    sig["mfds_context"] = "\n".join(context_parts)

        enriched.append(sig)

    return enriched


# ══════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _clean_html(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
