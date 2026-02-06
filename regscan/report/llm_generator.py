"""LLM 기반 브리핑 리포트 생성기"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from regscan.config import settings

BRIEFINGS_DIR = settings.BASE_DIR / "output" / "briefings"
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

    def save(self, directory: Path = BRIEFINGS_DIR) -> Path:
        """JSON 파일로 저장"""
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = self.inn.replace(" ", "_").replace("/", "_")
        path = directory / f"{safe_name}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, inn: str, directory: Path = BRIEFINGS_DIR) -> Optional["BriefingReport"]:
        """저장된 브리핑 로드. DB 우선, 파일 폴백."""
        from regscan.config import settings

        # DB 모드: PostgreSQL이면 DB에서 먼저 조회
        if settings.is_postgres:
            try:
                import asyncio
                from regscan.db.loader import DBLoader
                loader = DBLoader()
                # sync context에서 async 호출
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # FastAPI 등 이미 이벤트 루프가 있는 경우 — 파일 폴백
                    pass
                else:
                    report = loop.run_until_complete(loader.load_briefing(inn))
                    if report:
                        return report
            except Exception:
                pass  # DB 실패 시 파일 폴백

        # 파일 모드
        safe_name = inn.replace(" ", "_").replace("/", "_")
        path = directory / f"{safe_name}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                inn=data["inn"],
                headline=data["headline"],
                subtitle=data["subtitle"],
                key_points=data.get("key_points", []),
                global_section=data.get("global_section", ""),
                domestic_section=data.get("domestic_section", ""),
                medclaim_section=data.get("medclaim_section", ""),
                generated_at=datetime.fromisoformat(data["generated_at"]),
            )
        except Exception:
            return None

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
            if not response.content:
                logger.warning("Anthropic API returned empty content list")
                return ""
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
            if not response.choices:
                logger.warning("OpenAI API returned empty choices list")
                return ""
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

    # HIRA 상태 한글 매핑
    HIRA_STATUS_KR = {
        "reimbursed": "급여 적용",
        "deleted": "급여 삭제(이력 있음)",
        "not_covered": "비급여",
        "not_found": "급여 정보 없음",
        "herbal": "한약재·생약(별도 체계)",
    }

    def _hira_label(self, impact: DomesticImpact) -> str:
        """HIRA 상태를 한글로 변환"""
        if not impact.hira_status:
            return "급여 정보 없음"
        return self.HIRA_STATUS_KR.get(impact.hira_status.value, impact.hira_status.value)

    # ── 기사 의미 있는 태그만 필터 ──
    _REDUNDANT_REASONS = {"FDA 승인", "EMA 승인", "MFDS 허가", "3개국 승인"}

    _DESIGNATION_KR = {
        "EMA PRIME": "EMA PRIME(우선심사) 지정",
        "EMA Conditional Approval": "EMA 조건부 허가",
        "Breakthrough": "FDA 혁신치료제(Breakthrough) 지정",
        "Fast Track": "FDA 신속심사(Fast Track) 지정",
        "Accelerated": "FDA 가속승인(Accelerated Approval)",
        "Priority": "FDA 우선심사(Priority Review)",
    }

    def _fmt_date(self, d) -> str:
        """날짜를 한글 기사 형식으로 변환"""
        if d is None:
            return "날짜 미상"
        try:
            if hasattr(d, 'strftime'):
                return d.strftime("%Y년 %-m월 %-d일").replace("%-m", str(d.month)).replace("%-d", str(d.day))
        except Exception:
            pass
        # fallback: strftime with zero-padded then strip
        try:
            s = d.strftime("%Y년 %m월 %d일")
            # 0-padding 제거: "01월" → "1월"
            import re
            return re.sub(r'(?<=년 )0|(?<=월 )0', '', s)
        except Exception:
            return str(d)

    def _meaningful_reasons(self, impact: DomesticImpact) -> list[str]:
        """중복·무의미한 태그를 제외하고 의미 있는 이유만 반환"""
        result = []
        for r in impact.hot_issue_reasons:
            if r in self._REDUNDANT_REASONS:
                continue
            # 지정 사항 한글 매핑
            for key, label in self._DESIGNATION_KR.items():
                if key in r:
                    result.append(label)
                    break
            else:
                if "희귀" in r or "Orphan" in r:
                    result.append("희귀의약품 지정")
                elif "FDA+EMA" in r:
                    result.append("FDA·EMA 근접 시기 승인")
                elif "주요 질환" in r:
                    continue  # 너무 범용적, 스킵
                else:
                    result.append(r)
        # 중복 제거
        seen = set()
        unique = []
        for item in result:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    def _generate_fallback(self, impact: DomesticImpact) -> BriefingReport:
        """LLM 실패 시 기사톤 템플릿 기반 리포트"""
        from regscan.map.ingredient_bridge import ReimbursementStatus

        inn = impact.inn
        brand = impact.mfds_brand_name or ""
        # 표시용 이름: 국내 브랜드명이 있으면 "브랜드명(INN)" 형태
        display_name = f"{brand.split('(')[0]}({inn})" if brand else inn
        is_orphan = any("희귀" in r or "Orphan" in r for r in impact.hot_issue_reasons)
        meaningful = self._meaningful_reasons(impact)
        fda_str = self._fmt_date(impact.fda_date)
        ema_str = self._fmt_date(impact.ema_date)
        mfds_str = self._fmt_date(impact.mfds_date)

        # ── 헤드라인 ──
        if impact.fda_approved and impact.ema_approved and not impact.mfds_approved:
            headline = f"FDA·EMA 양대 기관 승인 '{display_name}', 국내 도입 초읽기"
        elif impact.fda_approved and not impact.mfds_approved:
            headline = f"미 FDA 승인 '{display_name}', 국내 허가 전망과 과제"
        elif impact.ema_approved and not impact.mfds_approved:
            headline = f"유럽 EMA 허가 '{display_name}', 국내 시장 진출 가능성은"
        elif impact.mfds_approved and impact.fda_approved and impact.ema_approved:
            if impact.hira_status == ReimbursementStatus.REIMBURSED:
                headline = f"글로벌·국내 동시 허가 '{display_name}', 급여 등재까지 완료"
            else:
                headline = f"3개국 허가 완료 '{display_name}', 급여 등재가 남은 과제"
        elif impact.mfds_approved and impact.fda_approved:
            headline = f"FDA·MFDS 동시 허가 '{display_name}', 보험 적용 여부 주목"
        elif impact.mfds_approved:
            headline = f"MFDS 허가 '{display_name}', 국내 시장 현황 점검"
        else:
            headline = f"'{display_name}' 규제 동향 브리핑"

        # ── 서브타이틀 ──
        subtitle_parts = []
        if meaningful:
            subtitle_parts.append(meaningful[0])
        if brand and not any(brand.split('(')[0] in p for p in subtitle_parts):
            subtitle_parts.append(f"국내 제품명 '{brand}'")
        hira_label = self._hira_label(impact)
        subtitle_parts.append(f"급여 현황: {hira_label}")
        subtitle = " · ".join(subtitle_parts)

        # ── 핵심 요약 (분석적 톤) ──
        key_points = []
        # 승인 현황 한 줄 요약
        agencies = []
        if impact.fda_approved:
            agencies.append(f"FDA({fda_str})")
        if impact.ema_approved:
            agencies.append(f"EMA({ema_str})")
        if impact.mfds_approved:
            agencies.append(f"MFDS({mfds_str})")
        if agencies:
            key_points.append(f"글로벌 승인: {', '.join(agencies)}")

        # 규제 지정 사항
        if meaningful:
            key_points.append(f"규제 특이사항: {', '.join(meaningful[:3])}")

        # 급여·가격
        if impact.hira_status == ReimbursementStatus.REIMBURSED:
            price_info = f", 상한가 ₩{impact.hira_price:,.0f}" if impact.hira_price else ""
            key_points.append(f"건강보험 급여 적용 중{price_info}")
        elif impact.mfds_approved:
            key_points.append("국내 허가 완료, 급여 미등재 — 약가 협상 또는 비급여 상태")
        else:
            key_points.append("국내 미허가 — 허가·급여 등재 동향 모니터링 필요")

        # 임상시험
        if impact.cris_trials:
            active = sum(1 for t in impact.cris_trials if t.status and t.status.lower() in ("recruiting", "active", "enrolling"))
            if active:
                key_points.append(f"국내 임상시험 {len(impact.cris_trials)}건 중 {active}건 진행 중")
            else:
                key_points.append(f"국내 임상시험 {len(impact.cris_trials)}건 등록 (활성 모집 없음)")

        # ── 글로벌 섹션 ──
        if impact.fda_approved and impact.ema_approved:
            global_section = (
                f"{display_name}은 미국 식품의약국(FDA)이 "
                f"{fda_str} 승인한 데 이어, "
                f"유럽의약품청(EMA)도 {ema_str} 허가를 완료했다. "
                f"글로벌 양대 규제기관이 모두 승인한 만큼, "
                f"해당 약물의 유효성·안전성 근거는 충분한 것으로 평가된다."
            )
        elif impact.fda_approved:
            global_section = (
                f"{display_name}은 미국 FDA가 {fda_str} 승인한 약물이다. "
                f"유럽 EMA 허가는 아직 확인되지 않았으나, FDA 승인 약물은 "
                f"통상 1~2년 내 EMA 심사가 진행되는 점을 고려할 필요가 있다."
            )
        elif impact.ema_approved:
            global_section = (
                f"{display_name}은 유럽 EMA가 {ema_str} 허가한 약물이다. "
                f"미국 FDA 승인은 아직 확인되지 않았다."
            )
        else:
            global_section = (
                f"{display_name}에 대한 글로벌 주요 규제기관(FDA, EMA)의 "
                f"승인 이력은 현재 확인되지 않는다."
            )

        # 의미 있는 규제 지정 사항 추가
        if meaningful:
            designations = ", ".join(meaningful[:3])
            global_section += f" 특히 {designations} 이력이 확인되어, 규제 당국이 해당 약물의 임상적 가치를 높게 평가한 것으로 해석된다."

        # ── 국내 섹션 ──
        if impact.mfds_approved:
            domestic_section = (
                f"국내에서는 식품의약품안전처(MFDS)가 {mfds_str} 품목허가를 완료했다."
            )
            if brand:
                domestic_section += f" 국내 유통 제품명은 '{brand}'이다."
        else:
            domestic_section = (
                f"현재 식약처(MFDS)에 {inn} 품목허가 이력은 확인되지 않는다."
            )
            if impact.cris_trials:
                domestic_section += (
                    f" 다만 임상연구정보서비스(CRIS)에 {len(impact.cris_trials)}건의 "
                    f"국내 임상시험이 등록되어 있어, 향후 허가 신청 가능성이 있다."
                )
            elif impact.fda_approved or impact.ema_approved:
                domestic_section += (
                    " 글로벌 주요국 승인이 완료된 상태이므로, "
                    "국내 허가 신청은 시간 문제로 판단된다."
                )
            else:
                domestic_section += " 국내 임상시험 등록도 확인되지 않아 단기간 내 도입은 불투명하다."

        # HIRA 급여 분석
        if impact.hira_status:
            if impact.hira_status == ReimbursementStatus.REIMBURSED:
                price_str = f" 현행 상한가는 ₩{impact.hira_price:,.0f}이다." if impact.hira_price else ""
                domestic_section += f" 건강보험심사평가원(HIRA) 급여 목록에 등재되어 있다.{price_str}"
            elif impact.hira_status == ReimbursementStatus.DELETED:
                domestic_section += (
                    " 과거 HIRA 급여 목록에 등재된 이력이 있으나 현재는 삭제된 상태다. "
                    "급여 재등재 여부를 모니터링할 필요가 있다."
                )
            elif impact.hira_status == ReimbursementStatus.NOT_COVERED:
                domestic_section += " HIRA 급여 목록에 미등재 상태로, 사용 시 전액 환자 부담이다."
            elif impact.hira_status == ReimbursementStatus.NOT_FOUND:
                if impact.mfds_approved:
                    domestic_section += (
                        " HIRA 급여 정보는 현재 미확인 상태다. "
                        "허가 후 급여 등재까지는 통상 6개월~2년이 소요되며, "
                        "약가 협상 결과에 따라 환자 접근성이 결정된다."
                    )
                else:
                    domestic_section += " HIRA 급여 정보는 확인되지 않는다."

        # ── 메드클레임 섹션 ──
        if impact.hira_status == ReimbursementStatus.REIMBURSED:
            medclaim_section = "건강보험 급여가 적용되고 있어 요양급여 청구가 가능하다."
            if impact.hira_price and impact.hira_price >= 1_000_000:
                medclaim_section += (
                    f" 상한가 ₩{impact.hira_price:,.0f} 기준 고가 약제에 해당하며, "
                    f"사전승인(PA) 및 요양급여 적정성 평가 대비가 필요하다. "
                    f"DUR(의약품안심서비스) 점검 대상일 수 있다."
                )
            elif impact.hira_price:
                medclaim_section += (
                    f" 상한가 ₩{impact.hira_price:,.0f} 기준으로, "
                    f"일반적인 청구 절차를 따르면 된다."
                )
        elif impact.mfds_approved:
            medclaim_section = (
                "국내 허가는 완료되었으나 급여 등재가 확인되지 않는다. "
                "비급여 처방 시 전액 환자 부담이며, "
                "실손의료보험 청구 가능 여부는 개별 약관에 따라 상이하다. "
                "향후 급여 전환 시 청구 체계 변동에 유의해야 한다."
            )
        else:
            medclaim_section = (
                "국내 미허가 약물로, 현 시점에서 보험 청구는 불가하다. "
                "다만 희소질환·항암제 등 특정 적응증의 경우 "
                "사전승인 비급여 또는 긴급도입 경로가 존재하므로, "
                "허가·급여 등재 동향을 지속 모니터링할 필요가 있다."
            )

        if is_orphan:
            medclaim_section += (
                " 희귀의약품으로 지정되어, 급여 적용 시 "
                "산정특례(본인부담률 10%) 대상이 될 수 있다. "
                "희귀질환자 의료비 지원사업 대상 여부도 확인이 필요하다."
            )

        return BriefingReport(
            inn=impact.inn,
            headline=headline,
            subtitle=subtitle,
            key_points=key_points[:5],
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
