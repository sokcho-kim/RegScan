"""FDA Safety (Label + Enforcement) 파서

Label → INN, brand, boxed_warning_text 추출
Enforcement → recall_number, classification, reason 추출
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FDASafetyParser:
    """FDA Safety 데이터 파서"""

    def parse_label(self, raw: dict[str, Any]) -> dict[str, Any]:
        """단일 라벨 레코드 파싱

        Returns:
            {inn, brand_name, boxed_warning_text, effective_date, source_type}
        """
        openfda = raw.get("openfda", {})

        # INN 추출
        generic_names = openfda.get("generic_name", [])
        substance_names = openfda.get("substance_name", [])
        inn = generic_names[0] if generic_names else (
            substance_names[0] if substance_names else ""
        )

        # Brand name
        brand_names = openfda.get("brand_name", [])
        brand_name = brand_names[0] if brand_names else ""

        # Boxed Warning
        boxed_warning_list = raw.get("boxed_warning", [])
        boxed_warning_text = boxed_warning_list[0] if boxed_warning_list else ""

        return {
            "inn": inn,
            "brand_name": brand_name,
            "boxed_warning_text": boxed_warning_text[:500],  # 길이 제한
            "effective_date": raw.get("effective_time", ""),
            "application_number": openfda.get("application_number", [""])[0] if openfda.get("application_number") else "",
            "source_type": "fda_label",
        }

    def parse_enforcement(self, raw: dict[str, Any]) -> dict[str, Any]:
        """단일 enforcement 레코드 파싱

        Returns:
            {inn, brand_name, recall_number, classification, reason, status, report_date, source_type}
        """
        openfda = raw.get("openfda", {})

        generic_names = openfda.get("generic_name", [])
        substance_names = openfda.get("substance_name", [])
        inn = generic_names[0] if generic_names else (
            substance_names[0] if substance_names else ""
        )

        brand_names = openfda.get("brand_name", [])
        brand_name = brand_names[0] if brand_names else raw.get("product_description", "")[:100]

        return {
            "inn": inn,
            "brand_name": brand_name,
            "recall_number": raw.get("recall_number", ""),
            "classification": raw.get("classification", ""),
            "reason": raw.get("reason_for_recall", "")[:300],
            "status": raw.get("status", ""),
            "report_date": raw.get("report_date", ""),
            "voluntary_mandated": raw.get("voluntary_mandated", ""),
            "source_type": "fda_enforcement",
        }

    def parse_many(
        self,
        raw_labels: list[dict] | None = None,
        raw_enforcements: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """여러 레코드 일괄 파싱

        Returns:
            파싱된 레코드 목록
        """
        results: list[dict[str, Any]] = []

        for raw in (raw_labels or []):
            try:
                parsed = self.parse_label(raw)
                if parsed["inn"]:
                    results.append(parsed)
            except Exception as e:
                logger.debug("Label 파싱 실패: %s", e)

        for raw in (raw_enforcements or []):
            try:
                parsed = self.parse_enforcement(raw)
                if parsed["inn"] or parsed["recall_number"]:
                    results.append(parsed)
            except Exception as e:
                logger.debug("Enforcement 파싱 실패: %s", e)

        return results
