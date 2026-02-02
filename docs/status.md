# RegScan 구현 현황

> 최종 업데이트: 2026-02-02 (오후)

## 현재 작업

### FDA→KR 매핑 엔진 구현 중
- 계획 문서: `worklog/plans/2026-02-02_fda_kr_mapping.md`
- 목표: 해외 승인 → 국내 급여 경로 분석
- 핵심: 비교기준, 시간축, 제도경로, 선례 검증

---

## 구현 완료

### Ingest Layer (데이터 수집)

| 소스 | 상태 | 파일 | 비고 |
|------|------|------|------|
| FDA Approvals | ✅ 완료 | `ingest/fda.py` | openFDA API, 41건 테스트 완료 |
| HIRA 보험인정기준 | ✅ 완료 | `ingest/hira.py` | Playwright, 25건 테스트 완료 |
| MOHW 행정예고 | ✅ 완료 | `ingest/mohw.py` | Playwright, iframe 처리 |
| HIRA 공지사항 | ⚠️ 미완성 | `ingest/hira.py` | 페이지 로드 이슈 |

### Parse Layer (파싱)

| 파서 | 상태 | 파일 | 비고 |
|------|------|------|------|
| FDADrugParser | ✅ 완료 | `parse/fda_parser.py` | domain/change_type 추론 |
| HIRAParser | ✅ 완료 | `parse/hira_parser.py` | 카테고리별 domain 매핑 |
| MOHWParser | ❌ 미구현 | - | raw data 그대로 사용 중 |
| KR 조-항-호-목 파서 | ❌ 미구현 | - | 로드맵에 스펙 정의됨 |

### Scan Layer (신호 생성)

| 기능 | 상태 | 파일 | 비고 |
|------|------|------|------|
| SignalGenerator | ✅ 완료 | `scan/signal.py` | FeedCard 생성 |
| why_it_matters | ✅ 완료 | `scan/why_it_matters.py` | 템플릿 + LLM 폴백 |
| Delta Analyzer | ❌ 미구현 | - | 버전 비교 |
| Evidence Trend | ❌ 미구현 | - | 논문 동향 분석 |

### Storage Layer (저장)

| 기능 | 상태 | 파일 | 비고 |
|------|------|------|------|
| FeedCardRepository | ✅ 완료 | `db/repository.py` | SQLite + SQLAlchemy |
| Snapshot Registry | ❌ 미구현 | - | 버전 관리 |
| Object Storage | ❌ 미구현 | - | S3/MinIO |

### Scripts (실행 스크립트)

| 스크립트 | 상태 | 파일 | 비고 |
|------|------|------|------|
| collect_fda.py | ✅ 완료 | `scripts/collect_fda.py` | FDA 단독 수집 |
| collect_hira.py | ✅ 완료 | `scripts/collect_hira.py` | HIRA 단독 수집 |
| collect_mohw.py | ✅ 완료 | `scripts/collect_mohw.py` | MOHW 단독 수집 |
| collect_all.py | ✅ 완료 | `scripts/collect_all.py` | 통합 파이프라인 (60건 테스트) |

---

### Map Engine (신규 구현 중)

| 기능 | 상태 | 파일 | 비고 |
|------|------|------|------|
| Timeline 모델 | 🔄 진행중 | `map/timeline.py` | FDA→MFDS→HIRA 시간축 |
| 성분명 매칭 | 🔄 진행중 | `map/matcher.py` | 정규화 + 매칭 로직 |
| 선례 분석 | ⬜ 예정 | `map/analyzer.py` | 동일계열 선례 검색 |
| 리포트 생성 | ⬜ 예정 | `map/report.py` | 전문가용 리포트 |

### 외부 데이터 연동

| 데이터 | 출처 | 건수 | 상태 |
|--------|------|------|------|
| MFDS 허가 | scrape-hub | 44,311건 | △ 연동 예정 |
| ATC 매핑 | scrape-hub/kpis | 21,702건 | △ 연동 예정 |
| 고시 히스토리 | scrape-hub/cg_parsed | 4,573건 | △ 연동 예정 |

---

## 미구현 (로드맵 기준)

### Sources (추가 데이터 소스)
- [ ] EMA (유럽 의약품청)
- [ ] CMS (미국 메디케어)
- [ ] PubMed/PMC (논문)
- [ ] medRxiv/bioRxiv (프리프린트)

### Infrastructure
- [ ] Scheduler (Airflow/cron)
- [ ] Queue (Redis Streams/RabbitMQ)
- [ ] Worker 아키텍처
- [ ] Postgres 마이그레이션
- [ ] Redis Cache
- [ ] Feed API (FastAPI)

### Advanced Features
- [ ] Map Engine (해외→국내 경로 매핑)
- [ ] Personalization (Role/Institution 프로필)
- [ ] Search/Vector DB

---

## 테스트 현황

| 테스트 | 결과 | 날짜 |
|--------|------|------|
| FDA 파이프라인 | ✅ 41건 수집/파싱/변환 | 2026-01-31 |
| HIRA 보험인정기준 | ✅ 25건 수집 | 2026-02-01 |
| MOHW 행정예고 | ✅ 10건 수집 | 2026-02-01 |
| 통합 파이프라인 | ✅ 60건 (FDA 35 + HIRA 25) | 2026-02-01 |

---

## 진행률

```
전체 로드맵 대비: ████░░░░░░░░░░░░░░░░ ~20%

데이터 수집:      ██████████░░░░░░░░░░ 50% (3/6 소스)
파싱:            ████████░░░░░░░░░░░░ 40% (기초 파서만)
신호 생성:        ████░░░░░░░░░░░░░░░░ 20% (Delta 없음)
인프라:          ██░░░░░░░░░░░░░░░░░░ 10% (SQLite만)
개인화:          ░░░░░░░░░░░░░░░░░░░░ 0%
API:            ░░░░░░░░░░░░░░░░░░░░ 0%
```
