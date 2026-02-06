"""DB 엔진 + 커넥션 풀링 + 세션 관리

- PostgreSQL: asyncpg (async) + psycopg2 (sync bulk)
- SQLite: aiosqlite (async) — 로컬 개발용
"""

import logging
from typing import Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import Session, sessionmaker

from regscan.config import settings
from regscan.db.models import Base

logger = logging.getLogger(__name__)

# 모듈 레벨 싱글톤
_async_engine: Optional[AsyncEngine] = None
_sync_engine: Optional[Engine] = None
_async_session_factory: Optional[async_sessionmaker] = None
_sync_session_factory: Optional[sessionmaker] = None


def _pool_kwargs() -> dict:
    """PostgreSQL 커넥션 풀링 설정 (SQLite에서는 무시)"""
    if settings.is_postgres:
        return {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
    return {}


def get_async_engine() -> AsyncEngine:
    """Async 엔진 (FastAPI 서빙용)"""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            **_pool_kwargs(),
        )
        logger.info(f"Async DB 엔진 생성: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL[:50]}")
    return _async_engine


def get_sync_engine() -> Engine:
    """Sync 엔진 (배치 벌크 인서트용)"""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.DATABASE_URL_SYNC,
            echo=False,
            **({k: v for k, v in _pool_kwargs().items() if k != "pool_pre_ping"} if settings.is_postgres else {}),
        )
        logger.info("Sync DB 엔진 생성")
    return _sync_engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Async 세션 팩토리"""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


def get_sync_session() -> sessionmaker[Session]:
    """Sync 세션 팩토리"""
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(
            get_sync_engine(),
            expire_on_commit=False,
        )
    return _sync_session_factory


async def init_db() -> None:
    """DB 테이블 생성 (없으면 CREATE)"""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB 테이블 초기화 완료")


async def close_engines() -> None:
    """엔진 종료 (앱 shutdown 시)"""
    global _async_engine, _sync_engine, _async_session_factory, _sync_session_factory

    if _async_engine:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
        logger.info("Async DB 엔진 종료")

    if _sync_engine:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None
        logger.info("Sync DB 엔진 종료")
