"""RegScan API 메인"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from regscan.api.routes import stats, drugs, scheduler as scheduler_routes
from regscan.api.routes import dashboard as dashboard_routes
from regscan.api.routes import changes as changes_routes
from regscan.api.routes import pdufa as pdufa_routes
from regscan.api.routes import briefings as briefing_routes
from regscan.api.deps import get_data_store
from regscan.config import settings

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 데이터 로드, DB 초기화, 스케줄러 관리"""
    # DB 초기화 (테이블 생성)
    if settings.is_postgres:
        try:
            from regscan.db.database import init_db
            await init_db()
            logger.info("DB 초기화 완료")
        except Exception as e:
            logger.error(f"DB 초기화 실패: {e}", exc_info=True)

    # 데이터 로드
    logger.info("데이터 로딩 시작...")
    try:
        if settings.is_postgres:
            # PG 모드: 카운트만 로드 (전체 메모리 로드 X)
            from regscan.api.deps import reload_data_from_db
            store = await reload_data_from_db()
            logger.info(
                f"DB 카운트 로드 완료: "
                f"FDA {store.fda_count}, EMA {store.ema_count}, "
                f"MFDS {store.mfds_count} (on-demand 쿼리 모드)"
            )
        else:
            # JSON 모드: 전체 메모리 로드
            store = get_data_store()
            logger.info(
                f"데이터 로드 완료: {len(store.impacts)}개 약물 "
                f"(FDA {store.fda_count}, EMA {store.ema_count}, "
                f"MFDS {store.mfds_count}, CRIS {store.cris_count})"
            )
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}", exc_info=True)

    # 스케줄러 시작 (로컬 개발 시에만 — Cloud Run에서는 비활성)
    if settings.SCHEDULER_ENABLED:
        from regscan.scheduler import start_scheduler

        start_scheduler()

    yield

    # 스케줄러 종료
    if settings.SCHEDULER_ENABLED:
        from regscan.scheduler import stop_scheduler

        stop_scheduler()

    # DB 엔진 종료
    if settings.is_postgres:
        try:
            from regscan.db.database import close_engines
            await close_engines()
        except Exception as e:
            logger.error(f"DB 엔진 종료 실패: {e}", exc_info=True)


app = FastAPI(
    title="RegScan API",
    description="글로벌 의약품 규제 인텔리전스 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(stats.router, prefix="/api/v1", tags=["Stats"])
app.include_router(drugs.router, prefix="/api/v1/drugs", tags=["Drugs"])
app.include_router(changes_routes.router, prefix="/api/v1/changes", tags=["Changes"])
app.include_router(scheduler_routes.router, prefix="/api/v1/scheduler", tags=["Scheduler"])
app.include_router(dashboard_routes.router, tags=["Dashboard"])
app.include_router(pdufa_routes.router, prefix="/api/v1/pdufa", tags=["PDUFA"])
app.include_router(briefing_routes.router, prefix="/api/v1/briefings", tags=["Briefings"])


@app.get("/")
def root():
    """API 상태"""
    return {
        "service": "RegScan API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
def health():
    """헬스체크"""
    store = get_data_store()
    drug_count = store.drug_count if settings.is_postgres else len(store.impacts)
    return {
        "status": "healthy",
        "loaded_at": store.loaded_at.isoformat() if store.loaded_at else None,
        "drug_count": drug_count,
        "mode": "postgres" if settings.is_postgres else "json",
    }
