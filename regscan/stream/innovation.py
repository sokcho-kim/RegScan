"""Stream 2: 혁신지표 (Innovation Indicators)

FDA Breakthrough/NME + EMA PRIME/Orphan/Conditional + PDUFA 일정.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from regscan.config import settings
from regscan.map.matcher import IngredientMatcher
from .base import BaseStream, StreamResult

logger = logging.getLogger(__name__)


class InnovationStream(BaseStream):
    """Stream 2: 혁신지표 수집"""

    def __init__(self):
        self._matcher = IngredientMatcher()

    @property
    def stream_name(self) -> str:
        return "innovation"

    async def collect(self) -> list[StreamResult]:
        """혁신지표 수집: NME + Breakthrough + PRIME + Orphan + Conditional + PDUFA"""
        drugs_by_inn: dict[str, dict[str, Any]] = {}
        signals: list[dict[str, Any]] = []
        errors: list[str] = []

        # 1) FDA NME (Type 1 New Molecular Entity)
        try:
            nme_count = await self._collect_fda_nme(drugs_by_inn, signals)
            logger.info("[Stream2] FDA NME: %d건", nme_count)
        except Exception as e:
            logger.warning("[Stream2] FDA NME 수집 실패: %s", e)
            errors.append(f"FDA NME: {e}")

        # 2) FDA Breakthrough (submission_class_code 5)
        try:
            bt_count = await self._collect_fda_breakthrough(drugs_by_inn, signals)
            logger.info("[Stream2] FDA Breakthrough: %d건", bt_count)
        except Exception as e:
            logger.warning("[Stream2] FDA Breakthrough 수집 실패: %s", e)
            errors.append(f"FDA Breakthrough: {e}")

        # 3) EMA PRIME
        try:
            prime_count = await self._collect_ema_prime(drugs_by_inn, signals)
            logger.info("[Stream2] EMA PRIME: %d건", prime_count)
        except Exception as e:
            logger.warning("[Stream2] EMA PRIME 수집 실패: %s", e)
            errors.append(f"EMA PRIME: {e}")

        # 4) EMA Orphan
        try:
            orphan_count = await self._collect_ema_orphan(drugs_by_inn, signals)
            logger.info("[Stream2] EMA Orphan: %d건", orphan_count)
        except Exception as e:
            logger.warning("[Stream2] EMA Orphan 수집 실패: %s", e)
            errors.append(f"EMA Orphan: {e}")

        # 5) EMA Conditional
        try:
            cond_count = await self._collect_ema_conditional(drugs_by_inn, signals)
            logger.info("[Stream2] EMA Conditional: %d건", cond_count)
        except Exception as e:
            logger.warning("[Stream2] EMA Conditional 수집 실패: %s", e)
            errors.append(f"EMA Conditional: {e}")

        # 6) PDUFA 일정
        try:
            pdufa_count = await self._collect_pdufa(signals)
            logger.info("[Stream2] PDUFA: %d건", pdufa_count)
        except Exception as e:
            logger.warning("[Stream2] PDUFA 조회 실패: %s", e)
            errors.append(f"PDUFA: {e}")

        drugs_list = list(drugs_by_inn.values())
        logger.info(
            "[Stream2] 혁신지표 완료: %d개 약물, %d개 시그널",
            len(drugs_list), len(signals),
        )

        return [StreamResult(
            stream_name=self.stream_name,
            drugs_found=drugs_list,
            signals=signals,
            errors=errors,
        )]

    async def _collect_fda_nme(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """FDA NME (submission_class_code=1, Type 1)"""
        from regscan.ingest.fda import FDAClient

        count = 0
        async with FDAClient() as client:
            # Type 1: New Molecular Entity
            for code in ["1", "TYPE 1"]:
                try:
                    response = await client.search_by_submission_class(code, limit=100)
                    for r in response.get("results", []):
                        inn = self._extract_inn_from_fda(r)
                        if not inn:
                            continue
                        norm = self._matcher.normalize(inn)
                        self._upsert_drug(drugs, norm, inn, r, designation="NME")
                        signals.append({
                            "type": "fda_nme",
                            "inn": inn,
                            "application_number": r.get("application_number", ""),
                        })
                        count += 1
                except Exception:
                    continue
        return count

    async def _collect_fda_breakthrough(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """FDA Breakthrough Therapy (submission_class_code=5)"""
        from regscan.ingest.fda import FDAClient

        count = 0
        async with FDAClient() as client:
            response = await client.search_by_submission_class("5", limit=100)
            for r in response.get("results", []):
                inn = self._extract_inn_from_fda(r)
                if not inn:
                    continue
                norm = self._matcher.normalize(inn)
                self._upsert_drug(drugs, norm, inn, r, designation="breakthrough")
                signals.append({
                    "type": "fda_breakthrough",
                    "inn": inn,
                    "application_number": r.get("application_number", ""),
                })
                count += 1
        return count

    async def _collect_ema_prime(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """EMA PRIME: medicines JSON에서 prime_priority_medicine 필터"""
        from regscan.ingest.ema import EMAClient

        count = 0
        async with EMAClient() as client:
            medicines = await client.fetch_medicines()

        for med in medicines:
            is_prime = str(
                med.get("primeMedicine", "") or
                med.get("prime_priority_medicine", "") or
                med.get("is_prime", "")
            ).lower() in ("yes", "true", "1")
            if not is_prime:
                continue

            inn = (med.get("activeSubstance", "") or
                   med.get("inn", "") or
                   med.get("active_substance", "") or
                   med.get("international_non_proprietary_name_common_name", "") or "")
            if not inn:
                continue

            norm = self._matcher.normalize(inn)
            self._upsert_drug(
                drugs, norm, inn, None,
                designation="PRIME",
                ema_data=med,
            )
            signals.append({"type": "ema_prime", "inn": inn})
            count += 1

        return count

    async def _collect_ema_orphan(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """EMA Orphan designations"""
        from regscan.ingest.ema import EMAClient

        count = 0
        async with EMAClient() as client:
            orphans = await client.fetch_orphan_designations()

        for item in orphans:
            inn = (item.get("activeSubstance", "") or
                   item.get("active_substance", "") or
                   item.get("inn", "") or
                   item.get("international_non_proprietary_name_common_name", "") or "")
            if not inn:
                continue

            norm = self._matcher.normalize(inn)
            self._upsert_drug(drugs, norm, inn, None, designation="orphan")
            signals.append({
                "type": "ema_orphan",
                "inn": inn,
                "condition": item.get("condition", "") or item.get("indication", ""),
            })
            count += 1

        return count

    async def _collect_ema_conditional(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """EMA Conditional approvals"""
        from regscan.ingest.ema import EMAClient

        count = 0
        async with EMAClient() as client:
            medicines = await client.fetch_medicines()

        for med in medicines:
            is_cond = str(
                med.get("conditionalApproval", "") or
                med.get("conditional_approval", "") or
                med.get("is_conditional", "")
            ).lower() in ("yes", "true", "1")
            if not is_cond:
                continue

            inn = (med.get("activeSubstance", "") or
                   med.get("inn", "") or
                   med.get("active_substance", "") or
                   med.get("international_non_proprietary_name_common_name", "") or "")
            if not inn:
                continue

            norm = self._matcher.normalize(inn)
            self._upsert_drug(
                drugs, norm, inn, None,
                designation="conditional",
                ema_data=med,
            )
            signals.append({"type": "ema_conditional", "inn": inn})
            count += 1

        return count

    async def _collect_pdufa(self, signals: list[dict]) -> int:
        """PDUFA 일정 조회 (DB에서)"""
        try:
            from regscan.db.database import get_async_session
            from regscan.db.models import PdufaDateDB
            from sqlalchemy import select

            async with get_async_session()() as session:
                stmt = (
                    select(PdufaDateDB)
                    .where(PdufaDateDB.status == "pending")
                    .where(PdufaDateDB.pdufa_date >= date.today())
                    .order_by(PdufaDateDB.pdufa_date)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                for row in rows:
                    days_until = (row.pdufa_date - date.today()).days
                    signals.append({
                        "type": "pdufa_upcoming",
                        "inn": row.inn,
                        "brand_name": row.brand_name,
                        "company": row.company,
                        "pdufa_date": row.pdufa_date.isoformat(),
                        "days_until": days_until,
                        "indication": row.indication,
                        "application_type": row.application_type,
                    })
                return len(rows)
        except Exception as e:
            logger.debug("PDUFA 조회 건너뜀 (테이블 미존재 가능): %s", e)
            return 0

    def _extract_inn_from_fda(self, result: dict) -> str:
        """FDA 결과에서 INN 추출"""
        openfda = result.get("openfda", {})
        inns = openfda.get("generic_name", [])
        if inns:
            return inns[0]
        substance = openfda.get("substance_name", [])
        if substance:
            return substance[0]
        return ""

    def _upsert_drug(
        self,
        drugs: dict[str, dict],
        norm: str,
        inn: str,
        fda_result: dict | None,
        designation: str = "",
        ema_data: dict | None = None,
    ) -> None:
        """drugs dict에 약물 추가/갱신"""
        if norm in drugs:
            existing = drugs[norm]
            if designation and designation not in existing.get("designations", []):
                existing.setdefault("designations", []).append(designation)
            if fda_result and not existing.get("fda_data"):
                existing["fda_data"] = fda_result
            if ema_data and not existing.get("ema_data"):
                existing["ema_data"] = ema_data
        else:
            drugs[norm] = {
                "inn": inn,
                "normalized_name": norm,
                "therapeutic_areas": [],
                "stream_sources": ["innovation"],
                "designations": [designation] if designation else [],
                "fda_data": fda_result,
                "ema_data": ema_data,
                "atc_code": "",
            }
