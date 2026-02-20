# RegScan v3 System Architecture

> 마지막 업데이트: 2026-02-19

---

## 1. 디렉토리 구조

```
/RegScan/
├── .env / .env.example         — 환경변수 (API 키, DB URL 등)
├── pyproject.toml              — Python 프로젝트 설정 (hatchling)
├── docker-compose.yml          — Docker Compose (app + web + PostgreSQL)
├── Dockerfile / Dockerfile.web — 배치/웹 컨테이너
├── regscan/                    — 메인 Python 패키지
│   ├── ai/                     — v2 AI 파이프라인 (Gemini, reasoning, writing)
│   ├── api/                    — FastAPI 웹 서버
│   ├── batch/                  — Cloud Run Jobs 진입점
│   ├── config/                 — Pydantic Settings 설정
│   ├── db/                     — 데이터베이스 레이어 (ORM, 로더, 리포지토리)
│   ├── ingest/                 — API 클라이언트 (데이터 수집)
│   ├── map/                    — 데이터 매핑/변환 (GlobalStatus, Matcher, Scorer)
│   ├── parse/                  — 원시 데이터 파서
│   ├── report/                 — LLM 브리핑 생성기
│   ├── scan/                   — 분석 레이어 (DomesticImpact)
│   ├── scripts/                — 패키지 내 스크립트 (publish_articles 등)
│   ├── storage/                — GCS 아카이브
│   └── stream/                 — v3 3-Stream 아키텍처
├── scripts/                    — 독립 스크립트
├── data/                       — 정적/참조 데이터 + 수집 JSON
├── output/                     — 파이프라인 산출물
└── tests/                      — pytest 테스트
```

---

## 2. 파이프라인 흐름 (v3 3-Stream)

### 진입점

```bash
python -m regscan.batch.pipeline              # 전체 3-stream
python -m regscan.batch.pipeline --stream therapeutic --area oncology
python -m regscan.batch.pipeline --legacy     # 레거시 DailyScanner
```

### 단계별 흐름 (`run_stream_pipeline`)

```
Step 1:   DB 초기화 (init_db → 테이블 생성)
Step 1.5: PDUFA 시드 자동 주입 (테이블 비어있으면)

Step 2:   StreamOrchestrator.run_all()
          ├── Stream 1: TherapeuticAreaStream (5개 치료영역 병렬)
          │     ├── FDA pharm_class_epc 검색 (영역별 키워드)
          │     ├── EMA therapeutic_area JSON 필터
          │     ├── FDA 교차참조 보강 (EMA-only 약물)
          │     ├── MFDS 보강 (선택, ENABLE_MFDS_ENRICHMENT)
          │     └── ATC 그룹핑 → StreamResult[]
          │
          ├── Stream 2: InnovationStream (단일 결과)
          │     ├── FDA NME (TYPE 1)
          │     ├── FDA Accelerated/Priority (TYPE 4/5)
          │     ├── EMA PRIME / Orphan / Conditional
          │     ├── PDUFA 일정 (DB 조회)
          │     ├── FDA Safety (Boxed Warning + Recall)
          │     └── FDA AdCom → StreamResult
          │
          └── Stream 3: ExternalSignalStream (Stream 1/2의 INN 목록 주입)
                ├── CT.gov Phase 3 → TrialTriageEngine (FAIL/PENDING/NEEDS_AI)
                ├── medRxiv compound keyword 수집
                └── Stream 1/2 INN과 교차참조 → StreamResult

Step 3:   merge_results()       → 병합 약물 리스트 (INN 중복 제거)
          build_global_statuses() → GlobalRegulatoryStatus[]
          (HotIssueScorer: 0~100점 산출, CT.gov 시그널 부스트)

Step 4:   DomesticImpactAnalyzer.analyze_batch(global_statuses)
          → DomesticImpact[] (HIRA + CRIS 보강 + KoreaRelevanceScorer)
          DBLoader.upsert_impacts(qualified) — score >= MIN_SCORE_FOR_DB(10)만 저장

Step 4.5: StreamSnapshot DB 저장

Step 5:   StreamBriefingGenerator (LLM via OpenAI/Anthropic)
          ├── 스트림별 브리핑 (therapeutic/innovation/external)
          └── 통합 일일 브리핑 → StreamBriefingDB

Step 6:   stream_results/<date>_<run_id>.json 저장
```

---

## 3. 데이터 소스 — API 클라이언트

| 클라이언트 | 파일 | 엔드포인트 | 인증 |
|-----------|------|----------|------|
| FDAClient | `ingest/fda.py` | `https://api.fda.gov` drugsfda.json | FDA_API_KEY (선택) |
| FDASafetyClient | `ingest/fda_safety.py` | FDA labels (Boxed Warning) + Enforcement | 없음 |
| FDAAdComClient | `ingest/fda_adcom.py` | `data/fda/adcom_meetings.json` 시드 | 없음 |
| EMAClient | `ingest/ema.py` | EMA Public Assessment Reports JSON | 없음 |
| MFDSClient | `ingest/mfds.py` | 공공데이터포털 의약품허가 API | DATA_GO_KR_API_KEY |
| HIRAClient | `ingest/hira.py` | HIRA 홈페이지 (Playwright 스크래핑) | 없음 |
| CRISClient | `ingest/cris.py` | 공공데이터포털 임상연구정보 API | DATA_GO_KR_API_KEY |
| ClinicalTrialsGovIngestor | `ingest/clinicaltrials.py` | CT.gov v2 API | 없음 |
| BioRxivClient | `ingest/biorxiv.py` | bioRxiv/medRxiv API | 없음 |
| ASTIClient | `ingest/asti.py` | ASTI/KISTI 시장보고서 | 없음 |
| HealthKrClient | `ingest/healthkr.py` | Health.kr 전문가 의견 | 없음 |
| MOHWClient | `ingest/mohw.py` | 보건복지부 입법예고 | 없음 |

---

## 4. 데이터베이스 스키마 (13 테이블)

### v1 핵심 테이블

| 테이블 | 클래스 | 주요 컬럼 |
|--------|--------|----------|
| `drugs` | `DrugDB` | inn(unique), global_score, korea_relevance_score, hot_issue_level, therapeutic_areas, stream_sources(JSON) |
| `regulatory_events` | `RegulatoryEventDB` | drug_id(FK), agency(fda/ema/mfds), status, approval_date, application_number, is_orphan/breakthrough/accelerated/priority/prime/conditional, raw_data(JSON), source_url |
| `hira_reimbursements` | `HIRAReimbursementDB` | drug_id(FK), status, ingredient_code, price_ceiling, criteria |
| `clinical_trials` | `ClinicalTrialDB` | drug_id(FK), trial_id(CRIS), phase, status, indication |
| `briefing_reports` | `BriefingReportDB` | drug_id(FK), headline, subtitle, key_points(JSON), global/domestic/medclaim_section |
| `scan_snapshots` | `ScanSnapshotDB` | source_type, scan_date, record_count |
| `drug_change_log` | `DrugChangeLogDB` | drug_id(FK), change_type, field_name, old/new_value, pipeline_run_id(UUID) |

### v2 AI 테이블

| 테이블 | 클래스 | 주요 컬럼 |
|--------|--------|----------|
| `preprints` | `PreprintDB` | doi(unique), server(biorxiv/medrxiv), gemini_parsed, extracted_facts(JSON) |
| `market_reports` | `MarketReportDB` | source(ASTI/KISTI), market_size_krw, growth_rate |
| `expert_opinions` | `ExpertOpinionDB` | source(KPIC/약사저널), author, summary |
| `ai_insights` | `AIInsightDB` | impact_score, risk/opportunity_factors(JSON), reasoning_chain, reasoning_model(o4-mini) |
| `articles` | `ArticleDB` | article_type, headline, body_html, writer_model(gpt-5.2) |

### v3 Stream 테이블

| 테이블 | 클래스 | 주요 컬럼 |
|--------|--------|----------|
| `stream_snapshots` | `StreamSnapshotDB` | stream_name, drug_count, signal_count, inn_list(JSON) |
| `drug_competitors` | `DrugCompetitorDB` | competitor_inn, relationship_type, atc_code |
| `pdufa_dates` | `PdufaDateDB` | inn, pdufa_date, indication, status(pending/approved/crl) |
| `clinical_trials_gov` | `ClinicalTrialGovDB` | nct_id(unique), phase, verdict(FAIL/PENDING/SUCCESS), verdict_summary |
| `stream_briefings` | `StreamBriefingDB` | stream_name, briefing_type(stream/unified), content_json(JSON) |

---

## 5. 핫이슈 스코어링 (HotIssueScorer)

| 시그널 | 점수 |
|--------|------|
| FDA 승인 | +10 |
| FDA Breakthrough | +15 |
| FDA Accelerated | +10 |
| EMA 승인 | +10 |
| EMA PRIME | +15 |
| EMA Conditional | +5 |
| MFDS 승인 | +5 |
| MFDS 희귀의약품 | +10 |
| 다기관 승인 (3+) | +10 |
| 다기관 승인 (4+) | +10 추가 |
| FDA+EMA 동시 승인 (1년 이내) | +10 |
| 희귀의약품 지정 | +15 |
| WHO EML | +10 |
| 주요 질환 적응증 | +10 |
| 최대 | 100 |

핫이슈 등급: **HOT**(80+) / **HIGH**(60-79) / **MID**(40-59) / **LOW**(<40)

---

## 6. 핵심 데이터 클래스

### GlobalRegulatoryStatus (`map/global_status.py`)
- `inn`, `normalized_name`, `atc_code`
- `fda/ema/pmda/mfds`: `RegulatoryApproval` (agency, status, approval_date, designations, source_url, raw_data)
- `global_score` (0-100), `hot_issue_level`, `hot_issue_reasons`
- `therapeutic_areas`, `stream_sources`
- `clinical_results` (CT.gov resultsSection), `clinical_results_nct_id`

### DomesticImpact (`scan/domestic.py`)
- `inn`, `domestic_status` (reimbursed/approved_not_reimbursed/imminent/expected/uncertain 등)
- FDA/EMA/MFDS 승인 여부 + 날짜
- HIRA 상태/코드/기준/가격
- CRIS 임상시험 목록
- `global_score`, `korea_relevance_score` (0-100)
- `clinical_results`, `clinical_results_nct_id`
- 계산 속성: `quadrant` (top_priority/watch/track/normal), `days_since_global_approval`

### BriefingReport (`report/llm_generator.py`)
- `headline`, `subtitle`, `key_points[]`
- `global_section`, `domestic_section`, `medclaim_section`
- `source_data`

---

## 7. FastAPI API 레이어

**Base URL:** `/api/v1`

| 라우터 | 엔드포인트 | 설명 |
|--------|----------|------|
| `stats.py` | `GET /stats`, `GET /hot-issues` | 통계, 핫이슈 목록 |
| `drugs.py` | `GET /drugs`, `GET /drugs/search?q=`, `GET /drugs/{inn}` | 약물 목록/검색/상세 |
| `changes.py` | `GET /changes` | 변경 이력 피드 |
| `briefings.py` | `GET /briefings` | 스트림 브리핑 |
| `pdufa.py` | `GET /pdufa` | PDUFA 일정 |
| `dashboard.py` | `GET /` | Jinja2 HTML 대시보드 |
| `scheduler.py` | `GET /scheduler` | 스케줄러 제어 |

---

## 8. 설정 (`config/settings.py`)

| 설정 | 기본값 | 용도 |
|------|--------|------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/regscan.db` | 비동기 DB |
| `MIN_SCORE_FOR_DB` | 10 | DB 저장 최소 점수 |
| `MIN_SCORE_FOR_BRIEFING` | 40 | LLM 브리핑 최소 점수 |
| `THERAPEUTIC_AREAS` | `oncology,rare_disease,immunology,cardiovascular,metabolic` | Stream 1 치료영역 |
| `CT_GOV_MONTHS_BACK` | 6 | CT.gov 검색 기간 |
| `MEDRXIV_DAYS_BACK` | 30 | medRxiv 검색 기간 |
| `ENABLE_STREAM_*` | True | 스트림별 on/off |
| `ENABLE_FDA_SAFETY/ADCOM` | True | FDA Safety/AdCom on/off |
| `USE_LLM` | True | LLM 브리핑 활성화 |
| `SCHEDULER_ENABLED` | True | APScheduler 일일 실행 |
| `DAILY_SCAN_HOUR` | 8 | 매일 08:00 KST |

---

## 9. 산출물

| 경로 | 내용 |
|------|------|
| `output/briefings/<INN>.json/html/md` | 약물별 LLM 브리핑 |
| `output/briefings/index.html` | 브리핑 인덱스 |
| `output/briefings/hot_issues_<date>.json/md` | 핫이슈 랭킹 |
| `output/stream_results/stream_<date>_<run_id>.json` | 파이프라인 실행 결과 |
| `output/daily_scan/` | 레거시 일일 스캔 결과 |
| `output/reports/` | 글로벌 인텔리전스 리포트 |
| `data/regscan.db` | SQLite DB (로컬 개발) |

---

## 10. 외부 의존성

| 패키지 | 용도 |
|--------|------|
| `httpx` | 비동기 HTTP 클라이언트 (모든 API) |
| `sqlalchemy` + `aiosqlite` / `asyncpg` | ORM (SQLite/PostgreSQL) |
| `fastapi` + `uvicorn` | REST API |
| `pydantic` + `pydantic-settings` | 데이터 검증, .env 로딩 |
| `apscheduler` | 일일 스케줄러 |
| `jinja2` | HTML 템플릿 |
| `beautifulsoup4` + `lxml` | HTML 파싱 (HIRA) |
| `pandas` | DataFrame (bridge/CSV) |
| `openai` | GPT-5.2 (writer/verifier), o4-mini (reasoning) |
| `anthropic` | Claude API 대체 |
| `playwright` | HIRA Playwright 스크래퍼 |
| `google-cloud-storage` | GCS 아카이브 |
| `google-generativeai` | Gemini 2.0 Flash 파싱 |
