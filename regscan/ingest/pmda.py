"""PMDA (일본 의약품의료기기종합기구) 수집기

승인심사: rss_011.xml (Reviews) — 신약 승인, 심사 보고서
안전성: rss_013.xml (Safety) + 안전성 정보 HTML 테이블
전체: rss_008.xml (All) — 모든 카테고리 통합

RSS (RDF 1.0) + HTML 크롤링 조합. bs4 + lxml XML 파서 사용.
"""

from __future__ import annotations

import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import BaseIngestor

logger = logging.getLogger(__name__)

PMDA_BASE = "https://www.pmda.go.jp"

# RSS 피드 URL
RSS_FEEDS = {
    "all": f"{PMDA_BASE}/rss_008.xml",
    "reviews": f"{PMDA_BASE}/rss_011.xml",
    "safety": f"{PMDA_BASE}/rss_013.xml",
    "international": f"{PMDA_BASE}/rss_009.xml",
}

# RSS 타이틀 카테고리 접두사 → 분류
CATEGORY_PREFIX = {
    "[SHINSA]": "review",       # 承認審査 (승인심사)
    "[ANZEN]": "safety",        # 安全対策 (안전대책)
    "[KOKUSAI]": "international",  # 国際 (국제)
    "[IBENTO]": "event",        # イベント (이벤트)
    "[SONOTA]": "other",        # その他 (기타)
    "[KISEI]": "regulation",    # 規制 (규제)
    "[SUKUHAI]": "relief",      # 救済 (구제)
}

# 안전성 정보 HTML 페이지
SAFETY_INFO_URL = (
    f"{PMDA_BASE}/english/safety/info-services"
    "/safety-information/0001.html"
)


def _make_tls12_context() -> ssl.SSLContext:
    """PMDA는 TLS 1.3 미지원 — TLS 1.2 강제"""
    ctx = ssl.create_default_context()
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _parse_rss_xml(xml_text: str) -> list[dict[str, str]]:
    """RDF 1.0 RSS XML을 파싱하여 항목 리스트 반환.

    feedparser 없이 bs4로 직접 파싱 (의존성 최소화).
    """
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item_el in soup.find_all("item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        date_el = item_el.find("dc:date") or item_el.find("date")

        title = title_el.get_text(strip=True) if title_el else ""
        link = link_el.get_text(strip=True) if link_el else ""
        date_str = date_el.get_text(strip=True) if date_el else ""

        if title:
            items.append({
                "title": title,
                "link": link,
                "date": date_str,
            })
    return items


def _classify_item(title: str) -> tuple[str, str]:
    """RSS 타이틀에서 카테고리 접두사 분리.

    Returns: (category, clean_title)
    """
    for prefix, category in CATEGORY_PREFIX.items():
        if title.startswith(prefix):
            clean = title[len(prefix):].strip()
            # 중복 접두사 제거 (예: [IBENTO][IBENTO])
            for p2 in CATEGORY_PREFIX:
                if clean.startswith(p2):
                    clean = clean[len(p2):].strip()
            return category, clean
    return "other", title


def _parse_iso_date(date_str: str) -> str:
    """ISO 8601 날짜를 YYYY-MM-DD로 변환."""
    if not date_str:
        return ""
    # 2026-04-14T12:00:00+09:00 → 2026-04-14
    match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
    return match.group(1) if match else ""


# ── PMDA RSS 수집기 ──────────────────────────────────────────


class PMDAReviewIngestor(BaseIngestor):
    """PMDA 승인심사 정보 수집기 (RSS)

    rss_011.xml — 신약 승인, 심사 보고서, 상담 정보 등
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_REVIEW"

    async def fetch(self) -> list[dict[str, Any]]:
        """승인심사 RSS 수집"""
        return await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["reviews"],
            source_type="PMDA_REVIEW",
            days_back=self.days_back,
        )


class PMDASafetyIngestor(BaseIngestor):
    """PMDA 안전성 정보 수집기 (RSS + HTML)

    rss_013.xml — 안전대책 관련 업데이트
    HTML 테이블 — Medical Safety Information (72+ 보고서)
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
        include_html_table: bool = True,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.include_html_table = include_html_table

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_SAFETY"

    async def fetch(self) -> list[dict[str, Any]]:
        """안전성 RSS + HTML 테이블 수집"""
        results = await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["safety"],
            source_type="PMDA_SAFETY",
            days_back=self.days_back,
        )

        if self.include_html_table:
            table_results = await self._fetch_safety_table()
            results.extend(table_results)

        logger.info(
            "[PMDA] 안전성 정보 총 %d건 수집", len(results),
        )
        return results

    async def _fetch_safety_table(self) -> list[dict[str, Any]]:
        """Medical Safety Information HTML 테이블 파싱"""
        try:
            response = await self.client.get(
                SAFETY_INFO_URL, follow_redirects=True,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error("[PMDA] 안전성 테이블 요청 실패: %s", e)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        records: list[dict[str, Any]] = []

        for row in soup.select("table tr"):
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            posted_in = cols[0].get_text(strip=True)
            number = cols[1].get_text(strip=True).replace("\n", " ")
            link = cols[2].find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            pdf_url = (
                f"{PMDA_BASE}{href}" if href.startswith("/") else href
            )

            records.append({
                "source": "PMDA",
                "source_type": "PMDA_SAFETY_REPORT",
                "title": title,
                "number": number,
                "posted_in": posted_in,
                "url": pdf_url,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        logger.info(
            "[PMDA] 안전성 보고서 테이블 %d건", len(records),
        )
        return records


class PMDAAllIngestor(BaseIngestor):
    """PMDA 전체 업데이트 수집기 (RSS)

    rss_008.xml — 모든 카테고리 통합 피드
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_ALL"

    async def fetch(self) -> list[dict[str, Any]]:
        """전체 RSS 수집"""
        return await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["all"],
            source_type="PMDA_ALL",
            days_back=self.days_back,
        )


# ── 공통 RSS 수집 로직 ──────────────────────────────────────


async def _fetch_rss(
    *,
    client: httpx.AsyncClient,
    feed_url: str,
    source_type: str,
    days_back: int,
) -> list[dict[str, Any]]:
    """RSS 피드를 가져와서 구조화된 레코드로 변환."""
    try:
        response = await client.get(feed_url, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        logger.error("[PMDA] RSS 요청 실패 (%s): %s", feed_url, e)
        return []

    items = _parse_rss_xml(response.text)
    cutoff = (datetime.now() - timedelta(days=days_back)).date()
    now_str = datetime.now().strftime("%Y-%m-%d")

    records: list[dict[str, Any]] = []
    for item in items:
        date_str = _parse_iso_date(item["date"])

        # 날짜 필터
        if date_str:
            try:
                pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if pub_date < cutoff:
                    continue
            except ValueError:
                pass

        category, clean_title = _classify_item(item["title"])

        records.append({
            "source": "PMDA",
            "source_type": source_type,
            "category": category,
            "title": clean_title,
            "title_original": item["title"],
            "date": date_str,
            "url": item["link"],
            "_fetched_at": now_str,
        })

    logger.info(
        "[PMDA] %s: %d건 수집 (최근 %d일)",
        source_type, len(records), days_back,
    )
    return records
