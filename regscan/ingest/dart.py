"""DART (전자공시시스템) 수집기 — 제약사 공시/라이선스 딜 모니터링

opendart.fss.or.kr API — 상장 제약사 공시 중 라이선스/파이프라인 관련 필터링.
라이선스 딜은 규제 승인보다 6~12개월 빠른 선행지표.
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

DART_API_BASE = "https://opendart.fss.or.kr/api"

# 제약/바이오 관련 키워드 (공시 제목 필터)
PHARMA_KEYWORDS = [
    "의약품",
    "신약",
    "라이선스",
    "기술이전",
    "기술수출",
    "임상시험",
    "임상",
    "바이오",
    "품목허가",
    "약가",
    "특허",
    "제네릭",
    "바이오시밀러",
    "위탁생산",
    "CMO",
    "CDMO",
]


class DARTDisclosureIngestor(BaseIngestor):
    """DART 전자공시 수집기

    상장법인(corp_cls=Y) 공시에서 제약/바이오 관련 키워드 필터링.
    API: opendart.fss.or.kr/api/list.json
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        days_back: int = 30,
        page_count: int = 100,
        max_pages: int = 5,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key or getattr(settings, "DART_API_KEY", None)
        self.days_back = days_back
        self.page_count = page_count
        self.max_pages = max_pages

    def source_type(self) -> str:
        return "DART_DISCLOSURE"

    async def fetch(self) -> list[dict[str, Any]]:
        """제약/바이오 관련 공시 수집"""
        if not self.api_key:
            logger.warning("[DART] DART_API_KEY 미설정, 스킵")
            return []

        end_date = datetime.now()
        bgn_date = end_date - timedelta(days=self.days_back)
        all_records: list[dict[str, Any]] = []

        for page_no in range(1, self.max_pages + 1):
            params = {
                "crtfc_key": self.api_key,
                "bgn_de": bgn_date.strftime("%Y%m%d"),
                "end_de": end_date.strftime("%Y%m%d"),
                "corp_cls": "Y",  # 상장법인
                "page_no": page_no,
                "page_count": self.page_count,
            }

            try:
                response = await self.client.get(
                    f"{DART_API_BASE}/list.json",
                    params=params,
                    follow_redirects=True,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error("[DART] API 요청 실패 (p%d): %s", page_no, e)
                break

            status = data.get("status", "")
            if status != "000":
                msg = data.get("message", "")
                if status == "013":  # 조회된 데이터가 없음
                    break
                logger.warning("[DART] API 에러: %s - %s", status, msg)
                break

            items = data.get("list", [])
            if not items:
                break

            for item in items:
                title = item.get("report_nm", "")
                # 제약/바이오 키워드 필터
                title_lower = title.lower()
                corp_name = item.get("corp_name", "")
                combined = f"{title} {corp_name}".lower()

                matched_kw = ""
                for kw in PHARMA_KEYWORDS:
                    if kw.lower() in combined:
                        matched_kw = kw
                        break

                if not matched_kw:
                    continue

                rcept_dt = item.get("rcept_dt", "")
                date_str = ""
                if rcept_dt and len(rcept_dt) == 8:
                    date_str = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"

                all_records.append({
                    "source": "DART",
                    "source_type": "DART_DISCLOSURE",
                    "title": title,
                    "corp_name": corp_name,
                    "corp_code": item.get("corp_code", ""),
                    "stock_code": item.get("stock_code", ""),
                    "report_no": item.get("rcept_no", ""),
                    "date": date_str,
                    "flr_nm": item.get("flr_nm", ""),  # 공시 제출인
                    "matched_keyword": matched_kw,
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                    "_fetched_at": self._now().strftime("%Y-%m-%d"),
                })

            total_page = data.get("total_page", 1)
            if page_no >= total_page:
                break

        logger.info(
            "[DART] 제약/바이오 공시 %d건 수집 (최근 %d일)",
            len(all_records), self.days_back,
        )
        return all_records
