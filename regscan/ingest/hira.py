"""HIRA (심평원) 데이터 수집 - Playwright 기반"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin

from parsel import Selector

from .base import BaseIngestor

logger = logging.getLogger(__name__)


# =============================================================================
# URL 상수
# =============================================================================
HIRA_BASE = "https://www.hira.or.kr"

# 보험인정기준 (Insurance Approval Criteria)
IAC_PGMID = "HIRAA030069000400"
IAC_LIST_URL = f"{HIRA_BASE}/rc/insu/insuadtcrtr/InsuAdtCrtrList.do?pgmid={IAC_PGMID}"
IAC_POPUP_URL = f"{HIRA_BASE}/rc/insu/insuadtcrtr/InsuAdtCrtrPopup.do"
IAC_DOWNLOAD_URL = f"{HIRA_BASE}/download.do"

# 공지사항 (Notices)
NOTICE_PGMID = "HIRAA020002000100"
NOTICE_LIST_URL = f"{HIRA_BASE}/bbsDummy.do?pgmid={NOTICE_PGMID}"
NOTICE_DOWNLOAD_URL = f"{HIRA_BASE}/bbs/bbsCDownLoad.do"

# 카테고리 맵핑
CATEGORY_MAP = {
    "01": "고시",
    "02": "행정해석",
    "09": "심사지침",
    "10": "심의사례공개",
    "17": "심사사례지침",
}


@dataclass
class CrawlConfig:
    """크롤링 설정"""

    headless: bool = True
    timeout: int = 30000  # ms
    page_size: int = 30
    max_pages: int = 100  # 카테고리당 최대 페이지
    days_back: int = 7  # 기본 수집 기간
    categories: list[str] = field(default_factory=lambda: list(CATEGORY_MAP.keys()))


class HIRAInsuranceCriteriaIngestor(BaseIngestor):
    """
    HIRA 보험인정기준 수집기 (Playwright 기반)

    수집 대상:
    - 고시 (01)
    - 행정해석 (02)
    - 심사지침 (09)
    - 심의사례공개 (10)
    - 심사사례지침 (17)
    """

    def __init__(self, config: CrawlConfig | None = None):
        super().__init__()
        self.config = config or CrawlConfig()
        self._playwright = None
        self._browser = None

    def source_type(self) -> str:
        return "HIRA_NOTICE"

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
                "pip install 'regscan[crawl]' 또는 pip install playwright && playwright install"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self) -> list[dict[str, Any]]:
        """보험인정기준 데이터 수집"""
        target_date = datetime.now() - timedelta(days=self.config.days_back)
        all_records = []

        context = await self._browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout)

        try:
            # 초기 페이지 로드
            await page.goto(IAC_LIST_URL)
            await page.wait_for_load_state("networkidle")

            # 페이지 크기 설정
            await self._set_page_size(page, self.config.page_size)

            # 각 카테고리별 크롤링
            for tab_code in self.config.categories:
                category_name = CATEGORY_MAP.get(tab_code, tab_code)
                logger.info(f"[HIRA] 카테고리 수집 시작: {category_name}")

                records = await self._crawl_category(page, tab_code, target_date)
                all_records.extend(records)

                logger.info(f"[HIRA] {category_name}: {len(records)}건 수집")

        finally:
            await context.close()

        logger.info(f"[HIRA] 총 {len(all_records)}건 수집 완료")
        return all_records

    async def _set_page_size(self, page, size: int):
        """페이지 크기 설정"""
        try:
            # 페이지 크기 선택
            select_elem = page.locator("select#pageLen")
            if await select_elem.count() > 0:
                await select_elem.select_option(str(size))

                # Submit 버튼 클릭 + 네비게이션 대기
                submit_btn = page.locator("#btnSubmit")
                if await submit_btn.count() > 0:
                    async with page.expect_navigation(wait_until="networkidle"):
                        await submit_btn.click()

                    await page.wait_for_selector("table", state="visible", timeout=15000)
                    await asyncio.sleep(1.0)
                    logger.debug(f"페이지 크기 {size}로 설정 완료")
        except Exception as e:
            logger.warning(f"페이지 크기 설정 실패: {e}")

    async def _crawl_category(
        self, page, tab_code: str, target_date: datetime
    ) -> list[dict[str, Any]]:
        """단일 카테고리 크롤링"""
        records = []
        category_name = CATEGORY_MAP.get(tab_code, tab_code)

        # 탭 전환 (JavaScript 직접 호출)
        try:
            # goTabMove 함수 호출 + 네비게이션 대기
            async with page.expect_navigation(wait_until="networkidle"):
                await page.evaluate(f"goTabMove('{tab_code}')")

            await page.wait_for_selector("table", state="visible", timeout=15000)
            await asyncio.sleep(1.0)

            # 탭 변경 후 페이지 크기 재설정
            await self._set_page_size(page, self.config.page_size)
            logger.debug(f"탭 전환 완료: {category_name}")
        except Exception as e:
            logger.error(f"탭 전환 실패 ({category_name}): {e}")
            return records

        current_page = 1
        should_stop = False

        while not should_stop and current_page <= self.config.max_pages:
            html = await page.content()
            sel = Selector(text=html)

            # onclick에서 파라미터 추출
            onclicks = sel.xpath(
                "//a[contains(@onclick,'viewInsuAdtCrtr')]/@onclick"
            ).getall()

            if not onclicks:
                logger.debug(f"[{category_name}] 페이지 {current_page}: 게시물 없음")
                break

            for onclick in onclicks:
                # viewInsuAdtCrtr('20251201', 'sno123', 'regSno456')
                # 더 유연한 파라미터 추출
                vals = re.findall(r"'([^']+)'", onclick)
                if len(vals) < 3:
                    continue

                mtg_hme_dd, sno, mtg_mtr_reg_sno = vals[0], vals[1], vals[2]

                # 날짜 확인 (YYYYMMDD 형식)
                try:
                    pub_date = datetime.strptime(mtg_hme_dd, "%Y%m%d")
                    if pub_date < target_date:
                        logger.info(
                            f"[{category_name}] target_date 이전 게시물 발견, 중단"
                        )
                        should_stop = True
                        break
                except ValueError:
                    pub_date = None

                # 상세 페이지 파싱
                record = await self._fetch_detail(
                    page, mtg_hme_dd, sno, mtg_mtr_reg_sno, category_name
                )
                if record:
                    record["category"] = category_name
                    record["tab_code"] = tab_code
                    records.append(record)

            if should_stop:
                break

            # 다음 페이지
            next_page = await self._goto_next_page(page, current_page)
            if next_page is None:
                break
            current_page = next_page

        return records

    async def _fetch_detail(
        self,
        page,
        mtg_hme_dd: str,
        sno: str,
        mtg_mtr_reg_sno: str,
        category_name: str,
    ) -> dict[str, Any] | None:
        """상세 페이지 파싱 (팝업)"""
        popup_url = (
            f"{IAC_POPUP_URL}?mtgHmeDd={mtg_hme_dd}&sno={sno}"
            f"&mtgMtrRegSno={mtg_mtr_reg_sno}"
        )

        try:
            # 새 탭으로 팝업 열기
            popup = await page.context.new_page()
            await popup.goto(popup_url)
            await popup.wait_for_load_state("networkidle")

            html = await popup.content()
            sel = Selector(text=html)

            # 제목
            title = sel.css("div.title::text").get()
            title = title.strip() if title else ""

            # 본문
            content_parts = sel.css("div.view ::text").getall()
            content = "\n".join(t.strip() for t in content_parts if t.strip())

            # 메타데이터 (게시일, 관련근거 등)
            meta = {}
            for li in sel.css("ul > li"):
                label = li.css("span::text").get()
                if label:
                    label = label.strip().rstrip(":")
                    full_text = "".join(li.css("::text").getall()).strip()
                    value = full_text.replace(label, "").strip().lstrip(":")
                    meta[label] = value.strip()

            # 첨부파일
            files = []
            for onclick in sel.css("a.btn_file::attr(onclick)").getall():
                # Header.goDown1('src', 'filename')
                match = re.search(
                    r"Header\.goDown1\('([^']+)'\s*,\s*'([^']+)'\)", onclick
                )
                if match:
                    src, fnm = match.groups()
                    download_url = f"{IAC_DOWNLOAD_URL}?src={quote(src)}&fnm={quote(fnm)}"
                    files.append({"filename": fnm, "url": download_url})

            await popup.close()

            # 날짜 파싱
            pub_date_str = meta.get("게시일", "")
            try:
                if pub_date_str:
                    publication_date = datetime.strptime(
                        pub_date_str.replace(".", "-"), "%Y-%m-%d"
                    )
                else:
                    publication_date = datetime.strptime(mtg_hme_dd, "%Y%m%d")
            except ValueError:
                publication_date = self._now()

            return {
                "title": title,
                "content": content,
                "publication_date": publication_date.strftime("%Y-%m-%d"),
                "url": popup_url,
                "meta": meta,
                "files": files,
                "collected_at": self._now().isoformat(),
            }

        except Exception as e:
            logger.error(f"상세 페이지 파싱 실패: {popup_url}, {e}")
            return None

    async def _goto_next_page(self, page, current_page: int) -> int | None:
        """다음 페이지로 이동, 성공하면 새 페이지 번호 반환"""
        html = await page.content()
        sel = Selector(text=html)

        # goPage(N) 패턴에서 페이지 번호 추출
        page_nums = sel.css('a[onclick^="goPage"]::attr(onclick)').re(r"goPage\((\d+)\)")
        next_pages = [int(p) for p in page_nums if int(p) > current_page]

        if not next_pages:
            return None

        next_page = min(next_pages)

        try:
            btn_selector = f'a[onclick="goPage({next_page}); return false;"]'
            await page.click(btn_selector)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(0.5)
            return next_page
        except Exception as e:
            logger.warning(f"페이지 이동 실패 ({current_page} -> {next_page}): {e}")
            return None


class HIRANoticeIngestor(BaseIngestor):
    """
    HIRA 공지사항 수집기 (Playwright 기반)

    수집 대상:
    - 심평원 공지사항 페이지
    """

    def __init__(self, config: CrawlConfig | None = None):
        super().__init__()
        self.config = config or CrawlConfig()
        self._playwright = None
        self._browser = None

    def source_type(self) -> str:
        return "HIRA_NOTICE"

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
                "pip install 'regscan[crawl]' 또는 pip install playwright && playwright install"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self) -> list[dict[str, Any]]:
        """공지사항 데이터 수집"""
        target_date = datetime.now() - timedelta(days=self.config.days_back)
        records = []

        context = await self._browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout)

        try:
            await page.goto(NOTICE_LIST_URL)
            await page.wait_for_load_state("networkidle")

            # 페이지 크기 설정
            try:
                await page.select_option("select#selPageSize", str(self.config.page_size))
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(0.5)
            except Exception:
                pass

            current_page = 1
            consecutive_old = 0

            while current_page <= self.config.max_pages:
                html = await page.content()
                sel = Selector(text=html)

                rows = sel.css("table tbody tr")
                if not rows:
                    break

                for row in rows:
                    link = row.css("td.col-tit > a::attr(href)").get()
                    if not link:
                        continue

                    record = await self._fetch_notice_detail(page, link, target_date)

                    if record is None:
                        # 날짜 이전 게시물
                        consecutive_old += 1
                        if consecutive_old >= 2:
                            logger.info("[HIRA 공지] 연속 2개 이전 게시물, 종료")
                            break
                    else:
                        consecutive_old = 0
                        records.append(record)

                if consecutive_old >= 2:
                    break

                # 다음 페이지
                next_page = await self._goto_next_page(page, current_page)
                if next_page is None:
                    break
                current_page = next_page

        finally:
            await context.close()

        logger.info(f"[HIRA 공지] 총 {len(records)}건 수집 완료")
        return records

    async def _fetch_notice_detail(
        self, page, link: str, target_date: datetime
    ) -> dict[str, Any] | None:
        """공지사항 상세 페이지 파싱"""
        detail_url = urljoin(HIRA_BASE, link)

        try:
            popup = await page.context.new_page()
            await popup.goto(detail_url)
            await popup.wait_for_load_state("networkidle")

            html = await popup.content()
            sel = Selector(text=html)

            # 제목
            title = sel.css("div.title::text").get()
            title = title.strip() if title else ""

            # 작성자/날짜
            writer_lis = sel.css("ul.writer > li::text").getall()
            publication_date_str = ""
            if len(writer_lis) >= 2:
                publication_date_str = writer_lis[1].strip()

            # 날짜 파싱 및 필터링
            try:
                pub_date = datetime.strptime(publication_date_str, "%Y-%m-%d")
                if pub_date < target_date:
                    await popup.close()
                    return None  # 이전 게시물
            except ValueError:
                pub_date = self._now()

            # 본문
            content_parts = []
            for p in sel.css("div.view p"):
                p_text = "".join(p.css("::text").getall()).strip()
                if p_text:
                    content_parts.append(p_text)
            content = "\n".join(content_parts)

            # 첨부파일
            files = []
            for onclick in sel.css("a.btn_file::attr(onclick)").getall():
                # downLoadBbs('apndNo','apndBrdBltNo','apndBrdTyNo','apndBltNo')
                match = re.search(
                    r"downLoadBbs\('([^']+)','([^']+)','([^']+)','([^']+)'\)",
                    onclick,
                )
                if match:
                    apnd_no, apnd_brd_blt_no, apnd_brd_ty_no, apnd_blt_no = match.groups()
                    download_url = (
                        f"{NOTICE_DOWNLOAD_URL}?apndNo={apnd_no}"
                        f"&apndBrdBltNo={apnd_brd_blt_no}"
                        f"&apndBrdTyNo={apnd_brd_ty_no}"
                        f"&apndBltNo={apnd_blt_no}"
                    )
                    files.append({"url": download_url})

            await popup.close()

            return {
                "title": title,
                "content": content,
                "publication_date": pub_date.strftime("%Y-%m-%d"),
                "url": detail_url,
                "files": files,
                "collected_at": self._now().isoformat(),
            }

        except Exception as e:
            logger.error(f"공지사항 상세 파싱 실패: {detail_url}, {e}")
            return None

    async def _goto_next_page(self, page, current_page: int) -> int | None:
        """다음 페이지로 이동"""
        html = await page.content()
        sel = Selector(text=html)

        page_nums = sel.css('a[onclick^="goPage"]::attr(onclick)').re(r"goPage\((\d+)\)")
        next_pages = [int(p) for p in page_nums if int(p) > current_page]

        if not next_pages:
            return None

        next_page = min(next_pages)

        try:
            btn_selector = f'a[onclick="goPage({next_page}); return false;"]'
            await page.click(btn_selector)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(0.5)
            return next_page
        except Exception:
            return None


class HIRAGuidelineIngestor(BaseIngestor):
    """심사지침 수집 (HIRAInsuranceCriteriaIngestor의 subset)"""

    def __init__(self, config: CrawlConfig | None = None):
        super().__init__()
        # 심사지침 카테고리만 수집
        self.config = config or CrawlConfig(categories=["09"])
        self._ingestor = HIRAInsuranceCriteriaIngestor(self.config)

    def source_type(self) -> str:
        return "HIRA_GUIDELINE"

    async def __aenter__(self):
        await self._ingestor.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._ingestor.__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self) -> list[dict[str, Any]]:
        return await self._ingestor.fetch()
