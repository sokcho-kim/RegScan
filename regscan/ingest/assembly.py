"""국회 의안정보 수집기 — 보건의료 법안 모니터링

열린국회정보 API (open.assembly.go.kr)
엔드포인트: /portal/openapi/nzmimeepazxkubdpn (국회의원 발의법률안)
인증: OPEN_ASSEMBLY_API_KEY + User-Agent 헤더 필수

+ LIKMS 상세페이지 스크래핑으로 제안이유/주요내용/조문 수집
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import asyncio

import httpx
from bs4 import BeautifulSoup

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

        # LIKMS 상세페이지에서 제안이유/주요내용/조문 수집
        enriched = 0
        for record in all_records:
            bill_id = record.get("bill_id", "")
            if not bill_id:
                continue
            detail = await self._fetch_bill_detail(bill_id)
            if detail:
                record.update(detail)
                enriched += 1
            await asyncio.sleep(0.5)

        # 동일 법명 복수 법안 관계 메타데이터 추가
        self._annotate_related_bills(all_records)

        logger.info(
            "[Assembly] 보건의료 법안 %d건 수집 (상세 %d건, 최근 %d일, %d대 국회)",
            len(all_records), enriched, self.days_back, self.age,
        )
        return all_records

    @staticmethod
    def _annotate_related_bills(records: list[dict]) -> None:
        """동일 법명 법안이 여러 개일 때 관계 정보를 주입.

        위원장 대안이 가결된 상태에서 개별 발의안이 계류 중이면,
        개별 발의안에 '이 법명의 위원장 대안이 이미 가결됨' 맥락을 붙인다.
        """
        # 법안명 정규화: "일부개정법률안" 등 접미사 제거
        def _normalize(title: str) -> str:
            return re.sub(
                r"\s*(일부개정법률안|전부개정법률안|제정법률안|폐지법률안).*$",
                "", title,
            ).strip()

        # 법명별 그룹핑
        by_law: dict[str, list[dict]] = {}
        for r in records:
            key = _normalize(r.get("title", ""))
            if key:
                by_law.setdefault(key, []).append(r)

        for law_name, bills in by_law.items():
            if len(bills) < 2:
                continue

            # 가결/공포/철회/대안반영 등 처리 완료된 법안 찾기
            passed = [
                b for b in bills
                if b.get("proc_result", "") in (
                    "원안가결", "수정가결", "대안반영폐기", "공포", "철회",
                )
                or "가결" in (b.get("proc_result") or "")
            ]
            # 위원장 대안 찾기
            chair_bills = [
                b for b in bills
                if "위원장" in (b.get("rst_proposer") or b.get("proposer", ""))
            ]

            context_parts = []
            if passed:
                latest = max(passed, key=lambda b: b.get("proc_date", "") or b.get("date", ""))
                context_parts.append(
                    f"동일 법명 '{law_name}'의 다른 법안이 "
                    f"{latest.get('proc_date') or latest.get('date', '')}에 "
                    f"{latest.get('proc_result', '')} 처리됨 "
                    f"(발의: {latest.get('rst_proposer', latest.get('proposer', ''))})"
                )
            if chair_bills:
                for cb in chair_bills:
                    if cb.get("proc_result"):
                        context_parts.append(
                            f"위원장 대안 ({cb.get('date', '')}) → {cb.get('proc_result', '')}"
                        )

            if context_parts:
                related_context = "; ".join(context_parts)
                for b in bills:
                    b["related_bills_context"] = related_context

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

    async def _fetch_bill_detail(self, bill_id: str) -> dict[str, str] | None:
        """lawmake.kr에서 제안이유/주요내용/조문 스크래핑"""
        url = f"https://www.lawmake.kr/bills/{bill_id}"
        try:
            resp = await self.client.get(
                url,
                headers={"User-Agent": "RegScan/1.0"},
                follow_redirects=True,
                timeout=15.0,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.debug("[Assembly] lawmake.kr 실패 (%s): %s", bill_id, e)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        detail: dict[str, str] = {}

        # 제안이유 추출
        for tag in soup.find_all(["h2", "h3", "h4", "strong", "dt"]):
            if "제안이유" in tag.get_text():
                sibling = tag.find_next(["p", "dd", "div"])
                if sibling:
                    detail["proposal_reason"] = sibling.get_text(strip=True)[:2000]
                break

        # 주요내용 추출
        for tag in soup.find_all(["h2", "h3", "h4", "strong", "dt"]):
            if "주요내용" in tag.get_text():
                sibling = tag.find_next(["p", "dd", "div", "ol", "ul"])
                if sibling:
                    detail["main_content"] = sibling.get_text(strip=True)[:3000]
                break

        # 조문 번호 추출 (페이지 전체에서)
        page_text = soup.get_text()
        articles = re.findall(r"제\d+조(?:의\d+)?", page_text)
        unique_articles = list(dict.fromkeys(articles))
        if unique_articles:
            detail["statute_articles"] = ", ".join(unique_articles)

        if detail:
            logger.debug(
                "[Assembly] 상세 수집: %s (조문 %d개, 제안이유 %s)",
                bill_id[:20],
                len(unique_articles),
                "있음" if detail.get("proposal_reason") else "없음",
            )
        return detail if detail else None
