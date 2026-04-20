"""FDA Purple Book 데이터 수집 — 생물의약품(BLA) 특허/독점권 정보

Purple Book은 BLA(생물의약품) + 바이오시밀러를 수록.
NDA(소분자)는 Orange Book에서 수집.

데이터 소스: https://purplebooksearch.fda.gov/downloads
- 월별 CSV 파일 (전체 DB 덤프)
- 업데이트 플래그: U(수정), N(신규 승인), R(이번 릴리스 추가)
"""

import asyncio
import csv
import io
import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# 월별 CSV URL 패턴
PURPLE_BOOK_CSV_URL = (
    "https://purplebooksearch.fda.gov/files/{year}/"
    "purplebook-search-{month}-data-download.csv"
)

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


class PurpleBookClient:
    """FDA Purple Book CSV 다운로드 및 파싱 클라이언트"""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("PurpleBookClient must be used as async context manager")
        return self._client

    async def download_and_parse(
        self, year: Optional[int] = None, month: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """최신 Purple Book CSV 다운로드 후 파싱

        Args:
            year: 대상 연도 (기본: 현재 연도)
            month: 대상 월 (기본: 현재 월부터 역순 탐색)

        Returns:
            제품 레코드 리스트
        """
        csv_text = await self._download_csv(year, month)
        return self._parse_csv(csv_text)

    async def _download_csv(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        max_retries: int = 3,
    ) -> str:
        """CSV 파일 다운로드 (최신 월부터 역순 탐색)"""
        now = datetime.now()
        target_year = year or now.year
        target_month = month or now.month

        # 지정 월부터 역순으로 최대 6개월 탐색
        for offset in range(6):
            m = target_month - offset
            y = target_year
            if m <= 0:
                m += 12
                y -= 1

            month_name = MONTH_NAMES[m - 1]
            url = PURPLE_BOOK_CSV_URL.format(year=y, month=month_name)

            for attempt in range(max_retries):
                try:
                    response = await self.client.get(url)

                    if response.status_code == 404:
                        logger.debug(f"Purple Book {y}-{m:02d} not found, trying earlier")
                        break  # 이전 월 시도

                    if response.status_code == 429:
                        wait_time = 2.0 * (2 ** attempt)
                        logger.warning(f"Purple Book rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    logger.info(
                        f"Purple Book CSV downloaded: {y}-{m:02d} "
                        f"({len(response.content):,} bytes)"
                    )
                    return response.text

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        break
                    logger.warning(f"Purple Book download attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(1.0)

                except httpx.RequestError as e:
                    logger.warning(f"Purple Book request error attempt {attempt + 1}: {e}")
                    await asyncio.sleep(1.0)

        raise Exception(
            f"Purple Book CSV not found for {target_year}-{target_month:02d} "
            f"(searched {min(6, target_month)} months back)"
        )

    def _parse_csv(self, csv_text: str) -> list[dict[str, Any]]:
        """CSV 텍스트 → dict 리스트

        Purple Book CSV는 표준 CSV (쉼표 구분, 헤더 행 포함).
        빈 행과 메타데이터 행(합계 등) 자동 스킵.
        """
        rows = []
        reader = csv.DictReader(io.StringIO(csv_text))

        for row in reader:
            # 빈 행 또는 합계 행 스킵
            bla = row.get("BLA Number", "").strip()
            if not bla or not bla.isdigit():
                continue

            # 필드 정규화 (앞뒤 공백 제거)
            cleaned = {k.strip(): v.strip() for k, v in row.items() if k}
            rows.append(cleaned)

        logger.info(f"Purple Book: {len(rows):,} records parsed")
        return rows


class FDAPurpleBookIngestor(BaseIngestor):
    """FDA Purple Book 수집기 — BLA 생물의약품 전체"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "FDA_PURPLE_BOOK"

    async def fetch(self) -> list[dict[str, Any]]:
        """Purple Book 전체 다운로드

        Returns:
            BLA 제품 레코드 리스트 (독점권 만료일, 바이오시밀러 여부 포함)
        """
        async with PurpleBookClient(timeout=self.timeout) as client:
            records = await client.download_and_parse()

        today = datetime.now().strftime("%Y-%m-%d")
        for row in records:
            row["_source"] = "purple_book"
            row["_fetched_at"] = today

        logger.info(f"Purple Book total: {len(records):,} BLA products")
        return records


class FDABiologicExpiryIngestor(BaseIngestor):
    """FDA Purple Book 독점권 만료 전용 수집기

    Reference product exclusivity (12년), orphan exclusivity,
    interchangeable exclusivity 만료일이 있는 레코드만 필터링.
    """

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "FDA_BIOLOGIC_EXPIRY"

    async def fetch(self) -> list[dict[str, Any]]:
        """독점권 만료 데이터가 있는 BLA 제품만 반환"""
        async with PurpleBookClient(timeout=self.timeout) as client:
            all_records = await client.download_and_parse()

        today = datetime.now().strftime("%Y-%m-%d")
        expiry_fields = [
            "Reference Product Exclusivity Expiry Date",
            "Orphan Exclusivity Expiry Date",
            "First Interchangeable Exclusivity Expiry Date",
        ]

        records = []
        for row in all_records:
            # 만료일 필드 중 하나라도 값이 있으면 포함
            has_expiry = any(row.get(f, "").strip() for f in expiry_fields)
            if not has_expiry:
                continue

            record = {
                "bla_number": row.get("BLA Number", ""),
                "proper_name": row.get("Proper Name", ""),
                "proprietary_name": row.get("Proprietary Name", ""),
                "applicant": row.get("Applicant", ""),
                "license_type": row.get("License Type", ""),
                "dosage_form": row.get("Dosage Form", ""),
                "route": row.get("Route of Administration", ""),
                "strength": row.get("Strength", ""),
                "approval_date": row.get("Date of First Licensure", ""),
                "ref_product_exclusivity_expiry": row.get(
                    "Reference Product Exclusivity Expiry Date", ""
                ),
                "orphan_exclusivity_expiry": row.get(
                    "Orphan Exclusivity Expiry Date", ""
                ),
                "interchangeable_exclusivity_expiry": row.get(
                    "First Interchangeable Exclusivity Expiry Date", ""
                ),
                "_source": "purple_book",
                "_ob_type": "biologic_expiry",
                "_fetched_at": today,
            }
            records.append(record)

        logger.info(
            f"Biologic expiry: {len(records):,} records "
            f"(out of {len(all_records):,} total BLA products)"
        )
        return records
