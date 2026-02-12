"""ClinicalTrials.gov v2 API 파서

v2 API의 nested protocolSection 구조를 평탄화하고,
DRUG/BIOLOGICAL intervention만 필터하여 INN 추출.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 용량/단위/salt 제거용 패턴
_DOSE_PATTERN = re.compile(
    r'\s*\d+\s*(mg|mcg|µg|g|ml|iu|unit|%|mg/ml|mg/m2|mg/kg)\b.*',
    re.IGNORECASE,
)
_SALT_SUFFIXES = [
    "hydrochloride", "hcl", "sodium", "potassium", "acetate",
    "sulfate", "sulphate", "mesylate", "maleate", "fumarate",
    "citrate", "tartrate", "phosphate", "succinate", "tosylate",
    "besylate", "bromide", "chloride", "nitrate", "calcium",
    "disodium", "tromethamine", "meglumine", "lysine",
]
_EXCLUDE_INTERVENTIONS = {
    "placebo", "standard of care", "best supportive care",
    "observation", "no intervention", "active comparator",
    "sham", "usual care", "watchful waiting",
}


class ClinicalTrialsGovParser:
    """CT.gov v2 API 결과 파서"""

    def parse_study(self, raw: dict) -> dict[str, Any]:
        """단일 연구 파싱

        Args:
            raw: CT.gov v2 API study dict

        Returns:
            평탄화된 dict
        """
        proto = raw.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        design_mod = proto.get("designModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

        # 기본 정보
        nct_id = ident.get("nctId", "")
        title = ident.get("briefTitle", "")
        overall_status = status_mod.get("overallStatus", "")

        # 날짜
        completion_date = self._parse_date_struct(status_mod.get("completionDateStruct"))
        results_date = self._parse_date_struct(
            raw.get("resultsSection", {}).get("moreInfoModule", {}).get("certainAgreement", {})
        )
        # results_posted_date는 별도 필드
        has_results = raw.get("hasResults", False)
        results_posted_date_str = status_mod.get("resultsFirstPostDateStruct", {}).get("date", "")
        results_posted_date = self._parse_date_str(results_posted_date_str)

        # 질환
        conditions = proto.get("conditionsModule", {}).get("conditions", [])

        # 중재 (DRUG/BIOLOGICAL만)
        interventions_raw = arms_mod.get("interventions", [])
        drug_interventions = []
        extracted_inns = []

        for interv in interventions_raw:
            itype = interv.get("type", "").upper()
            iname = interv.get("name", "")

            if itype not in ("DRUG", "BIOLOGICAL"):
                continue
            if iname.lower().strip() in _EXCLUDE_INTERVENTIONS:
                continue

            drug_interventions.append({
                "name": iname,
                "type": itype,
                "description": interv.get("description", ""),
            })

            inn = self._extract_inn(iname)
            if inn:
                extracted_inns.append(inn)

        # 스폰서
        lead_sponsor = sponsor_mod.get("leadSponsor", {})
        sponsor_name = lead_sponsor.get("name", "")

        # 등록 수
        enrollment_info = design_mod.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count", 0)

        # Phase
        phases = design_mod.get("phases", [])
        phase = phases[0] if phases else ""

        # WhyStopped
        why_stopped = status_mod.get("whyStopped", "")

        return {
            "nct_id": nct_id,
            "title": title,
            "conditions": conditions,
            "interventions": drug_interventions,
            "extracted_inns": extracted_inns,
            "phase": phase,
            "status": overall_status,
            "completion_date": completion_date,
            "results_posted_date": results_posted_date,
            "has_results": has_results,
            "why_stopped": why_stopped,
            "sponsor": sponsor_name,
            "enrollment": enrollment,
            "search_condition": raw.get("_search_condition", ""),
        }

    def parse_many(self, studies: list[dict]) -> list[dict]:
        """여러 연구 파싱"""
        results = []
        for study in studies:
            try:
                parsed = self.parse_study(study)
                if parsed.get("nct_id"):
                    results.append(parsed)
            except Exception as e:
                logger.debug("CT.gov 파싱 실패: %s", e)
        return results

    def _extract_inn(self, name: str) -> str:
        """약물명에서 INN 추출 (용량/salt 제거)"""
        # 괄호 안 내용 제거
        clean = re.sub(r'\([^)]*\)', '', name).strip()
        # 용량/단위 제거
        clean = _DOSE_PATTERN.sub('', clean).strip()
        # salt suffix 제거
        lower = clean.lower()
        for suffix in _SALT_SUFFIXES:
            if lower.endswith(suffix):
                clean = clean[:len(clean) - len(suffix)].strip()
                break
        # 앞뒤 공백, 쉼표, 하이픈 정리
        clean = clean.strip(" ,-/")
        return clean if len(clean) >= 3 else ""

    def _parse_date_struct(self, date_struct: Optional[dict]) -> Optional[str]:
        """CT.gov 날짜 구조 파싱"""
        if not date_struct:
            return None
        date_str = date_struct.get("date", "")
        return self._parse_date_str(date_str)

    def _parse_date_str(self, date_str: str) -> Optional[str]:
        """날짜 문자열 → ISO 형식"""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %Y", "%Y-%m"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str
