"""LLM 기반 브리핑 리포트 생성기"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from regscan.config import settings
from regscan.scan.domestic import DomesticImpact
from regscan.report.prompts import (
    SYSTEM_PROMPT,
    BRIEFING_REPORT_PROMPT,
    MEDCLAIM_INSIGHT_PROMPT,
    QUICK_SUMMARY_PROMPT,
)

logger = logging.getLogger(__name__)


@dataclass
class BriefingReport:
    """브리핑 리포트"""
    inn: str
    headline: str
    subtitle: str
    key_points: list[str]
    global_section: str
    domestic_section: str
    medclaim_section: str
    generated_at: datetime = field(default_factory=datetime.now)

    # 원본 데이터
    source_data: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "inn": self.inn,
            "headline": self.headline,
            "subtitle": self.subtitle,
            "key_points": self.key_points,
            "global_section": self.global_section,
            "domestic_section": self.domestic_section,
            "medclaim_section": self.medclaim_section,
            "generated_at": self.generated_at.isoformat(),
        }

    def to_markdown(self) -> str:
        """마크다운 형식 출력"""
        lines = [
            f"# {self.headline}",
            f"*{self.subtitle}*",
            "",
            "## 핵심 요약",
        ]
        for i, point in enumerate(self.key_points, 1):
            lines.append(f"{i}. {point}")

        lines.extend([
            "",
            "## 글로벌 승인 현황",
            self.global_section,
            "",
            "## 국내 도입 전망",
            self.domestic_section,
            "",
            "## 메드클레임 시사점",
            self.medclaim_section,
            "",
            "---",
            f"*생성: {self.generated_at.strftime('%Y-%m-%d %H:%M')} | RegScan AI*",
        ])
        return "\n".join(lines)


class LLMBriefingGenerator:
    """LLM 브리핑 리포트 생성기

    사용법:
        generator = LLMBriefingGenerator()
        report = await generator.generate(drug_impact)
        print(report.to_markdown())

    지원 모델:
        - OpenAI: gpt-4o-mini, gpt-4o, gpt-4-turbo, o1-mini
        - Anthropic: claude-sonnet-4-20250514, claude-3-haiku
    """

    # 지원 모델 목록
    SUPPORTED_MODELS = {
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "o1-mini"],
        "anthropic": ["claude-sonnet-4-20250514", "claude-3-haiku-20240307"],
    }

    def __init__(
        self,
        provider: str = "openai",  # "openai" or "anthropic"
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key

        if provider == "anthropic":
            self.model = model or "claude-sonnet-4-20250514"
            self.api_key = api_key or settings.ANTHROPIC_API_KEY
        else:
            self.model = model or "gpt-4o-mini"
            self.api_key = api_key or settings.OPENAI_API_KEY

        self._client = None

    def _get_client(self):
        """LLM 클라이언트 lazy loading"""
        if self._client is None:
            if self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            else:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def _prepare_drug_data(self, impact: DomesticImpact) -> str:
        """DomesticImpact를 LLM 입력 형식으로 변환"""
        data = {
            "inn": impact.inn,
            "fda": {
                "approved": impact.fda_approved,
                "date": impact.fda_date.isoformat() if impact.fda_date else None,
            },
            "ema": {
                "approved": impact.ema_approved,
                "date": impact.ema_date.isoformat() if impact.ema_date else None,
            },
            "mfds": {
                "approved": impact.mfds_approved,
                "date": impact.mfds_date.isoformat() if impact.mfds_date else None,
                "brand_name": impact.mfds_brand_name,
            },
            "hira": {
                "status": impact.hira_status.value if impact.hira_status else None,
                "price": impact.hira_price,
                "criteria": impact.hira_criteria,
            },
            "cris": {
                "trial_count": len(impact.cris_trials),
                "trials": [
                    {"id": t.trial_id, "title": t.title, "phase": t.phase}
                    for t in impact.cris_trials[:5]
                ],
            },
            "analysis": {
                "domestic_status": impact.domestic_status.value,
                "global_score": impact.global_score,
                "hot_issue_reasons": impact.hot_issue_reasons,
                "notes": impact.analysis_notes,
            },
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    async def generate(self, impact: DomesticImpact) -> BriefingReport:
        """브리핑 리포트 생성"""
        drug_data = self._prepare_drug_data(impact)
        prompt = BRIEFING_REPORT_PROMPT.format(drug_data=drug_data)

        try:
            response_text = await self._call_llm(prompt)
            parsed = self._parse_json_response(response_text)

            return BriefingReport(
                inn=impact.inn,
                headline=parsed.get("headline", f"{impact.inn} 규제 동향"),
                subtitle=parsed.get("subtitle", ""),
                key_points=parsed.get("key_points", []),
                global_section=parsed.get("global_section", ""),
                domestic_section=parsed.get("domestic_section", ""),
                medclaim_section=parsed.get("medclaim_section", ""),
                source_data=impact.to_dict(),
            )
        except Exception as e:
            logger.error(f"LLM 리포트 생성 실패: {e}")
            return self._generate_fallback(impact)

    async def generate_quick_summary(self, impact: DomesticImpact) -> str:
        """간단 요약 생성"""
        drug_data = self._prepare_drug_data(impact)
        prompt = QUICK_SUMMARY_PROMPT.format(drug_data=drug_data)

        try:
            return await self._call_llm(prompt)
        except Exception as e:
            logger.error(f"Quick summary 생성 실패: {e}")
            return impact.summary

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 호출"""
        client = self._get_client()

        if self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        else:
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content

    def _parse_json_response(self, text: str) -> dict:
        """LLM 응답에서 JSON 추출"""
        # JSON 블록 추출 시도
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패, 원본 텍스트 사용")
            return {"global_section": text}

    def _generate_fallback(self, impact: DomesticImpact) -> BriefingReport:
        """LLM 실패 시 템플릿 기반 리포트"""
        # 글로벌 섹션
        global_parts = []
        if impact.fda_approved:
            global_parts.append(f"FDA 승인 ({impact.fda_date})")
        if impact.ema_approved:
            global_parts.append(f"EMA 승인 ({impact.ema_date})")
        global_section = ", ".join(global_parts) if global_parts else "글로벌 승인 정보 없음"

        # 국내 섹션
        domestic_parts = []
        if impact.mfds_approved:
            domestic_parts.append(f"MFDS 허가 완료 ({impact.mfds_brand_name})")
        else:
            domestic_parts.append("MFDS 미허가")

        if impact.hira_status:
            domestic_parts.append(f"HIRA: {impact.hira_status.value}")
            if impact.hira_price:
                domestic_parts.append(f"상한가 ₩{impact.hira_price:,.0f}")

        if impact.cris_trials:
            domestic_parts.append(f"CRIS 임상시험 {len(impact.cris_trials)}건")

        domestic_section = " | ".join(domestic_parts)

        # 메드클레임 섹션
        medclaim_parts = []
        if impact.hira_status and impact.hira_status.value == "reimbursed":
            medclaim_parts.append("건강보험 급여 적용 중")
            if impact.hira_price and impact.hira_price >= 1_000_000:
                medclaim_parts.append("고가 약제 - 사전심사 대상 가능")
        else:
            medclaim_parts.append("비급여 또는 급여 미적용")

        medclaim_section = ". ".join(medclaim_parts)

        return BriefingReport(
            inn=impact.inn,
            headline=f"{impact.inn} 규제 동향 브리핑",
            subtitle=impact.summary[:50] if impact.summary else "",
            key_points=impact.hot_issue_reasons[:4] if impact.hot_issue_reasons else [],
            global_section=global_section,
            domestic_section=domestic_section,
            medclaim_section=medclaim_section,
            source_data=impact.to_dict(),
        )


# 편의 함수
async def generate_briefing(impact: DomesticImpact, provider: str = "openai") -> BriefingReport:
    """브리핑 리포트 생성 편의 함수"""
    generator = LLMBriefingGenerator(provider=provider)
    return await generator.generate(impact)


async def compare_models(
    impact: DomesticImpact,
    models: list[tuple[str, str]] = None,  # [(provider, model), ...]
) -> dict[str, BriefingReport]:
    """여러 모델로 브리핑 생성 비교

    Args:
        impact: 분석 대상 약물
        models: [(provider, model), ...] 리스트. None이면 기본 모델들 사용

    Returns:
        {model_name: BriefingReport} 딕셔너리

    Example:
        results = await compare_models(impact, [
            ("openai", "gpt-4o-mini"),
            ("openai", "gpt-4o"),
        ])
        for model, report in results.items():
            print(f"=== {model} ===")
            print(report.headline)
    """
    if models is None:
        models = [
            ("openai", "gpt-4o-mini"),
            ("openai", "gpt-4o"),
        ]

    results = {}
    for provider, model in models:
        try:
            generator = LLMBriefingGenerator(provider=provider, model=model)
            report = await generator.generate(impact)
            results[f"{provider}/{model}"] = report
        except Exception as e:
            logger.error(f"Model {provider}/{model} failed: {e}")
            results[f"{provider}/{model}"] = None

    return results
