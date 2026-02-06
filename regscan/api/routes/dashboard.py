"""대시보드 HTML 라우트"""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
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
