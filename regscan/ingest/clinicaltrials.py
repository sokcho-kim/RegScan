"""ClinicalTrials.gov v2 API 클라이언트

Phase 3 완료/중단/중지 임상시험 수집.
API 문서: https://clinicaltrials.gov/data-api/api
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from regscan.config import settings
from regscan.ingest.base import BaseIngestor

logger = logging.getLogger(__name__)

CT_GOV_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# v2 API 필드 목록
DEFAULT_FIELDS = [
    "NCTId",
    "BriefTitle",
    "Condition",
    "InterventionName",
    "InterventionType",
    "Phase",
    "OverallStatus",
    "CompletionDate",
    "ResultsFirstPostDate",
    "LeadSponsorName",
    "EnrollmentCount",
    "WhyStopped",
    "StudyType",
]


class ClinicalTrialsGovClient:
    """ClinicalTrials.gov v2 API 클라이언트"""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "RegScan/3.0 (Python aiohttp/3.12)"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ClinicalTrialsGovClient must be used as async context manager")
        return self._client

    async def search_studies(
        self,
        condition: str = "",
        phase: str = "PHASE3",
        statuses: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """임상시험 검색

        Args:
            condition: 질환명 (e.g. "Cancer")
            phase: 임상 단계 (PHASE3)
            statuses: 상태 필터 (COMPLETED, TERMINATED, SUSPENDED)
            date_range: (start, end) 날짜 범위 YYYY-MM-DD
            page_size: 페이지 크기
            page_token: 다음 페이지 토큰
        """
        if statuses is None:
            statuses = ["COMPLETED", "TERMINATED", "SUSPENDED"]

        params: dict[str, Any] = {
            "format": "json",
            "pageSize": page_size,
        }

        # 쿼리 구성: query.cond (전용 파라미터) + filter로 분리
        if condition:
            params["query.cond"] = condition

        params["filter.overallStatus"] = ",".join(statuses)

        # Phase + Date를 filter.advanced에 결합
        advanced_parts = []
        if phase:
            advanced_parts.append(f"AREA[Phase]{phase}")
        if date_range:
            advanced_parts.append(
                f"AREA[CompletionDate]RANGE[{date_range[0]},{date_range[1]}]"
            )
        if advanced_parts:
            params["filter.advanced"] = " AND ".join(advanced_parts)

        if page_token:
            params["pageToken"] = page_token

        response = await self.client.get(CT_GOV_BASE_URL, params=params)
        response.raise_for_status()
        return response.json()

    async def search_all(
        self,
        condition: str = "",
        phase: str = "PHASE3",
        statuses: list[str] | None = None,
        months_back: int = 6,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """자동 페이지네이션으로 전체 결과 수집"""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")

        all_results: list[dict] = []
        page_token: str | None = None

        while len(all_results) < max_results:
            data = await self.search_studies(
                condition=condition,
                phase=phase,
                statuses=statuses,
                date_range=(start_date, end_date),
                page_token=page_token,
            )

            studies = data.get("studies", [])
            all_results.extend(studies)

            page_token = data.get("nextPageToken")
            if not page_token or not studies:
                break

            # Rate limit: 1초 딜레이
            await asyncio.sleep(1.0)

        logger.info(
            "CT.gov 검색 완료: condition=%s, %d건 (최대 %d)",
            condition, len(all_results), max_results,
        )
        return all_results[:max_results]


class ClinicalTrialsGovIngestor(BaseIngestor):
    """ClinicalTrials.gov Phase 3 수집기"""

    def __init__(
        self,
        conditions: list[str] | None = None,
        months_back: int | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(timeout=timeout)
        self.conditions = conditions or ["Cancer", "Diabetes", "Heart Failure"]
        self.months_back = months_back or settings.CT_GOV_MONTHS_BACK

    def source_type(self) -> str:
        return "CT_GOV"

    async def fetch(self) -> list[dict[str, Any]]:
        """Phase 3 완료/중단 임상시험 수집"""
        all_studies: list[dict] = []
        seen_ncts: set[str] = set()

        async with ClinicalTrialsGovClient(timeout=self.timeout) as client:
            for condition in self.conditions:
                try:
                    studies = await client.search_all(
                        condition=condition,
                        phase="PHASE3",
                        statuses=["COMPLETED", "TERMINATED", "SUSPENDED"],
                        months_back=self.months_back,
                    )
                    for study in studies:
                        nct_id = self._extract_nct_id(study)
                        if nct_id and nct_id not in seen_ncts:
                            seen_ncts.add(nct_id)
                            study["_search_condition"] = condition
                            study["_collected_at"] = datetime.utcnow().isoformat()
                            all_studies.append(study)
                except Exception as e:
                    logger.warning("CT.gov 수집 실패 (condition=%s): %s", condition, e)

        logger.info("CT.gov 총 %d건 수집 (conditions=%d)", len(all_studies), len(self.conditions))
        return all_studies

    def _extract_nct_id(self, study: dict) -> str:
        """v2 API 구조에서 NCT ID 추출"""
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        return ident.get("nctId", "")
