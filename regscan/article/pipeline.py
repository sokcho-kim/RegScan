"""기사 생성 에이전트 파이프라인

4-Agent Loop:
  1. Editor-in-Chief: 시그널 선별 → 스토리 3~5개
  2. Reporter: 각 스토리 초안 (약업신문 톤)
  3. Fact-Checker: 수치 검증 + 결측 제거
  4. Copy-Editor: 헤드라인 정제 + 흐름 다듬기
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from regscan.config import settings

logger = logging.getLogger(__name__)


# ── LLM 호출 공통 ──

async def _call_llm(system: str, user: str) -> str:
    """LLM 호출 (OpenAI 우선, Gemini 폴백)"""
    # OpenAI
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
                temperature=0.3,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("OpenAI 호출 실패: %s", e)

    # Gemini fallback
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
    # ```json ... ``` 블록
    import re
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        return json.loads(match.group(1))
    # 직접 파싱 시도
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    raise ValueError(f"JSON 추출 실패: {text[:200]}")


# ── Agent 1: 편집장 ──

EDITOR_CHIEF_SYSTEM = """당신은 의약품 전문 매체의 편집장입니다.

## 역할
26개 데이터 소스에서 수집된 시그널을 검토하고, 오늘 기사로 발행할 스토리 3~5개를 선별합니다.

## 선별 기준
1. **뉴스 가치**: 독자(병원 의사, 약제팀, 행정인력)가 알아야 하는 정보인가?
2. **팩트 충분성**: 구체적 수치, 약물명, 날짜가 있는가? 근거 부족하면 제외.
3. **시의성**: 최근 발생한 이벤트인가?
4. **독자 임팩트**: 병원 운영, 약제 관리, 급여에 영향을 주는가?

## 제외 기준
- 데이터가 불완전한 소스 (빈 필드, "불명" 등)
- 이미 널리 알려진 정보
- 독자와 무관한 정보 (순수 학술, 해외만 해당)

## 출력 형식
```json
[
  {
    "story_id": 1,
    "headline_draft": "헤드라인 초안 (30자 이내)",
    "angle": "기사 각도 (어떤 관점으로 쓸 것인가)",
    "key_data": ["핵심 데이터 포인트 1", "포인트 2"],
    "sources_used": ["PMDA_APPROVAL", "ASSEMBLY_BILL"],
    "priority": "high/medium"
  }
]
```"""


async def agent_editor_chief(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """Agent 1: 시그널 → 스토리 선별"""
    from regscan.stream.intelligence_signals import format_for_prompt

    # 전체 시그널을 텍스트로
    signal_text = ""
    for src_type, sigs in signals.items():
        signal_text += format_for_prompt(src_type, sigs) + "\n\n"

    user_prompt = f"""오늘 날짜: {datetime.now().strftime('%Y-%m-%d')}

다음은 오늘 수집된 전체 시그널입니다:

{signal_text}

위 시그널에서 기사 가치가 있는 스토리 3~5개를 선별해주세요."""

    response = await _call_llm(EDITOR_CHIEF_SYSTEM, user_prompt)
    stories = _extract_json(response)
    logger.info("[Agent1 편집장] %d개 스토리 선별", len(stories))
    return stories


# ── Agent 2: 기자 ──

REPORTER_SYSTEM = """당신은 약업신문 스타일의 의약품 전문 기자입니다.

## 기사 톤 & 스타일 (약업신문 기준)
- **객관적 보도체**: "~로 나타났다", "~로 풀이된다", "~전망이다"
- **수치 중심**: 구체적 숫자로 팩트를 전달 (건수, 비율, 금액)
- **비교 프레임**: "기존 대비", "전년 동기 대비" 등 맥락 제공
- **실무 지시 금지**: "~해야 한다", "~하라" 등 지시형 문장 사용 금지
- **결측 노출 금지**: "데이터 부족", "확인 불가" 등의 표현 사용 금지. 모르면 안 쓴다.
- **일본어/영어 원문**: 반드시 한글로 번역. 원문은 괄호 안에 병기.

## 기사 구조
1. **리드** (1~2문장): 핵심 팩트 + 수치. "무엇이 어떻게 됐다"
2. **본문** (3~4단락):
   - 구체적 사례/데이터
   - 배경/맥락
   - 산업/시장 영향
3. **마무리** (1~2문장): 전망 또는 시사점

## 절대 금지
- "약제팀은", "RA/MA는", "병원은" 등 특정 대상에 대한 지시
- "즉시 점검하라", "재검토해야 한다" 등 명령형
- "그래서 뭐?" 같은 구어체
- "데이터 부족으로 판단 불가" 같은 메타 코멘트
- 데이터에 없는 내용 추측

## 출력 형식
```json
{
  "headline": "최종 헤드라인 (25자 이내)",
  "subheadline": "부제 (40자 이내)",
  "lead": "리드문 (2문장)",
  "body": "본문 (3~4단락, 각 단락 사이 빈 줄)",
  "closing": "마무리 (1~2문장)"
}
```"""


async def agent_reporter(
    story: dict,
    signals: dict[str, list[dict]],
) -> dict:
    """Agent 2: 스토리 → 기사 초안"""
    from regscan.stream.intelligence_signals import format_for_prompt

    # 해당 스토리에 사용할 소스 데이터만 추출
    sources_used = story.get("sources_used", [])
    relevant_data = ""
    for src in sources_used:
        if src in signals:
            relevant_data += format_for_prompt(src, signals[src]) + "\n\n"

    # 소스가 없으면 전체 중 상위 데이터
    if not relevant_data:
        for src_type, sigs in list(signals.items())[:3]:
            relevant_data += format_for_prompt(src_type, sigs) + "\n\n"

    user_prompt = f"""다음 기사를 작성해주세요.

## 스토리 지시
- 헤드라인 초안: {story.get('headline_draft', '')}
- 기사 각도: {story.get('angle', '')}
- 핵심 데이터: {json.dumps(story.get('key_data', []), ensure_ascii=False)}

## 원본 데이터
{relevant_data}

위 데이터를 기반으로 약업신문 스타일의 기사를 작성해주세요.
데이터에 없는 내용은 절대 쓰지 마세요."""

    response = await _call_llm(REPORTER_SYSTEM, user_prompt)
    article = _extract_json(response)
    logger.info("[Agent2 기자] 초안 작성: %s", article.get("headline", "")[:30])
    return article


# ── Agent 3: 팩트체커 ──

FACT_CHECKER_SYSTEM = """당신은 의약품 전문 매체의 팩트체커입니다.

## 역할
기자가 작성한 기사 초안을 검토하고 문제를 수정합니다.

## 검토 항목
1. **수치 정합성**: 원본 데이터와 기사의 수치가 일치하는가?
2. **결측 노출**: "데이터 부족", "확인 불가" 등이 남아있으면 해당 문장 삭제
3. **지시형 문장**: "~해야 한다", "~하라" → 보도체로 수정
4. **일본어/영어**: 한글 번역 누락 확인
5. **추측성 표현**: 데이터에 근거 없는 주장 삭제

## 출력 형식
수정된 기사를 동일한 JSON 구조로 반환:
```json
{
  "headline": "...",
  "subheadline": "...",
  "lead": "...",
  "body": "...",
  "closing": "...",
  "fact_check_notes": ["수정 사항 1", "수정 사항 2"]
}
```"""


async def agent_fact_checker(
    article: dict,
    original_data: str,
) -> dict:
    """Agent 3: 기사 팩트체크 + 수정"""
    user_prompt = f"""다음 기사를 팩트체크해주세요.

## 기사 초안
{json.dumps(article, ensure_ascii=False, indent=2)}

## 원본 데이터 (검증 기준)
{original_data[:3000]}

기사의 수치/팩트가 원본과 일치하는지 확인하고, 문제가 있으면 수정해주세요."""

    response = await _call_llm(FACT_CHECKER_SYSTEM, user_prompt)
    checked = _extract_json(response)
    notes = checked.get("fact_check_notes", [])
    logger.info("[Agent3 팩트체커] %d건 수정", len(notes))
    return checked


# ── Agent 4: 편집자 ──

COPY_EDITOR_SYSTEM = """당신은 의약품 전문 매체의 최종 편집자입니다.

## 역할
팩트체크를 통과한 기사의 가독성과 흐름을 최종 다듬습니다.

## 편집 기준
1. **헤드라인**: 25자 이내, 숫자+키워드, 기사 핵심을 한눈에
2. **부제**: 40자 이내, 헤드라인 보완 정보
3. **리드**: 2문장. 첫 문장에 가장 중요한 팩트.
4. **본문 흐름**: 사례→맥락→영향 순서. 단락 간 자연스러운 연결.
5. **마무리**: 전망 1~2문장. 열린 결말.
6. **문체**: 간결하고 건조한 보도체. 감탄사/의문문 지양.

## 출력
최종 기사를 동일 JSON으로 반환:
```json
{
  "headline": "...",
  "subheadline": "...",
  "lead": "...",
  "body": "...",
  "closing": "..."
}
```"""


async def agent_copy_editor(article: dict) -> dict:
    """Agent 4: 최종 편집"""
    user_prompt = f"""다음 기사를 최종 편집해주세요.

{json.dumps(article, ensure_ascii=False, indent=2)}

헤드라인 25자 이내, 부제 40자 이내로 정제하고, 본문 흐름을 다듬어주세요."""

    response = await _call_llm(COPY_EDITOR_SYSTEM, user_prompt)
    final = _extract_json(response)
    logger.info("[Agent4 편집자] 최종: %s", final.get("headline", "")[:30])
    return final


# ── 전체 파이프라인 ──

async def generate_articles(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """4-Agent 기사 생성 파이프라인.

    Args:
        signals: extract_signals()의 결과

    Returns:
        최종 기사 리스트
    """
    from regscan.stream.intelligence_signals import format_for_prompt

    logger.info("=== 기사 생성 파이프라인 시작 ===")

    # Agent 1: 편집장 — 스토리 선별
    stories = await agent_editor_chief(signals)
    if not stories:
        logger.warning("편집장이 스토리를 선별하지 않음")
        return []

    # Agent 2~4: 각 스토리별 기사 작성
    articles = []
    for story in stories:
        try:
            # Agent 2: 기자 — 초안
            draft = await agent_reporter(story, signals)

            # 원본 데이터 텍스트 (팩트체크용)
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
