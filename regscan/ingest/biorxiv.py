"""bioRxiv/medRxiv 프리프린트 논문 수집기

bioRxiv API를 사용하여 약물 관련 프리프린트 논문을 수집합니다.
API 문서: https://api.biorxiv.org/

HTTP API 기반 (Playwright 불필요).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

BIORXIV_API_BASE = "https://api.biorxiv.org/details"


class BioRxivClient:
    """bioRxiv/medRxiv API 클라이언트"""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client = None

    async def __aenter__(self):
        import httpx
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    async def fetch_recent(
        self,
        server: str = "biorxiv",
        days_back: int = 7,
        cursor: int = 0,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """최근 N일간 프리프린트 수집

        Args:
            server: "biorxiv" 또는 "medrxiv"
            days_back: 최근 N일
            cursor: 페이지네이션 커서
            page_size: 페이지 크기 (최대 100)

        Returns:
            프리프린트 목록
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        url = f"{BIORXIV_API_BASE}/{server}/{start_date}/{end_date}/{cursor}"
        response = await self._client.get(url)
        response.raise_for_status()

        data = response.json()
        collection = data.get("collection", [])

        logger.info(
            "%s API: %d건 수집 (%s ~ %s, cursor=%d)",
            server, len(collection), start_date, end_date, cursor,
        )
        return collection

    async def fetch_all_recent(
        self,
        server: str = "biorxiv",
        days_back: int = 7,
        max_results: int = 500,
    ) -> list[dict[str, Any]]:
        """페이지네이션을 통해 최근 프리프린트 전체 수집"""
        all_results = []
        cursor = 0
        page_size = 100

        while len(all_results) < max_results:
            batch = await self.fetch_recent(
                server=server, days_back=days_back, cursor=cursor
            )
            if not batch:
                break

            all_results.extend(batch)
            cursor += len(batch)

            if len(batch) < page_size:
                break

        return all_results[:max_results]

    async def search_by_keyword(
        self,
        keyword: str,
        server: str = "biorxiv",
        days_back: int = 30,
    ) -> list[dict[str, Any]]:
        """키워드 기반 프리프린트 필터링

        bioRxiv API는 키워드 검색을 직접 지원하지 않으므로
        전체 수집 후 제목/초록에서 필터링합니다.
        """
        all_papers = await self.fetch_all_recent(server=server, days_back=days_back)
        keyword_lower = keyword.lower()

        filtered = [
            paper for paper in all_papers
            if keyword_lower in (paper.get("title", "") + paper.get("abstract", "")).lower()
        ]

        logger.info(
            "%s 키워드 '%s' 필터: %d/%d건",
            server, keyword, len(filtered), len(all_papers),
        )
        return filtered


class BioRxivIngestor(BaseIngestor):
    """bioRxiv/medRxiv 프리프린트 수집기"""

    def __init__(
        self,
        drug_keywords: list[str] | None = None,
        servers: list[str] | None = None,
        days_back: int = 7,
        timeout: float = 30.0,
    ):
        super().__init__(timeout=timeout)
        self.drug_keywords = drug_keywords or []
        self.servers = servers or ["biorxiv", "medrxiv"]
        self.days_back = days_back

    def source_type(self) -> str:
        return "BIORXIV"

    async def fetch(self) -> list[dict[str, Any]]:
        """bioRxiv/medRxiv 프리프린트 수집

        Returns:
            프리프린트 목록 (파싱 전 raw data)
        """
        all_papers = []
        seen_dois = set()

        async with BioRxivClient(timeout=self.timeout) as client:
            for server in self.servers:
                for keyword in self.drug_keywords:
                    try:
                        papers = await client.search_by_keyword(
                            keyword=keyword,
                            server=server,
                            days_back=self.days_back,
                        )
                        for paper in papers:
                            doi = paper.get("doi", "")
                            if doi and doi not in seen_dois:
                                seen_dois.add(doi)
                                paper["server"] = server
                                paper["search_keyword"] = keyword
                                paper["collected_at"] = self._now().isoformat()
                                all_papers.append(paper)
                    except Exception as e:
                        logger.warning(
                            "%s '%s' 수집 실패: %s", server, keyword, e
                        )

        logger.info("bioRxiv/medRxiv 총 %d건 수집 완료", len(all_papers))
        return all_papers
