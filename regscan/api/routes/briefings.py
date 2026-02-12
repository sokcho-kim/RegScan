"""브리핑 API

GET /api/v1/briefings/latest?stream=therapeutic_area&area=oncology
GET /api/v1/briefings/unified/latest
GET /api/v1/briefings/history?days=7
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


# ── Schemas ──

class BriefingItem(BaseModel):
    id: int
    stream_name: str
    sub_category: str = ""
    briefing_type: str
    headline: str = ""
    content_json: dict = {}
    generated_at: Optional[datetime] = None
    pipeline_run_id: Optional[str] = None


# ── Endpoints ──

@router.get("/latest", response_model=list[BriefingItem])
async def get_latest_briefings(
    stream: Optional[str] = Query(None, description="스트림 이름 (therapeutic_area, innovation, external)"),
    area: Optional[str] = Query(None, description="치료영역 (oncology, rare_disease, ...)"),
):
    """최신 스트림별 브리핑 조회"""
    from regscan.db.database import get_async_session
    from regscan.db.models import StreamBriefingDB
    from sqlalchemy import select

    try:
        async with get_async_session()() as session:
            stmt = (
                select(StreamBriefingDB)
                .where(StreamBriefingDB.briefing_type == "stream")
                .order_by(StreamBriefingDB.generated_at.desc())
                .limit(20)
            )

            if stream:
                stmt = stmt.where(StreamBriefingDB.stream_name == stream)
            if area:
                stmt = stmt.where(StreamBriefingDB.sub_category == area)

            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                BriefingItem(
                    id=row.id,
                    stream_name=row.stream_name,
                    sub_category=row.sub_category or "",
                    briefing_type=row.briefing_type,
                    headline=row.headline or "",
                    content_json=row.content_json or {},
                    generated_at=row.generated_at,
                    pipeline_run_id=row.pipeline_run_id,
                )
                for row in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"브리핑 조회 실패: {e}")


@router.get("/unified/latest", response_model=Optional[BriefingItem])
async def get_latest_unified_briefing():
    """최신 통합 브리핑 조회"""
    from regscan.db.database import get_async_session
    from regscan.db.models import StreamBriefingDB
    from sqlalchemy import select

    try:
        async with get_async_session()() as session:
            stmt = (
                select(StreamBriefingDB)
                .where(StreamBriefingDB.briefing_type == "unified")
                .order_by(StreamBriefingDB.generated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if not row:
                return None

            return BriefingItem(
                id=row.id,
                stream_name=row.stream_name,
                sub_category=row.sub_category or "",
                briefing_type=row.briefing_type,
                headline=row.headline or "",
                content_json=row.content_json or {},
                generated_at=row.generated_at,
                pipeline_run_id=row.pipeline_run_id,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통합 브리핑 조회 실패: {e}")


@router.get("/history", response_model=list[BriefingItem])
async def get_briefing_history(
    days: int = Query(7, ge=1, le=90, description="조회 기간 (일)"),
):
    """브리핑 히스토리"""
    from regscan.db.database import get_async_session
    from regscan.db.models import StreamBriefingDB
    from sqlalchemy import select

    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with get_async_session()() as session:
            stmt = (
                select(StreamBriefingDB)
                .where(StreamBriefingDB.generated_at >= cutoff)
                .order_by(StreamBriefingDB.generated_at.desc())
                .limit(100)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                BriefingItem(
                    id=row.id,
                    stream_name=row.stream_name,
                    sub_category=row.sub_category or "",
                    briefing_type=row.briefing_type,
                    headline=row.headline or "",
                    content_json=row.content_json or {},
                    generated_at=row.generated_at,
                    pipeline_run_id=row.pipeline_run_id,
                )
                for row in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"브리핑 히스토리 조회 실패: {e}")
