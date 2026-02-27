"""뉴스 ↔ INN 매칭 — IngredientMatcher.SYNONYMS 재사용

뉴스 제목 + 요약에서 약물 INN(또는 브랜드명)을 탐지하고,
INN → [NewsArticle] 인덱스를 구축한다.
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from regscan.news.fetcher import NewsArticle

logger = logging.getLogger(__name__)


def _build_search_index() -> dict[str, str]:
    """SYNONYMS → {검색 토큰(소문자): 정규화된 INN} 역인덱스 구축.

    예: "keytruda" → "pembrolizumab", "키트루다" → "pembrolizumab"
    """
    from regscan.map.matcher import IngredientMatcher

    index: dict[str, str] = {}
    for inn, synonyms in IngredientMatcher.SYNONYMS.items():
        inn_lower = inn.lower()
        index[inn_lower] = inn_lower
        for syn in synonyms:
            index[syn.lower()] = inn_lower
    return index


# 모듈 레벨 캐시
_SEARCH_INDEX: dict[str, str] | None = None


def _get_search_index() -> dict[str, str]:
    global _SEARCH_INDEX
    if _SEARCH_INDEX is None:
        _SEARCH_INDEX = _build_search_index()
    return _SEARCH_INDEX


def match_news_to_inns(
    articles: list[NewsArticle],
    target_inns: list[str] | None = None,
) -> dict[str, list[NewsArticle]]:
    """뉴스 기사 → INN 매칭.

    Args:
        articles: NewsArticle 리스트
        target_inns: 매칭 대상 INN 목록 (None이면 SYNONYMS 전체)

    Returns:
        {normalized_inn: [매칭된 NewsArticle 리스트]}
    """
    search_index = _get_search_index()

    # target_inns가 지정되면 해당 INN만 필터
    target_set: set[str] | None = None
    if target_inns:
        target_set = {inn.lower() for inn in target_inns}

    result: dict[str, list[NewsArticle]] = {}

    for article in articles:
        # 검색 대상 텍스트: 제목 + 요약
        searchable = f"{article.title} {article.summary}".lower()

        matched: set[str] = set()
        for token, norm_inn in search_index.items():
            if target_set and norm_inn not in target_set:
                continue
            # 단어 경계 매칭 (한글 토큰은 포함 검색)
            if len(token) <= 3 or not token.isascii():
                # 짧은 토큰이나 한글: 단순 포함 검색
                if token in searchable:
                    matched.add(norm_inn)
            else:
                # 영문 긴 토큰: 단어 경계
                if re.search(r'\b' + re.escape(token) + r'\b', searchable):
                    matched.add(norm_inn)

        if matched:
            article.matched_inns = list(matched)
            for inn in matched:
                result.setdefault(inn, []).append(article)

    # INN별 최신순 정렬 + 중복 제거 (같은 URL)
    for inn in result:
        seen_urls: set[str] = set()
        deduped: list[NewsArticle] = []
        for art in result[inn]:
            if art.url not in seen_urls:
                seen_urls.add(art.url)
                deduped.append(art)
        result[inn] = deduped

    total_matched = sum(len(v) for v in result.values())
    logger.info("뉴스-INN 매칭: %d개 INN, %d건 매칭", len(result), total_matched)
    return result
