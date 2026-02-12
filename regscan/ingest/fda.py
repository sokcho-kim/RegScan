"""FDA 데이터 수집"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from regscan.config import settings
from .base import BaseIngestor


class FDAClient:
    """FDA API 클라이언트"""

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
            raise RuntimeError("FDAClient must be used as async context manager")
        return self._client

    async def search_drug_approvals(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        days_back: int = 7,
        limit: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """
        Drug approvals 검색

        Args:
            from_date: 시작일 (YYYYMMDD), 없으면 days_back 사용
            to_date: 종료일 (YYYYMMDD), 없으면 오늘
            days_back: from_date 없을 때 오늘로부터 N일 전
            limit: 최대 결과 수
            skip: 건너뛸 결과 수 (페이지네이션)

        Returns:
            API 응답 dict
        """
        # 날짜 계산
        if not to_date:
            to_date = datetime.now().strftime("%Y%m%d")
        if not from_date:
            from_dt = datetime.now() - timedelta(days=days_back)
            from_date = from_dt.strftime("%Y%m%d")

        # 쿼리 구성
        search_query = f"submissions.submission_status_date:[{from_date}+TO+{to_date}]"

        params = {
            "search": search_query,
            "limit": limit,
            "skip": skip,
        }

        if self.api_key:
            params["api_key"] = self.api_key

        # urlencode가 +를 %2B로 바꾸면 FDA API가 500 에러 반환
        url = f"{self.BASE_URL}/drug/drugsfda.json?{urlencode(params, safe='[]+ ')}"

        return await self._request(url)

    async def get_drug_by_application_number(self, app_number: str) -> dict[str, Any]:
        """
        Application number로 약물 조회

        Args:
            app_number: NDA/BLA 번호 (예: "NDA215256")

        Returns:
            API 응답 dict
        """
        params = {
            "search": f"application_number:{app_number}",
            "limit": 1,
        }

        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/drugsfda.json?{urlencode(params)}"

        return await self._request(url)

    async def search_by_sponsor(
        self,
        sponsor_name: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        제약사로 검색

        Args:
            sponsor_name: 제약사명 (예: "pfizer")
            limit: 최대 결과 수
        """
        params = {
            "search": f'sponsor_name:"{sponsor_name}"',
            "limit": limit,
        }

        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/drugsfda.json?{urlencode(params)}"

        return await self._request(url)

    async def search_by_pharm_class(
        self,
        term: str,
        limit: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """FDA pharm_class_epc 기반 검색 (치료영역 스트림용)

        Args:
            term: pharmacologic class 검색어 (e.g. "Antineoplastic")
            limit: 최대 결과 수
            skip: 건너뛸 결과 수
        """
        params = {
            "search": f'openfda.pharm_class_epc:"{term}"',
            "limit": limit,
            "skip": skip,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/drugsfda.json?{urlencode(params)}"
        return await self._request(url)

    async def search_by_submission_class(
        self,
        code: str,
        limit: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """FDA submission_class_code 기반 검색 (혁신지표 스트림용)

        Args:
            code: submission class code (e.g. "1" for NME Type 1)
            limit: 최대 결과 수
            skip: 건너뛸 결과 수
        """
        params = {
            "search": f"submissions.submission_class_code:{code}",
            "limit": limit,
            "skip": skip,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/drug/drugsfda.json?{urlencode(params)}"
        return await self._request(url)

    async def _request(
        self,
        url: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        API 요청 (재시도 로직 포함)

        Args:
            url: 요청 URL
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격 (초)
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.get(url)

                # Rate limit 처리
                if response.status_code == 429:
                    wait_time = retry_delay * (2 ** attempt)  # 지수 백오프
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 404:
                    # 결과 없음
                    return {"meta": {"results": {"total": 0}}, "results": []}
                await asyncio.sleep(retry_delay)

            except httpx.RequestError as e:
                last_error = e
                await asyncio.sleep(retry_delay)

        raise last_error or Exception("Unknown error")


class FDAApprovalIngestor(BaseIngestor):
    """FDA 승인 정보 수집기"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        days_back: int = 7,
    ):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.days_back = days_back

    def source_type(self) -> str:
        return "FDA_APPROVAL"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        최근 FDA 승인 정보 수집

        Returns:
            승인 정보 목록
        """
        all_results = []

        async with FDAClient(api_key=self.api_key, timeout=self.timeout) as client:
            # 첫 페이지
            response = await client.search_drug_approvals(
                days_back=self.days_back,
                limit=100,
            )

            total = response.get("meta", {}).get("results", {}).get("total", 0)
            results = response.get("results", [])
            all_results.extend(results)

            # 추가 페이지 (100개 이상일 경우)
            skip = 100
            while skip < total:
                response = await client.search_drug_approvals(
                    days_back=self.days_back,
                    limit=100,
                    skip=skip,
                )
                results = response.get("results", [])
                all_results.extend(results)
                skip += 100

        return all_results


class FDAGuidanceIngestor(BaseIngestor):
    """FDA 가이드라인 수집기 (향후 구현)"""

    def source_type(self) -> str:
        return "FDA_GUIDANCE"

    async def fetch(self) -> list[dict[str, Any]]:
        """TODO: FDA Guidance 수집 구현"""
        return []
