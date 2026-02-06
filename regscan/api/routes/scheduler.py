"""스케줄러 API 라우트"""

import asyncio

from fastapi import APIRouter

from regscan.scheduler import run_daily_pipeline, get_scheduler_status

router = APIRouter()


@router.get("/status")
def scheduler_status():
    """스케줄러 상태 조회"""
    return get_scheduler_status()


@router.post("/run-now")
async def run_now():
    """일간 파이프라인 즉시 실행 (백그라운드)

    파이프라인을 백그라운드 태스크로 실행하고 즉시 응답합니다.
    실행 결과는 GET /status에서 last_run으로 확인할 수 있습니다.
    """
    asyncio.create_task(run_daily_pipeline())
    return {
        "message": "일간 파이프라인 실행이 시작되었습니다",
        "check_status": "/api/v1/scheduler/status",
    }
