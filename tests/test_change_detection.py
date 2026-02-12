"""변경 감지(Change Detection) 테스트

테스트 항목:
  1. 새 약물 INSERT → new_drug change 생성 확인
  2. 점수 변경 → score_change 생성 확인
  3. 동일 데이터 재 upsert → change 미생성 확인
  4. 새 이벤트 추가 → new_event 생성 확인
  5. changed_drug_ids 반환값 검증
"""

import asyncio
import os
import pytest
from datetime import datetime

# 테스트 전용 in-memory DB 설정 (import 전에 환경변수 설정)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["DATABASE_URL_SYNC"] = "sqlite://"

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from regscan.db.models import Base, DrugDB, DrugChangeLogDB, RegulatoryEventDB
from regscan.db.loader import DBLoader
from regscan.scan.domestic import DomesticImpact, DomesticStatus


# ── Fixtures ──


@pytest.fixture
def event_loop():
    """pytest-asyncio용 이벤트 루프."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session():
    """테스트용 in-memory SQLite async 세션."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory

    await engine.dispose()


@pytest.fixture
def loader(db_session):
    """테스트용 DBLoader (in-memory DB 사용)."""
    ldr = DBLoader()
    ldr._session_factory = db_session
    return ldr


def _make_impact(
    inn: str = "testdrug",
    global_score: int = 50,
    domestic_status: DomesticStatus = DomesticStatus.EXPECTED,
    fda_approved: bool = False,
    ema_approved: bool = False,
    mfds_approved: bool = False,
) -> DomesticImpact:
    """테스트용 DomesticImpact 생성 헬퍼."""
    return DomesticImpact(
        inn=inn,
        domestic_status=domestic_status,
        fda_approved=fda_approved,
        ema_approved=ema_approved,
        mfds_approved=mfds_approved,
        global_score=global_score,
    )


# ── Tests ──

RUN_ID = "test-run-00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_new_drug_creates_change(loader, db_session):
    """1. 새 약물 INSERT → new_drug change 생성"""
    impact = _make_impact(inn="newdrug", global_score=60)

    result = await loader.upsert_impacts([impact], pipeline_run_id=RUN_ID)

    assert result["drugs"] == 1
    assert result["changes"] == 1
    assert len(result["changed_drug_ids"]) == 1

    # DB에서 change_log 확인
    async with db_session() as session:
        stmt = select(DrugChangeLogDB).where(DrugChangeLogDB.change_type == "new_drug")
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].field_name == "inn"
        assert rows[0].new_value == "newdrug"
        assert rows[0].old_value is None
        assert rows[0].pipeline_run_id == RUN_ID


@pytest.mark.asyncio
async def test_score_change_creates_change(loader, db_session):
    """2. 점수 변경 → score_change 생성"""
    # 1회차: 초기 INSERT
    impact_v1 = _make_impact(inn="scored", global_score=50)
    await loader.upsert_impacts([impact_v1], pipeline_run_id=RUN_ID)

    # 2회차: 점수 변경
    impact_v2 = _make_impact(inn="scored", global_score=80)
    run_id_2 = "test-run-00000000-0000-0000-0000-000000000002"
    result = await loader.upsert_impacts([impact_v2], pipeline_run_id=run_id_2)

    assert result["changes"] >= 1

    # DB에서 score_change 확인
    async with db_session() as session:
        stmt = select(DrugChangeLogDB).where(
            DrugChangeLogDB.change_type == "score_change",
            DrugChangeLogDB.pipeline_run_id == run_id_2,
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].field_name == "global_score"
        assert rows[0].old_value == "50"
        assert rows[0].new_value == "80"


@pytest.mark.asyncio
async def test_no_change_on_same_data(loader, db_session):
    """3. 동일 데이터 재 upsert → change 미생성"""
    impact = _make_impact(inn="stable", global_score=60)

    # 1회차
    run_id_1 = "test-run-same-1"
    await loader.upsert_impacts([impact], pipeline_run_id=run_id_1)

    # 2회차: 동일 데이터
    run_id_2 = "test-run-same-2"
    result = await loader.upsert_impacts([impact], pipeline_run_id=run_id_2)

    # 2회차에서는 new_drug도 아니고, score도 같으므로 변경 없음
    async with db_session() as session:
        stmt = select(DrugChangeLogDB).where(
            DrugChangeLogDB.pipeline_run_id == run_id_2
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 0

    assert result["changes"] == 0
    assert len(result["changed_drug_ids"]) == 0


@pytest.mark.asyncio
async def test_new_event_creates_change(loader, db_session):
    """4. 새 이벤트 추가 → new_event 생성"""
    # 1회차: 약물만 (FDA 미승인)
    impact_v1 = _make_impact(inn="eventdrug", global_score=50, fda_approved=False)
    await loader.upsert_impacts([impact_v1], pipeline_run_id="run-evt-1")

    # 2회차: FDA 승인 추가
    impact_v2 = _make_impact(inn="eventdrug", global_score=50, fda_approved=True)
    result = await loader.upsert_impacts([impact_v2], pipeline_run_id="run-evt-2")

    assert result["changes"] >= 1

    # DB에서 new_event 확인
    async with db_session() as session:
        stmt = select(DrugChangeLogDB).where(
            DrugChangeLogDB.change_type == "new_event",
            DrugChangeLogDB.pipeline_run_id == "run-evt-2",
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].field_name == "fda_approval"
        assert rows[0].new_value == "approved"


@pytest.mark.asyncio
async def test_changed_drug_ids_returned(loader, db_session):
    """5. changed_drug_ids 반환값 검증"""
    impacts = [
        _make_impact(inn="drug_a", global_score=50),
        _make_impact(inn="drug_b", global_score=70),
        _make_impact(inn="drug_c", global_score=90),
    ]

    # 1회차: 모든 약물이 new_drug
    result = await loader.upsert_impacts(impacts, pipeline_run_id="run-multi-1")
    assert len(result["changed_drug_ids"]) == 3

    # 2회차: drug_b만 점수 변경
    impacts_v2 = [
        _make_impact(inn="drug_a", global_score=50),   # 동일
        _make_impact(inn="drug_b", global_score=90),   # 변경
        _make_impact(inn="drug_c", global_score=90),   # 동일
    ]
    result_v2 = await loader.upsert_impacts(impacts_v2, pipeline_run_id="run-multi-2")

    assert len(result_v2["changed_drug_ids"]) == 1
    assert result_v2["changes"] == 1

    # drug_b의 id만 포함 확인
    async with db_session() as session:
        stmt = select(DrugDB.id).where(DrugDB.inn == "drug_b")
        drug_b_id = (await session.execute(stmt)).scalar_one()
        assert drug_b_id in result_v2["changed_drug_ids"]


@pytest.mark.asyncio
async def test_status_change_detection(loader, db_session):
    """hot_issue_level 변경 감지."""
    # MID (score=50) → HOT (score=80)
    impact_v1 = _make_impact(inn="statusdrug", global_score=50)
    await loader.upsert_impacts([impact_v1], pipeline_run_id="run-status-1")

    impact_v2 = _make_impact(inn="statusdrug", global_score=80)
    await loader.upsert_impacts([impact_v2], pipeline_run_id="run-status-2")

    async with db_session() as session:
        stmt = select(DrugChangeLogDB).where(
            DrugChangeLogDB.change_type == "status_change",
            DrugChangeLogDB.field_name == "hot_issue_level",
            DrugChangeLogDB.pipeline_run_id == "run-status-2",
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].old_value == "MID"
        assert rows[0].new_value == "HOT"


@pytest.mark.asyncio
async def test_no_pipeline_run_id_skips_detection(loader, db_session):
    """pipeline_run_id 없이 호출 시 변경 감지 안 함 (하위 호환)."""
    impact = _make_impact(inn="legacy", global_score=60)

    result = await loader.upsert_impacts([impact])

    assert result["drugs"] == 1
    assert result["changes"] == 0
    assert len(result["changed_drug_ids"]) == 0

    # change_log 테이블에 기록 없음
    async with db_session() as session:
        stmt = select(DrugChangeLogDB)
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 0
