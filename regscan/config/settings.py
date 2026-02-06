"""프로젝트 설정"""

import os
from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """RegScan 설정"""

    # 프로젝트 경로
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"

    # DB (PostgreSQL for prod, SQLite for local dev)
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATA_DIR}/regscan.db"
    DATABASE_URL_SYNC: str = f"sqlite:///{DATA_DIR}/regscan.db"

    # GCS (비어있으면 스킵 — 로컬 개발 시 불필요)
    GCS_BUCKET: str = ""
    GCS_PREFIX: str = "raw/"

    # Cloud SQL (Cloud Run에서 Unix socket 연결)
    CLOUD_SQL_CONNECTION_NAME: str = ""

    @property
    def DB_URL(self) -> str:
        """레거시 호환 — 기존 FeedCardRepository 등에서 사용"""
        return self.DATABASE_URL

    @property
    def is_postgres(self) -> bool:
        """PostgreSQL 모드 여부"""
        return self.DATABASE_URL.startswith("postgresql")

    # FDA API
    FDA_API_KEY: Optional[str] = None
    FDA_BASE_URL: str = "https://api.fda.gov"
    FDA_TIMEOUT: float = 30.0

    # LLM
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    LLM_TIMEOUT: float = 5.0
    USE_LLM: bool = True

    # 공공데이터 API
    DATA_GO_KR_API_KEY: Optional[str] = None  # 공공데이터포털
    OPEN_ASSEMBLY_API_KEY: Optional[str] = None  # 열린국회정보

    # 수집 설정
    COLLECT_DAYS_BACK: int = 7  # 최근 N일 수집

    # 스케줄러
    SCHEDULER_ENABLED: bool = True
    DAILY_SCAN_HOUR: int = 8        # 매일 08:00 스캔
    DAILY_SCAN_MINUTE: int = 0
    SCAN_DAYS_BACK: int = 7         # 최근 7일 스캔
    GENERATE_BRIEFING: bool = True  # 핫이슈 브리핑 자동 생성
    GENERATE_HTML: bool = True      # HTML 뉴스레터 자동 생성

    # 로깅
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 추가 환경변수 무시


settings = Settings()
