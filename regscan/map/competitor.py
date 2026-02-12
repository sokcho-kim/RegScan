"""제네릭/바이오시밀러 경쟁약물 매핑

Orange Book TE 코드 기반 제네릭 매핑 + EMA 바이오시밀러 + ATC 3단계 그룹핑.
"""

from __future__ import annotations

import logging
from typing import Any

from regscan.map.matcher import IngredientMatcher

logger = logging.getLogger(__name__)


class CompetitorMapper:
    """제네릭/바이오시밀러/동일 ATC 약물 매핑"""

    def __init__(self):
        self._matcher = IngredientMatcher()
        self._ema_cache: list[dict] | None = None
        self._fda_cache: dict[str, list[dict]] = {}  # atc_prefix -> results

    async def find_same_atc(
        self,
        atc_code: str,
        exclude_inn: str = "",
    ) -> list[dict[str, Any]]:
        """같은 ATC 3단계 코드를 가진 약물 목록

        Args:
            atc_code: ATC 코드 (최소 4자리)
            exclude_inn: 제외할 INN

        Returns:
            [{inn, atc_code, source}]
        """
        if len(atc_code) < 4:
            return []

        atc_3 = atc_code[:4]
        exclude_norm = self._matcher.normalize(exclude_inn) if exclude_inn else ""

        results: list[dict] = []
        ema_meds = await self._get_ema_medicines()

        for med in ema_meds:
            med_atc = (med.get("atcCode", "") or med.get("atc_code", "") or "")
            if not med_atc or not med_atc.startswith(atc_3):
                continue

            inn = (med.get("activeSubstance", "") or
                   med.get("inn", "") or
                   med.get("active_substance", "") or "")
            if not inn:
                continue

            norm = self._matcher.normalize(inn)
            if norm == exclude_norm:
                continue

            results.append({
                "inn": inn,
                "atc_code": med_atc,
                "source": "ema",
                "relationship_type": "same_atc",
            })

        # 중복 제거
        seen = set()
        unique = []
        for r in results:
            norm = self._matcher.normalize(r["inn"])
            if norm not in seen:
                seen.add(norm)
                unique.append(r)

        return unique

    async def find_generics(self, inn: str) -> list[dict[str, Any]]:
        """openFDA Orange Book 기반 제네릭 약물 조회

        Args:
            inn: 오리지널 약물 INN

        Returns:
            [{inn, te_code, source}]
        """
        from regscan.ingest.fda import FDAClient

        results: list[dict] = []
        try:
            async with FDAClient() as client:
                response = await client.search_by_pharm_class(inn, limit=50)
                for r in response.get("results", []):
                    openfda = r.get("openfda", {})
                    generic_names = openfda.get("generic_name", [])
                    for gn in generic_names:
                        norm_gn = self._matcher.normalize(gn)
                        norm_inn = self._matcher.normalize(inn)
                        if norm_gn != norm_inn:
                            results.append({
                                "inn": gn,
                                "te_code": "",
                                "source": "fda_openfda",
                                "relationship_type": "generic",
                            })
        except Exception as e:
            logger.debug("제네릭 조회 실패 (%s): %s", inn, e)

        return results

    async def find_biosimilars(self, inn: str) -> list[dict[str, Any]]:
        """EMA biosimilar 필드 기반 바이오시밀러 조회

        Args:
            inn: 참조의약품 INN

        Returns:
            [{inn, source}]
        """
        norm_inn = self._matcher.normalize(inn)
        results: list[dict] = []

        ema_meds = await self._get_ema_medicines()
        for med in ema_meds:
            is_biosimilar = (
                str(med.get("biosimilar", "")).lower() in ("yes", "true", "1") or
                str(med.get("isBiosimilar", "")).lower() in ("yes", "true", "1")
            )
            if not is_biosimilar:
                continue

            active = (med.get("activeSubstance", "") or
                      med.get("inn", "") or
                      med.get("active_substance", "") or "")
            norm_active = self._matcher.normalize(active)

            # 바이오시밀러의 INN이 참조제품과 같거나 유사한 경우
            if norm_active == norm_inn or norm_inn in norm_active:
                name = med.get("medicineName", "") or med.get("name", "")
                results.append({
                    "inn": active,
                    "brand_name": name,
                    "source": "ema",
                    "relationship_type": "biosimilar",
                })

        return results

    async def _get_ema_medicines(self) -> list[dict]:
        """EMA medicines JSON 캐시"""
        if self._ema_cache is None:
            from regscan.ingest.ema import EMAClient
            async with EMAClient() as client:
                self._ema_cache = await client.fetch_medicines()
        return self._ema_cache
