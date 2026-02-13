"""Stream 1: 치료영역 기반 약물 수집

5대 치료영역(항암, 희귀질환, 면역, 심혈관, 대사)별로
FDA pharm_class_epc + EMA therapeutic_area 필터를 사용하여 수집.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from regscan.config import settings
from regscan.map.matcher import IngredientMatcher
from .base import BaseStream, StreamResult

logger = logging.getLogger(__name__)


@dataclass
class AreaConfig:
    """개별 치료영역 설정"""
    name: str
    label_ko: str
    fda_pharm_classes: list[str]           # FDA openfda.pharm_class_epc 검색어
    ema_therapeutic_keywords: list[str]    # EMA therapeutic_area 문자열 매칭
    ct_conditions: list[str]              # ClinicalTrials.gov condition 검색어
    atc_prefixes: list[str]               # ATC 3단계 코드 prefix


class TherapeuticAreaConfig:
    """5대 치료영역 설정"""

    AREAS: dict[str, AreaConfig] = {
        "oncology": AreaConfig(
            name="oncology",
            label_ko="항암",
            fda_pharm_classes=[
                "Kinase Inhibitor",
                "Proteasome Inhibitor",
                "Programmed Death Receptor-1 Blocking Antibody",
                "Programmed Death Ligand-1 Blocker",
                "Vascular Endothelial Growth Factor Inhibitor",
                "HER2/neu Receptor Antagonist",
                "Poly(ADP-Ribose) Polymerase Inhibitor",
                "Epidermal Growth Factor Receptor Antagonist",
                "CD20-directed Cytolytic Antibody",
                "CD30-directed Immunoconjugate",
                "Hedgehog Pathway Inhibitor",
                "BCL-2 Inhibitor",
            ],
            ema_therapeutic_keywords=[
                "Oncology", "Neoplasm", "Cancer", "Leukaemia",
                "Lymphoma", "Melanoma", "Carcinoma", "Sarcoma",
                "Myeloma",
            ],
            ct_conditions=[
                "Cancer", "Neoplasm", "Carcinoma", "Leukemia",
                "Lymphoma", "Melanoma", "Sarcoma", "Myeloma",
                "Glioblastoma",
            ],
            atc_prefixes=["L01", "L02"],
        ),
        "rare_disease": AreaConfig(
            name="rare_disease",
            label_ko="희귀질환",
            fda_pharm_classes=[
                "Complement Inhibitor",
                "Antisense Oligonucleotide",
                "Cystic Fibrosis Transmembrane Conductance Regulator Corrector",
                "Cystic Fibrosis Transmembrane Conductance Regulator Potentiator",
            ],
            ema_therapeutic_keywords=[
                "Orphan", "Rare",
                "Cystic fibrosis", "Gaucher",
                "Fabry", "Pompe", "Huntington",
                "Spinal muscular atrophy", "Duchenne",
                "Haemophilia",
            ],
            ct_conditions=[
                "Rare Disease", "Orphan Disease",
                "Cystic Fibrosis", "Spinal Muscular Atrophy",
                "Duchenne Muscular Dystrophy", "Gaucher Disease",
                "Haemophilia", "Hemophilia",
            ],
            atc_prefixes=["A16"],  # ATC: Other alimentary tract (enzyme replacement etc.)
        ),
        "immunology": AreaConfig(
            name="immunology",
            label_ko="면역",
            fda_pharm_classes=[
                "Tumor Necrosis Factor Blocker",
                "Interleukin-12 Antagonist",
                "Interleukin-17A Antagonist",
                "Interleukin-23 Antagonist",
                "Interleukin-4 Receptor alpha Antagonist",
                "Janus Kinase Inhibitor",
                "Calcineurin Inhibitor Immunosuppressant",
                "Sphingosine 1-Phosphate Receptor Modulator",
                "CD20-directed Cytolytic Antibody",
                "Integrin Receptor Antagonist",
            ],
            ema_therapeutic_keywords=[
                "Immunology", "Autoimmune",
                "Rheumatoid", "Psoriasis", "Crohn",
                "Ulcerative colitis", "Multiple sclerosis",
                "Lupus", "Atopic dermatitis",
            ],
            ct_conditions=[
                "Rheumatoid Arthritis", "Psoriasis",
                "Crohn Disease", "Ulcerative Colitis",
                "Multiple Sclerosis", "Atopic Dermatitis",
                "Systemic Lupus Erythematosus",
            ],
            atc_prefixes=["L04"],
        ),
        "cardiovascular": AreaConfig(
            name="cardiovascular",
            label_ko="심혈관",
            fda_pharm_classes=[
                "HMG-CoA Reductase Inhibitor",
                "Angiotensin 2 Receptor Blocker",
                "Sodium-Glucose Cotransporter 2 Inhibitor",
                "Factor Xa Inhibitor",
                "P2Y12 Platelet Inhibitor",
                "Soluble Guanylate Cyclase Stimulator",
                "Neprilysin Inhibitor",
                "Endothelin Receptor Antagonist",
            ],
            ema_therapeutic_keywords=[
                "Cardiovascular", "Cardiac", "Heart failure",
                "Hypertension", "Atherosclerosis",
                "Thrombosis", "Pulmonary arterial hypertension",
                "Atrial fibrillation",
            ],
            ct_conditions=[
                "Heart Failure", "Cardiovascular Disease",
                "Atrial Fibrillation", "Pulmonary Arterial Hypertension",
                "Coronary Artery Disease", "Acute Coronary Syndrome",
                "Deep Vein Thrombosis",
            ],
            atc_prefixes=["C01", "C02", "C03", "C07", "C08", "C09", "C10"],
        ),
        "metabolic": AreaConfig(
            name="metabolic",
            label_ko="대사/당뇨",
            fda_pharm_classes=[
                "GLP-1 Receptor Agonist",
                "Sodium-Glucose Cotransporter 2 Inhibitor",
                "Dipeptidyl Peptidase 4 Inhibitor",
                "Glucose-dependent Insulinotropic Polypeptide Receptor Agonist",
                "Amylin Analog",
            ],
            ema_therapeutic_keywords=[
                "Diabetes", "Metabolic", "Obesity",
                "Lipodystrophy", "Growth hormone",
                "Thyroid", "Adrenal",
            ],
            ct_conditions=[
                "Diabetes Mellitus", "Type 2 Diabetes",
                "Type 1 Diabetes", "Obesity",
                "Non-alcoholic Steatohepatitis", "NASH",
                "Metabolic Syndrome",
            ],
            atc_prefixes=["A10", "H01", "H02", "H03"],
        ),
    }

    @classmethod
    def get_area(cls, name: str) -> AreaConfig | None:
        return cls.AREAS.get(name)

    @classmethod
    def enabled_areas(cls) -> list[AreaConfig]:
        """settings.THERAPEUTIC_AREAS에 설정된 영역만 반환"""
        enabled = [a.strip() for a in settings.THERAPEUTIC_AREAS.split(",")]
        return [cls.AREAS[k] for k in enabled if k in cls.AREAS]


class TherapeuticAreaStream(BaseStream):
    """Stream 1: 치료영역 기반 약물 수집"""

    def __init__(self, areas: list[str] | None = None):
        """
        Args:
            areas: 수집할 치료영역 목록. None이면 settings에서 읽음.
        """
        if areas:
            self._areas = [
                TherapeuticAreaConfig.AREAS[a]
                for a in areas
                if a in TherapeuticAreaConfig.AREAS
            ]
        else:
            self._areas = TherapeuticAreaConfig.enabled_areas()
        self._matcher = IngredientMatcher()

    @property
    def stream_name(self) -> str:
        return "therapeutic_area"

    async def collect(self) -> list[StreamResult]:
        """영역별로 FDA + EMA 데이터 수집"""
        results: list[StreamResult] = []
        for area in self._areas:
            try:
                result = await self._collect_area(area)
                results.append(result)
            except Exception as e:
                logger.error("치료영역 '%s' 수집 실패: %s", area.name, e)
                results.append(StreamResult(
                    stream_name=self.stream_name,
                    sub_category=area.name,
                    errors=[str(e)],
                ))
        return results

    async def _collect_area(self, area: AreaConfig) -> StreamResult:
        """단일 치료영역 수집"""
        logger.info("[Stream1] 치료영역 '%s' 수집 시작...", area.label_ko)

        drugs_by_inn: dict[str, dict[str, Any]] = {}
        errors: list[str] = []

        # 1) FDA pharm_class_epc 검색
        try:
            fda_drugs = await self._search_fda_pharm_class(area)
            for drug in fda_drugs:
                inn = drug.get("inn", "")
                if not inn:
                    continue
                norm = self._matcher.normalize(inn)
                if norm in drugs_by_inn:
                    drugs_by_inn[norm]["sources"].append("fda")
                    drugs_by_inn[norm]["fda_data"] = drug.get("fda_data")
                else:
                    drugs_by_inn[norm] = {
                        "inn": inn,
                        "normalized_name": norm,
                        "therapeutic_areas": [area.name],
                        "sources": ["fda"],
                        "fda_data": drug.get("fda_data"),
                        "ema_data": None,
                        "atc_code": drug.get("atc_code", ""),
                        "stream_sources": ["therapeutic_area"],
                    }
            logger.info("  FDA pharm_class: %d개 약물", len(fda_drugs))
        except Exception as e:
            logger.warning("  FDA 검색 실패 (%s): %s", area.name, e)
            errors.append(f"FDA pharm_class search failed: {e}")

        # 2) EMA therapeutic_area 필터
        try:
            ema_drugs = await self._filter_ema_therapeutic(area)
            for drug in ema_drugs:
                inn = drug.get("inn", "")
                if not inn:
                    continue
                norm = self._matcher.normalize(inn)
                if norm in drugs_by_inn:
                    if "ema" not in drugs_by_inn[norm]["sources"]:
                        drugs_by_inn[norm]["sources"].append("ema")
                    drugs_by_inn[norm]["ema_data"] = drug.get("ema_data")
                    if not drugs_by_inn[norm].get("atc_code") and drug.get("atc_code"):
                        drugs_by_inn[norm]["atc_code"] = drug["atc_code"]
                else:
                    drugs_by_inn[norm] = {
                        "inn": inn,
                        "normalized_name": norm,
                        "therapeutic_areas": [area.name],
                        "sources": ["ema"],
                        "fda_data": None,
                        "ema_data": drug.get("ema_data"),
                        "atc_code": drug.get("atc_code", ""),
                        "stream_sources": ["therapeutic_area"],
                    }
            logger.info("  EMA therapeutic_area: %d개 약물", len(ema_drugs))
        except Exception as e:
            logger.warning("  EMA 필터 실패 (%s): %s", area.name, e)
            errors.append(f"EMA therapeutic_area filter failed: {e}")

        # 3) FDA 교차참조 보강 — EMA에서만 수집된 약물을 FDA generic_name으로 검색
        try:
            fda_xref_count = await self._enrich_with_fda_crossref(drugs_by_inn)
            if fda_xref_count > 0:
                logger.info("  FDA 교차참조: %d개 보강", fda_xref_count)
        except Exception as e:
            logger.debug("  FDA 교차참조 실패: %s", e)

        # 4) MFDS 보강 (Stream 1에서 수집된 INN으로 MFDS API 조회)
        if settings.ENABLE_MFDS_ENRICHMENT:
            try:
                mfds_count = await self._enrich_with_mfds(drugs_by_inn)
                if mfds_count > 0:
                    logger.info("  MFDS 매칭: %d개", mfds_count)
            except Exception as e:
                logger.debug("  MFDS 보강 실패: %s", e)

        # 5) ATC 기반 그룹핑 (같은 ATC 3단계 약물 태깅)
        atc_groups = self._group_by_atc(drugs_by_inn, area.atc_prefixes)

        drugs_list = list(drugs_by_inn.values())
        for d in drugs_list:
            norm = d["normalized_name"]
            d["atc_group_count"] = atc_groups.get(norm, 0)

        logger.info(
            "[Stream1] '%s' 완료: %d개 약물 (FDA+EMA 병합)",
            area.label_ko, len(drugs_list),
        )

        return StreamResult(
            stream_name=self.stream_name,
            sub_category=area.name,
            drugs_found=drugs_list,
            errors=errors,
        )

    async def _search_fda_pharm_class(self, area: AreaConfig) -> list[dict]:
        """FDA pharm_class_epc로 약물 검색"""
        from regscan.ingest.fda import FDAClient

        all_drugs: list[dict] = []
        seen_inns: set[str] = set()

        async with FDAClient() as client:
            for term in area.fda_pharm_classes:
                try:
                    response = await client.search_by_pharm_class(term, limit=100)
                    results = response.get("results", [])
                    for r in results:
                        openfda = r.get("openfda", {})
                        inns = openfda.get("generic_name", [])
                        inn = inns[0] if inns else ""
                        if not inn:
                            substance = openfda.get("substance_name", [])
                            inn = substance[0] if substance else ""
                        if not inn:
                            continue

                        norm = self._matcher.normalize(inn)
                        if norm in seen_inns:
                            continue
                        seen_inns.add(norm)

                        atc = openfda.get("pharm_class_epc", [])
                        brand_names = openfda.get("brand_name", [])

                        all_drugs.append({
                            "inn": inn,
                            "atc_code": "",
                            "fda_data": {
                                "generic_name": inn,
                                "brand_name": brand_names[0] if brand_names else "",
                                "pharm_class_epc": atc,
                                "application_number": r.get("application_number", ""),
                                "submissions": r.get("submissions", []),
                                "raw": r,
                            },
                        })
                except Exception as e:
                    logger.debug("FDA pharm_class '%s' 검색 실패: %s", term, e)
                    continue

        return all_drugs

    async def _filter_ema_therapeutic(self, area: AreaConfig) -> list[dict]:
        """EMA medicines JSON에서 therapeutic_area 키워드 필터"""
        from regscan.ingest.ema import EMAClient

        all_drugs: list[dict] = []
        seen_inns: set[str] = set()
        keywords_lower = [k.lower() for k in area.ema_therapeutic_keywords]

        async with EMAClient() as client:
            medicines = await client.fetch_medicines()

        for med in medicines:
            # EMA JSON: 두 가지 형식 지원 (camelCase + snake_case)
            ta = (med.get("therapeuticArea", "") or
                  med.get("therapeutic_area", "") or
                  med.get("therapeutic_area_mesh", "") or "")
            # pharmacotherapeutic_group_human도 폴백으로 확인
            ptg = med.get("pharmacotherapeutic_group_human", "") or ""
            combined_ta = f"{ta} {ptg}".lower()

            if not any(kw in combined_ta for kw in keywords_lower):
                continue

            inn = (med.get("activeSubstance", "") or
                   med.get("inn", "") or
                   med.get("active_substance", "") or
                   med.get("international_non_proprietary_name_common_name", "") or "")
            if not inn:
                continue

            norm = self._matcher.normalize(inn)
            if norm in seen_inns:
                continue
            seen_inns.add(norm)

            atc_code = (med.get("atcCode", "") or
                        med.get("atc_code", "") or
                        med.get("atc_code_human", "") or "")

            med_name = (med.get("medicineName", "") or
                        med.get("name", "") or
                        med.get("name_of_medicine", "") or "")

            all_drugs.append({
                "inn": inn,
                "atc_code": atc_code,
                "ema_data": {
                    "inn": inn,
                    "active_substance": inn,
                    "name": med_name,
                    "therapeutic_area": ta,
                    "atc_code": atc_code,
                    "marketing_authorisation_date": (
                        med.get("marketingAuthorisationDate", "") or
                        med.get("marketing_authorisation_date", "")
                    ),
                    "medicine_status": med.get("authorisationStatus", "") or med.get("medicine_status", ""),
                    "is_orphan": _bool_field(med, "orphanMedicine", "is_orphan", "orphan_medicine"),
                    "is_prime": _bool_field(med, "primeMedicine", "is_prime", "prime_priority_medicine"),
                    "is_conditional": _bool_field(med, "conditionalApproval", "is_conditional", "conditional_approval"),
                    "is_accelerated": _bool_field(med, "acceleratedAssessment", "is_accelerated", "accelerated_assessment"),
                    "ema_product_number": med.get("emaProductNumber", "") or med.get("ema_product_number", ""),
                    "therapeutic_indication": (
                        med.get("therapeuticIndication", "") or
                        med.get("therapeutic_indication", "") or ""
                    ),
                    "raw": med,
                },
            })

        return all_drugs

    async def _enrich_with_fda_crossref(self, drugs_by_inn: dict[str, dict]) -> int:
        """EMA에서만 수집된 약물을 FDA generic_name/substance_name으로 교차검색

        pharm_class_epc 검색에서 누락된 약물(CAR-T, 이중특이항체 등)을 보강.

        Args:
            drugs_by_inn: 정규화된 INN → drug dict

        Returns:
            FDA 교차참조로 보강된 약물 수
        """
        import asyncio as _aio
        from regscan.ingest.fda import FDAClient

        # EMA 있고 FDA 없는 약물 필터
        targets = [
            (norm, drug) for norm, drug in drugs_by_inn.items()
            if drug.get("ema_data") and not drug.get("fda_data")
        ]
        if not targets:
            return 0

        count = 0
        async with FDAClient() as client:
            for norm, drug in targets:
                inn = drug.get("inn", "")
                if not inn or len(inn) < 3:
                    continue

                fda_result = None
                try:
                    # 1차: generic_name 검색
                    response = await client.search_by_generic_name(inn, limit=3)
                    results = response.get("results", [])
                    if results:
                        fda_result = results[0]
                except Exception:
                    pass

                if not fda_result:
                    try:
                        # 2차: substance_name 검색 (대문자 변환)
                        response = await client.search_by_substance_name(
                            inn.upper(), limit=3
                        )
                        results = response.get("results", [])
                        if results:
                            fda_result = results[0]
                    except Exception:
                        pass

                if fda_result:
                    openfda = fda_result.get("openfda", {})
                    generic_names = openfda.get("generic_name", [])
                    brand_names = openfda.get("brand_name", [])
                    submissions = fda_result.get("submissions", [])

                    # 최신 승인 submission 찾기
                    submission_status_date = ""
                    for sub in submissions:
                        if sub.get("submission_status") == "AP":
                            sub_date = sub.get("submission_status_date", "")
                            if sub_date > submission_status_date:
                                submission_status_date = sub_date

                    drug["fda_data"] = {
                        "generic_name": generic_names[0] if generic_names else inn,
                        "brand_name": brand_names[0] if brand_names else "",
                        "application_number": fda_result.get("application_number", ""),
                        "submission_status_date": submission_status_date,
                        "submission_status": "AP" if submission_status_date else "",
                        "submissions": submissions,
                        "pharm_class_epc": openfda.get("pharm_class_epc", []),
                        "raw": fda_result,
                    }
                    if "fda" not in drug.get("sources", []):
                        drug.setdefault("sources", []).append("fda")
                    count += 1

                # Rate limit (0.3초 — FDA API 제한 준수)
                await _aio.sleep(0.3)

        return count

    async def _enrich_with_mfds(self, drugs_by_inn: dict[str, dict]) -> int:
        """Stream 1에서 수집된 INN으로 MFDS API 조회하여 데이터 보강

        Args:
            drugs_by_inn: 정규화된 INN → drug dict

        Returns:
            MFDS 매칭된 약물 수
        """
        import asyncio as _aio
        from regscan.ingest.mfds import MFDSClient
        from regscan.parse.mfds_parser import MFDSPermitParser

        count = 0
        parser = MFDSPermitParser()

        async with MFDSClient() as client:
            for norm, drug in drugs_by_inn.items():
                inn = drug.get("inn", "")
                if not inn or len(inn) < 3:
                    continue

                try:
                    response = await client.search_permits(item_name=inn, num_of_rows=5)
                    items = response.get("body", {}).get("items", [])
                    if items:
                        parsed = parser.parse_many(items)
                        if parsed:
                            drug["mfds_data"] = parsed[0]
                            count += 1
                except Exception:
                    pass

                # Rate limit (0.2초 간격)
                await _aio.sleep(0.2)

        return count

    def _group_by_atc(
        self,
        drugs: dict[str, dict],
        atc_prefixes: list[str],
    ) -> dict[str, int]:
        """ATC 3단계 기준 그룹 크기 계산"""
        atc_groups: dict[str, list[str]] = {}  # atc_3 -> [norm_inn, ...]
        for norm, d in drugs.items():
            atc = d.get("atc_code", "")
            if len(atc) >= 4:
                atc_3 = atc[:4]
                atc_groups.setdefault(atc_3, []).append(norm)

        # 각 약물에 같은 그룹 내 약물 수 반환
        result: dict[str, int] = {}
        for atc_3, members in atc_groups.items():
            for norm in members:
                result[norm] = len(members)
        return result


def _bool_field(data: dict, *keys: str) -> bool:
    """여러 키 이름으로 bool 값 추출"""
    for key in keys:
        val = data.get(key)
        if val is not None:
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ("yes", "true", "1")
    return False
