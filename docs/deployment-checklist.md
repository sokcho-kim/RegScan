# RegScan 배포 준비 체크리스트

> 점검일: 2026-02-19

---

## 요약

| # | 항목 | 상태 | 우선순위 |
|---|------|------|---------|
| 1 | 환경변수/시크릿 | **NEEDS WORK** | CRITICAL |
| 2 | Docker/배포 | **OK** | MEDIUM |
| 3 | 의존성 관리 | **NEEDS WORK** | HIGH |
| 4 | 데이터베이스 | **OK** | LOW |
| 5 | 에러 핸들링 | **NEEDS WORK** | MEDIUM |
| 6 | Rate Limiting | **OK** | LOW |
| 7 | 로깅 | **NEEDS WORK** | MEDIUM |
| 8 | 테스트 | **OK** | LOW |
| 9 | CI/CD | **MISSING** | HIGH |
| 10 | 보안 | **NEEDS WORK** | CRITICAL |

---

## 상세 분석

### 1. 환경변수/시크릿 — CRITICAL

- `.env` 파일에 실제 API 키가 평문으로 존재 (OpenAI, FDA, Gemini, 공공데이터포털)
- `.gitignore`에 `.env` 포함 — OK
- `.env.example` 존재 — OK
- **조치**: 모든 API 키 로테이션 필수. 프로덕션에서는 GCP Secret Manager 사용

### 2. Docker/배포 — OK (개선 가능)

- `Dockerfile` (배치) + `Dockerfile.web` (FastAPI) — 정상
- `docker-compose.yml` — PostgreSQL 14 + 헬스체크 — 정상
- **누락**: `.dockerignore` 파일 없음 → `.env`, `.git/`, `.venv/`, `data/` 등이 이미지에 포함됨
- **조치**: `.dockerignore` 생성 필수

### 3. 의존성 관리 — HIGH

- `pyproject.toml`에 최소 버전만 지정 (예: `httpx>=0.27.0`)
- 상한 없음, lockfile 없음
- **조치**: `pip freeze` 또는 `uv lock`으로 lockfile 생성, 상한 버전 추가

### 4. 데이터베이스 — OK

- SQLite (로컬) + PostgreSQL (프로덕션) 모두 지원
- 커넥션 풀링 설정 완료 (pool_size=5, max_overflow=10)
- Alembic 마이그레이션 없음 — `create_all` 사용
- **참고**: 루트에 빈 `JiminRegScandataregscan.db` 파일 존재

### 5. 에러 핸들링 — MEDIUM

- 17건의 `except Exception:` 블록에서 로깅 없이 예외 무시
  - `batch/pipeline.py`, `map/global_status.py`, `parse/ema_parser.py`
  - `stream/therapeutic.py` (3건), `stream/innovation.py`
  - `report/llm_generator.py` (4건), `ingest/hira.py` (2건)
  - `storage/gcs.py` (2건), `scan/domestic.py`, `ingest/mohw.py`
- 파이프라인 최상위 에러 핸들링은 양호

### 6. Rate Limiting — OK

- FDA/EMA: HTTP 429 지수 백오프 재시도 (최대 3회)
- MFDS/CRIS: 요청간 100~200ms 딜레이
- **갭**: CT.gov 클라이언트에 429 핸들링 없음

### 7. 로깅 — MEDIUM

- 모든 모듈에서 `logging.getLogger(__name__)` 사용 — 일관성 OK
- `LOG_LEVEL` 환경변수로 레벨 조정 가능
- **누락**: 구조화된 로깅(JSON) 없음 — Cloud Run/Cloud Logging에서 비효율적
- **누락**: 일부 예외 핸들러에서 로그 출력 없음

### 8. 테스트 — OK

- `tests/` 디렉토리에 12개 테스트 파일
- `scripts/test_*.py`에 14개 통합 테스트
- pytest asyncio_mode = "auto" 설정
- **누락**: 테스트 커버리지 리포팅 없음

### 9. CI/CD — MISSING

- `.github/` 디렉토리 없음
- `cloudbuild.yaml` 없음
- **어떤 자동화도 없음**: 푸시 시 테스트/린트/빌드/배포 없음
- **조치**: GitHub Actions (ruff + pytest) + Cloud Build 배포 파이프라인 구축

### 10. 보안 — CRITICAL

| 이슈 | 심각도 | 상세 |
|------|--------|------|
| `.env`에 실제 API 키 | CRITICAL | `.gitignore`에 있으나 로테이션 필요 |
| `.dockerignore` 없음 | HIGH | Docker 이미지에 `.env` 포함됨 |
| `*.db` gitignore 미포함 | MEDIUM | SQLite 파일이 커밋될 수 있음 |
| CORS `allow_origins=["*"]` | MEDIUM | 프로덕션에서 특정 도메인으로 제한 필요 |
| DB 마이그레이션 없음 | MEDIUM | `create_all` → Alembic 전환 권장 |

---

## 배포 전 필수 3개 조치

1. **`.dockerignore` 생성** — `.env`, `.git/`, `.venv/`, `data/`, `tests/`, `*.db` 제외
2. **API 키 로테이션** — 모든 키 재발급 후 GCP Secret Manager로 이전
3. **CI/CD 구축** — GitHub Actions (ruff + pytest) + Cloud Run 배포 자동화
