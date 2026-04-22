"""기사 품질 가드레일 — 코드 레벨 전처리/후처리

LLM 비결정성을 코드로 보정.
- 전처리: 편집장에게 넘기기 전 시그널 필터
- 중간검증: 편집장 출력에서 소스 중복 제거
- 후처리: 금지표현 삭제 + 기관명 치환 + 메타언급 제거
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════
# 1. 전처리: 시그널 필터
# ══════════════════════════════════════════════

MIN_SIGNALS_FOR_ARTICLE = 5  # 이 수 미만이면 편집장에게 안 넘김


def filter_signals(
    signals: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """기사 가치 없는 소스 제거.

    Returns:
        필터링된 시그널 (5건 미만 소스 제거)
    """
    filtered = {}
    for src, sigs in signals.items():
        if len(sigs) >= MIN_SIGNALS_FOR_ARTICLE:
            filtered[src] = sigs
        else:
            logger.info(
                "[가드레일] %s 제외 (%d건 < %d건 최소)",
                src, len(sigs), MIN_SIGNALS_FOR_ARTICLE,
            )
    return filtered


# ══════════════════════════════════════════════
# 2. 중간검증: 편집장 출력 소스 중복 제거
# ══════════════════════════════════════════════

def dedupe_stories(stories: list[dict]) -> list[dict]:
    """같은 소스에서 2건 이상 나오면 첫 번째만 유지."""
    seen_sources: set[str] = set()
    result = []

    for story in stories:
        sources = story.get("sources_used", [])
        primary = sources[0] if sources else ""

        if primary in seen_sources:
            logger.info(
                "[가드레일] 중복 소스 제거: #%d %s (%s)",
                story.get("story_id", 0),
                story.get("headline_draft", "")[:30],
                primary,
            )
            continue

        if primary:
            seen_sources.add(primary)
        result.append(story)

    return result


# ══════════════════════════════════════════════
# 3. 후처리: 금지표현 + 기관명 + 메타언급
# ══════════════════════════════════════════════

# 금지 표현 패턴 (매칭되는 문장 전체 삭제)
BANNED_SENTENCE_PATTERNS = [
    r"[^.。]*데이터\s*부족[^.。]*[.。]",
    r"[^.。]*확인\s*불가[^.。]*[.。]",
    r"[^.。]*분석\s*불가[^.。]*[.。]",
    r"[^.。]*추가\s*확인이?\s*필요[^.。]*[.。]",
    r"[^.。]*공문서와?\s*허가사항에서\s*확인[^.。]*[.。]",
    r"[^.。]*후속\s*자료를?\s*통해\s*확인[^.。]*[.。]",
    r"[^.。]*약제팀은[^.。]*[.。]",
    r"[^.。]*RA/MA는[^.。]*[.。]",
    r"[^.。]*즉시\s*점검하라[^.。]*[.。]",
    r"[^.。]*재검토해야\s*한다[^.。]*[.。]",
    r"[^.。]*그래서\s*뭐\?[^.。]*[.。]",
    r"[^.。]*\[FACT\s*DATA\][^.。]*[.。]",
    r"[^.。]*기사\s*초안[은에]서?[^.。]*[.。]",
    r"[^.。]*초안[은에]?\s*따르면[^.。]*[.。]",
    r"[^.。]*초안[은이]?\s*제시한[^.。]*[.。]",
    r"[^.。]*초안[은이]?\s*전했다[^.。]*[.。]",
    r"[^.。]*해석은?\s*포함하지\s*않았다[^.。]*[.。]",
]

# 기관명 치환 (풀네임 → "풀네임(이하 약어)" 첫 등장, 이후 약어만)
INSTITUTION_MAP = {
    "일본 의약품의료기기종합기구": ("PMDA", "일본 의약품의료기기종합기구(이하 PMDA)"),
    "미국 식품의약국": ("FDA", "미국 식품의약국(이하 FDA)"),
    "유럽의약품청": ("EMA", "유럽의약품청(이하 EMA)"),
    "식품의약품안전처": ("식약처", "식품의약품안전처(이하 식약처)"),
    "건강보험심사평가원": ("심평원", "건강보험심사평가원(이하 심평원)"),
    "영국 국립보건의료연구원": ("NICE", "영국 국립보건의료연구원(이하 NICE)"),
    "보건산업진흥원": ("KHIDI", "보건산업진흥원(이하 KHIDI)"),
}


def post_process_article(article: dict) -> dict:
    """기사 후처리 — 금지표현 삭제 + 기관명 치환 + 메타언급 제거."""
    body = article.get("body", "")
    if not body:
        return article

    corrections = []

    # 1. 금지 표현 문장 삭제
    for pattern in BANNED_SENTENCE_PATTERNS:
        matches = re.findall(pattern, body)
        for m in matches:
            corrections.append(f"삭제: {m.strip()[:50]}")
        body = re.sub(pattern, "", body)

    # 2. 기관명 치환
    for fullname, (abbr, first_mention) in INSTITUTION_MAP.items():
        # 이미 "(이하 약어)" 있으면 스킵
        if f"(이하 {abbr})" in body:
            # 이후 풀네임을 약어로 치환
            parts = body.split(f"(이하 {abbr})")
            if len(parts) == 2:
                parts[1] = parts[1].replace(fullname, abbr)
                body = f"(이하 {abbr})".join(parts)
            continue

        # 풀네임이 있으면 첫 등장을 "풀네임(이하 약어)"로, 나머지를 약어로
        if fullname in body:
            idx = body.index(fullname)
            before = body[:idx]
            after = body[idx + len(fullname):]
            # 바로 뒤에 "(PMDA)" 등이 붙어있으면 제거하고 "(이하 PMDA)"로 교체
            after = re.sub(
                rf"^\s*\({abbr}\)", "", after,
            )
            after = after.replace(fullname, abbr)
            body = before + first_mention + after
            corrections.append(f"기관명: {fullname} → {first_mention}")

    # 3. 외국어 음역 정리 (3단어 이상 연속 한글 음역)
    # 예: "엥스띠뛰 나씨오날 드 라 쌍떼 에 드 라 흐쉐르슈 메디깔"
    body = re.sub(
        r"[가-힣]+\s+[가-힣]+\s+[가-힣]+\s+[가-힣]+\s+[가-힣]+(?:\s+[가-힣]+)*",
        lambda m: _check_transliteration(m.group()),
        body,
    )

    # 4. 불완전 문장 제거 (마지막 문장이 마침표 없이 끝나면 삭제)
    sentences = body.rstrip().split(".")
    if sentences and len(sentences[-1].strip()) > 0 and not sentences[-1].strip().endswith(("다", "요", "음", "임")):
        removed = sentences.pop()
        if removed.strip():
            corrections.append(f"불완전 문장 삭제: {removed.strip()[:40]}")
        body = ".".join(sentences)
        if not body.endswith("."):
            body += "."

    # 5. 빈 줄 정리 (연속 빈 줄 → 단일 빈 줄)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.strip()

    if corrections:
        logger.info(
            "[가드레일] 후처리 %d건: %s",
            len(corrections),
            ", ".join(corrections[:3]),
        )

    article["body"] = body
    article["_guardrail_corrections"] = corrections
    return article


def _check_transliteration(text: str) -> str:
    """5단어 이상 연속 한글이 외국어 음역인지 판단.

    한국어 일반 문장과 구분하기 위해 보수적으로 처리:
    음역 특징적 글자(뛰, 쌍, 흐, 띠 등)가 포함되면 삭제.
    """
    transliteration_chars = set("뛰띠쌍흐깔떼씨뜨끄")
    if any(c in text for c in transliteration_chars):
        return ""  # 외국어 음역 삭제
    return text  # 일반 한국어 유지
