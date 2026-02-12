"""Bulk data loader — DomesticImpact / BriefingReport -> DB

DomesticImpact 분석 결과와 BriefingReport를 정규화 테이블에 적재.
PostgreSQL / SQLite 모두 지원 (ORM upsert 패턴 사용).

v2.1: 변경 감지(Change Detection) 추가 — changed_drug_ids 반환.

사용법:
    loader = DBLoader()
    summary = await loader.upsert_impacts(impacts)
    await loader.save_briefing(report)

    # 변경 감지 모드
    summary = await loader.upsert_impacts(impacts, pipeline_run_id="...")
    changed_ids = summary["changed_drug_ids"]
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regscan.db.database import get_async_session
from regscan.db.models import (
    DrugDB,
    RegulatoryEventDB,
    HIRAReimbursementDB,
    ClinicalTrialDB,
    BriefingReportDB,
    ScanSnapshotDB,
    DrugChangeLogDB,
)
from regscan.report.llm_generator import BriefingReport
from regscan.scan.domestic import DomesticImpact

logger = logging.getLogger(__name__)


def _hot_issue_level(score: int) -> str:
    """global_score -> HOT / HIGH / MID / LOW"""
    if score >= 80:
        return "HOT"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MID"
    return "LOW"


class DBLoader:
    """Async bulk loader for RegScan normalized tables.

    모든 퍼블릭 메서드는 자체 세션을 열어 처리하므로
    외부에서 세션 관리가 필요하지 않습니다.
    """

    def __init__(self) -> None:
        self._session_factory = get_async_session()

    # ------------------------------------------------------------------ #
    #  1. upsert_impacts — 메인 적재 메서드 (변경 감지 통합)
    # ------------------------------------------------------------------ #

    async def upsert_impacts(
        self,
        impacts: list[DomesticImpact],
        pipeline_run_id: str | None = None,
    ) -> dict:
        """DomesticImpact 리스트를 DB에 upsert.

        Args:
            impacts: DomesticImpactAnalyzer.analyze_batch() 결과
            pipeline_run_id: 파이프라인 실행 ID (변경 감지용, None이면 감지 안 함)

        Returns:
            {"drugs": N, "events": N, "hira": N, "trials": N,
             "changed_drug_ids": set[int], "changes": N}
        """
        counts = {
            "drugs": 0, "events": 0, "hira": 0, "trials": 0,
            "changed_drug_ids": set(), "changes": 0,
        }

        async with self._session_factory() as session:
            async with session.begin():
                for impact in impacts:
                    if pipeline_run_id:
                        drug, is_changed = await self._upsert_drug_with_changes(
                            session, impact, pipeline_run_id
                        )
                        if is_changed:
                            counts["changed_drug_ids"].add(drug.id)
                    else:
                        drug = await self._upsert_drug(session, impact)
                    counts["drugs"] += 1

                    if pipeline_run_id:
                        evt_count, evt_changed = await self._upsert_events_with_changes(
                            session, drug.id, impact, pipeline_run_id
                        )
                        counts["events"] += evt_count
                        if evt_changed:
                            counts["changed_drug_ids"].add(drug.id)
                    else:
                        counts["events"] += await self._upsert_events(
                            session, drug.id, impact
                        )

                    counts["hira"] += await self._upsert_hira(
                        session, drug.id, impact
                    )
                    counts["trials"] += await self._upsert_trials(
                        session, drug.id, impact
                    )

        counts["changes"] = len(counts["changed_drug_ids"])

        logger.info(
            "DB upsert 완료: drugs=%d, events=%d, hira=%d, trials=%d, changed=%d",
            counts["drugs"],
            counts["events"],
            counts["hira"],
            counts["trials"],
            counts["changes"],
        )
        return counts

    # ------------------------------------------------------------------ #
    #  2. save_briefing / load_briefing
    # ------------------------------------------------------------------ #

    async def save_briefing(self, report: BriefingReport) -> None:
        """BriefingReport를 briefing_reports 테이블에 저장.

        동일 INN 에 대해 기존 리포트가 있으면 갱신하고,
        없으면 새로 삽입합니다.  drug_id 는 drugs 테이블에서 조회합니다.
        """
        async with self._session_factory() as session:
            async with session.begin():
                # drug_id 조회
                drug_id = await self._get_drug_id(session, report.inn)

                # 기존 브리핑 조회 (같은 INN)
                stmt = select(BriefingReportDB).where(
                    BriefingReportDB.inn == report.inn
                )
                result = await session.execute(stmt)
                existing: Optional[BriefingReportDB] = result.scalar_one_or_none()

                if existing:
                    existing.drug_id = drug_id
                    existing.headline = report.headline
                    existing.subtitle = report.subtitle
                    existing.key_points = report.key_points
                    existing.global_section = report.global_section
                    existing.domestic_section = report.domestic_section
                    existing.medclaim_section = report.medclaim_section
                    existing.generated_at = report.generated_at
                else:
                    row = BriefingReportDB(
                        drug_id=drug_id,
                        inn=report.inn,
                        headline=report.headline,
                        subtitle=report.subtitle,
                        key_points=report.key_points,
                        global_section=report.global_section,
                        domestic_section=report.domestic_section,
                        medclaim_section=report.medclaim_section,
                        generated_at=report.generated_at,
                    )
                    session.add(row)

        logger.info("브리핑 저장 완료: %s", report.inn)

    async def load_briefing(self, inn: str) -> Optional[BriefingReport]:
        """INN 으로 최신 BriefingReport 조회.

        Returns:
            BriefingReport dataclass 또는 None
        """
        async with self._session_factory() as session:
            stmt = (
                select(BriefingReportDB)
                .where(BriefingReportDB.inn == inn)
                .order_by(BriefingReportDB.generated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row: Optional[BriefingReportDB] = result.scalar_one_or_none()

            if row is None:
                return None

            return BriefingReport(
                inn=row.inn,
                headline=row.headline or "",
                subtitle=row.subtitle or "",
                key_points=row.key_points or [],
                global_section=row.global_section or "",
                domestic_section=row.domestic_section or "",
                medclaim_section=row.medclaim_section or "",
                generated_at=row.generated_at or datetime.utcnow(),
            )

    # ------------------------------------------------------------------ #
    #  3. save_snapshot
    # ------------------------------------------------------------------ #

    async def save_snapshot(
        self,
        source_type: str,
        scan_date: date,
        record_count: int,
        gcs_path: str = "",
        checksum: str = "",
    ) -> None:
        """수집 메타 스냅샷 저장.

        Args:
            source_type: "fda" / "ema" / "mfds" / "cris"
            scan_date:   수집 날짜
            record_count: 수집 건수
            gcs_path:    GCS 원본 경로 (optional)
            checksum:    파일 해시 (optional)
        """
        async with self._session_factory() as session:
            async with session.begin():
                # 같은 source_type + scan_date 가 있으면 갱신
                stmt = select(ScanSnapshotDB).where(
                    ScanSnapshotDB.source_type == source_type,
                    ScanSnapshotDB.scan_date == scan_date,
                )
                result = await session.execute(stmt)
                existing: Optional[ScanSnapshotDB] = result.scalar_one_or_none()

                if existing:
                    existing.record_count = record_count
                    existing.gcs_path = gcs_path
                    existing.checksum = checksum
                    existing.collected_at = datetime.utcnow()
                else:
                    row = ScanSnapshotDB(
                        source_type=source_type,
                        scan_date=scan_date,
                        record_count=record_count,
                        gcs_path=gcs_path,
                        checksum=checksum,
                    )
                    session.add(row)

        logger.info(
            "스냅샷 저장: %s %s (%d건)", source_type, scan_date, record_count
        )

    # ================================================================== #
    #  Private helpers — 기존 메서드 (하위 호환)
    # ================================================================== #

    async def _upsert_drug(
        self, session: AsyncSession, impact: DomesticImpact
    ) -> DrugDB:
        """drugs 테이블 upsert. INN 이 unique key."""
        stmt = select(DrugDB).where(DrugDB.inn == impact.inn)
        result = await session.execute(stmt)
        drug: Optional[DrugDB] = result.scalar_one_or_none()

        level = _hot_issue_level(impact.global_score)

        if drug:
            drug.global_score = impact.global_score
            drug.korea_relevance_score = impact.korea_relevance_score
            drug.hot_issue_level = level
            drug.hot_issue_reasons = impact.hot_issue_reasons
            drug.domestic_status = impact.domestic_status.value
            drug.updated_at = datetime.utcnow()
        else:
            drug = DrugDB(
                inn=impact.inn,
                global_score=impact.global_score,
                korea_relevance_score=impact.korea_relevance_score,
                hot_issue_level=level,
                hot_issue_reasons=impact.hot_issue_reasons,
                domestic_status=impact.domestic_status.value,
            )
            session.add(drug)
            # flush 로 id 확보
            await session.flush()

        return drug

    async def _upsert_events(
        self, session: AsyncSession, drug_id: int, impact: DomesticImpact
    ) -> int:
        """regulatory_events upsert. (drug_id, agency) unique."""
        count = 0

        agencies = [
            (
                "fda",
                impact.fda_approved,
                impact.fda_date,
            ),
            (
                "ema",
                impact.ema_approved,
                impact.ema_date,
            ),
            (
                "mfds",
                impact.mfds_approved,
                impact.mfds_date,
            ),
        ]

        for agency, approved, approval_date in agencies:
            if not approved:
                continue

            stmt = select(RegulatoryEventDB).where(
                RegulatoryEventDB.drug_id == drug_id,
                RegulatoryEventDB.agency == agency,
            )
            result = await session.execute(stmt)
            event: Optional[RegulatoryEventDB] = result.scalar_one_or_none()

            status = "approved" if approved else "pending"

            if event:
                event.status = status
                event.approval_date = approval_date
                if agency == "mfds" and impact.mfds_brand_name:
                    event.brand_name = impact.mfds_brand_name
            else:
                event = RegulatoryEventDB(
                    drug_id=drug_id,
                    agency=agency,
                    status=status,
                    approval_date=approval_date,
                    brand_name=(
                        impact.mfds_brand_name if agency == "mfds" else None
                    ),
                )
                session.add(event)

            count += 1

        return count

    async def _upsert_hira(
        self, session: AsyncSession, drug_id: int, impact: DomesticImpact
    ) -> int:
        """hira_reimbursements upsert. drug_id 기준 1행."""
        if impact.hira_status is None:
            return 0

        stmt = select(HIRAReimbursementDB).where(
            HIRAReimbursementDB.drug_id == drug_id,
        )
        result = await session.execute(stmt)
        hira: Optional[HIRAReimbursementDB] = result.scalar_one_or_none()

        if hira:
            hira.status = impact.hira_status.value
            hira.ingredient_code = impact.hira_code
            hira.price_ceiling = impact.hira_price
            hira.criteria = impact.hira_criteria
            hira.updated_at = datetime.utcnow()
        else:
            hira = HIRAReimbursementDB(
                drug_id=drug_id,
                status=impact.hira_status.value,
                ingredient_code=impact.hira_code,
                price_ceiling=impact.hira_price,
                criteria=impact.hira_criteria,
            )
            session.add(hira)

        return 1

    async def _upsert_trials(
        self, session: AsyncSession, drug_id: int, impact: DomesticImpact
    ) -> int:
        """clinical_trials upsert. (drug_id, trial_id) unique."""
        count = 0

        for trial in impact.cris_trials:
            stmt = select(ClinicalTrialDB).where(
                ClinicalTrialDB.drug_id == drug_id,
                ClinicalTrialDB.trial_id == trial.trial_id,
            )
            result = await session.execute(stmt)
            existing: Optional[ClinicalTrialDB] = result.scalar_one_or_none()

            if existing:
                existing.title = trial.title
                existing.phase = trial.phase
                existing.status = trial.status
                existing.indication = trial.indication
                existing.sponsor = trial.sponsor
            else:
                row = ClinicalTrialDB(
                    drug_id=drug_id,
                    trial_id=trial.trial_id,
                    title=trial.title,
                    phase=trial.phase,
                    status=trial.status,
                    indication=trial.indication,
                    sponsor=trial.sponsor,
                )
                session.add(row)

            count += 1

        return count

    async def _get_drug_id(self, session: AsyncSession, inn: str) -> Optional[int]:
        """drugs 테이블에서 INN 으로 drug_id 조회.

        없으면 최소 레코드를 생성하고 id 를 반환합니다.
        """
        stmt = select(DrugDB.id).where(DrugDB.inn == inn)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is not None:
            return row

        # 아직 drugs 에 없으면 최소 레코드 생성
        drug = DrugDB(inn=inn, hot_issue_level="LOW")
        session.add(drug)
        await session.flush()
        return drug.id

    # ================================================================== #
    #  Change Detection helpers
    # ================================================================== #

    async def _upsert_drug_with_changes(
        self,
        session: AsyncSession,
        impact: DomesticImpact,
        pipeline_run_id: str,
    ) -> tuple[DrugDB, bool]:
        """drugs 테이블 upsert + 변경 감지. 변경 시 change_log INSERT.

        Returns:
            (DrugDB, is_changed) — 변경 여부
        """
        stmt = select(DrugDB).where(DrugDB.inn == impact.inn)
        result = await session.execute(stmt)
        drug: Optional[DrugDB] = result.scalar_one_or_none()

        level = _hot_issue_level(impact.global_score)
        changed = False

        if drug:
            # score_change 감지 (global_score)
            if drug.global_score != impact.global_score:
                self._add_change(
                    session, drug.id, "score_change", "global_score",
                    str(drug.global_score), str(impact.global_score),
                    pipeline_run_id,
                )
                changed = True

            # score_change 감지 (korea_relevance_score)
            if (drug.korea_relevance_score or 0) != impact.korea_relevance_score:
                self._add_change(
                    session, drug.id, "score_change", "korea_relevance_score",
                    str(drug.korea_relevance_score or 0),
                    str(impact.korea_relevance_score),
                    pipeline_run_id,
                )
                changed = True

            # status_change 감지 (hot_issue_level)
            if drug.hot_issue_level != level:
                self._add_change(
                    session, drug.id, "status_change", "hot_issue_level",
                    drug.hot_issue_level, level,
                    pipeline_run_id,
                )
                changed = True

            # status_change 감지 (domestic_status)
            if drug.domestic_status != impact.domestic_status.value:
                self._add_change(
                    session, drug.id, "status_change", "domestic_status",
                    drug.domestic_status, impact.domestic_status.value,
                    pipeline_run_id,
                )
                changed = True

            # 실제 업데이트
            drug.global_score = impact.global_score
            drug.korea_relevance_score = impact.korea_relevance_score
            drug.hot_issue_level = level
            drug.hot_issue_reasons = impact.hot_issue_reasons
            drug.domestic_status = impact.domestic_status.value
            drug.updated_at = datetime.utcnow()
        else:
            # 새 약물 → new_drug
            drug = DrugDB(
                inn=impact.inn,
                global_score=impact.global_score,
                korea_relevance_score=impact.korea_relevance_score,
                hot_issue_level=level,
                hot_issue_reasons=impact.hot_issue_reasons,
                domestic_status=impact.domestic_status.value,
            )
            session.add(drug)
            await session.flush()

            self._add_change(
                session, drug.id, "new_drug", "inn",
                None, impact.inn,
                pipeline_run_id,
            )
            changed = True

        return drug, changed

    async def _upsert_events_with_changes(
        self,
        session: AsyncSession,
        drug_id: int,
        impact: DomesticImpact,
        pipeline_run_id: str,
    ) -> tuple[int, bool]:
        """regulatory_events upsert + 변경 감지.

        Returns:
            (count, is_changed)
        """
        count = 0
        changed = False

        agencies = [
            ("fda", impact.fda_approved, impact.fda_date),
            ("ema", impact.ema_approved, impact.ema_date),
            ("mfds", impact.mfds_approved, impact.mfds_date),
        ]

        designation_fields = [
            "is_orphan", "is_breakthrough", "is_accelerated",
            "is_priority", "is_prime", "is_conditional", "is_fast_track",
        ]

        for agency, approved, approval_date in agencies:
            if not approved:
                continue

            stmt = select(RegulatoryEventDB).where(
                RegulatoryEventDB.drug_id == drug_id,
                RegulatoryEventDB.agency == agency,
            )
            result = await session.execute(stmt)
            event: Optional[RegulatoryEventDB] = result.scalar_one_or_none()

            status = "approved" if approved else "pending"

            if event:
                # status 변경 감지
                if event.status != status:
                    self._add_change(
                        session, drug_id, "status_change",
                        f"{agency}_status", event.status, status,
                        pipeline_run_id,
                    )
                    changed = True

                event.status = status
                event.approval_date = approval_date
                if agency == "mfds" and impact.mfds_brand_name:
                    event.brand_name = impact.mfds_brand_name
            else:
                # 새 이벤트
                event = RegulatoryEventDB(
                    drug_id=drug_id,
                    agency=agency,
                    status=status,
                    approval_date=approval_date,
                    brand_name=(
                        impact.mfds_brand_name if agency == "mfds" else None
                    ),
                )
                session.add(event)

                self._add_change(
                    session, drug_id, "new_event",
                    f"{agency}_approval", None, status,
                    pipeline_run_id,
                )
                changed = True

            count += 1

        return count, changed

    @staticmethod
    def _add_change(
        session: AsyncSession,
        drug_id: int,
        change_type: str,
        field_name: str,
        old_value: str | None,
        new_value: str | None,
        pipeline_run_id: str,
    ) -> None:
        """change_log에 변경 기록 추가."""
        log = DrugChangeLogDB(
            drug_id=drug_id,
            change_type=change_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            pipeline_run_id=pipeline_run_id,
        )
        session.add(log)
