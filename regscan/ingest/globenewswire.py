"""GlobeNewsWire 제약·바이오 보도자료 수집기

RSS 기반 — 기업 임상 결과, 승인, 파이프라인 발표.
무료, 인증 불필요, 20건/피드.

소스:
  - Pharmaceuticals: /RssFeed/industry/4577-Pharmaceuticals/
  - Biotechnology: /RssFeed/industry/4573-Biotechnology/
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree

from .base import BaseIngestor

logger = logging.getLogger(__name__)

GNW_BASE = "https://www.globenewswire.com"

FEEDS = {
    "pharma": {
        "url": f"{GNW_BASE}/RssFeed/industry/4577-Pharmaceuticals/feedTitle/GlobeNewswire%20-%20Industry%20News%20on%20Pharmaceuticals",
        "label": "Pharmaceuticals",
    },
    "biotech": {
        "url": f"{GNW_BASE}/RssFeed/industry/4573-Biotechnology/feedTitle/GlobeNewswire%20-%20Industry%20News%20on%20Biotechnology",
        "label": "Biotechnology",
    },
}

# 기사 가치 높은 키워드 (제목 필터)
HIGH_VALUE_KEYWORDS = [
    "FDA", "EMA", "CHMP", "approval", "approved", "clearance",
    "Phase 3", "Phase III", "Phase 2", "Phase II", "pivotal",
    "orphan drug", "breakthrough", "priority review", "fast track",
    "accelerated approval", "clinical trial", "clinical data",
    "ORR", "PFS", "OS", "overall survival", "progression-free",
    "AACR", "ASCO", "ESMO", "ASH", "EHA",
    "pipeline", "indication", "label expansion",
    "PDUFA", "NDA", "BLA", "MAA", "sNDA", "sBLA",
    "results", "interim", "topline", "endpoint",
]


class GlobeNewsWireIngestor(BaseIngestor):
    """GlobeNewsWire 제약·바이오 보도자료 수집기

    RSS 피드에서 최신 보도자료 수집.
    제목 키워드 필터로 기사 가치 높은 것만 선별.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 7,
        feeds: list[str] | None = None,
        filter_keywords: bool = True,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.feeds = feeds or list(FEEDS.keys())
        self.filter_keywords = filter_keywords

    def source_type(self) -> str:
        return "GNW_PRESS"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for feed_key in self.feeds:
            feed = FEEDS.get(feed_key)
            if not feed:
                continue
            records = await self._fetch_feed(feed["url"], feed["label"], cutoff, seen_urls)
            all_records.extend(records)

        logger.info(
            "[GNW] %d건 수집 (최근 %d일, %s)",
            len(all_records), self.days_back,
            "+".join(self.feeds),
        )
        return all_records

    async def _fetch_feed(
        self,
        url: str,
        label: str,
        cutoff,
        seen_urls: set[str],
    ) -> list[dict[str, Any]]:
        try:
            response = await self._request_with_retry(
                "GET", url, max_retries=2,
                headers={"User-Agent": "RegScan/1.0"},
            )
        except Exception as e:
            logger.warning("[GNW] %s 피드 실패: %s", label, e)
            return []

        return self._parse_rss(response.text, label, cutoff, seen_urls)

    def _parse_rss(
        self,
        xml_text: str,
        label: str,
        cutoff,
        seen_urls: set[str],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.warning("[GNW] %s XML 파싱 실패: %s", label, e)
            return []

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date_raw = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()

            if not title or not link:
                continue
            if link in seen_urls:
                continue

            # 날짜 파싱 (RFC 2822)
            date_str = self._parse_date(pub_date_raw)
            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        continue
                except ValueError:
                    pass

            # 키워드 필터
            if self.filter_keywords:
                title_upper = title.upper()
                if not any(kw.upper() in title_upper for kw in HIGH_VALUE_KEYWORDS):
                    continue

            seen_urls.add(link)

            # description에서 HTML 태그 제거
            clean_desc = re.sub(r"<[^>]+>", "", description).strip()

            records.append({
                "source": "GlobeNewsWire",
                "source_type": "GNW_PRESS",
                "board": label,
                "title": title,
                "url": link,
                "date": date_str,
                "description": clean_desc[:500],
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records

    @staticmethod
    def _parse_date(raw: str) -> str:
        """RFC 2822 날짜 → YYYY-MM-DD"""
        import email.utils
        try:
            tt = email.utils.parsedate_tz(raw)
            if tt:
                ts = email.utils.mktime_tz(tt)
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            pass
        # fallback
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return ""
