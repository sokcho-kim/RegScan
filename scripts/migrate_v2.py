"""v2 테이블 마이그레이션 스크립트

독립 실행 가능 — DATABASE_URL 환경변수만 설정하면 동작.
테이블이 이미 존재하면 스킵 (안전한 멱등 실행).

Usage:
    # 로컬 docker-compose PostgreSQL
    DATABASE_URL=postgresql+asyncpg://regscan:dev_password@localhost/regscan \
    DATABASE_URL_SYNC=postgresql+psycopg2://regscan:dev_password@localhost/regscan \
        python scripts/migrate_v2.py

    # Cloud SQL (Proxy 사용 시)
    DATABASE_URL_SYNC=postgresql+psycopg2://... python scripts/migrate_v2.py
"""

import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text
from regscan.config import settings
from regscan.db.models import Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

V2_TABLES = ["preprints", "market_reports", "expert_opinions", "ai_insights", "articles"]


def run_migration(database_url: str | None = None) -> dict[str, str]:
    """v2 테이블 생성 (없으면 CREATE, 있으면 SKIP).

    Returns:
        {table_name: "created" | "exists"} 결과 딕셔너리
    """
    url = database_url or settings.DATABASE_URL_SYNC
    logger.info("DB 연결: %s", url.split("@")[-1] if "@" in url else url[:50])

    engine = create_engine(url, echo=False)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    results: dict[str, str] = {}

    for table in V2_TABLES:
        if table in existing:
            logger.info("  [SKIP] %s — 이미 존재", table)
            results[table] = "exists"
        else:
            logger.info("  [CREATE] %s", table)
            results[table] = "created"

    # create_all은 이미 존재하는 테이블은 건너뜀 (SQLAlchemy 기본 동작)
    Base.metadata.create_all(engine, checkfirst=True)

    # 생성 후 검증
    inspector = inspect(engine)
    final_tables = set(inspector.get_table_names())

    for table in V2_TABLES:
        if table not in final_tables:
            logger.error("  [FAIL] %s — 생성 실패!", table)
            results[table] = "FAILED"

    engine.dispose()
    return results


def main():
    logger.info("=== v2 테이블 마이그레이션 시작 ===")
    results = run_migration()

    created = sum(1 for v in results.values() if v == "created")
    skipped = sum(1 for v in results.values() if v == "exists")
    failed = sum(1 for v in results.values() if v == "FAILED")

    logger.info("=== 마이그레이션 완료: created=%d, skipped=%d, failed=%d ===", created, skipped, failed)

    for table, status in results.items():
        logger.info("  %s: %s", table, status)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
