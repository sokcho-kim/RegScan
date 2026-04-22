"""MFDS (식약처) 안전성 서한/속보 + 회수·판매중지 수집

안전성 서한: nedrug.mfds.go.kr/pbp/CCBAC01 — httpx + bs4 (SSR 페이지, Playwright 불필요)
회수/판매중지: data.go.kr API (15059114)
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

NEDRUG_BASE = "https://nedrug.mfds.go.kr"
SAFETY_LETTER_URL = f"{NEDRUG_BASE}/pbp/CCBAC01"
SAFETY_LETTER_DETAIL_URL = f"{NEDRUG_BASE}/pbp/CCBAC01/getItem"


# ── 안전성 서한/속보 크롤러 (httpx + bs4) ─────────────────────────


class MFDSSafetyLetterIngestor(BaseIngestor):
    """MFDS 안전성 서한/속보 수집기 (httpx + BeautifulSoup)

    nedrug.mfds.go.kr/pbp/CCBAC01 — SSR 페이지라 Playwright 불필요.
    POST form submit으로 페이지네이션.

    수집 필드: 제목, 요약, 담당부서, 공고일, 조회수, 상세 URL
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
        page_size: int = 50,
        max_pages: int = 20,
        fetch_detail: bool = False,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.page_size = page_size
        self.max_pages = max_pages
        self.fetch_detail = fetch_detail

    async def __aenter__(self):
        # nedrug.mfds.go.kr는 TLS 1.3 미지원 → TLS 1.2 강제
        ctx = ssl.create_default_context()
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        self._client = httpx.AsyncClient(timeout=self.timeout, verify=ctx)
        return self

    def source_type(self) -> str:
        return "MFDS_SAFETY_LETTER"

    async def fetch(self) -> list[dict[str, Any]]:
        """안전성 서한/속보 목록 수집"""
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        records: list[dict[str, Any]] = []

        logger.info("[MFDS Safety] 안전성 서한/속보 수집 시작")

        for page_num in range(1, self.max_pages + 1):
            html = await self._fetch_page(page_num)
            if not html:
                break

            page_records, should_stop = self._parse_list(html, cutoff)
            records.extend(page_records)

            logger.info(
                "[MFDS Safety] 페이지 %d: %d건", page_num, len(page_records),
            )

            if should_stop or not page_records:
                break

            await asyncio.sleep(0.3)

        if self.fetch_detail and records:
            await self._fetch_details(records)

        logger.info(
            "[MFDS Safety] 안전성 서한/속보 %d건 수집 (최근 %d일)",
            len(records), self.days_back,
        )
        return records

    async def _fetch_page(self, page_num: int) -> str | None:
        """목록 페이지 HTML 가져오기 (재시도 포함)"""
        try:
            response = await self._request_with_retry(
                "POST",
                SAFETY_LETTER_URL,
                data={"page": str(page_num), "pageSize": str(self.page_size)},
                max_retries=3,
                retry_delay=2.0,
            )
            return response.text
        except Exception as e:
            logger.error("[MFDS Safety] 페이지 %d 요청 실패 (재시도 소진): %s", page_num, e)
            return None

    def _parse_list(
        self, html: str, cutoff,
    ) -> tuple[list[dict[str, Any]], bool]:
        """HTML에서 안전성 서한 목록 파싱"""
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict[str, Any]] = []
        should_stop = False

        rows = soup.select("table tbody tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue

            # 제목 + 링크
            link = cols[1].find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            # 상세 URL: safeLetterNo=NNN
            href = link.get("href", "") or link.get("onclick", "") or ""
            detail_url = ""
            letter_match = re.search(r"safeLetterNo=(\d+)", href)
            if letter_match:
                detail_url = (
                    f"{SAFETY_LETTER_DETAIL_URL}"
                    f"?safeLetterNo={letter_match.group(1)}"
                )

            # 요약 (3번째 컬럼) — 헤더 텍스트 제거
            summary = cols[2].get_text(strip=True) if len(cols) >= 3 else ""
            for prefix in ("요약", "summary"):
                if summary.startswith(prefix):
                    summary = summary[len(prefix):].strip()

            # 담당부서 (4번째 컬럼) — 헤더 텍스트 제거
            department = cols[3].get_text(strip=True) if len(cols) >= 4 else ""
            for prefix in ("담당부서", "department"):
                if department.startswith(prefix):
                    department = department[len(prefix):].strip()

            # 조회수 (5번째 컬럼)
            views = 0
            if len(cols) >= 5:
                views_text = cols[4].get_text(strip=True).replace(",", "")
                views_match = re.search(r"(\d+)", views_text)
                if views_match:
                    views = int(views_match.group(1))

            # 공고일 (마지막 컬럼에서 날짜 탐색)
            date_str = ""
            for col in reversed(cols):
                text = col.get_text(strip=True)
                date_match = re.search(r"(\d{4}[.-]\d{2}[.-]\d{2})", text)
                if date_match:
                    date_str = date_match.group(1).replace(".", "-")
                    break

            # 날짜 필터
            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            records.append({
                "source": "MFDS",
                "source_type": "MFDS_SAFETY_LETTER",
                "title": title,
                "summary": summary,
                "department": department,
                "views": views,
                "date": date_str,
                "url": detail_url,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop

    async def _fetch_details(self, records: list[dict[str, Any]]) -> None:
        """상세 페이지에서 본문 + 첨부파일 수집"""
        for i, record in enumerate(records):
            url = record.get("url", "")
            if not url:
                continue

            try:
                response = await self.client.get(
                    url, follow_redirects=True,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                # 본문
                content_el = soup.select_one(
                    "div.view_cont, div.board_view_content, "
                    "div.cont_area, div.container_wrap"
                )
                if content_el:
                    record["content"] = content_el.get_text(
                        separator="\n", strip=True,
                    )

                # 첨부파일
                files = []
                for fl in soup.select(
                    "a[href*='download'], a.file_down, "
                    "div.file_list a, div.file_attach a"
                ):
                    filename = fl.get_text(strip=True)
                    fhref = fl.get("href", "")
                    if filename and fhref:
                        files.append({
                            "filename": filename,
                            "url": (
                                f"{NEDRUG_BASE}{fhref}"
                                if fhref.startswith("/") else fhref
                            ),
                        })
                if files:
                    record["files"] = files

                logger.debug(
                    "[MFDS Safety] 상세 %d/%d: %s",
                    i + 1, len(records), record["title"][:30],
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(
                    "[MFDS Safety] 상세 수집 실패 (%s): %s", url, e,
                )


# ── 회수·판매중지 API (data.go.kr) ─────────────────────────────


class MFDSSafetyClient:
    """MFDS 회수·판매중지 API 클라이언트 (data.go.kr)"""

    RECALL_ENDPOINT = (
        "http://apis.data.go.kr/1471000/MdcinRtrvlSleStpgeInfoService04"
        "/getMdcinRtrvlSleStpgelList03"
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.DATA_GO_KR_API_KEY
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "MFDSSafetyClient must be used as async context manager"
            )
        return self._client

    async def fetch_recalls(
        self,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> dict[str, Any]:
        """회수/판매중지 조회"""
        params = {
            "serviceKey": self.api_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
        }
        return await self._request(self.RECALL_ENDPOINT, params)

    async def _request(
        self,
        url: str,
        params: dict,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """API 요청 (이중 인코딩 방지)"""
        last_error = None
        params = params.copy()
        service_key = params.pop("serviceKey", "")

        for attempt in range(max_retries):
            try:
                query_string = urlencode(params)
                full_url = f"{url}?serviceKey={service_key}&{query_string}"

                response = await self.client.get(full_url)

                if response.status_code == 429:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning("Rate limited, waiting %ss...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                if "header" in data:
                    result_code = data["header"].get("resultCode", "00")
                    if result_code != "00":
                        error_msg = data["header"].get(
                            "resultMsg", "Unknown error"
                        )
                        raise Exception(
                            f"API Error ({result_code}): {error_msg}"
                        )

                return data

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning("HTTP error (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(retry_delay)

            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    "Request error (attempt %d): %s", attempt + 1, e,
                )
                await asyncio.sleep(retry_delay)

        raise last_error or Exception("MFDS Safety API request failed")


class MFDSRecallIngestor(BaseIngestor):
    """MFDS 의약품 회수/판매중지 수집기 (data.go.kr API)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        days_back: int = 90,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.days_back = days_back

    def source_type(self) -> str:
        return "MFDS_RECALL"

    async def fetch(self) -> list[dict[str, Any]]:
        """회수/판매중지 수집 (최근 N일)"""
        all_results = []
        cutoff = datetime.now() - timedelta(days=self.days_back)
        cutoff_str = cutoff.strftime("%Y%m%d")

        async with MFDSSafetyClient(
            api_key=self.api_key, timeout=self.timeout,
        ) as client:
            page_no = 1

            while True:
                response = await client.fetch_recalls(
                    page_no=page_no, num_of_rows=100,
                )

                body = response.get("body", {})
                items = body.get("items", [])
                if not items:
                    break

                for item in items:
                    recall_date = item.get(
                        "RECALL_COMMAND_DATE", ""
                    ) or item.get("CREATE_DATE", "")
                    if (
                        recall_date
                        and recall_date.replace("-", "") >= cutoff_str
                    ):
                        item["_source"] = "mfds_recall"
                        item["_fetched_at"] = datetime.now().strftime(
                            "%Y-%m-%d"
                        )
                        all_results.append(item)

                total = body.get("totalCount", 0)
                if page_no * 100 >= total:
                    break

                page_no += 1
                await asyncio.sleep(0.1)

        logger.info(
            "[MFDS Safety] 회수/판매중지 %d건 수집 (최근 %d일)",
            len(all_results), self.days_back,
        )
        return all_results
