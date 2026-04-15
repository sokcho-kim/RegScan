# RegScan

**Scanning Global Regulation into Local Impact**

글로벌 의약품 규제 인텔리전스 엔진 — FDA/EMA 승인 약물의 국내 허가·급여 상태를 자동 추적하고, 병원 약제팀용 Executive Briefing을 생성합니다.

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Data Collection (Daily)                                │
│  FDA · EMA · MFDS · CRIS · KDCA · KHIDI                │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│  IngredientBridge + Decomposer v1.0.0                   │
│  MFDS→HIRA 성분 매칭 (88.0%) + 무손실 분해              │
│  SALT_FORMS 114개 · FORMULATION_TOKENS 36개 (RxNorm 검증)│
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│  HIRA Enrichment                                        │
│  급여 등재 · 비급여 · 급여 삭제 · 확인 자료 없음          │
│  상한가 + 용량규격 (0.1g/4mL) · 산정특례 · 접근경로       │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│  Briefing Generator (LLM)                               │
│  3-Stream: Therapeutic · Innovation · External           │
│  Few-shot HIRA 3패턴 + 네거티브 예시 + CoT 시간추론      │
│  GPT-5.2 → Gemini 2.5 Flash → Claude Sonnet (fallback)  │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│  Dashboard + API                                        │
│  FastAPI · Jinja2 · Executive Briefing 대시보드           │
└─────────────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
RegScan/
├── regscan/
│   ├── api/                    # FastAPI + 대시보드
│   │   ├── routes/             # dashboard, drugs, stats
│   │   └── templates/          # Jinja2 (base, dashboard, briefing)
│   ├── parse/                  # 데이터 파서 (FDA, EMA, MFDS, CRIS)
│   ├── ingest/                 # 크롤러 (KDCA, KHIDI)
│   ├── map/                    # 매핑 엔진
│   │   ├── decomposer.py       # 무손실 분해 v1.0.0 (Base INN/Salt/Formulation/Strength)
│   │   ├── ingredient_bridge.py # MFDS↔HIRA 2-Pass Lookup
│   │   ├── assets_loader.py    # JSON 사전 로더 (frozenset 캐싱)
│   │   └── assets/             # salt_forms.json, formulation_tokens.json, ref_normalization_map.json
│   ├── stream/                 # 3-Stream 브리핑 파이프라인
│   │   ├── briefing.py         # StreamBriefingGenerator + HIRA Enrichment
│   │   └── base.py             # StreamResult 데이터클래스
│   ├── prompts/                # LLM 프롬프트 (shared.py 기반)
│   ├── monitor/                # DailyScanner (일일 스캔)
│   ├── workers/                # 공공데이터 수집 워커 (DrugPrice, MFDS, HIRA)
│   ├── batch/                  # Cloud Run Jobs 진입점 (pipeline.py)
│   ├── db/                     # SQLAlchemy ORM + async 엔진
│   └── config/                 # Pydantic Settings
├── data/
│   ├── fda/                    # FDA 승인 데이터
│   ├── ema/                    # EMA 승인 데이터
│   ├── mfds/                   # MFDS 허가 데이터 (44K+ 품목)
│   ├── hira/                   # HIRA 약가 데이터 (59K+ 제품)
│   └── bridge/                 # 마스터 CSV + ATC 매핑
├── tests/
│   ├── test_decomposer.py      # 39개 단위 테스트
│   ├── test_decomposer_snapshot.py  # 6,414건 전수 스냅샷
│   └── fixtures/               # 골든 데이터
├── scripts/
│   ├── validate_decomposer_vocab.py  # OMOP RxNorm 교차 검증
│   └── test_briefing_quality.py      # 브리핑 품질 테스트 (버전별 저장)
├── docs/
│   ├── worklog/                # 작업일지 (2026-01~)
│   └── unmatched_ingredient_report.md  # 미매칭 768건 분류
├── output/
│   ├── briefings/snapshots/    # 브리핑 버전별 스냅샷 (프롬프트+입력+결과+메타)
│   └── daily_scan/             # 일일 스캔 결과
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
- 사전은 `regscan/map/assets/*.json`으로 분리, 코드 수정 없이 갱신 가능
- 스냅샷 테스트로 regression 자동 감지

### IngredientBridge (2-Pass Lookup)

```
Pass 1: variant_key (Base+Salt+Formulation) → 마스터 완전 일치
Pass 2: base_key (Base INN) → fallback 매칭
```

매칭률: **88.0%** (6,414건 중 5,646건)

### HIRA Enrichment

브리핑 생성 시 약물별 HIRA 급여 데이터 자동 주입:

| 상태 | 출력 예시 |
|------|----------|
| 급여 등재 | `HIRA 급여 등재, 상한가 2,103,620원 (0.1g/4mL)` |
| 비급여 | `HIRA 비급여 (전액 환자부담)` |
| 급여 삭제 | `HIRA 급여 삭제 (과거 등재 이력)` |
| 확인 자료 없음 | `HIRA 확인 자료 없음` |

## 실행

```bash
# 로컬 개발 서버
uvicorn regscan.api.main:app --host 0.0.0.0 --port 8001 --reload

# 일일 스캔
python -m regscan.batch.pipeline

# 브리핑 품질 테스트
python scripts/test_briefing_quality.py --version v5.x --area oncology --area-ko 항암

# Decomposer 테스트
pytest tests/test_decomposer.py tests/test_decomposer_snapshot.py -v

# OMOP 사전 검증
python scripts/validate_decomposer_vocab.py
```

## Docker

```bash
# 로컬 (PostgreSQL + web + batch)
docker-compose up

# 배치 단독
docker-compose --profile batch run batch

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

*LLM 키 최소 1개 필수

## 브리핑 버전 관리

```
output/briefings/snapshots/
├── v5.0_hira_fewshot/          # HIRA few-shot 첫 적용
├── v5.1_real_pipeline/         # 실제 파이프라인 데이터
├── v5.2_auto_top5/             # hot_issue_score 자동 선별
└── v5.x_next/
    ├── _meta.json              # 변경사항, 약물, 모델
    ├── *_prompts.txt           # system + user prompt 원문
    ├── *_input.json            # HIRA 주입 후 약물 데이터
    └── *_therapeutic.json      # LLM 출력 결과
```

## 사전 갱신 주기

| 대상 | 주기 | 시점 |
|------|------|------|
| HIRA 마스터 | 연 1회 | 10월 |
| `assets/*.json` 재검증 | 연 1회 | HIRA 갱신 후 |
| `validate_decomposer_vocab.py` 실행 | 연 1회 | OMOP RxNorm 갱신 시 |
