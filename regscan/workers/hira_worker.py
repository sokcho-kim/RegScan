"""HIRA 급여목록 수집 워커

공공데이터포털 건강보험심사평가원 의약품 급여·비급여 목록 및 상한금액 API를 통해
약물별 급여 상태, 성분코드, 상한가, 급여 기준을 수집하여 hira_reimbursements 테이블에 적재한다.

데이터 소스: apis.data.go.kr/B551182/pharmacyInfoService
인증: DATA_GO_KR_API_KEY (MFDS와 동일 키)

사용법:
    # CLI 단독 실행
    python -m regscan.workers.hira_worker

    # 코드에서 호출
    worker = HIRAReimbursementWorker()
    result = await worker.run()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from regscan.config.settings import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# HIRA API Client
# ═══════════════════════════════════════════════════════

class HIRADrugPriceClient:
    """건강보험심사평가원 의약품 급여목록 정보 API 클라이언트.

    API: 의약품제품 허가정보 중 급여·비급여 목록 + 상한금액
    Base URL: http://apis.data.go.kr/B551182/pharmacyInfoService
    """

    BASE_URL = "https://apis.data.go.kr/B551182/dgamtCrtrInfoService1.2"

    ENDPOINTS = {
        "price_list": "/getDgamtList",
    }

    MAX_RETRIES = 3
    RETRY_BACKOFF = 2.0
    REQUEST_INTERVAL = 0.2  # 초 (rate limit)

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.DATA_GO_KR_API_KEY
        if not self.api_key:
            raise ValueError("DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HIRADrugPriceClient:
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_price_list(
        self,
        item_name: str | None = None,
        entp_name: str | None = None,
        mds_cd: str | None = None,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> dict[str, Any]:
        """의약품 급여목록(약가기준정보) 조회.

        Parameters
        ----------
        item_name : 품목명 (itmNm)
        entp_name : 제조업체명 (mnfEntpNm)
        mds_cd : 제품코드 (mdsCd)
        page_no : 페이지 번호
        num_of_rows : 페이지당 건수 (최대 100)

        Returns
        -------
        API 응답 body dict (items, totalCount 포함)
        """
        params: dict[str, Any] = {
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
        }
        if item_name:
            params["itmNm"] = item_name
        if entp_name:
            params["mnfEntpNm"] = entp_name
        if mds_cd:
            params["mdsCd"] = mds_cd

        return await self._request("price_list", params)

    async def get_total_count(self) -> int:
        """전체 급여목록 건수 조회."""
        result = await self.get_price_list(num_of_rows=1)
        return result.get("totalCount", 0)

    async def _request(
        self, endpoint_key: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """API 호출 (재시도 + 에러 처리)."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        endpoint = self.ENDPOINTS[endpoint_key]
        # 공공데이터포털 키는 이미 URL-encoded 상태이므로 직접 URL에 삽입
        url = f"{self.BASE_URL}{endpoint}?serviceKey={self.api_key}"

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = await self._client.get(url, params=params)

                if resp.status_code == 429:
                    wait = self.RETRY_BACKOFF * attempt
                    logger.warning("HIRA API 429 rate limit, %s초 대기 (시도 %d/%d)",
                                   wait, attempt, self.MAX_RETRIES)
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # 공공데이터포털 에러 응답 체크
                header = data.get("response", {}).get("header", {})
                if header and header.get("resultCode") != "00":
                    msg = header.get("resultMsg", "Unknown API error")
                    raise RuntimeError(f"HIRA API error: {msg} (code={header.get('resultCode')})")

                body = data.get("response", {}).get("body", {})
                return body

            except httpx.HTTPStatusError as e:
                logger.error("HIRA API HTTP %d (시도 %d/%d): %s",
                             e.response.status_code, attempt, self.MAX_RETRIES, e)
                if attempt == self.MAX_RETRIES:
                    raise
                await asyncio.sleep(self.RETRY_BACKOFF * attempt)

            except (httpx.RequestError, RuntimeError) as e:
                logger.error("HIRA API 요청 실패 (시도 %d/%d): %s",
                             attempt, self.MAX_RETRIES, e)
                if attempt == self.MAX_RETRIES:
                    raise
                await asyncio.sleep(self.RETRY_BACKOFF * attempt)

        return {}


# ═══════════════════════════════════════════════════════
# Response Parser
# ═══════════════════════════════════════════════════════

def parse_price_item(item: dict[str, Any]) -> dict[str, Any]:
    """API 응답 항목을 정규화된 급여 정보로 변환.

    약가기준정보조회서비스 (dgamtCrtrInfoService1.2) 응답 필드:
    - gnlNmCd → ingredient_code (일반명코드)
    - itmNm → product_name (품목명)
    - mnfEntpNm → manufacturer (제조업체명)
    - payTpNm → pay_type (급여구분: 급여/비급여)
    - mxCprc → price_ceiling (상한금액)
    - mdsCd → mds_code (제품코드)
    - adtStaDd → apply_start_date (적용시작일)
    """
    # 급여 상태 판정
    pay_type = (item.get("payTpNm") or "").strip()
    if "급여" in pay_type and "비급여" not in pay_type:
        status = "reimbursed"
    elif "비급여" in pay_type:
        status = "not_covered"
    elif "삭제" in pay_type:
        status = "deleted"
    else:
        status = "not_found"

    # 상한금액 파싱
    price_raw = item.get("mxCprc") or ""
    try:
        price = float(str(price_raw).replace(",", "")) if price_raw else None
    except (ValueError, TypeError):
        price = None

    return {
        "ingredient_code": (item.get("gnlNmCd") or "").strip(),
        "product_name": (item.get("itmNm") or "").strip(),
        "manufacturer": (item.get("mnfEntpNm") or "").strip(),
        "status": status,
        "price_ceiling": price,
        "pay_type": pay_type,
        "mds_code": (item.get("mdsCd") or "").strip(),
        "apply_start_date": (item.get("adtStaDd") or "").strip(),
    }


# ═══════════════════════════════════════════════════════
# Worker
# ═══════════════════════════════════════════════════════

class HIRAReimbursementWorker:
    """HIRA 급여목록 수집 워커.

    실행 모드:
    1. full — 전체 급여목록 수집 (초기 구축 또는 정기 전체 갱신)
    2. by_inn — 특정 INN 목록에 대해서만 조회 (일일 브리핑용)
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def run(
        self,
        *,
        mode: str = "by_inn",
        target_inns: list[str] | None = None,
        max_pages: int = 500,
    ) -> dict[str, Any]:
        """워커 실행.

        Parameters
        ----------
        mode : "full" (전체 수집) 또는 "by_inn" (INN 기반 조회)
        target_inns : by_inn 모드 시 조회할 INN 목록. None이면 DB의 전체 drugs 조회.
        max_pages : full 모드 시 최대 페이지 수

        Returns
        -------
        실행 결과 dict (collected, updated, errors, duration 등)
        """
        start = datetime.now(timezone.utc)
        logger.info("[HIRA Worker] 시작 (mode=%s)", mode)

        if mode == "full":
            result = await self._collect_full(max_pages=max_pages)
        elif mode == "by_inn":
            inns = target_inns or await self._get_db_inns()
            result = await self._collect_by_inn(inns)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        result["mode"] = mode
        result["duration_sec"] = round(elapsed, 1)
        result["started_at"] = start.isoformat()

        logger.info(
            "[HIRA Worker] 완료: collected=%d, updated=%d, errors=%d (%.1f초)",
            result.get("collected", 0),
            result.get("updated", 0),
            result.get("errors", 0),
            elapsed,
        )
        return result

    async def _collect_full(self, max_pages: int = 500) -> dict[str, Any]:
        """전체 급여목록 페이지네이션 수집."""
        collected: list[dict] = []
        errors: list[str] = []

        async with HIRADrugPriceClient(api_key=self.api_key) as client:
            total = await client.get_total_count()
            logger.info("[HIRA Worker] 전체 건수: %d", total)

            for page in range(1, max_pages + 1):
                try:
                    body = await client.get_price_list(page_no=page, num_of_rows=100)
                    items = body.get("items", [])
                    if not items:
                        break

                    for raw in items:
                        parsed = parse_price_item(raw)
                        if parsed["ingredient_code"]:
                            collected.append(parsed)

                    if page % 50 == 0:
                        logger.info("[HIRA Worker] %d/%d 페이지 처리 (%d건)",
                                    page, max_pages, len(collected))

                except Exception as e:
                    errors.append(f"page {page}: {e}")
                    logger.warning("[HIRA Worker] 페이지 %d 실패: %s", page, e)

                await asyncio.sleep(HIRADrugPriceClient.REQUEST_INTERVAL)

        updated = await self._upsert_to_db(collected)

        return {
            "total_api": total,
            "collected": len(collected),
            "updated": updated,
            "errors": len(errors),
            "error_details": errors[:10],
        }

    async def _collect_by_inn(self, inns: list[str]) -> dict[str, Any]:
        """INN 목록 기반 개별 조회."""
        collected: list[dict] = []
        errors: list[str] = []
        not_found: list[str] = []

        async with HIRADrugPriceClient(api_key=self.api_key) as client:
            for inn in inns:
                try:
                    body = await client.get_price_list(item_name=inn, num_of_rows=10)
                    items = body.get("items", [])

                    if not items:
                        not_found.append(inn)
                        continue

                    for raw in items:
                        parsed = parse_price_item(raw)
                        parsed["query_inn"] = inn
                        collected.append(parsed)

                except Exception as e:
                    errors.append(f"{inn}: {e}")
                    logger.warning("[HIRA Worker] %s 조회 실패: %s", inn, e)

                await asyncio.sleep(HIRADrugPriceClient.REQUEST_INTERVAL)

        updated = await self._upsert_to_db(collected)

        return {
            "target_count": len(inns),
            "collected": len(collected),
            "updated": updated,
            "not_found": len(not_found),
            "errors": len(errors),
            "error_details": errors[:10],
        }

    async def _upsert_to_db(self, items: list[dict]) -> int:
        """수집된 급여 정보를 hira_reimbursements 테이블에 upsert."""
        from regscan.db.loader import DBLoader

        loader = DBLoader()
        updated = 0

        for item in items:
            try:
                count = await loader.upsert_hira_reimbursement(
                    ingredient_code=item["ingredient_code"],
                    status=item["status"],
                    price_ceiling=item.get("price_ceiling"),
                    criteria=item.get("pay_type", ""),
                    product_name=item.get("product_name", ""),
                    query_inn=item.get("query_inn", ""),
                )
                updated += count
            except Exception as e:
                logger.warning("[HIRA Worker] DB upsert 실패 (%s): %s",
                               item.get("ingredient_code"), e)

        return updated

    async def _get_db_inns(self) -> list[str]:
        """DB drugs 테이블에서 전체 INN 목록 조회."""
        from sqlalchemy import select
        from regscan.db.models import DrugDB
        from regscan.db.session import async_session_factory

        async with async_session_factory() as session:
            stmt = select(DrugDB.inn).where(DrugDB.inn.isnot(None))
            result = await session.execute(stmt)
            return [row[0] for row in result.fetchall()]


# ═══════════════════════════════════════════════════════
# CLI entrypoint
# ═══════════════════════════════════════════════════════

async def _main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="HIRA 급여목록 수집 워커")
    parser.add_argument("--mode", choices=["full", "by_inn"], default="by_inn",
                        help="수집 모드 (default: by_inn)")
    parser.add_argument("--max-pages", type=int, default=500,
                        help="full 모드 최대 페이지 수")
    parser.add_argument("--inn", nargs="*", help="by_inn 모드 시 조회할 INN 목록")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 저장 없이 API 응답만 확인")
    args = parser.parse_args()

    worker = HIRAReimbursementWorker()

    if args.dry_run:
        async with HIRADrugPriceClient() as client:
            body = await client.get_price_list(num_of_rows=3)
            items = body.get("items", [])
            print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
            print(f"\n총 건수: {body.get('totalCount', '?')}")
        return

    result = await worker.run(
        mode=args.mode,
        target_inns=args.inn,
        max_pages=args.max_pages,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
