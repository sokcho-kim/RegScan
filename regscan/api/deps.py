"""API 의존성 - 데이터 로딩 및 캐싱

두 가지 모드:
1. JSON 모드 (settings.is_postgres == False): 파일에서 메모리로 전체 로드
2. PG 모드 (settings.is_postgres == True): 카운트만 캐시, 나머지 온디맨드 DB 쿼리
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from regscan.config import settings
from regscan.db.database import get_async_session
from regscan.db.models import DrugDB, RegulatoryEventDB, HIRAReimbursementDB, ClinicalTrialDB
from regscan.map.ingredient_bridge import ReimbursementStatus
from regscan.parse.fda_parser import FDADrugParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.cris_parser import CRISTrialParser
from regscan.map.global_status import merge_global_status, GlobalRegulatoryStatus
from regscan.scan.domestic import (
    DomesticImpactAnalyzer,
    DomesticImpact,
    DomesticStatus,
    ClinicalTrialInfo,
)

logger = logging.getLogger(__name__)


def _find_latest(directory: Path, pattern: str) -> Optional[Path]:
    """디렉토리에서 패턴과 일치하는 가장 최근 파일 반환"""
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


class DataStore:
    """데이터 저장소 (싱글톤)

    JSON 모드: load() → 전체 데이터를 메모리에 로드
    PG 모드: aload_counts() → 카운트만 로드, 나머지는 async 메서드로 온디맨드 쿼리
    """

    def __init__(self):
        self.statuses: list[GlobalRegulatoryStatus] = []
        self.impacts: list[DomesticImpact] = []
        self.analyzer: Optional[DomesticImpactAnalyzer] = None

        # 인덱스 (JSON 모드에서만 사용)
        self._by_inn: dict[str, DomesticImpact] = {}

        # 메타
        self.loaded_at: Optional[datetime] = None
        self.fda_count = 0
        self.ema_count = 0
        self.mfds_count = 0
        self.cris_count = 0
        self.drug_count = 0

    # ──────────────────────────────────────────────
    # JSON 모드 (동기) — 기존 동작 유지
    # ──────────────────────────────────────────────

    def load(self, data_dir: Path) -> None:
        """데이터 로드 - 각 소스의 최신 파일을 자동 탐색"""
        # 최신 파일 자동 탐색
        files = {
            "fda": _find_latest(data_dir / "fda", "approvals_*.json"),
            "ema": _find_latest(data_dir / "ema", "medicines_*.json"),
            "mfds": (
                _find_latest(data_dir / "mfds", "permits_full_*.json")
                or _find_latest(data_dir / "mfds", "permits_*.json")
            ),
            "cris": _find_latest(data_dir / "cris", "trials_full_*.json"),
        }

        # 로드
        raw_data = {}
        for key, path in files.items():
            if path and path.exists():
                with open(path, encoding="utf-8") as f:
                    raw_data[key] = json.load(f)
                logger.info(f"[DataStore] {key} 로드: {path.name}")
            else:
                logger.warning(f"[DataStore] {key} 데이터 파일 없음")

        # 파싱
        fda_parsed = FDADrugParser().parse_many(raw_data.get("fda", []))
        ema_parsed = EMAMedicineParser().parse_many(raw_data.get("ema", []))
        mfds_parsed = MFDSPermitParser().parse_many(raw_data.get("mfds", []))
        cris_parsed = CRISTrialParser().parse_many(raw_data.get("cris", []))

        self.fda_count = len(fda_parsed)
        self.ema_count = len(ema_parsed)
        self.mfds_count = len(mfds_parsed)
        self.cris_count = len(cris_parsed)

        # GlobalRegulatoryStatus 생성
        self.statuses = merge_global_status(
            fda_list=fda_parsed,
            ema_list=ema_parsed,
            mfds_list=mfds_parsed,
        )

        # DomesticImpactAnalyzer 실행
        self.analyzer = DomesticImpactAnalyzer()
        self.analyzer.load_cris_data(cris_parsed)
        self.impacts = self.analyzer.analyze_batch(self.statuses)

        # 인덱스 생성
        self._by_inn = {
            impact.inn.lower(): impact
            for impact in self.impacts
            if impact.inn
        }

        self.drug_count = len(self.impacts)
        self.loaded_at = datetime.now()

    def get_by_inn(self, inn: str) -> Optional[DomesticImpact]:
        """INN으로 조회 (JSON 모드)"""
        return self._by_inn.get(inn.lower())

    def search(self, query: str, limit: int = 20) -> list[DomesticImpact]:
        """검색 (JSON 모드)"""
        query_lower = query.lower()
        results = []
        for impact in self.impacts:
            if query_lower in impact.inn.lower():
                results.append(impact)
                if len(results) >= limit:
                    break
        return results

    def get_hot_issues(self, min_score: int = 60) -> list[DomesticImpact]:
        """핫이슈 조회 (JSON 모드)"""
        return sorted(
            [i for i in self.impacts if i.global_score >= min_score],
            key=lambda x: -x.global_score
        )

    def get_imminent(self) -> list[DomesticImpact]:
        """국내 도입 임박 약물 (JSON 모드)"""
        return sorted(
            [i for i in self.impacts if i.domestic_status == DomesticStatus.IMMINENT],
            key=lambda x: -x.global_score
        )

    def get_high_value(self, min_price: float = 1_000_000) -> list[DomesticImpact]:
        """고가 급여 약물 (JSON 모드)"""
        return sorted(
            [i for i in self.impacts
             if i.hira_price and i.hira_price >= min_price],
            key=lambda x: -(x.hira_price or 0)
        )

    # ──────────────────────────────────────────────
    # PG 모드 (비동기) — 온디맨드 DB 쿼리
    # ──────────────────────────────────────────────

    def _drug_row_to_impact(self, drug: DrugDB) -> DomesticImpact:
        """DrugDB row -> DomesticImpact 변환

        drug 객체는 events, hira, trials 관계가 이미 eager-load 된 상태여야 함.
        """
        # --- 규제 이벤트에서 승인 정보 추출 ---
        fda_approved = False
        fda_date = None
        ema_approved = False
        ema_date = None
        mfds_approved = False
        mfds_date = None
        mfds_brand_name = ""

        for event in (drug.events or []):
            agency = event.agency.lower() if event.agency else ""
            if agency == "fda":
                fda_approved = True
                fda_date = event.approval_date
            elif agency == "ema":
                ema_approved = True
                ema_date = event.approval_date
            elif agency == "mfds":
                mfds_approved = True
                mfds_date = event.approval_date
                mfds_brand_name = event.brand_name or ""

        # --- HIRA 급여 정보 (첫 번째 레코드 사용) ---
        hira_status = None
        hira_code = ""
        hira_criteria = ""
        hira_price = None

        if drug.hira:
            hira_row = drug.hira[0]
            if hira_row.status:
                try:
                    hira_status = ReimbursementStatus(hira_row.status)
                except ValueError:
                    logger.warning(
                        f"[DataStore] 알 수 없는 hira_status: {hira_row.status} (inn={drug.inn})"
                    )
            hira_code = hira_row.ingredient_code or ""
            hira_criteria = hira_row.criteria or ""
            hira_price = hira_row.price_ceiling

        # --- CRIS 임상시험 ---
        cris_trials = []
        for trial in (drug.trials or []):
            cris_trials.append(
                ClinicalTrialInfo(
                    trial_id=trial.trial_id or "",
                    title=trial.title or "",
                    phase=trial.phase or "",
                    status=trial.status or "",
                    indication=trial.indication or "",
                    sponsor=trial.sponsor or "",
                )
            )

        has_active_trial = any(
            t.status and t.status.lower() in ("recruiting", "active", "enrolling")
            for t in (drug.trials or [])
        )

        # --- DomesticStatus ---
        domestic_status = DomesticStatus.NOT_APPLICABLE
        if drug.domestic_status:
            try:
                domestic_status = DomesticStatus(drug.domestic_status)
            except ValueError:
                logger.warning(
                    f"[DataStore] 알 수 없는 domestic_status: {drug.domestic_status} (inn={drug.inn})"
                )

        # --- DomesticImpact 생성 ---
        return DomesticImpact(
            inn=drug.inn or "",
            domestic_status=domestic_status,
            fda_approved=fda_approved,
            fda_date=fda_date,
            ema_approved=ema_approved,
            ema_date=ema_date,
            mfds_approved=mfds_approved,
            mfds_date=mfds_date,
            mfds_brand_name=mfds_brand_name,
            hira_status=hira_status,
            hira_code=hira_code,
            hira_criteria=hira_criteria,
            hira_price=hira_price,
            cris_trials=cris_trials,
            has_active_trial=has_active_trial,
            global_score=drug.global_score or 0,
            hot_issue_reasons=drug.hot_issue_reasons or [],
        )

    async def aload_counts(self) -> None:
        """기동 시 카운트만 로드 (PG 모드)

        전체 drugs를 메모리에 올리지 않고 COUNT 쿼리만 실행.
        """
        session_factory = get_async_session()

        async with session_factory() as session:
            # agency별 regulatory_events 카운트
            stmt = (
                select(
                    RegulatoryEventDB.agency,
                    func.count(RegulatoryEventDB.id),
                )
                .group_by(RegulatoryEventDB.agency)
            )
            result = await session.execute(stmt)
            agency_counts = {row[0].lower(): row[1] for row in result.all() if row[0]}

            self.fda_count = agency_counts.get("fda", 0)
            self.ema_count = agency_counts.get("ema", 0)
            self.mfds_count = agency_counts.get("mfds", 0)

            # CRIS 임상시험 카운트
            cris_stmt = select(func.count(ClinicalTrialDB.id))
            cris_result = await session.execute(cris_stmt)
            self.cris_count = cris_result.scalar() or 0

            # 전체 drug 수
            drug_stmt = select(func.count(DrugDB.id))
            drug_result = await session.execute(drug_stmt)
            self.drug_count = drug_result.scalar() or 0

        self.loaded_at = datetime.now()
        logger.info(
            f"[DataStore] PG 카운트 로드 완료: drugs={self.drug_count}, "
            f"fda={self.fda_count}, ema={self.ema_count}, "
            f"mfds={self.mfds_count}, cris={self.cris_count}"
        )

    async def _aquery_drugs(self, stmt) -> list[DomesticImpact]:
        """공통 DB 쿼리 실행 + DomesticImpact 변환 헬퍼"""
        session_factory = get_async_session()
        async with session_factory() as session:
            result = await session.execute(stmt)
            drugs = result.scalars().all()
            return [self._drug_row_to_impact(drug) for drug in drugs]

    def _base_drug_query(self):
        """eagerly-loaded relationships가 포함된 기본 DrugDB 쿼리문 반환"""
        return (
            select(DrugDB)
            .options(
                selectinload(DrugDB.events),
                selectinload(DrugDB.hira),
                selectinload(DrugDB.trials),
            )
        )

    async def aget_hot_issues(self, min_score: int = 60) -> list[DomesticImpact]:
        """DB에서 핫이슈 조회 (PG 모드)"""
        stmt = (
            self._base_drug_query()
            .where(DrugDB.global_score >= min_score)
            .order_by(DrugDB.global_score.desc())
        )
        return await self._aquery_drugs(stmt)

    async def aget_imminent(self) -> list[DomesticImpact]:
        """DB에서 도입 임박 약물 조회 (PG 모드)"""
        stmt = (
            self._base_drug_query()
            .where(DrugDB.domestic_status == DomesticStatus.IMMINENT.value)
            .order_by(DrugDB.global_score.desc())
        )
        return await self._aquery_drugs(stmt)

    async def aget_by_inn(self, inn: str) -> Optional[DomesticImpact]:
        """DB에서 INN으로 약물 조회 (PG 모드, case insensitive)"""
        stmt = (
            self._base_drug_query()
            .where(func.lower(DrugDB.inn) == inn.lower())
        )
        session_factory = get_async_session()
        async with session_factory() as session:
            result = await session.execute(stmt)
            drug = result.scalars().first()
            if drug is None:
                return None
            return self._drug_row_to_impact(drug)

    async def asearch(self, query: str, limit: int = 20) -> list[DomesticImpact]:
        """DB에서 검색 (PG 모드, ILIKE)"""
        stmt = (
            self._base_drug_query()
            .where(DrugDB.inn.ilike(f"%{query}%"))
            .limit(limit)
        )
        return await self._aquery_drugs(stmt)

    async def aget_high_value(self, min_price: float = 1_000_000) -> list[DomesticImpact]:
        """DB에서 고가 약물 조회 (PG 모드)"""
        stmt = (
            self._base_drug_query()
            .join(DrugDB.hira)
            .where(HIRAReimbursementDB.price_ceiling >= min_price)
            .order_by(HIRAReimbursementDB.price_ceiling.desc())
        )
        return await self._aquery_drugs(stmt)


# ──────────────────────────────────────────────
# 싱글톤 + 모듈 레벨 함수
# ──────────────────────────────────────────────

_store: Optional[DataStore] = None


def get_data_store() -> DataStore:
    """DataStore 싱글톤 반환 (JSON 모드에서 자동 로드)"""
    global _store
    if _store is None:
        _store = DataStore()
        if not settings.is_postgres:
            data_dir = Path(__file__).parent.parent.parent / "data"
            _store.load(data_dir)
    return _store


def reload_data() -> DataStore:
    """데이터 리로드 (JSON 모드)"""
    global _store
    _store = DataStore()
    data_dir = Path(__file__).parent.parent.parent / "data"
    _store.load(data_dir)
    return _store


async def reload_data_from_db() -> DataStore:
    """DB에서 카운트만 리로드 (PG 모드)"""
    global _store
    _store = DataStore()
    await _store.aload_counts()
    return _store
