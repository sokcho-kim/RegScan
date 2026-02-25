"""ClinicalTrials.gov v2 API 파서

v2 API의 nested protocolSection 구조를 평탄화하고,
DRUG/BIOLOGICAL intervention만 필터하여 INN 추출.
resultsSection에서 primary endpoint, 통계 분석, 안전성 데이터 추출.
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

        # resultsSection 파싱 (있으면)
        clinical_results = None
        if has_results and raw.get("resultsSection"):
            clinical_results = self.parse_results_section(raw["resultsSection"])

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
            "clinical_results": clinical_results,
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

    def parse_results_section(self, results: dict) -> dict[str, Any]:
        """resultsSection에서 임상 결과 데이터 추출

        Args:
            results: CT.gov v2 resultsSection dict

        Returns:
            {
                "primary_outcomes": [...],
                "secondary_outcomes": [...],
                "adverse_events": {...},
            }
        """
        parsed: dict[str, Any] = {
            "primary_outcomes": [],
            "secondary_outcomes": [],
            "adverse_events": None,
        }

        # 1) Outcome Measures
        outcome_mod = results.get("outcomeMeasuresModule", {})
        for measure in outcome_mod.get("outcomeMeasures", []):
            outcome = self._parse_outcome_measure(measure)
            if not outcome:
                continue
            if outcome["type"] == "PRIMARY":
                parsed["primary_outcomes"].append(outcome)
            else:
                parsed["secondary_outcomes"].append(outcome)

        # secondary는 최대 3개만
        parsed["secondary_outcomes"] = parsed["secondary_outcomes"][:3]

        # 2) Adverse Events
        ae_mod = results.get("adverseEventsModule", {})
        if ae_mod:
            parsed["adverse_events"] = self._parse_adverse_events(ae_mod)

        # 3) 한계점(Limitations) 자동 추출
        parsed["limitations"] = self._extract_limitations(parsed)

        return parsed

    def _extract_limitations(self, parsed_results: dict) -> list[str]:
        """임상 결과에서 한계점을 자동 추출

        기준:
        - 표본 크기 < 200: 소규모 시험 경고
        - CI 폭 > 0.5: 넓은 신뢰구간 경고
        - p-value 경계값 (0.01 < p < 0.05): 경계적 유의성 경고
        - primary outcome에서 통계적 유의성 미달
        """
        limitations: list[str] = []

        for outcome in parsed_results.get("primary_outcomes", []):
            for analysis in outcome.get("analyses", []):
                # p-value 경계성 체크
                p_str = analysis.get("p_value", "")
                if p_str:
                    try:
                        # "<0.001" → 0.001, "0.02" → 0.02 등
                        p_clean = p_str.replace("<", "").replace(">", "").replace("=", "").strip()
                        p_val = float(p_clean)
                        if 0.01 < p_val < 0.05:
                            limitations.append(
                                f"Primary endpoint p-value가 경계적 수준({p_str})으로, 통계적 유의성이 강건하지 않을 수 있음"
                            )
                        elif p_val >= 0.05:
                            limitations.append(
                                f"Primary endpoint에서 통계적 유의성 미달(p={p_str})"
                            )
                    except (ValueError, TypeError):
                        pass

                # CI 폭 체크
                ci_str = analysis.get("ci", "")
                if ci_str:
                    # "95% CI [0.44, 0.80]" 형식 파싱
                    ci_match = re.search(r'\[([0-9.]+),\s*([0-9.]+)\]', ci_str)
                    if ci_match:
                        try:
                            ci_lower = float(ci_match.group(1))
                            ci_upper = float(ci_match.group(2))
                            ci_width = ci_upper - ci_lower
                            if ci_width > 0.5:
                                limitations.append(
                                    f"신뢰구간 폭이 넓음({ci_str}), 효과 추정의 정밀도 제한적"
                                )
                        except (ValueError, TypeError):
                            pass

            # 그룹 표본 크기 체크
            for gv in outcome.get("group_values", []):
                # group_values에서 표본 크기 추정은 어려우므로 생략
                pass

        return limitations

    def _parse_outcome_measure(self, measure: dict) -> dict[str, Any] | None:
        """단일 outcome measure 파싱"""
        title = measure.get("title", "")
        otype = measure.get("type", "").upper()  # PRIMARY, SECONDARY, OTHER
        if otype not in ("PRIMARY", "SECONDARY"):
            return None

        time_frame = measure.get("timeFrame", "")
        param_type = measure.get("paramType", "")  # e.g. "Number", "Mean", "Median"
        unit = measure.get("unitOfMeasure", "")

        # 그룹 정의
        groups_def = {
            g["id"]: g.get("title", "")
            for g in measure.get("groups", [])
        }

        # 측정값
        group_values: list[dict] = []
        for cls in measure.get("classes", []):
            cls_title = cls.get("title", "")
            for cat in cls.get("categories", []):
                for meas in cat.get("measurements", []):
                    gid = meas.get("groupId", "")
                    val = meas.get("value", "")
                    spread = meas.get("spread", "")
                    if val:
                        group_values.append({
                            "group": groups_def.get(gid, gid),
                            "value": val,
                            "spread": spread,
                            "class": cls_title,
                        })

        # 통계 분석
        analyses: list[dict] = []
        for analysis in measure.get("analyses", []):
            p_val = analysis.get("pValue", "")
            stat_method = analysis.get("statisticalMethod", "")
            param_type_a = analysis.get("paramType", "")
            param_value = analysis.get("paramValue", "")
            ci_lower = analysis.get("ciLowerLimit", "")
            ci_upper = analysis.get("ciUpperLimit", "")
            ci_pct = analysis.get("ciPctValue", "")
            groups_compared = [
                groups_def.get(gid, gid)
                for gid in analysis.get("groupIds", [])
            ]

            entry: dict[str, Any] = {}
            if p_val:
                entry["p_value"] = p_val
            if stat_method:
                entry["method"] = stat_method
            if param_type_a and param_value:
                entry["param_type"] = param_type_a  # e.g. "Hazard Ratio (HR)"
                entry["param_value"] = param_value
            if ci_lower and ci_upper:
                entry["ci"] = f"{ci_pct or '95'}% CI [{ci_lower}, {ci_upper}]"
            if groups_compared:
                entry["groups_compared"] = groups_compared
            if entry:
                analyses.append(entry)

        return {
            "type": otype,
            "title": title,
            "time_frame": time_frame,
            "param_type": param_type,
            "unit": unit,
            "group_values": group_values,
            "analyses": analyses,
        }

    def _parse_adverse_events(self, ae_mod: dict) -> dict[str, Any]:
        """adverseEventsModule 파싱"""
        # 이벤트 그룹 (각 arm)
        groups_def = {
            g["id"]: g.get("title", "")
            for g in ae_mod.get("eventGroups", [])
        }

        group_summary: list[dict] = []
        for g in ae_mod.get("eventGroups", []):
            group_summary.append({
                "group": g.get("title", ""),
                "serious_affected": g.get("seriousNumAffected", 0),
                "serious_at_risk": g.get("seriousNumAtRisk", 0),
                "other_affected": g.get("otherNumAffected", 0),
                "other_at_risk": g.get("otherNumAtRisk", 0),
            })

        # 상위 심각한 이상반응 (빈도순)
        serious_events: list[dict] = []
        for event_cat in ae_mod.get("seriousEvents", []):
            term = event_cat.get("term", "")
            for stat in event_cat.get("stats", []):
                gid = stat.get("groupId", "")
                n_affected = stat.get("numAffected", 0)
                if n_affected and n_affected > 0:
                    serious_events.append({
                        "term": term,
                        "group": groups_def.get(gid, gid),
                        "n_affected": n_affected,
                    })

        # 상위 10건만
        serious_events.sort(key=lambda x: x["n_affected"], reverse=True)
        serious_events = serious_events[:10]

        return {
            "group_summary": group_summary,
            "top_serious_events": serious_events,
            "frequency_threshold": ae_mod.get("frequencyThreshold", ""),
            "description": ae_mod.get("description", ""),
        }

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
