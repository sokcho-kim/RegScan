"""Stream 3: 외부시그널 (External Signals)

ClinicalTrials.gov Phase 3 + medRxiv 수집.
Stream 1/2의 INN 교차 참조.
"""

from __future__ import annotations

import logging
from typing import Any

from regscan.config import settings
from regscan.map.matcher import IngredientMatcher
from regscan.stream.base import BaseStream, StreamResult
from regscan.stream.therapeutic import TherapeuticAreaConfig

logger = logging.getLogger(__name__)


class ExternalSignalStream(BaseStream):
    """Stream 3: 외부시그널 수집"""

    def __init__(
        self,
        target_inns: list[str] | None = None,
        therapeutic_areas: list[str] | None = None,
    ):
        """
        Args:
            target_inns: Stream 1/2 약물 INN 목록 (교차 참조용)
            therapeutic_areas: CT.gov 검색용 치료영역
        """
        self._target_inns = set(target_inns or [])
        self._therapeutic_areas = therapeutic_areas
        self._matcher = IngredientMatcher()

    @property
    def stream_name(self) -> str:
        return "external"

    async def collect(self) -> list[StreamResult]:
        """CT.gov + medRxiv 수집"""
        drugs_by_inn: dict[str, dict[str, Any]] = {}
        signals: list[dict[str, Any]] = []
        errors: list[str] = []

        # 1) ClinicalTrials.gov Phase 3
        try:
            ct_count = await self._collect_ctgov(drugs_by_inn, signals)
            logger.info("[Stream3] CT.gov Phase 3: %d건", ct_count)
        except Exception as e:
            logger.warning("[Stream3] CT.gov 수집 실패: %s", e)
            errors.append(f"CT.gov: {e}")

        # 2) medRxiv 복합 키워드
        try:
            mr_count = await self._collect_medrxiv(signals)
            logger.info("[Stream3] medRxiv: %d건", mr_count)
        except Exception as e:
            logger.warning("[Stream3] medRxiv 수집 실패: %s", e)
            errors.append(f"medRxiv: {e}")

        # 3) 교차 참조 (CT.gov INN이 Stream 1/2에도 있으면 강조)
        cross_ref_count = 0
        target_norms = self._target_inns_normalized()
        for norm, drug in drugs_by_inn.items():
            if norm in target_norms:
                drug["cross_referenced"] = True
                cross_ref_count += 1
            else:
                # fuzzy_match fallback
                fuzzy_hit = self._matcher.fuzzy_match(norm, target_norms)
                if fuzzy_hit:
                    drug["cross_referenced"] = True
                    drug["fuzzy_matched_to"] = fuzzy_hit
                    cross_ref_count += 1

        drugs_list = list(drugs_by_inn.values())
        logger.info(
            "[Stream3] 외부시그널 완료: %d개 약물, %d개 시그널 (교차참조 %d건)",
            len(drugs_list), len(signals), cross_ref_count,
        )

        return [StreamResult(
            stream_name=self.stream_name,
            drugs_found=drugs_list,
            signals=signals,
            errors=errors,
        )]

    async def _collect_ctgov(
        self,
        drugs: dict[str, dict],
        signals: list[dict],
    ) -> int:
        """ClinicalTrials.gov Phase 3 수집 + Triage"""
        from regscan.ingest.clinicaltrials import ClinicalTrialsGovIngestor
        from regscan.parse.clinicaltrials_parser import ClinicalTrialsGovParser
        from regscan.stream.trial_triage import TrialTriageEngine

        # 치료영역별 CT.gov condition 목록 수집
        conditions = self._get_ct_conditions()

        ingestor = ClinicalTrialsGovIngestor(
            conditions=conditions,
            months_back=settings.CT_GOV_MONTHS_BACK,
        )
        async with ingestor:
            raw_studies = await ingestor.fetch()

        # 파싱
        parser = ClinicalTrialsGovParser()
        parsed = parser.parse_many(raw_studies)

        # Triage
        triage = TrialTriageEngine()
        triaged = triage.triage_many(parsed)

        # FAIL → 즉시 시그널
        for study in triaged["fail"]:
            signals.append({
                "type": "ctgov_trial_fail",
                "nct_id": study.get("nct_id"),
                "title": study.get("title"),
                "inns": study.get("extracted_inns", []),
                "verdict": "FAIL",
                "why_stopped": study.get("why_stopped", ""),
                "verdict_summary": study.get("verdict_summary", ""),
            })
            self._add_inns_to_drugs(drugs, study)

        # PENDING → 워치리스트
        for study in triaged["pending"]:
            signals.append({
                "type": "ctgov_trial_pending",
                "nct_id": study.get("nct_id"),
                "title": study.get("title"),
                "inns": study.get("extracted_inns", []),
                "verdict": "PENDING",
            })
            self._add_inns_to_drugs(drugs, study)

        # NEEDS_AI → AI 판독 대기 시그널
        for study in triaged["needs_ai"]:
            signals.append({
                "type": "ctgov_trial_needs_ai",
                "nct_id": study.get("nct_id"),
                "title": study.get("title"),
                "inns": study.get("extracted_inns", []),
                "verdict": "NEEDS_AI",
            })
            self._add_inns_to_drugs(drugs, study)

        return len(parsed)

    async def _collect_medrxiv(self, signals: list[dict]) -> int:
        """medRxiv 복합 키워드 수집"""
        from regscan.ingest.biorxiv import MedRxivCompoundIngestor

        areas = self._get_area_labels()
        ingestor = MedRxivCompoundIngestor(
            therapeutic_areas=areas,
            days_back=settings.MEDRXIV_DAYS_BACK,
        )
        async with ingestor:
            papers = await ingestor.fetch()

        for paper in papers:
            signals.append({
                "type": "medrxiv_paper",
                "doi": paper.get("doi", ""),
                "title": paper.get("title", ""),
                "search_keyword": paper.get("search_keyword", ""),
                "server": paper.get("server", "medrxiv"),
            })

        return len(papers)

    def _add_inns_to_drugs(self, drugs: dict, study: dict) -> None:
        """파싱된 임상시험에서 INN을 약물 목록에 추가 (brand→INN 변환 선행)"""
        for raw_inn in study.get("extracted_inns", []):
            # brand name → canonical INN 변환
            inn = self._matcher.find_canonical(raw_inn)
            norm = self._matcher.normalize(inn)
            if norm not in drugs:
                drugs[norm] = {
                    "inn": inn,
                    "normalized_name": norm,
                    "therapeutic_areas": [],
                    "stream_sources": ["external"],
                    "ct_gov_nct_ids": [study.get("nct_id")],
                    "cross_referenced": False,
                }
            else:
                ncts = drugs[norm].setdefault("ct_gov_nct_ids", [])
                nct_id = study.get("nct_id")
                if nct_id and nct_id not in ncts:
                    ncts.append(nct_id)

    def _target_inns_normalized(self) -> set[str]:
        """교차 참조용 INN 정규화"""
        return {self._matcher.normalize(inn) for inn in self._target_inns}

    def _get_ct_conditions(self) -> list[str]:
        """치료영역 설정에서 CT.gov condition 목록 추출"""
        conditions: list[str] = []
        areas = self._therapeutic_areas or [
            a.strip() for a in settings.THERAPEUTIC_AREAS.split(",")
        ]
        for area_name in areas:
            area = TherapeuticAreaConfig.get_area(area_name)
            if area:
                conditions.extend(area.ct_conditions)
        # 중복 제거
        return list(dict.fromkeys(conditions))

    def _get_area_labels(self) -> list[str]:
        """치료영역 라벨 목록 (medRxiv 키워드용)"""
        labels: list[str] = []
        areas = self._therapeutic_areas or [
            a.strip() for a in settings.THERAPEUTIC_AREAS.split(",")
        ]
        for area_name in areas:
            area = TherapeuticAreaConfig.get_area(area_name)
            if area:
                labels.append(area.label_ko)
                labels.append(area.name)
        return labels
