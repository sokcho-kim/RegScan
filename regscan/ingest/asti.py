"""ASTI/KISTI 시장 리포트 수집기

ASTI(과학기술정보통신부 과학기술정보분석센터)에서
바이오·의약품 시장 리포트를 수집합니다.

Playwright 기반 크롤링 (HIRA/MOHW 패턴 참고).
"""

import logging
from datetime import datetime
from typing import Any

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

ASTI_BASE_URL = "https://www.asti.re.kr"
ASTI_REPORT_URL = f"{ASTI_BASE_URL}/report/list.do"


class ASTIClient:
    """ASTI 리포트 크롤링 클라이언트 (Playwright)"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._page = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()
        except ImportError:
            logger.warning("playwright 미설치 — pip install 'regscan[crawl]'")
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()

    async def search_reports(
        self,
        keyword: str = "의약품",
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        """ASTI 리포트 검색

        Args:
            keyword: 검색 키워드
            max_pages: 최대 페이지 수

        Returns:
            리포트 목록 [{title, url, publisher, date, ...}, ...]
        """
        results = []

        for page_num in range(1, max_pages + 1):
            try:
                url = f"{ASTI_REPORT_URL}?searchKeyword={keyword}&pageIndex={page_num}"
                await self._page.goto(url, wait_until="networkidle", timeout=30000)
                await self._page.wait_for_timeout(2000)

                rows = await self._page.query_selector_all("table tbody tr")
                if not rows:
                    break

                for row in rows:
                    try:
                        cols = await row.query_selector_all("td")
                        if len(cols) < 4:
                            continue

                        title_el = await cols[1].query_selector("a")
                        title = (await title_el.inner_text()).strip() if title_el else ""
                        href = await title_el.get_attribute("href") if title_el else ""

                        publisher = (await cols[2].inner_text()).strip()
                        date_str = (await cols[3].inner_text()).strip()

                        if title:
                            results.append({
                                "title": title,
                                "source_url": f"{ASTI_BASE_URL}{href}" if href else "",
                                "publisher": publisher,
                                "date_str": date_str,
                                "source": "ASTI",
                            })
                    except Exception as e:
                        logger.debug("ASTI 행 파싱 오류: %s", e)
                        continue

            except Exception as e:
                logger.warning("ASTI 페이지 %d 수집 실패: %s", page_num, e)
                break

        logger.info("ASTI 리포트 %d건 수집", len(results))
        return results

    async def fetch_report_detail(self, url: str) -> dict[str, Any]:
        """리포트 상세 페이지에서 본문/요약 추출"""
        try:
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(1000)

            content_el = await self._page.query_selector(".view_content, .report_content, article")
            content = (await content_el.inner_text()).strip() if content_el else ""

            return {"content": content, "url": url}
        except Exception as e:
            logger.warning("ASTI 상세 수집 실패 (%s): %s", url, e)
            return {"content": "", "url": url}


class ASTIIngestor(BaseIngestor):
    """ASTI 시장 리포트 수집기"""

    def source_type(self) -> str:
        return "ASTI"

    async def fetch(self) -> list[dict[str, Any]]:
        """ASTI 리포트 수집

        Returns:
            리포트 목록 (파싱 전 raw data)
        """
        keywords = ["의약품", "바이오", "제약", "신약"]
        all_reports = []
        seen_titles = set()

        async with ASTIClient() as client:
            for keyword in keywords:
                try:
                    reports = await client.search_reports(keyword=keyword, max_pages=2)
                    for r in reports:
                        if r["title"] not in seen_titles:
                            seen_titles.add(r["title"])
                            r["collected_at"] = self._now().isoformat()
                            all_reports.append(r)
                except Exception as e:
                    logger.warning("ASTI '%s' 수집 실패: %s", keyword, e)

        logger.info("ASTI 총 %d건 수집 완료", len(all_reports))
        return all_reports
