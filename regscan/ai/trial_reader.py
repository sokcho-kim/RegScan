"""AI Trial Result Reader — 완료된 임상시험 결과 성공/실패 판독

COMPLETED + HasResults 임상시험에 대해 LLM으로 Primary Outcome 판독.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from regscan.config import settings

logger = logging.getLogger(__name__)

TRIAL_READER_PROMPT = """You are an expert clinical trial analyst. Analyze the following Phase 3 clinical trial data and determine if the trial was successful.

**Trial Information:**
- Title: {title}
- NCT ID: {nct_id}
- Conditions: {conditions}
- Interventions: {interventions}
- Sponsor: {sponsor}
- Enrollment: {enrollment}
- Status: {status}

**Task:**
1. Determine if the primary endpoint was met (success/failure)
2. Assess your confidence level (0.0-1.0)
3. Provide a brief summary

**Output JSON format (ONLY output valid JSON, no other text):**
{{
  "success": true/false/null,
  "confidence": 0.0-1.0,
  "summary": "Brief analysis",
  "primary_endpoint_met": true/false/null
}}

If you cannot determine success/failure from the available data, set success to null.
"""


class TrialResultReader:
    """AI 기반 임상시험 결과 판독기"""

    def __init__(self):
        self._anthropic_client = None
        self._openai_client = None

    async def read_trial(self, study: dict[str, Any]) -> dict[str, Any]:
        """단일 임상시험 AI 판독

        Args:
            study: ClinicalTrialsGovParser 파싱 결과

        Returns:
            {success: bool|None, confidence: float, summary: str, primary_endpoint_met: bool|None}
        """
        prompt = TRIAL_READER_PROMPT.format(
            title=study.get("title", ""),
            nct_id=study.get("nct_id", ""),
            conditions=", ".join(study.get("conditions", [])),
            interventions=json.dumps(study.get("interventions", []), ensure_ascii=False),
            sponsor=study.get("sponsor", ""),
            enrollment=study.get("enrollment", 0),
            status=study.get("status", ""),
        )

        try:
            result_text = await self._call_llm(prompt)
            return self._parse_result(result_text)
        except Exception as e:
            logger.warning("AI 임상결과 판독 실패 (%s): %s", study.get("nct_id"), e)
            return {
                "success": None,
                "confidence": 0.0,
                "summary": f"판독 실패: {e}",
                "primary_endpoint_met": None,
            }

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출 (Anthropic → OpenAI fallback)"""
        # Anthropic 우선
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                if not self._anthropic_client:
                    self._anthropic_client = anthropic.AsyncAnthropic(
                        api_key=settings.ANTHROPIC_API_KEY,
                    )
                response = await self._anthropic_client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception as e:
                logger.debug("Anthropic 호출 실패: %s", e)

        # OpenAI fallback
        if settings.OPENAI_API_KEY:
            try:
                import openai
                if not self._openai_client:
                    self._openai_client = openai.AsyncOpenAI(
                        api_key=settings.OPENAI_API_KEY,
                    )
                response = await self._openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.debug("OpenAI 호출 실패: %s", e)

        raise RuntimeError("LLM API 키 미설정 (ANTHROPIC_API_KEY 또는 OPENAI_API_KEY)")

    def _parse_result(self, text: str) -> dict[str, Any]:
        """LLM 응답 JSON 파싱"""
        # JSON 블록 추출
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
            return {
                "success": data.get("success"),
                "confidence": float(data.get("confidence", 0.0)),
                "summary": str(data.get("summary", "")),
                "primary_endpoint_met": data.get("primary_endpoint_met"),
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "success": None,
                "confidence": 0.0,
                "summary": text[:200],
                "primary_endpoint_met": None,
            }
