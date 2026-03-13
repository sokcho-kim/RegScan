"""KHIDI (한국보건산업진흥원) 보도자료·산업동향 수집기

공공저작물 자유이용 (출처 표기 조건).
httpx 기반 — Playwright 불필요.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlencode

from .base import BaseIngestor

logger = logging.getLogger(__name__)

KHIDI_BASE = "https://www.khidi.or.kr"

# 메뉴별 ID
MENU_IDS = {
    "brief": "MENU01783",       # 바이오헬스산업동향 브리프
    "notice": "MENU02339",      # 공지사항
    "report": "MENU01784",      # 보고서
}


class KHIDIIngestor(BaseIngestor):
    """KHIDI 바이오헬스산업동향 브리프 수집기

    수집 대상:
    - 바이오헬스산업동향 브리프 (주간/월간 산업 분석)
    - 보고서 (시장 규모, 정책 동향)

    공공저작물로 출처 표기 조건 하에 자유이용 가능.
    """

    def __init__(
        self,
        menu_id: str = "MENU01783",
        days_back: int = 30,
        max_pages: int = 3,
        row_count: int = 10,
    ):
        super().__init__(timeout=30.0)
        self.menu_id = menu_id
        self.days_back = days_back
        self.max_pages = max_pages
        self.row_count = row_count

    def source_type(self) -> str:
        return "KHIDI"

    async def fetch(self) -> list[dict[str, Any]]:
        """KHIDI 브리프/보고서 목록 수집"""
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_items: list[dict[str, Any]] = []

        for page_num in range(1, self.max_pages + 1):
            try:
                items, should_stop = await self._fetch_list_page(page_num, cutoff)
                all_items.extend(items)

                if should_stop:
                    break

            except Exception as e:
                logger.warning("[KHIDI] 페이지 %d 수집 실패: %s", page_num, e)
                break

        logger.info("[KHIDI] 총 %d건 수집 완료 (menu=%s)", len(all_items), self.menu_id)
        return all_items

    async def _fetch_list_page(
        self, page_num: int, cutoff
    ) -> tuple[list[dict[str, Any]], bool]:
        """목록 페이지 1개 수집. (items, should_stop) 반환."""
        params = {
            "menuId": self.menu_id,
            "pageNum": page_num,
            "rowCnt": self.row_count,
        }
        url = f"{KHIDI_BASE}/board?{urlencode(params)}"

        resp = await self.client.get(url)
        resp.raise_for_status()
        html = resp.text

        items: list[dict[str, Any]] = []
        should_stop = False

        # 목록 행 파싱: /board/view?...no1=XXX&linkId=YYY...
        pattern = re.compile(
            r'<a[^>]+href="(/board/view\?[^"]*no1=(\d+)[^"]*linkId=(\d+)[^"]*)"[^>]*>'
            r'\s*(.*?)\s*</a>',
            re.DOTALL,
        )

        # 날짜 패턴: YYYY-MM-DD
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')

        for match in pattern.finditer(html):
            href, no1, link_id, raw_title = match.groups()
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            if not title:
                continue

            # 해당 행 주변에서 날짜 추출
            context_start = max(0, match.start() - 200)
            context_end = min(len(html), match.end() + 500)
            context = html[context_start:context_end]
            date_match = date_pattern.search(context[match.start() - context_start:])
            date_str = date_match.group(1) if date_match else ""

            # 날짜 필터
            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            detail_url = urljoin(KHIDI_BASE, href)

            items.append({
                "source": "KHIDI",
                "source_type": self.source_type(),
                "title": title,
                "no1": no1,
                "link_id": link_id,
                "date": date_str,
                "url": detail_url,
                "menu_id": self.menu_id,
                "collected_at": self._now().isoformat(),
            })

        return items, should_stop

    async def fetch_detail(self, item: dict[str, Any]) -> dict[str, Any]:
        """상세 페이지에서 본문·첨부파일 추출"""
        url = item.get("url", "")
        if not url:
            return item

        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            html = resp.text

            # 본문 추출: .viewContent 영역
            content = self._extract_view_content(html)
            # 첨부파일 추출
            files = self._extract_files(html)

            item["content"] = content
            item["files"] = files

        except Exception as e:
            logger.warning("[KHIDI] 상세 수집 실패 (%s): %s", url, e)

        return item

    def _extract_view_content(self, html: str) -> str:
        """viewContent 영역에서 텍스트 추출"""
        match = re.search(
            r'<div[^>]*class="viewContent"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        if not match:
            return ""

        raw = match.group(1)
        # HTML 태그 제거, 공백 정리
        text = re.sub(r'<br\s*/?>', '\n', raw)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_files(self, html: str) -> list[dict[str, str]]:
        """첨부파일 목록 추출"""
        files = []
        # fileDownload 링크 패턴
        pattern = re.compile(
            r'<a[^>]+href="([^"]*fileDownload[^"]*)"[^>]*>\s*(.*?)\s*</a>',
            re.DOTALL,
        )
        for m in pattern.finditer(html):
            href, filename = m.groups()
            filename = re.sub(r'<[^>]+>', '', filename).strip()
            if filename:
                files.append({
                    "filename": filename,
                    "url": urljoin(KHIDI_BASE, href),
                })
        return files


class KHIDIBriefIngestor(KHIDIIngestor):
    """바이오헬스산업동향 브리프 전용"""

    def __init__(self, days_back: int = 30, max_pages: int = 3):
        super().__init__(
            menu_id=MENU_IDS["brief"],
            days_back=days_back,
            max_pages=max_pages,
        )


class KHIDIReportIngestor(KHIDIIngestor):
    """KHIDI 보고서 전용"""

    def __init__(self, days_back: int = 60, max_pages: int = 3):
        super().__init__(
            menu_id=MENU_IDS["report"],
            days_back=days_back,
            max_pages=max_pages,
        )
