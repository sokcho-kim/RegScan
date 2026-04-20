"""FDA Orange Book 데이터 수집 — 특허/독점권 만료 정보

Orange Book은 NDA(소분자) + ANDA(제네릭)만 수록.
BLA(생물의약품, e.g. pembrolizumab)는 Purple Book에서 별도 수집 필요.
"""

import asyncio
import csv
import io
import logging
import zipfile
from datetime import datetime
from typing import Any, Optional

import httpx

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# FDA Orange Book ZIP 다운로드 URL
ORANGE_BOOK_ZIP_URL = "https://www.fda.gov/media/76860/download"

# 틸드 구분자 파일 내 컬럼 정의 (FDA 공식 스키마)
PRODUCT_COLUMNS = [
    "Ingredient",
    "DF;Route",
    "Trade_Name",
    "Applicant",
    "Strength",
    "Appl_Type",
    "Appl_No",
    "Product_No",
    "TE_Code",
    "Approval_Date",
    "RLD",
    "RS",
    "Type",
    "Applicant_Full_Name",
]

PATENT_COLUMNS = [
    "Appl_Type",
    "Appl_No",
    "Product_No",
    "Patent_No",
    "Patent_Expire_Date_Text",
    "Drug_Substance_Flag",
    "Drug_Product_Flag",
    "Patent_Use_Code",
    "Delist_Flag",
    "Submission_Date",
]

EXCLUSIVITY_COLUMNS = [
    "Appl_Type",
    "Appl_No",
    "Product_No",
    "Exclusivity_Code",
    "Exclusivity_Date",
]


class OrangeBookClient:
    """FDA Orange Book ZIP 다운로드 및 파싱 클라이언트"""

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
            raise RuntimeError("OrangeBookClient must be used as async context manager")
        return self._client

    async def download_and_parse(self) -> dict[str, list[dict[str, Any]]]:
        """Orange Book ZIP 다운로드 후 3개 파일 파싱

        Returns:
            {"products": [...], "patents": [...], "exclusivities": [...]}
        """
        zip_bytes = await self._download_zip()
        return self._parse_zip(zip_bytes)

    async def _download_zip(self, max_retries: int = 3) -> bytes:
        """ZIP 파일 다운로드 (재시도 포함)"""
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.get(ORANGE_BOOK_ZIP_URL)

                if response.status_code == 429:
                    wait_time = 2.0 * (2 ** attempt)
                    logger.warning(f"Orange Book rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                logger.info(
                    f"Orange Book ZIP downloaded: {len(response.content):,} bytes"
                )
                return response.content

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"Orange Book download attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1.0)

            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Orange Book request error attempt {attempt + 1}: {e}")
                await asyncio.sleep(1.0)

        raise last_error or Exception("Orange Book download failed")

    def _parse_zip(self, zip_bytes: bytes) -> dict[str, list[dict[str, Any]]]:
        """ZIP 내 3개 틸드 구분 파일 파싱"""
        result = {"products": [], "patents": [], "exclusivities": []}

        file_map = {
            "products": ("products.txt", PRODUCT_COLUMNS),
            "patents": ("patent.txt", PATENT_COLUMNS),
            "exclusivities": ("exclusivity.txt", EXCLUSIVITY_COLUMNS),
        }

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            logger.info(f"Orange Book ZIP contains: {names}")

            for key, (filename, columns) in file_map.items():
                # 파일명 대소문자 무관 매칭
                matched = next(
                    (n for n in names if n.lower() == filename.lower()),
                    None,
                )
                if not matched:
                    logger.warning(f"Orange Book: {filename} not found in ZIP")
                    continue

                raw = zf.read(matched).decode("utf-8", errors="replace")
                rows = self._parse_tilde_delimited(raw, columns)
                result[key] = rows
                logger.info(f"Orange Book {key}: {len(rows):,} records parsed")

        return result

    def _parse_tilde_delimited(
        self, text: str, columns: list[str]
    ) -> list[dict[str, Any]]:
        """틸드(~) 구분 텍스트 → dict 리스트

        첫 줄은 헤더로 스킵하고, 실제 컬럼 정의는 COLUMNS 상수 사용.
        FDA 파일은 헤더 컬럼명이 일관적이지 않으므로 고정 스키마 우선.
        """
        rows = []
        lines = text.strip().splitlines()

        if not lines:
            return rows

        # 첫 줄 헤더 스킵
        for line in lines[1:]:
            fields = line.split("~")

            if len(fields) < len(columns):
                # 필드 부족 → 빈 문자열로 패딩
                fields.extend([""] * (len(columns) - len(fields)))

            row = {col: fields[i].strip() for i, col in enumerate(columns)}
            rows.append(row)

        return rows


class FDAOrangeBookIngestor(BaseIngestor):
    """FDA Orange Book 수집기 — 특허/독점권 만료 데이터"""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "FDA_ORANGE_BOOK"

    async def fetch(self) -> list[dict[str, Any]]:
        """Orange Book 전체 다운로드 후 특허/독점권 레코드 반환

        Returns:
            통합 레코드 리스트. 각 레코드에 _ob_type 필드 포함:
            - "patent": 특허 정보 (만료일, 용도코드)
            - "exclusivity": 독점권 정보 (코드, 만료일)
            - "product": 제품 정보 (성분, 승인일, TE 코드)
        """
        async with OrangeBookClient(timeout=self.timeout) as client:
            data = await client.download_and_parse()

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        # 제품 정보
        for row in data["products"]:
            row["_ob_type"] = "product"
            row["_fetched_at"] = today
            records.append(row)

        # 특허 정보
        for row in data["patents"]:
            row["_ob_type"] = "patent"
            row["_fetched_at"] = today
            records.append(row)

        # 독점권 정보
        for row in data["exclusivities"]:
            row["_ob_type"] = "exclusivity"
            row["_fetched_at"] = today
            records.append(row)

        logger.info(
            f"Orange Book total: {len(records):,} records "
            f"(products={len(data['products']):,}, "
            f"patents={len(data['patents']):,}, "
            f"exclusivities={len(data['exclusivities']):,})"
        )

        return records


class FDAPatentExpiryIngestor(BaseIngestor):
    """FDA Orange Book 특허 만료 전용 수집기

    전체 Orange Book 중 patent + product만 조인하여
    INN별 특허 만료일 목록을 반환.
    """

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)

    def source_type(self) -> str:
        return "FDA_PATENT_EXPIRY"

    async def fetch(self) -> list[dict[str, Any]]:
        """특허 만료 데이터 수집 + 제품 정보 조인

        Returns:
            특허 레코드 리스트 (INN, 브랜드명, 특허번호, 만료일 포함)
        """
        async with OrangeBookClient(timeout=self.timeout) as client:
            data = await client.download_and_parse()

        # product → (Appl_Type, Appl_No, Product_No) 인덱스
        product_index: dict[str, dict[str, Any]] = {}
        for p in data["products"]:
            key = f"{p.get('Appl_Type', '')}_{p.get('Appl_No', '')}_{p.get('Product_No', '')}"
            product_index[key] = p

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        for patent in data["patents"]:
            key = f"{patent.get('Appl_Type', '')}_{patent.get('Appl_No', '')}_{patent.get('Product_No', '')}"
            product = product_index.get(key, {})

            record = {
                # 제품 정보
                "ingredient": product.get("Ingredient", ""),
                "trade_name": product.get("Trade_Name", ""),
                "applicant": product.get("Applicant_Full_Name", "")
                or product.get("Applicant", ""),
                "appl_type": patent.get("Appl_Type", ""),
                "appl_no": patent.get("Appl_No", ""),
                "product_no": patent.get("Product_No", ""),
                "strength": product.get("Strength", ""),
                "approval_date": product.get("Approval_Date", ""),
                # 특허 정보
                "patent_no": patent.get("Patent_No", ""),
                "patent_expire_date": patent.get("Patent_Expire_Date_Text", ""),
                "drug_substance_flag": patent.get("Drug_Substance_Flag", ""),
                "drug_product_flag": patent.get("Drug_Product_Flag", ""),
                "patent_use_code": patent.get("Patent_Use_Code", ""),
                "delist_flag": patent.get("Delist_Flag", ""),
                "submission_date": patent.get("Submission_Date", ""),
                # 메타
                "_ob_type": "patent_with_product",
                "_fetched_at": today,
            }
            records.append(record)

        # 독점권도 추가
        for excl in data["exclusivities"]:
            key = f"{excl.get('Appl_Type', '')}_{excl.get('Appl_No', '')}_{excl.get('Product_No', '')}"
            product = product_index.get(key, {})

            record = {
                "ingredient": product.get("Ingredient", ""),
                "trade_name": product.get("Trade_Name", ""),
                "applicant": product.get("Applicant_Full_Name", "")
                or product.get("Applicant", ""),
                "appl_type": excl.get("Appl_Type", ""),
                "appl_no": excl.get("Appl_No", ""),
                "product_no": excl.get("Product_No", ""),
                "strength": product.get("Strength", ""),
                "approval_date": product.get("Approval_Date", ""),
                # 독점권 정보
                "exclusivity_code": excl.get("Exclusivity_Code", ""),
                "exclusivity_date": excl.get("Exclusivity_Date", ""),
                # 메타
                "_ob_type": "exclusivity_with_product",
                "_fetched_at": today,
            }
            records.append(record)

        logger.info(
            f"Patent expiry: {len(records):,} records "
            f"(patents={len(data['patents']):,}, "
            f"exclusivities={len(data['exclusivities']):,})"
        )

        return records
