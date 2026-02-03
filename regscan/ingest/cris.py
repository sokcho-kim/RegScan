"""CRIS (임상연구정보서비스) 데이터 수집

공공데이터포털 API: 질병관리청_임상연구 DB
- 엔드포인트: apis.data.go.kr/1352159/crisinfodataview
- 데이터: 11,547건 (2026-02 기준)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class CRISClient:
    """CRIS 공공데이터 API 클라이언트"""

    BASE_URL = "http://apis.data.go.kr/1352159/crisinfodataview"

    # 엔드포인트
    ENDPOINTS = {
        "list": "/list",      # 목록 조회
        "detail": "/detail",  # 상세 조회
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
            raise RuntimeError("CRISClient must be used as async context manager")
        return self._client

    async def search_trials(
        self,
        keyword: Optional[str] = None,
        page_no: int = 1,
        num_of_rows: int = 50,
    ) -> dict[str, Any]:
        """
        임상시험 검색

        Args:
            keyword: 검색 키워드 (연구제목, 시험약 등)
            page_no: 페이지 번호
            num_of_rows: 페이지당 건수 (최대 50)

        Returns:
            API 응답 dict
        """
        params = {
            "serviceKey": self.api_key,
            "resultType": "JSON",
            "pageNo": page_no,
            "numOfRows": min(num_of_rows, 50),  # 최대 50
        }

        if keyword:
            params["srchWord"] = keyword

        url = f"{self.BASE_URL}{self.ENDPOINTS['list']}"
        return await self._request(url, params)

    async def get_trial_detail(
        self,
        trial_id: str,
    ) -> dict[str, Any]:
        """
        임상시험 상세정보 조회

        Args:
            trial_id: CRIS 등록번호 (예: KCT0003340)

        Returns:
            API 응답 dict
        """
        params = {
            "serviceKey": self.api_key,
            "resultType": "JSON",
            "trial_id": trial_id,
        }

        url = f"{self.BASE_URL}{self.ENDPOINTS['detail']}"
        return await self._request(url, params)

    async def get_total_count(self) -> int:
        """전체 데이터 건수 조회"""
        response = await self.search_trials(num_of_rows=1)
        # CRIS API는 body 없이 바로 totalCount 반환
        return response.get("totalCount", 0) or response.get("body", {}).get("totalCount", 0)

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


class CRISTrialIngestor(BaseIngestor):
    """CRIS 임상시험 수집기"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_items: Optional[int] = None,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.max_items = max_items

    def source_type(self) -> str:
        return "CRIS_TRIAL"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        CRIS 임상시험 수집

        Returns:
            임상시험 목록
        """
        all_results = []

        async with CRISClient(api_key=self.api_key, timeout=self.timeout) as client:
            # 전체 건수 확인
            total_count = await client.get_total_count()
            logger.info(f"[CRIS] 전체 {total_count:,}건")

            if self.max_items:
                total_count = min(total_count, self.max_items)
                logger.info(f"[CRIS] max_items 제한: {total_count:,}건")

            # 페이지네이션으로 수집
            page_no = 1
            num_of_rows = 50  # CRIS API 최대값

            while len(all_results) < total_count:
                response = await client.search_trials(
                    page_no=page_no,
                    num_of_rows=num_of_rows,
                )

                # CRIS API는 body 없이 바로 items 반환
                items = response.get("items", []) or response.get("items", []) or response.get("body", {}).get("items", [])
                if not items:
                    break

                all_results.extend(items)
                logger.info(f"[CRIS] 페이지 {page_no}: {len(items)}건 수집 (누적: {len(all_results):,}건)")

                page_no += 1

                # Rate limit 방지
                await asyncio.sleep(0.2)

                # max_items 체크
                if self.max_items and len(all_results) >= self.max_items:
                    all_results = all_results[:self.max_items]
                    break

        logger.info(f"[CRIS] 총 {len(all_results):,}건 수집 완료")
        return all_results

    async def search_by_drug(
        self,
        drug_name: str,
    ) -> list[dict[str, Any]]:
        """
        약물명으로 임상시험 검색

        Args:
            drug_name: 약물명 (시험약)

        Returns:
            매칭된 임상시험 목록
        """
        all_results = []

        async with CRISClient(api_key=self.api_key, timeout=self.timeout) as client:
            page_no = 1

            while True:
                response = await client.search_trials(
                    keyword=drug_name,
                    page_no=page_no,
                    num_of_rows=50,
                )

                items = response.get("items", []) or response.get("body", {}).get("items", [])
                if not items:
                    break

                all_results.extend(items)
                page_no += 1

                await asyncio.sleep(0.2)

                # 최대 10페이지까지만
                if page_no > 10:
                    break

        return all_results


class CRISActiveTrialIngestor(BaseIngestor):
    """CRIS 진행 중 임상시험 수집기"""

    # 진행 중 상태 목록
    ACTIVE_STATUS = [
        "모집중",
        "모집예정",
        "Recruiting",
        "Not yet recruiting",
        "Enrolling by invitation",
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key

    def source_type(self) -> str:
        return "CRIS_ACTIVE_TRIAL"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        진행 중인 임상시험만 수집
        """
        # 전체 데이터 수집 후 필터링
        ingestor = CRISTrialIngestor(
            api_key=self.api_key,
            timeout=self.timeout,
        )

        all_items = await ingestor.fetch()

        # 진행 중 상태만 필터링
        active_trials = []
        for item in all_items:
            status = item.get("recruitment_status_kr", "") or item.get("recruitment_status", "")
            if any(s in status for s in self.ACTIVE_STATUS):
                active_trials.append(item)

        logger.info(f"[CRIS] 진행 중 임상시험 {len(active_trials)}건 필터링")
        return active_trials


class CRISDrugTrialIngestor(BaseIngestor):
    """CRIS 의약품 임상시험 수집기 (의약품 Phase I~IV만)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        phases: Optional[list[str]] = None,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.phases = phases or ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]

    def source_type(self) -> str:
        return "CRIS_DRUG_TRIAL"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        의약품 임상시험 수집
        """
        ingestor = CRISTrialIngestor(
            api_key=self.api_key,
            timeout=self.timeout,
        )

        all_items = await ingestor.fetch()

        # 의약품 임상시험 + Phase 필터링
        drug_trials = []
        for item in all_items:
            # 중재 종류 확인
            intervention_type = item.get("intervention_type_kr", "") or item.get("intervention_type", "")
            if "의약품" not in intervention_type and "Drug" not in intervention_type:
                continue

            # Phase 확인
            phase = item.get("phase_kr", "") or item.get("phase", "")
            if not any(p.lower() in phase.lower() for p in self.phases):
                continue

            drug_trials.append(item)

        logger.info(f"[CRIS] 의약품 임상시험 {len(drug_trials)}건 필터링")
        return drug_trials
