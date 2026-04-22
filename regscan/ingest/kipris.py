"""KIPRIS (특허정보원) 수집기 — 의약품 특허 현황 모니터링

plus.kipris.or.kr OpenAPI — 특허·실용 공개·등록공보
엔드포인트: /kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch
무료 월 1,000건 제한.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

API_URL = (
    "http://plus.kipris.or.kr/kipo-api/kipi"
    "/patUtiModInfoSearchSevice/getWordSearch"
)

# 의약품 특허 검색 키워드
PHARMA_PATENT_KEYWORDS = [
    "의약품",
    "약학 조성물",
    "항체 치료",
    "바이오시밀러",
    "제네릭 의약",
]

# IPC(국제특허분류) 의약 관련 코드
PHARMA_IPC_CODES = ["A61K", "A61P", "C07K", "C07D", "C12N"]


class KIPRISPatentIngestor(BaseIngestor):
    """KIPRIS 의약품 특허 수집기 (getWordSearch)

    키워드 검색 + IPC 코드 필터로 의약품 관련 특허 수집.
    year 파라미터로 최근 N년 범위 지정.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        years: int = 3,
        num_of_rows: int = 50,
        max_pages: int = 2,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key or getattr(settings, "KIPRIS_API_KEY", None)
        self.years = years
        self.num_of_rows = num_of_rows
        self.max_pages = max_pages

    def source_type(self) -> str:
        return "KIPRIS_PATENT"

    async def fetch(self) -> list[dict[str, Any]]:
        """의약품 특허 검색"""
        if not self.api_key:
            logger.warning("[KIPRIS] KIPRIS_API_KEY 미설정, 스킵")
            return []

        all_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for keyword in PHARMA_PATENT_KEYWORDS:
            records = await self._search_patents(keyword, seen_ids)
            all_records.extend(records)

        all_records.sort(key=lambda r: r.get("date", ""), reverse=True)

        logger.info(
            "[KIPRIS] 의약품 특허 %d건 수집 (최근 %d년, %d개 키워드)",
            len(all_records), self.years, len(PHARMA_PATENT_KEYWORDS),
        )
        return all_records

    async def _search_patents(
        self,
        keyword: str,
        seen_ids: set[str],
    ) -> list[dict[str, Any]]:
        """키워드별 특허 검색"""
        records: list[dict[str, Any]] = []

        for page_no in range(1, self.max_pages + 1):
            params = {
                "ServiceKey": self.api_key,
                "word": keyword,
                "year": self.years,
                "patent": "true",
                "utility": "false",
                "numOfRows": self.num_of_rows,
                "pageNo": page_no,
            }

            try:
                response = await self.client.get(
                    API_URL, params=params, follow_redirects=True,
                )
                response.raise_for_status()
            except Exception as e:
                logger.error(
                    "[KIPRIS] API 요청 실패 (%s, p%d): %s",
                    keyword, page_no, e,
                )
                break

            items = self._parse_xml(response.text, seen_ids, keyword)
            records.extend(items)

            if not items:
                break

        return records

    def _parse_xml(
        self,
        xml_text: str,
        seen_ids: set[str],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """XML 응답 파싱"""
        soup = BeautifulSoup(xml_text, "xml")
        now_str = self._now().strftime("%Y-%m-%d")

        # 에러 체크
        success = _get_text(soup, "successYN")
        if success == "N":
            msg = _get_text(soup, "resultMsg")
            logger.warning("[KIPRIS] API 에러: %s", msg)
            return []

        records: list[dict[str, Any]] = []

        for item in soup.find_all("item"):
            app_no = _get_text(item, "applicationNumber")
            if not app_no or app_no in seen_ids:
                continue
            seen_ids.add(app_no)

            title = _get_text(item, "inventionTitle")
            ipc_code = _get_text(item, "ipcNumber")

            # IPC 의약 관련 필터
            is_pharma_ipc = any(
                code in (ipc_code or "") for code in PHARMA_IPC_CODES
            )

            # 날짜 (등록 > 공개 > 출원)
            reg_date = _get_text(item, "registerDate")
            open_date = _get_text(item, "openDate")
            app_date = _get_text(item, "applicationDate")
            raw_date = reg_date or open_date or app_date or ""
            date_str = _format_date(raw_date)

            records.append({
                "source": "KIPRIS",
                "source_type": "KIPRIS_PATENT",
                "title": title,
                "application_number": app_no,
                "applicant": _get_text(item, "applicantName"),
                "application_date": _format_date(app_date),
                "open_date": _format_date(open_date),
                "register_date": _format_date(reg_date),
                "register_number": _get_text(item, "registerNumber"),
                "register_status": _get_text(item, "registerStatus"),
                "ipc_code": ipc_code,
                "is_pharma_ipc": is_pharma_ipc,
                "abstract": (_get_text(item, "astrtCont") or "")[:300],
                "date": date_str,
                "matched_keyword": keyword,
                "_fetched_at": now_str,
            })

        return records


def _get_text(parent, tag_name: str) -> str:
    """XML 태그에서 텍스트 추출"""
    el = parent.find(tag_name)
    return el.get_text(strip=True) if el else ""


def _format_date(raw: str) -> str:
    """YYYYMMDD 또는 YYYY/MM/DD → YYYY-MM-DD"""
    if not raw:
        return ""
    clean = raw.replace("/", "").replace(" ", "").replace("00:00:00", "").strip()
    if len(clean) >= 8:
        return f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
    return ""
