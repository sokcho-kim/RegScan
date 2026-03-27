"""Stream Briefing Generator V3 — 시간추론 규칙 + few-shot + 풍부한 인텔리전스

V3 개선 (V2 대비):
  - SYSTEM_PROMPT 템플릿화: {today} 주입 + 시간추론 규칙 + GOOD/BAD 예시
  - 스트림 프롬프트: 날짜 명시, why_it_matters 4관점 가이드, key_takeaway 필수
  - _extract_drug_intel max_fields 8→14 (clinical_results, mfds_data, therapeutic_areas)
  - 통합 브리핑: 스트림 브리핑 JSON 직접 주입 + 4000자 truncation
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from regscan.config import settings
from regscan.stream.base import StreamResult

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────
# 시스템 프롬프트 (공통)
# ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 제약·바이오 산업의 규제 인텔리전스 전문 분석가이며,
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

[TASK]
위 데이터를 기반으로 {area_ko} 치료영역 주간 Executive Briefing을 작성하라.
시간 추론 규칙을 반드시 준수하라 (승인일 vs 오늘 날짜 비교).

출력 JSON:
{{
  "headline": "40자 이내 BLUF 헤드라인 — 이번 주 가장 중요한 한 가지",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "top_drugs": [
    {{
      "inn": "약물명",
      "status": "FDA/EMA 승인 현황 1줄 (과거/미래 시제 정확히)",
      "why_it_matters": "4관점으로 분석: (a)경쟁구도 — 기존 약물 대비 포지셔닝, (b)급여/가격 — 약가·급여 등재 영향, (c)환자규모 — 국내 대상 환자 수, (d)처방변화 — 기존 처방 패턴에 미치는 영향. 최소 2개 관점 포함, 구체적 수치 활용."
    }}
  ],
  "trend_analysis": "이번 수집에서 드러난 치료영역 트렌드 (3-5줄, 숫자 기반)",
  "action_items": [
    "약제팀이 이번 주 해야 할 구체적 행동 1",
    "약제팀이 이번 주 해야 할 구체적 행동 2"
  ]
}}"""

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

[TASK]
위 데이터를 기반으로 혁신 시그널 Executive Briefing을 작성하라.
NME, PRIME, 희귀의약품 등 규제 지정이 병원 약물 도입에 미치는 영향에 초점.
시간 추론 규칙을 반드시 준수하라 (승인일 vs 오늘 날짜 비교).

출력 JSON:
{{
  "headline": "40자 이내 BLUF — 이번 주 혁신 시그널의 핵심",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "nme_spotlight": [
    {{
      "inn": "약물명",
      "designation": "NME/PRIME/orphan 등",
      "implication": "3관점 분석: (a)기존 치료 대비 혁신성 — MOA/효능 차별점, (b)도입 시점 — 허가/급여 일정 기반 예상 시기, (c)경쟁약물 대비 포지셔닝. 최소 2개 관점 포함."
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

[TASK]
위 데이터를 기반으로 외부시그널 Future Trend Report를 작성하라.
임상실패 약물이 현재 병원 처방에 미치는 즉각적 영향과, medRxiv 논문이 시사하는 미래 변화에 초점.
시간 추론 규칙을 반드시 준수하라 (승인일 vs 오늘 날짜 비교).

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

[TASK]
3개 스트림을 종합한 오늘의 RegScan Executive Daily Briefing을 작성하라.
경영진이 30초 만에 핵심을 파악할 수 있는 BLUF 톤.
시간 추론 규칙을 반드시 준수하라 (승인일 vs 오늘 날짜 비교).

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


# ────────────────────────────────────────────────────────
# Generator
# ────────────────────────────────────────────────────────

class StreamBriefingGenerator:
    """스트림별 + 통합 브리핑 생성기 (V3: 시간추론 + few-shot + 풍부한 인텔리전스)"""

    # ── 약물 인텔리전스 추출 헬퍼 ──

    @staticmethod
    def _extract_drug_intel(drug: dict, max_fields: int = 14) -> dict:
        """drugs_found 항목에서 브리핑에 필요한 핵심 정보 추출"""
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

    # ── 스트림별 브리핑 생성 ──

    async def generate_therapeutic_briefing(
        self,
        area: str,
        area_ko: str,
        result: StreamResult,
    ) -> dict[str, Any]:
        """치료영역 Executive Briefing"""
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
        """통합 Executive Daily Briefing — V3: 스트림 브리핑 JSON 직접 주입"""
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

    def _fallback_therapeutic(self, area: str, area_ko: str, result: StreamResult) -> dict:
        """LLM 실패 시 구조화 데이터 기반 브리핑"""
        return {
            "headline": f"{area_ko} 치료영역 브리핑",
            "drug_count": result.drug_count,
            "top_drugs": [{"inn": inn} for inn in result.inn_list[:10]],
            "errors": result.errors,
        }

    # ── LLM 호출 ──

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출 — 시스템 프롬프트에 today 주입 + 사용자 프롬프트 분리"""
        today = datetime.now().strftime("%Y-%m-%d")
        system_prompt = SYSTEM_PROMPT.format(today=today)

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
                    max_completion_tokens=2500,
                    temperature=0.3,
                )
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
                    max_tokens=2500,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
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
