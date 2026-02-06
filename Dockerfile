FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 (PostgreSQL 클라이언트)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# 의존성 설치
COPY pyproject.toml .
RUN pip install --no-cache-dir . ".[llm]"

# 소스 복사
COPY . .

# Cloud Run Jobs 배치 파이프라인
CMD ["python", "-m", "regscan.batch.pipeline"]
