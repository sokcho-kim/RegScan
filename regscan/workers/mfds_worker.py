"""MFDS 허가정보 증분 수집 워커

기존 MFDSClient를 활용하여 최근 N일간 변경된 허가정보만 수집(delta collection).
전체 28만건을 매일 수집하는 것이 아니라, 날짜 필터로 변경분만 가져온다.

데이터 소스: apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07
인증: DATA_GO_KR_API_KEY

사용법:
    # CLI 단독 실행
    python -m regscan.workers.mfds_worker

    # 코드에서 호출
    worker = MFDSPermitWorker()
    result = await worker.run()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from regscan.config.settings import settings
from regscan.ingest.mfds import MFDSClient
from regscan.parse.mfds_parser import MFDSPermitParser

logger = logging.getLogger(__name__)


class MFDSPermitWorker:
    """MFDS 허가정보 증분 수집 워커.

    실행 모드:
    1. delta — 최근 N일간 변경된 허가정보만 수집 (기본)
    2. full — 전체 수집 (초기 구축용, max_items 제한 가능)
    3. by_inn — 특정 INN 목록 조회 (브리핑 enrichment용)
    """

    REQUEST_INTERVAL = 0.2  # 초

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.DATA_GO_KR_API_KEY
        self.parser = MFDSPermitParser()

    async def run(
        self,
        *,
        mode: str = "delta",
        days_back: int = 7,
        target_inns: list[str] | None = None,
        max_items: int = 10000,
    ) -> dict[str, Any]:
        """워커 실행.

        Parameters
        ----------
        mode : "delta" (증분), "full" (전체), "by_inn" (INN 기반)
        days_back : delta 모드 시 조회 기간 (일)
        target_inns : by_inn 모드 시 INN 목록. None이면 DB에서 조회.
        max_items : full 모드 시 최대 수집 건수

        Returns
        -------
        실행 결과 dict
        """
        start = datetime.now(timezone.utc)
        logger.info("[MFDS Worker] 시작 (mode=%s, days_back=%d)", mode, days_back)

        if mode == "delta":
            result = await self._collect_delta(days_back=days_back)
        elif mode == "full":
            result = await self._collect_full(max_items=max_items)
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
            "[MFDS Worker] 완료: collected=%d, upserted=%d, errors=%d (%.1f초)",
            result.get("collected", 0),
            result.get("upserted", 0),
            result.get("errors", 0),
            elapsed,
        )
        return result

    async def _collect_delta(self, days_back: int = 7) -> dict[str, Any]:
        """최근 N일간 허가/변경된 의약품만 수집.

        MFDS API에 날짜 필터 파라미터가 없으므로,
        전체 목록을 최신순으로 가져오면서 허가일(ITEM_PERMIT_DATE)이
        기준일 이전이면 중단하는 방식으로 delta를 구현한다.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_str = cutoff.strftime("%Y%m%d")
        collected: list[dict] = []
        errors: list[str] = []
        stop = False

        async with MFDSClient() as client:
            page = 1
            while not stop and page <= 200:  # 안전장치
                try:
                    resp = await client.search_permits(
                        page_no=page, num_of_rows=100
                    )
                    items = resp.get("body", {}).get("items", [])
                    if not items:
                        break

                    for raw in items:
                        permit_date = str(raw.get("ITEM_PERMIT_DATE") or "")[:8]
                        # 허가일이 cutoff 이전이면 → 더 이상 최근 데이터 없음
                        if permit_date and permit_date < cutoff_str:
                            stop = True
                            break

                        parsed_list = self.parser.parse_many([raw])
                        if parsed_list:
                            collected.append(parsed_list[0])

                    page += 1

                except Exception as e:
                    errors.append(f"page {page}: {e}")
                    logger.warning("[MFDS Worker] 페이지 %d 실패: %s", page, e)
                    page += 1

                await asyncio.sleep(self.REQUEST_INTERVAL)

        upserted = await self._upsert_to_db(collected)

        return {
            "days_back": days_back,
            "cutoff": cutoff_str,
            "pages_scanned": page - 1,
            "collected": len(collected),
            "upserted": upserted,
            "errors": len(errors),
            "error_details": errors[:10],
        }

    async def _collect_full(self, max_items: int = 10000) -> dict[str, Any]:
        """전체 MFDS 허가정보 수집 (초기 구축용)."""
        collected: list[dict] = []
        errors: list[str] = []
        max_pages = (max_items // 100) + 1

        async with MFDSClient() as client:
            total = await client.get_total_count()
            logger.info("[MFDS Worker] 전체 건수: %d (max_items=%d)", total, max_items)

            for page in range(1, max_pages + 1):
                try:
                    resp = await client.search_permits(
                        page_no=page, num_of_rows=100
                    )
                    items = resp.get("body", {}).get("items", [])
                    if not items:
                        break

                    parsed_list = self.parser.parse_many(items)
                    collected.extend(parsed_list)

                    if len(collected) >= max_items:
                        collected = collected[:max_items]
                        break

                    if page % 50 == 0:
                        logger.info("[MFDS Worker] %d/%d 페이지 (%d건)",
                                    page, max_pages, len(collected))

                except Exception as e:
                    errors.append(f"page {page}: {e}")
                    logger.warning("[MFDS Worker] 페이지 %d 실패: %s", page, e)

                await asyncio.sleep(self.REQUEST_INTERVAL)

        upserted = await self._upsert_to_db(collected)

        return {
            "total_api": total,
            "collected": len(collected),
            "upserted": upserted,
            "errors": len(errors),
            "error_details": errors[:10],
        }

    async def _collect_by_inn(self, inns: list[str]) -> dict[str, Any]:
        """INN 목록 기반 개별 조회."""
        collected: list[dict] = []
        errors: list[str] = []
        not_found: list[str] = []

        async with MFDSClient() as client:
            for inn in inns:
                try:
                    resp = await client.search_permits(
                        item_name=inn, num_of_rows=5
                    )
                    items = resp.get("body", {}).get("items", [])

                    if not items:
                        not_found.append(inn)
                        continue

                    parsed_list = self.parser.parse_many(items)
                    for p in parsed_list:
                        p["query_inn"] = inn
                    collected.extend(parsed_list)

                except Exception as e:
                    errors.append(f"{inn}: {e}")
                    logger.warning("[MFDS Worker] %s 조회 실패: %s", inn, e)

                await asyncio.sleep(self.REQUEST_INTERVAL)

        upserted = await self._upsert_to_db(collected)

        return {
            "target_count": len(inns),
            "collected": len(collected),
            "upserted": upserted,
            "not_found": len(not_found),
            "errors": len(errors),
            "error_details": errors[:10],
        }

    async def _upsert_to_db(self, items: list[dict]) -> int:
        """수집된 MFDS 허가정보를 regulatory_events 테이블에 upsert."""
        from regscan.db.loader import DBLoader

        loader = DBLoader()
        upserted = 0

        for item in items:
            try:
                count = await loader.upsert_mfds_permit(
                    inn=item.get("inn") or item.get("item_name", ""),
                    approval_status=item.get("approval_status", ""),
                    approval_date=item.get("approval_date"),
                    brand_name=item.get("brand_name") or item.get("product_name", ""),
                    raw_data=item,
                )
                upserted += count
            except Exception as e:
                logger.warning("[MFDS Worker] DB upsert 실패 (%s): %s",
                               item.get("inn", "?"), e)

        return upserted

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

    parser = argparse.ArgumentParser(description="MFDS 허가정보 수집 워커")
    parser.add_argument("--mode", choices=["delta", "full", "by_inn"], default="delta",
                        help="수집 모드 (default: delta)")
    parser.add_argument("--days-back", type=int, default=7,
                        help="delta 모드 조회 기간 (일)")
    parser.add_argument("--max-items", type=int, default=10000,
                        help="full 모드 최대 수집 건수")
    parser.add_argument("--inn", nargs="*", help="by_inn 모드 시 INN 목록")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 저장 없이 API 응답만 확인")
    args = parser.parse_args()

    if args.dry_run:
        async with MFDSClient() as client:
            resp = await client.search_permits(num_of_rows=3)
            items = resp.get("body", {}).get("items", [])
            print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
            print(f"\n총 건수: {resp.get('body', {}).get('totalCount', '?')}")
        return

    worker = MFDSPermitWorker()
    result = await worker.run(
        mode=args.mode,
        days_back=args.days_back,
        target_inns=args.inn,
        max_items=args.max_items,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
