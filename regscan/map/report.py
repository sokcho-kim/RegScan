"""FDA→KR 매핑 리포트 생성기

전문가용 리포트 포맷 생성
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .timeline import DrugTimeline
from .matcher import DrugMatcher, MFDSProduct, ATCMapping, HIRANotification


@dataclass
class ReportItem:
    """리포트 항목"""
    # 기본 정보
    brand_name: str
    generic_name: str
    ingredient: str

    # FDA 정보
    fda_approval_date: Optional[date]
    fda_application_number: str
    fda_submission_type: str
    indication: str
    pharm_class: list[str]

    # 국내 상태
    mfds_status: str  # "허가됨", "미허가"
    mfds_permit_date: Optional[date]
    mfds_product_name: str

    hira_status: str  # "기존급여", "신규급여", "미등재"
    hira_atc_code: str
    hira_notification: str

    # 분석
    report_priority: str  # "HIGH", "MID", "LOW"
    key_insight: str

    # 핫 이슈
    is_hot_issue: bool = False
    hot_issue_reasons: list[str] = field(default_factory=list)


class HotIssueDetector:
    """글로벌 핫 이슈 판별"""

    # FDA 특별 지정 (높은 관심도)
    SPECIAL_DESIGNATIONS = [
        "breakthrough therapy",
        "priority review",
        "fast track",
        "accelerated approval",
        "orphan drug",
    ]

    # 핫 이슈 치료 분야
    HOT_THERAPEUTIC_AREAS = {
        "oncology": ["antineoplastic", "cancer", "tumor", "leukemia", "lymphoma", "carcinoma"],
        "alzheimer": ["alzheimer", "dementia", "amyloid", "tau"],
        "obesity": ["obesity", "weight loss", "glp-1", "semaglutide", "tirzepatide"],
        "gene_therapy": ["gene therapy", "car-t", "cell therapy", "aav"],
        "rare_disease": ["orphan", "rare disease", "ultra-rare"],
        "immunotherapy": ["immunotherapy", "checkpoint inhibitor", "pd-1", "pd-l1", "ctla-4"],
    }

    def detect(self, fda_data: dict) -> tuple[bool, list[str]]:
        """
        글로벌 핫 이슈 여부 판별

        Args:
            fda_data: FDA 파서 출력

        Returns:
            (is_hot_issue, reasons)
        """
        reasons = []

        app_number = fda_data.get("application_number", "")
        sub_type = fda_data.get("submission_type", "")
        pharm_class = fda_data.get("pharm_class", [])
        products = fda_data.get("products", [])

        # 1. BLA (바이오의약품) 체크
        if "BLA" in app_number:
            reasons.append("바이오의약품 (BLA)")

        # 2. 신약 여부
        if sub_type == "ORIG":
            reasons.append("신약 (Original Application)")

        # 3. pharm_class에서 핫 분야 검색
        pharm_text = " ".join(pharm_class).lower()
        for area, keywords in self.HOT_THERAPEUTIC_AREAS.items():
            if any(kw in pharm_text for kw in keywords):
                area_names = {
                    "oncology": "항암제",
                    "alzheimer": "알츠하이머/치매",
                    "obesity": "비만/대사",
                    "gene_therapy": "유전자/세포치료",
                    "rare_disease": "희귀질환",
                    "immunotherapy": "면역항암제",
                }
                reasons.append(f"핫 분야: {area_names.get(area, area)}")
                break

        # 4. 제품 정보에서 특별 지정 체크
        for product in products:
            marketing_status = str(product.get("marketing_status", "")).lower()
            for designation in self.SPECIAL_DESIGNATIONS:
                if designation in marketing_status:
                    reasons.append(f"FDA 특별지정: {designation}")
                    break

        is_hot = len(reasons) >= 2  # 2개 이상 조건 충족시 핫 이슈

        return is_hot, reasons


class FDAKRReportGenerator:
    """FDA→KR 매핑 리포트 생성기"""

    def __init__(self, matcher: DrugMatcher):
        self.matcher = matcher
        self.hot_detector = HotIssueDetector()

    def analyze(self, fda_data: dict) -> ReportItem:
        """
        FDA 데이터 분석하여 리포트 항목 생성

        Args:
            fda_data: FDA 파서 출력

        Returns:
            ReportItem
        """
        # 기본 정보 추출
        brand_name = fda_data.get("brand_name", "")
        generic_name = fda_data.get("generic_name", "")
        substances = fda_data.get("substance_name", [])
        ingredient = substances[0] if substances else generic_name

        fda_date_str = fda_data.get("submission_status_date", "")
        fda_date = self._parse_date(fda_date_str)

        app_number = fda_data.get("application_number", "")
        sub_type = fda_data.get("submission_type", "")
        pharm_class = fda_data.get("pharm_class", [])

        # 국내 상태 확인
        mfds_status = "미허가"
        mfds_date = None
        mfds_product = ""

        if ingredient:
            mfds_results = self.matcher.find_mfds_by_ingredient(ingredient)
            if mfds_results:
                mfds_status = "허가됨"
                mfds_date = mfds_results[0].permit_date
                mfds_product = mfds_results[0].item_name

        # HIRA 상태 확인
        hira_status = "미등재"
        atc_code = ""
        notification = ""

        if ingredient:
            atc_results = self.matcher.find_atc_by_ingredient(ingredient)
            if atc_results:
                hira_status = "기존급여"
                atc_code = atc_results[0].atc_code
            else:
                hira_results = self.matcher.find_hira_by_ingredient(ingredient)
                if hira_results:
                    hira_status = "신규급여"
                    notification = hira_results[0].notification_number

        # 핫 이슈 판별
        is_hot, hot_reasons = self.hot_detector.detect(fda_data)

        # 우선순위 및 인사이트 결정
        priority, insight = self._determine_priority(
            mfds_status, hira_status, sub_type, app_number, pharm_class, is_hot
        )

        return ReportItem(
            brand_name=brand_name,
            generic_name=generic_name,
            ingredient=ingredient,
            fda_approval_date=fda_date,
            fda_application_number=app_number,
            fda_submission_type=sub_type,
            indication="",  # TODO: FDA 적응증 추출
            pharm_class=pharm_class,
            mfds_status=mfds_status,
            mfds_permit_date=mfds_date,
            mfds_product_name=mfds_product,
            hira_status=hira_status,
            hira_atc_code=atc_code,
            hira_notification=notification,
            report_priority=priority,
            key_insight=insight,
            is_hot_issue=is_hot,
            hot_issue_reasons=hot_reasons,
        )

    def _determine_priority(
        self,
        mfds_status: str,
        hira_status: str,
        sub_type: str,
        app_number: str,
        pharm_class: list[str],
        is_hot_issue: bool = False,
    ) -> tuple[str, str]:
        """우선순위 및 인사이트 결정"""

        is_bla = "BLA" in app_number
        is_new = sub_type == "ORIG"
        is_cancer = any("antineoplastic" in p.lower() or "cancer" in p.lower() for p in pharm_class)

        # 우선순위 결정
        if mfds_status == "미허가" and (is_bla or is_cancer or is_hot_issue):
            priority = "HIGH"
            insight = "국내 미허가 신약 - 허가 동향 모니터링 필요"
            if is_hot_issue:
                insight = "🔥 글로벌 핫이슈, " + insight
        elif mfds_status == "허가됨" and hira_status == "미등재":
            priority = "HIGH"
            insight = "국내 허가됨, 급여 미등재 - 급여 등재 가능성 검토"
        elif hira_status == "신규급여":
            priority = "HIGH"
            insight = "신규 급여 등재 - 급여기준 확인 필요"
        elif mfds_status == "미허가":
            priority = "MID"
            insight = "국내 미허가 - 향후 허가 신청 가능성"
            if is_hot_issue:
                priority = "HIGH"
                insight = "🔥 글로벌 핫이슈, " + insight
        else:
            priority = "LOW"
            insight = "국내 허가/급여 완료"

        return priority, insight

    def generate_text_report(self, item: ReportItem) -> str:
        """텍스트 리포트 생성"""

        # 헤더
        hot_badge = " 🔥" if item.is_hot_issue else ""
        lines = [
            "━" * 50,
            f"📋 FDA→KR 매핑 리포트{hot_badge}",
            "━" * 50,
            "",
            f"약물명: {item.brand_name} ({item.ingredient})",
        ]

        # 핫 이슈 표시
        if item.is_hot_issue and item.hot_issue_reasons:
            lines.append(f"🔥 글로벌 핫이슈: {', '.join(item.hot_issue_reasons)}")

        # FDA 정보
        fda_date = item.fda_approval_date.strftime("%Y-%m-%d") if item.fda_approval_date else "N/A"
        lines.extend([
            f"FDA 승인: {fda_date} ({item.fda_application_number}, {item.fda_submission_type})",
        ])

        if item.pharm_class:
            lines.append(f"분류: {item.pharm_class[0][:50]}")

        lines.append("")

        # 국내 현황 박스
        lines.extend([
            "┌" + "─" * 48 + "┐",
            "│ 국내 현황" + " " * 38 + "│",
            "├" + "─" * 48 + "┤",
        ])

        # MFDS 상태
        if item.mfds_status == "허가됨":
            mfds_line = f"│ MFDS 허가: ✅ {item.mfds_permit_date} "
            mfds_line += " " * (48 - len(mfds_line) + 1) + "│"
        else:
            mfds_line = "│ MFDS 허가: ❌ 미허가" + " " * 27 + "│"
        lines.append(mfds_line)

        # HIRA 상태
        if item.hira_status == "기존급여":
            hira_line = f"│ HIRA 급여: ✅ 기존급여 ({item.hira_atc_code})"
            hira_line += " " * (49 - len(hira_line)) + "│"
        elif item.hira_status == "신규급여":
            hira_line = f"│ HIRA 급여: ⭐ 신규급여 ({item.hira_notification})"
            hira_line += " " * (49 - len(hira_line)) + "│"
        else:
            hira_line = "│ HIRA 급여: ⏳ 미등재" + " " * 27 + "│"
        lines.append(hira_line)

        lines.append("└" + "─" * 48 + "┘")
        lines.append("")

        # 인사이트
        priority_emoji = {"HIGH": "🔴", "MID": "🟡", "LOW": "🟢"}[item.report_priority]
        lines.extend([
            f"{priority_emoji} 우선순위: {item.report_priority}",
            f"💡 시사점: {item.key_insight}",
            "",
            "━" * 50,
        ])

        return "\n".join(lines)

    def generate_summary_table(self, items: list[ReportItem]) -> str:
        """요약 테이블 생성"""

        lines = [
            "## FDA 승인 → 국내 현황 요약",
            "",
            "| 우선순위 | 약물 | FDA 승인 | MFDS | HIRA | 시사점 |",
            "|:--------:|------|----------|------|------|--------|",
        ]

        # 우선순위순 정렬
        priority_order = {"HIGH": 0, "MID": 1, "LOW": 2}
        sorted_items = sorted(items, key=lambda x: priority_order.get(x.report_priority, 3))

        for item in sorted_items:
            fda_date = item.fda_approval_date.strftime("%m-%d") if item.fda_approval_date else "N/A"
            mfds = "✅" if item.mfds_status == "허가됨" else "❌"

            if item.hira_status == "기존급여":
                hira = f"✅ {item.hira_atc_code}"
            elif item.hira_status == "신규급여":
                hira = "⭐ 신규"
            else:
                hira = "⏳"

            priority_emoji = {"HIGH": "🔴", "MID": "🟡", "LOW": "🟢"}[item.report_priority]
            hot_badge = "🔥" if item.is_hot_issue else ""
            name_display = f"{hot_badge}{item.brand_name[:13]}" if hot_badge else item.brand_name[:15]

            lines.append(
                f"| {priority_emoji} {item.report_priority} | {name_display} | {fda_date} | {mfds} | {hira} | {item.key_insight[:20]}... |"
            )

        return "\n".join(lines)

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """날짜 파싱"""
        if not date_str:
            return None

        for fmt in ["%Y%m%d", "%Y-%m-%d"]:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
