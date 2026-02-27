"""RSS 뉴스 수집기 — Endpoints News + FiercePharma

영문 RSS 피드를 파싱하여 최근 N일 이내 제약/바이오 뉴스를 수집한다.
feedparser 가 없으면 xml.etree 폴백으로 최소 파싱.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── RSS 피드 소스 정의 ──
RSS_FEEDS: list[dict[str, str]] = [
    {
        "name": "Endpoints News",
        "url": "https://endpts.com/feed/",
    },
    {
        "name": "FiercePharma",
        "url": "https://www.fiercepharma.com/rss/xml",
    },
    {
        "name": "Fierce Biotech",
        "url": "https://www.fiercebiotech.com/rss/xml",
    },
]


@dataclass
class NewsArticle:
    """수집된 뉴스 기사 1건"""

    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""
    # INN 매칭 후 채워짐
    matched_inns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary[:300],
            "matched_inns": self.matched_inns,
        }


def _parse_date(date_str: str) -> Optional[datetime]:
    """RSS 날짜 문자열 → datetime (다양한 포맷 대응)"""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",   # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _parse_rss_xml(xml_text: str, source_name: str) -> list[NewsArticle]:
    """xml.etree 기반 RSS 파싱 (feedparser 불필요)"""
    articles: list[NewsArticle] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("RSS XML 파싱 실패 (%s): %s", source_name, e)
        return articles

    # RSS 2.0: channel/item
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate") or item.findtext("published") or ""
        description = (item.findtext("description") or "").strip()

        if not title or not link:
            continue

        # HTML 태그 제거 (간단한 strip)
        import re
        summary = re.sub(r"<[^>]+>", "", description)[:500]

        articles.append(NewsArticle(
            title=title,
            url=link,
            source=source_name,
            published=_parse_date(pub_date),
            summary=summary,
        ))

    # Atom: feed/entry (FiercePharma 등)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", namespaces=ns) or ""
        summary_el = entry.findtext("atom:summary", namespaces=ns) or ""

        if not title or not link:
            continue

        import re
        summary = re.sub(r"<[^>]+>", "", summary_el)[:500]

        articles.append(NewsArticle(
            title=title,
            url=link,
            source=source_name,
            published=_parse_date(updated),
            summary=summary,
        ))

    return articles


async def fetch_news(
    days_back: int = 7,
    max_per_feed: int = 50,
    feeds: list[dict[str, str]] | None = None,
) -> list[NewsArticle]:
    """RSS 피드에서 최근 뉴스 수집.

    Args:
        days_back: 최근 N일 이내 기사만 수집
        max_per_feed: 피드당 최대 수집 건수
        feeds: 커스텀 피드 목록 (기본: RSS_FEEDS)

    Returns:
        NewsArticle 리스트 (최신순 정렬)
    """
    target_feeds = feeds or RSS_FEEDS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    all_articles: list[NewsArticle] = []

    headers = {
        "User-Agent": "RegScan/1.0 (RSS Reader; +https://github.com/regscan)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, headers=headers,
    ) as client:
        for feed_info in target_feeds:
            name = feed_info["name"]
            url = feed_info["url"]
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                articles = _parse_rss_xml(resp.text, name)

                # 날짜 필터
                filtered = []
                for art in articles[:max_per_feed]:
                    if art.published and art.published.tzinfo:
                        if art.published < cutoff:
                            continue
                    filtered.append(art)

                all_articles.extend(filtered)
                logger.info("뉴스 수집 [%s]: %d건 (필터 후 %d건)",
                           name, len(articles), len(filtered))
            except Exception as e:
                logger.warning("뉴스 수집 실패 [%s]: %s", name, e)

    # 최신순 정렬 (날짜 없는 기사는 뒤로)
    all_articles.sort(
        key=lambda a: a.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    logger.info("총 뉴스 수집: %d건", len(all_articles))
    return all_articles
