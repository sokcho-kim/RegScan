"""MOHW 건강보험정책 수집기 — 건보심 의결/급여 결정 모니터링

보건복지부 보도자료 게시판에서 건강보험/급여/건보심 관련 키워드를 필터링.
SSR 페이지라 httpx + bs4로 충분 (Playwright 불필요).

데이터 소스: https://www.mohw.go.kr/board.es (보도자료 bid=0027)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import BaseIngestor

logger = logging.getLogger(__name__)

MOHW_BASE = "https://www.mohw.go.kr"
BOARD_URL = f"{MOHW_BASE}/board.es"

# 보도자료 게시판 파라미터
BOARD_PARAMS = {
    "mid": "a10401010100",
    "bid": "0027",
    "act": "list",
}

# 건강보험/급여 관련 키워드 (OR 검색)
# 건강보험/급여 관련 키워드 — "급여" 단독은 범위가 넓어 제외
# (요양급여, 선별급여 등 복합 키워드로 커버)
INSURANCE_KEYWORDS = [
    "건강보험",
    "건보심",
    "약가",
    "비급여",
    "선별급여",
    "본인부담",
    "요양급여",
    "보험정책",
    "건강보험정책심의",
    "의약품 급여",
]

# 관련 담당부서 (우선순위 높음)
RELEVANT_DEPTS = {
    "보험급여과",
    "보험약제과",
    "보험정책과",
    "건강보험정책과",
    "보험평가과",
    "약무정책과",
}


class MOHWHealthInsuranceIngestor(BaseIngestor):
    """MOHW 건강보험정책 수집기 (보도자료 키워드 필터)

    건보심 의결, 급여 결정, 약가 정책 등 건강보험 관련
    보도자료를 자동 수집. 키워드 검색 + 담당부서 필터 조합.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
        max_pages: int = 5,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.max_pages = max_pages

    def source_type(self) -> str:
        return "MOHW_HEALTH_INSURANCE"

    async def fetch(self) -> list[dict[str, Any]]:
        """건강보험 관련 보도자료 수집"""
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for keyword in INSURANCE_KEYWORDS:
            records = await self._search_keyword(keyword, cutoff, seen_ids)
            all_records.extend(records)

        # 날짜 역순 정렬
        all_records.sort(key=lambda r: r.get("date", ""), reverse=True)

        logger.info(
            "[MOHW Insurance] %d건 수집 (최근 %d일, %d개 키워드)",
            len(all_records), self.days_back, len(INSURANCE_KEYWORDS),
        )
        return all_records

    async def _search_keyword(
        self,
        keyword: str,
        cutoff,
        seen_ids: set[str],
    ) -> list[dict[str, Any]]:
        """키워드별 게시판 검색"""
        records: list[dict[str, Any]] = []

        for page_num in range(1, self.max_pages + 1):
            params = {
                **BOARD_PARAMS,
                "keyField": "title",
                "keyWord": keyword,
                "nPage": str(page_num),
            }

            try:
                response = await self.client.get(
                    BOARD_URL, params=params, follow_redirects=True,
                )
                response.raise_for_status()
            except Exception as e:
                logger.error(
                    "[MOHW Insurance] 검색 실패 (%s, p%d): %s",
                    keyword, page_num, e,
                )
                break

            page_records, should_stop = self._parse_list(
                response.text, cutoff, seen_ids, keyword,
            )
            records.extend(page_records)

            if should_stop or not page_records:
                break

        return records

    def _parse_list(
        self,
        html: str,
        cutoff,
        seen_ids: set[str],
        keyword: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """게시판 목록 HTML 파싱"""
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict[str, Any]] = []
        should_stop = False

        for row in soup.select("tr"):
            tds = row.find_all("td")
            if not tds:
                continue

            # data-label 속성으로 필드 추출
            fields: dict[str, str] = {}
            for td in tds:
                label = td.get("data-label", "")
                if label:
                    fields[label] = td.get_text(strip=True)

            if "제목" not in fields or "등록일" not in fields:
                continue

            # 제목에서 "새글" 접두사 제거
            title = fields["제목"]
            title = re.sub(r"^새글", "", title).strip()

            # URL 추출
            link = row.select_one("a.txt_title")
            href = link.get("href", "") if link else ""
            url = f"{MOHW_BASE}{href}" if href.startswith("/") else href

            # list_no로 중복 방지
            list_no_match = re.search(r"list_no=(\d+)", href)
            list_no = list_no_match.group(1) if list_no_match else ""
            if list_no in seen_ids:
                continue
            if list_no:
                seen_ids.add(list_no)

            date_str = fields.get("등록일", "")
            department = fields.get("담당부서", "")
            views = 0
            views_text = fields.get("조회수", "0")
            views_match = re.search(r"(\d+)", views_text.replace(",", ""))
            if views_match:
                views = int(views_match.group(1))

            # 날짜 필터
            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            # 담당부서 관련성 태깅
            is_relevant_dept = department in RELEVANT_DEPTS

            records.append({
                "source": "MOHW",
                "source_type": "MOHW_HEALTH_INSURANCE",
                "title": title,
                "department": department,
                "date": date_str,
                "views": views,
                "url": url,
                "list_no": list_no,
                "matched_keyword": keyword,
                "is_relevant_dept": is_relevant_dept,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop
