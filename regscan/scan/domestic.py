"""국내 영향 분석기

글로벌 승인 약물의 국내 시장 영향 분석:
- MFDS 허가 현황
- HIRA 급여 현황 (75.7% 커버리지)
- CRIS 임상시험 현황
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, Any

from regscan.map.global_status import GlobalRegulatoryStatus, ApprovalStatus
from regscan.map.ingredient_bridge import (
    IngredientBridge,
    ReimbursementStatus,
    HIRAReimbursementInfo,
    get_ingredient_bridge,
)
from regscan.map.matcher import IngredientMatcher


class DomesticStatus(str, Enum):
    """국내 시장 상태"""

    # 국내 가용
    REIMBURSED = "reimbursed"                    # MFDS 허가 + HIRA 급여
    APPROVED_NOT_REIMBURSED = "approved_not_reimbursed"  # MFDS 허가 + HIRA 미급여
    APPROVED_DELETED = "approved_deleted"        # MFDS 허가 + HIRA 삭제

    # 국내 미허가
    IMMINENT = "imminent"                        # 글로벌 승인 + MFDS 미허가 + CRIS 진행
    EXPECTED = "expected"                        # 글로벌 승인 + MFDS 미허가 + 임상 없음 (but 주요 약물)
    UNCERTAIN = "uncertain"                      # 글로벌 승인 + MFDS 미허가 + 임상 없음

    # 기타
    DOMESTIC_ONLY = "domestic_only"              # MFDS만 허가 (글로벌 미승인)
    NOT_APPLICABLE = "not_applicable"            # 분석 대상 아님


@dataclass
class ClinicalTrialInfo:
    """CRIS 임상시험 정보"""
    trial_id: str
    title: str
    phase: str = ""
    status: str = ""
    indication: str = ""
    sponsor: str = ""


@dataclass
class DomesticImpact:
    """국내 영향 분석 결과"""

    # 기본 정보
    inn: str                                     # 성분명 (INN)
    domestic_status: DomesticStatus              # 국내 상태

    # 글로벌 승인 현황
    fda_approved: bool = False
    fda_date: Optional[date] = None
    ema_approved: bool = False
    ema_date: Optional[date] = None

    # 국내 허가 현황
    mfds_approved: bool = False
    mfds_date: Optional[date] = None
    mfds_brand_name: str = ""

    # HIRA 급여 현황
    hira_status: Optional[ReimbursementStatus] = None
    hira_code: str = ""
    hira_criteria: str = ""                      # 급여기준
    hira_price: Optional[float] = None           # 상한가

    # CRIS 임상시험
    cris_trials: list[ClinicalTrialInfo] = field(default_factory=list)
    has_active_trial: bool = False

    # 분석 메타
    global_score: int = 0
    hot_issue_reasons: list[str] = field(default_factory=list)
    analysis_notes: list[str] = field(default_factory=list)

    @property
    def is_globally_approved(self) -> bool:
        """FDA 또는 EMA 승인 여부"""
        return self.fda_approved or self.ema_approved

    @property
    def days_since_global_approval(self) -> Optional[int]:
        """글로벌 최초 승인 후 경과일"""
        dates = []
        if self.fda_date:
            dates.append(self.fda_date)
        if self.ema_date:
            dates.append(self.ema_date)
        if not dates:
            return None
        first = min(dates)
        return (date.today() - first).days

    @property
    def summary(self) -> str:
        """한 줄 요약"""
        parts = []

        # 글로벌
        global_parts = []
        if self.fda_approved:
            global_parts.append("FDA")
        if self.ema_approved:
            global_parts.append("EMA")
        if global_parts:
            parts.append(f"글로벌: {'+'.join(global_parts)}")

        # 국내 허가
        if self.mfds_approved:
            parts.append(f"MFDS: 허가")
        else:
            parts.append(f"MFDS: 미허가")

        # HIRA
        if self.hira_status:
            if self.hira_status == ReimbursementStatus.REIMBURSED:
                price_str = f" (₩{self.hira_price:,.0f})" if self.hira_price else ""
                parts.append(f"HIRA: 급여{price_str}")
            elif self.hira_status == ReimbursementStatus.DELETED:
                parts.append("HIRA: 삭제")
            elif self.hira_status == ReimbursementStatus.NOT_COVERED:
                parts.append("HIRA: 비급여")

        # CRIS
        if self.has_active_trial:
            parts.append(f"CRIS: {len(self.cris_trials)}건 진행")

        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "inn": self.inn,
            "domestic_status": self.domestic_status.value,
            "fda_approved": self.fda_approved,
            "fda_date": self.fda_date.isoformat() if self.fda_date else None,
            "ema_approved": self.ema_approved,
            "ema_date": self.ema_date.isoformat() if self.ema_date else None,
            "mfds_approved": self.mfds_approved,
            "mfds_date": self.mfds_date.isoformat() if self.mfds_date else None,
            "mfds_brand_name": self.mfds_brand_name,
            "hira_status": self.hira_status.value if self.hira_status else None,
            "hira_code": self.hira_code,
            "hira_criteria": self.hira_criteria,
            "hira_price": self.hira_price,
            "cris_trial_count": len(self.cris_trials),
            "has_active_trial": self.has_active_trial,
            "global_score": self.global_score,
            "summary": self.summary,
            "analysis_notes": self.analysis_notes,
        }


class DomesticImpactAnalyzer:
    """국내 영향 분석기

    사용법:
        analyzer = DomesticImpactAnalyzer()
        analyzer.load_cris_data(cris_parsed)

        # 단일 분석
        impact = analyzer.analyze(global_status)

        # 배치 분석
        impacts = analyzer.analyze_batch(statuses)

        # 분류별 조회
        imminent = analyzer.get_by_status(DomesticStatus.IMMINENT)
    """

    def __init__(self, ingredient_bridge: Optional[IngredientBridge] = None):
        self._bridge = ingredient_bridge
        self._matcher = IngredientMatcher()
        self._cris_by_drug: dict[str, list[dict]] = {}
        self._results: list[DomesticImpact] = []

    def _get_bridge(self) -> Optional[IngredientBridge]:
        """IngredientBridge lazy loading"""
        if self._bridge is None:
            try:
                self._bridge = get_ingredient_bridge()
            except Exception:
                pass
        return self._bridge

    def load_cris_data(self, cris_parsed: list[dict]) -> int:
        """
        CRIS 임상시험 데이터 로드

        Args:
            cris_parsed: CRISTrialParser로 파싱된 데이터

        Returns:
            인덱싱된 고유 약물명 수
        """
        self._cris_by_drug.clear()

        for trial in cris_parsed:
            for drug in trial.get("drug_names", []):
                normalized = self._matcher.normalize(drug)
                if normalized and len(normalized) > 2:
                    if normalized not in self._cris_by_drug:
                        self._cris_by_drug[normalized] = []
                    self._cris_by_drug[normalized].append(trial)

        return len(self._cris_by_drug)

    def analyze(self, status: GlobalRegulatoryStatus) -> DomesticImpact:
        """
        단일 GlobalRegulatoryStatus 분석

        Args:
            status: 글로벌 규제 현황

        Returns:
            DomesticImpact
        """
        impact = DomesticImpact(
            inn=status.inn,
            domestic_status=DomesticStatus.NOT_APPLICABLE,
            global_score=status.global_score,
            hot_issue_reasons=status.hot_issue_reasons.copy(),
        )

        # FDA
        if status.fda and status.fda.status == ApprovalStatus.APPROVED:
            impact.fda_approved = True
            impact.fda_date = status.fda.approval_date

        # EMA
        if status.ema and status.ema.status == ApprovalStatus.APPROVED:
            impact.ema_approved = True
            impact.ema_date = status.ema.approval_date

        # MFDS
        if status.mfds and status.mfds.status == ApprovalStatus.APPROVED:
            impact.mfds_approved = True
            impact.mfds_date = status.mfds.approval_date
            impact.mfds_brand_name = status.mfds.brand_name

        # HIRA (새로 추가!)
        self._enrich_hira(impact, status)

        # CRIS
        self._enrich_cris(impact)

        # 상태 결정
        impact.domestic_status = self._determine_status(impact)

        # 분석 노트
        self._add_analysis_notes(impact)

        return impact

    def _enrich_hira(self, impact: DomesticImpact, status: GlobalRegulatoryStatus) -> None:
        """HIRA 급여 정보 추가"""
        bridge = self._get_bridge()
        if not bridge:
            return

        # GlobalRegulatoryStatus에 이미 HIRA 정보가 있으면 사용
        if status.hira_reimbursement:
            hira = status.hira_reimbursement
        else:
            # 없으면 직접 조회
            ingredient_name = status.inn
            if not ingredient_name and status.mfds:
                ingredient_name = status.mfds.raw_data.get("ITEM_INGR_NAME", "")

            if ingredient_name:
                hira = bridge.lookup(ingredient_name)
            else:
                return

        impact.hira_status = hira.status
        impact.hira_code = hira.ingredient_code
        impact.hira_criteria = hira.reimbursement_criteria
        impact.hira_price = hira.price_ceiling

    def _enrich_cris(self, impact: DomesticImpact) -> None:
        """CRIS 임상시험 정보 추가"""
        normalized = self._matcher.normalize(impact.inn)

        if normalized in self._cris_by_drug:
            trials = self._cris_by_drug[normalized]
            for trial in trials:
                impact.cris_trials.append(ClinicalTrialInfo(
                    trial_id=trial.get("trial_id", ""),
                    title=trial.get("title", ""),
                    phase=trial.get("phase", ""),
                    status=trial.get("status", ""),
                    indication=trial.get("indication", ""),
                    sponsor=trial.get("sponsor", ""),
                ))
            impact.has_active_trial = len(trials) > 0

    def _determine_status(self, impact: DomesticImpact) -> DomesticStatus:
        """국내 상태 결정"""

        # Case 1: MFDS 허가됨
        if impact.mfds_approved:
            if impact.hira_status == ReimbursementStatus.REIMBURSED:
                return DomesticStatus.REIMBURSED
            elif impact.hira_status == ReimbursementStatus.DELETED:
                return DomesticStatus.APPROVED_DELETED
            elif impact.hira_status in [ReimbursementStatus.NOT_COVERED,
                                         ReimbursementStatus.NOT_FOUND,
                                         ReimbursementStatus.HERBAL]:
                return DomesticStatus.APPROVED_NOT_REIMBURSED
            else:
                # HIRA 정보 없음 - 기본적으로 미급여로 처리
                return DomesticStatus.APPROVED_NOT_REIMBURSED

        # Case 2: MFDS 미허가 + 글로벌 승인
        if impact.is_globally_approved:
            if impact.has_active_trial:
                return DomesticStatus.IMMINENT
            elif impact.global_score >= 60:
                return DomesticStatus.EXPECTED
            else:
                return DomesticStatus.UNCERTAIN

        # Case 3: 글로벌 미승인 + MFDS만 (있으면)
        if impact.mfds_approved:
            return DomesticStatus.DOMESTIC_ONLY

        return DomesticStatus.NOT_APPLICABLE

    def _add_analysis_notes(self, impact: DomesticImpact) -> None:
        """분석 노트 추가"""
        notes = []

        # 글로벌 승인 후 국내 미허가
        if impact.is_globally_approved and not impact.mfds_approved:
            days = impact.days_since_global_approval
            if days and days > 365:
                notes.append(f"글로벌 승인 후 {days // 365}년 경과, 국내 미허가")

        # 국내 허가 but 비급여
        if impact.mfds_approved and impact.hira_status != ReimbursementStatus.REIMBURSED:
            if impact.hira_status == ReimbursementStatus.NOT_COVERED:
                notes.append("국내 허가되었으나 비급여")
            elif impact.hira_status == ReimbursementStatus.DELETED:
                notes.append("국내 허가되었으나 급여 삭제됨")

        # 고가 약물
        if impact.hira_price and impact.hira_price > 1_000_000:
            notes.append(f"고가 약물 (상한가 ₩{impact.hira_price:,.0f})")

        # 임상 진행 중
        if impact.has_active_trial and not impact.mfds_approved:
            notes.append(f"국내 임상시험 {len(impact.cris_trials)}건 진행 중")

        impact.analysis_notes = notes

    def analyze_batch(self, statuses: list[GlobalRegulatoryStatus]) -> list[DomesticImpact]:
        """
        배치 분석

        Args:
            statuses: GlobalRegulatoryStatus 목록

        Returns:
            DomesticImpact 목록
        """
        self._results = [self.analyze(s) for s in statuses]
        return self._results

    def get_by_status(self, status: DomesticStatus) -> list[DomesticImpact]:
        """특정 상태의 결과만 조회"""
        return [r for r in self._results if r.domestic_status == status]

    def get_summary(self) -> dict[str, Any]:
        """분석 결과 요약"""
        if not self._results:
            return {"total": 0}

        by_status = {}
        for status in DomesticStatus:
            items = self.get_by_status(status)
            if items:
                by_status[status.value] = len(items)

        # HIRA 통계
        reimbursed = [r for r in self._results if r.hira_status == ReimbursementStatus.REIMBURSED]
        total_price = sum(r.hira_price or 0 for r in reimbursed)

        return {
            "total": len(self._results),
            "by_status": by_status,
            "hira_reimbursed_count": len(reimbursed),
            "hira_total_price_sum": total_price,
            "with_cris_trials": len([r for r in self._results if r.has_active_trial]),
            "globally_approved_not_in_korea": len([
                r for r in self._results
                if r.is_globally_approved and not r.mfds_approved
            ]),
        }

    def get_imminent_drugs(self) -> list[DomesticImpact]:
        """국내 도입 임박 약물"""
        return sorted(
            self.get_by_status(DomesticStatus.IMMINENT),
            key=lambda x: -x.global_score
        )

    def get_high_value_reimbursed(self, min_price: float = 1_000_000) -> list[DomesticImpact]:
        """고가 급여 약물"""
        return sorted(
            [r for r in self._results
             if r.hira_status == ReimbursementStatus.REIMBURSED
             and r.hira_price and r.hira_price >= min_price],
            key=lambda x: -(x.hira_price or 0)
        )
