"""FDA→KR 매핑 엔진

해외 승인 약물의 국내 급여 상태 분석 및 예측
"""

from .timeline import DrugTimeline, TimelineBuilder
from .matcher import IngredientMatcher, DrugMatcher
from .report import ReportItem, HotIssueDetector, FDAKRReportGenerator
from .global_status import (
    ApprovalStatus,
    HotIssueLevel,
    RegulatoryApproval,
    GlobalRegulatoryStatus,
    HotIssueScorer,
    GlobalStatusBuilder,
    merge_by_inn,
    enrich_with_hira,
)
from .atc import (
    ATCEntry,
    ATCDatabase,
    ATCMatcher,
    ATC_LEVEL1,
    ATC_LEVEL1_KO,
    get_atc_database,
    enrich_with_atc,
    classify_therapeutic_area,
)
from .ingredient_bridge import (
    ReimbursementStatus,
    HIRAReimbursementInfo,
    IngredientBridge,
    normalize_ingredient_name,
    is_herbal_ingredient,
    get_ingredient_bridge,
    lookup_hira_reimbursement,
)

__all__ = [
    "DrugTimeline",
    "TimelineBuilder",
    "IngredientMatcher",
    "DrugMatcher",
    "ReportItem",
    "HotIssueDetector",
    "FDAKRReportGenerator",
    # Global Status
    "ApprovalStatus",
    "HotIssueLevel",
    "RegulatoryApproval",
    "GlobalRegulatoryStatus",
    "HotIssueScorer",
    "GlobalStatusBuilder",
    "merge_by_inn",
    "enrich_with_hira",
    # ATC
    "ATCEntry",
    "ATCDatabase",
    "ATCMatcher",
    "ATC_LEVEL1",
    "ATC_LEVEL1_KO",
    "get_atc_database",
    "enrich_with_atc",
    "classify_therapeutic_area",
    # Ingredient Bridge (MFDS ↔ HIRA)
    "ReimbursementStatus",
    "HIRAReimbursementInfo",
    "IngredientBridge",
    "normalize_ingredient_name",
    "is_herbal_ingredient",
    "get_ingredient_bridge",
    "lookup_hira_reimbursement",
]
