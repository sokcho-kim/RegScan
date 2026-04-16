"""트렌드 분석기 — Step 2: 팩트카드 → LLM → 트렌드/교차분석

팩트카드(Step 1)를 입력으로 받아 패턴/교차신호/핵심 인사이트를 도출.
LLM은 팩트를 생성하지 않음 — 이미 확정된 팩트에서 패턴만 읽음.

Usage:
    cards = generate_fact_cards(drugs)
    trends = await analyze_trends(cards, stream_name="therapeutic_area")
    # trends = {"trends": [...], "cross_signals": [...], "key_insight": "..."}
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from regscan.stream.fact_card import FactCard

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 프롬프트
# ════════════════════════════════════════════════════════════════════

TREND_SYSTEM_PROMPT = """당신은 제약·바이오 규제 데이터 분석가입니다.
아래 팩트카드는 코드가 생성한 검증된 사실입니다. 당신이 할 일:

1. 팩트카드 간 **패턴**을 식별하라 (적응증 집중, 급여 격차, 허가 공백 등)
2. **교차 신호**를 찾아라 (여러 약물에 반복되는 현상)
3. **핵심 인사이트** 1문장을 도출하라

규칙:
- 약물의 승인 상태, 가격, 허가 여부를 직접 기술하지 마라. 그건 이미 팩트카드에 있다.
- 팩트카드에 없는 날짜, 가격, 상태를 만들지 마라.
- "패턴이 뭔가"만 답하라.
- guardrail이 붙은 약물은 "확인 필요" 수준으로만 언급하라.

오늘 날짜: {today}
"""

TREND_USER_PROMPT = """[FACT CARDS — {n}건, {stream_name}]

{fact_cards_json}

위 팩트카드에서 패턴을 분석하라. 출력은 반드시 아래 JSON 형식만:

{{
  "trends": [
    {{"pattern": "패턴 설명", "drugs": ["INN1", "INN2"], "significance": "왜 중요한가"}}
  ],
  "cross_signals": [
    {{"signal": "교차 신호 설명", "drugs": ["INN1"], "signal_strength": "strong/moderate/weak"}}
  ],
  "key_insight": "경영진이 알아야 할 핵심 1문장",
  "guardrailed_drugs": ["확인 필요 약물 INN 목록"]
}}"""


# ════════════════════════════════════════════════════════════════════
# 분석 함수
# ════════════════════════════════════════════════════════════════════

async def analyze_trends(
    fact_cards: list[FactCard],
    stream_name: str = "all",
    today: str | None = None,
) -> dict[str, Any]:
    """팩트카드 → LLM → 트렌드/교차분석.

    Args:
        fact_cards: Step 1에서 생성된 FactCard 리스트
        stream_name: "therapeutic_area", "innovation", "external", "unified" 등
        today: YYYY-MM-DD

    Returns:
        {"trends": [...], "cross_signals": [...], "key_insight": "...", "guardrailed_drugs": [...]}
    """
    if not fact_cards:
        return _empty_result()

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    # compact JSON 조립 (~10줄/약물)
    compact_list = [card.to_compact_dict() for card in fact_cards]
    fact_cards_json = json.dumps(compact_list, ensure_ascii=False, indent=2)

    system_prompt = TREND_SYSTEM_PROMPT.format(today=today)
    user_prompt = TREND_USER_PROMPT.format(
        n=len(fact_cards),
        stream_name=stream_name,
        fact_cards_json=fact_cards_json,
    )

    # LLM 호출 (LLM 실패만 fallback, 그 외 버그는 전파)
    try:
        raw = await _call_llm(system_prompt, user_prompt)
    except Exception as e:
        logger.warning("[TrendAnalyzer] LLM 호출 실패: %s", e)
        raw = None

    if raw is not None:
        result = _parse_trend_json(raw)
    else:
        result = _fallback_trends(fact_cards)

    # 가드레일 약물 자동 추가
    guardrailed = [c.inn for c in fact_cards if c.is_guardrailed]
    if guardrailed:
        existing = result.get("guardrailed_drugs", [])
        for g in guardrailed:
            if g not in existing:
                existing.append(g)
        result["guardrailed_drugs"] = existing

    result["_meta"] = {
        "stream_name": stream_name,
        "card_count": len(fact_cards),
        "input_chars": len(fact_cards_json),
        "generated_at": datetime.now().isoformat(),
    }

    return result


# ════════════════════════════════════════════════════════════════════
# LLM 호출
# ════════════════════════════════════════════════════════════════════

async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """LLM 호출 — GPT → Gemini → Anthropic fallback.

    briefing.py의 _call_llm과 동일한 fallback 체인이지만
    max_tokens를 1500으로 제한 (트렌드 분석은 짧은 출력).
    """
    from regscan.config import settings

    # 1차: OpenAI
    if settings.OPENAI_API_KEY:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.WRITER_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=1500,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.debug("[TrendAnalyzer] OpenAI 실패: %s", e)

    # 2차: Gemini (동기 SDK → run_in_executor로 이벤트루프 보호)
    if settings.GEMINI_API_KEY:
        try:
            import asyncio
            from google import genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

            def _sync_gemini():
                return client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=full_prompt,
                )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, _sync_gemini)
            return response.text or ""
        except Exception as e:
            logger.debug("[TrendAnalyzer] Gemini 실패: %s", e)

    # 3차: Anthropic
    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.debug("[TrendAnalyzer] Anthropic 실패: %s", e)

    raise RuntimeError("LLM API 키 미설정")


# ════════════════════════════════════════════════════════════════════
# 파싱/폴백
# ════════════════════════════════════════════════════════════════════

def _parse_trend_json(raw: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 추출."""
    # ```json ... ``` 블록 추출
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        # 첫 { ~ 마지막 }
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]

    try:
        result = json.loads(raw)
        # 필수 키 확인
        if "trends" not in result:
            result["trends"] = []
        if "cross_signals" not in result:
            result["cross_signals"] = []
        if "key_insight" not in result:
            result["key_insight"] = ""
        if "guardrailed_drugs" not in result:
            result["guardrailed_drugs"] = []
        return result
    except json.JSONDecodeError:
        logger.warning("[TrendAnalyzer] JSON 파싱 실패, raw=%s", raw[:500])
        return _empty_result()


def _fallback_trends(fact_cards: list[FactCard]) -> dict[str, Any]:
    """LLM 실패 시 코드 기반 기본 트렌드 분석."""
    guardrailed = [c.inn for c in fact_cards if c.is_guardrailed]
    reimbursed = [c.inn for c in fact_cards if "급여 등재" in c.hira_phrase]
    unmatched = [c.inn for c in fact_cards if "매핑 실패" in c.hira_phrase or "미확인" in c.hira_phrase]

    trends = []
    if reimbursed:
        trends.append({
            "pattern": f"급여 등재 확인 {len(reimbursed)}건",
            "drugs": reimbursed,
            "significance": "처방·청구 경로 확보",
        })
    if unmatched:
        trends.append({
            "pattern": f"심평원 데이터 미확인/매핑 실패 {len(unmatched)}건",
            "drugs": unmatched,
            "significance": "급여/가격 단정 불가 — 수동 확인 필요",
        })

    key_insight = f"전체 {len(fact_cards)}건 중 급여 확인 {len(reimbursed)}건, 미확인 {len(unmatched)}건"

    return {
        "trends": trends,
        "cross_signals": [],
        "key_insight": key_insight,
        "guardrailed_drugs": guardrailed,
    }


def _empty_result() -> dict[str, Any]:
    return {
        "trends": [],
        "cross_signals": [],
        "key_insight": "",
        "guardrailed_drugs": [],
    }
