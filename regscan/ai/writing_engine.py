"""Writing Engine — GPT-5.2 기반 전문 기사 작성

검증된 AI 인사이트를 기반으로 전문 기사를 생성합니다.
기사 유형: briefing / newsletter / press_release
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from regscan.config import settings
from regscan.ai.prompts.writer_prompt import (
    WRITER_SYSTEM_PROMPT,
    BRIEFING_WRITER_PROMPT,
    WRITER_FEW_SHOT,
)

logger = logging.getLogger(__name__)


class WritingEngine:
    """GPT-5.2 기반 기사 작성 엔진"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model or settings.WRITER_MODEL
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

    async def write_article(
        self,
        drug: dict[str, Any],
        verified_insight: dict[str, Any],
        article_type: str = "briefing",
    ) -> dict[str, Any]:
        """AI 기사 작성

        Args:
            drug: 약물 기본 데이터
            verified_insight: InsightVerifier의 출력 (검증 완료 인사이트)
            article_type: 기사 유형 (briefing / newsletter / press_release)

        Returns:
            {article_type, headline, subtitle, lead_paragraph,
             body_html, tags, writer_model, writer_tokens}
        """
        if not self.api_key:
            logger.warning("OPENAI_API_KEY 미설정 — writing 건너뜀")
            return self._fallback_result(drug, article_type)

        source_summary = self._build_source_summary(drug, verified_insight)

        prompt = BRIEFING_WRITER_PROMPT.format(
            article_type=article_type,
            drug_name=drug.get("inn", "Unknown"),
            verified_insight=json.dumps(verified_insight, ensure_ascii=False, default=str),
            source_summary=source_summary,
        )

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": WRITER_SYSTEM_PROMPT},
                    {"role": "user", "content": WRITER_FEW_SHOT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0

            result = json.loads(result_text)
            result["article_type"] = article_type
            result["writer_model"] = self.model
            result["writer_tokens"] = tokens

            logger.info(
                "기사 작성 완료: %s [%s], headline=%s, tokens=%d",
                drug.get("inn", "?"),
                article_type,
                result.get("headline", "?")[:30],
                tokens,
            )
            return result

        except Exception as e:
            logger.error(
                "기사 작성 실패 (%s, %s): %s",
                drug.get("inn", "?"), article_type, e,
            )
            return self._fallback_result(drug, article_type)

    def _fallback_result(self, drug: dict, article_type: str) -> dict:
        """API 실패 시 기본 기사 반환"""
        inn = drug.get("inn", "Unknown")
        return {
            "article_type": article_type,
            "headline": f"{inn} 규제 동향 요약",
            "subtitle": "AI 기사 생성 실패 — 기본 템플릿",
            "lead_paragraph": f"{inn}에 대한 AI 분석 기사를 생성하지 못했습니다.",
            "body_html": "",
            "tags": [inn],
            "writer_model": "fallback",
            "writer_tokens": 0,
        }

    @staticmethod
    def _build_source_summary(drug: dict, insight: dict) -> str:
        """원본 데이터 요약 생성"""
        lines = []
        inn = drug.get("inn", "Unknown")
        lines.append(f"약물: {inn}")

        if drug.get("fda_approved"):
            lines.append(f"FDA: 승인 ({drug.get('fda_date', 'N/A')})")
        if drug.get("ema_approved"):
            lines.append(f"EMA: 승인 ({drug.get('ema_date', 'N/A')})")
        if drug.get("mfds_approved"):
            lines.append(f"MFDS: 허가 ({drug.get('mfds_date', 'N/A')})")

        hira = drug.get("hira_status")
        if hira:
            lines.append(f"HIRA 급여: {hira}")

        score = insight.get("verified_score") or insight.get("impact_score", 0)
        lines.append(f"AI 영향도 점수: {score}")

        confidence = insight.get("confidence_level", "")
        if confidence:
            lines.append(f"검증 신뢰도: {confidence}")

        return "\n".join(lines)
