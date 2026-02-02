"""보건복지부 데이터 수집 - Playwright 기반"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from parsel import Selector

from .base import BaseIngestor
from .hira import CrawlConfig

logger = logging.getLogger(__name__)


# =============================================================================
# URL 상수
# =============================================================================
MOHW_BASE = "https://www.mohw.go.kr"

# 입법/행정예고 페이지
PRE_ANNOUNCEMENT_URL = f"{MOHW_BASE}/menu.es?mid=a10409030000"

# epeople 파일 다운로드
EPEOPLE_DOWNLOAD_URL = "https://www.epeople.go.kr/paid/syscmmn/fileDwld.npaid"


class MOHWPreAnnouncementIngestor(BaseIngestor):
    """
    보건복지부 입법/행정예고 수집기 (Playwright 기반)

    수집 대상:
    - 입법예고 (법령 제/개정 예고)
    - 행정예고 (행정규칙 제/개정 예고)

    핵심 가치:
    - 아직 확정되지 않은 규제 → 의견제출 가능
    - "미래 규제 신호" 감지
    """

    def __init__(self, config: CrawlConfig | None = None):
        super().__init__()
        self.config = config or CrawlConfig(days_back=30)
        self._playwright = None
        self._browser = None

    def source_type(self) -> str:
        return "MOHW_ADMIN_NOTICE"

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
        """입법/행정예고 데이터 수집"""
        records = []

        context = await self._browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout)

        try:
            logger.info("[MOHW] 입법/행정예고 수집 시작")

            # 페이지 로드
            await page.goto(PRE_ANNOUNCEMENT_URL)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2.0)

            # iframe으로 전환
            iframe = await self._switch_to_iframe(page)
            if not iframe:
                logger.error("[MOHW] iframe 전환 실패")
                return records

            # 전체 페이지 수 확인
            total_pages = await self._get_total_pages(iframe)
            logger.info(f"[MOHW] 총 {total_pages} 페이지")

            # 페이지별 크롤링
            for page_num in range(1, min(total_pages + 1, self.config.max_pages + 1)):
                if page_num > 1:
                    success = await self._navigate_to_page(iframe, page_num)
                    if not success:
                        break

                # 목록 데이터 추출
                page_records = await self._extract_list_data(iframe)

                for item in page_records:
                    # 상세 페이지에서 내용 추출
                    if item.get("idea_reg_no"):
                        detail = await self._fetch_detail(iframe, item)
                        item.update(detail)

                    # 기간에서 종료일 추출하여 필터링
                    if self._is_expired(item.get("period", "")):
                        item["status"] = "완료"

                    records.append(item)

                logger.info(f"[MOHW] 페이지 {page_num}: {len(page_records)}건")

        except Exception as e:
            logger.error(f"[MOHW] 수집 중 오류: {e}")
        finally:
            await context.close()

        logger.info(f"[MOHW] 총 {len(records)}건 수집 완료")
        return records

    async def _switch_to_iframe(self, page):
        """iframe으로 전환"""
        try:
            iframe_element = await page.wait_for_selector("iframe", timeout=10000)
            if iframe_element:
                iframe = await iframe_element.content_frame()
                await asyncio.sleep(1.0)
                return iframe
        except Exception as e:
            logger.warning(f"iframe 전환 실패: {e}")
        return None

    async def _get_total_pages(self, frame) -> int:
        """전체 페이지 수 확인"""
        try:
            # <span class="paging_count">1/73</span>
            paging_elem = await frame.wait_for_selector(".paging_count", timeout=5000)
            if paging_elem:
                text = await paging_elem.text_content()
                if "/" in text:
                    return int(text.strip().split("/")[1])
        except Exception as e:
            logger.warning(f"페이지 수 확인 실패: {e}")
        return 1

    async def _navigate_to_page(self, frame, page_num: int) -> bool:
        """특정 페이지로 이동"""
        try:
            # fn_searchElecPblntcList(page) 호출
            await frame.evaluate(f"fn_searchElecPblntcList({page_num})")
            await asyncio.sleep(1.5)

            # 테이블 로드 대기
            await frame.wait_for_selector(
                "table.tbl.default.brd9 tbody", timeout=10000
            )
            return True
        except Exception as e:
            logger.error(f"페이지 {page_num} 이동 실패: {e}")
            return False

    async def _extract_list_data(self, frame) -> list[dict[str, Any]]:
        """목록 페이지에서 데이터 추출"""
        records = []

        try:
            html = await frame.content()
            sel = Selector(text=html)

            rows = sel.css("table.tbl.default.brd9 tbody tr")

            for row in rows:
                tds = row.css("td")
                if len(tds) < 4:
                    continue

                # 번호
                number = tds[0].css("::text").get()
                number = number.strip() if number else ""

                # 진행상태
                status = tds[1].css("span::text").get()
                if not status:
                    status = tds[1].css("::text").get()
                status = status.strip() if status else ""

                # 제목 및 onclick
                title = tds[2].css("a::text").get()
                title = title.strip() if title else ""

                onclick = tds[2].css("a::attr(onclick)").get()
                idea_reg_no = None
                if onclick:
                    match = re.search(r"fn_elecPblntcDetailView\('([^']+)'\)", onclick)
                    if match:
                        idea_reg_no = match.group(1)

                # 기간
                period = tds[3].css("::text").get()
                period = period.strip() if period else ""

                records.append({
                    "number": number,
                    "status": status,
                    "title": title,
                    "period": period,
                    "idea_reg_no": idea_reg_no,
                    "collected_at": self._now().isoformat(),
                })

        except Exception as e:
            logger.error(f"목록 데이터 추출 실패: {e}")

        return records

    async def _fetch_detail(self, frame, item: dict) -> dict[str, Any]:
        """상세 페이지에서 내용 추출"""
        idea_reg_no = item.get("idea_reg_no")
        if not idea_reg_no:
            return {}

        try:
            # 상세 페이지 클릭
            link_xpath = f"//a[contains(@onclick, \"{idea_reg_no}\")]"
            link = await frame.wait_for_selector(f"xpath={link_xpath}", timeout=5000)
            if link:
                await link.click()
                await asyncio.sleep(2.0)

            html = await frame.content()
            sel = Selector(text=html)

            # 테이블에서 메타데이터 추출
            meta = {}
            for row in sel.css("table.tbl tr"):
                ths = row.css("th::text").getall()
                tds = row.css("td::text").getall()
                for th, td in zip(ths, tds):
                    if th and td:
                        meta[th.strip()] = td.strip()

            # 본문 내용 추출
            content_parts = []

            # b_info (두 번째)
            b_info_texts = sel.css("div.b_info::text").getall()
            if len(b_info_texts) >= 2:
                content_parts.append(b_info_texts[1].strip())

            # b_content
            b_content = sel.css("div.b_content ::text").getall()
            content_parts.extend([t.strip() for t in b_content if t.strip()])

            content = "\n".join(content_parts)

            # URL 생성
            detail_url = f"https://www.epeople.go.kr/cmmn/idea/redirectGo.do?ideaRegNo={idea_reg_no}"

            # 첨부파일 정보 추출
            files = []
            for link in sel.css("div.file_Attach div.file_dw a"):
                onclick = link.css("::attr(onclick)").get()
                if onclick:
                    match = re.search(
                        r"fn_fileDownload\('([^']+)','([^']+)'\)", onclick
                    )
                    if match:
                        atch_file_id, atch_file_grp_id = match.groups()
                        download_url = (
                            f"{EPEOPLE_DOWNLOAD_URL}"
                            f"?atchFileGrpId={atch_file_grp_id}"
                            f"&atchFileId={atch_file_id}"
                        )
                        filename = link.css("::text").get()
                        files.append({
                            "filename": filename.strip() if filename else "",
                            "url": download_url,
                        })

            # 뒤로 가기
            await frame.evaluate("window.history.back()")
            await asyncio.sleep(1.5)
            await frame.wait_for_selector(
                "table.tbl.default.brd9 tbody", timeout=10000
            )

            return {
                "content": content,
                "url": detail_url,
                "meta": meta,
                "files": files,
            }

        except Exception as e:
            logger.error(f"상세 페이지 추출 실패 ({idea_reg_no}): {e}")
            # 복구 시도
            try:
                await frame.evaluate("window.history.back()")
                await asyncio.sleep(1.0)
            except Exception:
                pass
            return {}

    def _is_expired(self, period: str) -> bool:
        """기간이 만료되었는지 확인"""
        if not period:
            return False

        try:
            # "2025.12.10~ 2026.01.14" 형식
            parts = re.split(r"~", period)
            if len(parts) < 2:
                return False

            end_date_str = parts[1].strip()
            end_date = datetime.strptime(end_date_str, "%Y.%m.%d").date()
            return datetime.now().date() > end_date
        except ValueError:
            return False


# 기존 클래스 유지 (하위 호환성)
class MOHWNoticeIngestor(BaseIngestor):
    """복지부 고시 수집 (미구현)"""

    BASE_URL = "https://www.mohw.go.kr"

    def source_type(self) -> str:
        return "MOHW_NOTICE"

    async def fetch(self) -> list[dict[str, Any]]:
        # 고시는 HIRA 보험인정기준과 중복될 수 있음
        # 필요시 추후 구현
        return []


class MOHWAdminNoticeIngestor(MOHWPreAnnouncementIngestor):
    """행정예고 수집 (별칭)"""
    pass
