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
# 1-B. openFDA 승인 이력 (Priority/Standard, 스폰서)
# ══════════════════════════════════════════════

async def fetch_fda_approval_history(inn: str) -> dict[str, Any]:
    """openFDA drug/drugsfda에서 승인 이력 조회.

    Returns:
        {
            "sponsor": "ROCHE",
            "approval_date": "2024-03-15",
            "review_type": "Priority",
            "application_number": "NDA215310",
        }
    """
    url = "https://api.fda.gov/drug/drugsfda.json"
    params: dict[str, Any] = {
        "search": f'openfda.generic_name:"{inn}"',
        "limit": 1,
    }
    if settings.FDA_API_KEY:
        params["api_key"] = settings.FDA_API_KEY

    result: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return result
            data = r.json()
            results = data.get("results", [])
            if not results:
                return result
            drug = results[0]

            result["sponsor"] = drug.get("sponsor_name", "")
            app_num = drug.get("application_number", "")
            result["application_number"] = app_num

            # 최신 submission에서 review type 추출
            submissions = drug.get("submissions", [])
            if submissions:
                latest = submissions[0]
                result["review_type"] = latest.get("review_priority", "")
                sub_date = latest.get("submission_status_date", "")
                if sub_date and len(sub_date) == 8:
                    result["approval_date"] = f"{sub_date[:4]}-{sub_date[4:6]}-{sub_date[6:8]}"

    except Exception as e:
        logger.debug("[Enrichment] FDA approval history 실패 (%s): %s", inn, e)

    return result


# ══════════════════════════════════════════════
# 1-C. MFDS 허가 상세 (효능효과/용법용량)
# ══════════════════════════════════════════════

async def fetch_mfds_permit_detail(drug_name: str) -> dict[str, str]:
    """MFDS 허가 상세 — 허가정보 목록에서 item_seq 확보 → 상세 조회.

    Args:
        drug_name: 약물명 (INN 영문 또는 한글 품목명)

    Returns:
        {"efficacy": "...", "dosage": "..."}
    """
    if not settings.DATA_GO_KR_API_KEY:
        return {}

    from urllib.parse import unquote
    raw_key = unquote(settings.DATA_GO_KR_API_KEY)

    # Step 1: 허가정보 목록에서 item_seq 확보
    list_url = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07"
    list_params = {
        "serviceKey": raw_key,
        "item_name": drug_name,
        "type": "json",
        "numOfRows": 1,
        "pageNo": 1,
    }

    result: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r1 = await client.get(list_url, params=list_params)
            if r1.status_code != 200:
                return result
            data1 = r1.json()
            body1 = data1.get("body", data1)
            items1 = body1.get("items", [])
            if not items1:
                return result
            first = items1[0] if isinstance(items1, list) else items1
            item_seq = first.get("ITEM_SEQ", "")
            if not item_seq:
                return result

            # Step 2: 상세 조회 (item_seq 기반) — DtlInq06이 정확한 오퍼레이션
            detail_url = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnDtlInq06"
            detail_params = {
                "serviceKey": raw_key,
                "item_seq": item_seq,
                "type": "json",
            }
            r2 = await client.get(detail_url, params=detail_params)
            if r2.status_code != 200:
                return result
            data2 = r2.json()
            body2 = data2.get("body", data2)
            items2 = body2.get("items", [])
            if not items2:
                return result
            item = items2[0] if isinstance(items2, list) else items2

            ee = item.get("EE_DOC_DATA", "")
            if ee:
                result["efficacy"] = _parse_mfds_doc(str(ee))[:500]
            ud = item.get("UD_DOC_DATA", "")
            if ud:
                result["dosage"] = _parse_mfds_doc(str(ud))[:500]

    except Exception as e:
        logger.debug("[Enrichment] MFDS 허가상세 실패 (%s): %s", drug_name, e)

    return result


# ══════════════════════════════════════════════
# 1-D. ClinicalTrials.gov NCT 상세
# ══════════════════════════════════════════════

async def fetch_clinical_trial(nct_id: str) -> dict[str, Any]:
    """ClinicalTrials.gov v2 API에서 임상시험 상세 조회.

    Returns:
        {
            "title": "...",
            "phase": "Phase 3",
            "status": "Recruiting",
            "enrollment": 1200,
            "primary_outcome": "Progression-free survival",
            "start_date": "2024-01",
            "completion_date": "2027-06",
        }
    """
    if not nct_id or not nct_id.startswith("NCT"):
        return {}

    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    params = {
        "fields": "NCTId,BriefTitle,Phase,OverallStatus,EnrollmentCount,"
                  "PrimaryOutcomeMeasure,StartDate,CompletionDate",
        "format": "json",
    }

    result: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return result
            data = r.json()

            proto = data.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design = proto.get("designModule", {})
            outcomes = proto.get("outcomesModule", {})

            result["title"] = ident.get("briefTitle", "")
            result["phase"] = (design.get("phases") or [""])[0] if design.get("phases") else ""
            result["status"] = status_mod.get("overallStatus", "")
            result["enrollment"] = design.get("enrollmentInfo", {}).get("count", 0)

            primary = outcomes.get("primaryOutcomes", [])
            if primary:
                result["primary_outcome"] = primary[0].get("measure", "")

            start = status_mod.get("startDateStruct", {})
            result["start_date"] = start.get("date", "")
            comp = status_mod.get("completionDateStruct", {})
            result["completion_date"] = comp.get("date", "")

    except Exception as e:
        logger.debug("[Enrichment] ClinicalTrials.gov 실패 (%s): %s", nct_id, e)

    return result


# ══════════════════════════════════════════════
# 1-E. HIRA 급여/약가 (SQLite DB 조회)
# ══════════════════════════════════════════════

async def fetch_hira_reimbursement(inn: str) -> dict[str, Any]:
    """HIRA 급여 상태 + 상한가 조회 (로컬 DB).

    Returns:
        {
            "status": "reimbursed" / "not_covered" / "not_found",
            "status_kr": "급여" / "비급여" / "미등재",
            "price_ceiling": 45652.0,
            "ingredient_code": "626103ATB",
        }
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(settings.BASE_DIR) / "data" / "regscan.db"
    if not db_path.exists():
        return {}

    result: dict[str, Any] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT hr.status, hr.price_ceiling, hr.ingredient_code
               FROM hira_reimbursements hr
               JOIN drugs d ON hr.drug_id = d.id
               WHERE UPPER(d.inn) = ?
               LIMIT 1""",
            (inn.upper(),),
        ).fetchone()
        conn.close()

        if row:
            status = row["status"]
            status_map = {
                "reimbursed": "급여",
                "not_covered": "비급여",
                "not_found": "미등재",
                "deleted": "삭제",
            }
            result["status"] = status
            result["status_kr"] = status_map.get(status, status)
            if row["price_ceiling"]:
                result["price_ceiling"] = row["price_ceiling"]
            if row["ingredient_code"]:
                result["ingredient_code"] = row["ingredient_code"]

    except Exception as e:
        logger.debug("[Enrichment] HIRA 조회 실패 (%s): %s", inn, e)

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

    from urllib.parse import unquote
    raw_key = unquote(settings.DATA_GO_KR_API_KEY)

    url = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
    params = {
        "serviceKey": raw_key,
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
                logger.debug("[Enrichment] e약은요 HTTP %d (%s)", r.status_code, drug_name)
                return result
            data = r.json()

            # 응답 구조: {header: {resultCode, ...}, body: {items: [...]}}
            # 또는 직접: {items: [...]}
            body = data.get("body", data)
            items = body.get("items", [])
            if not items:
                return result
            item = items[0] if isinstance(items, list) else items

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
        elif src_type == "KIPRIS_PATENT":
            enriched[src_type] = await _enrich_kipris_patent(sigs)
        elif src_type == "ASSEMBLY_BILL":
            enriched[src_type] = await _enrich_assembly_bill(sigs)
        elif src_type == "GNW_PRESS":
            enriched[src_type] = await _enrich_gnw_press(sigs)
        elif src_type in ("NICE_TA", "KHIDI_GLOBAL_INFO"):
            enriched[src_type] = await _enrich_global_with_domestic(sigs)
        else:
            enriched[src_type] = sigs

    return enriched


async def _enrich_drug_signals(
    sigs: list[dict],
) -> list[dict]:
    """약물명이 있는 시그널에 글로벌 심사 데이터 추가."""
    enriched = []
    seen_inns: set[str] = set()

    for sig in sigs:
        inn = sig.get("title", "").strip().upper()
        if not inn or inn in seen_inns:
            enriched.append(sig)
            continue
        seen_inns.add(inn)

        context_parts = []

        # FDA label (적응증/용법/임상/부작용)
        label = await fetch_fda_label_full(inn)
        if label:
            if label.get("indications"):
                context_parts.append(f"[FDA 적응증] {label['indications'][:300]}")
            if label.get("dosage"):
                context_parts.append(f"[FDA 용법] {label['dosage'][:200]}")
            if label.get("clinical_studies"):
                context_parts.append(f"[FDA 임상시험] {label['clinical_studies'][:500]}")
            if label.get("adverse_reactions"):
                context_parts.append(f"[FDA 부작용] {label['adverse_reactions'][:200]}")

        # FDA 승인 이력 (Priority/Standard)
        approval = await fetch_fda_approval_history(inn)
        if approval:
            parts = []
            if approval.get("review_type"):
                parts.append(f"심사유형: {approval['review_type']}")
            if approval.get("approval_date"):
                parts.append(f"승인일: {approval['approval_date']}")
            if approval.get("sponsor"):
                parts.append(f"스폰서: {approval['sponsor']}")
            if parts:
                context_parts.append(f"[FDA 승인이력] {', '.join(parts)}")

        # MFDS 허가 상세 (한글 효능효과/용법)
        mfds = await fetch_mfds_permit_detail(inn)
        if mfds:
            if mfds.get("efficacy"):
                context_parts.append(f"[식약처 효능효과] {mfds['efficacy'][:300]}")
            if mfds.get("dosage"):
                context_parts.append(f"[식약처 용법용량] {mfds['dosage'][:200]}")

        # HIRA 급여/약가
        hira = await fetch_hira_reimbursement(inn)
        if hira:
            hira_parts = [f"국내 급여상태: {hira.get('status_kr', '확인불가')}"]
            if hira.get("price_ceiling"):
                hira_parts.append(f"상한가: {hira['price_ceiling']:,.0f}원")
            context_parts.append(f"[국내 급여] {', '.join(hira_parts)}")

        if context_parts:
            sig["fda_context"] = "\n".join(context_parts)

        enriched.append(sig)

    return enriched


async def _enrich_assembly_bill(
    sigs: list[dict],
) -> list[dict]:
    """법안 시그널에 제안이유 크롤링 + LLM 3문장 요약 + 원문 링크."""
    enriched = []
    fetched = 0

    for sig in sigs:
        if fetched < 5:
            bill_url = sig.get("url", "")
            if bill_url:
                raw_reason = await fetch_bill_summary(bill_url)
                if raw_reason:
                    # LLM 3문장 요약
                    summary = await _summarize_bill_reason(raw_reason)
                    context = f"[제안이유 요약]\n{summary}" if summary else f"[제안이유 원문]\n{raw_reason[:800]}"
                    # 원문 링크 추가
                    context += f"\n[원문 링크] {bill_url}"
                    sig["fda_context"] = context
                    fetched += 1
                    logger.info("[Enrichment] 법안 요약: %s", sig.get("title", "")[:30])

        enriched.append(sig)

    return enriched


async def _summarize_bill_reason(raw_text: str) -> str:
    """제안이유를 기자가 쓸 수 있는 3문장으로 요약."""
    if not raw_text or len(raw_text) < 50:
        return ""

    prompt = f"""다음은 법률 개정안의 제안이유 및 주요내용입니다.
기자가 기사에 바로 쓸 수 있도록 정확히 3문장으로 요약하세요.

1문장: 현행법의 문제점 (왜 바꾸려는지)
2문장: 개정안의 핵심 변경 내용 (뭐가 바뀌는지, 조항 번호 포함)
3문장: 영향받는 대상/기관 (누가 영향받는지)

법률 용어는 일상어로 바꾸되, 조항 번호(안 제XX조)는 유지하세요.
3문장 외에 다른 말은 쓰지 마세요.

제안이유:
{raw_text[:2000]}"""

    try:
        if settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=getattr(settings, "LLM_MODEL", "gpt-5.2"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=300,
            )
            return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.debug("[Enrichment] 법안 요약 LLM 실패: %s", e)

    return ""


async def _enrich_gnw_press(
    sigs: list[dict],
) -> list[dict]:
    """GlobeNewsWire 보도자료 URL에서 본문 크롤링 (상위 5건)."""
    enriched = []
    fetched = 0

    for sig in sigs:
        if fetched < 5:
            url = sig.get("url", "")
            if url:
                body = await _fetch_gnw_body(url)
                if body:
                    sig["fda_context"] = f"[보도자료 본문]\n{body}"
                    fetched += 1

        enriched.append(sig)

    return enriched


async def _fetch_gnw_body(url: str) -> str:
    """GlobeNewsWire 보도자료 페이지에서 본문 추출."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return ""
            # 본문 영역 추출 (main-body 또는 article-body)
            body_match = re.search(
                r'<div[^>]*class="[^"]*(?:main-body|article-body|notified-body)[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</article)',
                r.text, re.DOTALL,
            )
            if not body_match:
                # fallback: <article> 태그
                body_match = re.search(r"<article[^>]*>(.*?)</article>", r.text, re.DOTALL)
            if not body_match:
                return ""
            raw = body_match.group(1)
            text = _clean_html(raw)
            return _truncate(text, 2000)
    except Exception as e:
        logger.debug("[Enrichment] GNW 본문 실패 (%s): %s", url[:50], e)
        return ""


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
# 5. 법안 상세 엔리칭 — 의안원문 제안이유/주요내용
# ══════════════════════════════════════════════

async def fetch_bill_summary(bill_url: str) -> str:
    """국회 의안정보시스템에서 제안이유 및 주요내용 크롤링.

    Playwright로 JS 렌더링 후 텍스트 추출.
    Playwright 미설치 시 빈 문자열 반환.
    """
    if not bill_url:
        return ""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.debug("[Enrichment] playwright 미설치, 법안 상세 스킵")
        return ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(bill_url, wait_until="networkidle", timeout=20000)

            # billInfo 탭 내용 대기
            await page.wait_for_timeout(2000)

            # 제안이유 및 주요내용 영역 추출
            content = await page.evaluate("""() => {
                // 의안 상세 영역에서 텍스트 추출
                const sect = document.querySelector('#tab_billInfo_sect');
                if (sect) return sect.innerText;
                // fallback: 전체 본문
                const body = document.querySelector('.contIn, .bill_detail, #content');
                return body ? body.innerText : '';
            }""")

            await browser.close()

            if not content:
                return ""

            # "제안이유" ~ 끝 추출
            import re
            match = re.search(r"제안이유(.*?)(?:부\s*칙|법제사법위원회|$)", content, re.DOTALL)
            if match:
                text = match.group(1).strip()
                return _truncate(text, 1500)

            return _truncate(content, 1500)

    except Exception as e:
        logger.debug("[Enrichment] 법안 상세 크롤링 실패 (%s): %s", bill_url, e)
        return ""


# ══════════════════════════════════════════════
# 6. KIPRIS 특허 엔리칭 — 타겟/약물 키워드 → FDA label
# ══════════════════════════════════════════════

# 특허 제목에서 감지할 키워드 → 대표 약물 INN 매핑
_PATENT_KEYWORD_TO_INN = {
    "PD-1": "PEMBROLIZUMAB",
    "PD-L1": "ATEZOLIZUMAB",
    "HER2": "TRASTUZUMAB",
    "CD137": "NIVOLUMAB",
    "EGFR": "OSIMERTINIB",
    "BRCA": "OLAPARIB",
    "VEGF": "BEVACIZUMAB",
    "ALK": "ALECTINIB",
    "BTK": "IBRUTINIB",
    "FLT3": "QUIZARTINIB",
    "BCR-ABL": "IMATINIB",
    "JAK": "RUXOLITINIB",
    "BRAF": "VEMURAFENIB",
    "CDK4": "PALBOCICLIB",
    "CDK6": "PALBOCICLIB",
    "PARP": "OLAPARIB",
    "PI3K": "ALPELISIB",
    "mTOR": "EVEROLIMUS",
    "CAR-T": "TISAGENLECLEUCEL",
    "ADC": "TRASTUZUMAB DERUXTECAN",
    "BTN3A": "PEMBROLIZUMAB",  # 가장 가까운 면역항암
}


async def _enrich_kipris_patent(
    sigs: list[dict],
) -> list[dict]:
    """특허 제목에서 타겟 키워드 감지 → 대표 약물 FDA label 조회."""
    enriched = []
    seen_inns: set[str] = set()

    for sig in sigs:
        title = sig.get("title", "").upper()

        # 키워드 매칭
        matched_inn = None
        for keyword, inn in _PATENT_KEYWORD_TO_INN.items():
            if keyword.upper() in title or keyword in sig.get("title", ""):
                matched_inn = inn
                break

        if matched_inn and matched_inn not in seen_inns:
            seen_inns.add(matched_inn)
            context_parts = [f"[참조 약물: {matched_inn}]"]

            # FDA label
            label = await fetch_fda_label_full(matched_inn)
            if label:
                if label.get("indications"):
                    context_parts.append(f"[적응증] {label['indications'][:300]}")
                if label.get("clinical_studies"):
                    context_parts.append(f"[임상시험] {label['clinical_studies'][:400]}")

            # FDA 승인 이력
            approval = await fetch_fda_approval_history(matched_inn)
            if approval and approval.get("review_type"):
                context_parts.append(
                    f"[FDA 승인] {approval.get('review_type', '')}, "
                    f"{approval.get('approval_date', '')}, "
                    f"스폰서: {approval.get('sponsor', '')}"
                )

            # NCT 번호가 clinical_studies에 있으면 상세 조회
            clinical_text = label.get("clinical_studies", "") if label else ""
            nct_match = re.search(r"(NCT\d{8})", clinical_text)
            if nct_match:
                trial = await fetch_clinical_trial(nct_match.group(1))
                if trial:
                    trial_parts = [f"[임상 상세: {nct_match.group(1)}]"]
                    if trial.get("phase"):
                        trial_parts.append(f"Phase: {trial['phase']}")
                    if trial.get("enrollment"):
                        trial_parts.append(f"참여자: {trial['enrollment']}명")
                    if trial.get("primary_outcome"):
                        trial_parts.append(f"주요 평가변수: {trial['primary_outcome']}")
                    if trial.get("status"):
                        trial_parts.append(f"상태: {trial['status']}")
                    context_parts.append(" | ".join(trial_parts))

            if len(context_parts) > 1:
                sig["fda_context"] = "\n".join(context_parts)

        enriched.append(sig)

    return enriched


# ══════════════════════════════════════════════
# 7. 글로벌 시그널 → 국내 크로스레퍼런스
# ══════════════════════════════════════════════

# 글로벌 기사에 자주 등장하는 약물 INN → 한글 품목명 매핑
_INN_TO_KR_NAME: dict[str, list[str]] = {
    "PEMBROLIZUMAB": ["키트루다", "펨브롤리주맙"],
    "NIVOLUMAB": ["옵디보", "니볼루맙"],
    "ATEZOLIZUMAB": ["티쎈트릭", "아테졸리주맙"],
    "TRASTUZUMAB": ["허셉틴", "트라스투주맙"],
    "TRASTUZUMAB DERUXTECAN": ["엔허투", "트라스투주맙 데룩스테칸"],
    "BEVACIZUMAB": ["아바스틴", "베바시주맙"],
    "OLAPARIB": ["린파자", "올라파립"],
    "OSIMERTINIB": ["타그리소", "오시머티닙"],
    "IBRUTINIB": ["임브루비카", "이브루티닙"],
    "RUXOLITINIB": ["자카피", "룩소리티닙"],
    "PALBOCICLIB": ["입랜스", "팔보시클립"],
    "LENVATINIB": ["렌비마", "렌바티닙"],
    "DURVALUMAB": ["임핀지", "더발루맙"],
    "SEMAGLUTIDE": ["오젬픽", "위고비", "세마글루타이드"],
    "OMALIZUMAB": ["졸레어", "오말리주맙"],
    "REMIBRUTINIB": ["레미브루티닙"],
    "GEFAPIXANT": ["게파픽산트"],
    "MELPHALAN FLUFENAMIDE": ["멜팔란 플루페나마이드"],
    "TISAGENLECLEUCEL": ["킴리아", "티사젠렉류셀"],
}


def _extract_inns_from_text(text: str) -> list[str]:
    """텍스트에서 알려진 약물 INN 추출."""
    text_upper = text.upper()
    found = []
    for inn in _INN_TO_KR_NAME:
        if inn in text_upper:
            found.append(inn)
    return found


async def _enrich_global_with_domestic(
    sigs: list[dict],
) -> list[dict]:
    """글로벌 시그널(NICE, KHIDI 등)에서 약물명 감지 → 국내 허가/급여/임상 데이터 추가."""
    enriched = []
    seen_inns: set[str] = set()

    for sig in sigs:
        title = sig.get("title", "")
        desc = sig.get("description", sig.get("summary", ""))
        full_text = f"{title} {desc}"

        inns = _extract_inns_from_text(full_text)
        domestic_parts = []

        for inn in inns:
            if inn in seen_inns:
                continue
            seen_inns.add(inn)

            kr_names = _INN_TO_KR_NAME.get(inn, [])
            kr_label = f" ({'/'.join(kr_names)})" if kr_names else ""

            # 1. MFDS 허가 확인
            mfds = await fetch_mfds_permit_detail(inn)
            if not mfds and kr_names:
                # 한글 품목명으로 재시도
                for kr in kr_names:
                    mfds = await fetch_mfds_permit_detail(kr)
                    if mfds:
                        break

            if mfds:
                parts = [f"[국내 허가: {inn}{kr_label}]"]
                if mfds.get("efficacy"):
                    parts.append(f"효능: {mfds['efficacy'][:200]}")
                if mfds.get("dosage"):
                    parts.append(f"용법: {mfds['dosage'][:150]}")
                domestic_parts.append(" | ".join(parts))
            else:
                domestic_parts.append(f"[국내 허가: {inn}{kr_label}] 식약처 허가정보 미확인")

            # 2. HIRA 급여 확인
            hira = await fetch_hira_reimbursement(inn)
            if hira and hira.get("status"):
                hira_info = f"[국내 급여: {inn}] {hira.get('status_kr', '확인불가')}"
                if hira.get("price_ceiling"):
                    hira_info += f", 상한가 {hira['price_ceiling']:,.0f}원"
                domestic_parts.append(hira_info)
            else:
                domestic_parts.append(f"[국내 급여: {inn}] HIRA 등재정보 미확인 — 미등재 가능성")

            # 3. 국내 임상시험 확인 (ClinicalTrials.gov에서 한국 사이트)
            kr_trial = await _fetch_kr_clinical_trials(inn)
            if kr_trial:
                domestic_parts.append(kr_trial)

        if domestic_parts:
            existing = sig.get("fda_context", "")
            kr_context = "\n".join(domestic_parts)
            sig["fda_context"] = f"{existing}\n\n[국내 크로스레퍼런스]\n{kr_context}" if existing else f"[국내 크로스레퍼런스]\n{kr_context}"

        enriched.append(sig)

    return enriched


async def _fetch_kr_clinical_trials(inn: str) -> str:
    """ClinicalTrials.gov에서 한국 사이트 임상시험 검색."""
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.intr": inn,
        "query.locn": "Korea",
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION",
        "pageSize": 3,
        "format": "json",
        "fields": "NCTId,BriefTitle,Phase,OverallStatus,EnrollmentCount",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return ""
            data = r.json()
            studies = data.get("studies", [])
            if not studies:
                return ""

            parts = [f"[국내 임상시험: {inn}] {len(studies)}건 진행 중"]
            for s in studies[:3]:
                proto = s.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status = proto.get("statusModule", {})
                design = proto.get("designModule", {})
                nct = ident.get("nctId", "")
                title = ident.get("briefTitle", "")[:60]
                phase = (design.get("phases") or [""])[0] if design.get("phases") else ""
                overall = status.get("overallStatus", "")
                parts.append(f"  - {nct} {phase} ({overall}): {title}")

            return "\n".join(parts)

    except Exception as e:
        logger.debug("[Enrichment] 국내 임상 검색 실패 (%s): %s", inn, e)
        return ""


# ══════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _parse_mfds_doc(xml_text: str) -> str:
    """MFDS DOC XML (CDATA 포함) → 평문 추출."""
    # CDATA 내용 추출
    import re
    cdata = re.findall(r"<!\[CDATA\[(.*?)\]\]>", xml_text, re.DOTALL)
    if cdata:
        text = "\n".join(cdata)
    else:
        text = xml_text
    # XML/HTML 태그 제거
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_html(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
