"""KoreaRelevanceScorer + DomesticImpact.quadrant 테스트"""

import pytest

from regscan.map.ingredient_bridge import ReimbursementStatus
from regscan.scan.domestic import (
    DomesticImpact,
    DomesticStatus,
    KoreaRelevanceScorer,
)


# ── helpers ──

def _make_impact(**overrides) -> DomesticImpact:
    """테스트용 DomesticImpact 생성."""
    defaults = dict(
        inn="test-drug",
        domestic_status=DomesticStatus.NOT_APPLICABLE,
        global_score=0,
    )
    defaults.update(overrides)
    return DomesticImpact(**defaults)


# ── quadrant 테스트 ──

class TestQuadrant:
    def test_top_priority(self):
        impact = _make_impact(global_score=80, korea_relevance_score=60)
        assert impact.quadrant == "top_priority"

    def test_watch(self):
        impact = _make_impact(global_score=70, korea_relevance_score=30)
        assert impact.quadrant == "watch"

    def test_track(self):
        impact = _make_impact(global_score=40, korea_relevance_score=55)
        assert impact.quadrant == "track"

    def test_normal(self):
        impact = _make_impact(global_score=30, korea_relevance_score=20)
        assert impact.quadrant == "normal"

    def test_boundary_global_60_korea_50(self):
        """경계값: global=60, korea=50 → top_priority"""
        impact = _make_impact(global_score=60, korea_relevance_score=50)
        assert impact.quadrant == "top_priority"

    def test_boundary_global_59_korea_50(self):
        """경계값: global=59, korea=50 → track"""
        impact = _make_impact(global_score=59, korea_relevance_score=50)
        assert impact.quadrant == "track"

    def test_boundary_global_60_korea_49(self):
        """경계값: global=60, korea=49 → watch"""
        impact = _make_impact(global_score=60, korea_relevance_score=49)
        assert impact.quadrant == "watch"


# ── KoreaRelevanceScorer 테스트 ──

class TestKoreaRelevanceScorer:
    def test_empty_impact_scores_zero(self):
        """아무 데이터 없으면 0점."""
        scorer = KoreaRelevanceScorer()
        impact = _make_impact()
        score, reasons = scorer.calculate(impact)
        assert score == 0
        assert reasons == []

    def test_mfds_approved_adds_20(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(mfds_approved=True)
        score, reasons = scorer.calculate(impact)
        assert score == 20
        assert "MFDS 허가" in reasons

    def test_hira_reimbursed_adds_20(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(hira_status=ReimbursementStatus.REIMBURSED)
        score, reasons = scorer.calculate(impact)
        assert score == 20
        assert "HIRA 급여 등재" in reasons

    def test_hira_deleted_adds_5(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(hira_status=ReimbursementStatus.DELETED)
        score, reasons = scorer.calculate(impact)
        assert score == 5
        assert "HIRA 급여 삭제 이력" in reasons

    def test_cris_active_adds_15(self):
        from regscan.scan.domestic import ClinicalTrialInfo

        scorer = KoreaRelevanceScorer()
        impact = _make_impact(
            has_active_trial=True,
            cris_trials=[ClinicalTrialInfo(trial_id="KCT001", title="Trial 1")],
        )
        score, reasons = scorer.calculate(impact)
        assert score == 15
        assert any("임상시험" in r for r in reasons)

    def test_cris_multiple_adds_5_bonus(self):
        from regscan.scan.domestic import ClinicalTrialInfo

        scorer = KoreaRelevanceScorer()
        impact = _make_impact(
            has_active_trial=True,
            cris_trials=[
                ClinicalTrialInfo(trial_id="KCT001", title="Trial 1"),
                ClinicalTrialInfo(trial_id="KCT002", title="Trial 2"),
            ],
        )
        score, reasons = scorer.calculate(impact)
        # 15 (cris_active) + 5 (cris_multiple) = 20
        assert score == 20

    def test_atc_market_exists(self):
        scorer = KoreaRelevanceScorer(hira_atc_codes={"L01"})
        impact = _make_impact()
        score, reasons = scorer.calculate(impact, atc_code="L01X")
        assert score == 15
        assert any("치료영역" in r for r in reasons)

    def test_atc_no_match(self):
        scorer = KoreaRelevanceScorer(hira_atc_codes={"L01"})
        impact = _make_impact()
        score, reasons = scorer.calculate(impact, atc_code="N05A")
        assert score == 0

    def test_atc_skipped_when_no_codes(self):
        """hira_atc_codes 없으면 ATC 항목 스킵."""
        scorer = KoreaRelevanceScorer()
        impact = _make_impact()
        score, reasons = scorer.calculate(impact, atc_code="L01X")
        assert score == 0

    def test_high_burden_disease(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact()
        score, reasons = scorer.calculate(impact, indication="advanced cancer treatment")
        assert score == 15
        assert "국내 다빈도 질환" in reasons

    def test_high_burden_case_insensitive(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact()
        score, _ = scorer.calculate(impact, indication="DIABETES mellitus type 2")
        assert score == 15

    def test_orphan_drug_from_hot_issue_reasons(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(hot_issue_reasons=["Orphan Drug Designation"])
        score, reasons = scorer.calculate(impact)
        assert score == 10
        assert "희귀의약품 지정" in reasons

    def test_orphan_drug_korean_keyword(self):
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(hot_issue_reasons=["희귀의약품 지정"])
        score, reasons = scorer.calculate(impact)
        assert score == 10

    def test_full_combination(self):
        """MFDS(20) + HIRA(20) + CRIS(15+5) + ATC(15) + 다빈도(15) + 희귀(10) = 100."""
        from regscan.scan.domestic import ClinicalTrialInfo

        scorer = KoreaRelevanceScorer(hira_atc_codes={"L01"})
        impact = _make_impact(
            mfds_approved=True,
            hira_status=ReimbursementStatus.REIMBURSED,
            has_active_trial=True,
            cris_trials=[
                ClinicalTrialInfo(trial_id="KCT001", title="T1"),
                ClinicalTrialInfo(trial_id="KCT002", title="T2"),
            ],
            hot_issue_reasons=["Orphan Drug"],
        )
        score, reasons = scorer.calculate(
            impact, atc_code="L01X", indication="advanced cancer"
        )
        assert score == 100
        assert len(reasons) == 6  # MFDS, HIRA, CRIS(1개 reason), ATC, 다빈도, 희귀

    def test_cap_at_100(self):
        """점수는 100 이상으로 올라가지 않는다."""
        from regscan.scan.domestic import ClinicalTrialInfo

        scorer = KoreaRelevanceScorer(hira_atc_codes={"L01"})
        impact = _make_impact(
            mfds_approved=True,
            hira_status=ReimbursementStatus.REIMBURSED,
            has_active_trial=True,
            cris_trials=[
                ClinicalTrialInfo(trial_id="KCT001", title="T1"),
                ClinicalTrialInfo(trial_id="KCT002", title="T2"),
                ClinicalTrialInfo(trial_id="KCT003", title="T3"),
            ],
            hot_issue_reasons=["희귀의약품"],
        )
        score, _ = scorer.calculate(
            impact, atc_code="L01X", indication="cancer treatment"
        )
        assert score <= 100

    def test_hira_not_covered_scores_zero(self):
        """비급여(NOT_COVERED)는 HIRA 점수 없음."""
        scorer = KoreaRelevanceScorer()
        impact = _make_impact(hira_status=ReimbursementStatus.NOT_COVERED)
        score, reasons = scorer.calculate(impact)
        assert score == 0

    def test_is_high_burden_static(self):
        """_is_high_burden 정적 메서드 직접 테스트."""
        assert KoreaRelevanceScorer._is_high_burden("treatment for asthma") is True
        assert KoreaRelevanceScorer._is_high_burden("cosmetic procedure") is False
        assert KoreaRelevanceScorer._is_high_burden("HIV infection") is True
        assert KoreaRelevanceScorer._is_high_burden("") is False
