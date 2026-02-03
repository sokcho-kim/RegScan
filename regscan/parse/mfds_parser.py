"""MFDS 응답 파서"""

from datetime import datetime
from typing import Any, Optional
import re
import html


class MFDSPermitParser:
    """MFDS 의약품 허가정보 파서"""

    def parse_permit(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        MFDS 허가정보를 중간 형식으로 변환

        Args:
            raw: 공공데이터포털 API 응답의 단일 항목

        Returns:
            정규화된 dict
        """
        item_seq = raw.get("ITEM_SEQ", "")
        item_name = raw.get("ITEM_NAME", "")
        item_name_eng = raw.get("ITEM_ENG_NAME", "")
        entp_name = raw.get("ENTP_NAME", "")
        entp_name_eng = raw.get("ENTP_ENG_NAME", "")

        # 허가일 파싱
        permit_date_str = raw.get("ITEM_PERMIT_DATE", "")
        permit_date = self._parse_date(permit_date_str)

        # 주성분 추출 (INN 매칭용) - 두 가지 필드명 지원
        material_name = raw.get("MATERIAL_NAME", "") or raw.get("ITEM_INGR_NAME", "")
        ingredients = self._extract_ingredients(material_name)

        # 전문/일반 구분 - 두 가지 필드명 지원
        etc_otc = raw.get("ETC_OTC_CODE", "") or raw.get("SPCLTY_PBLC", "")
        is_prescription = "전문" in etc_otc

        # 허가구분 (신약, 자료제출의약품 등)
        permit_kind = raw.get("PERMIT_KIND_CODE", "") or raw.get("PERMIT_KIND_NAME", "")
        is_new_drug = "신약" in permit_kind or permit_kind == "신규"

        # 제품 유형
        product_type = raw.get("PRDUCT_TYPE", "")

        # 취소 여부
        cancel_date = raw.get("CANCEL_DATE") or ""
        cancel_name = raw.get("CANCEL_NAME", "")
        is_valid = not cancel_date or cancel_name == "정상"

        # 효능효과 (XML에서 텍스트 추출)
        ee_doc = raw.get("EE_DOC_DATA", "")
        indication = self._extract_text_from_xml(ee_doc)

        # 제형
        chart = raw.get("CHART", "") or raw.get("PRDUCT_TYPE", "")

        # 분류번호에서 희귀의약품 등 확인
        class_no = raw.get("CLASS_NO", "") or raw.get("PRDLST_STDR_CODE", "")

        return {
            # 식별
            "item_seq": item_seq,
            "source_id": item_seq,

            # 제품 정보
            "item_name": item_name,
            "item_name_eng": item_name_eng,
            "entp_name": entp_name,
            "entp_name_eng": entp_name_eng,
            "brand_name": item_name,

            # 성분
            "material_name": material_name,
            "ingredients": ingredients,
            "main_ingredient": ingredients[0] if ingredients else "",

            # 날짜
            "permit_date": permit_date,
            "permit_date_str": permit_date_str,
            "cancel_date": cancel_date,

            # 상태
            "is_valid": is_valid,
            "cancel_name": cancel_name,

            # 분류
            "etc_otc_code": etc_otc,
            "is_prescription": is_prescription,
            "permit_kind": permit_kind,
            "is_new_drug": is_new_drug,
            "product_type": product_type,
            "class_no": class_no,
            "chart": chart,

            # 적응증
            "indication": indication[:500] if indication else "",  # 500자 제한

            # 기타
            "storage_method": raw.get("STORAGE_METHOD", ""),
            "valid_term": raw.get("VALID_TERM", ""),
            "pack_unit": raw.get("PACK_UNIT", ""),
            "edi_code": raw.get("EDI_CODE", ""),

            # URL
            "source_url": self._build_source_url(item_seq),

            # 원본
            "raw": raw,
        }

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        # 다양한 형식 지원
        formats = [
            "%Y%m%d",
            "%Y-%m-%d",
            "%Y.%m.%d",
            "%Y/%m/%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None

    def _extract_ingredients(self, material_name: str) -> list[str]:
        """
        주성분에서 성분명 추출

        예시 입력:
        "아세트아미노펜|500|밀리그램|KP|정|성분"
        "레보플록사신수화물|513.87|밀리그램|USP|레보플록사신으로서|500|밀리그램"
        """
        if not material_name:
            return []

        ingredients = []

        # 파이프로 구분된 경우
        if "|" in material_name:
            parts = material_name.split("|")
            # 첫 번째 부분이 성분명
            if parts:
                name = parts[0].strip()
                # 괄호 내용 제거 (영문명 등)
                name = re.sub(r"\([^)]*\)", "", name).strip()
                if name:
                    ingredients.append(name)
        else:
            # 세미콜론이나 콤마로 구분된 경우
            for sep in [";", ","]:
                if sep in material_name:
                    for part in material_name.split(sep):
                        name = part.strip()
                        name = re.sub(r"\([^)]*\)", "", name).strip()
                        if name and not name.isdigit():
                            ingredients.append(name)
                    break
            else:
                # 구분자 없이 단일 성분
                name = material_name.strip()
                name = re.sub(r"\([^)]*\)", "", name).strip()
                if name:
                    ingredients.append(name)

        return ingredients

    def _extract_text_from_xml(self, xml_str: str) -> str:
        """XML 문자열에서 텍스트만 추출"""
        if not xml_str:
            return ""

        # HTML 엔티티 디코딩
        text = html.unescape(xml_str)

        # XML 태그 제거
        text = re.sub(r"<[^>]+>", " ", text)

        # 여러 공백을 하나로
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _build_source_url(self, item_seq: str) -> str:
        """의약품안전나라 URL 생성"""
        if not item_seq:
            return ""
        return f"https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq={item_seq}"

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_permit(raw) for raw in raw_list]

    def is_new_drug(self, parsed: dict[str, Any]) -> bool:
        """신약 여부 판별"""
        raw = parsed.get("raw", {})

        # 다양한 필드에서 신약 확인
        item_name = parsed.get("item_name", "").lower()
        class_no = parsed.get("class_no", "")

        # 품목명에 (신약) 표시
        if "(신약)" in item_name or "신약" in item_name:
            return True

        # TODO: 허가구분 필드 확인 (API에서 제공시)

        return False

    def is_orphan_drug(self, parsed: dict[str, Any]) -> bool:
        """희귀의약품 여부 판별"""
        raw = parsed.get("raw", {})

        # 희귀의약품 키워드 확인
        item_str = str(raw).lower()
        if "희귀" in item_str or "orphan" in item_str:
            return True

        return False
