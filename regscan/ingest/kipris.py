"""KIPRIS (특허정보원) 수집기 — 의약품 특허 현황 모니터링

plus.kipris.or.kr OpenAPI — 의약품 관련 특허 검색.
Orange Book은 미국 특허만 커버, 국내 제네릭 진입 예측엔 국내 특허 필요.
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

KIPRIS_API_BASE = "http://plus.kipris.or.kr/openapi/rest"

# 의약품 특허 검색 키워드
PHARMA_PATENT_KEYWORDS = [
    "의약품",
    "약학 조성물",
    "항체",
    "제제",
    "치료용 조성물",
]

# IPC(국제특허분류) 의약 관련 코드
# A61K: 의약용 제제  A61P: 치료 활성  C07K: 펩타이드
PHARMA_IPC_CODES = ["A61K", "A61P", "C07K"]


class KIPRISPatentIngestor(BaseIngestor):
    """KIPRIS 의약품 특허 수집기

    의약품 관련 키워드 + IPC 코드로 최근 공개/등록 특허 검색.
    API: plus.kipris.or.kr/openapi/rest/patUtiModInfoSearchSevice
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        days_back: int = 30,
        num_of_rows: int = 50,
        max_pages: int = 3,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key or getattr(settings, "KIPRIS_API_KEY", None)
        self.days_back = days_back
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
            "[KIPRIS] 의약품 특허 %d건 수집 (최근 %d일)",
            len(all_records), self.days_back,
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
                "searchWord": keyword,
                "numOfRows": self.num_of_rows,
                "pageNo": page_no,
            }

            try:
                response = await self.client.get(
                    f"{KIPRIS_API_BASE}/patUtiModInfoSearchSevice"
                    "/freeSearchInfo",
                    params=params,
                    follow_redirects=True,
                )
                response.raise_for_status()
            except Exception as e:
                logger.error(
                    "[KIPRIS] API 요청 실패 (%s, p%d): %s",
                    keyword, page_no, e,
                )
                break

            items = self._parse_xml_response(response.text, seen_ids, keyword)
            records.extend(items)

            if not items:
                break

        return records

    def _parse_xml_response(
        self,
        xml_text: str,
        seen_ids: set[str],
        keyword: str,
    ) -> list[dict[str, Any]]:
        """XML 응답 파싱"""
        soup = BeautifulSoup(xml_text, "html.parser")
        records: list[dict[str, Any]] = []
        cutoff = (self._now() - timedelta(days=self.days_back)).strftime(
            "%Y%m%d"
        )
        now_str = self._now().strftime("%Y-%m-%d")

        for item in soup.select("item"):
            app_no = _get_text(item, "applicationnumber")
            if not app_no or app_no in seen_ids:
                continue
            seen_ids.add(app_no)

            title = _get_text(item, "inventionname") or _get_text(
                item, "inventionnameenglish"
            )
            applicant = _get_text(item, "applicantname")
            app_date = _get_text(item, "applicationdate")
            pub_date = _get_text(item, "publicationdate")
            reg_date = _get_text(item, "registrationdate")
            ipc_code = _get_text(item, "ipcnumber")

            # 날짜 결정 (등록 > 공개 > 출원)
            raw_date = reg_date or pub_date or app_date or ""
            if raw_date and raw_date < cutoff:
                continue

            date_str = ""
            if raw_date and len(raw_date) >= 8:
                date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

            # IPC 관련성 체크
            is_pharma_ipc = any(
                code in (ipc_code or "") for code in PHARMA_IPC_CODES
            )

            records.append({
                "source": "KIPRIS",
                "source_type": "KIPRIS_PATENT",
                "title": title,
                "application_number": app_no,
                "applicant": applicant,
                "application_date": _format_date(app_date),
                "publication_date": _format_date(pub_date),
                "registration_date": _format_date(reg_date),
                "ipc_code": ipc_code or "",
                "is_pharma_ipc": is_pharma_ipc,
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
    """YYYYMMDD → YYYY-MM-DD"""
    if raw and len(raw) >= 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""
