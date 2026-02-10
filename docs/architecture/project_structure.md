# RegScan 프로젝트 구조 가이드

> **Scanning Global Regulation into Local Impact**
>
> 글로벌 의약품 규제 인텔리전스 시스템 -- FDA/EMA 승인 약물의 국내 시장 영향 분석 및 메드클레임 시사점 제공

---

## 1. 프로젝트 구조 맵

```
RegScan/
├── pyproject.toml              # 프로젝트 메타/의존성 (hatchling 빌드)
├── README.md                   # 프로젝트 소개 및 실행법
│
├── regscan/                    # 메인 패키지
│   ├── __init__.py
│   ├── scheduler.py            # APScheduler 기반 일간 파이프라인 스케줄러
│   │
│   ├── config/                 # 설정
│   │   ├── __init__.py         # settings 싱글톤 re-export
│   │   └── settings.py         # pydantic-settings 기반 환경변수/설정값
│   │
│   ├── ingest/                 # 데이터 수집 (API 클라이언트)
│   │   ├── __init__.py
│   │   ├── base.py             # BaseIngestor ABC (httpx async context manager)
│   │   ├── fda.py              # FDA openFDA API 클라이언트 + 수집기
│   │   ├── ema.py              # EMA JSON Report API 클라이언트 + 수집기
│   │   ├── mfds.py             # MFDS 공공데이터포털 API 클라이언트 + 수집기
│   │   ├── cris.py             # CRIS 임상연구정보서비스 API 클라이언트 + 수집기
│   │   ├── hira.py             # HIRA 보험인정기준/공지사항 Playwright 크롤러
│   │   ├── mohw.py             # 보건복지부 입법/행정예고 Playwright 크롤러
│   │   ├── asti.py             # [v2] ASTI/KISTI 시장 리포트 Playwright 크롤러
│   │   ├── healthkr.py         # [v2] Health.kr 전문가 리뷰 Playwright 크롤러
│   │   └── biorxiv.py          # [v2] bioRxiv/medRxiv REST API 수집기
│   │
│   ├── parse/                  # 데이터 파서 (원본 -> 정규화 dict)
│   │   ├── __init__.py
│   │   ├── fda_parser.py       # FDA Drug 응답 파서 (FDADrugParser)
│   │   ├── ema_parser.py       # EMA 의약품/희귀의약품/공급부족/DHPC 파서
│   │   ├── mfds_parser.py      # MFDS 허가정보 파서 (MFDSPermitParser)
│   │   ├── cris_parser.py      # CRIS 임상시험 파서 (CRISTrialParser)
│   │   ├── hira_parser.py      # HIRA 보험인정기준/공지사항 파서 (HIRAParser)
│   │   ├── asti_parser.py      # [v2] ASTI 시장 리포트 파서 (시장규모/성장률 추출)
│   │   ├── healthkr_parser.py  # [v2] Health.kr 전문가 리뷰 파서
│   │   └── biorxiv_parser.py   # [v2] bioRxiv/medRxiv 프리프린트 파서
│   │
│   ├── map/                    # 매핑 & 통합 로직
│   │   ├── __init__.py
│   │   ├── matcher.py          # 성분명 정규화/유의어 매칭 (IngredientMatcher, DrugMatcher)
│   │   ├── global_status.py    # 글로벌 규제 현황 통합 (GlobalRegulatoryStatus, HotIssueScorer)
│   │   ├── ingredient_bridge.py # MFDS<->HIRA 성분명 브릿지 (75.7% 매칭률)
│   │   ├── atc.py              # WHO ATC 코드 연동 (ATCDatabase, ATCMatcher)
│   │   ├── timeline.py         # 약물 타임라인 빌더 (DrugTimeline)
│   │   └── report.py           # 매핑 결과 리포트 유틸
│   │
│   ├── scan/                   # 분석 엔진
│   │   ├── __init__.py
│   │   ├── domestic.py         # 국내 영향 분석기 (DomesticImpactAnalyzer)
│   │   ├── signal_generator.py # 원본 데이터 -> FeedCard 변환 (SignalGenerator)
│   │   └── why_it_matters.py   # "왜 중요한가" 생성 (LLM + 템플릿 폴백)
│   │
│   ├── monitor/                # 일간 모니터링
│   │   ├── __init__.py
│   │   └── daily_scanner.py    # DailyScanner: FDA/EMA/MFDS 일간 신규승인 체크 & 핫이슈 판정
│   │
│   ├── report/                 # 리포트 생성
│   │   ├── __init__.py         # 모듈 re-export
│   │   ├── generator.py        # ReportGenerator: 일간/주간 리포트 (DB 기반)
│   │   ├── llm_generator.py    # LLMBriefingGenerator: Claude/GPT 기반 브리핑 리포트
│   │   └── prompts.py          # LLM 프롬프트 템플릿 (Few-Shot, CoT)
│   │
│   ├── api/                    # FastAPI REST API
│   │   ├── __init__.py
│   │   ├── main.py             # 앱 진입점 (lifespan, CORS, 라우터 등록)
│   │   ├── deps.py             # DataStore 싱글톤 (데이터 로딩/캐싱/검색)
│   │   ├── schemas.py          # Pydantic 응답 스키마 (DrugDetail, MedclaimInsight 등)
│   │   └── routes/             # API 엔드포인트
│   │       ├── __init__.py
│   │       ├── drugs.py        # 약물 조회/검색/상세/메드클레임/브리핑
│   │       ├── stats.py        # 전체 통계, 핫이슈, 도입임박 약물
│   │       └── scheduler.py    # 스케줄러 상태/수동실행
│   │
│   ├── ai/                     # [v2] AI Intelligence Layer
│   │   ├── __init__.py
│   │   ├── gemini_parser.py    # Gemini PDF 파서 (bioRxiv PDF→구조화 데이터)
│   │   ├── reasoning_engine.py # o4-mini 기반 CoT 추론 엔진
│   │   ├── verifier.py         # GPT-5.2 기반 팩트체크 검증기
│   │   ├── writing_engine.py   # GPT-5.2 기반 기사 작성 엔진
│   │   ├── pipeline.py         # AIIntelligencePipeline 오케스트레이터
│   │   └── prompts/            # AI 프롬프트 모음
│   │       ├── __init__.py
│   │       ├── reasoning_prompt.py  # 4대 스트림 CoT 분석 프롬프트
│   │       ├── verifier_prompt.py   # 팩트체크 검증 프롬프트
│   │       └── writer_prompt.py     # Few-Shot 기사 작성 프롬프트
│   │
│   ├── models/                 # 공통 데이터 모델
│   │   ├── __init__.py
│   │   └── feed_card.py        # FeedCard, SourceType, ChangeType, Domain, ImpactLevel 등
│   │
│   ├── db/                     # 데이터베이스 (SQLAlchemy + aiosqlite)
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy ORM 모델 (v1 6개 + v2 5개 테이블)
│   │   ├── repository.py       # FeedCardRepository (CRUD)
│   │   ├── global_status_repository.py  # GlobalStatusRepository
│   │   ├── snapshot_repository.py       # SnapshotRepository
│   │   └── v2_loader.py        # [v2] V2Loader (preprints/market/expert/insight/article upsert)
│   │
│   ├── scripts/                # 패키지 내장 스크립트 (python -m 실행용)
│   │   ├── __init__.py
│   │   ├── collect_all.py      # 통합 수집 파이프라인 (FDA+HIRA+MOHW)
│   │   ├── collect_fda.py      # FDA 단독 수집
│   │   ├── collect_hira.py     # HIRA 단독 수집
│   │   └── collect_mohw.py     # MOHW 단독 수집
│   │
│   └── utils/                  # 공통 유틸리티
│       └── __init__.py
│
├── scripts/                    # 실행/테스트 스크립트 (프로젝트 루트)
│   ├── run_daily_scan.py       # 일간 스캔 수동 실행
│   ├── generate_daily_html.py  # 일간 HTML 뉴스레터 생성
│   ├── generate_briefing_reports.py  # LLM 브리핑 리포트 생성
│   ├── generate_html_briefings.py    # HTML 브리핑 생성
│   ├── generate_full_report.py       # 전체 리포트 생성
│   ├── generate_full_report_with_fda.py  # FDA 포함 전체 리포트
│   ├── collect_ema.py          # EMA 데이터 수집 (독립 스크립트)
│   ├── collect_mfds_full.py    # MFDS 전체 데이터 수집
│   ├── build_timeline_dataset.py     # 타임라인 데이터셋 구축
│   ├── compare_models.py       # LLM 모델 비교 테스트
│   ├── capture_screenshot.py   # 스크린샷 캡처 유틸
│   ├── scrape_seladelpar_articles.py # 특정 약물 뉴스 스크래핑
│   ├── test_api.py             # API 통합 테스트
│   ├── test_briefing.py        # 브리핑 테스트
│   ├── test_e2e_pipeline.py    # E2E 파이프라인 테스트
│   ├── test_*.py               # 기타 모듈별 테스트 스크립트
│   ├── scraping/               # 뉴스 스크래핑 도구
│   │   ├── yakup_scraper.py    # 약업신문 스크래퍼
│   │   ├── multi_news_scraper.py  # 멀티 뉴스 소스 스크래퍼
│   │   └── analyze_articles.py # 기사 분석 도구
│   └── archive/                # 실험 스크립트 아카이브
│       └── experiment_matching_v*.py  # 성분명 매칭 실험 (v1~v6)
│
├── data/                       # 데이터 파일 (Git 추적 외)
│   ├── fda/                    # FDA 승인 데이터 (approvals_*.json)
│   ├── ema/                    # EMA 승인 데이터 (medicines_*.json)
│   ├── mfds/                   # MFDS 허가 데이터 (permits_*.json, permits_full_*.json)
│   ├── cris/                   # CRIS 임상시험 데이터 (trials_full_*.json)
│   ├── hira/                   # HIRA 급여 데이터 (drug_prices_*.json)
│   ├── bridge/                 # MFDS<->HIRA 브릿지 마스터 파일
│   │   ├── yakga_ingredient_master.csv  # 의약품주성분 마스터
│   │   └── 건강보험심사평가원_ATC코드_매핑_목록_*.csv
│   ├── atc/                    # WHO ATC 코드 캐시
│   └── archive/                # 임시/실험 파일
│
├── output/                     # 생성된 결과물
│   └── daily_scan/             # 일간 스캔 결과 (JSON + HTML)
│
├── tests/                      # pytest 테스트
│   ├── __init__.py
│   ├── test_fda.py             # FDA 수집기 테스트
│   ├── test_hira.py            # HIRA 수집기 테스트
│   ├── test_models.py          # 데이터 모델 테스트
│   ├── test_v2_schema.py       # [v2] v2 테이블 생성·CRUD 테스트 (7개)
│   ├── test_v2_pipeline.py     # [v2] 파서·설정·임포트 테스트 (13개)
│   └── test_ai_pipeline.py     # [v2] AI 3단 파이프라인 단위 테스트 (9개)
│
└── docs/                       # 프로젝트 문서
    ├── architecture/           # 아키텍처 문서
    ├── schema/                 # DB 스키마 문서 (v2_schema.md 포함)
    ├── worklog/                # 작업일지
    ├── research/               # 리서치 리포트
    ├── design/                 # 설계 문서
    └── analysis/               # 초기 분석 자료
```

---

## 2. 데이터 흐름도

### 전체 파이프라인

```
                     ┌─────────────────────────────────────────────┐
                     │            외부 데이터 소스                    │
                     │                                             │
                     │  FDA API    EMA JSON    MFDS API   CRIS API │
                     │  (openFDA)  (Report)    (data.go.kr)        │
                     │                                             │
                     │  HIRA 웹    MOHW 웹                         │
                     │  (Playwright 크롤링)                         │
                     │                                             │
                     │  [v2] ASTI 웹    Health.kr 웹   bioRxiv API │
                     │  (Playwright)    (Playwright)   (REST)      │
                     └────────┬────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   ingest/ (수집)    │  BaseIngestor -> httpx / Playwright
                    │                    │  원본 JSON/HTML 수집
                    └─────────┬──────────┘
                              │
                    ┌─────────▼─────────┐
                    │   parse/ (파싱)     │  FDADrugParser, EMAMedicineParser,
                    │                    │  MFDSPermitParser, CRISTrialParser
                    │                    │  [v2] ASTIReportParser, HealthKRParser,
                    │                    │       BioRxivParser
                    │                    │  -> 정규화된 dict 출력
                    └─────────┬──────────┘
                              │
                    ┌─────────▼─────────┐
                    │   map/ (매핑/통합)   │  IngredientMatcher: 성분명 정규화
                    │                    │  GlobalStatusBuilder: FDA+EMA+MFDS 병합
                    │                    │  IngredientBridge: MFDS<->HIRA 연결
                    │                    │  HotIssueScorer: 핫이슈 스코어링 (0-100)
                    └─────────┬──────────┘
                              │
                    ┌─────────▼─────────┐
                    │   scan/ (분석)      │  DomesticImpactAnalyzer: 국내 영향 분석
                    │                    │  SignalGenerator: FeedCard 생성
                    │                    │  WhyItMattersGenerator: LLM/템플릿
                    └─────────┬──────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼────┐  ┌──────▼──────┐  ┌─────▼──────┐
    │  api/ (서빙)  │  │ monitor/    │  │ report/    │
    │  FastAPI      │  │ DailyScanner│  │ LLM 브리핑  │
    │  REST 엔드포인트│  │ 일간 스캔    │  │ HTML 뉴스레터│
    └──────┬───────┘  └──────┬──────┘  └─────┬──────┘
           │                 │               │
           │          ┌──────▼───────────────▼──────┐
           │          │   output/ (결과 저장)          │
           │          │   daily_scan/*.json           │
           │          │   daily_scan/*.html           │
           │          └────────────────────────────────┘
           │
    ┌──────▼─────────────────────────────────────┐
    │  [v2] ai/ (AI Intelligence Layer)           │
    │                                             │
    │  GeminiParser → PDF 파싱                     │
    │  ReasoningEngine (o4-mini) → CoT 추론        │
    │  InsightVerifier (GPT-5.2) → 팩트체크         │
    │  WritingEngine (GPT-5.2) → 기사 생성          │
    │                                             │
    │  AIIntelligencePipeline 오케스트레이터         │
    └─────────────────────────────────────────────┘
```

### API 서버 시작 시 데이터 흐름

```
uvicorn regscan.api.main:app
    │
    ├── lifespan() 시작
    │   ├── get_data_store() 호출
    │   │   ├── data/ 에서 최신 JSON 파일 자동 탐색
    │   │   ├── FDADrugParser.parse_many()
    │   │   ├── EMAMedicineParser.parse_many()
    │   │   ├── MFDSPermitParser.parse_many()
    │   │   ├── CRISTrialParser.parse_many()
    │   │   ├── merge_global_status() -> GlobalRegulatoryStatus 목록
    │   │   ├── DomesticImpactAnalyzer.analyze_batch() -> DomesticImpact 목록
    │   │   └── DataStore에 캐싱 (메모리 싱글톤)
    │   │
    │   └── start_scheduler() (SCHEDULER_ENABLED=True 시)
    │       └── CronTrigger(hour=8, minute=0) -> run_daily_pipeline()
    │
    └── API 요청 처리
        └── DataStore에서 데이터 조회 (인메모리)
```

---

## 3. 핵심 모듈 설명

### 3.1 ingest/ -- 데이터 수집

외부 API 및 웹사이트에서 원본 데이터를 수집하는 계층.

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `base.py` | `BaseIngestor` | 수집기 ABC. httpx AsyncClient를 async context manager로 관리 |
| `fda.py` | `FDAClient`, `FDAApprovalIngestor` | openFDA API로 FDA 승인 약물 수집. 페이지네이션, 재시도, rate limit 처리 |
| `ema.py` | `EMAClient`, `EMAMedicineIngestor` | EMA JSON Report에서 EU 승인 의약품, 희귀의약품, 공급부족, DHPC 수집 |
| `mfds.py` | `MFDSClient`, `MFDSPermitIngestor` | 공공데이터포털 API로 MFDS 허가품목 수집 (284K건). 이중 인코딩 방지 로직 포함 |
| `cris.py` | `CRISClient`, `CRISTrialIngestor` | 공공데이터포털 API로 CRIS 임상시험 수집 (11.5K건) |
| `hira.py` | `HIRAInsuranceCriteriaIngestor`, `HIRANoticeIngestor` | Playwright로 HIRA 보험인정기준(고시/행정해석/심사지침) 크롤링 |
| `mohw.py` | `MOHWPreAnnouncementIngestor` | Playwright로 보건복지부 입법/행정예고 크롤링 |
| `asti.py` | `ASTIClient`, `ASTIIngestor` | **[v2]** Playwright로 ASTI 시장 리포트 크롤링. 키워드: 의약품/바이오/제약/신약 |
| `healthkr.py` | `HealthKRClient`, `HealthKRIngestor` | **[v2]** Playwright로 Health.kr 전문가 리뷰 수집. 검색→drug_cd→KPIC 섹션 파싱 |
| `biorxiv.py` | `BioRxivClient`, `BioRxivIngestor` | **[v2]** REST API로 bioRxiv/medRxiv 프리프린트 수집. 키워드 필터링 |

### 3.2 parse/ -- 데이터 파서

각 소스의 원본 응답을 정규화된 dict로 변환. `parse_many(raw_list)` 메서드로 배치 처리.

| 모듈 | 주요 클래스 | 입력 | 주요 출력 필드 |
|------|-----------|------|-------------|
| `fda_parser.py` | `FDADrugParser` | openFDA JSON | `generic_name`, `brand_name`, `submission_status_date`, `source_url` |
| `ema_parser.py` | `EMAMedicineParser`, `EMAOrphanParser` | EMA JSON Report | `inn`, `is_orphan`, `is_prime`, `marketing_authorisation_date` |
| `mfds_parser.py` | `MFDSPermitParser` | 공공데이터포털 JSON | `main_ingredient`, `permit_date`, `is_new_drug`, `indication` |
| `cris_parser.py` | `CRISTrialParser` | 공공데이터포털 JSON | `trial_id`, `phase`, `status`, `drug_names`, `is_drug_trial` |
| `hira_parser.py` | `HIRAParser` | Playwright 크롤링 결과 | `title`, `category`, `change_type`, `domain` |
| `asti_parser.py` | `ASTIReportParser` | **[v2]** ASTI 크롤링 결과 | `title`, `market_size_krw`, `growth_rate`, `published_date` |
| `healthkr_parser.py` | `HealthKRParser` | **[v2]** Health.kr 크롤링 결과 | `title`, `source`, `summary`, `published_date` |
| `biorxiv_parser.py` | `BioRxivParser` | **[v2]** bioRxiv API 응답 | `doi`, `title`, `authors`, `pdf_url`, `published_date` |

### 3.3 map/ -- 매핑 & 통합

서로 다른 소스의 데이터를 성분명(INN) 기준으로 통합하고, 핫이슈를 스코어링.

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `matcher.py` | `IngredientMatcher` | 성분명 정규화 (접미사 제거, 유의어 매핑). `DrugMatcher`로 FDA-MFDS-HIRA 통합 |
| `global_status.py` | `GlobalRegulatoryStatus`, `HotIssueScorer`, `GlobalStatusBuilder` | FDA+EMA+MFDS 데이터를 INN 기준 병합. 0-100점 핫이슈 스코어 (Breakthrough +15, Orphan +15 등) |
| `ingredient_bridge.py` | `IngredientBridge`, `HIRAReimbursementInfo` | 의약품주성분 마스터를 브릿지로 MFDS->HIRA 연결 (75.7% 매칭률). 정규화 후 완전 일치만 사용 |
| `atc.py` | `ATCDatabase`, `ATCMatcher` | WHO ATC 분류 코드 매칭 (GitHub CSV 자동 다운로드/캐시) |
| `timeline.py` | `DrugTimeline`, `TimelineBuilder` | 약물별 타임라인 구축 (FDA->EMA->MFDS->HIRA) |

**핫이슈 스코어링 기준** (합산, 최대 100점):

| 항목 | 점수 |
|------|------|
| FDA 승인 | +10 |
| FDA Breakthrough | +15 |
| FDA Accelerated | +10 |
| EMA 승인 | +10 |
| EMA PRIME | +15 |
| 희귀의약품 | +15 |
| 3개국 이상 승인 | +10 |
| FDA+EMA 근접 승인 | +10 |
| 주요 질환 치료제 | +10 |

### 3.4 scan/ -- 분석 엔진

통합된 데이터를 분석하여 국내 시장 영향도 판단 및 FeedCard 생성.

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `domestic.py` | `DomesticImpactAnalyzer`, `DomesticImpact` | 국내 영향 분석: MFDS 허가 + HIRA 급여 + CRIS 임상 종합. `DomesticStatus` 8단계 분류 (REIMBURSED, IMMINENT, EXPECTED 등) |
| `signal_generator.py` | `SignalGenerator` | 파싱된 데이터를 FeedCard로 변환 (제목/요약/영향도/도메인/태그 자동 생성) |
| `why_it_matters.py` | `WhyItMattersGenerator` | "왜 중요한가" 1문장 생성. LLM(GPT-4o-mini) 우선, 실패시 키워드 기반 템플릿 폴백 |

### 3.5 monitor/ -- 일간 모니터링

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `daily_scanner.py` | `DailyScanner`, `ScanResult`, `NewApproval` | 매일 FDA/EMA/MFDS API를 조회하여 신규 승인 감지. 기존 데이터와 크로스 매칭으로 핫이슈 자동 판정 (threshold: 20점) |

### 3.6 report/ -- 리포트 생성

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `generator.py` | `ReportGenerator` | DB 기반 일간/주간 리포트 생성 (텍스트, 마크다운 형식) |
| `llm_generator.py` | `LLMBriefingGenerator`, `BriefingReport` | OpenAI/Anthropic LLM으로 약물별 브리핑 리포트 생성. Few-Shot + CoT 프롬프트 |
| `prompts.py` | -- | 시스템 프롬프트, 브리핑 리포트, 메드클레임, 간단요약 프롬프트 템플릿 |

### 3.7 ai/ -- AI Intelligence Layer [v2]

3단 AI 파이프라인: 추론 → 검증 → 작성. 모든 단계 `ENABLE_*` 플래그로 독립 토글.

| 모듈 | 주요 클래스 | 역할 |
|------|-----------|------|
| `gemini_parser.py` | `GeminiParser` | bioRxiv PDF → Gemini API → 구조화 데이터 (약물명/적응증/MOA/결과). MD5 캐싱 |
| `reasoning_engine.py` | `ReasoningEngine` | o4-mini (reasoning_effort=high)로 4대 스트림 CoT 분석. impact_score/risk/opportunity 생성 |
| `verifier.py` | `InsightVerifier` | GPT-5.2 (temperature=0.2)로 추론 결과 팩트체크. verified_score/corrections/confidence 생성 |
| `writing_engine.py` | `WritingEngine` | GPT-5.2 (temperature=0.7)로 기사 작성. briefing/newsletter/press_release 3종 |
| `pipeline.py` | `AIIntelligencePipeline` | 3단 오케스트레이터. 일일 호출 제한, 단계별 fallback, 사용량 추적 |
| `prompts/` | -- | reasoning/verifier/writer 프롬프트 템플릿. Few-Shot 예시 포함 |

**파이프라인 흐름:**
```
[o4-mini] Reasoning → [GPT-5.2] Verifier → [GPT-5.2] Writer
     ↓ fallback           ↓ fallback           ↓ fallback
  global_score 유지    confidence=low       템플릿 기사
```

### 3.8 api/ -- FastAPI REST API

| 모듈 | 역할 |
|------|------|
| `main.py` | FastAPI 앱 생성. lifespan에서 데이터 로드 + 스케줄러 시작. CORS 전역 허용 |
| `deps.py` | `DataStore` 싱글톤: 앱 시작 시 data/ 최신 파일 로드 -> 파싱 -> 글로벌 상태 병합 -> 국내 영향 분석 -> 메모리 캐싱 |
| `schemas.py` | Pydantic 응답 스키마: `StatsResponse`, `DrugDetail`, `MedclaimInsight`, `BriefingReportResponse` 등 |
| `routes/drugs.py` | 약물 목록/상세/검색/메드클레임/LLM 브리핑 엔드포인트 |
| `routes/stats.py` | 전체 통계, 핫이슈, 도입임박 약물 엔드포인트 |
| `routes/scheduler.py` | 스케줄러 상태 조회, 수동 실행 트리거 |

---

## 4. 설정 가이드

### 4.1 settings.py 설정값 표

`regscan/config/settings.py`에서 `pydantic-settings`로 관리. `.env` 파일 또는 환경변수로 오버라이드 가능.

| 변수명 | 타입 | 기본값 | 설명 |
|--------|------|--------|------|
| `BASE_DIR` | `Path` | 프로젝트 루트 자동 감지 | 프로젝트 기본 경로 |
| `DATA_DIR` | `Path` | `BASE_DIR / "data"` | 데이터 파일 디렉토리 |
| `DB_URL` | `str` | `sqlite+aiosqlite:///data/regscan.db` | SQLAlchemy DB URL |
| `FDA_API_KEY` | `str?` | `None` | openFDA API 키 (없으면 rate limit 적용) |
| `FDA_BASE_URL` | `str` | `https://api.fda.gov` | FDA API 베이스 URL |
| `FDA_TIMEOUT` | `float` | `30.0` | FDA API 타임아웃 (초) |
| `OPENAI_API_KEY` | `str?` | `None` | OpenAI API 키 (LLM 브리핑 생성용) |
| `ANTHROPIC_API_KEY` | `str?` | `None` | Anthropic API 키 (Claude 브리핑 생성용) |
| `LLM_TIMEOUT` | `float` | `5.0` | LLM API 타임아웃 (초) |
| `USE_LLM` | `bool` | `True` | LLM 사용 여부 (False면 템플릿만) |
| `DATA_GO_KR_API_KEY` | `str?` | `None` | 공공데이터포털 API 키 (MFDS, CRIS) |
| `OPEN_ASSEMBLY_API_KEY` | `str?` | `None` | 열린국회정보 API 키 |
| `COLLECT_DAYS_BACK` | `int` | `7` | 수집 시 최근 N일 기간 |
| `SCHEDULER_ENABLED` | `bool` | `True` | 스케줄러 자동 시작 여부 |
| `DAILY_SCAN_HOUR` | `int` | `8` | 일간 스캔 실행 시각 (시) |
| `DAILY_SCAN_MINUTE` | `int` | `0` | 일간 스캔 실행 시각 (분) |
| `SCAN_DAYS_BACK` | `int` | `7` | 일간 스캔 범위 (일) |
| `GENERATE_BRIEFING` | `bool` | `True` | 핫이슈 브리핑 자동 생성 |
| `GENERATE_HTML` | `bool` | `True` | HTML 뉴스레터 자동 생성 |
| `LOG_LEVEL` | `str` | `"INFO"` | 로깅 레벨 |

#### v2 추가 설정

| 변수명 | 타입 | 기본값 | 설명 |
|--------|------|--------|------|
| `GEMINI_API_KEY` | `str?` | `None` | Google Gemini API 키 (PDF 파싱용) |
| `ENABLE_GEMINI_PARSING` | `bool` | `False` | Gemini PDF 파싱 활성화 |
| `GEMINI_MODEL` | `str` | `"gemini-2.5-flash"` | Gemini 모델명 |
| `ENABLE_AI_REASONING` | `bool` | `False` | o4-mini 추론 엔진 활성화 |
| `REASONING_MODEL` | `str` | `"o4-mini"` | 추론 모델명 |
| `ENABLE_AI_VERIFIER` | `bool` | `False` | GPT-5.2 검증기 활성화 |
| `VERIFIER_MODEL` | `str` | `"gpt-5.2"` | 검증 모델명 |
| `ENABLE_AI_WRITER` | `bool` | `False` | GPT-5.2 기사 작성기 활성화 |
| `WRITER_MODEL` | `str` | `"gpt-5.2"` | 기사 작성 모델명 |
| `MAX_REASONING_CALLS_PER_DAY` | `int` | `50` | 일일 추론 API 호출 제한 |
| `MAX_WRITER_CALLS_PER_DAY` | `int` | `50` | 일일 기사 작성 API 호출 제한 |
| `ENABLE_ASTI` | `bool` | `False` | ASTI 시장 리포트 수집 활성화 |
| `ENABLE_HEALTHKR` | `bool` | `False` | Health.kr 전문가 리뷰 수집 활성화 |
| `ENABLE_BIORXIV` | `bool` | `False` | bioRxiv 프리프린트 수집 활성화 |

### 4.2 .env 파일 예시

```env
# === API 키 ===
FDA_API_KEY=your_fda_api_key_here
DATA_GO_KR_API_KEY=your_data_go_kr_key_here
OPENAI_API_KEY=sk-your_openai_key_here
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key_here

# === 스케줄러 ===
SCHEDULER_ENABLED=true
DAILY_SCAN_HOUR=8
DAILY_SCAN_MINUTE=0
SCAN_DAYS_BACK=7

# === LLM ===
USE_LLM=true
LLM_TIMEOUT=5.0

# === 로깅 ===
LOG_LEVEL=INFO
```

---

## 5. API 엔드포인트 목록

API 서버 실행: `uvicorn regscan.api.main:app --reload`

### 시스템 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | API 상태 (서비스명, 버전, 상태) |
| `GET` | `/health` | 헬스체크 (로드 시간, 약물 건수) |

### Stats & 핫이슈 (`/api/v1`)

| Method | Path | 설명 | 주요 파라미터 |
|--------|------|------|-------------|
| `GET` | `/api/v1/stats` | 전체 통계 (소스별 건수, 핫이슈/임박 건수) | -- |
| `GET` | `/api/v1/hot-issues` | 핫이슈 목록 (글로벌 스코어 >= threshold) | `min_score=60`, `limit=50` |
| `GET` | `/api/v1/imminent` | 국내 도입 임박 약물 | `limit=50` |

### Drugs (`/api/v1/drugs`)

| Method | Path | 설명 | 주요 파라미터 |
|--------|------|------|-------------|
| `GET` | `/api/v1/drugs` | 약물 목록 (페이지네이션) | `offset=0`, `limit=50`, `status=(reimbursed\|imminent\|hot\|high_value)` |
| `GET` | `/api/v1/drugs/search` | 약물 검색 (INN 부분 매칭) | `q` (필수, 2자 이상), `limit=20` |
| `GET` | `/api/v1/drugs/{inn}` | 약물 상세 (글로벌+국내+CRIS) | -- |
| `GET` | `/api/v1/drugs/{inn}/medclaim` | 메드클레임 시사점 (급여/본인부담/인사이트) | -- |
| `GET` | `/api/v1/drugs/{inn}/briefing` | LLM 브리핑 리포트 생성 | `use_llm=true` |
| `GET` | `/api/v1/drugs/{inn}/insight` | **[v2]** AI 추론·검증 결과 | -- |
| `GET` | `/api/v1/drugs/{inn}/article` | **[v2]** AI 기사 조회 | `article_type=briefing` |
| `GET` | `/api/v1/drugs/{inn}/preprints` | **[v2]** 프리프린트 논문 목록 | -- |
| `GET` | `/api/v1/drugs/{inn}/market` | **[v2]** 시장 리포트 목록 | -- |

### Scheduler (`/api/v1/scheduler`)

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/v1/scheduler/status` | 스케줄러 상태 (실행여부, 다음실행, 마지막결과) |
| `POST` | `/api/v1/scheduler/run-now` | 일간 파이프라인 즉시 실행 (백그라운드) |

---

## 6. 일간 파이프라인 흐름

APScheduler가 매일 지정 시각(기본 08:00)에 `run_daily_pipeline()`을 실행.
수동 실행: `POST /api/v1/scheduler/run-now` 또는 `python scripts/run_daily_scan.py`.

### 실행 단계

```
run_daily_pipeline()
│
├── [Step 1/9] 데이터 수집 (FDA/EMA/MFDS/CRIS)
│   └── scanner.scan(days_back=7)
│
├── [Step 2/9] 데이터 파싱 + 매핑 + 스코어링
│
├── [Step 3/9] DB 저장 (drugs, regulatory_events 등)
│
├── [Step 4/9] 스캔 결과 JSON 저장
│   └── output/daily_scan/scan_YYYY-MM-DD.json
│
├── [Step 4.5/9] [v2] 신규 소스 수집 — ENABLE_* 체크
│   ├── ASTI 시장 리포트 (ENABLE_ASTI)
│   ├── Health.kr 전문가 리뷰 (ENABLE_HEALTHKR)
│   └── bioRxiv 프리프린트 (ENABLE_BIORXIV)
│
├── [Step 4.6/9] [v2] Gemini PDF 파싱 — ENABLE_GEMINI_PARSING 체크
│   └── 핫이슈(score>=60) 프리프린트 PDF만 선택 파싱
│
├── [Step 5/9] LLM 브리핑 생성 (기존 v1)
│
├── [Step 5.5/9] [v2] AI 3단 파이프라인 — ENABLE_AI_* 체크
│   ├── ReasoningEngine (o4-mini): 영향도 추론
│   ├── InsightVerifier (GPT-5.2): 팩트체크
│   └── WritingEngine (GPT-5.2): 기사 생성
│   └── 핫이슈(score>=60) 상위 10건만 대상
│
├── [Step 6/9] HTML 뉴스레터 생성
│
└── [Step 7/9] DataStore 리로드
    └── reload_data()
```

### ScanResult 구조

```python
ScanResult(
    scan_date=date(2026, 2, 6),
    fda_new=[NewApproval(...)],     # FDA 신규 승인
    ema_new=[NewApproval(...)],     # EMA 신규 승인/갱신
    mfds_new=[NewApproval(...)],    # MFDS 신규 허가
    hot_issues=[NewApproval(...)],  # 핫이슈 (score >= 20)
    errors=["..."],                 # 에러 로그
)
```

---

## 7. scripts/ 디렉토리 가이드

### 데이터 수집 스크립트

| 스크립트 | 실행 방법 | 설명 |
|---------|----------|------|
| `python -m regscan.scripts.collect_all` | 패키지 스크립트 | FDA+HIRA+MOHW 통합 수집. `--sources fda hira mohw`, `--days 7`, `--no-llm`, `--dry-run` |
| `scripts/collect_ema.py` | `python scripts/collect_ema.py` | EMA 데이터 단독 수집, `data/ema/medicines_*.json` 저장 |
| `scripts/collect_mfds_full.py` | `python scripts/collect_mfds_full.py` | MFDS 전체 허가품목 수집 (44K건), `data/mfds/permits_full_*.json` 저장 |

### 리포트 생성 스크립트

| 스크립트 | 설명 |
|---------|------|
| `scripts/run_daily_scan.py` | 일간 스캔 수동 실행 (스케줄러 없이) |
| `scripts/generate_daily_html.py` | ScanResult로부터 HTML 뉴스레터 생성 |
| `scripts/generate_briefing_reports.py` | LLM 브리핑 리포트 배치 생성 |
| `scripts/generate_html_briefings.py` | 브리핑 리포트 HTML 형식 생성 |
| `scripts/generate_full_report.py` | 전체 분석 리포트 생성 |
| `scripts/generate_full_report_with_fda.py` | FDA 데이터 포함 전체 리포트 |

### 유틸리티/분석 스크립트

| 스크립트 | 설명 |
|---------|------|
| `scripts/build_timeline_dataset.py` | 약물 타임라인 데이터셋 구축 (FDA->MFDS->HIRA) |
| `scripts/compare_models.py` | LLM 모델 비교 (GPT-4o-mini vs GPT-4o 등) |
| `scripts/capture_screenshot.py` | 브라우저 스크린샷 캡처 유틸 |
| `scripts/scraping/` | 뉴스 스크래핑 도구 (약업신문, 멀티소스) |

### 테스트 스크립트

| 스크립트 | 설명 |
|---------|------|
| `scripts/test_api.py` | API 통합 테스트 (전체 엔드포인트 호출) |
| `scripts/test_e2e_pipeline.py` | E2E 파이프라인 테스트 (수집->파싱->분석->리포트) |
| `scripts/test_briefing.py` | LLM 브리핑 생성 테스트 |
| `scripts/test_ingredient_bridge.py` | MFDS<->HIRA 브릿지 매칭 테스트 |
| `scripts/test_domestic_impact.py` | 국내 영향 분석 테스트 |
| `scripts/test_global_status.py` | 글로벌 규제 현황 통합 테스트 |

### pytest 단위 테스트

```bash
pytest tests/                    # 전체 테스트 실행 (52건)
pytest tests/test_fda.py         # FDA 수집기 테스트
pytest tests/test_hira.py        # HIRA 수집기 테스트
pytest tests/test_models.py      # 데이터 모델 테스트
pytest tests/test_v2_schema.py   # [v2] DB 스키마 테스트 (7건)
pytest tests/test_v2_pipeline.py # [v2] 파서·설정·임포트 테스트 (13건)
pytest tests/test_ai_pipeline.py # [v2] AI 파이프라인 테스트 (9건)
```

---

## 부록: 빠른 시작

```bash
# 1. 의존성 설치
pip install -e ".[dev,llm,crawl]"

# 2. .env 파일 생성 (API 키 설정)
cp .env.example .env

# 3. 데이터 수집 (초기 1회)
python scripts/collect_ema.py
python scripts/collect_mfds_full.py

# 4. API 서버 실행
uvicorn regscan.api.main:app --reload

# 5. API 테스트
python scripts/test_api.py

# 6. 일간 스캔 수동 실행
python scripts/run_daily_scan.py
```
