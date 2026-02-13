"""FDA Safety Alert + Enforcement 데이터 수집

openFDA endpoints:
  - drug/label.json    — 라벨링 (Boxed Warning)
  - drug/enforcement.json — 리콜/시장조치
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class FDASafetyClient:
    """FDA Safety (Label + Enforcement) API 클라이언트"""

    BASE_URL = "https://api.fda.gov"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.FDA_API_KEY
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
            raise RuntimeError("FDASafetyClient must be used as async context manager")
        return self._client

    async def search_label_changes(
        self,
        days_back: int = 30,
        has_boxed_warning: bool = True,
        limit: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """라벨 변경 검색 (Boxed Warning 포함)

        Args:
            days_back: 최근 N일
            has_boxed_warning: Boxed Warning 필터 적용 여부
            limit: 최대 결과 수
            skip: 건너뛸 결과 수
        """
        to_date = datetime.now().strftime("%Y%m%d")
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        search_parts = [
            f"effective_time:[{from_date}+TO+{to_date}]",
        ]
        if has_boxed_warning:
            search_parts.append("_exists_:boxed_warning")

        search_query = "+AND+".join(search_parts)

        params = {
            "search": search_query,
            "limit": limit,
            "skip": skip,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/label.json?{urlencode(params, safe='[]+ ')}"
        return await self._request(url)

    async def search_enforcement(
        self,
        days_back: int = 30,
        limit: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """약물 리콜/시장조치 검색

        Args:
            days_back: 최근 N일
            limit: 최대 결과 수
            skip: 건너뛸 결과 수
        """
        to_date = datetime.now().strftime("%Y%m%d")
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        search_query = f"report_date:[{from_date}+TO+{to_date}]"

        params = {
            "search": search_query,
            "limit": limit,
            "skip": skip,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/enforcement.json?{urlencode(params, safe='[]+ ')}"
        return await self._request(url)

    async def _request(
        self,
        url: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """API 요청 (재시도 + 404→빈 결과)"""
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.get(url)

                if response.status_code == 429:
                    wait_time = retry_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 404:
                    return {"meta": {"results": {"total": 0}}, "results": []}
                await asyncio.sleep(retry_delay)

            except httpx.RequestError as e:
                last_error = e
                await asyncio.sleep(retry_delay)

        raise last_error or Exception("Unknown error")
