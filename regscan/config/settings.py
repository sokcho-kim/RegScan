"""프로젝트 설정"""

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """RegScan 설정"""

    # 프로젝트 경로
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"

    # DB
    DB_URL: str = f"sqlite+aiosqlite:///{DATA_DIR}/regscan.db"

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

    # 로깅
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 추가 환경변수 무시


settings = Settings()
