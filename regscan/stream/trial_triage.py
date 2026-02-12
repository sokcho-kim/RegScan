"""Trial Triage Engine — CT.gov 임상시험 3단계 판독

[TERMINATED/SUSPENDED] → FAIL (즉시 리포트)
[COMPLETED & No Results] → PENDING (워치리스트)
[COMPLETED & Has Results] → AI 판독으로 승격
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class TrialTriageEngine:
    """수집된 CT.gov 임상시험을 3단계로 분류"""

    def triage(self, parsed_study: dict[str, Any]) -> dict[str, Any]:
        """단일 임상시험 판독

        Args:
            parsed_study: ClinicalTrialsGovParser.parse_study() 결과

        Returns:
            parsed_study에 verdict/verdict_summary/verdict_confidence 추가
        """
        status = (parsed_study.get("status") or "").upper()
        has_results = parsed_study.get("has_results", False)
        results_posted = parsed_study.get("results_posted_date") is not None

        if status in ("TERMINATED", "SUSPENDED"):
            return self._verdict_fail(parsed_study)
        elif status == "COMPLETED" and not has_results and not results_posted:
            return self._verdict_pending(parsed_study)
        elif status == "COMPLETED" and (has_results or results_posted):
            return self._verdict_needs_ai(parsed_study)
        else:
            # Unknown status → pending
            return self._verdict_pending(parsed_study)

    def triage_many(self, studies: list[dict]) -> dict[str, list[dict]]:
        """여러 임상시험 일괄 분류

        Returns:
            {"fail": [...], "pending": [...], "needs_ai": [...]}
        """
        result: dict[str, list[dict]] = {
            "fail": [],
            "pending": [],
            "needs_ai": [],
        }

        for study in studies:
            triaged = self.triage(study)
            verdict = triaged.get("verdict", "PENDING")
            if verdict == "FAIL":
                result["fail"].append(triaged)
            elif verdict == "PENDING":
                result["pending"].append(triaged)
            else:
                result["needs_ai"].append(triaged)

        logger.info(
            "Triage 완료: FAIL=%d, PENDING=%d, NEEDS_AI=%d",
            len(result["fail"]), len(result["pending"]), len(result["needs_ai"]),
        )
        return result

    def _verdict_fail(self, study: dict) -> dict:
        """TERMINATED/SUSPENDED → 즉시 실패 판정"""
        why_stopped = study.get("why_stopped", "")
        inns = study.get("extracted_inns", [])
        inn_str = ", ".join(inns) if inns else "Unknown"

        summary = f"Phase 3 임상 실패/중단: {inn_str}"
        if why_stopped:
            summary += f" (사유: {why_stopped})"

        study["verdict"] = "FAIL"
        study["verdict_summary"] = summary
        study["verdict_confidence"] = 1.0
        study["verdicted_at"] = datetime.utcnow().isoformat()
        return study

    def _verdict_pending(self, study: dict) -> dict:
        """COMPLETED but no results → 워치리스트"""
        inns = study.get("extracted_inns", [])
        inn_str = ", ".join(inns) if inns else "Unknown"

        study["verdict"] = "PENDING"
        study["verdict_summary"] = f"Phase 3 완료, 결과 미공개 (워치리스트): {inn_str}"
        study["verdict_confidence"] = 0.5
        study["verdicted_at"] = datetime.utcnow().isoformat()
        return study

    def _verdict_needs_ai(self, study: dict) -> dict:
        """COMPLETED with results → AI 판독 필요"""
        study["verdict"] = "NEEDS_AI"
        study["verdict_summary"] = "결과 공개됨 — AI 판독 대기"
        study["verdict_confidence"] = 0.0
        study["verdicted_at"] = datetime.utcnow().isoformat()
        return study
