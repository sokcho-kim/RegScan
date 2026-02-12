"""Stream Briefing Generator — 스트림별 + 통합 브리핑

각 스트림이 독립적으로 브리핑 생성, 마지막에 통합 데일리 브리핑.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from regscan.config import settings
from regscan.stream.base import StreamResult

logger = logging.getLogger(__name__)


# ── LLM 프롬프트 ──

THERAPEUTIC_BRIEFING_PROMPT = """당신은 의약품 규제 전문 분석가입니다.
다음 치료영역({area}) 수집 결과를 분석하여 주간 브리핑을 생성하세요.

수집된 약물 수: {drug_count}
주요 약물 INN 목록: {inn_list}
에러: {errors}

다음 JSON 형식으로 출력하세요:
{{
  "headline": "주간 {area_ko} 치료영역 브리핑",
  "highlights": ["핵심 포인트 1", "핵심 포인트 2", ...],
  "top_drugs": [
    {{"inn": "약물명", "reason": "주목 이유"}},
    ...
  ],
  "trends": "전반적 트렌드 분석 (2-3문장)",
  "action_items": ["후속 조치 1", ...]
}}
"""

INNOVATION_BRIEFING_PROMPT = """당신은 의약품 혁신 전문 분석가입니다.
다음 혁신지표 수집 결과를 분석하여 브리핑을 생성하세요.

수집된 약물 수: {drug_count}
시그널: {signals}

다음 JSON 형식으로 출력하세요:
{{
  "headline": "혁신 시그널 브리핑",
  "nme_highlights": ["신규 NME 관련 핵심 포인트"],
  "breakthrough_highlights": ["혁신 치료제 관련 핵심"],
  "pdufa_alerts": ["PDUFA D-Day 알림"],
  "implications": "전략적 시사점 (2-3문장)"
}}
"""

EXTERNAL_BRIEFING_PROMPT = """당신은 임상시험 및 의학 문헌 전문 분석가입니다.
다음 외부시그널 수집 결과를 분석하여 미래 트렌드 리포트를 생성하세요.

수집된 약물 수: {drug_count}
시그널 요약:
  - 임상실패: {fail_count}건
  - 결과대기: {pending_count}건
  - AI판독대기: {needs_ai_count}건
  - medRxiv 논문: {medrxiv_count}건

시그널 상세: {signals}

다음 JSON 형식으로 출력하세요:
{{
  "headline": "미래 트렌드 리포트",
  "trial_failures": ["주요 임상실패 분석"],
  "watch_list": ["주시 대상 약물"],
  "medrxiv_insights": ["medRxiv 논문 인사이트"],
  "outlook": "향후 전망 (2-3문장)"
}}
"""

UNIFIED_BRIEFING_PROMPT = """당신은 의약품 규제 인텔리전스 총괄 분석가입니다.
3개 스트림의 결과를 종합하여 통합 데일리 브리핑을 생성하세요.

[치료영역 스트림]
{therapeutic_summary}

[혁신지표 스트림]
{innovation_summary}

[외부시그널 스트림]
{external_summary}

다음 JSON 형식으로 출력하세요:
{{
  "headline": "RegScan 데일리 브리핑",
  "date": "{date}",
  "executive_summary": "핵심 요약 (3-5줄)",
  "cross_analysis": "스트림 간 교차 분석 (3-5줄)",
  "top_5_drugs": [
    {{"rank": 1, "inn": "약물명", "reason": "선정 이유", "streams": ["therapeutic_area", "innovation"]}},
    ...
  ],
  "risk_alerts": ["리스크 알림"],
  "opportunities": ["기회 요인"]
}}
"""


class StreamBriefingGenerator:
    """스트림별 + 통합 브리핑 생성기"""

    async def generate_therapeutic_briefing(
        self,
        area: str,
        area_ko: str,
        result: StreamResult,
    ) -> dict[str, Any]:
        """치료영역 주간 브리핑"""
        prompt = THERAPEUTIC_BRIEFING_PROMPT.format(
            area=area,
            area_ko=area_ko,
            drug_count=result.drug_count,
            inn_list=", ".join(result.inn_list[:30]),
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
        """혁신 시그널 브리핑"""
        prompt = INNOVATION_BRIEFING_PROMPT.format(
            drug_count=result.drug_count,
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
        """외부시그널 미래 트렌드 리포트"""
        fail_count = sum(1 for s in result.signals if s.get("verdict") == "FAIL")
        pending_count = sum(1 for s in result.signals if s.get("verdict") == "PENDING")
        needs_ai_count = sum(1 for s in result.signals if s.get("verdict") == "NEEDS_AI")
        medrxiv_count = sum(1 for s in result.signals if s.get("type") == "medrxiv_paper")

        prompt = EXTERNAL_BRIEFING_PROMPT.format(
            drug_count=result.drug_count,
            fail_count=fail_count,
            pending_count=pending_count,
            needs_ai_count=needs_ai_count,
            medrxiv_count=medrxiv_count,
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
        """통합 데일리 브리핑"""
        # 각 스트림 요약
        therapeutic_summary = self._summarize_stream(all_results.get("therapeutic_area", []))
        innovation_summary = self._summarize_stream(all_results.get("innovation", []))
        external_summary = self._summarize_stream(all_results.get("external", []))

        prompt = UNIFIED_BRIEFING_PROMPT.format(
            therapeutic_summary=therapeutic_summary,
            innovation_summary=innovation_summary,
            external_summary=external_summary,
            date=datetime.now().strftime("%Y-%m-%d"),
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

    def _summarize_stream(self, results: list[StreamResult]) -> str:
        """스트림 결과 텍스트 요약"""
        if not results:
            return "수집 없음"
        total_drugs = sum(r.drug_count for r in results)
        total_signals = sum(r.signal_count for r in results)
        categories = [r.sub_category for r in results if r.sub_category]
        top_inns = []
        for r in results:
            top_inns.extend(r.inn_list[:5])
        return (
            f"약물 {total_drugs}건, 시그널 {total_signals}건. "
            f"카테고리: {', '.join(categories) if categories else 'N/A'}. "
            f"주요 INN: {', '.join(top_inns[:10])}"
        )

    def _fallback_therapeutic(self, area: str, area_ko: str, result: StreamResult) -> dict:
        """LLM 실패 시 구조화 데이터 기반 브리핑"""
        return {
            "headline": f"{area_ko} 치료영역 브리핑",
            "drug_count": result.drug_count,
            "top_drugs": [{"inn": inn} for inn in result.inn_list[:10]],
            "errors": result.errors,
        }

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출"""
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
                response = await client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception as e:
                logger.debug("Anthropic 브리핑 호출 실패: %s", e)

        if settings.OPENAI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.debug("OpenAI 브리핑 호출 실패: %s", e)

        raise RuntimeError("LLM API 키 미설정")

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
