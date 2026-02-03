"""MFDS (식약처) 의약품 허가 현황 수집

공공데이터포털 API: 식품의약품안전처_의약품 제품 허가정보
- 엔드포인트: apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07
- 데이터: 284,477건 (2026-02 기준)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class MFDSClient:
    """MFDS 공공데이터 API 클라이언트"""

    BASE_URL = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"

    # 엔드포인트
    ENDPOINTS = {
        "permit_info": "/getDrugPrdtPrmsnInq07",      # 허가정보 조회
        "permit_detail": "/getDrugPrdtPrmsnDtlInq04", # 허가상세 조회
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
            raise RuntimeError("MFDSClient must be used as async context manager")
        return self._client

    async def search_permits(
        self,
        item_name: Optional[str] = None,
        entp_name: Optional[str] = None,
        item_seq: Optional[str] = None,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> dict[str, Any]:
        """
        의약품 허가정보 검색

        Args:
            item_name: 품목명 검색
            entp_name: 업체명 검색
            item_seq: 품목일련번호
            page_no: 페이지 번호
            num_of_rows: 페이지당 건수 (최대 100)

        Returns:
            API 응답 dict
        """
        params = {
            "serviceKey": self.api_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
        }

        if item_name:
            params["item_name"] = item_name
        if entp_name:
            params["entp_name"] = entp_name
        if item_seq:
            params["item_seq"] = item_seq

        url = f"{self.BASE_URL}{self.ENDPOINTS['permit_info']}"
        return await self._request(url, params)

    async def get_permit_detail(
        self,
        item_seq: str,
    ) -> dict[str, Any]:
        """
        의약품 허가 상세정보 조회

        Args:
            item_seq: 품목일련번호

        Returns:
            API 응답 dict
        """
        params = {
            "serviceKey": self.api_key,
            "item_seq": item_seq,
            "type": "json",
        }

        url = f"{self.BASE_URL}{self.ENDPOINTS['permit_detail']}"
        return await self._request(url, params)

    async def get_total_count(self) -> int:
        """전체 데이터 건수 조회"""
        response = await self.search_permits(num_of_rows=1)
        return response.get("body", {}).get("totalCount", 0)

    async def _request(
        self,
        url: str,
        params: dict,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        API 요청 (재시도 로직 포함)

        Note: 공공데이터포털 API 키는 이미 URL 인코딩되어 있으므로
              직접 URL에 추가해야 함 (httpx params 사용시 이중 인코딩 발생)
        """
        last_error = None

        # 서비스 키를 별도로 추출 (이중 인코딩 방지)
        params = params.copy()  # 원본 유지
        service_key = params.pop("serviceKey", "")

        for attempt in range(max_retries):
            try:
                # 서비스 키는 URL에 직접 추가
                from urllib.parse import urlencode
                query_string = urlencode(params)
                full_url = f"{url}?serviceKey={service_key}&{query_string}"

                response = await self.client.get(full_url)

                # Rate limit 처리
                if response.status_code == 429:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                # 공공데이터포털 에러 응답 처리
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

        raise last_error or Exception("Unknown error")


class MFDSPermitIngestor(BaseIngestor):
    """MFDS 의약품 허가정보 수집기"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_items: Optional[int] = None,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.max_items = max_items  # None이면 전체 수집

    def source_type(self) -> str:
        return "MFDS_PERMIT"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        MFDS 허가정보 수집

        Returns:
            허가정보 목록
        """
        all_results = []

        async with MFDSClient(api_key=self.api_key, timeout=self.timeout) as client:
            # 전체 건수 확인
            total_count = await client.get_total_count()
            logger.info(f"[MFDS] 전체 {total_count:,}건")

            if self.max_items:
                total_count = min(total_count, self.max_items)
                logger.info(f"[MFDS] max_items 제한: {total_count:,}건")

            # 페이지네이션으로 수집
            page_no = 1
            num_of_rows = 100

            while len(all_results) < total_count:
                response = await client.search_permits(
                    page_no=page_no,
                    num_of_rows=num_of_rows,
                )

                items = response.get("body", {}).get("items", [])
                if not items:
                    break

                all_results.extend(items)
                logger.info(f"[MFDS] 페이지 {page_no}: {len(items)}건 수집 (누적: {len(all_results):,}건)")

                page_no += 1

                # Rate limit 방지
                await asyncio.sleep(0.1)

                # max_items 체크
                if self.max_items and len(all_results) >= self.max_items:
                    all_results = all_results[:self.max_items]
                    break

        logger.info(f"[MFDS] 총 {len(all_results):,}건 수집 완료")
        return all_results

    async def fetch_by_ingredient(
        self,
        ingredient_name: str,
    ) -> list[dict[str, Any]]:
        """
        성분명으로 허가 품목 검색

        Args:
            ingredient_name: 성분명 (주성분)

        Returns:
            매칭된 품목 목록
        """
        all_results = []

        async with MFDSClient(api_key=self.api_key, timeout=self.timeout) as client:
            page_no = 1

            while True:
                response = await client.search_permits(
                    item_name=ingredient_name,
                    page_no=page_no,
                    num_of_rows=100,
                )

                items = response.get("body", {}).get("items", [])
                if not items:
                    break

                all_results.extend(items)
                page_no += 1

                await asyncio.sleep(0.1)

        return all_results


class MFDSNewDrugIngestor(BaseIngestor):
    """MFDS 신약 수집기 (허가구분이 신약인 품목만)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        years_back: int = 5,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.years_back = years_back

    def source_type(self) -> str:
        return "MFDS_NEW_DRUG"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        최근 N년간 신약 수집
        """
        # 전체 데이터 수집 후 신약만 필터링
        # (API에서 허가구분 필터 미지원)
        ingestor = MFDSPermitIngestor(
            api_key=self.api_key,
            timeout=self.timeout,
        )

        all_items = await ingestor.fetch()

        # 신약 필터링 (허가구분에 "신약" 포함)
        cutoff_year = datetime.now().year - self.years_back
        new_drugs = []

        for item in all_items:
            # 허가일 확인
            permit_date_str = item.get("ITEM_PERMIT_DATE", "")
            if permit_date_str:
                try:
                    permit_year = int(permit_date_str[:4])
                    if permit_year < cutoff_year:
                        continue
                except (ValueError, IndexError):
                    pass

            # 신약 여부 확인 (다양한 필드에서)
            item_str = str(item).lower()
            if "신약" in item_str or "new drug" in item_str.lower():
                new_drugs.append(item)

        logger.info(f"[MFDS] 신약 {len(new_drugs)}건 필터링 (최근 {self.years_back}년)")
        return new_drugs
