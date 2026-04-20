"""MFDS (식약처) 안전성 서한 / 회수·판매중지 수집

공공데이터포털 API:
- 안전성 서한: apis.data.go.kr/1471000/MdcinGrpInfoService/getMdcinSftyLeterInfo
- 회수/폐기: apis.data.go.kr/1471000/MdcinGrpInfoService/getMdcnRtrvlDsuse
- 판매중지/회수: apis.data.go.kr/1471000/DrugRcllInfoService/getDrugRcllList

기존 MFDSClient와 동일 키(DATA_GO_KR_API_KEY) 사용.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class MFDSSafetyClient:
    """MFDS 안전성 정보 API 클라이언트"""

    ENDPOINTS = {
        "safety_letter": (
            "http://apis.data.go.kr/1471000/MdcinGrpInfoService"
            "/getMdcinSftyLeterInfo"
        ),
        "recall": (
            "http://apis.data.go.kr/1471000/DrugRcllInfoService"
            "/getDrugRcllList"
        ),
    }

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
            raise RuntimeError("MFDSSafetyClient must be used as async context manager")
        return self._client

    async def fetch_safety_letters(
        self,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> dict[str, Any]:
        """안전성 서한 조회"""
        params = {
            "serviceKey": self.api_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
        }
        return await self._request(self.ENDPOINTS["safety_letter"], params)

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
        return await self._request(self.ENDPOINTS["recall"], params)

    async def _request(
        self,
        url: str,
        params: dict,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """API 요청 (MFDSClient 패턴 동일 — 이중 인코딩 방지)"""
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
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                if "header" in data:
                    result_code = data["header"].get("resultCode", "00")
                    if result_code != "00":
                        error_msg = data["header"].get("resultMsg", "Unknown error")
                        raise Exception(f"API Error ({result_code}): {error_msg}")

                return data

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"HTTP error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(retry_delay)

            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Request error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(retry_delay)

        raise last_error or Exception("MFDS Safety API request failed")


class MFDSSafetyLetterIngestor(BaseIngestor):
    """MFDS 의약품 안전성 서한 수집기"""

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
        return "MFDS_SAFETY_LETTER"

    async def fetch(self) -> list[dict[str, Any]]:
        """안전성 서한 수집 (최근 N일)"""
        all_results = []
        cutoff = datetime.now() - timedelta(days=self.days_back)
        cutoff_str = cutoff.strftime("%Y%m%d")

        async with MFDSSafetyClient(
            api_key=self.api_key, timeout=self.timeout,
        ) as client:
            page_no = 1

            while True:
                response = await client.fetch_safety_letters(
                    page_no=page_no, num_of_rows=100,
                )

                body = response.get("body", {})
                items = body.get("items", [])
                if not items:
                    break

                # 날짜 필터링
                for item in items:
                    letter_date = item.get("SAFETY_LETTER_DATE", "") or item.get(
                        "CREATE_DATE", ""
                    )
                    # 최근 N일 이내만
                    if letter_date and letter_date.replace("-", "") >= cutoff_str:
                        item["_source"] = "mfds_safety_letter"
                        item["_fetched_at"] = datetime.now().strftime("%Y-%m-%d")
                        all_results.append(item)

                total = body.get("totalCount", 0)
                if page_no * 100 >= total:
                    break

                page_no += 1
                await asyncio.sleep(0.1)

        logger.info(
            f"[MFDS Safety] 안전성 서한 {len(all_results)}건 수집 "
            f"(최근 {self.days_back}일)"
        )
        return all_results


class MFDSRecallIngestor(BaseIngestor):
    """MFDS 의약품 회수/판매중지 수집기"""

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
                    recall_date = item.get("RECALL_COMMAND_DATE", "") or item.get(
                        "CREATE_DATE", ""
                    )
                    if recall_date and recall_date.replace("-", "") >= cutoff_str:
                        item["_source"] = "mfds_recall"
                        item["_fetched_at"] = datetime.now().strftime("%Y-%m-%d")
                        all_results.append(item)

                total = body.get("totalCount", 0)
                if page_no * 100 >= total:
                    break

                page_no += 1
                await asyncio.sleep(0.1)

        logger.info(
            f"[MFDS Safety] 회수/판매중지 {len(all_results)}건 수집 "
            f"(최근 {self.days_back}일)"
        )
        return all_results
