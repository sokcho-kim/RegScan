"""HIRA 약제 기준정보 수집기 (9개 게시판)

수집 대상:
  P0: 약제급여평가위원회, 암질환_공고
  P1: 약제급여목록표, 암질환_공고예고
  P2: 항암화학요법, 주성분별가중평균
  P3: 퇴장방지의약품, 저가약대체조제, FAQ

scrape-hub/project/hira_drug_info에서 검증된 로직을 BaseIngestor로 포팅.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from parsel import Selector

from .base import BaseIngestor

logger = logging.getLogger(__name__)

HIRA_BASE = "https://www.hira.or.kr"

# 9개 게시판 설정
DRUG_INFO_BOARDS = {
    "약제급여평가위원회": {
        "pgmid": "HIRAA030014040000",
        "source_type": "HIRA_DRUG_COMMITTEE",
        "priority": "P0",
    },
    "암질환_공고": {
        "pgmid": "HIRAA030023010000",
        "source_type": "HIRA_CANCER_NOTICE",
        "priority": "P0",
    },
    "약제급여목록표": {
        "pgmid": "HIRAA030014050000",
        "source_type": "HIRA_DRUG_LIST",
        "priority": "P1",
    },
    "암질환_공고예고": {
        "pgmid": "HIRAA030023020000",
        "source_type": "HIRA_CANCER_PRENOTICE",
        "priority": "P1",
    },
    "항암화학요법": {
        "pgmid": "HIRAA030023030000",
        "source_type": "HIRA_CHEMO_REGIMEN",
        "priority": "P2",
    },
    "주성분별가중평균": {
        "pgmid": "HIRAA030017000000",
        "source_type": "HIRA_WEIGHTED_PRICE",
        "priority": "P2",
    },
    "퇴장방지의약품": {
        "pgmid": "HIRAA030019000000",
        "source_type": "HIRA_EXIT_PREVENTION",
        "priority": "P3",
    },
    "저가약대체조제": {
        "pgmid": "HIRAA030015000000",
        "source_type": "HIRA_GENERIC_SUBST",
        "priority": "P3",
    },
    "FAQ": {
        "pgmid": "HIRAA030023080000",
        "source_type": "HIRA_CANCER_FAQ",
        "priority": "P3",
    },
}


@dataclass
class DrugInfoConfig:
    """약제 기준정보 수집 설정"""

    headless: bool = True
    timeout: int = 30000
    days_back: int = 30
    max_pages: int = 5
    boards: list[str] = field(default_factory=lambda: list(DRUG_INFO_BOARDS.keys()))


class HIRADrugInfoIngestor(BaseIngestor):
    """HIRA 약제 기준정보 통합 수집기 (Playwright 기반)

    9개 게시판에서 약제 급여/평가/가격 정보를 수집한다.
    RegScan의 기사 파이프라인과 DB 적재에 활용.
    """

    def __init__(self, config: DrugInfoConfig | None = None):
        super().__init__()
        self.config = config or DrugInfoConfig()
        self._playwright = None
        self._browser = None

    def source_type(self) -> str:
        return "HIRA_DRUG_INFO"

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
                "playwright 필요: pip install playwright && playwright install"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def fetch(self) -> list[dict[str, Any]]:
        """설정된 게시판들에서 데이터 수집"""
        target_date = datetime.now() - timedelta(days=self.config.days_back)
        all_records = []

        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout)

        try:
            for board_name in self.config.boards:
                board = DRUG_INFO_BOARDS[board_name]
                logger.info(f"[HIRA 약제] {board_name} 수집 시작")

                records = await self._crawl_board(
                    page, board_name, board, target_date
                )
                all_records.extend(records)
                logger.info(f"[HIRA 약제] {board_name}: {len(records)}건")

        finally:
            await context.close()

        logger.info(f"[HIRA 약제] 총 {len(all_records)}건 수집 완료")
        return all_records

    async def _crawl_board(
        self,
        page,
        board_name: str,
        board: dict,
        target_date: datetime,
    ) -> list[dict[str, Any]]:
        """단일 게시판 크롤링"""
        pgmid = board["pgmid"]
        # 약제급여목록표는 bbsDummyKR.do 사용
        endpoint = "bbsDummyKR.do" if board_name == "약제급여목록표" else "bbsDummy.do"
        url = f"{HIRA_BASE}/{endpoint}?pgmid={pgmid}"

        records = []

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"[{board_name}] 페이지 로드 실패: {e}")
            return records

        for page_num in range(1, self.config.max_pages + 1):
            if page_num > 1:
                try:
                    await page.evaluate(f"goPage({page_num})")
                    await asyncio.sleep(2)
                except Exception:
                    break

            html = await page.content()
            posts = self._parse_list(html, board_name)

            if not posts:
                break

            stop = False
            for post in posts:
                # 날짜 필터
                pub_date = self._parse_date(post.get("date", ""))
                if pub_date and pub_date < target_date:
                    stop = True
                    break

                # 상세 페이지 파싱
                detail = await self._fetch_detail(page, post, board_name, pgmid)
                if detail:
                    detail["source_type"] = board["source_type"]
                    detail["board"] = board_name
                    detail["pgmid"] = pgmid
                    detail["collected_at"] = self._now().isoformat()
                    records.append(detail)

                # 목록으로 복귀
                await page.go_back()
                await asyncio.sleep(1)

            if stop:
                break

        return records

    def _parse_list(self, html: str, board_name: str) -> list[dict]:
        """게시판 목록 파싱 (게시판 유형별 분기)"""
        sel = Selector(text=html)
        rows = sel.css("table tbody tr")
        if not rows:
            # tbody 없이 tr만 있는 경우
            rows = sel.css("table tr")[1:]  # 헤더 제외

        if not rows:
            return []

        # 약제급여평가위원회: 특수 테이블 (성분명/제품명/업소명/평가결과)
        headers = sel.css("table tr:first-child th::text, table tr:first-child td::text").getall()
        header_str = " ".join(h.strip() for h in headers)

        if "성분명" in header_str or "평가결과" in header_str:
            return self._parse_committee_list(rows)

        return self._parse_standard_list(rows)

    def _parse_committee_list(self, rows) -> list[dict]:
        """약제급여평가위원회 테이블"""
        posts = []
        for row in rows:
            cells = row.css("td")
            if len(cells) < 5:
                continue

            session = cells[0].css("::text").get("").strip()
            ingredient = cells[1].css("::text").get("").strip()
            product = cells[2].css("::text").get("").strip()
            company = cells[3].css("::text").get("").strip()
            result = cells[4].css("::text").get("").strip()

            # 링크 추출
            href = row.css("a::attr(href)").get("")
            onclick = row.css("a::attr(onclick)").get("")

            posts.append({
                "title": f"{ingredient} ({product})",
                "date": "",
                "href": href,
                "onclick": onclick,
                "metadata": {
                    "session": session,
                    "ingredient": ingredient,
                    "product": product,
                    "company": company,
                    "result": result,
                },
            })
        return posts

    def _parse_standard_list(self, rows) -> list[dict]:
        """일반 게시판 목록"""
        posts = []
        for row in rows:
            cells = row.css("td")
            if len(cells) < 3:
                continue

            # 제목 + 링크
            title_cell = row.css("td.col-tit, td:nth-child(2)")
            title = title_cell.css("::text").get("").strip()
            href = row.css("a::attr(href)").get("")
            onclick = row.css("a::attr(onclick)").get("")

            # 날짜 (보통 마지막 or 세번째 칸)
            date = ""
            for cell in cells:
                text = cell.css("::text").get("").strip()
                if re.match(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                    date = text
                    break

            posts.append({
                "title": title,
                "date": date,
                "href": href,
                "onclick": onclick,
                "metadata": {},
            })
        return posts

    async def _fetch_detail(
        self, page, post: dict, board_name: str, pgmid: str
    ) -> dict[str, Any] | None:
        """상세 페이지 파싱"""
        try:
            navigated = False
            href = post.get("href", "")
            onclick = post.get("onclick", "")

            # href 기반 이동
            if href and "brdBltNo" in href:
                endpoint = "bbsDummyKR.do" if board_name == "약제급여목록표" else "bbsDummy.do"
                full_url = f"{HIRA_BASE}/{endpoint}{href}" if not href.startswith("http") else href
                await page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                navigated = True

            # onclick JS 기반 이동
            if not navigated and onclick:
                js_code = onclick.replace("return false;", "").strip().rstrip(";")
                try:
                    await page.evaluate(js_code)
                    await asyncio.sleep(2)
                    navigated = True
                except Exception as e:
                    logger.warning(f"JS 실행 실패: {e}")

            if not navigated:
                return None

            html = await page.content()
            sel = Selector(text=html)

            # 제목
            title = sel.css("div.viewCont div.title::text, div.title::text").get("")
            title = title.strip() or post.get("title", "")

            # 메타 (ul.writer → 부서, 날짜)
            meta = post.get("metadata", {})
            writer_texts = sel.css("ul.writer li::text").getall()
            for t in writer_texts:
                t = t.strip()
                if re.match(r"\d{4}-\d{2}-\d{2}", t):
                    meta["published_date"] = t
                elif t and not re.match(r"[\d\-,.]+$", t):
                    meta["department"] = t

            # 본문
            content_parts = sel.css("div.view ::text").getall()
            content = "\n".join(t.strip() for t in content_parts if t.strip())

            # 첨부파일 목록
            files = []
            for li in sel.css("div.fileBox ul li"):
                filename = ""
                for text in li.css("::text").getall():
                    text = text.strip()
                    if text and len(text) > 2:
                        filename = text
                        break
                onclick_attr = li.css("a::attr(onclick)").get("")
                if filename or onclick_attr:
                    files.append({"filename": filename, "onclick": onclick_attr})

            # 날짜 결정
            pub_date = meta.get("published_date", "") or post.get("date", "")
            pub_date = pub_date.replace(".", "-")

            return {
                "title": title,
                "content": content,
                "publication_date": pub_date,
                "url": page.url,
                "files": files,
                "metadata": meta,
            }

        except Exception as e:
            logger.error(f"상세 파싱 실패 ({board_name}): {e}")
            return None

    def _parse_date(self, date_str: str) -> datetime | None:
        """날짜 문자열 → datetime"""
        if not date_str:
            return None
        date_str = date_str.replace(".", "-").strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None


# ── 게시판별 단일 인제스터 (편의 클래스) ───────────────────────────


class HIRADrugCommitteeIngestor(HIRADrugInfoIngestor):
    """약제급여평가위원회 전용 (신약 급여 심의 결과)"""

    def __init__(self, config: DrugInfoConfig | None = None):
        cfg = config or DrugInfoConfig(boards=["약제급여평가위원회"])
        if config:
            cfg.boards = ["약제급여평가위원회"]
        super().__init__(cfg)

    def source_type(self) -> str:
        return "HIRA_DRUG_COMMITTEE"


class HIRACancerNoticeIngestor(HIRADrugInfoIngestor):
    """암질환 급여 공고 전용"""

    def __init__(self, config: DrugInfoConfig | None = None):
        cfg = config or DrugInfoConfig(boards=["암질환_공고", "암질환_공고예고"])
        if config:
            cfg.boards = ["암질환_공고", "암질환_공고예고"]
        super().__init__(cfg)

    def source_type(self) -> str:
        return "HIRA_CANCER_NOTICE"


class HIRADrugListIngestor(HIRADrugInfoIngestor):
    """약제급여목록표 전용 (급여 등재 목록 + 상한금액)"""

    def __init__(self, config: DrugInfoConfig | None = None):
        cfg = config or DrugInfoConfig(boards=["약제급여목록표"])
        if config:
            cfg.boards = ["약제급여목록표"]
        super().__init__(cfg)

    def source_type(self) -> str:
        return "HIRA_DRUG_LIST"
