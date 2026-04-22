"""기사 생성 에이전트 파이프라인 v2

4-Agent Loop (전문지 기사체):
  1. Editor-in-Chief: 핵심 이슈 1개 중심 스토리 선별
  2. Reporter: 사실→의미→영향→전망 구조의 기사 초안
  3. Fact-Checker: 결측 제거 + 지시문 제거 + 수치 검증
  4. Copy-Editor: 제목-리드-본문 메시지 일치 + 최종 정제

품질 기준: docs/research/article-reference/article-quality-spec.md
레퍼런스: 약업신문 + 뉴시스 산업 기사 톤
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from regscan.config import settings

logger = logging.getLogger(__name__)


# ── LLM 호출 공통 ──

async def _call_llm(system: str, user: str, temperature: float = 0.3) -> str:
    """LLM 호출 (OpenAI 우선, Gemini 폴백)"""
    if settings.OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=getattr(settings, "LLM_MODEL", "gpt-5.2"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("OpenAI 호출 실패: %s", e)

    if getattr(settings, "GEMINI_API_KEY", None):
        try:
            from google import genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
                contents=f"{system}\n\n{user}",
            )
            return resp.text or ""
        except Exception as e:
            logger.warning("Gemini 호출 실패: %s", e)

    raise RuntimeError("LLM 키 없음")


def _extract_json(text: str) -> dict | list:
    """LLM 응답에서 JSON 추출"""
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        return json.loads(match.group(1))
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    raise ValueError(f"JSON 추출 실패: {text[:200]}")


# ══════════════════════════════════════════════
# Agent 1: 편집장 — 스토리 선별
# ══════════════════════════════════════════════

EDITOR_CHIEF_SYSTEM = """당신은 의약품 전문 매체의 편집장입니다.
독자: 병원 의사, 약제팀, 행정인력.

## 임무
26개 데이터 소스에서 수집된 시그널 중 **기사 가치가 있는 스토리 3~5개**를 선별합니다.

## 핵심 원칙: "1기사 = 1이슈"
각 스토리는 **단 하나의 핵심 이슈**를 중심으로 구성합니다.
여러 시그널을 묶되, 하나의 메시지로 수렴해야 합니다.

## 선별 기준 (우선순위)
1. **"왜 지금?"** — 시의성이 있는가
2. **"누가 영향받나?"** — 독자(병원)에 직접 영향이 있는가
3. **"숫자가 있는가?"** — 약물명, 건수, 날짜 등 구체적 팩트가 충분한가
4. **"비교 가능한가?"** — "기존 대비" 프레임을 만들 수 있는가

## 반드시 제외
- 데이터가 빈약한 소스 (필드가 비어있거나 건수가 1~2건뿐인 경우)
- "데이터 부족"이나 "추가 확인 필요"로 귀결될 수밖에 없는 소스
- 독자와 무관한 순수 해외 이벤트 (국내 맥락 연결 불가)

## 출력
```json
[
  {
    "story_id": 1,
    "core_message": "이 기사의 핵심 메시지 1문장",
    "headline_draft": "헤드라인 초안 (25자 이내, 숫자 포함)",
    "angle": "어떤 관점으로 쓸 것인가 (1문장)",
    "key_facts": ["구체적 팩트 1", "팩트 2", "팩트 3"],
    "sources_used": ["PMDA_APPROVAL"],
    "why_now": "왜 지금 기사인가 (1문장)",
    "priority": "high/medium"
  }
]
```"""


async def agent_editor_chief(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """Agent 1: 시그널 → 스토리 선별"""
    from regscan.stream.intelligence_signals import format_for_prompt

    signal_text = ""
    for src_type, sigs in signals.items():
        signal_text += format_for_prompt(src_type, sigs) + "\n\n"

    user_prompt = f"""오늘 날짜: {datetime.now().strftime('%Y-%m-%d')}

수집된 전체 시그널:

{signal_text}

위에서 기사 가치가 있는 스토리 3~5개를 선별하세요.
데이터가 빈약한 소스는 반드시 제외하세요."""

    response = await _call_llm(EDITOR_CHIEF_SYSTEM, user_prompt)
    stories = _extract_json(response)
    logger.info("[편집장] %d개 스토리 선별", len(stories))
    return stories


# ══════════════════════════════════════════════
# Agent 2: 기자 — 초안 작성
# ══════════════════════════════════════════════

REPORTER_SYSTEM = """당신은 약업신문·뉴시스 수준의 의약품 전문 기자입니다.
독자: 병원 의사, 약제팀, 행정인력.

## 기사 구조 (반드시 이 순서)
1. **리드** (2문장): 핵심 사실 + 숫자 + 왜 중요한지. 제목과 같은 메시지.
2. **대표 사례** (1~2단락): 가장 강한 구체적 예시. 약물명, 적응증, 날짜, 수치.
3. **맥락/비교** (1단락): 기존 대비 뭐가 달라졌는지. "~와 비교하면", "기존에는~"
4. **확장 의미** (1단락): 국내 시장/제도/개발에 미치는 영향.
5. **마무리** (1~2문장): 전망. 과장 없이. 관전 포인트 1개.

## 문체 규칙
- 보도체: "~로 나타났다", "~로 풀이된다", "~전망이다"
- 수치가 근거: 주장마다 구체적 숫자가 붙어야 한다
- 일본어/영어 원문은 한글 번역 후 괄호에 원문 병기
- 간결하고 건조하게. 감탄사, 의문문 사용하지 않음
- 800~1200자 분량

## 절대 금지 (위반 시 기사 불합격)
- "데이터 부족", "확인 불가", "분석 불가" → 모르면 안 쓴다
- "약제팀은 ~하라", "즉시 점검하라" → 실무 지시 금지
- "RA/MA는", "병원은 ~해야" → 특정 대상 지시 금지
- "그래서 뭐?", "[FACT DATA]" → 메타 코멘트 금지
- 데이터에 없는 내용 추측
- "전망이다" 2회 이상 반복

## 좋은 리드 예시
> 일본 PMDA가 3월 23일 엔허투(트라스투주맙 데룩스테칸)의 HER2 양성 고형암 적응증을 추가 승인하면서, 다암종 정밀의료 전략이 다시 주목받고 있다. 같은 날 승인된 20건 중 희귀질환 신약이 5건을 차지해 '희귀·항암 집중' 흐름이 뚜렷했다.

## 나쁜 리드 예시
> PMDA는 엔허투를 승인했다. 향후 관련 변화가 주목된다.

## 출력
```json
{
  "headline": "최종 헤드라인 (25자 이내, 숫자 포함)",
  "subheadline": "부제 (40자 이내)",
  "body": "전체 기사 본문 (리드~마무리 포함, 단락 사이 빈 줄)"
}
```"""


async def agent_reporter(
    story: dict,
    signals: dict[str, list[dict]],
) -> dict:
    """Agent 2: 스토리 → 기사 초안"""
    from regscan.stream.intelligence_signals import format_for_prompt

    sources_used = story.get("sources_used", [])
    relevant_data = ""
    for src in sources_used:
        if src in signals:
            relevant_data += format_for_prompt(src, signals[src]) + "\n\n"
    if not relevant_data:
        for src_type, sigs in list(signals.items())[:3]:
            relevant_data += format_for_prompt(src_type, sigs) + "\n\n"

    user_prompt = f"""## 편집장 지시

핵심 메시지: {story.get('core_message', '')}
헤드라인 초안: {story.get('headline_draft', '')}
기사 각도: {story.get('angle', '')}
왜 지금: {story.get('why_now', '')}
핵심 팩트: {json.dumps(story.get('key_facts', []), ensure_ascii=False)}

## 원본 데이터

{relevant_data}

위 데이터만 사용하여 기사를 작성하세요. 데이터에 없는 내용은 절대 쓰지 마세요."""

    response = await _call_llm(REPORTER_SYSTEM, user_prompt)
    article = _extract_json(response)
    logger.info("[기자] 초안: %s", article.get("headline", "")[:30])
    return article


# ══════════════════════════════════════════════
# Agent 3: 팩트체커 — 검증 + 결측 제거
# ══════════════════════════════════════════════

FACT_CHECKER_SYSTEM = """당신은 의약품 전문 매체의 팩트체커입니다.

## 검토 항목 (체크리스트)

### 하드 룰 위반 (1개라도 있으면 해당 문장 삭제/수정)
- [ ] "데이터 부족", "확인 불가", "분석 불가" 포함 → 해당 문장 삭제
- [ ] "약제팀은", "RA/MA는", "병원은 ~해야" → 해당 문장 삭제
- [ ] "즉시 점검하라", "재검토해야 한다" → 해당 문장 삭제
- [ ] "그래서 뭐?", "[FACT DATA]" → 해당 문장 삭제
- [ ] "전망이다" 2회 이상 → 1회로 축소, 나머지는 다른 표현

### 팩트 검증
- [ ] 기사의 수치가 원본 데이터와 일치하는가?
- [ ] 약물명·적응증·날짜가 원본과 일치하는가?
- [ ] 데이터에 없는 내용을 추측하고 있지 않은가?

### 구조 검증
- [ ] 리드가 2문장 이내인가?
- [ ] 리드에 숫자가 1개 이상 있는가?
- [ ] 제목과 리드의 메시지가 일치하는가?

## 출력
수정된 기사를 반환하되, 수정 사항을 명시:
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "...",
  "corrections": ["수정 1: ~문장 삭제 (결측 노출)", "수정 2: ~"]
}
```"""


async def agent_fact_checker(
    article: dict,
    original_data: str,
) -> dict:
    """Agent 3: 기사 팩트체크 + 하드 룰 검증"""
    user_prompt = f"""## 기사 초안

{json.dumps(article, ensure_ascii=False, indent=2)}

## 원본 데이터 (검증 기준)

{original_data[:4000]}

위 체크리스트에 따라 검토하고 수정해주세요."""

    response = await _call_llm(FACT_CHECKER_SYSTEM, user_prompt, temperature=0.1)
    checked = _extract_json(response)
    corrections = checked.get("corrections", [])
    logger.info("[팩트체커] %d건 수정", len(corrections))
    return checked


# ══════════════════════════════════════════════
# Agent 4: 편집자 — 최종 정제
# ══════════════════════════════════════════════

COPY_EDITOR_SYSTEM = """당신은 의약품 전문 매체의 최종 편집자입니다.

## 편집 기준

### 제목-리드-본문 메시지 일치
제목이 말하는 것, 리드가 말하는 것, 본문이 전개하는 것이 하나의 메시지를 향해야 합니다.
제목은 세게, 리드는 팩트로, 본문은 깊이로.

### 헤드라인
- 25자 이내
- 숫자 1개 이상 포함
- 핵심 이슈가 바로 보여야 함
- 예시: "PMDA 3월 승인 20건, 희귀·항암 집중"
- 예시: "국회 4월 보건 법안 15건, 의료법 개정 집중"

### 부제
- 40자 이내
- 헤드라인의 보완 정보

### 본문 흐름
- 리드 → 사례 → 맥락 → 영향 → 마무리 순서 확인
- 단락 간 자연스러운 연결 ("이에 따라", "한편", "반면")
- 사실→의미 흐름 (사실만 나열하면 수정)

### 분량
- 800~1200자
- 너무 짧으면 사례/맥락 보강 지시
- 너무 길면 중복 삭제

## 출력
최종 기사:
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "...",
  "editor_note": "편집 포인트 1줄 요약"
}
```"""


async def agent_copy_editor(article: dict) -> dict:
    """Agent 4: 최종 편집 — 메시지 일치 + 흐름 + 분량"""
    user_prompt = f"""다음 기사를 최종 편집해주세요.

{json.dumps(article, ensure_ascii=False, indent=2)}

제목-리드-본문의 메시지가 일치하는지 확인하고, 흐름을 다듬어주세요.
800~1200자 분량으로 조절해주세요."""

    response = await _call_llm(COPY_EDITOR_SYSTEM, user_prompt, temperature=0.2)
    final = _extract_json(response)
    logger.info("[편집자] 최종: %s", final.get("headline", "")[:30])
    return final


# ══════════════════════════════════════════════
# 전체 파이프라인
# ══════════════════════════════════════════════

async def generate_articles(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """4-Agent 기사 생성 파이프라인 v2.

    Args:
        signals: extract_signals()의 결과

    Returns:
        최종 기사 리스트
    """
    from regscan.stream.intelligence_signals import format_for_prompt

    logger.info("=== 기사 생성 파이프라인 v2 시작 ===")

    # Agent 1: 편집장
    stories = await agent_editor_chief(signals)
    if not stories:
        logger.warning("편집장이 스토리를 선별하지 않음")
        return []

    articles = []
    for story in stories:
        try:
            # Agent 2: 기자
            draft = await agent_reporter(story, signals)

            # 원본 데이터 (팩트체크용)
            sources_used = story.get("sources_used", [])
            original_data = ""
            for src in sources_used:
                if src in signals:
                    original_data += format_for_prompt(src, signals[src]) + "\n"

            # Agent 3: 팩트체커
            checked = await agent_fact_checker(draft, original_data)

            # Agent 4: 편집자
            final = await agent_copy_editor(checked)

            final["story_id"] = story.get("story_id", 0)
            final["core_message"] = story.get("core_message", "")
            final["sources_used"] = sources_used
            final["priority"] = story.get("priority", "medium")
            final["generated_at"] = datetime.now().isoformat()

            articles.append(final)
            logger.info(
                "  기사 #%d 완성: %s",
                story.get("story_id", 0),
                final.get("headline", "")[:40],
            )

        except Exception as e:
            logger.warning(
                "  기사 #%d 생성 실패: %s",
                story.get("story_id", 0), e,
            )

    logger.info("=== 기사 생성 완료: %d건 ===", len(articles))
    return articles
