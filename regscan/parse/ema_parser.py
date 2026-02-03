"""EMA 응답 파서"""

from datetime import datetime
from typing import Any, Optional


def parse_ema_date(date_str: str) -> str:
    """
    EMA 날짜 형식(DD/MM/YYYY)을 ISO 형식(YYYY-MM-DD)으로 변환

    Args:
        date_str: EMA 날짜 문자열 (예: "19/01/2026")

    Returns:
        ISO 형식 날짜 문자열 (예: "2026-01-19")
    """
    if not date_str:
        return ""

    try:
        # DD/MM/YYYY 형식
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3:
                day, month, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        return date_str
    except Exception:
        return date_str


class EMAMedicineParser:
    """EMA 의약품 응답 파서"""

    def parse_medicine(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        EMA 의약품 응답을 중간 형식으로 변환

        Args:
            raw: EMA API 응답의 단일 결과

        Returns:
            정규화된 dict
        """
        # 기본 정보
        name = raw.get("name_of_medicine", "")
        ema_number = raw.get("ema_product_number", "")

        # INN (International Nonproprietary Name) - 실제 필드명 사용
        inn = raw.get("international_non_proprietary_name_common_name", "")
        active_substance = raw.get("active_substance", "")

        # 상태
        medicine_status = raw.get("medicine_status", "")
        opinion_status = raw.get("opinion_status", "")

        # 분류 - 실제 필드명 사용
        atc_code = raw.get("atc_code_human", "") or raw.get("atcvet_code_veterinary", "")
        therapeutic_area = raw.get("therapeutic_area_mesh", "")
        pharm_group = raw.get("pharmacotherapeutic_group_human", "") or raw.get("pharmacotherapeutic_group_veterinary", "")

        # 날짜 - DD/MM/YYYY → YYYY-MM-DD 변환
        ec_decision_date_raw = raw.get("european_commission_decision_date", "")
        opinion_date_raw = raw.get("opinion_adopted_date", "")
        ma_date_raw = raw.get("marketing_authorisation_date", "")

        ec_decision_date = parse_ema_date(ec_decision_date_raw)
        opinion_date = parse_ema_date(opinion_date_raw)
        ma_date = parse_ema_date(ma_date_raw)

        # 기타 - 실제 필드명 사용
        mah = raw.get("marketing_authorisation_developer_applicant_holder", "")
        indication = raw.get("therapeutic_indication", "")
        category = raw.get("category", "")  # Human, Veterinary

        # URL
        medicine_url = raw.get("medicine_url", "")

        return {
            # 식별
            "ema_product_number": ema_number,
            "source_id": ema_number,

            # 제품 정보
            "name": name,
            "inn": inn,
            "active_substance": active_substance,
            "brand_name": name,  # FDA 호환
            "generic_name": inn or active_substance,  # FDA 호환

            # 상태
            "medicine_status": medicine_status,
            "opinion_status": opinion_status,
            "is_authorized": medicine_status.lower() == "authorised" if medicine_status else False,

            # 분류
            "atc_code": atc_code,
            "therapeutic_area": therapeutic_area,
            "pharmacotherapeutic_group": pharm_group,
            "category": category,

            # 날짜 (ISO 형식)
            "ec_decision_date": ec_decision_date,
            "opinion_date": opinion_date,
            "marketing_authorisation_date": ma_date,
            "approval_date": ma_date or ec_decision_date,  # FDA 호환 - 최초 승인일 우선

            # MAH (Marketing Authorisation Holder)
            "mah": mah,
            "sponsor": mah,  # FDA 호환

            # 적응증
            "therapeutic_indication": indication,

            # 특수 지정
            "is_orphan": self._check_yes_no(raw, "orphan_medicine"),
            "is_biosimilar": self._check_yes_no(raw, "biosimilar"),
            "is_generic": self._check_yes_no(raw, "generic_or_hybrid"),
            "is_conditional": self._check_yes_no(raw, "conditional_approval"),
            "is_accelerated": self._check_yes_no(raw, "accelerated_assessment"),
            "is_prime": self._check_yes_no(raw, "prime_priority_medicine"),
            "is_advanced_therapy": self._check_yes_no(raw, "advanced_therapy"),

            # URL
            "source_url": medicine_url if medicine_url else self._build_source_url(ema_number),

            # 원본
            "raw": raw,
        }

    def _check_yes_no(self, raw: dict, field: str) -> bool:
        """Yes/No 필드 확인"""
        value = raw.get(field, "")
        return str(value).lower() in ("yes", "true", "1")

    def _check_orphan(self, raw: dict) -> bool:
        """희귀의약품 여부 확인 (deprecated, use _check_yes_no)"""
        return self._check_yes_no(raw, "orphan_medicine")

    def _check_biosimilar(self, raw: dict) -> bool:
        """바이오시밀러 여부 확인 (deprecated, use _check_yes_no)"""
        return self._check_yes_no(raw, "biosimilar")

    def _check_generic(self, raw: dict) -> bool:
        """제네릭 여부 확인 (deprecated, use _check_yes_no)"""
        return self._check_yes_no(raw, "generic_or_hybrid")

    def _check_conditional(self, raw: dict) -> bool:
        """조건부 승인 여부 확인 (deprecated, use _check_yes_no)"""
        return self._check_yes_no(raw, "conditional_approval")

    def _build_source_url(self, ema_number: str) -> str:
        """EMA 제품 페이지 URL 생성"""
        if not ema_number:
            return ""
        # EMA 제품 번호로 URL 생성
        return f"https://www.ema.europa.eu/en/medicines/human/EPAR/{ema_number}"

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_medicine(raw) for raw in raw_list]


class EMAOrphanParser:
    """EMA 희귀의약품 지정 파서"""

    def parse_orphan(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        희귀의약품 지정 응답 파싱

        Args:
            raw: EMA API 응답의 단일 결과

        Returns:
            정규화된 dict
        """
        medicine_name = raw.get("medicine_name", "")
        active_substance = raw.get("active_substance", "")
        designation_date_raw = raw.get("date_of_designation_or_refusal", "")
        intended_use = raw.get("intended_use", "")
        eu_number = raw.get("eu_designation_number", "")
        status = raw.get("status", "")
        related_ema = raw.get("related_ema_product_number", "")

        # 이름: medicine_name이 있으면 사용, 없으면 active_substance
        name = medicine_name if medicine_name else active_substance

        # 날짜 변환
        designation_date = parse_ema_date(designation_date_raw)

        return {
            # 식별
            "eu_designation_number": eu_number,
            "source_id": eu_number,
            "related_ema_product_number": related_ema,

            # 제품 정보
            "name": name,
            "medicine_name": medicine_name,
            "active_substance": active_substance,
            "inn": active_substance,  # 호환용
            "generic_name": active_substance,  # 호환용

            # 지정 정보
            "designation_date": designation_date,
            "intended_use": intended_use,
            "therapeutic_area": intended_use,  # 호환용
            "status": status,
            "is_designated": status.lower() in ("positive", "positive opinion") if status else False,

            # URL
            "source_url": raw.get("orphan_designation_url", ""),

            # 원본
            "raw": raw,
        }

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_orphan(raw) for raw in raw_list]


class EMAShortageParser:
    """EMA 공급 부족 파서"""

    def parse_shortage(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        공급 부족 응답 파싱

        Args:
            raw: EMA API 응답의 단일 결과

        Returns:
            정규화된 dict
        """
        medicine = raw.get("medicine_affected", "")
        status = raw.get("supply_shortage_status", "")
        inn = raw.get("INN", "") or raw.get("inn", "")
        therapeutic_area = raw.get("therapeutic_area_mesh", "")
        forms_affected = raw.get("pharmaceutical_forms_affected", "")
        strengths_affected = raw.get("strengths_affected", "")
        alternatives = raw.get("availability_of_alternatives", "")
        start_date = raw.get("start_of_shortage_date", "")
        expected_resolution = raw.get("expected_resolution_date", "")

        return {
            # 식별
            "source_id": f"shortage_{medicine}_{start_date}".replace(" ", "_"),

            # 의약품 정보
            "medicine_affected": medicine,
            "inn": inn,
            "therapeutic_area": therapeutic_area,

            # 부족 정보
            "shortage_status": status,
            "is_ongoing": "ongoing" in status.lower() if status else False,
            "forms_affected": forms_affected,
            "strengths_affected": strengths_affected,
            "alternatives_available": alternatives,

            # 날짜
            "start_date": start_date,
            "expected_resolution_date": expected_resolution,

            # URL
            "source_url": raw.get("shortage_url", ""),

            # 원본
            "raw": raw,
        }

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_shortage(raw) for raw in raw_list]


class EMADHPCParser:
    """EMA DHPC (Direct Healthcare Professional Communications) 파서"""

    def parse_dhpc(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        DHPC 응답 파싱

        Args:
            raw: EMA API 응답의 단일 결과

        Returns:
            정규화된 dict
        """
        name = raw.get("name_of_medicine", "")
        procedure_number = raw.get("procedure_number", "")
        active_substances = raw.get("active_substances", "")
        dhpc_type = raw.get("dhpc_type", "")
        regulatory_outcome = raw.get("regulatory_outcome", "")
        atc_code = raw.get("atc_code_human", "")
        therapeutic_area = raw.get("therapeutic_area_mesh", "")
        dissemination_date = raw.get("dissemination_date", "")

        return {
            # 식별
            "procedure_number": procedure_number,
            "source_id": procedure_number or f"dhpc_{name}_{dissemination_date}".replace(" ", "_"),

            # 의약품 정보
            "name": name,
            "active_substances": active_substances,
            "atc_code": atc_code,
            "therapeutic_area": therapeutic_area,

            # DHPC 정보
            "dhpc_type": dhpc_type,
            "regulatory_outcome": regulatory_outcome,
            "dissemination_date": dissemination_date,

            # URL
            "source_url": raw.get("dhpc_url", ""),

            # 원본
            "raw": raw,
        }

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_dhpc(raw) for raw in raw_list]
