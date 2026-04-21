"""국회 의안정보 수집기 — 보건의료 법안 모니터링

열린국회정보 API (open.assembly.go.kr)
엔드포인트: /portal/openapi/nzmimeepazxkubdpn (국회의원 발의법률안)
인증: OPEN_ASSEMBLY_API_KEY + User-Agent 헤더 필수
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

API_URL = (
    "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn"
)

# 보건의료 관련 키워드 (법안명 필터)
HEALTHCARE_KEYWORDS = [
    "약사법",
    "국민건강보험법",
    "건강보험",
    "의약품",
    "의료법",
    "감염���",
    "의료기기",
    "첨단재생의료",
    "생명윤리",
    "마약류",
    "희귀질환",
    "암관리",
    "공공보건",
    "한의약",
    "보건의료",
    "의료급여",
]

# 현재 국회 대수
CURRENT_AGE = 22


class AssemblyBillIngestor(BaseIngestor):
    """국회 의안정보 수집기 (열린국회정보 API)

    보건의료 관련 법안 발의/심의/통과를 모니터링.
    키워드 필터링으로 약사법, 건강보험법 �� 관련 법안만 수집.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        days_back: int = 90,
        page_size: int = 100,
        max_pages: int = 10,
        age: int = CURRENT_AGE,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key or settings.OPEN_ASSEMBLY_API_KEY
        self.days_back = days_back
        self.page_size = page_size
        self.max_pages = max_pages
        self.age = age

    def source_type(self) -> str:
        return "ASSEMBLY_BILL"

    async def fetch(self) -> list[dict[str, Any]]:
        """보��의료 관련 법안 수집"""
        if not self.api_key:
            logger.warning("[Assembly] OPEN_ASSEMBLY_API_KEY 미설정, 스킵")
            return []

        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for keyword in HEALTHCARE_KEYWORDS:
            records = await self._search_bills(keyword, cutoff, seen_ids)
            all_records.extend(records)

        all_records.sort(key=lambda r: r.get("date", ""), reverse=True)

        logger.info(
            "[Assembly] 보건의료 법안 %d건 수집 (최근 %d일, %d대 국회)",
            len(all_records), self.days_back, self.age,
        )
        return all_records

    async def _search_bills(
        self,
        keyword: str,
        cutoff,
        seen_ids: set[str],
    ) -> list[dict[str, Any]]:
        """키워드별 법안 검색"""
        records: list[dict[str, Any]] = []

        for page_idx in range(1, self.max_pages + 1):
            items, should_stop = await self._fetch_page(
                keyword, page_idx, cutoff, seen_ids,
            )
            records.extend(items)

            if should_stop or not items:
                break

        return records

    async def _fetch_page(
        self,
        keyword: str,
        page_idx: int,
        cutoff,
        seen_ids: set[str],
    ) -> tuple[list[dict[str, Any]], bool]:
        """API 페이지 요청 + 파싱"""
        params = {
            "KEY": self.api_key,
            "Type": "json",
            "pIndex": page_idx,
            "pSize": self.page_size,
            "AGE": self.age,
            "BILL_NAME": keyword,
        }

        try:
            response = await self.client.get(
                API_URL,
                params=params,
                headers={"User-Agent": "RegScan/1.0"},
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(
                "[Assembly] API 요청 실패 (%s, p%d): %s",
                keyword, page_idx, e,
            )
            return [], True

        # 에러 응답 체크
        if "RESULT" in data:
            code = data["RESULT"].get("CODE", "")
            if code != "INFO-000":
                msg = data["RESULT"].get("MESSAGE", "")
                logger.warning("[Assembly] API 에러: %s - %s", code, msg)
                return [], True

        # 정상 응답 파싱
        api_key = "nzmimeepazxkubdpn"
        entries = data.get(api_key, [])

        # head/row 구조
        rows = []
        for entry in entries:
            if "row" in entry:
                rows = entry["row"]
                break

        if not rows:
            return [], True

        records: list[dict[str, Any]] = []
        should_stop = False

        for row in rows:
            bill_id = row.get("BILL_ID", "")
            if bill_id in seen_ids:
                continue

            propose_dt = row.get("PROPOSE_DT", "")

            # 날짜 필터
            if propose_dt:
                try:
                    dt = datetime.strptime(propose_dt, "%Y-%m-%d").date()
                    if dt < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            seen_ids.add(bill_id)

            records.append({
                "source": "ASSEMBLY",
                "source_type": "ASSEMBLY_BILL",
                "bill_id": bill_id,
                "bill_no": row.get("BILL_NO", ""),
                "title": row.get("BILL_NAME", ""),
                "proposer": row.get("PROPOSER", ""),
                "rst_proposer": row.get("RST_PROPOSER", ""),
                "committee": row.get("COMMITTEE") or "",
                "propose_date": propose_dt,
                "proc_result": row.get("PROC_RESULT") or "",
                "proc_date": row.get("PROC_DT") or "",
                "date": propose_dt,
                "url": row.get("DETAIL_LINK", ""),
                "matched_keyword": keyword,
                "age": str(row.get("AGE", "")),
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop
