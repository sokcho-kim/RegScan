"""크롤러 건강 대시보드 — 수집기 상태 모니터링"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import select, func, desc
from regscan.db.database import get_async_session
from regscan.db.models import IngestRunDB

router = APIRouter()
templates = Jinja2Templates(
    directory="regscan/api/templates",
)

# 소스별 예상 갱신 주기 (시간) — 이 주기의 2배 이상 미수집이면 ORANGE
EXPECTED_INTERVALS = {
    "PMDA_REVIEW": 168,        # 주간
    "PMDA_SAFETY": 168,
    "PMDA_APPROVAL": 720,      # 월간
    "NICE_TA": 720,
    "MFDS_SAFETY_LETTER": 720,
    "MOHW_HEALTH_INSURANCE": 720,
    "ASSEMBLY_BILL": 168,
    "DART_DISCLOSURE": 48,     # 2일
    "KIPRIS_PATENT": 720,
}


@router.get("/dashboard/health", response_class=HTMLResponse)
async def health_dashboard(request: Request):
    """수집기 건강 대시보드"""
    now = datetime.utcnow()
    cutoff_7d = now - timedelta(days=7)

    async with get_async_session()() as session:
        # 소스별 최근 실행
        latest_stmt = (
            select(
                IngestRunDB.source_type,
                func.max(IngestRunDB.started_at).label("last_run"),
                func.count(IngestRunDB.id).label("total_runs"),
            )
            .group_by(IngestRunDB.source_type)
        )
        latest_result = await session.execute(latest_stmt)
        latest_by_source = {
            row.source_type: {
                "last_run": row.last_run,
                "total_runs": row.total_runs,
            }
            for row in latest_result
        }

        # 소스별 최근 성공 건수 + 에러 수
        detail_stmt = (
            select(
                IngestRunDB.source_type,
                IngestRunDB.status,
                func.count(IngestRunDB.id).label("cnt"),
                func.avg(IngestRunDB.record_count).label("avg_records"),
                func.avg(IngestRunDB.duration_ms).label("avg_duration"),
            )
            .where(IngestRunDB.started_at >= cutoff_7d)
            .group_by(IngestRunDB.source_type, IngestRunDB.status)
        )
        detail_result = await session.execute(detail_stmt)

        stats: dict = {}
        for row in detail_result:
            if row.source_type not in stats:
                stats[row.source_type] = {
                    "success": 0, "error": 0, "skip": 0,
                    "avg_records": 0, "avg_duration": 0,
                }
            stats[row.source_type][row.status.lower()] = row.cnt
            if row.status == "SUCCESS":
                stats[row.source_type]["avg_records"] = round(
                    row.avg_records or 0
                )
                stats[row.source_type]["avg_duration"] = round(
                    row.avg_duration or 0
                )

        # 최근 실행 이력 (전체, 최신 30건)
        recent_stmt = (
            select(IngestRunDB)
            .order_by(desc(IngestRunDB.started_at))
            .limit(30)
        )
        recent_result = await session.execute(recent_stmt)
        recent_runs = recent_result.scalars().all()

    # 상태 판정
    sources = []
    for src_type in sorted(
        set(list(latest_by_source.keys()) + list(EXPECTED_INTERVALS.keys()))
    ):
        info = latest_by_source.get(src_type, {})
        stat = stats.get(src_type, {})
        last_run = info.get("last_run")

        # 상태 판정
        if not last_run:
            status = "GRAY"  # 실행 기록 없음
        elif stat.get("error", 0) >= 3 and stat.get("success", 0) == 0:
            status = "RED"   # 최근 7일 연속 실패
        elif stat.get("error", 0) > 0:
            status = "YELLOW"  # 에러 있음
        else:
            expected_h = EXPECTED_INTERVALS.get(src_type, 168)
            hours_since = (now - last_run).total_seconds() / 3600
            if hours_since > expected_h * 2:
                status = "ORANGE"  # 예상 주기 초과
            else:
                status = "GREEN"

        sources.append({
            "source_type": src_type,
            "status": status,
            "last_run": last_run,
            "total_runs": info.get("total_runs", 0),
            "success_7d": stat.get("success", 0),
            "error_7d": stat.get("error", 0),
            "avg_records": stat.get("avg_records", 0),
            "avg_duration_ms": stat.get("avg_duration", 0),
        })

    return templates.TemplateResponse("health.html", {
        "request": request,
        "sources": sources,
        "recent_runs": recent_runs,
        "now": now,
    })


@router.get("/api/health/ingest-runs")
async def api_ingest_runs(
    days: int = 7,
    source_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    """수집 이력 JSON API"""
    cutoff = datetime.utcnow() - timedelta(days=days)

    async with get_async_session()() as session:
        stmt = (
            select(IngestRunDB)
            .where(IngestRunDB.started_at >= cutoff)
            .order_by(desc(IngestRunDB.started_at))
            .limit(limit)
        )
        if source_type:
            stmt = stmt.where(IngestRunDB.source_type == source_type)
        if status:
            stmt = stmt.where(IngestRunDB.status == status)

        result = await session.execute(stmt)
        runs = result.scalars().all()

    return [
        {
            "id": r.id,
            "pipeline_run_id": r.pipeline_run_id,
            "source_type": r.source_type,
            "status": r.status,
            "record_count": r.record_count,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_ms": r.duration_ms,
        }
        for r in runs
    ]
