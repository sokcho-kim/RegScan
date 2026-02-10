"""Insight Verifier — GPT-5.2 기반 팩트체크·검증

o4-mini 추론 결과를 원본 데이터와 대조 검증합니다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from regscan.config import settings
from regscan.ai.prompts.verifier_prompt import (
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_PROMPT,
)

logger = logging.getLogger(__name__)


class InsightVerifier:
    """GPT-5.2 기반 인사이트 검증기

    Reasoning Engine의 출력을 원본 데이터와 대조하여
    팩트체크하고 신뢰도를 평가합니다.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model or settings.VERIFIER_MODEL
        self.api_key = api_key or settings.OPENAI_API_KEY
        self._client = None

    def _get_client(self):
        """OpenAI 클라이언트 lazy init"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "openai 패키지가 필요합니다. pip install 'regscan[llm]'"
                )
        return self._client

    async def verify(
        self,
        drug: dict[str, Any],
        reasoning_result: dict[str, Any],
        raw_sources: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """추론 결과 검증

        Args:
            drug: 약물 기본 데이터
            reasoning_result: ReasoningEngine의 출력
            raw_sources: 원본 데이터 {"preprints", "market_reports", "expert_opinions"}

        Returns:
            {verified_score, corrections, confidence_level,
             verifier_model, verifier_tokens}
        """
        if not self.api_key:
            logger.warning("OPENAI_API_KEY 미설정 — verification 건너뜀")
            return self._fallback_result(reasoning_result)

        raw_sources = raw_sources or {}

        prompt = VERIFIER_PROMPT.format(
            reasoning_result=json.dumps(reasoning_result, ensure_ascii=False, default=str),
            regulatory_data=json.dumps(
                {k: drug.get(k) for k in [
                    "inn", "fda_approved", "fda_date", "ema_approved", "ema_date",
                    "mfds_approved", "mfds_date", "hira_status", "hira_price",
                ]},
                ensure_ascii=False, default=str,
            ),
            preprint_data=json.dumps(
                raw_sources.get("preprints", [])[:5],
                ensure_ascii=False, default=str,
            ),
            market_data=json.dumps(
                raw_sources.get("market_reports", [])[:3],
                ensure_ascii=False, default=str,
            ),
            expert_data=json.dumps(
                raw_sources.get("expert_opinions", [])[:3],
                ensure_ascii=False, default=str,
            ),
            original_score=reasoning_result.get("impact_score", 0),
        )

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0

            result = json.loads(result_text)
            result["verifier_model"] = self.model
            result["verifier_tokens"] = tokens

            logger.info(
                "Verification 완료: %s, original=%d → verified=%d, confidence=%s",
                drug.get("inn", "?"),
                reasoning_result.get("impact_score", 0),
                result.get("verified_score", 0),
                result.get("confidence_level", "?"),
            )
            return result

        except Exception as e:
            logger.error("Verification 실패 (%s): %s", drug.get("inn", "?"), e)
            return self._fallback_result(reasoning_result)

    def _fallback_result(self, reasoning_result: dict) -> dict:
        """API 실패 시 기본 검증 결과 반환"""
        return {
            "verified_score": reasoning_result.get("impact_score", 0),
            "corrections": [],
            "confidence_level": "low",
            "confidence_reason": "Fallback: 검증 미수행",
            "verifier_model": "fallback",
            "verifier_tokens": 0,
        }
