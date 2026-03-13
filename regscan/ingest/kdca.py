"""KDCA (질병관리청) 보도자료 수집기 - Playwright 기반

공공저작물 자유이용 (출처 표기 조건).
KDCA 사이트는 외부 HTTP 요청 차단 → Playwright 필수.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from .base import BaseIngestor
from .hira import CrawlConfig

logger = logging.getLogger(__name__)

KDCA_BASE = "https://www.kdca.go.kr"

# 보도자료 목록 URL
PRESS_RELEASE_URL = (
    f"{KDCA_BASE}/board/board.es?mid=a20501010000&bid=0015"
)

# 감염병 관련 공지
DISEASE_INFO_URL = (
    f"{KDCA_BASE}/board/board.es?mid=a20501000000&bid=0015"
)


class KDCAIngestor(BaseIngestor):
    """질병관리청 보도자료 수집기 (Playwright)

    수집 대상:
    - 보도자료 (감염병·백신·바이오 정책)
    - 공공저작물로 출처 표기 조건 하에 자유이용 가능

    KDCA 사이트는 외부 HTTP 요청을 차단하므로 Playwright 필수.
    """

    def __init__(
        self,
        config: CrawlConfig | None = None,
        days_back: int = 30,
        keywords: list[str] | None = None,
    ):
        super().__init__()
        self.config = config or CrawlConfig(days_back=days_back)
        self.days_back = days_back
        self.keywords = keywords or [
            "백신", "예방접종", "감염병", "의약품", "바이오",
            "임상", "허가", "승인", "치료제",
        ]
        self._playwright = None
        self._browser = None

    def source_type(self) -> str:
        return "KDCA"

    async def __aenter__(self):
        await super().__aenter__()
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except ImportError:
            raise ImportError(
                "playwright가 설치되지 않았습니다. "
                "pip install 'regscan[crawl]' 또는 "
                "pip install playwright && playwright install"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self) -> list[dict[str, Any]]:
        """보도자료 수집"""
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        records: list[dict[str, Any]] = []

        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout)

        try:
            logger.info("[KDCA] 보도자료 수집 시작")

            await page.goto(PRESS_RELEASE_URL, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2.0)

            for page_num in range(1, self.config.max_pages + 1):
                if page_num > 1:
                    success = await self._navigate_to_page(page, page_num)
                    if not success:
                        break

                page_records, should_stop = await self._extract_list(
                    page, cutoff
                )
                records.extend(page_records)

                logger.info(
                    "[KDCA] 페이지 %d: %d건", page_num, len(page_records)
                )

                if should_stop:
                    break

        except Exception as e:
            logger.error("[KDCA] 수집 중 오류: %s", e)
        finally:
            await context.close()

        # 키워드 필터링 (제약/바이오 관련만)
        if self.keywords:
            filtered = [
                r for r in records
                if self._matches_keywords(r)
            ]
            logger.info(
                "[KDCA] 키워드 필터: %d → %d건", len(records), len(filtered)
            )
            records = filtered

        logger.info("[KDCA] 총 %d건 수집 완료", len(records))
        return records

    async def _navigate_to_page(self, page, page_num: int) -> bool:
        """페이지 이동"""
        try:
            # 공공기관 사이트 공통 페이지네이션: fn_egov_link_page(N) 또는 직접 링크
            # 방법 1: 페이지 번호 링크 클릭
            paging_link = await page.query_selector(
                f'a[href*="nPage={page_num}"], '
                f'a[onclick*="({page_num})"]'
            )
            if paging_link:
                await paging_link.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1.5)
                return True

            # 방법 2: URL 직접 변경
            url = f"{PRESS_RELEASE_URL}&nPage={page_num}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.5)
            return True

        except Exception as e:
            logger.error("[KDCA] 페이지 %d 이동 실패: %s", page_num, e)
            return False

    async def _extract_list(
        self, page, cutoff
    ) -> tuple[list[dict[str, Any]], bool]:
        """목록에서 항목 추출. (records, should_stop) 반환."""
        records: list[dict[str, Any]] = []
        should_stop = False

        try:
            # 공공기관 사이트 공통 테이블 구조
            rows = await page.query_selector_all(
                "table.board_list tbody tr, "
                "div.board_list table tbody tr, "
                "table.bbs_default tbody tr, "
                "div.boardList table tbody tr"
            )

            if not rows:
                # fallback: 모든 테이블 행
                rows = await page.query_selector_all("table tbody tr")

            for row in rows:
                try:
                    record = await self._parse_row(row)
                    if not record or not record.get("title"):
                        continue

                    # 날짜 필터
                    if record.get("date"):
                        try:
                            pub_date = datetime.strptime(
                                record["date"], "%Y-%m-%d"
                            ).date()
                            if pub_date < cutoff:
                                should_stop = True
                                continue
                        except ValueError:
                            pass

                    record["collected_at"] = self._now().isoformat()
                    records.append(record)

                except Exception as e:
                    logger.debug("[KDCA] 행 파싱 오류: %s", e)
                    continue

        except Exception as e:
            logger.error("[KDCA] 목록 추출 실패: %s", e)

        return records, should_stop

    async def _parse_row(self, row) -> dict[str, Any] | None:
        """테이블 행에서 데이터 추출"""
        cols = await row.query_selector_all("td")
        if len(cols) < 3:
            return None

        # 공공기관 공통 패턴: 번호 | 제목 | 담당부서 | 작성일 | 조회수
        title_col = cols[1] if len(cols) >= 4 else cols[0]

        # 제목 + 링크
        link = await title_col.query_selector("a")
        if not link:
            return None

        title = (await link.inner_text()).strip()
        href = await link.get_attribute("href") or ""
        onclick = await link.get_attribute("onclick") or ""

        # URL 생성
        detail_url = ""
        if href and href.startswith("http"):
            detail_url = href
        elif href and not href.startswith("javascript"):
            detail_url = f"{KDCA_BASE}{href}" if href.startswith("/") else href
        elif onclick:
            # fn_detail('12345') 등의 패턴
            id_match = re.search(r"['\"](\d+)['\"]", onclick)
            if id_match:
                detail_url = (
                    f"{PRESS_RELEASE_URL}"
                    f"&act=view&list_no={id_match.group(1)}"
                )

        # 날짜 추출 (마지막 열들에서)
        date_str = ""
        for col in reversed(cols):
            text = (await col.inner_text()).strip()
            date_match = re.search(r'(\d{4}[.-]\d{2}[.-]\d{2})', text)
            if date_match:
                date_str = date_match.group(1).replace(".", "-")
                break

        return {
            "source": "KDCA",
            "source_type": "KDCA",
            "title": title,
            "date": date_str,
            "url": detail_url,
        }

    def _matches_keywords(self, record: dict[str, Any]) -> bool:
        """제목이 키워드와 매칭되는지 확인"""
        title = record.get("title", "")
        return any(kw in title for kw in self.keywords)

    async def fetch_detail(self, page, url: str) -> dict[str, Any]:
        """상세 페이지에서 본문 추출"""
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.5)

            # 본문 추출 (공공기관 공통 셀렉터)
            content_el = await page.query_selector(
                "div.board_view_content, "
                "div.bbs_content, "
                "td.content, "
                "div.view_con"
            )
            content = ""
            if content_el:
                content = (await content_el.inner_text()).strip()

            # 첨부파일
            files = []
            file_links = await page.query_selector_all(
                "div.file_attach a, div.board_file a, a.file_down"
            )
            for fl in file_links:
                filename = (await fl.inner_text()).strip()
                href = await fl.get_attribute("href") or ""
                if filename:
                    files.append({
                        "filename": filename,
                        "url": f"{KDCA_BASE}{href}" if href.startswith("/") else href,
                    })

            return {"content": content, "files": files}

        except Exception as e:
            logger.warning("[KDCA] 상세 수집 실패 (%s): %s", url, e)
            return {"content": "", "files": []}
