"""Timeline 모델 및 빌더

FDA → MFDS → HIRA 시간축 데이터 모델
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class FDAInfo:
    """FDA 승인 정보"""
    approval_date: Optional[date] = None
    application_number: str = ""
    brand_name: str = ""
    generic_name: str = ""
    indication: str = ""
    submission_type: str = ""  # ORIG, SUPPL 등


@dataclass
class MFDSInfo:
    """MFDS (식약처) 허가 정보"""
    permit_date: Optional[date] = None
    item_seq: str = ""
    item_name: str = ""
    ingredient_name: str = ""
    company: str = ""
    cancel_status: str = "정상"


@dataclass
class HIRAInfo:
    """HIRA 급여 정보"""
    coverage_date: Optional[date] = None
    notification_number: str = ""  # 고시번호
    product_code: str = ""
    product_name: str = ""
    atc_code: str = ""
    criteria_summary: str = ""


@dataclass
class DrugTimeline:
    """약물 시간축 통합 모델"""

    # 정규화된 성분명 (매칭 키)
    ingredient_normalized: str = ""
    ingredient_name_en: str = ""
    ingredient_name_kr: str = ""

    # 각 단계 정보
    fda: FDAInfo = field(default_factory=FDAInfo)
    mfds: MFDSInfo = field(default_factory=MFDSInfo)
    hira: HIRAInfo = field(default_factory=HIRAInfo)

    # 분석 결과
    @property
    def fda_to_mfds_days(self) -> Optional[int]:
        """FDA 승인 → MFDS 허가 소요일"""
        if self.fda.approval_date and self.mfds.permit_date:
            return (self.mfds.permit_date - self.fda.approval_date).days
        return None

    @property
    def mfds_to_hira_days(self) -> Optional[int]:
        """MFDS 허가 → HIRA 급여 소요일"""
        if self.mfds.permit_date and self.hira.coverage_date:
            return (self.hira.coverage_date - self.mfds.permit_date).days
        return None

    @property
    def total_days(self) -> Optional[int]:
        """FDA 승인 → HIRA 급여 총 소요일"""
        if self.fda.approval_date and self.hira.coverage_date:
            return (self.hira.coverage_date - self.fda.approval_date).days
        return None

    @property
    def status(self) -> str:
        """현재 상태"""
        if self.hira.coverage_date:
            return "COVERED"  # 급여 등재
        elif self.mfds.permit_date:
            return "MFDS_APPROVED"  # MFDS 허가, 급여 미등재
        elif self.fda.approval_date:
            return "FDA_ONLY"  # FDA만 승인
        return "UNKNOWN"

    def to_dict(self) -> dict:
        """딕셔너리 변환"""
        return {
            "ingredient": {
                "normalized": self.ingredient_normalized,
                "en": self.ingredient_name_en,
                "kr": self.ingredient_name_kr,
            },
            "fda": {
                "approval_date": self.fda.approval_date.isoformat() if self.fda.approval_date else None,
                "application_number": self.fda.application_number,
                "brand_name": self.fda.brand_name,
                "generic_name": self.fda.generic_name,
                "indication": self.fda.indication,
            },
            "mfds": {
                "permit_date": self.mfds.permit_date.isoformat() if self.mfds.permit_date else None,
                "item_seq": self.mfds.item_seq,
                "item_name": self.mfds.item_name,
                "company": self.mfds.company,
            },
            "hira": {
                "coverage_date": self.hira.coverage_date.isoformat() if self.hira.coverage_date else None,
                "notification_number": self.hira.notification_number,
                "atc_code": self.hira.atc_code,
                "product_name": self.hira.product_name,
            },
            "analysis": {
                "status": self.status,
                "fda_to_mfds_days": self.fda_to_mfds_days,
                "mfds_to_hira_days": self.mfds_to_hira_days,
                "total_days": self.total_days,
            },
        }


class TimelineBuilder:
    """Timeline 생성 헬퍼"""

    def __init__(self):
        self._timeline = DrugTimeline()

    def with_ingredient(
        self,
        normalized: str,
        en: str = "",
        kr: str = "",
    ) -> TimelineBuilder:
        """성분명 설정"""
        self._timeline.ingredient_normalized = normalized
        self._timeline.ingredient_name_en = en or normalized
        self._timeline.ingredient_name_kr = kr
        return self

    def with_fda(
        self,
        approval_date: Optional[date | str] = None,
        application_number: str = "",
        brand_name: str = "",
        generic_name: str = "",
        indication: str = "",
        submission_type: str = "",
    ) -> TimelineBuilder:
        """FDA 정보 설정"""
        if isinstance(approval_date, str):
            approval_date = self._parse_date(approval_date)

        self._timeline.fda = FDAInfo(
            approval_date=approval_date,
            application_number=application_number,
            brand_name=brand_name,
            generic_name=generic_name,
            indication=indication,
            submission_type=submission_type,
        )
        return self

    def with_mfds(
        self,
        permit_date: Optional[date | str] = None,
        item_seq: str = "",
        item_name: str = "",
        ingredient_name: str = "",
        company: str = "",
    ) -> TimelineBuilder:
        """MFDS 정보 설정"""
        if isinstance(permit_date, str):
            permit_date = self._parse_date(permit_date)

        self._timeline.mfds = MFDSInfo(
            permit_date=permit_date,
            item_seq=item_seq,
            item_name=item_name,
            ingredient_name=ingredient_name,
            company=company,
        )
        return self

    def with_hira(
        self,
        coverage_date: Optional[date | str] = None,
        notification_number: str = "",
        product_code: str = "",
        product_name: str = "",
        atc_code: str = "",
        criteria_summary: str = "",
    ) -> TimelineBuilder:
        """HIRA 정보 설정"""
        if isinstance(coverage_date, str):
            coverage_date = self._parse_date(coverage_date)

        self._timeline.hira = HIRAInfo(
            coverage_date=coverage_date,
            notification_number=notification_number,
            product_code=product_code,
            product_name=product_name,
            atc_code=atc_code,
            criteria_summary=criteria_summary,
        )
        return self

    def build(self) -> DrugTimeline:
        """Timeline 생성"""
        return self._timeline

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        # 다양한 포맷 지원
        for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y.%m.%d", "%Y/%m/%d"]:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
