"""적응증 구조화 카드 — FDA/EMA 라벨 → LLM 정보 추출

LLM이 기사를 쓰는 게 아니라, 라벨 원문에서 구조화된 필드를 추출하는 역할.
hallucination 위험이 낮음 — ground truth(라벨 원문)가 입력으로 주어지기 때문.

Usage:
    card = await generate_indication_card("quizartinib", fda_data=drug["fda_data"], ema_data=drug["ema_data"])
    # card.disease = "acute myeloid leukemia (AML)"
    # card.biomarker = "FLT3-ITD"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# IndicationCard
# ════════════════════════════════════════════════════════════════════

@dataclass
class IndicationCard:
    """구조화된 적응증 카드."""
    inn: str

    # 구조화 적응증
    disease: str = ""                   # "acute myeloid leukemia (AML)"
    disease_subtype: str = ""           # "FLT3-ITD mutation positive"
    biomarker: str = ""                 # "FLT3-ITD"
    line_of_therapy: str = ""           # "first-line" / "second-line+" / "maintenance"
    combination: list[str] = field(default_factory=list)  # ["cytarabine", "anthracycline"]
    patient_population: str = ""        # "adult" / "pediatric"

    # 추적
    source: str = ""                    # "fda_label" / "ema_indication" / "both"
    source_text: str = ""               # 원문 span (검증용)
    extraction_confidence: float = 0.0  # 0.0~1.0
    needs_review: bool = True           # confidence < 0.8이면 True

    # 메타
    generated_at: str = ""

    def to_compact_dict(self) -> dict:
        """LLM 입력용 압축 dict."""
        d: dict[str, Any] = {"inn": self.inn}
        if self.disease:
            d["disease"] = self.disease
        if self.disease_subtype:
            d["subtype"] = self.disease_subtype
        if self.biomarker:
            d["biomarker"] = self.biomarker
        if self.line_of_therapy:
            d["line"] = self.line_of_therapy
        if self.combination:
            d["combination"] = self.combination
        if self.patient_population:
            d["population"] = self.patient_population
        if self.needs_review:
            d["needs_review"] = True
        return d


# ════════════════════════════════════════════════════════════════════
# FDA labels API
# ════════════════════════════════════════════════════════════════════

async def fetch_fda_indication(inn: str) -> str:
    """FDA drug/label.json에서 indications_and_usage 텍스트 가져오기."""
    url = "https://api.fda.gov/drug/label.json"
    params = {
        "search": f'openfda.generic_name:"{inn}"',
        "limit": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return ""
            data = r.json()
            results = data.get("results", [])
            if not results:
                return ""
            ind = results[0].get("indications_and_usage", [])
            return ind[0] if ind else ""
    except Exception as e:
        logger.debug("[IndicationCard] FDA label 조회 실패 (%s): %s", inn, e)
        return ""


# ════════════════════════════════════════════════════════════════════
# LLM 구조화 추출
# ════════════════════════════════════════════════════════════════════

INDICATION_EXTRACT_PROMPT = """Below is the official FDA/EMA label indication text for a drug.
Extract the following fields as JSON. If a field is not found in the text, leave it as empty string "".
Do NOT infer or guess — only extract what is explicitly stated.

Output JSON only, no markdown:
{{
  "disease": "disease name (English, include abbreviation)",
  "disease_subtype": "subtype/variant if specified",
  "biomarker": "biomarker if specified (e.g., FLT3-ITD, HER2+, EGFR, BRCA)",
  "line_of_therapy": "first-line / second-line / maintenance / adjuvant / neoadjuvant / salvage / unspecified",
  "combination": ["list of combination drugs if specified"],
  "patient_population": "adult / pediatric / both / unspecified"
}}

Indication text:
{indication_text}"""


async def _extract_indication_structured(indication_text: str) -> dict:
    """LLM으로 적응증 텍스트에서 구조화 필드 추출."""
    if not indication_text or len(indication_text) < 20:
        return {}

    prompt = INDICATION_EXTRACT_PROMPT.format(indication_text=indication_text[:2000])

    # OpenAI 우선
    if settings.OPENAI_API_KEY:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.WRITER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=500,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            return _parse_extraction_json(raw)
        except Exception as e:
            logger.debug("[IndicationCard] OpenAI 추출 실패: %s", e)

    # Anthropic fallback
    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            return _parse_extraction_json(raw)
        except Exception as e:
            logger.debug("[IndicationCard] Anthropic 추출 실패: %s", e)

    return {}


def _parse_extraction_json(raw: str) -> dict:
    """LLM 응답에서 JSON 추출."""
    import re
    # ```json 블록
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("[IndicationCard] JSON 파싱 실패: %s", raw[:200])
        return {}


# ════════════════════════════════════════════════════════════════════
# 메인 생성 함수
# ════════════════════════════════════════════════════════════════════

async def generate_indication_card(
    inn: str,
    fda_data: dict | None = None,
    ema_data: dict | None = None,
) -> IndicationCard:
    """약물 → IndicationCard 생성.

    1) FDA labels API에서 indications_and_usage 가져오기
    2) EMA therapeutic_indication 가져오기
    3) 둘 중 더 긴 텍스트를 LLM에 넘겨 구조화 추출
    """
    fda_data = fda_data or {}
    ema_data = ema_data or {}

    # 1) 적응증 텍스트 확보
    fda_text = await fetch_fda_indication(inn)
    ema_text = (ema_data.get("therapeutic_indication", "") or "")

    # 더 긴 텍스트 선택 (둘 다 있으면 합침)
    if fda_text and ema_text:
        indication_text = f"[FDA] {fda_text}\n\n[EMA] {ema_text}"
        source = "both"
    elif fda_text:
        indication_text = fda_text
        source = "fda_label"
    elif ema_text:
        indication_text = ema_text
        source = "ema_indication"
    else:
        return IndicationCard(
            inn=inn,
            source="none",
            needs_review=True,
            generated_at=datetime.now().isoformat(),
        )

    # 2) LLM 구조화 추출
    extracted = await _extract_indication_structured(indication_text)

    if not extracted:
        return IndicationCard(
            inn=inn,
            source=source,
            source_text=indication_text[:500],
            needs_review=True,
            generated_at=datetime.now().isoformat(),
        )

    # 3) confidence 계산 — 비어있지 않은 필드 비율
    total_fields = 6
    filled = sum(1 for v in [
        extracted.get("disease", ""),
        extracted.get("disease_subtype", ""),
        extracted.get("biomarker", ""),
        extracted.get("line_of_therapy", ""),
        extracted.get("combination", []),
        extracted.get("patient_population", ""),
    ] if v)
    confidence = filled / total_fields

    combo = extracted.get("combination", [])
    if isinstance(combo, str):
        combo = [combo] if combo else []

    return IndicationCard(
        inn=inn,
        disease=extracted.get("disease", ""),
        disease_subtype=extracted.get("disease_subtype", ""),
        biomarker=extracted.get("biomarker", ""),
        line_of_therapy=extracted.get("line_of_therapy", ""),
        combination=combo,
        patient_population=extracted.get("patient_population", ""),
        source=source,
        source_text=indication_text[:500],
        extraction_confidence=round(confidence, 2),
        needs_review=confidence < 0.5,
        generated_at=datetime.now().isoformat(),
    )


async def generate_indication_cards(
    drugs: list[dict],
) -> dict[str, IndicationCard]:
    """여러 약물 일괄 IndicationCard 생성. INN → IndicationCard dict."""
    cards: dict[str, IndicationCard] = {}
    for drug in drugs:
        inn = (drug.get("inn") or "").strip().upper()
        if not inn or len(inn) < 3:
            continue
        card = await generate_indication_card(
            inn,
            fda_data=drug.get("fda_data"),
            ema_data=drug.get("ema_data"),
        )
        cards[inn] = card
        logger.debug(
            "[IndicationCard] %s: disease=%s, biomarker=%s, conf=%.2f",
            inn, card.disease, card.biomarker, card.extraction_confidence,
        )
    logger.info("[IndicationCard] %d건 생성 완료", len(cards))
    return cards
