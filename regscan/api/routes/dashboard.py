"""대시보드 HTML 라우트"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from regscan.api.deps import get_data_store, DataStore
from regscan.config import settings
from regscan.scheduler import get_scheduler_status

logger = logging.getLogger(__name__)

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _today_str() -> str:
    now = datetime.now()
    weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    return now.strftime(f"%Y년 %m월 %d일 ({weekday})")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, store: DataStore = Depends(get_data_store)):
    """메인 대시보드"""
    if settings.is_postgres:
        hot_issues = await store.aget_hot_issues(min_score=40)
        imminent = await store.aget_imminent()
        total_drugs = store.drug_count
    else:
        hot_issues = store.get_hot_issues(min_score=40)
        imminent = store.get_imminent()
        total_drugs = len(store.impacts)

    top_story = hot_issues[0] if hot_issues else None
    rest_issues = hot_issues[1:] if len(hot_issues) > 1 else []

    scheduler = get_scheduler_status()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "today": _today_str(),
            "fda_count": f"{store.fda_count:,}",
            "ema_count": f"{store.ema_count:,}",
            "mfds_count": f"{store.mfds_count:,}",
            "hot_count": len(hot_issues),
            "total_drugs": f"{total_drugs:,}",
            "top_story": top_story,
            "hot_issues": rest_issues,
            "imminent": imminent,
            "loaded_at": (
                store.loaded_at.strftime("%Y-%m-%d %H:%M")
                if store.loaded_at
                else None
            ),
            "scheduler": scheduler,
        },
    )


@router.get("/dashboard/drug/{inn}", response_class=HTMLResponse)
async def drug_briefing(
    request: Request,
    inn: str,
    store: DataStore = Depends(get_data_store),
):
    """약물 상세 기사 페이지

    저장된 LLM 브리핑을 로드합니다.
    저장 파일이 없으면 fallback 템플릿으로 표시합니다.
    """
    if settings.is_postgres:
        drug = await store.aget_by_inn(inn)
    else:
        drug = store.get_by_inn(inn)

    if not drug:
        raise HTTPException(status_code=404, detail=f"Drug not found: {inn}")

    # 저장된 브리핑 로드
    if settings.is_postgres:
        from regscan.db.loader import DBLoader
        loader = DBLoader()
        briefing = await loader.load_briefing(inn)
    else:
        from regscan.report.llm_generator import BriefingReport
        briefing = BriefingReport.load(inn)

    # 저장된 브리핑이 없으면 fallback 템플릿으로 즉시 생성
    if not briefing:
        from regscan.report.llm_generator import LLMBriefingGenerator
        generator = LLMBriefingGenerator()
        briefing = generator._generate_fallback(drug)

    return templates.TemplateResponse(
        "briefing.html",
        {
            "request": request,
            "today": _today_str(),
            "drug": drug,
            "briefing": briefing,
        },
    )


@router.get("/dashboard/briefing", response_class=HTMLResponse)
async def stream_briefing_page(
    request: Request,
    run_id: Optional[str] = Query(None),
):
    """V2 Executive Briefing 페이지"""

    if settings.is_postgres:
        runs, unified, streams = await _load_briefings_pg(run_id)
    else:
        runs, unified, streams = _load_briefings_sqlite(run_id)

    if not runs:
        raise HTTPException(status_code=404, detail="No briefings found")

    current_run = run_id or runs[0]["id"]

    return templates.TemplateResponse(
        "stream_briefing.html",
        {
            "request": request,
            "today": _today_str(),
            "runs": runs,
            "current_run": current_run,
            "unified": unified,
            "streams": streams,
        },
    )


def _load_briefings_sqlite(run_id: str | None):
    """SQLite에서 브리핑 로드."""
    import sqlite3

    raw_url = settings.DATABASE_URL
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        raw_url = raw_url.replace(prefix, "")
    db_path = Path(raw_url)
    if not db_path.exists():
        return [], None, []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    run_rows = conn.execute(
        """SELECT pipeline_run_id, MIN(generated_at) as first_at, COUNT(*) as cnt
           FROM stream_briefings
           GROUP BY pipeline_run_id
           ORDER BY MIN(generated_at) DESC"""
    ).fetchall()

    runs = []
    for r in run_rows:
        dt = r["first_at"][:16].replace("T", " ")
        runs.append({"id": r["pipeline_run_id"], "date": dt, "count": r["cnt"]})

    if not runs:
        conn.close()
        return [], None, []

    current_run = run_id or runs[0]["id"]

    rows = conn.execute(
        """SELECT stream_name, sub_category, briefing_type, headline, content_json
           FROM stream_briefings
           WHERE pipeline_run_id = ?
           ORDER BY id""",
        (current_run,),
    ).fetchall()
    conn.close()

    unified = None
    streams = []
    for row in rows:
        content = json.loads(row["content_json"]) if row["content_json"] else {}
        entry = {
            "stream_name": row["stream_name"],
            "sub_category": row["sub_category"] or "",
            "briefing_type": row["briefing_type"],
            "headline": row["headline"],
            "content": content,
        }
        if row["briefing_type"] == "unified":
            unified = content
        else:
            streams.append(entry)

    return runs, unified, streams


async def _load_briefings_pg(run_id: str | None):
    """PostgreSQL에서 브리핑 로드."""
    from sqlalchemy import select, func
    from regscan.db.database import get_async_session
    from regscan.db.models import StreamBriefingDB

    session_factory = get_async_session()
    async with session_factory() as session:
        # 파이프라인 실행 목록
        stmt = (
            select(
                StreamBriefingDB.pipeline_run_id,
                func.min(StreamBriefingDB.generated_at).label("first_at"),
                func.count().label("cnt"),
            )
            .group_by(StreamBriefingDB.pipeline_run_id)
            .order_by(func.min(StreamBriefingDB.generated_at).desc())
        )
        result = await session.execute(stmt)
        run_rows = result.all()

        runs = []
        for r in run_rows:
            dt = r.first_at.strftime("%Y-%m-%d %H:%M") if r.first_at else ""
            runs.append({"id": r.pipeline_run_id, "date": dt, "count": r.cnt})

        if not runs:
            return [], None, []

        current_run = run_id or runs[0]["id"]

        # 해당 run의 브리핑
        stmt2 = (
            select(StreamBriefingDB)
            .where(StreamBriefingDB.pipeline_run_id == current_run)
            .order_by(StreamBriefingDB.id)
        )
        result2 = await session.execute(stmt2)
        rows = result2.scalars().all()

    unified = None
    streams = []
    for row in rows:
        content = row.content_json or {}
        entry = {
            "stream_name": row.stream_name,
            "sub_category": row.sub_category or "",
            "briefing_type": row.briefing_type,
            "headline": row.headline or "",
            "content": content,
        }
        if row.briefing_type == "unified":
            unified = content
        else:
            streams.append(entry)

    return runs, unified, streams
