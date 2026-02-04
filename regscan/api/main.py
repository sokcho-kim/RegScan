"""RegScan API 메인"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from regscan.api.routes import stats, drugs
from regscan.api.deps import get_data_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 데이터 로드"""
    # 시작 시 데이터 로드
    print("Loading data...")
    store = get_data_store()
    print(f"Loaded {len(store.impacts)} drugs")
    yield
    # 종료 시 정리 (필요시)


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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(stats.router, prefix="/api/v1", tags=["Stats"])
app.include_router(drugs.router, prefix="/api/v1/drugs", tags=["Drugs"])


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
    return {
        "status": "healthy",
        "loaded_at": store.loaded_at.isoformat() if store.loaded_at else None,
        "drug_count": len(store.impacts),
    }
