"""NICE (영국) Technology Appraisal 수집 — HTA 결정 데이터

NICE Technology Appraisal (TA) 권고 사항 수집.
해외 HTA 선례는 국내 급여 가능성 예측의 핵심 선행지표.

데이터 소스:
- Excel 벌크 다운로드 (인증 불필요, 전체 TA 이력)
- 1,100+ TA, 1,400+ 권고 (2000년~현재)
"""

import asyncio
import io
import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# NICE TA 권고 Excel 다운로드 URL
NICE_TA_XLSX_URL = (
    "https://a.storyblok.com/f/243782/x/0410ebd8e4/ta-recommendations.xlsx"
)

# NICE 개별 가이던스 웹 URL 패턴
NICE_GUIDANCE_URL = "https://www.nice.org.uk/guidance/{ref}"


class NICEClient:
    """NICE TA 데이터 다운로드 클라이언트"""

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
            raise RuntimeError("NICEClient must be used as async context manager")
        return self._client

    async def download_and_parse(self) -> list[dict[str, Any]]:
        """NICE TA Excel 다운로드 후 파싱"""
        xlsx_bytes = await self._download_xlsx()
        return self._parse_xlsx(xlsx_bytes)

    async def _download_xlsx(self, max_retries: int = 3) -> bytes:
        """Excel 파일 다운로드"""
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.get(NICE_TA_XLSX_URL)

                if response.status_code == 429:
                    wait_time = 2.0 * (2 ** attempt)
                    logger.warning(f"NICE rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                logger.info(
                    f"NICE TA Excel downloaded: {len(response.content):,} bytes"
                )
                return response.content

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"NICE download attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1.0)

            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"NICE request error attempt {attempt + 1}: {e}")
                await asyncio.sleep(1.0)

        raise last_error or Exception("NICE TA Excel download failed")

    @staticmethod
    def _parse_xlsx(xlsx_bytes: bytes) -> list[dict[str, Any]]:
        """Excel 파싱 (openpyxl 사용)"""
        try:
            import openpyxl
        except ImportError:
            raise ImportError(
                "openpyxl required for NICE Excel parsing. "
                "Install: pip install openpyxl"
            )

        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
        ws = wb.active

        rows_iter = ws.iter_rows(values_only=True)

        # 첫 행 = 헤더
        header_row = next(rows_iter, None)
        if not header_row:
            return []

        # 헤더 정규화 (공백/줄바꿈 제거, 소문자)
        headers = []
        for h in header_row:
            if h is None:
                headers.append("")
            else:
                headers.append(str(h).strip().replace("\n", " "))

        records = []
        for row in rows_iter:
            if not row or all(cell is None for cell in row):
                continue

            record = {}
            for i, value in enumerate(row):
                if i < len(headers) and headers[i]:
                    key = headers[i]
                    if value is None:
                        record[key] = ""
                    elif isinstance(value, datetime):
                        record[key] = value.strftime("%Y-%m-%d")
                    else:
                        record[key] = str(value).strip()

            # TA 번호가 없으면 스킵
            ta_ref = (
                record.get("TA ID", "")
                or record.get("Appraisal number", "")
                or record.get("TA number", "")
            )
            if not ta_ref:
                continue

            records.append(record)

        wb.close()
        logger.info(f"NICE TA: {len(records):,} recommendations parsed")
        return records


class NICETAIngestor(BaseIngestor):
    """NICE Technology Appraisal 수집기 — 전체 TA 권고"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "NICE_TA"

    async def fetch(self) -> list[dict[str, Any]]:
        """NICE TA 전체 권고 수집

        Returns:
            TA 권고 레코드 리스트
        """
        async with NICEClient(timeout=self.timeout) as client:
            records = await client.download_and_parse()

        today = datetime.now().strftime("%Y-%m-%d")
        for row in records:
            row["_source"] = "nice_ta"
            row["_fetched_at"] = today

            # 가이던스 URL 추가
            ta_ref = row.get("TA ID", "") or row.get("Appraisal number", "")
            if ta_ref:
                row["_guidance_url"] = NICE_GUIDANCE_URL.format(ref=ta_ref.lower())

        logger.info(f"NICE TA total: {len(records):,} recommendations")
        return records


class NICERecentTAIngestor(BaseIngestor):
    """NICE Technology Appraisal 최근 권고만 수집

    지정 연도 이후의 TA만 필터링하여 반환.
    """

    def __init__(self, timeout: float = 60.0, years_back: int = 2):
        super().__init__(timeout=timeout)
        self.years_back = years_back

    def source_type(self) -> str:
        return "NICE_TA_RECENT"

    async def fetch(self) -> list[dict[str, Any]]:
        """최근 N년간 TA 권고 수집"""
        async with NICEClient(timeout=self.timeout) as client:
            all_records = await client.download_and_parse()

        cutoff_year = datetime.now().year - self.years_back
        today = datetime.now().strftime("%Y-%m-%d")

        records = []
        for row in all_records:
            # 연도 필드에서 필터링 (형식: "2024/25" 또는 "2024")
            pub_year_raw = row.get("Year of Publication", "") or row.get(
                "Year of publication", ""
            )
            try:
                year_str = pub_year_raw.split("/")[0].strip()
                if int(year_str) < cutoff_year:
                    continue
            except (ValueError, TypeError, IndexError):
                pass

            row["_source"] = "nice_ta"
            row["_fetched_at"] = today

            ta_ref = row.get("TA ID", "") or row.get("Appraisal number", "")
            if ta_ref:
                row["_guidance_url"] = NICE_GUIDANCE_URL.format(ref=ta_ref.lower())

            records.append(row)

        logger.info(
            f"NICE TA recent: {len(records):,} recommendations "
            f"(since {cutoff_year}, out of {len(all_records):,} total)"
        )
        return records
