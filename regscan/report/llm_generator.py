"""LLM 기반 브리핑 리포트 생성기"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any

from regscan.config import settings

BRIEFINGS_DIR = settings.BASE_DIR / "output" / "briefings"
from regscan.scan.domestic import DomesticImpact
from regscan.report.prompts import (
    SYSTEM_PROMPT,
    BRIEFING_REPORT_PROMPT,
    SYSTEM_PROMPT_V4,
    BRIEFING_REPORT_PROMPT_V4,
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
    global_heading: str = ""
    domestic_heading: str = ""
    generated_at: datetime = field(default_factory=datetime.now)

    # 원본 데이터
    source_data: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "inn": self.inn,
            "headline": self.headline,
            "subtitle": self.subtitle,
            "key_points": self.key_points,
            "global_section": self.global_section,
            "domestic_section": self.domestic_section,
            "medclaim_section": self.medclaim_section,
            "generated_at": self.generated_at.isoformat(),
        }
        if self.global_heading:
            d["global_heading"] = self.global_heading
        if self.domestic_heading:
            d["domestic_heading"] = self.domestic_heading
        return d

    def save(self, directory: Path = BRIEFINGS_DIR) -> Path:
        """JSON 파일로 저장"""
        import re as _re
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = _re.sub(r'[^\w\-]', '_', self.inn)[:80]
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
        "openai": ["gpt-5.2", "gpt-5.2-pro", "gpt-5", "gpt-4o-mini", "gpt-4o", "o1-mini"],
        "anthropic": ["claude-sonnet-4-20250514", "claude-3-haiku-20240307"],
        "gemini": ["gemini-2.0-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    }

    def __init__(
        self,
        provider: str = "openai",  # "openai", "anthropic", or "gemini"
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key

        if provider == "anthropic":
            self.model = model or "claude-sonnet-4-20250514"
            self.api_key = api_key or settings.ANTHROPIC_API_KEY
        elif provider == "gemini":
            self.model = model or settings.GEMINI_MODEL
            self.api_key = api_key or settings.GEMINI_API_KEY
        else:
            self.model = model or "gpt-5.2"
            self.api_key = api_key or settings.OPENAI_API_KEY

        self._client = None

    def _get_client(self):
        """LLM 클라이언트 lazy loading"""
        if self._client is None:
            if self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            elif self.provider == "gemini":
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            else:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    @staticmethod
    def _estimate_mfds_timeline(impact: DomesticImpact) -> str | None:
        """글로벌 승인 경과일 기반 MFDS 허가 타임라인 예측"""
        if impact.mfds_approved:
            return "already_approved"
        days = impact.days_since_global_approval
        if days is None:
            return None
        if impact.has_active_trial or len(impact.cris_trials) > 0:
            if days < 365:
                return "1~2년 내 허가 가능 (국내 임상 진행 중, 글로벌 승인 1년 미만)"
            else:
                return f"허가 임박 가능 (글로벌 승인 후 {days}일 경과, 국내 임상 진행 중)"
        if days < 365:
            return f"글로벌 승인 후 {days}일 — 통상 허가 신청 준비 단계 (1~3년 소요)"
        elif days < 730:
            return f"글로벌 승인 후 {days}일 — 허가 신청 진행 중일 가능성 (통상 1~2년)"
        elif days < 1095:
            return f"글로벌 승인 후 {days}일 — 허가 지연 (국내 판매권자 확보 지연 가능성)"
        else:
            return f"글로벌 승인 후 {days}일 경과 — 장기 미허가 (판매권자 부재 또는 시장성 판단 보류)"

    @staticmethod
    def _build_approval_timeline(impact: DomesticImpact) -> list[dict]:
        """승인 타임라인을 사전 계산된 구조체로 반환.

        각 항목: {agency, status, date, tense}
        tense: "past" / "future" / "unknown" — LLM이 시제를 자체 판단하지 않도록.
        """
        today = date.today()
        entries = []
        for agency, approved, d in [
            ("FDA", impact.fda_approved, impact.fda_date),
            ("EMA", impact.ema_approved, impact.ema_date),
            ("MFDS", impact.mfds_approved, impact.mfds_date),
        ]:
            if d is None:
                entries.append({
                    "agency": agency, "status": "미확인",
                    "date": None, "tense": "unknown",
                })
            elif d > today:
                entries.append({
                    "agency": agency, "status": "승인 예정",
                    "date": d.isoformat(), "tense": "future",
                })
            else:
                days = (today - d).days
                entries.append({
                    "agency": agency,
                    "status": f"승인 완료 (D+{days}일)",
                    "date": d.isoformat(), "tense": "past",
                })
        return entries

    @staticmethod
    def _to_display_case(inn: str) -> str:
        """INN을 Title Case로 변환 (USAN 접미사는 lowercase)"""
        if not inn:
            return inn
        words = inn.split()
        result = []
        for word in words:
            if '-' in word:
                parts = word.split('-')
                result.append(
                    parts[0].capitalize() + '-' + '-'.join(p.lower() for p in parts[1:])
                )
            else:
                result.append(word.capitalize())
        return ' '.join(result)

    def _prepare_drug_data(self, impact: DomesticImpact) -> str:
        """DomesticImpact를 LLM 입력 형식으로 변환"""
        data = {
            "inn": self._to_display_case(impact.inn),
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
                "korea_relevance_score": impact.korea_relevance_score,
                "korea_relevance_reasons": impact.korea_relevance_reasons,
                "quadrant": impact.quadrant,
                "hot_issue_reasons": impact.hot_issue_reasons,
                "notes": impact.analysis_notes,
            },
            "context": {
                "therapeutic_areas": impact.therapeutic_areas,
                "stream_sources": impact.stream_sources,
                "days_since_global_approval": impact.days_since_global_approval,
                "mfds_timeline_estimate": self._estimate_mfds_timeline(impact),
            },
        }

        # 산정특례 카테고리 (없으면 null → LLM은 산정특례 시나리오 생략)
        data["copay_exemption"] = getattr(impact, '_copay_exemption', None)

        # 승인 타임라인 (시제 사전 계산 — LLM이 날짜 계산하지 않도록)
        data["approval_timeline"] = self._build_approval_timeline(impact)

        # 경쟁약 데이터가 주입되었으면 포함
        if hasattr(impact, '_competitors') and impact._competitors:
            data["competitors"] = impact._competitors

        # 적응증 텍스트가 있으면 포함
        if hasattr(impact, '_indication_text') and impact._indication_text:
            data["indication"] = impact._indication_text

        # 약리학적 분류 (기전 이해에 활용)
        if hasattr(impact, '_pharmacotherapeutic_group') and impact._pharmacotherapeutic_group:
            data["pharmacotherapeutic_group"] = impact._pharmacotherapeutic_group

        # CT.gov 임상 결과 (resultsSection)
        if impact.clinical_results:
            cr = impact.clinical_results
            clinical_data: dict = {}
            if impact.clinical_results_nct_id:
                clinical_data["nct_id"] = impact.clinical_results_nct_id
            if cr.get("primary_outcomes"):
                clinical_data["primary_outcomes"] = cr["primary_outcomes"]
            if cr.get("secondary_outcomes"):
                clinical_data["secondary_outcomes"] = cr["secondary_outcomes"]
            if cr.get("adverse_events"):
                clinical_data["adverse_events"] = cr["adverse_events"]
            if clinical_data:
                data["clinical_trial_results"] = clinical_data

        return json.dumps(data, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════
    # V4: FactComputer — 사전 계산 팩트 필드 생성
    # ═══════════════════════════════════════════════════════

    # OpenAI Function Calling 툴 정의
    V4_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "get_regulatory_status",
                "description": "약물의 규제기관별 승인 상태/날짜/경과일 조회",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "inn": {"type": "string"},
                        "agency": {
                            "type": "string",
                            "enum": ["fda", "ema", "mfds"],
                        },
                    },
                    "required": ["inn", "agency"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_patient_cost",
                "description": "시나리오별 환자 본인부담금 계산",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "drug_price": {"type": "number"},
                        "scenario": {
                            "type": "string",
                            "enum": [
                                "general",
                                "cancer_special",
                                "rare_special",
                                "out_of_pocket",
                            ],
                        },
                    },
                    "required": ["drug_price", "scenario"],
                },
            },
        },
    ]

    def _compute_status_text(self, approved: bool, d, brand_name: str = "") -> str:
        """단일 기관 승인 상태 텍스트 생성"""
        if not approved:
            return "미허가 (not_approved)"
        if d is None:
            suffix = f" ({brand_name})" if brand_name else ""
            return f"허가 완료{suffix}"
        date_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        suffix = f", {brand_name}" if brand_name else ""
        return f"승인 완료 ({date_str}{suffix})"

    def _compute_d_day_text(self, impact: DomesticImpact) -> str:
        """글로벌 승인 경과일 + 해석 텍스트"""
        days = impact.days_since_global_approval
        if days is None:
            return "글로벌 승인 정보 없음"
        estimate = self._estimate_mfds_timeline(impact)
        if estimate and estimate != "already_approved":
            return f"글로벌 승인 후 {days}일 경과 — {estimate}"
        if estimate == "already_approved":
            return f"글로벌 승인 후 {days}일 경과 (국내 허가 완료)"
        return f"글로벌 승인 후 {days}일 경과"

    def _compute_copay_scenario_text(self, impact: DomesticImpact) -> str:
        """급여 시나리오 텍스트 생성"""
        copay = getattr(impact, '_copay_exemption', None)
        price = impact.hira_price

        from regscan.map.ingredient_bridge import ReimbursementStatus
        if impact.hira_status == ReimbursementStatus.REIMBURSED and price:
            parts = [f"HIRA 등재 약제 (상한가 ₩{price:,.0f})."]
            parts.append(f"일반 급여 시 본인부담 약 ₩{price * 0.3:,.0f} (30%).")
            if copay:
                rate = copay["rate"]
                label = copay["label"]
                parts.append(
                    f"{label}({int(rate*100)}%) 적용 시 본인부담 약 ₩{price * rate:,.0f}."
                )
            return " ".join(parts)

        if not impact.mfds_approved:
            if copay:
                label = copay["label"]
                rate = copay["rate"]
                return (
                    f"향후 급여 등재 시 {label}({int(rate*100)}%) 적용 가능. "
                    f"현재는 전액 비급여."
                )
            return "국내 미허가 — 급여 적용 불가. 전액 환자 부담."

        # 허가 완료, 급여 미등재
        if copay:
            label = copay["label"]
            rate = copay["rate"]
            return (
                f"국내 허가 완료, 급여 미등재. "
                f"향후 등재 시 {label}({int(rate*100)}%) 적용 가능."
            )
        return "국내 허가 완료, 급여 미등재. 비급여 처방 시 전액 환자 부담."

    def _compute_approval_summary_table(self, impact: DomesticImpact) -> str:
        """마크다운 승인 요약 표"""
        rows = []
        for agency, approved, d in [
            ("FDA", impact.fda_approved, impact.fda_date),
            ("EMA", impact.ema_approved, impact.ema_date),
            ("MFDS(식약처)", impact.mfds_approved, impact.mfds_date),
        ]:
            status = "승인" if approved else "미허가"
            date_str = d.isoformat() if d else "-"
            rows.append(f"| {agency} | {status} | {date_str} |")
        header = "| 기관 | 상태 | 날짜 |\n|---|---|---|"
        return header + "\n" + "\n".join(rows)

    def _compute_cost_scenario_table(self, impact: DomesticImpact) -> str:
        """마크다운 비용 시나리오 표"""
        copay = getattr(impact, '_copay_exemption', None)
        price = impact.hira_price

        from regscan.map.ingredient_bridge import ReimbursementStatus
        rows = []

        if impact.hira_status == ReimbursementStatus.REIMBURSED and price:
            rows.append(
                f"| 일반 급여 | 30% | ₩{price * 0.3:,.0f} |"
            )
            if copay:
                rate = copay["rate"]
                label = copay["label"]
                rows.append(
                    f"| {label} | {int(rate*100)}% | ₩{price * rate:,.0f} |"
                )
            rows.append(f"| 비급여(급여외 적응증) | 100% | ₩{price:,.0f} |")
        else:
            if copay:
                label = copay["label"]
                rate = copay["rate"]
                rows.append(f"| 향후 급여 ({label}) | {int(rate*100)}% | 등재 후 결정 |")
            rows.append("| 비급여 | 100% | 전액 환자 부담 |")
            rows.append("| KODC 긴급도입 | 전액 | 개별 신청 |")

        if not rows:
            return ""
        header = "| 시나리오 | 본인부담률 | 비고 |\n|---|---|---|"
        return header + "\n" + "\n".join(rows)

    def _compute_valid_competitors(self, impact: DomesticImpact) -> list[dict]:
        """경쟁약 목록을 간결한 형태로 변환"""
        raw = getattr(impact, '_competitors', []) or []
        result = []
        for comp in raw[:5]:
            entry = {"inn": comp.get("inn", "")}
            ds = comp.get("domestic_status", "")
            if ds:
                entry["domestic_status"] = ds
            if comp.get("indication"):
                entry["reason"] = comp["indication"][:100]
            result.append(entry)
        return result

    def _prepare_drug_data_v4(self, impact: DomesticImpact) -> str:
        """V4 FactComputer: 기존 데이터 + 사전 계산 팩트 필드"""
        # 기존 V3 데이터를 기반으로 구축
        data = json.loads(self._prepare_drug_data(impact))

        # V4 사전 계산 팩트 필드 추가
        data["d_day_text"] = self._compute_d_day_text(impact)
        data["fda_status_text"] = self._compute_status_text(
            impact.fda_approved, impact.fda_date,
        )
        data["ema_status_text"] = self._compute_status_text(
            impact.ema_approved, impact.ema_date,
        )
        data["mfds_status_text"] = self._compute_status_text(
            impact.mfds_approved, impact.mfds_date, impact.mfds_brand_name,
        )
        data["copay_scenario_text"] = self._compute_copay_scenario_text(impact)
        data["valid_competitors"] = self._compute_valid_competitors(impact)
        data["approval_summary_table"] = self._compute_approval_summary_table(impact)
        data["cost_scenario_table"] = self._compute_cost_scenario_table(impact)

        return json.dumps(data, ensure_ascii=False, indent=2)

    def _execute_tool(self, name: str, arguments: dict, impact: DomesticImpact) -> dict:
        """V4 툴콜링 핸들러: LLM이 요청한 tool을 Python이 즉시 계산"""
        if name == "get_regulatory_status":
            agency = arguments.get("agency", "").lower()
            if agency == "fda":
                return {
                    "approved": impact.fda_approved,
                    "date": impact.fda_date.isoformat() if impact.fda_date else None,
                    "status_text": self._compute_status_text(
                        impact.fda_approved, impact.fda_date,
                    ),
                }
            elif agency == "ema":
                return {
                    "approved": impact.ema_approved,
                    "date": impact.ema_date.isoformat() if impact.ema_date else None,
                    "status_text": self._compute_status_text(
                        impact.ema_approved, impact.ema_date,
                    ),
                }
            elif agency == "mfds":
                return {
                    "approved": impact.mfds_approved,
                    "date": impact.mfds_date.isoformat() if impact.mfds_date else None,
                    "brand_name": impact.mfds_brand_name,
                    "status_text": self._compute_status_text(
                        impact.mfds_approved, impact.mfds_date,
                        impact.mfds_brand_name,
                    ),
                }
            return {"error": f"Unknown agency: {agency}"}

        elif name == "calculate_patient_cost":
            drug_price = arguments.get("drug_price", 0)
            scenario = arguments.get("scenario", "")
            rates = {
                "general": 0.30,
                "cancer_special": 0.05,
                "rare_special": 0.10,
                "out_of_pocket": 1.0,
            }
            rate = rates.get(scenario, 1.0)
            return {
                "scenario": scenario,
                "rate": rate,
                "patient_cost": round(drug_price * rate),
                "drug_price": drug_price,
            }

        return {"error": f"Unknown tool: {name}"}

    async def _call_llm_v4(
        self, prompt: str, impact: DomesticImpact,
    ) -> str:
        """V4 LLM 호출 (툴콜링 지원, 스레드풀 기반)"""
        import asyncio
        return await asyncio.to_thread(
            self._call_llm_v4_sync, prompt, impact,
        )

    def _call_llm_v4_sync(self, prompt: str, impact: DomesticImpact) -> str:
        """V4 LLM 동기 호출 — OpenAI 툴콜링 지원, 나머지 프로바이더는 직접 호출"""
        client = self._get_client()

        if self.provider == "openai":
            return self._call_llm_v4_openai(client, prompt, impact)
        elif self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                max_tokens=3000,
                system=SYSTEM_PROMPT_V4,
                messages=[{"role": "user", "content": prompt}],
            )
            if not response.content:
                return ""
            return response.content[0].text
        elif self.provider == "gemini":
            full_prompt = f"{SYSTEM_PROMPT_V4}\n\n{prompt}"
            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
            )
            return response.text if response.text else ""
        else:
            return self._call_llm_v4_openai(client, prompt, impact)

    def _call_llm_v4_openai(
        self, client, prompt: str, impact: DomesticImpact,
    ) -> str:
        """OpenAI V4 호출 — 툴콜링 루프"""
        token_param = (
            {"max_completion_tokens": 3000}
            if "gpt-5" in self.model or "o1" in self.model
               or "o3" in self.model or "o4" in self.model
            else {"max_tokens": 3000}
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_V4},
            {"role": "user", "content": prompt},
        ]

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.V4_TOOLS,
            response_format={"type": "json_object"},
            **token_param,
        )

        if not response.choices:
            return ""

        # 툴콜링 루프 (최대 3회)
        max_rounds = 3
        for _ in range(max_rounds):
            msg = response.choices[0].message
            if not msg.tool_calls:
                break

            messages.append(msg)
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = self._execute_tool(
                    tc.function.name, args, impact,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.V4_TOOLS,
                response_format={"type": "json_object"},
                **token_param,
            )
            if not response.choices:
                return ""

        return response.choices[0].message.content or ""

    async def generate_v4(self, impact: DomesticImpact) -> BriefingReport:
        """V4 브리핑 리포트 생성 — 팩트/인사이트 분리"""
        drug_data = self._prepare_drug_data_v4(impact)
        prompt = BRIEFING_REPORT_PROMPT_V4.format(drug_data=drug_data)

        try:
            response_text = await self._call_llm_v4(prompt, impact)
            parsed = self._parse_json_response(response_text)

            return BriefingReport(
                inn=self._to_display_case(impact.inn),
                headline=parsed.get(
                    "headline",
                    f"{self._to_display_case(impact.inn)} 규제 동향",
                ),
                subtitle=parsed.get("subtitle", ""),
                key_points=parsed.get("key_points", []),
                global_section=parsed.get("global_insight_text", ""),
                domestic_section=parsed.get("domestic_insight_text", ""),
                medclaim_section=parsed.get("medclaim_action_text", ""),
                source_data=impact.to_dict(),
            )
        except Exception as e:
            logger.error("V4 리포트 생성 실패: %s", e)
            return self._generate_fallback(impact)

    async def generate(self, impact: DomesticImpact) -> BriefingReport:
        """브리핑 리포트 생성"""
        drug_data = self._prepare_drug_data(impact)
        prompt = BRIEFING_REPORT_PROMPT.format(drug_data=drug_data)

        try:
            response_text = await self._call_llm(prompt)
            parsed = self._parse_json_response(response_text)

            return BriefingReport(
                inn=self._to_display_case(impact.inn),
                headline=parsed.get("headline", f"{self._to_display_case(impact.inn)} 규제 동향"),
                subtitle=parsed.get("subtitle", ""),
                key_points=parsed.get("key_points", []),
                global_section=parsed.get("global_section", ""),
                domestic_section=parsed.get("domestic_section", ""),
                medclaim_section=parsed.get("medclaim_section", ""),
                global_heading=parsed.get("global_heading", ""),
                domestic_heading=parsed.get("domestic_heading", ""),
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
        """LLM API 호출 (스레드풀 기반 병렬 지원)"""
        import asyncio
        return await asyncio.to_thread(self._call_llm_sync, prompt)

    def _call_llm_sync(self, prompt: str) -> str:
        """LLM API 동기 호출"""
        client = self._get_client()

        if self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                max_tokens=3000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if not response.content:
                logger.warning("Anthropic API returned empty content list")
                return ""
            return response.content[0].text
        elif self.provider == "gemini":
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
            )
            if not response.text:
                logger.warning("Gemini API returned empty text")
                return ""
            return response.text
        else:
            # GPT-5 등 최신 모델은 max_completion_tokens 사용
            token_param = (
                {"max_completion_tokens": 3000}
                if "gpt-5" in self.model or "o1" in self.model or "o3" in self.model or "o4" in self.model
                else {"max_tokens": 3000}
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                **token_param,
            )
            if not response.choices:
                logger.warning("OpenAI API returned empty choices list")
                return ""
            return response.choices[0].message.content

    def _parse_json_response(self, text: str) -> dict:
        """LLM 응답에서 JSON 추출 (다단계 시도)"""
        candidates: list[str] = []

        # 1) ```json ... ``` 코드 펜스 추출
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                candidates.append(text[start:end].strip())

        # 2) ``` ... ``` 일반 코드 펜스
        if "```" in text and not candidates:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                candidates.append(text[start:end].strip())

        # 3) 원본 텍스트 그대로
        candidates.append(text.strip())

        # 4) 가장 바깥쪽 { ... } 브레이스 매칭
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            candidates.append(text[first_brace:last_brace + 1].strip())

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                continue

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

        inn = self._to_display_case(impact.inn)
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
                domestic_section += f" 심평원(HIRA) 급여 목록에 등재되어 있다.{price_str}"
            elif impact.hira_status == ReimbursementStatus.DELETED:
                domestic_section += (
                    " 과거 심평원(HIRA) 급여 목록에 등재된 이력이 있으나 현재는 삭제된 상태다. "
                    "급여 재등재 여부를 모니터링할 필요가 있다."
                )
            elif impact.hira_status == ReimbursementStatus.NOT_COVERED:
                domestic_section += " 심평원(HIRA) 급여 목록에 미등재 상태로, 사용 시 전액 환자 부담이다."
            elif impact.hira_status == ReimbursementStatus.NOT_FOUND:
                if impact.mfds_approved:
                    domestic_section += (
                        " 심평원(HIRA) 급여 정보는 현재 미확인 상태다. "
                        "허가 후 급여 등재까지는 통상 6개월~2년이 소요되며, "
                        "약가 협상 결과에 따라 환자 접근성이 결정된다."
                    )
                else:
                    domestic_section += " 심평원(HIRA) 급여 정보는 확인되지 않는다."

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
            inn=inn,
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


async def generate_briefing_v4(impact: DomesticImpact, provider: str = "openai") -> BriefingReport:
    """V4 브리핑 리포트 생성 편의 함수 (팩트/인사이트 분리)"""
    generator = LLMBriefingGenerator(provider=provider)
    return await generator.generate_v4(impact)


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
            ("openai", "gpt-5"),
            ("gemini", settings.GEMINI_MODEL),
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
