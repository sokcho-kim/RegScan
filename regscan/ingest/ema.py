"""EMA (European Medicines Agency) 데이터 수집"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from enum import Enum

import httpx

from .base import BaseIngestor

logger = logging.getLogger(__name__)


class EMAEndpoint(str, Enum):
    """EMA JSON API 엔드포인트"""

    # 의약품 데이터
    MEDICINES = "medicines-output-medicines_json-report_en.json"
    POST_AUTH = "medicines-output-post_authorisation_json-report_en.json"
    ORPHAN = "medicines-output-orphan_designations-json-report_en.json"
    HERBAL = "medicines-output-herbal_medicines-report-output-json_en.json"
    OUTSIDE_EU = "medicine-use-outside-eu-output-json-report_en.json"

    # 안전성 데이터
    SHORTAGES = "shortages-output-json-report_en.json"
    REFERRALS = "referrals-output-json-report_en.json"
    DHPC = "dhpc-output-json-report_en.json"
    PSUSA = "medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json"

    # 소아 데이터
    PIP = "medicines-output-paediatric_investigation_plans-output-json-report_en.json"

    # 문서
    DOCUMENTS = "documents-output-json-report_en.json"
    EPAR_DOCS = "documents-output-epar_documents_json-report_en.json"
    NON_EPAR_DOCS = "documents-output-non_epar_documents_json-report_en.json"

    # 일반
    NEWS = "news-json-report_en.json"
    EVENTS = "events-json-report_en.json"
    GENERAL = "general-json-report_en.json"


class EMAClient:
    """EMA API 클라이언트

    EMA JSON API는 인증이 필요 없으며, 하루 2회 (06:00, 18:00 CET) 업데이트됩니다.
    """

    BASE_URL = "https://www.ema.europa.eu/en/documents/report"

    def __init__(self, timeout: float = 60.0):
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
            raise RuntimeError("EMAClient must be used as async context manager")
        return self._client

    async def fetch_endpoint(
        self,
        endpoint: EMAEndpoint,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> list[dict[str, Any]]:
        """
        EMA 엔드포인트에서 데이터 가져오기

        Args:
            endpoint: EMA 엔드포인트
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격 (초)

        Returns:
            데이터 목록
        """
        url = f"{self.BASE_URL}/{endpoint.value}"
        return await self._request(url, max_retries, retry_delay)

    async def fetch_medicines(self) -> list[dict[str, Any]]:
        """EU 승인 의약품 목록"""
        return await self.fetch_endpoint(EMAEndpoint.MEDICINES)

    async def fetch_orphan_designations(self) -> list[dict[str, Any]]:
        """희귀의약품 지정 목록"""
        return await self.fetch_endpoint(EMAEndpoint.ORPHAN)

    async def fetch_shortages(self) -> list[dict[str, Any]]:
        """의약품 공급 부족 목록"""
        return await self.fetch_endpoint(EMAEndpoint.SHORTAGES)

    async def fetch_referrals(self) -> list[dict[str, Any]]:
        """안전성 심사(Referrals) 목록"""
        return await self.fetch_endpoint(EMAEndpoint.REFERRALS)

    async def fetch_dhpc(self) -> list[dict[str, Any]]:
        """의료전문가 안전 통신 (DHPC) 목록"""
        return await self.fetch_endpoint(EMAEndpoint.DHPC)

    async def fetch_pip(self) -> list[dict[str, Any]]:
        """소아 임상시험 계획 (PIP) 목록"""
        return await self.fetch_endpoint(EMAEndpoint.PIP)

    async def fetch_news(self) -> list[dict[str, Any]]:
        """EMA 뉴스"""
        return await self.fetch_endpoint(EMAEndpoint.NEWS)

    async def _request(
        self,
        url: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> list[dict[str, Any]]:
        """
        API 요청 (재시도 로직 포함)

        Args:
            url: 요청 URL
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격 (초)

        Returns:
            JSON 응답 데이터 (리스트)
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.get(url, follow_redirects=True)

                # Rate limit 처리
                if response.status_code == 429:
                    wait_time = retry_delay * (2**attempt)
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                # EMA API는 리스트를 직접 반환
                if isinstance(data, list):
                    return data
                # 혹시 dict로 래핑되어 있다면
                elif isinstance(data, dict):
                    return data.get("data", data.get("results", [data]))

                return []

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 404:
                    return []
                await asyncio.sleep(retry_delay)

            except httpx.RequestError as e:
                last_error = e
                await asyncio.sleep(retry_delay)

            except Exception as e:
                last_error = e
                await asyncio.sleep(retry_delay)

        # 실패 시 빈 리스트 반환 (에러 로깅)
        logger.error(f"[EMA] Request failed after {max_retries} attempts: {url}")
        if last_error:
            logger.error(f"[EMA] Last error: {last_error}")
        return []


class EMAMedicineIngestor(BaseIngestor):
    """EMA 의약품 수집기"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "EMA_MEDICINE"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        EMA 승인 의약품 수집

        Returns:
            의약품 목록
        """
        async with EMAClient(timeout=self.timeout) as client:
            return await client.fetch_medicines()


class EMAOrphanIngestor(BaseIngestor):
    """EMA 희귀의약품 수집기"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "EMA_ORPHAN"

    async def fetch(self) -> list[dict[str, Any]]:
        """희귀의약품 지정 목록 수집"""
        async with EMAClient(timeout=self.timeout) as client:
            return await client.fetch_orphan_designations()


class EMAShortageIngestor(BaseIngestor):
    """EMA 공급 부족 수집기"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "EMA_SHORTAGE"

    async def fetch(self) -> list[dict[str, Any]]:
        """공급 부족 목록 수집"""
        async with EMAClient(timeout=self.timeout) as client:
            return await client.fetch_shortages()


class EMASafetyIngestor(BaseIngestor):
    """EMA 안전성 정보 수집기 (DHPC, Referrals)"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "EMA_SAFETY"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        안전성 관련 정보 수집 (DHPC + Referrals)

        Returns:
            통합된 안전성 정보 목록
        """
        async with EMAClient(timeout=self.timeout) as client:
            dhpc = await client.fetch_dhpc()
            referrals = await client.fetch_referrals()

            # 소스 타입 태깅
            for item in dhpc:
                item["_ema_type"] = "dhpc"
            for item in referrals:
                item["_ema_type"] = "referral"

            return dhpc + referrals


# 편의 함수
async def fetch_ema_medicines() -> list[dict[str, Any]]:
    """EMA 의약품 목록 조회 (간편 함수)"""
    async with EMAClient() as client:
        return await client.fetch_medicines()


async def fetch_ema_all(
    include_medicines: bool = True,
    include_orphan: bool = True,
    include_shortages: bool = True,
    include_safety: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """
    EMA 전체 데이터 조회

    Args:
        include_medicines: 의약품 포함 여부
        include_orphan: 희귀의약품 포함 여부
        include_shortages: 공급 부족 포함 여부
        include_safety: 안전성 정보 포함 여부

    Returns:
        카테고리별 데이터 딕셔너리
    """
    result = {}

    async with EMAClient() as client:
        if include_medicines:
            result["medicines"] = await client.fetch_medicines()
        if include_orphan:
            result["orphan"] = await client.fetch_orphan_designations()
        if include_shortages:
            result["shortages"] = await client.fetch_shortages()
        if include_safety:
            result["dhpc"] = await client.fetch_dhpc()
            result["referrals"] = await client.fetch_referrals()

    return result
