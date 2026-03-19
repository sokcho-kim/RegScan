"""Stream Briefing Generator V2 — Executive Tone + 약물 인텔리전스 주입

V1 대비 개선:
  - 프롬프트에 약물별 승인 현황/지정/MOA 등 팩트 데이터 주입
  - V4.1 Executive Tone (BLUF, So What, 기사체)
  - 모델 업그레이드 (gpt-5.2 / gemini-2.5-flash)
  - max_tokens 2500
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

## 원칙
1. **BLUF**: 첫 문장에서 "그래서 뭐?"에 대한 답을 제시하라.
2. **Fact/Insight 분리**: 아래 [FACT DATA]는 검증된 사실이다. LLM이 할 일은 사실을 기반으로 인사이트와 시사점을 도출하는 것이다.
3. **기사체**: 병원장이 출근길 1분 만에 읽는 톤. 짧은 문장(40자 이내), 능동태, 전문용어 최소화.
4. **숫자는 구체적으로**: "많은" 대신 "17건", "최근" 대신 "2026-03-17 기준".
5. **행동 지향**: 각 섹션 끝에 "So What" — 약제팀이 내일 할 일을 명시.
6. **허위 생성 금지**: [FACT DATA]에 없는 승인일, 점수, 임상 결과를 절대 만들지 마라.

## 출력
- 반드시 순수 JSON만 출력 (코드블록/마크다운 금지).
- 한글로 작성."""

# ────────────────────────────────────────────────────────
# 치료영역 브리핑 프롬프트
# ────────────────────────────────────────────────────────

THERAPEUTIC_BRIEFING_PROMPT = """[FACT DATA]
치료영역: {area_ko} ({area})
수집일: {date}
총 수집 약물: {drug_count}건

## 주요 약물 상세 (상위 {top_n}건)
{drug_details}

## 수집 에러
{errors}

[TASK]
위 데이터를 기반으로 {area_ko} 치료영역 주간 Executive Briefing을 작성하라.

출력 JSON:
{{
  "headline": "40자 이내 BLUF 헤드라인 — 이번 주 가장 중요한 한 가지",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장",
  "top_drugs": [
    {{
      "inn": "약물명",
      "status": "FDA/EMA 승인 현황 1줄",
      "why_it_matters": "병원 관점에서 왜 중요한지 2줄"
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
수집일: {date}
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

출력 JSON:
{{
  "headline": "40자 이내 BLUF — 이번 주 혁신 시그널의 핵심",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장",
  "nme_spotlight": [
    {{
      "inn": "약물명",
      "designation": "NME/PRIME/orphan 등",
      "implication": "병원 도입 관점 시사점 2줄"
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
수집일: {date}
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

출력 JSON:
{{
  "headline": "40자 이내 BLUF — 이번 주 외부시그널 핵심",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장",
  "trial_failures": [
    {{
      "inn": "약물명",
      "verdict": "FAIL 사유 1줄",
      "hospital_impact": "병원 처방/재고에 미치는 영향"
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
날짜: {date}

## 치료영역 스트림 요약
{therapeutic_summary}

## 혁신지표 스트림 요약
{innovation_summary}

## 외부시그널 스트림 요약
{external_summary}

## 스트림별 Top 약물
{cross_stream_drugs}

[TASK]
3개 스트림을 종합한 오늘의 RegScan Executive Daily Briefing을 작성하라.
경영진이 30초 만에 핵심을 파악할 수 있는 BLUF 톤.
스트림 간 교차 분석 — 같은 약물이 여러 스트림에 등장하면 신호가 강하다는 의미.

출력 JSON:
{{
  "headline": "50자 이내 — 오늘의 RegScan 한 줄 요약",
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
    """스트림별 + 통합 브리핑 생성기 (V2: Executive Tone + 약물 인텔리전스)"""

    # ── 약물 인텔리전스 추출 헬퍼 ──

    @staticmethod
    def _extract_drug_intel(drug: dict, max_fields: int = 8) -> dict:
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
        """통합 Executive Daily Briefing"""
        therapeutic_summary = self._rich_summarize(
            all_results.get("therapeutic_area", []), stream_briefings, "therapeutic",
        )
        innovation_summary = self._rich_summarize(
            all_results.get("innovation", []), stream_briefings, "innovation",
        )
        external_summary = self._rich_summarize(
            all_results.get("external", []), stream_briefings, "external",
        )

        # 스트림 간 교차 약물 추출
        cross_drugs = self._find_cross_stream_drugs(all_results)

        prompt = UNIFIED_BRIEFING_PROMPT.format(
            date=datetime.now().strftime("%Y-%m-%d"),
            therapeutic_summary=therapeutic_summary,
            innovation_summary=innovation_summary,
            external_summary=external_summary,
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
        """LLM 호출 — 시스템 프롬프트 + 사용자 프롬프트 분리, 고품질 모델 사용"""

        # 1차: OpenAI (gpt-5.2 — V4.1 검증 완료 모델)
        if settings.OPENAI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                response = await client.chat.completions.create(
                    model=settings.WRITER_MODEL,  # gpt-5.2
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=2500,
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
                full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{prompt}"
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
                    system=SYSTEM_PROMPT,
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
