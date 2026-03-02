"""FDA 응답 파서"""

import logging
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FDADrugParser:
    """FDA Drug 응답 파서"""

    def parse_approval(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        FDA 응답을 중간 형식으로 변환

        Args:
            raw: openFDA API 응답의 단일 결과

        Returns:
            정규화된 dict
        """
        # 기본 정보
        app_number = raw.get("application_number", "")
        sponsor = raw.get("sponsor_name", "")

        # Products 정보 추출
        products = raw.get("products", [])
        brand_name, generic_name, dosage_form = self._extract_product_info(products)

        # Submissions 정보 추출 (가장 최근)
        submissions = raw.get("submissions", [])
        submission_info = self._extract_latest_submission(submissions)

        # OpenFDA 정보 (적응증 등)
        openfda = raw.get("openfda", {})

        return {
            # 식별
            "application_number": app_number,
            "source_id": app_number,

            # 제품 정보
            "brand_name": brand_name,
            "generic_name": generic_name,
            "dosage_form": dosage_form,
            "sponsor": sponsor,

            # Submission 정보
            "submission_type": submission_info.get("submission_type"),
            "submission_status": submission_info.get("submission_status"),
            "submission_status_date": submission_info.get("submission_status_date"),
            "submission_class_code": submission_info.get("submission_class_code"),
            "submission_class_code_description": submission_info.get("submission_class_code_description"),

            # OpenFDA
            "manufacturer_name": openfda.get("manufacturer_name", [None])[0],
            "route": openfda.get("route", []),
            "substance_name": openfda.get("substance_name", []),
            "pharm_class": openfda.get("pharm_class_epc", []),  # 약리학적 분류

            # URL
            "source_url": self._build_source_url(app_number),

            # 원본
            "raw": raw,
        }

    def _extract_product_info(
        self, products: list[dict]
    ) -> tuple[str, str, str]:
        """
        Products에서 브랜드명, 성분명, 제형 추출

        가장 첫 번째 활성 제품 사용
        """
        if not products:
            return ("", "", "")

        # 활성 제품 찾기
        active_products = [
            p for p in products
            if p.get("marketing_status") == "Prescription"
            or p.get("marketing_status") == "Over-the-counter"
        ]

        product = active_products[0] if active_products else products[0]

        brand_name = product.get("brand_name", "")
        active_ingredients = product.get("active_ingredients", [])

        # 성분명 추출
        generic_names = [
            ing.get("name", "")
            for ing in active_ingredients
        ]
        generic_name = ", ".join(generic_names) if generic_names else ""

        dosage_form = product.get("dosage_form", "")

        return (brand_name, generic_name, dosage_form)

    @staticmethod
    def _validate_date(date_str: str) -> bool:
        """submission_status_date 유효성 검증.

        Returns:
            True if valid, False if invalid (future, before 1985, unparseable)
        """
        if not date_str:
            return False
        try:
            dt = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            logger.warning("FDA 날짜 파싱 불가: '%s'", date_str)
            return False

        if dt > date.today():
            logger.warning("FDA 미래 날짜 스킵: %s", date_str)
            return False
        if dt.year < 1985:
            logger.warning("FDA 1985년 이전 날짜 스킵: %s", date_str)
            return False

        return True

    def _extract_latest_submission(
        self, submissions: list[dict]
    ) -> dict[str, Any]:
        """
        최초 승인(ORIG+AP) 우선으로 submission 추출.

        우선순위:
          1) ORIG + AP (최초 승인) — 유효 날짜, 날짜 내림차순
          2) 아무 AP (sNDA 승인 등) — 유효 날짜, 날짜 내림차순
          3) 가장 최근 submission (fallback)
        """
        if not submissions:
            return {}

        # 유효 날짜를 가진 submission만 필터
        valid_subs = [
            s for s in submissions
            if self._validate_date(s.get("submission_status_date", ""))
        ]

        by_date_desc = sorted(
            valid_subs if valid_subs else submissions,
            key=lambda x: x.get("submission_status_date", ""),
            reverse=True,
        )

        # 1차: ORIG + AP
        for sub in by_date_desc:
            if sub.get("submission_type") == "ORIG" and sub.get("submission_status") == "AP":
                return self._format_submission(sub)

        # 2차: 아무 AP
        for sub in by_date_desc:
            if sub.get("submission_status") == "AP":
                return self._format_submission(sub)

        # 3차: fallback (가장 최근)
        return self._format_submission(by_date_desc[0])

    @staticmethod
    def _format_submission(sub: dict) -> dict[str, Any]:
        """단일 submission → 표준 dict"""
        return {
            "submission_type": sub.get("submission_type"),
            "submission_status": sub.get("submission_status"),
            "submission_status_date": sub.get("submission_status_date"),
            "submission_class_code": sub.get("submission_class_code"),
            "submission_class_code_description": sub.get("submission_class_code_description"),
        }

    def _build_source_url(self, app_number: str) -> str:
        """FDA DAF URL 생성"""
        if not app_number:
            return ""

        # NDA, BLA, ANDA 구분
        app_num_only = "".join(filter(str.isdigit, app_number))

        return f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={app_num_only}"

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_approval(raw) for raw in raw_list]
