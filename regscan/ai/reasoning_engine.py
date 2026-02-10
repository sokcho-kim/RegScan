"""Reasoning Engine — o4-mini 기반 다차원 영향도 분석

4대 스트림(규제/연구/시장/현장반응)을 종합하여
약물의 영향도 점수, 리스크, 기회 요인을 도출합니다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from regscan.config import settings
from regscan.ai.prompts.reasoning_prompt import (
    REASONING_SYSTEM_PROMPT,
    REASONING_PROMPT,
)

logger = logging.getLogger(__name__)


class ReasoningEngine:
    """o4-mini 기반 Reasoning Engine

    비용 효율적인 o4-mini 모델로 최대한 추론을 수행합니다.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model or settings.REASONING_MODEL
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

    async def analyze_impact(
        self,
        drug: dict[str, Any],
        preprints: list[dict] | None = None,
        market_reports: list[dict] | None = None,
        expert_opinions: list[dict] | None = None,
    ) -> dict[str, Any]:
        """약물 영향도 분석

        Args:
            drug: 약물 기본 데이터 (INN, 승인현황, 급여, 임상 등)
            preprints: bioRxiv 프리프린트 목록
            market_reports: ASTI 시장 리포트 목록
            expert_opinions: Health.kr 전문가 리뷰 목록

        Returns:
            {impact_score, risk_factors, opportunity_factors,
             reasoning_chain, market_forecast, reasoning_model, reasoning_tokens}
        """
        if not self.api_key:
            logger.warning("OPENAI_API_KEY 미설정 — reasoning 건너뜀")
            return self._fallback_result(drug)

        prompt = REASONING_PROMPT.format(
            drug_data=json.dumps(drug, ensure_ascii=False, default=str),
            regulatory_data=self._format_regulatory(drug),
            preprint_data=self._format_preprints(preprints or []),
            market_data=self._format_market(market_reports or []),
            expert_data=self._format_experts(expert_opinions or []),
        )

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": REASONING_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                reasoning_effort="high",
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0

            result = json.loads(result_text)
            result["reasoning_model"] = self.model
            result["reasoning_tokens"] = tokens

            logger.info(
                "Reasoning 완료: %s, impact=%d, tokens=%d",
                drug.get("inn", "?"),
                result.get("impact_score", 0),
                tokens,
            )
            return result

        except Exception as e:
            logger.error("Reasoning 실패 (%s): %s", drug.get("inn", "?"), e)
            return self._fallback_result(drug)

    def _fallback_result(self, drug: dict) -> dict:
        """API 실패 시 기본 분석 결과 반환"""
        return {
            "impact_score": drug.get("global_score", 0),
            "risk_factors": [],
            "opportunity_factors": [],
            "reasoning_chain": "Fallback: 기존 v1 점수 사용",
            "market_forecast": "",
            "reasoning_model": "fallback",
            "reasoning_tokens": 0,
        }

    @staticmethod
    def _format_regulatory(drug: dict) -> str:
        """규제 데이터 포맷팅"""
        lines = []
        for agency in ["fda", "ema", "mfds"]:
            approved = drug.get(f"{agency}_approved", False)
            date = drug.get(f"{agency}_date", "")
            status = "승인" if approved else "미승인"
            lines.append(f"- {agency.upper()}: {status} ({date or 'N/A'})")

        hira = drug.get("hira_status", "")
        if hira:
            lines.append(f"- HIRA 급여: {hira}")
            price = drug.get("hira_price")
            if price:
                lines.append(f"  상한가: ₩{price:,.0f}")

        return "\n".join(lines) if lines else "규제 데이터 없음"

    @staticmethod
    def _format_preprints(preprints: list[dict]) -> str:
        """프리프린트 데이터 포맷팅"""
        if not preprints:
            return "관련 프리프린트 없음"
        lines = []
        for p in preprints[:10]:
            lines.append(f"- [{p.get('doi', '')}] {p.get('title', '')}")
            if p.get("abstract"):
                # 500자로 확장 — 임상 결과(PFS, OS, 환자수)는 보통 초록 후반에 위치
                abstract = p["abstract"]
                if len(abstract) > 500:
                    abstract = abstract[:500] + "..."
                lines.append(f"  요약: {abstract}")
        return "\n".join(lines)

    @staticmethod
    def _format_market(reports: list[dict]) -> str:
        """시장 데이터 포맷팅"""
        if not reports:
            return "시장 데이터 없음"
        lines = []
        for r in reports[:5]:
            lines.append(f"- {r.get('title', '')}")
            if r.get("market_size_krw"):
                lines.append(f"  시장 규모: {r['market_size_krw']}억 원")
            if r.get("growth_rate"):
                lines.append(f"  성장률: {r['growth_rate']}%")
        return "\n".join(lines)

    @staticmethod
    def _format_experts(opinions: list[dict]) -> str:
        """전문가 의견 포맷팅"""
        if not opinions:
            return "전문가 리뷰 없음"
        lines = []
        for o in opinions[:5]:
            lines.append(f"- [{o.get('source', '')}] {o.get('title', '')}")
            if o.get("summary"):
                lines.append(f"  요약: {o['summary'][:200]}...")
        return "\n".join(lines)
