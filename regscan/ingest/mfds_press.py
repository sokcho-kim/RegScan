"""MFDS 보도자료/공지사항/입법예고 수집기

mfds.go.kr 게시판 3개 통합 크롤링 (httpx+bs4, TLS 1.2+UA).
- 보도자료 (m_99): 신약 허가, 안전성, 정책
- 공지사항 (m_74): 규제 변경
- 입법예고 (m_209): 법령 제/개정
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

MFDS_BASE = "https://www.mfds.go.kr"

BOARDS = {
    "press": {"id": "m_99", "label": "보도자료"},
    "notice": {"id": "m_74", "label": "공지사항"},
    "legislation": {"id": "m_209", "label": "입법예고"},
}


class MFDSPressIngestor(BaseIngestor):
    """MFDS 보도자료/공지/입법예고 수집기"""

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 14,
        max_pages: int = 3,
        boards: list[str] | None = None,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.max_pages = max_pages
        self.boards = boards or ["press", "notice"]

    async def __aenter__(self):
        ctx = ssl.create_default_context()
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            verify=ctx,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        return self

    def source_type(self) -> str:
        return "MFDS_PRESS"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []

        for board_key in self.boards:
            board = BOARDS.get(board_key)
            if not board:
                continue
            records = await self._fetch_board(board, cutoff)
            all_records.extend(records)

        logger.info(
            "[MFDS Press] %d건 수집 (최근 %d일)",
            len(all_records), self.days_back,
        )
        return all_records

    async def _fetch_board(self, board: dict, cutoff) -> list[dict]:
        board_id = board["id"]
        label = board["label"]
        records: list[dict] = []

        for page in range(1, self.max_pages + 1):
            try:
                response = await self._request_with_retry(
                    "GET",
                    f"{MFDS_BASE}/brd/{board_id}/list.do",
                    params={"page": page},
                    max_retries=3,
                )
            except Exception as e:
                logger.warning("[MFDS Press] %s p%d 실패: %s", label, page, e)
                break

            page_records, should_stop = self._parse_list(
                response.text, board_id, label, cutoff,
            )
            records.extend(page_records)
            if should_stop or not page_records:
                break

        return records

    def _parse_list(
        self, html: str, board_id: str, label: str, cutoff,
    ) -> tuple[list[dict], bool]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        should_stop = False

        for li in soup.select("div.bbs_list01 ul li"):
            a = li.select_one("a.title")
            if not a:
                continue

            title = a.get_text(strip=True)
            href = a.get("href", "")
            if "view.do" not in href:
                continue

            url = f"{MFDS_BASE}/brd/{board_id}/{href}" if not href.startswith("http") else href

            text = li.get_text()
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            date_str = date_match.group(1) if date_match else ""

            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            # 담당부서 추출
            dept_match = re.search(r"담당부서\s*\|?\s*([^\n]+?)(?:\s+조회수|\s+\d{4}-|$)", text)
            department = dept_match.group(1).strip() if dept_match else ""

            records.append({
                "source": "MFDS",
                "source_type": "MFDS_PRESS",
                "board": label,
                "title": title,
                "department": department,
                "date": date_str,
                "url": url,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop
