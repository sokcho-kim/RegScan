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
import re
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# 월별 CSV URL 패턴 (accessdata.fda.gov 도메인)
PURPLE_BOOK_CSV_URL = (
    "https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/{year}/"
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
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        # 세션 쿠키 획득 (bot 감지 우회)
        await self._client.get("https://purplebooksearch.fda.gov/")
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

    async def _get_download_urls(self) -> list[str]:
        """다운로드 페이지에서 실제 CSV URL 목록 추출 (최신순)"""
        downloads_url = "https://purplebooksearch.fda.gov/index.cfm?event=downloads"
        response = await self.client.get(downloads_url)
        response.raise_for_status()

        urls = re.findall(
            r'href=["\']([^"\']+\.csv)["\']', response.text, re.I
        )
        logger.info(f"Purple Book downloads page: {len(urls)} CSV links found")
        return urls

    async def _download_csv(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        max_retries: int = 3,
    ) -> str:
        """CSV 파일 다운로드

        다운로드 페이지를 먼저 방문하여 세션/Referer를 확보한 뒤
        실제 CSV URL을 가져옴. 최신 파일 우선.
        """
        # Step 1: 다운로드 페이지에서 실제 URL 추출
        csv_urls = await self._get_download_urls()
        if not csv_urls:
            raise Exception("Purple Book downloads page에서 CSV 링크를 찾을 수 없음")

        # year/month 지정 시 해당 파일 우선 선택
        target_url = None
        if year and month:
            month_name = MONTH_NAMES[month - 1]
            for url in csv_urls:
                if f"/{year}/" in url and month_name in url.lower():
                    target_url = url
                    break

        # 지정 없으면 최신 (첫 번째 = 가장 최근)
        if not target_url:
            target_url = csv_urls[0]

        # Step 2: Referer 설정 후 다운로드
        headers = {
            "Referer": "https://purplebooksearch.fda.gov/index.cfm?event=downloads",
        }

        for attempt in range(max_retries):
            try:
                response = await self.client.get(target_url, headers=headers)

                if response.status_code == 429:
                    await asyncio.sleep(2.0 * (2 ** attempt))
                    continue

                response.raise_for_status()
                logger.info(
                    f"Purple Book CSV downloaded: {target_url.split('/')[-1]} "
                    f"({len(response.content):,} bytes)"
                )
                return response.text

            except httpx.HTTPStatusError as e:
                logger.warning(f"Purple Book download attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1.0)

            except httpx.RequestError as e:
                logger.warning(f"Purple Book request error {attempt + 1}: {e}")
                await asyncio.sleep(1.0)

        raise Exception(f"Purple Book CSV download failed: {target_url}")

    @staticmethod
    def _parse_csv(csv_text: str) -> list[dict[str, Any]]:
        """CSV 텍스트 → dict 리스트

        Purple Book CSV 구조:
        - Line 0~2: 메타데이터 (제목, 빈 줄, 범례)
        - Line 3: 실제 헤더 (N/R/U, Applicant, BLA Number, ...)
        - Line 4+: 데이터 (변경분 + 전체 DB 순서)
        - BOM (﻿) 포함 가능

        "BLA Number" 컬럼에 숫자가 있는 행만 파싱.
        """
        # BOM 제거
        csv_text = csv_text.lstrip("\ufeff")

        # 실제 헤더 행 찾기: "BLA Number" 포함된 첫 줄
        lines = csv_text.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if "BLA Number" in line:
                header_idx = i
                break

        if header_idx is None:
            logger.warning("Purple Book: 'BLA Number' header not found")
            return []

        # 헤더 이후부터 DictReader로 파싱
        data_text = "\n".join(lines[header_idx:])
        reader = csv.DictReader(io.StringIO(data_text))

        rows = []
        for row in reader:
            bla = row.get("BLA Number", "").strip()
            if not bla or not bla.isdigit():
                continue

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
        """독점권 만료 데이터가 있는 BLA 제품만 반환

        FDAPurpleBookIngestor와 동일 데이터 재사용.
        """
        parent = FDAPurpleBookIngestor(timeout=self.timeout)
        all_records = await parent.fetch()

        today = datetime.now().strftime("%Y-%m-%d")
        expiry_fields = [
            "Ref. Product Exclusivity Exp. Date",
            "Orphan Exclusivity Exp. Date",
            "First Interchangeable Exclusivity Exp. Date",
            "Exclusivity Expiration Date",
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
                "bla_type": row.get("BLA Type", ""),
                "dosage_form": row.get("Dosage Form", ""),
                "route": row.get("Route of Administration", ""),
                "strength": row.get("Strength", ""),
                "approval_date": row.get("Approval Date", ""),
                "date_of_first_licensure": row.get("Date of First Licensure", ""),
                "exclusivity_expiration_date": row.get(
                    "Exclusivity Expiration Date", ""
                ),
                "ref_product_exclusivity_expiry": row.get(
                    "Ref. Product Exclusivity Exp. Date", ""
                ),
                "orphan_exclusivity_expiry": row.get(
                    "Orphan Exclusivity Exp. Date", ""
                ),
                "interchangeable_exclusivity_expiry": row.get(
                    "First Interchangeable Exclusivity Exp. Date", ""
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
