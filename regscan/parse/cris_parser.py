"""CRIS 응답 파서"""

from datetime import datetime
from typing import Any, Optional
import re


class CRISTrialParser:
    """CRIS 임상시험 파서"""

    # Phase 정규화 매핑
    PHASE_MAP = {
        "phase 0": "Phase 0",
        "phase 1": "Phase 1",
        "phase 2": "Phase 2",
        "phase 3": "Phase 3",
        "phase 4": "Phase 4",
        "phase i": "Phase 1",
        "phase ii": "Phase 2",
        "phase iii": "Phase 3",
        "phase iv": "Phase 4",
        "1상": "Phase 1",
        "2상": "Phase 2",
        "3상": "Phase 3",
        "4상": "Phase 4",
        "1/2상": "Phase 1/2",
        "2/3상": "Phase 2/3",
    }

    # 모집 상태 정규화
    RECRUITMENT_STATUS_MAP = {
        "모집전": "not_yet_recruiting",
        "모집예정": "not_yet_recruiting",
        "모집중": "recruiting",
        "모집종료": "completed",
        "연구종결": "completed",
        "중단": "terminated",
        "취소": "withdrawn",
        "recruiting": "recruiting",
        "not yet recruiting": "not_yet_recruiting",
        "completed": "completed",
        "terminated": "terminated",
        "withdrawn": "withdrawn",
    }

    def parse_trial(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        CRIS 임상시험 데이터를 중간 형식으로 변환

        Args:
            raw: 공공데이터포털 API 응답의 단일 항목

        Returns:
            정규화된 dict
        """
        # 기본 정보
        trial_id = raw.get("trial_id", "") or raw.get("cris_number", "")

        # 제목
        title_kr = raw.get("scientific_title_kr", "") or raw.get("title_kr", "")
        title_en = raw.get("scientific_title_en", "") or raw.get("title_en", "")
        title = title_kr or title_en

        # Phase 정규화
        phase_raw = raw.get("phase_kr", "") or raw.get("phase", "")
        phase = self._normalize_phase(phase_raw)

        # 모집 상태
        status_raw = raw.get("recruitment_status_kr", "") or raw.get("recruitment_status", "")
        status = self._normalize_status(status_raw)
        is_active = status in ["recruiting", "not_yet_recruiting"]

        # 의뢰자/스폰서
        sponsor = raw.get("primary_sponsor_kr", "") or raw.get("primary_sponsor", "")
        sponsor_type = self._determine_sponsor_type(sponsor)

        # 시험약 정보 (scientific_title에서도 추출 시도)
        intervention = raw.get("intervention_kr", "") or raw.get("intervention", "") or ""
        title = raw.get("scientific_title_kr", "") or raw.get("scientific_title_en", "") or ""
        drug_names = self._extract_drug_names(intervention + " " + title)

        # 중재 종류 (i_freetext_kr 또는 intervention_type_kr)
        intervention_type = (
            raw.get("i_freetext_kr", "") or
            raw.get("intervention_type_kr", "") or
            raw.get("intervention_type", "")
        )
        is_drug_trial = self._is_drug_trial(intervention_type)

        # 대상 질환
        condition = raw.get("condition_kr", "") or raw.get("condition", "")
        icd_code = raw.get("icd10_code", "") or raw.get("health_condition_code", "")

        # 날짜
        registration_date = self._parse_date(raw.get("date_registration", ""))
        update_date = self._parse_date(raw.get("date_updated", ""))
        start_date = self._parse_date(raw.get("date_enrollment", "") or raw.get("study_start_date", ""))

        # 목표 피험자 수
        target_size = self._parse_int(raw.get("target_size", "") or raw.get("enrollment", ""))

        return {
            # 식별
            "trial_id": trial_id,
            "source_id": trial_id,

            # 제목
            "title": title,
            "title_kr": title_kr,
            "title_en": title_en,

            # Phase
            "phase": phase,
            "phase_raw": phase_raw,

            # 상태
            "status": status,
            "status_raw": status_raw,
            "is_active": is_active,

            # 의뢰자
            "sponsor": sponsor,
            "sponsor_type": sponsor_type,

            # 시험약
            "intervention": intervention,
            "drug_names": drug_names,
            "main_drug": drug_names[0] if drug_names else "",

            # 중재 종류
            "intervention_type": intervention_type,
            "is_drug_trial": is_drug_trial,

            # 질환
            "condition": condition,
            "icd_code": icd_code,

            # 날짜
            "registration_date": registration_date,
            "update_date": update_date,
            "start_date": start_date,

            # 규모
            "target_size": target_size,

            # URL
            "source_url": self._build_source_url(trial_id),

            # 원본
            "raw": raw,
        }

    def _normalize_phase(self, phase_str: str) -> str:
        """Phase 정규화"""
        if not phase_str:
            return ""

        phase_lower = phase_str.lower().strip()

        for pattern, normalized in self.PHASE_MAP.items():
            if pattern in phase_lower:
                return normalized

        return phase_str

    def _normalize_status(self, status_str: str) -> str:
        """모집 상태 정규화"""
        if not status_str:
            return "unknown"

        status_lower = status_str.lower().strip()

        for pattern, normalized in self.RECRUITMENT_STATUS_MAP.items():
            if pattern in status_lower:
                return normalized

        return "unknown"

    def _determine_sponsor_type(self, sponsor: str) -> str:
        """의뢰자 유형 판별"""
        if not sponsor:
            return "unknown"

        sponsor_lower = sponsor.lower()

        # 제약회사 키워드
        pharma_keywords = [
            "제약", "pharma", "biotech", "바이오",
            "파마", "케미칼", "사이언스",
        ]
        if any(kw in sponsor_lower for kw in pharma_keywords):
            return "pharmaceutical"

        # 의료기관 키워드
        hospital_keywords = [
            "병원", "의료원", "메디컬센터", "hospital",
            "medical center", "clinic",
        ]
        if any(kw in sponsor_lower for kw in hospital_keywords):
            return "hospital"

        # 대학/연구기관 키워드
        academic_keywords = [
            "대학", "university", "연구원", "연구소",
            "institute", "research",
        ]
        if any(kw in sponsor_lower for kw in academic_keywords):
            return "academic"

        # 정부기관
        gov_keywords = [
            "식약처", "질병관리", "보건복지부", "NIH",
            "government", "ministry",
        ]
        if any(kw in sponsor_lower for kw in gov_keywords):
            return "government"

        return "other"

    def _extract_drug_names(self, intervention: str) -> list[str]:
        """중재 내용에서 약물명 추출"""
        if not intervention:
            return []

        drugs = []

        # 괄호 내 영문명 추출
        en_names = re.findall(r"\(([A-Za-z][A-Za-z0-9\-\s]+)\)", intervention)
        drugs.extend(en_names)

        # 일반적인 약물명 패턴 (영문)
        drug_patterns = re.findall(r"\b([A-Z][a-z]+(?:mab|nib|zumab|tinib|ciclib|parin|statin|sartan))\b", intervention)
        drugs.extend(drug_patterns)

        # 한글 약물명 (끝이 ~맙, ~닙 등)
        kr_patterns = re.findall(r"([가-힣]+(?:맙|닙|틴|졸|셉트))", intervention)
        drugs.extend(kr_patterns)

        # 중복 제거
        seen = set()
        unique_drugs = []
        for drug in drugs:
            drug_lower = drug.lower()
            if drug_lower not in seen:
                seen.add(drug_lower)
                unique_drugs.append(drug)

        return unique_drugs

    def _is_drug_trial(self, intervention_type: str) -> bool:
        """의약품 임상시험 여부"""
        if not intervention_type:
            return False

        drug_keywords = ["의약품", "drug", "약물", "pharmaceutical", "biologic"]
        return any(kw in intervention_type.lower() for kw in drug_keywords)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        formats = [
            "%Y-%m-%d",
            "%Y%m%d",
            "%Y.%m.%d",
            "%Y/%m/%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip()[:10], fmt)
            except ValueError:
                continue

        return None

    def _parse_int(self, value: Any) -> Optional[int]:
        """정수 파싱"""
        if not value:
            return None

        if isinstance(value, int):
            return value

        try:
            # 콤마 제거
            cleaned = str(value).replace(",", "").strip()
            return int(cleaned)
        except ValueError:
            return None

    def _build_source_url(self, trial_id: str) -> str:
        """CRIS 상세 페이지 URL 생성"""
        if not trial_id:
            return ""
        return f"https://cris.nih.go.kr/cris/search/detailSearch.do?search_lang=K&focus=reset&trial_id={trial_id}"

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse_trial(raw) for raw in raw_list]

    def find_matching_trials_for_inn(
        self,
        trials: list[dict[str, Any]],
        inn: str,
    ) -> list[dict[str, Any]]:
        """
        INN으로 매칭되는 임상시험 찾기

        Args:
            trials: 파싱된 임상시험 목록
            inn: International Nonproprietary Name

        Returns:
            매칭된 임상시험 목록
        """
        if not inn:
            return []

        inn_lower = inn.lower()
        matched = []

        for trial in trials:
            # 약물명에서 검색
            drug_names = trial.get("drug_names", [])
            for drug in drug_names:
                if inn_lower in drug.lower() or drug.lower() in inn_lower:
                    matched.append(trial)
                    break
            else:
                # intervention 전체에서 검색
                intervention = trial.get("intervention", "").lower()
                if inn_lower in intervention:
                    matched.append(trial)

        return matched
