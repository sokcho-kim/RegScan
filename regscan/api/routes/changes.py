"""변경 감지 로그 API"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from regscan.api.schemas import ChangeLogResponse

router = APIRouter()


@router.get("/recent", response_model=list[ChangeLogResponse])
async def get_recent_changes(
    hours: int = Query(default=24, ge=1, le=168, description="최근 N시간 이내 변경"),
    limit: int = Query(default=50, ge=1, le=200, description="최대 건수"),
    change_type: str | None = Query(
        default=None,
        description="변경 유형 필터 (new_drug, score_change, status_change, new_event, designation_change, new_preprint)",
    ),
):
    """최근 변경 감지 로그 조회

    파이프라인 실행 시 감지된 약물 데이터 변경 이력을 조회합니다.
    """
    from regscan.config import settings
    if not settings.is_postgres:
        raise HTTPException(status_code=501, detail="PostgreSQL 모드에서만 지원됩니다")

    from regscan.db.database import get_async_session
    from regscan.db.models import DrugChangeLogDB, DrugDB
    from sqlalchemy import select

    since = datetime.utcnow() - timedelta(hours=hours)

    async with get_async_session()() as session:
        stmt = (
            select(DrugChangeLogDB, DrugDB.inn)
            .join(DrugDB, DrugChangeLogDB.drug_id == DrugDB.id)
            .where(DrugChangeLogDB.detected_at >= since)
        )

        if change_type:
            stmt = stmt.where(DrugChangeLogDB.change_type == change_type)

        stmt = stmt.order_by(DrugChangeLogDB.detected_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            ChangeLogResponse(
                id=row.DrugChangeLogDB.id,
                drug_id=row.DrugChangeLogDB.drug_id,
                inn=row.inn or "",
                change_type=row.DrugChangeLogDB.change_type,
                field_name=row.DrugChangeLogDB.field_name,
                old_value=row.DrugChangeLogDB.old_value,
                new_value=row.DrugChangeLogDB.new_value,
                pipeline_run_id=row.DrugChangeLogDB.pipeline_run_id,
                detected_at=row.DrugChangeLogDB.detected_at,
            )
            for row in rows
        ]
