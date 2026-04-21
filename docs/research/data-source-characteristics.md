# 데이터 소스 특성 및 갱신 주기 리포트

> 작성일: 2026-04-21
> 기준: 전체 25개 소스 실측 데이터 기반 분석
> 목적: 수집 대시보드 설계 기초자료

---

## 1. 전체 소스 실측 요약

### 1.1 실측 결과 일람

| # | 소스 | source_type | 실측 건수 | 실측 조건 | 상태 |
|---|------|------------|----------|----------|------|
| 1 | FDA openFDA | (DailyScanner) | 29,014 전체 | API meta | OK |
| 2 | FDA Orange Book | FDA_ORANGE_BOOK | 70,995 | 전수 CSV | OK |
| 3 | FDA Patent Expiry | FDA_PATENT_EXPIRY | 22,912 | 만료일 필터 | OK |
| 4 | FDA Purple Book | FDA_PURPLE_BOOK | 2,173 | 전수 CSV | OK |
| 5 | FDA Biologic Expiry | FDA_BIOLOGIC_EXPIRY | 599 | 독점권 필터 | OK |
| 6 | EMA Medicine | EMA_MEDICINE | 2,679 | 전수 JSON | OK |
| 7 | EMA Orphan | EMA_ORPHAN | 3,160 | 전수 JSON | OK |
| 8 | EMA Safety | EMA_SAFETY | 752 | 전수 JSON | OK |
| 9 | EMA Shortage | EMA_SHORTAGE | 77 | 전수 JSON | OK |
| 10 | PMDA Review RSS | PMDA_REVIEW | 17 | 365일 | OK |
| 11 | PMDA Safety RSS | PMDA_SAFETY | 11 | 365일 RSS | OK |
| 12 | PMDA Safety Table | PMDA_SAFETY_REPORT | 75 | 전체 HTML | OK |
| 13 | PMDA Approval | PMDA_APPROVAL | 275 | 2년 Excel | OK |
| 14 | NICE TA 전체 | NICE_TA | 1,486 | 전수 Excel | OK |
| 15 | NICE TA 최근 | NICE_TA_RECENT | 179 | 2년 필터 | OK |
| 16 | MFDS 허가 | MFDS_PERMIT | 284,000+ | data.go.kr (API 키 401) | WARN |
| 17 | MFDS 신약 | MFDS_NEW_DRUG | - | data.go.kr (API 키 401) | WARN |
| 18 | MFDS 안전성 서한 | MFDS_SAFETY_LETTER | 2 | 90일 (이전 테스트) | OK* |
| 19 | MFDS 회수 | MFDS_RECALL | - | data.go.kr (API 키 401) | WARN |
| 20 | HIRA 약가/급여 | HIRA_NOTICE | 59,076 | Playwright (이전 실행) | OK* |
| 21 | MOHW 입법예고 | MOHW_ADMIN_NOTICE | - | Playwright 필요 | N/T |
| 22 | MOHW 건강보험 | MOHW_HEALTH_INSURANCE | 2 | 365일, 정밀필터 | OK |
| 23 | 국회 법안 | ASSEMBLY_BILL | 175 | 365일, 16키워드 | OK |
| 24 | CRIS 임상시험 | CRIS_TRIAL | - | **엔드포인트 미존재**, API 폐기 추정 | FAIL |
| 25 | bioRxiv/medRxiv | BIORXIV | 0 | 7일 (API 일시 장애) | WARN |
| 26 | KHIDI | KHIDI | 4 | 30일 | OK |
| 27 | KDCA | KDCA | - | Playwright 필요 | N/T |
| 28 | ASTI | ASTI | - | Playwright, 기본 OFF | N/T |
| 29 | Health.kr | HEALTHKR | - | Playwright, 기본 OFF | N/T |
| 30 | Endpoints News | (RSS) | 24 items/피드 | RSS | OK |
| 31 | FiercePharma | (RSS) | 5/3일 | RSS (파싱 버그 수정 `5020a54`) | OK |
| 32 | FierceBiotech | (RSS) | 5/3일 | RSS (파싱 버그 수정 `5020a54`) | OK |
| 33 | DART 공시 | DART_DISCLOSURE | 7/30일 | API 키 발급 완료, 테스트 통과 | OK |
| 34 | KIPRIS 특허 | KIPRIS_PATENT | - | 키 발급 완료, **서비스 이용신청 필요** | WARN |

**범례:** OK=정상, OK*=이전 실행 결과, WARN=일시적 이슈, FAIL=차단, N/T=미테스트(환경 제약)

### 1.2 현재 이슈

| 이슈 | 대상 | 영향 | 조치 |
|------|------|------|------|
| ~~data.go.kr API 키 401~~ | ~~MFDS 허가~~ | **해결** (활용신청 재등록) | MFDS 회수도 정상 |
| ~~FiercePharma/Biotech 403~~ | ~~뉴스 RSS 2개~~ | **해결** (`5020a54`) | title 내 HTML 파싱 버그 수정 |
| **bioRxiv API 일시 장애** | 학술 프리프린트 | 일시적, 재시도로 해결 | 자동 재시도 |
| **nedrug TLS 불안정** | MFDS 안전성 서한 | 간헐적 ConnectError | TLS 1.2 + 재시도 |

---

## 2. 소스별 상세 분석

### 2.1 FDA (미국)

#### openFDA

| 항목 | 값 |
|------|-----|
| 수집 방식 | REST API (`api.fda.gov/drug/drugsfda.json`) |
| 전체 건수 | 29,014 NDA/BLA |
| API 갱신일 | 2026-04-20 (거의 매일) |
| 갱신 주기 | **수시** (승인 즉시 반영) |
| 인증 | `FDA_API_KEY` (없어도 동작, rate limit만) |
| 호출 위치 | DailyScanner 직접 호출 |

#### Orange Book (특허/독점권)

| 항목 | 값 |
|------|-----|
| 수집 방식 | CSV 벌크 다운로드 |
| 전체 건수 | 70,995 제품 |
| 특허 만료 필터 | 22,912건 |
| 갱신 주기 | **월간** (매월 초) |
| 데이터 특성 | 특허 만료일은 고정값, 변동 적음 |

#### Purple Book (생물의약품)

| 항목 | 값 |
|------|-----|
| 수집 방식 | CSV 다운로드 (세션 쿠키 필요, Akamai bot 감지) |
| 전체 건수 | 2,173 BLA |
| 독점권 만료 필터 | 599건 |
| 갱신 주기 | **분기** |
| 주의 | Bot 감지 우회 필요 — 장기적 불안정 가능 |

---

### 2.2 EMA (유럽)

| 항목 | Medicine | Orphan | Safety | Shortage |
|------|---------|--------|--------|----------|
| 수집 방식 | JSON Report | JSON Report | JSON Report | JSON Report |
| 전체 건수 | 2,679 | 3,160 | 752 | 77 |
| 갱신 주기 | **주 1~2회** | 주간 | 수시 | 수시 |
| 인증 | 불필요 (공개) | 좌동 | 좌동 | 좌동 |

**갱신 패턴:** CHMP 매주 목요일 의견 → EC 결정 → JSON 반영 (1~2주)

---

### 2.3 PMDA (일본)

| 항목 | Review RSS | Safety RSS | Safety Table | Approval Excel |
|------|-----------|-----------|--------------|---------------|
| 건수 | 17/년 | 11/년 | 75 (전체 이력) | 275 (2년) |
| 갱신 주기 | **주 1~2회** | **주 1~2회** | 수시 | **월 1회 배치** |
| 최신 | 2026-04-14 | - | - | 2026-03-23 |

**핵심 발견 — 월 1회 일괄 승인:**
```
승인 간격: 평균 36일, 중앙값 35일
1회당 건수: 7~33건 (대량 배치)
고유 승인일: 20일/2년 (월 ~1일)
```

**승인일 분포 (최근):**
| 날짜 | 건수 | 날짜 | 건수 |
|------|------|------|------|
| 2025-09-19 | 33 | 2026-02-19 | 15 |
| 2025-12-22 | 22 | 2026-03-06 | 1 |
| 2025-11-20 | 7 | 2026-03-23 | 20 |

**전략:** RSS(실시간 알림) + Excel(구조화 데이터) 조합. RSS `[SHINSA]` 태그가 선행 신호.

---

### 2.4 NICE HTA (영국)

| 항목 | 값 |
|------|-----|
| 수집 방식 | storyblok CDN Excel 벌크 |
| 전체 TA | 1,486건 (2000년~현재) |
| 최근 2년 | 179건 |
| 갱신 주기 | **TA 발행 시 반영** (월 2~5건) |
| 인증 | 불필요 (공개 CDN) |

**데이터 특성:** Excel에 날짜 컬럼이 명확하지 않아 전체 다운로드 + diff 전략이 적합.
연간 ~80건 TA, 단일 Excel 파일이라 트래픽 부담 없음.

---

### 2.5 MFDS (식약처)

#### 허가 품목 (공공데이터 API)

| 항목 | 값 |
|------|-----|
| 수집 방식 | data.go.kr REST API |
| 전체 건수 | 284,000+ 품목 |
| 갱신 주기 | **수시** (허가 즉시, API 반영 ~1주) |
| 현재 상태 | **API 키 401** — 갱신 필요 |

#### 안전성 서한 (nedrug 크롤링)

| 항목 | 값 |
|------|-----|
| 수집 방식 | httpx+bs4 (nedrug.mfds.go.kr, TLS 1.2) |
| 실측 건수 | 2건/90일 |
| 갱신 주기 | **비정기** (안전성 이슈 발생 시, 월 0~3건) |
| 주의 | TLS 1.3 미지원, 간헐적 ConnectError |

#### 회수/판매중지 (공공데이터 API)

| 항목 | 값 |
|------|-----|
| 수집 방식 | data.go.kr REST API |
| 갱신 주기 | **수시** |
| 현재 상태 | **API 키 401** — 갱신 필요 |

---

### 2.6 HIRA (심평원)

| 항목 | 값 |
|------|-----|
| 수집 방식 | Playwright (Nexacro SSV 역공학) |
| 약가 건수 | 59,076 제품 |
| 갱신 주기 | **월간** (고시 반영, 매월 1일 경) |
| 수집 주기 | `python -m regscan.workers.drug_price_collector` |
| Ingestor 클래스 | HIRAInsuranceCriteriaIngestor, HIRANoticeIngestor, HIRAGuidelineIngestor |
| 주의 | Playwright + Chromium 필수, JS 렌더링 |

---

### 2.7 MOHW (보건복지부)

#### 입법/행정예고

| 항목 | 값 |
|------|-----|
| 수집 방식 | Playwright |
| 갱신 주기 | **수시** (예고 공고 시) |
| Ingestor 클래스 | MOHWPreAnnouncementIngestor, MOHWNoticeIngestor, MOHWAdminNoticeIngestor |

#### 건강보험정책 (건보심)

| 항목 | 값 |
|------|-----|
| 수집 방식 | httpx+bs4 (보도자료 키워드 필터) |
| 실측 건수 | 2건/365일 (정밀 필터 후) |
| 갱신 주기 | **분기 1~2건** |
| 핵심 부서 | 보험급여과, 약무정책과 |
| 필터 전략 | 담당부서 필터 + 고신뢰 키워드 (건보심, 약가, 요양급여 등) |

---

### 2.8 국회 의안정보

| 항목 | 값 |
|------|-----|
| 수집 방식 | 열린국회정보 REST API (JSON) |
| 실측 건수 | 175건/365일 (22대 국회) |
| 월평균 | **13.5건/월** |
| 갱신 주기 | **수시** (발의 즉시 반영) |
| 인증 | `OPEN_ASSEMBLY_API_KEY` + User-Agent 필수 |

**월별 분포:**
```
2025-04:  3    2025-07:  5    2025-10:  8    2026-01: 12
2025-05:  5    2025-08: 21    2025-11: 20    2026-02: 14
2025-06:  7    2025-09: 25    2025-12: 17    2026-03: 26
                                              2026-04: 12
```
정기국회(9~12월) 집중: 월 17~25건 / 휴회기: 월 3~8건

**키워드 분포:**
| 키워드 | 건수 | 비율 |
|--------|------|------|
| 약사법 | 26 | 15% |
| 건강보험법 | 24 | 14% |
| 의료법 | 20 | 11% |
| 보건의료 | 10 | 6% |
| 의료기기 | 9 | 5% |
| 마약류 | 6 | 3% |
| 기타 | 80 | 46% |

---

### 2.9 CRIS (임상시험정보서비스)

| 항목 | 값 |
|------|-----|
| 수집 방식 | data.go.kr REST API |
| 전체 건수 | 11,500+ 국내 임상시험 |
| 갱신 주기 | **수시** (등록 즉시) |
| 인증 | `DATA_GO_KR_API_KEY` |
| Ingestor 클래스 | CRISTrialIngestor, CRISActiveTrialIngestor, CRISDrugTrialIngestor |

---

### 2.10 bioRxiv/medRxiv

| 항목 | 값 |
|------|-----|
| 수집 방식 | REST API (`api.biorxiv.org/details`) |
| 갱신 주기 | **일일** (프리프린트 게시 즉시) |
| 실측 | 테스트 시점 API 일시 장애 (0건) |
| 정상 시 | 약물 키워드 기준 주 10~30건 |
| 인증 | 불필요 (공개) |

---

### 2.11 KHIDI (보건산업진흥원)

| 항목 | 값 |
|------|-----|
| 수집 방식 | Web API (httpx) |
| 실측 건수 | 4건/30일 |
| 갱신 주기 | **주 1~2건** |
| 인증 | 불필요 |
| Ingestor 클래스 | KHIDIIngestor, KHIDIBriefIngestor, KHIDIReportIngestor |

---

### 2.12 KDCA (질병관리청)

| 항목 | 값 |
|------|-----|
| 수집 방식 | Playwright |
| 갱신 주기 | **주 2~5건** (보도자료) |
| 인증 | 불필요 |

---

### 2.13 ASTI / Health.kr

| 항목 | ASTI | Health.kr |
|------|------|----------|
| 수집 방식 | Playwright | Playwright |
| 기본 설정 | **OFF** | **OFF** |
| 갱신 주기 | 월간 | 주간 |
| 용도 | 시장 조사 보고서 | 전문가 리뷰, KPIC |

---

### 2.14 뉴스 RSS

| 소스 | URL | 상태 | 건수/피드 |
|------|-----|------|----------|
| Endpoints News | endpts.com/feed/ | **OK** | 24 items |
| FiercePharma | fiercepharma.com/rss/xml | **OK** | 5/3일 |
| FierceBiotech | fiercebiotech.com/rss/xml | **OK** | 5/3일 |

**해결 완료:** `<title>` 내 `<a>` 태그로 인한 파싱 버그 → `itertext()`로 수정 (`5020a54`).

---

### 2.15 DART / KIPRIS (미검증)

| 항목 | DART | KIPRIS |
|------|------|--------|
| 수집 방식 | REST API (JSON) | REST API (XML) |
| 갱신 주기 | **수시** (공시 즉시) | **수시** (공개/등록 즉시) |
| API 키 | `DART_API_KEY` (미등록) | `KIPRIS_API_KEY` (미등록) |
| 코드 상태 | 구현 완료, graceful skip | 구현 완료, graceful skip |
| 예상 건수 | 제약 관련 월 수~수십 건 | 의약품 IPC 월 수십 건 |

---

## 3. 갱신 주기별 분류

### 실시간/수시 (이벤트 발생 즉시)

| 소스 | 반영 시간 | 일일 예상 건수 |
|------|----------|--------------|
| FDA openFDA | ~수시간 | 0~5 |
| DART 공시* | ~당일 | 0~10 |
| 국회 법안 | ~당일 | 0~3 |
| 뉴스 RSS | ~즉시 | 5~15 |
| KIPRIS 특허* | ~당일 | TBD |
| MFDS 허가 | ~1주 | 0~10 |

### 주간 갱신

| 소스 | 주기 | 주간 예상 건수 |
|------|------|--------------|
| EMA 의약품 | 주 1~2회 | 0~10 |
| PMDA RSS | 주 1~2회 | 0~3 |
| bioRxiv | 일일 | 10~30 |
| KHIDI | 주 1~2건 | 1~2 |
| KDCA | 주 2~5건 | 2~5 |

### 월간 갱신

| 소스 | 주기 | 월간 건수 |
|------|------|----------|
| PMDA 승인 Excel | 월 1회 배치 | 7~33 |
| HIRA 약가 | 월 1회 고시 | 전수 59K |
| Orange Book CSV | 월초 | 전수 71K |
| MFDS 안전성 서한 | 비정기, 월 0~3건 | 0~3 |
| MOHW 건강보험 | 분기 1~2건 | 0~1 |

### 분기+ 갱신

| 소스 | 주기 |
|------|------|
| Purple Book CSV | 분기 |
| NICE TA Excel | TA 발행 시 (월 2~5건) |

---

## 4. 데이터 신선도 매트릭스

이벤트 발생 → 데이터 반영까지 걸리는 시간:

| 이벤트 | 소스 | 반영 지연 |
|--------|------|----------|
| FDA 승인 | openFDA | **수시간** |
| FDA 승인 | Orange Book CSV | **~1개월** |
| EMA CHMP 의견 | JSON Report | **~1주** |
| PMDA 승인 | RSS | **~수일** (속보) |
| PMDA 승인 | Excel | **~수주** (정확한 지연 불명) |
| MFDS 허가 | data.go.kr API | **~1주** |
| MFDS 안전성 이슈 | nedrug 서한 | **~수일** |
| NICE TA 발행 | storyblok Excel | **~수일** |
| 건보심 의결 | MOHW 보도자료 | **~1~3일** |
| 법안 발의 | 열린국회정보 API | **즉시** (~당일) |
| 기업 공시 | DART API | **즉시** (~당일) |
| 특허 공개 | KIPRIS API | **즉시** (~당일) |
| 뉴스 보도 | RSS | **즉시** |

---

## 5. 대시보드 설계 시 고려사항

### 5.1 모니터링 지표 (권장)

| 지표 | 설명 | 알림 기준 |
|------|------|----------|
| `last_success_at` | 마지막 성공 수집 시각 | 예상 주기 × 2 초과 시 |
| `last_record_count` | 마지막 수집 건수 | 0건이 3회 연속 시 |
| `error_count_24h` | 최근 24시간 에러 횟수 | 3회 이상 시 |
| `avg_duration_ms` | 평균 수집 소요 시간 | 평소 대비 3배 초과 시 |
| `total_records` | 누적 수집 건수 | 갑작스러운 감소 시 |

### 5.2 소스별 기대 건수 (알림 임계값 설정용)

| 소스 | 일일 실행 시 기대 건수 | 0건 정상 여부 |
|------|---------------------|-------------|
| FDA openFDA | 0~5 | 정상 (승인 없는 날) |
| EMA | 0~10 | 정상 (갱신 없는 날) |
| PMDA RSS | 0~3 | 정상 |
| PMDA Approval | 0~33 | **정상** (월 1회만 데이터) |
| NICE HTA | 0~179 | diff 기반, 0=변경 없음 |
| MFDS 안전성 서한 | 0~3 | **정상** (비정기 발행) |
| MOHW 건강보험 | 0~2 | **정상** (분기 1~2건) |
| 국회 법안 | 0~5 | 정상 (휴회기) |
| bioRxiv | 0~30 | 0=API 장애 가능 |
| 뉴스 RSS | 5~15 | 0=차단/장애 |

### 5.3 건강 상태 분류

```
GREEN  — 최근 수집 성공, 기대 건수 범위 내
YELLOW — 수집 성공이나 건수 0건 (기대 주기 내)
ORANGE — 예상 주기 초과, 미수집
RED    — 에러 3회 연속 또는 API 키 만료
GRAY   — API 키 미등록 또는 ENABLE=False
```

---

## 6. 기술적 주의사항

### 인프라

| 이슈 | 대상 | 해결 |
|------|------|------|
| TLS 1.3 미지원 | nedrug.mfds.go.kr, pmda.go.jp | `ssl.maximum_version=TLSv1_2` |
| User-Agent 필수 | open.assembly.go.kr | `User-Agent: RegScan/1.0` |
| Bot 감지 (Akamai) | purplebooksearch.fda.gov | 세션 쿠키 선획득 |
| API 키 만료 | data.go.kr (MFDS/CRIS) | 주기적 갱신 |
| ~~RSS 403~~ | ~~FiercePharma, FierceBiotech~~ | **해결** — 파싱 버그 (`5020a54`) |
| Playwright 필요 | HIRA, MOHW예고, KDCA, ASTI, Health.kr | Chromium headless |

### 데이터 품질

| 이슈 | 대상 | 대응 |
|------|------|------|
| 날짜 형식 불일치 | PMDA (YYYY.M.DD) | 파서에서 정규화 |
| 제목 노이즈 | MOHW ("새글" 접두사) | regex 제거 |
| 키워드 오탐 | MOHW 건강보험 | 담당부서 필터 적용 |
| Excel 헤더 행 | PMDA, Orange Book | 동적 헤더 탐색 |
| NICE 날짜 없음 | TA Excel | 전체 다운로드 + diff |
| 일본어/한글 | PMDA, MFDS | UTF-8 강제 |
