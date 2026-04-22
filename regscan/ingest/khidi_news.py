"""KHIDI 제약산업정보포털 뉴스 수집기

https://www.khidi.or.kr/board?menuId=MENU01816 (국내뉴스)
https://www.khidi.or.kr/board?menuId=MENU01817 (해외뉴스)
SSR 테이블 — httpx+bs4, Playwright 불필요.
30,439건 아카이브, pageNum/rowCnt 페이지네이션.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import BaseIngestor

logger = logging.getLogger(__name__)

KHIDI_BASE = "https://www.khidi.or.kr"

# 뉴스 게시판
NEWS_BOARDS = {
    "domestic": {
        "menuId": "MENU01816",
        "label": "국내뉴스",
    },
    "global": {
        "menuId": "MENU01817",
        "label": "해외뉴스",
    },
}


class KHIDIPharmaNewsIngestor(BaseIngestor):
    """KHIDI 제약산업정보포털 뉴스 수집기

    국내+해외 뉴스 게시판에서 최근 N일 기사 수집.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 7,
        max_pages: int = 3,
        boards: list[str] | None = None,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.max_pages = max_pages
        self.boards = boards or ["domestic", "global"]

    def source_type(self) -> str:
        return "KHIDI_PHARMA_NEWS"

    async def fetch(self) -> list[dict[str, Any]]:
        """뉴스 수집"""
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []

        for board_key in self.boards:
            board = NEWS_BOARDS.get(board_key)
            if not board:
                continue
            records = await self._fetch_board(
                board["menuId"], board["label"], cutoff,
            )
            all_records.extend(records)

        logger.info(
            "[KHIDI News] %d건 수집 (최근 %d일, %s)",
            len(all_records), self.days_back,
            "+".join(self.boards),
        )
        return all_records

    async def _fetch_board(
        self,
        menu_id: str,
        label: str,
        cutoff,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        for page_num in range(1, self.max_pages + 1):
            try:
                response = await self._request_with_retry(
                    "GET",
                    f"{KHIDI_BASE}/board",
                    params={
                        "menuId": menu_id,
                        "siteId": "SITE00032",
                        "pageNum": page_num,
                        "rowCnt": 20,
                    },
                    max_retries=2,
                )
            except Exception as e:
                logger.warning(
                    "[KHIDI News] %s p%d 실패: %s", label, page_num, e,
                )
                break

            page_records, should_stop = self._parse_list(
                response.text, label, cutoff,
            )
            records.extend(page_records)

            if should_stop or not page_records:
                break

        return records

    def _parse_list(
        self,
        html: str,
        label: str,
        cutoff,
    ) -> tuple[list[dict[str, Any]], bool]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict[str, Any]] = []
        should_stop = False

        for row in soup.select("tr"):
            tds = row.find_all("td")
            if len(tds) < 4:
                continue

            link = tds[1].find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            href = link.get("href", "")
            # 외부 링크 or 내부 링크
            if href.startswith("http"):
                url = href
            elif href.startswith("/"):
                url = f"{KHIDI_BASE}{href}"
            else:
                url = href

            source_name = tds[2].get_text(strip=True) if len(tds) > 2 else ""
            date_text = tds[3].get_text(strip=True) if len(tds) > 3 else ""

            # 날짜 파싱 (YYYY.MM.DD)
            date_str = ""
            date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", date_text)
            if date_match:
                date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            records.append({
                "source": "KHIDI",
                "source_type": "KHIDI_PHARMA_NEWS",
                "board": label,
                "title": title,
                "url": url,
                "news_source": source_name,
                "date": date_str,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop
