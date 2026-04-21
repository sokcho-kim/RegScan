# RegScan

**Scanning Global Regulation into Local Impact**

글로벌 의약품 규제 인텔리전스 엔진 — FDA/EMA/MFDS/PMDA 승인, 특허 만료, HTA 결정, 국내 급여 정책, 국회 법안까지 **22개 소스**를 자동 추적하고, 병원 약제팀용 Executive Briefing을 생성합니다.

## 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│  Data Collection (22 Sources, Daily)                         │
│                                                              │
│  글로벌 규제 (6)       국내 규제 (7)        보조 정보 (9)    │
│  ────────────         ────────────        ──────────         │
│  FDA openFDA          MFDS 허가            KHIDI             │
│  FDA Orange Book      MFDS 안전성 서한     KDCA              │
│  FDA Purple Book      HIRA 약가/급여       ASTI              │
│  EMA 의약품           MOHW 입법예고        Health.kr          │
│  PMDA 승인심사        MOHW 건강보험정책    bioRxiv            │
│  PMDA 안전성          국회 보건 법안       News RSS (3)       │
│                       CRIS 임상시험                           │
│  해외 HTA (1)                                                │
│  ────────────                                                │
│  NICE TA (영국)                                              │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  IngredientBridge + Decomposer v1.0.0                        │
│  MFDS→HIRA 성분 매칭 (88.0%) + 무손실 분해                   │
│  SALT_FORMS 114개 · FORMULATION_TOKENS 36개 (RxNorm 검증)     │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  HIRA Enrichment                                             │
│  급여 등재 · 비급여 · 급여 삭제 · 확인 자료 없음              │
│  상한가 + 용량규격 (0.1g/4mL) · 산정특례 · 접근경로           │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Briefing Generator (LLM)                                    │
│  3-Stream: Therapeutic · Innovation · External                │
│  Few-shot HIRA 3패턴 + 네거티브 예시 + CoT 시간추론           │
│  GPT-5.2 → Gemini 2.5 Flash → Claude Sonnet (fallback)       │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Dashboard + API                                             │
│  FastAPI · Jinja2 · Executive Briefing 대시보드               │
└──────────────────────────────────────────────────────────────┘
```

## 배치 파이프라인

```
python -m regscan.batch.pipeline        # v3 Stream (기본)
python -m regscan.batch.pipeline --legacy  # Legacy v2

v3 Stream Pipeline:
  [1]   DB 초기화 + PDUFA 시드
  [1.7] 레거시 워커 (HIRA/MFDS/급여, 선택)
  [2]   3-Stream 오케스트레이터 (therapeutic · innovation · external)
  [3]   결과 병합 + GlobalRegulatoryStatus
  [4]   DB 적재 (score 필터)
  [4.7] KHIDI/KDCA 보도자료
  [4.8] 보조 인텔리전스 수집 ─────────────────────────────
        │ PMDA 승인심사 + 안전성   (일본 RSS + HTML)
        │ NICE HTA 권고            (영국 Excel 벌크)
        │ MFDS 안전성 서한         (nedrug.mfds.go.kr 크롤링)
        │ MOHW 건강보험정책        (보도자료 키워드 필터)
        │ 국회 보건 법안           (열린국회정보 API)
        └─────────────────────────────────────────────────
  [5]   스트림 브리핑 생성 (LLM)
  [6]   결과 JSON 저장
```

## 데이터 수집 소스 (22개)

### 글로벌 규제

| 소스 | 방식 | 수집 데이터 | 토글 |
|------|------|-----------|------|
| FDA (openFDA) | REST API | 승인, NDA/BLA, Breakthrough, PDUFA, Safety, AdCom | - |
| FDA Orange Book | CSV 다운로드 | 특허 만료일, 독점권, 치료적 동등성 | `ENABLE_FDA_ORANGE_BOOK` |
| FDA Purple Book | CSV 다운로드 | BLA 생물의약품 독점권, 바이오시밀러 | `ENABLE_FDA_PURPLE_BOOK` |
| EMA | REST API | 허가 의약품, 오펀, 부족, 안전성(DHPC/referral) | - |
| PMDA (일본) | RSS + HTML | 승인심사, 안전성 보고서 (72+건) | `ENABLE_PMDA` |

### 해외 HTA

| 소스 | 방식 | 수집 데이터 | 토글 |
|------|------|-----------|------|
| NICE (영국) | Excel 벌크 | Technology Appraisal 권고 (1,486+건) | `ENABLE_NICE_HTA` |

### 국내 규제

| 소스 | 방식 | 수집 데이터 | 토글 |
|------|------|-----------|------|
| MFDS (식약처) | 공공데이터 API | 284K+ 허가 품목 | - |
| MFDS 안전성 서한 | httpx+bs4 크롤링 | nedrug.mfds.go.kr 안전성 서한/속보 | `ENABLE_MFDS_SAFETY` |
| HIRA (심평원) | Playwright + Excel | 심사기준, 약가(상한가), 급여 상태 | - |
| MOHW 입법예고 | Playwright | 입법/행정예고 | - |
| MOHW 건강보험정책 | httpx+bs4 | 건보심 의결, 급여 결정, 약가 정책 | `ENABLE_MOHW_INSURANCE` |
| 국회 의안정보 | REST API | 약사법, 건강보험법 등 보건의료 법안 | `ENABLE_ASSEMBLY_BILL` |
| CRIS (임상시험) | 공공데이터 API | 국내 임상시험 11.5K+ | - |

### 산업/학술/뉴스

| 소스 | 방식 | 수집 데이터 |
|------|------|-----------|
| KHIDI (보건산업진흥원) | Web API | 바이오헬스 산업 브리프 |
| KDCA (질병관리청) | Playwright | 보도자료, 백신/질병 정책 |
| ASTI | Playwright | 바이오/제약 시장 조사 |
| Health.kr (약학정보원) | Playwright | 전문가 리뷰, KPIC |
| bioRxiv/medRxiv | REST API | 약물 관련 프리프린트 |
| Endpoints/FiercePharma/FierceBiotech | RSS | 글로벌 제약 뉴스 |

## 프로젝트 구조

```
RegScan/
├── regscan/
│   ├── api/                    # FastAPI + 대시보드
│   │   ├── routes/             # dashboard, drugs, stats
│   │   └── templates/          # Jinja2 (base, dashboard, briefing)
│   ├── ingest/                 # 수집기 22개
│   │   ├── base.py             # BaseIngestor (async context manager)
│   │   ├── fda.py              # FDA openFDA
│   │   ├── ema.py              # EMA 의약품
│   │   ├── mfds.py             # MFDS 허가
│   │   ├── mfds_safety.py      # MFDS 안전성 서한 + 회수 API
│   │   ├── orange_book.py      # FDA Orange Book (특허)
│   │   ├── purple_book.py      # FDA Purple Book (BLA)
│   │   ├── nice.py             # NICE HTA (영국)
│   │   ├── pmda.py             # PMDA (일본)
│   │   ├── mohw.py             # MOHW 입법예고 (Playwright)
│   │   ├── mohw_insurance.py   # MOHW 건강보험정책
│   │   ├── assembly.py         # 국회 의안정보
│   │   ├── hira.py             # HIRA 약가/급여 (Playwright)
│   │   ├── cris.py             # CRIS 임상시험
│   │   ├── biorxiv.py          # bioRxiv/medRxiv
│   │   ├── khidi.py            # KHIDI
│   │   ├── kdca.py             # KDCA
│   │   ├── asti.py             # ASTI
│   │   └── healthkr.py         # Health.kr
│   ├── parse/                  # 데이터 파서 (FDA, EMA, MFDS, CRIS)
│   ├── map/                    # 매핑 엔진
│   │   ├── decomposer.py       # 무손실 분해 v1.0.0
│   │   ├── ingredient_bridge.py # MFDS↔HIRA 2-Pass Lookup
│   │   └── assets/             # salt_forms.json, formulation_tokens.json
│   ├── stream/                 # 3-Stream 브리핑 파이프라인
│   ├── prompts/                # LLM 프롬프트
│   ├── monitor/                # DailyScanner (일일 스캔)
│   ├── workers/                # 공공데이터 수집 워커
│   ├── batch/                  # Cloud Run Jobs 진입점 (pipeline.py)
│   ├── db/                     # SQLAlchemy ORM + async 엔진
│   └── config/                 # Pydantic Settings
├── data/                       # FDA/EMA/MFDS/HIRA/bridge 데이터
├── docs/
│   ├── plan/                   # 백로그, 로드맵
│   ├── worklog/                # 작업일지
│   ├── commit-log/             # 커밋 이력
│   └── research/               # 조사/분석 문서
├── tests/                      # Decomposer 단위/스냅샷 테스트
├── scripts/                    # 검증/유틸리티 스크립트
├── output/                     # 브리핑 스냅샷, 스캔 결과
├── Dockerfile                  # 배치용 (Cloud Run Jobs)
├── Dockerfile.web              # 웹서버용 (Cloud Run Service)
└── docker-compose.yml          # 로컬 개발 (PostgreSQL + web + batch)
```

## 핵심 모듈

### Decomposer v1.0.0 (Logic Frozen)

성분명 무손실 분해 — 원본 텍스트를 4개 컬럼으로 쪼개되 정보를 버리지 않음.

```
"Ascorbic Acid Coated Granules 97%"
  → base_inn: "ascorbic acid"
  → salt: None
  → formulation: "coated granules"
  → strength: "97%"
```

- SALT_FORMS 114개 + REF_NORMALIZATION_MAP 23개 (OMOP RxNorm 교차 검증 완료)
- FORMULATION_TOKENS 36개 (MFDS 실데이터 + RxNorm 검증)
- 스냅샷 테스트로 regression 자동 감지

### IngredientBridge (2-Pass Lookup)

```
Pass 1: variant_key (Base+Salt+Formulation) → 마스터 완전 일치
Pass 2: base_key (Base INN) → fallback 매칭
```

매칭률: **88.0%** (6,414건 중 5,646건)

### 수집기 공통 패턴

```python
# 모든 수집기는 BaseIngestor를 상속, async context manager
async with PMDAReviewIngestor(days_back=90) as ingestor:
    results = await ingestor.fetch()

# 파이프라인에서는 settings 토글로 개별 ON/OFF
# 실패해도 다른 수집기에 영향 없음 (try/except + graceful skip)
```

## 실행

```bash
# 로컬 개발 서버
uvicorn regscan.api.main:app --host 0.0.0.0 --port 8001 --reload

# v3 파이프라인 (3-Stream, 기본)
python -m regscan.batch.pipeline

# 특정 스트림만
python -m regscan.batch.pipeline --stream therapeutic --area oncology

# 레거시 모드
python -m regscan.batch.pipeline --legacy --days-back 7

# HIRA 약가 갱신
python -m regscan.workers.drug_price_collector

# 브리핑 품질 테스트
python scripts/test_briefing_quality.py --version v5.x --area oncology --area-ko 항암

# Decomposer 테스트
pytest tests/test_decomposer.py tests/test_decomposer_snapshot.py -v
```

## Docker

```bash
# DEV
docker-compose up

# PROD
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Cloud Run 배포
gcloud run jobs deploy regscan-batch --source . --dockerfile Dockerfile
gcloud run deploy regscan-web --source . --dockerfile Dockerfile.web
```

## 환경 변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `DATABASE_URL` | O | SQLite(로컬) or PostgreSQL(Cloud) |
| `OPENAI_API_KEY` | O* | GPT-5.2 브리핑 생성 |
| `GEMINI_API_KEY` | O* | Gemini 2.5 Flash fallback |
| `ANTHROPIC_API_KEY` | - | Claude Sonnet fallback |
| `FDA_API_KEY` | - | FDA openFDA (없으면 rate limit) |
| `DATA_GO_KR_API_KEY` | - | 공공데이터포털 (MFDS, CRIS) |
| `OPEN_ASSEMBLY_API_KEY` | - | 열린국회정보 API (국회 법안) |

*LLM 키 최소 1개 필수

## 데이터 갱신 주기

| 대상 | 주기 | 방법 |
|------|------|------|
| FDA/EMA/MFDS 스캔 | 일일 | `python -m regscan.batch.pipeline` (자동) |
| 보조 인텔리전스 (PMDA/NICE/법안 등) | 일일 | 파이프라인 Step 4.8 (자동) |
| HIRA 약가 Excel | 월간 | `python -m regscan.workers.drug_price_collector` (자동) |
| HIRA 마스터 CSV | 연 1회 (10월) | 수동 교체 |
| `assets/*.json` 재검증 | 연 1회 | `python scripts/validate_decomposer_vocab.py` |

## 운영 비용

| 항목 | GPT-5.2 | Gemini 2.5 Flash |
|------|---------|-----------------|
| 단건 브리핑 | 34원 | 3원 |
| LLM 월 (일 4건 × 30일) | 4,092원 | 307원 |
| 인프라 (Cloud Run + Cloud SQL) | 42,000원 | 42,000원 |
| **월 합계** | **~46,000원** | **~42,000원** |
