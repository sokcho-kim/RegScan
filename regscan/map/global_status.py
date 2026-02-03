"""글로벌 규제 현황 모델

FDA, EMA, PMDA, MFDS 데이터를 통합하여 글로벌 규제 현황 제공
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from .matcher import IngredientMatcher


class ApprovalStatus(str, Enum):
    """승인 상태"""
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class HotIssueLevel(str, Enum):
    """핫이슈 등급"""
    HOT = "HOT"      # 80+ 점: 글로벌 주목 신약
    HIGH = "HIGH"    # 60-79점: 높은 관심
    MID = "MID"      # 40-59점: 중간
    LOW = "LOW"      # 40점 미만: 일반


@dataclass
class RegulatoryApproval:
    """개별 규제기관 승인 정보"""
    agency: str                          # FDA, EMA, PMDA, MFDS
    status: ApprovalStatus
    approval_date: Optional[date] = None
    application_number: str = ""
    brand_name: str = ""
    indication: str = ""

    # 특수 지정
    is_orphan: bool = False
    is_accelerated: bool = False         # FDA: Accelerated, EMA: Accelerated
    is_breakthrough: bool = False        # FDA: Breakthrough
    is_priority: bool = False            # FDA: Priority Review
    is_prime: bool = False               # EMA: PRIME
    is_conditional: bool = False         # EMA: Conditional Approval
    is_fast_track: bool = False          # FDA: Fast Track

    # 원본 데이터 참조
    source_url: str = ""
    raw_data: dict = field(default_factory=dict)

    @property
    def has_expedited_pathway(self) -> bool:
        """신속심사 경로 여부"""
        return any([
            self.is_accelerated,
            self.is_breakthrough,
            self.is_priority,
            self.is_prime,
            self.is_fast_track,
        ])


@dataclass
class GlobalRegulatoryStatus:
    """글로벌 규제 현황"""

    # 약물 식별
    inn: str                              # International Nonproprietary Name
    normalized_name: str = ""             # 정규화된 성분명
    atc_code: str = ""                    # ATC 분류 코드

    # 규제기관별 승인 현황
    fda: Optional[RegulatoryApproval] = None
    ema: Optional[RegulatoryApproval] = None
    pmda: Optional[RegulatoryApproval] = None
    mfds: Optional[RegulatoryApproval] = None

    # WHO 지정
    who_eml: bool = False                 # Essential Medicines List 등재
    who_prequalified: bool = False        # WHO 사전적격

    # 분석 결과
    global_score: int = 0                 # 글로벌 중요도 점수 (0-100)
    hot_issue_level: HotIssueLevel = HotIssueLevel.LOW
    hot_issue_reasons: list[str] = field(default_factory=list)

    # 메타데이터
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def approved_agencies(self) -> list[str]:
        """승인된 규제기관 목록"""
        agencies = []
        for agency, approval in [
            ("FDA", self.fda),
            ("EMA", self.ema),
            ("PMDA", self.pmda),
            ("MFDS", self.mfds),
        ]:
            if approval and approval.status == ApprovalStatus.APPROVED:
                agencies.append(agency)
        return agencies

    @property
    def approval_count(self) -> int:
        """승인된 기관 수"""
        return len(self.approved_agencies)

    @property
    def is_globally_approved(self) -> bool:
        """3개국 이상 승인 여부"""
        return self.approval_count >= 3

    @property
    def first_approval_date(self) -> Optional[date]:
        """최초 승인일"""
        dates = []
        for approval in [self.fda, self.ema, self.pmda, self.mfds]:
            if approval and approval.approval_date:
                dates.append(approval.approval_date)
        return min(dates) if dates else None

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "inn": self.inn,
            "normalized_name": self.normalized_name,
            "atc_code": self.atc_code,
            "fda": self._approval_to_dict(self.fda),
            "ema": self._approval_to_dict(self.ema),
            "pmda": self._approval_to_dict(self.pmda),
            "mfds": self._approval_to_dict(self.mfds),
            "who_eml": self.who_eml,
            "approved_agencies": self.approved_agencies,
            "approval_count": self.approval_count,
            "global_score": self.global_score,
            "hot_issue_level": self.hot_issue_level.value,
            "hot_issue_reasons": self.hot_issue_reasons,
            "last_updated": self.last_updated.isoformat(),
        }

    def _approval_to_dict(self, approval: Optional[RegulatoryApproval]) -> Optional[dict]:
        if not approval:
            return None
        return {
            "agency": approval.agency,
            "status": approval.status.value,
            "approval_date": approval.approval_date.isoformat() if approval.approval_date else None,
            "brand_name": approval.brand_name,
            "is_orphan": approval.is_orphan,
            "has_expedited_pathway": approval.has_expedited_pathway,
            "source_url": approval.source_url,
        }


class HotIssueScorer:
    """핫이슈 스코어링 시스템"""

    # 스코어 가중치
    SCORE_WEIGHTS = {
        # FDA 관련 (최대 35점)
        "fda_approved": 10,
        "fda_breakthrough": 15,
        "fda_accelerated": 10,
        "fda_priority": 5,
        "fda_fast_track": 5,

        # EMA 관련 (최대 30점)
        "ema_approved": 10,
        "ema_prime": 15,
        "ema_accelerated": 10,
        "ema_conditional": 5,

        # MFDS 관련 (최대 15점)
        "mfds_approved": 5,         # 국내 허가
        "mfds_orphan": 10,          # 국내 희귀의약품

        # 글로벌 승인 (최대 20점)
        "multi_approval_3": 10,      # 3개국 이상
        "multi_approval_4": 10,      # 4개국 (추가)
        "fda_ema_concurrent": 10,    # FDA+EMA 동시/근접 승인

        # 특수 지정 (최대 25점)
        "orphan_drug": 15,
        "who_eml": 10,

        # 질환 분류 (최대 10점)
        "major_disease": 10,         # 암, 치매, 당뇨 등
    }

    # 주요 질환 키워드
    MAJOR_DISEASE_KEYWORDS = [
        "cancer", "neoplasm", "tumor", "oncolog", "leukemia", "lymphoma",
        "alzheimer", "dementia",
        "diabetes",
        "heart failure", "cardiovascular",
        "hiv", "aids",
        "hepatitis",
        "covid", "sars-cov",
    ]

    def calculate_score(self, status: GlobalRegulatoryStatus) -> tuple[int, list[str]]:
        """
        핫이슈 스코어 계산

        Args:
            status: 글로벌 규제 현황

        Returns:
            (점수, 이유 목록)
        """
        score = 0
        reasons = []

        # FDA
        if status.fda:
            if status.fda.status == ApprovalStatus.APPROVED:
                score += self.SCORE_WEIGHTS["fda_approved"]
                reasons.append("FDA 승인")

            if status.fda.is_breakthrough:
                score += self.SCORE_WEIGHTS["fda_breakthrough"]
                reasons.append("FDA Breakthrough Therapy")

            if status.fda.is_accelerated:
                score += self.SCORE_WEIGHTS["fda_accelerated"]
                reasons.append("FDA Accelerated Approval")

            if status.fda.is_priority:
                score += self.SCORE_WEIGHTS["fda_priority"]
                reasons.append("FDA Priority Review")

            if status.fda.is_fast_track:
                score += self.SCORE_WEIGHTS["fda_fast_track"]
                reasons.append("FDA Fast Track")

        # EMA
        if status.ema:
            if status.ema.status == ApprovalStatus.APPROVED:
                score += self.SCORE_WEIGHTS["ema_approved"]
                reasons.append("EMA 승인")

            if status.ema.is_prime:
                score += self.SCORE_WEIGHTS["ema_prime"]
                reasons.append("EMA PRIME")

            if status.ema.is_accelerated:
                score += self.SCORE_WEIGHTS["ema_accelerated"]
                reasons.append("EMA Accelerated Assessment")

            if status.ema.is_conditional:
                score += self.SCORE_WEIGHTS["ema_conditional"]
                reasons.append("EMA Conditional Approval")

        # MFDS
        if status.mfds:
            if status.mfds.status == ApprovalStatus.APPROVED:
                score += self.SCORE_WEIGHTS["mfds_approved"]
                reasons.append("MFDS 허가")

            if status.mfds.is_orphan:
                score += self.SCORE_WEIGHTS["mfds_orphan"]
                reasons.append("MFDS 희귀의약품")

        # 다중 승인
        if status.approval_count >= 3:
            score += self.SCORE_WEIGHTS["multi_approval_3"]
            reasons.append(f"{status.approval_count}개국 승인")

        if status.approval_count >= 4:
            score += self.SCORE_WEIGHTS["multi_approval_4"]

        # FDA+EMA 동시 승인 (1년 이내)
        if status.fda and status.ema:
            if (status.fda.status == ApprovalStatus.APPROVED and
                status.ema.status == ApprovalStatus.APPROVED and
                status.fda.approval_date and status.ema.approval_date):
                days_diff = abs((status.fda.approval_date - status.ema.approval_date).days)
                if days_diff <= 365:
                    score += self.SCORE_WEIGHTS["fda_ema_concurrent"]
                    reasons.append("FDA+EMA 근접 승인")

        # 희귀의약품
        orphan_found = False
        for approval in [status.fda, status.ema, status.pmda, status.mfds]:
            if approval and approval.is_orphan:
                orphan_found = True
                break
        if orphan_found:
            score += self.SCORE_WEIGHTS["orphan_drug"]
            reasons.append("희귀의약품")

        # WHO EML
        if status.who_eml:
            score += self.SCORE_WEIGHTS["who_eml"]
            reasons.append("WHO 필수의약품")

        # 주요 질환
        indication_text = ""
        for approval in [status.fda, status.ema]:
            if approval and approval.indication:
                indication_text += " " + approval.indication.lower()

        if any(kw in indication_text for kw in self.MAJOR_DISEASE_KEYWORDS):
            score += self.SCORE_WEIGHTS["major_disease"]
            reasons.append("주요 질환 치료제")

        # 최대 100점으로 제한
        score = min(score, 100)

        return score, reasons

    def determine_level(self, score: int) -> HotIssueLevel:
        """점수로 등급 결정"""
        if score >= 80:
            return HotIssueLevel.HOT
        elif score >= 60:
            return HotIssueLevel.HIGH
        elif score >= 40:
            return HotIssueLevel.MID
        else:
            return HotIssueLevel.LOW


class GlobalStatusBuilder:
    """GlobalRegulatoryStatus 빌더"""

    def __init__(self):
        self.matcher = IngredientMatcher()
        self.scorer = HotIssueScorer()

    def build_from_fda_ema(
        self,
        fda_data: Optional[dict] = None,
        ema_data: Optional[dict] = None,
    ) -> GlobalRegulatoryStatus:
        """
        FDA + EMA 데이터로 GlobalRegulatoryStatus 생성

        Args:
            fda_data: FDA 파싱된 데이터
            ema_data: EMA 파싱된 데이터

        Returns:
            GlobalRegulatoryStatus
        """
        # INN 추출
        inn = ""
        if fda_data:
            inn = fda_data.get("generic_name", "") or fda_data.get("substance_name", [""])[0]
        if not inn and ema_data:
            inn = ema_data.get("inn", "") or ema_data.get("active_substance", "")

        normalized_name = self.matcher.normalize(inn)

        # ATC 코드
        atc_code = ""
        if ema_data:
            atc_code = ema_data.get("atc_code", "")

        # FDA 승인 정보 생성
        fda_approval = None
        if fda_data:
            fda_approval = self._build_fda_approval(fda_data)

        # EMA 승인 정보 생성
        ema_approval = None
        if ema_data:
            ema_approval = self._build_ema_approval(ema_data)

        # GlobalRegulatoryStatus 생성
        status = GlobalRegulatoryStatus(
            inn=inn,
            normalized_name=normalized_name,
            atc_code=atc_code,
            fda=fda_approval,
            ema=ema_approval,
        )

        # 스코어 계산
        score, reasons = self.scorer.calculate_score(status)
        status.global_score = score
        status.hot_issue_level = self.scorer.determine_level(score)
        status.hot_issue_reasons = reasons

        return status

    def _build_fda_approval(self, data: dict) -> RegulatoryApproval:
        """FDA 데이터에서 RegulatoryApproval 생성"""
        # 날짜 파싱
        approval_date = None
        date_str = data.get("submission_status_date", "")
        if date_str:
            try:
                approval_date = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                pass

        # 상태 결정
        status = ApprovalStatus.APPROVED
        submission_status = data.get("submission_status", "").lower()
        if "withdraw" in submission_status:
            status = ApprovalStatus.WITHDRAWN
        elif "pending" in submission_status:
            status = ApprovalStatus.PENDING

        # 특수 지정 확인
        submission_class = data.get("submission_class_code", "")
        pharm_class = " ".join(data.get("pharm_class", [])).lower()

        return RegulatoryApproval(
            agency="FDA",
            status=status,
            approval_date=approval_date,
            application_number=data.get("application_number", ""),
            brand_name=data.get("brand_name", ""),
            indication="",  # FDA 데이터에서 적응증 추출 필요
            is_orphan="orphan" in pharm_class,
            is_accelerated=submission_class in ["AA", "4"],  # Accelerated Approval
            is_breakthrough=submission_class == "5",  # Breakthrough
            is_priority=submission_class in ["1", "P"],  # Priority
            is_fast_track=False,  # 별도 데이터 필요
            source_url=data.get("source_url", ""),
            raw_data=data.get("raw", {}),
        )

    def from_ema(self, ema_data: dict) -> GlobalRegulatoryStatus:
        """EMA 데이터만으로 GlobalRegulatoryStatus 생성"""
        return self.build_from_fda_ema(None, ema_data)

    def from_fda(self, fda_data: dict) -> GlobalRegulatoryStatus:
        """FDA 데이터만으로 GlobalRegulatoryStatus 생성"""
        return self.build_from_fda_ema(fda_data, None)

    def _build_ema_approval(self, data: dict) -> RegulatoryApproval:
        """EMA 데이터에서 RegulatoryApproval 생성"""
        # 날짜 파싱
        approval_date = None
        date_str = data.get("marketing_authorisation_date") or data.get("approval_date", "")
        if date_str:
            try:
                approval_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        # 상태 결정
        medicine_status = data.get("medicine_status", "").lower()
        if medicine_status == "authorised":
            status = ApprovalStatus.APPROVED
        elif medicine_status == "withdrawn":
            status = ApprovalStatus.WITHDRAWN
        elif "pending" in medicine_status or "under" in medicine_status:
            status = ApprovalStatus.PENDING
        else:
            status = ApprovalStatus.UNKNOWN

        # 적응증 (첫 번째만)
        therapeutic_area = data.get("therapeutic_area", "")
        indication = therapeutic_area.split(";")[0].strip() if therapeutic_area else ""

        return RegulatoryApproval(
            agency="EMA",
            status=status,
            approval_date=approval_date,
            application_number=data.get("ema_product_number", ""),
            brand_name=data.get("name", ""),
            indication=indication,
            is_orphan=data.get("is_orphan", False),
            is_accelerated=data.get("is_accelerated", False),
            is_prime=data.get("is_prime", False),
            is_conditional=data.get("is_conditional", False),
            source_url=data.get("source_url", ""),
            raw_data=data.get("raw", {}),
        )

    def _build_mfds_approval(self, data: dict) -> RegulatoryApproval:
        """MFDS 데이터에서 RegulatoryApproval 생성"""
        # 날짜 파싱
        approval_date = None
        permit_date = data.get("permit_date")
        if permit_date:
            if isinstance(permit_date, date):
                approval_date = permit_date
            elif isinstance(permit_date, datetime):
                approval_date = permit_date.date()

        if not approval_date:
            date_str = data.get("permit_date_str", "")
            if date_str:
                try:
                    approval_date = datetime.strptime(date_str, "%Y%m%d").date()
                except ValueError:
                    pass

        # 상태 결정
        is_valid = data.get("is_valid", True)
        cancel_name = data.get("cancel_name", "")

        if is_valid and approval_date:
            status = ApprovalStatus.APPROVED
        elif "취소" in cancel_name or "철회" in cancel_name:
            status = ApprovalStatus.WITHDRAWN
        elif not approval_date:
            status = ApprovalStatus.PENDING
        else:
            status = ApprovalStatus.UNKNOWN

        # 적응증
        indication = data.get("indication", "")

        # 희귀/신속심사 (MFDS도 희귀의약품 지정 있음)
        is_orphan = data.get("is_orphan", False) or "희귀" in str(data.get("raw", {}))
        is_new_drug = data.get("is_new_drug", False)

        return RegulatoryApproval(
            agency="MFDS",
            status=status,
            approval_date=approval_date,
            application_number=data.get("item_seq", ""),
            brand_name=data.get("item_name", ""),
            indication=indication,
            is_orphan=is_orphan,
            is_accelerated=False,  # MFDS 신속심사는 별도 필드 필요
            source_url=data.get("source_url", ""),
            raw_data=data.get("raw", {}),
        )

    def build_from_all(
        self,
        fda_data: Optional[dict] = None,
        ema_data: Optional[dict] = None,
        mfds_data: Optional[dict] = None,
    ) -> GlobalRegulatoryStatus:
        """
        FDA + EMA + MFDS 데이터로 GlobalRegulatoryStatus 생성
        """
        # 기존 FDA+EMA 빌드
        status = self.build_from_fda_ema(fda_data, ema_data)

        # MFDS 추가
        if mfds_data:
            status.mfds = self._build_mfds_approval(mfds_data)

            # INN이 비어있으면 MFDS에서 가져오기
            if not status.inn:
                status.inn = mfds_data.get("main_ingredient", "")
                status.normalized_name = self.matcher.normalize(status.inn)

        # 스코어 재계산
        score, reasons = self.scorer.calculate_score(status)
        status.global_score = score
        status.hot_issue_level = self.scorer.determine_level(score)
        status.hot_issue_reasons = reasons

        return status

    def from_mfds(self, mfds_data: dict) -> GlobalRegulatoryStatus:
        """MFDS 데이터만으로 GlobalRegulatoryStatus 생성"""
        return self.build_from_all(None, None, mfds_data)


def merge_by_inn(
    fda_list: list[dict],
    ema_list: list[dict],
) -> list[GlobalRegulatoryStatus]:
    """
    INN 기준으로 FDA와 EMA 데이터 병합

    Args:
        fda_list: FDA 파싱된 데이터 목록
        ema_list: EMA 파싱된 데이터 목록

    Returns:
        GlobalRegulatoryStatus 목록
    """
    matcher = IngredientMatcher()
    builder = GlobalStatusBuilder()

    # EMA 데이터를 정규화된 INN으로 인덱싱
    ema_by_inn: dict[str, dict] = {}
    for ema_data in ema_list:
        inn = ema_data.get("inn", "") or ema_data.get("active_substance", "")
        if inn:
            normalized = matcher.normalize(inn)
            ema_by_inn[normalized] = ema_data

    # FDA 데이터와 매칭
    results = []
    matched_ema_inns = set()

    for fda_data in fda_list:
        inn = fda_data.get("generic_name", "") or ""
        if isinstance(fda_data.get("substance_name"), list):
            inn = fda_data["substance_name"][0] if fda_data["substance_name"] else inn

        if not inn:
            continue

        normalized = matcher.normalize(inn)

        # EMA 매칭
        ema_data = ema_by_inn.get(normalized)
        if ema_data:
            matched_ema_inns.add(normalized)

        status = builder.build_from_fda_ema(fda_data, ema_data)
        results.append(status)

    # 매칭되지 않은 EMA 데이터 추가
    for normalized, ema_data in ema_by_inn.items():
        if normalized not in matched_ema_inns:
            status = builder.build_from_fda_ema(None, ema_data)
            results.append(status)

    return results


def merge_global_status(
    fda_list: list[dict],
    ema_list: list[dict],
    mfds_list: list[dict],
) -> list[GlobalRegulatoryStatus]:
    """
    INN 기준으로 FDA, EMA, MFDS 데이터 병합

    Args:
        fda_list: FDA 파싱된 데이터 목록
        ema_list: EMA 파싱된 데이터 목록
        mfds_list: MFDS 파싱된 데이터 목록

    Returns:
        GlobalRegulatoryStatus 목록
    """
    matcher = IngredientMatcher()
    builder = GlobalStatusBuilder()

    # 각 데이터를 정규화된 INN으로 인덱싱
    fda_by_inn: dict[str, dict] = {}
    for fda_data in fda_list:
        inn = fda_data.get("generic_name", "") or ""
        if isinstance(fda_data.get("substance_name"), list):
            inn = fda_data["substance_name"][0] if fda_data["substance_name"] else inn
        if inn:
            normalized = matcher.normalize(inn)
            fda_by_inn[normalized] = fda_data

    ema_by_inn: dict[str, dict] = {}
    for ema_data in ema_list:
        inn = ema_data.get("inn", "") or ema_data.get("active_substance", "")
        if inn:
            normalized = matcher.normalize(inn)
            ema_by_inn[normalized] = ema_data

    mfds_by_inn: dict[str, dict] = {}
    for mfds_data in mfds_list:
        # MFDS는 main_ingredient 또는 ingredients 사용
        inn = mfds_data.get("main_ingredient", "")
        if not inn:
            ingredients = mfds_data.get("ingredients", [])
            inn = ingredients[0] if ingredients else ""
        if inn:
            normalized = matcher.normalize(inn)
            # MFDS는 같은 성분에 여러 제품이 있을 수 있으므로 첫 번째만 저장
            if normalized not in mfds_by_inn:
                mfds_by_inn[normalized] = mfds_data

    # 모든 INN 수집
    all_inns = set(fda_by_inn.keys()) | set(ema_by_inn.keys()) | set(mfds_by_inn.keys())

    results = []
    for normalized_inn in all_inns:
        fda_data = fda_by_inn.get(normalized_inn)
        ema_data = ema_by_inn.get(normalized_inn)
        mfds_data = mfds_by_inn.get(normalized_inn)

        status = builder.build_from_all(fda_data, ema_data, mfds_data)
        results.append(status)

    return results


def enrich_with_mfds(
    global_statuses: list[GlobalRegulatoryStatus],
    mfds_list: list[dict],
) -> list[GlobalRegulatoryStatus]:
    """
    기존 GlobalRegulatoryStatus 목록에 MFDS 데이터 추가

    Args:
        global_statuses: 기존 FDA+EMA 병합 결과
        mfds_list: MFDS 파싱된 데이터 목록

    Returns:
        MFDS가 추가된 GlobalRegulatoryStatus 목록
    """
    matcher = IngredientMatcher()
    builder = GlobalStatusBuilder()

    # MFDS 인덱싱
    mfds_by_inn: dict[str, dict] = {}
    for mfds_data in mfds_list:
        inn = mfds_data.get("main_ingredient", "")
        if not inn:
            ingredients = mfds_data.get("ingredients", [])
            inn = ingredients[0] if ingredients else ""
        if inn:
            normalized = matcher.normalize(inn)
            if normalized not in mfds_by_inn:
                mfds_by_inn[normalized] = mfds_data

    # 기존 상태에 MFDS 추가
    for status in global_statuses:
        normalized = matcher.normalize(status.inn)
        mfds_data = mfds_by_inn.get(normalized)

        if mfds_data and not status.mfds:
            status.mfds = builder._build_mfds_approval(mfds_data)

            # 스코어 재계산
            score, reasons = builder.scorer.calculate_score(status)
            status.global_score = score
            status.hot_issue_level = builder.scorer.determine_level(score)
            status.hot_issue_reasons = reasons

    return global_statuses
