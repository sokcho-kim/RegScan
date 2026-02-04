"""통계 및 핫이슈 API"""

from fastapi import APIRouter, Depends
from regscan.api.deps import get_data_store, DataStore
from regscan.api.schemas import (
    StatsResponse,
    HotIssueItem,
    ImminentDrugItem,
)
from regscan.map.ingredient_bridge import ReimbursementStatus

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def get_stats(store: DataStore = Depends(get_data_store)):
    """전체 통계"""
    hot_issues = store.get_hot_issues(min_score=60)
    imminent = store.get_imminent()
    reimbursed = [
        i for i in store.impacts
        if i.hira_status == ReimbursementStatus.REIMBURSED
    ]

    return StatsResponse(
        fda_count=store.fda_count,
        ema_count=store.ema_count,
        mfds_count=store.mfds_count,
        cris_count=store.cris_count,
        hot_issues_count=len(hot_issues),
        imminent_count=len(imminent),
        reimbursed_count=len(reimbursed),
        last_updated=store.loaded_at,
    )


@router.get("/hot-issues", response_model=list[HotIssueItem])
def get_hot_issues(
    min_score: int = 60,
    limit: int = 50,
    store: DataStore = Depends(get_data_store),
):
    """핫이슈 목록"""
    items = store.get_hot_issues(min_score=min_score)[:limit]

    return [
        HotIssueItem(
            inn=i.inn,
            global_score=i.global_score,
            hot_issue_level="HOT" if i.global_score >= 80 else "HIGH",
            reasons=i.hot_issue_reasons,
            fda_approved=i.fda_approved,
            ema_approved=i.ema_approved,
            mfds_approved=i.mfds_approved,
            hira_reimbursed=i.hira_status == ReimbursementStatus.REIMBURSED,
        )
        for i in items
    ]


@router.get("/imminent", response_model=list[ImminentDrugItem])
def get_imminent_drugs(
    limit: int = 50,
    store: DataStore = Depends(get_data_store),
):
    """국내 도입 임박 약물"""
    items = store.get_imminent()[:limit]

    return [
        ImminentDrugItem(
            inn=i.inn,
            global_score=i.global_score,
            fda_date=i.fda_date,
            ema_date=i.ema_date,
            hira_status=i.hira_status.value if i.hira_status else None,
            hira_price=i.hira_price,
            cris_trial_count=len(i.cris_trials),
            days_since_global_approval=i.days_since_global_approval,
            analysis_notes=i.analysis_notes,
        )
        for i in items
    ]
