"""KHIDI 제약글로벌정보센터 수집기 (약가·보험 / 법령·고시)

XML Open API 기반 — HTML 파싱 불필요.
https://www.khidi.or.kr/kps/openAPI/requestxml?rowCnt=100&menuId=MENU#####

공공저작물 자유이용 (출처 표기 조건).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree

from .base import BaseIngestor

logger = logging.getLogger(__name__)

KHIDI_BASE = "https://www.khidi.or.kr"
XML_API = f"{KHIDI_BASE}/kps/openAPI/requestxml"

# 제약산업정보포털 게시판 (XML API 공통 구조)
# docs/research/khidi-portal-exploration.md 참조
GLOBAL_BOARDS = {
    # ── 의약품 인허가정보 ──
    "regulation":      {"menuId": "MENU01872", "label": "법령 및 고시"},
    "approval_patent": {"menuId": "MENU02599", "label": "허가 및 특허"},
    # ── 의약품 시장정보 ──
    "market_status":   {"menuId": "MENU01866", "label": "의약품 시장 현황"},
    # ── 임상 ──
    "clinical_trial":  {"menuId": "MENU02139", "label": "임상 및 비임상"},
    # ── 인프라 ──
    "infra":           {"menuId": "MENU01868", "label": "인프라 정보"},
    # ── 자료실 ──
    "report_external": {"menuId": "MENU01846", "label": "보고서 (유관기관)"},
    # ── 전문가 ──
    "expert_insight":  {"menuId": "MENU01819", "label": "전문가 Insight"},
}


class KHIDIGlobalInfoIngestor(BaseIngestor):
    """KHIDI 제약글로벌정보센터 — XML API 기반 수집기

    약가·보험(MENU01869) + 법령·고시(MENU01872) 수집.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 30,
        row_count: int = 50,
        boards: list[str] | None = None,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.row_count = row_count
        self.boards = boards or list(GLOBAL_BOARDS.keys())

    def source_type(self) -> str:
        return "KHIDI_GLOBAL_INFO"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []

        for board_key in self.boards:
            board = GLOBAL_BOARDS.get(board_key)
            if not board:
                continue
            records = await self._fetch_board(
                board["menuId"], board["label"], cutoff,
            )
            all_records.extend(records)

        logger.info(
            "[KHIDI Global] %d건 수집 (최근 %d일, %s)",
            len(all_records), self.days_back,
            "+".join(self.boards),
        )
        return all_records

    async def _fetch_board(
        self,
        menu_id: str,
        label: str,
        cutoff,
    ) -> list[dict[str, Any]]:
        """XML API로 게시판 수집"""
        try:
            response = await self._request_with_retry(
                "GET",
                XML_API,
                params={
                    "menuId": menu_id,
                    "rowCnt": self.row_count,
                },
                max_retries=2,
            )
        except Exception as e:
            logger.warning("[KHIDI Global] %s XML 요청 실패: %s", label, e)
            return []

        return self._parse_xml(response.text, menu_id, label, cutoff)

    def _parse_xml(
        self,
        xml_text: str,
        menu_id: str,
        label: str,
        cutoff,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.warning("[KHIDI Global] %s XML 파싱 실패: %s", label, e)
            return []

        for row in root.findall(".//row"):
            title = (row.findtext("title") or "").strip()
            if not title:
                continue

            date_raw = (row.findtext("date") or "").strip()
            date_str = self._normalize_date(date_raw)

            # 날짜 필터
            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        continue
                except ValueError:
                    pass

            link_id = (row.findtext("linkid") or "").strip()
            content_raw = (row.findtext("content") or "").strip()
            content = self._clean_html(content_raw)

            # 상세 URL 구성
            url = (
                f"{KHIDI_BASE}/board/view?menuId={menu_id}&linkId={link_id}"
                if link_id else ""
            )

            records.append({
                "source": "KHIDI",
                "source_type": "KHIDI_GLOBAL_INFO",
                "board": label,
                "menu_id": menu_id,
                "title": title,
                "url": url,
                "date": date_str,
                "content": content,
                "link_id": link_id,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records

    async def fetch_detail(self, item: dict[str, Any]) -> dict[str, Any]:
        """상세 페이지에서 본문 보강 (XML content가 짧을 때)."""
        url = item.get("url", "")
        if not url or len(item.get("content", "")) > 500:
            return item

        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            match = re.search(
                r'<div[^>]*class="viewContent"[^>]*>(.*?)</div>',
                resp.text, re.DOTALL,
            )
            if match:
                text = re.sub(r'<br\s*/?>', '\n', match.group(1))
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'\n{3,}', '\n\n', text).strip()
                if text and len(text) > len(item.get("content", "")):
                    item["content"] = text
        except Exception as e:
            logger.debug("[KHIDI Global] 상세 fetch 실패 (%s): %s", url, e)

        return item

    @staticmethod
    def _normalize_date(raw: str) -> str:
        """다양한 날짜 형식 → YYYY-MM-DD"""
        for fmt, pattern in [
            ("%Y-%m-%d", r"(\d{4}-\d{2}-\d{2})"),
            ("%Y.%m.%d", r"(\d{4}\.\d{2}\.\d{2})"),
            ("%Y%m%d", r"(\d{8})"),
        ]:
            m = re.search(pattern, raw)
            if m:
                try:
                    return datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return ""

    @staticmethod
    def _clean_html(text: str) -> str:
        """HTML 엔티티 디코딩 + 태그 제거"""
        import html
        text = html.unescape(text)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
