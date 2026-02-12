# RegScan 프로젝트 현황 정리

> 작성일: 2026-02-12

---

## 1. 프로젝트 목적: 이걸 왜 만드는가

### 한 줄 정의

**글로벌 의약품 규제 변화를 스캔해서, "한국 보험/심사/급여" 관점의 영향으로 번역하는 인텔리전스 엔진.**

### 배경

메드클레임(MedClaim)이라는 의료 정보 포털이 본체다. RegScan은 그 메인화면에 **"오늘 봐야 할 정보"**를 공급하는 콘텐츠 엔진 역할.

```
MedClaim (본체)  ←  "정답을 말해주는" 인터랙티브 Q&A 시스템
    ↑
RegScan (서브)   ←  "보여줄 정보를 만드는" 규제 인텔리전스 엔진  ← 현재 위치
```

### 핵심 가치

| 기존 | RegScan |
|------|---------|
| 언론 기사 요약 (저작권 문제) | 1차 소스(기관 API) 직접 수집 |
| 빈 검색창 → 사용자가 알아서 검색 | 정보가 흐르는 포털 → 물어보지 않아도 알려줌 |
| 공공 데이터 = 무료 인식 | 큐레이션 + 개인화 + AI 분석 = 유료 가치 |

### 하는 것 / 안 하는 것

| 하는 것 | 안 하는 것 |
|---------|-----------|
| 규제 변화 **신호(Signal)** 감지 | 뉴스 기사 요약 |
| 임상/학술 **근거 흐름** 분석 | 단순 RAG 검색 |
| 글로벌 → 한국 **영향 매핑** | Chat 응답, 정답 판별 |
| AI 기반 **전문 기사** 생성 | Hallucination 통제 (MedClaim 역할) |

---

## 2. 아키텍처: 어떻게 돌아가는가

### 전체 파이프라인 (v2 기준)

```
[수집] → [파싱] → [매핑/스코어링] → [분석/AI] → [리포트/서빙]
```

구체적으로:

```
Step 1. 데이터 수집 (Ingest)
        FDA / EMA / MFDS / CRIS / HIRA / MOHW  ← v1 (동작중)
        ASTI / Health.kr / bioRxiv              ← v2 (코드만 있음)

Step 2. 파싱 (Parse)
        각 소스별 파서 → 정규화된 dict

Step 3. 매핑 + 스코어링 (Map)
        INN(성분명) 기준 FDA+EMA+MFDS 병합
        HotIssueScorer로 0-100점 부여 (HOT/HIGH/MID/LOW)
        MFDS↔HIRA 브릿지로 국내 급여 상태 연결

Step 4. DB 적재
        drugs 마스터 + regulatory_events + hira + clinical_trials 등

Step 4.5. [v2] 신규 소스 수집
        ASTI 시장 리포트, Health.kr 전문가 리뷰, bioRxiv 논문

Step 4.6. [v2] Gemini PDF 파싱
        bioRxiv PDF → Gemini API → 구조화 데이터

Step 5. LLM 브리핑 (v1)
        score >= 40 약물에 대해 Claude/GPT로 브리핑 리포트 생성

Step 5.5. [v2] AI 3단 파이프라인
        o4-mini(추론) → GPT-5.2(검증) → GPT-5.2(기사)
        score >= 40 핫이슈 약물만 대상

Step 6. HTML 뉴스레터 + JSON 저장

Step 7. FastAPI로 서빙 (DataStore 인메모리 캐시)
```

### 4대 데이터 스트림 (v2 설계)

| 스트림 | 소스 | 제공 정보 | 상태 |
|--------|------|-----------|------|
| **A. 규제 팩트** | FDA/EMA/MFDS | 승인, 특수 지정, 허가 | 동작중 |
| **B. 선행 기술** | bioRxiv/medRxiv | 프리프린트 논문, MOA | 코드만 |
| **C. 시장 규모** | ASTI/KISTI | 시장 규모, 성장률 | 코드만 |
| **D. 현장 반응** | Health.kr | KPIC 학술, 약사저널 | 코드만 |

### 3단 AI 엔진 (v2 설계)

```
[o4-mini] 추론 (Reasoning)
    4대 스트림 데이터를 종합해서 "인과관계 + 확률 추론"
    → impact_score, risk_factors, opportunity_factors
         ↓
[GPT-5.2] 검증 (Verifier)
    추론 결과 팩트체크, 교정
    → verified_score, corrections, confidence_level
         ↓
[GPT-5.2] 기사 작성 (Writer)
    검증된 분석을 기사화
    → briefing / newsletter / press_release
```

모든 단계 `ENABLE_*` 플래그로 독립 토글, 일일 API 호출 제한 있음.

### DB 스키마 (11개 테이블)

```
v1 (동작중):
  drugs              — 약물 마스터 (INN 기준, global_score, hot_issue_level)
  regulatory_events  — FDA/EMA/MFDS 승인 이벤트
  hira_reimbursements — HIRA 급여 정보
  clinical_trials    — CRIS 임상시험
  briefing_reports   — LLM 브리핑
  scan_snapshots     — 수집 메타 (날짜, 소스, 건수, GCS 경로)
  feed_cards         — 레거시 피드 카드

v2 (테이블 생성됨, 데이터 없음):
  preprints          — bioRxiv/medRxiv 논문
  market_reports     — ASTI/KISTI 시장 리포트
  expert_opinions    — Health.kr 전문가 리뷰
  ai_insights        — AI 추론+검증 결과
  articles           — AI 기사
```

### 핫이슈 스코어링 (HotIssueScorer, 최대 100점)

| 항목 | 점수 |
|------|------|
| FDA 승인 | +10 |
| FDA Breakthrough | +15 |
| FDA Accelerated | +10 |
| FDA Priority/Fast Track | +5 each |
| EMA 승인 | +10 |
| EMA PRIME | +15 |
| MFDS 승인 | +5 |
| 희귀의약품 | +15 |
| 3개국 이상 승인 | +10 |
| FDA+EMA 동시승인 | +10 |
| 주요 질환 (암/치매/당뇨 등) | +10 |

**등급:** HOT(80+) / HIGH(60-79) / MID(40-59) / LOW(<40)

**필터링 기준선:**

| 상수 | 값 | 용도 |
|------|---|------|
| `MIN_SCORE_FOR_DB` | 10 | DB에 넣을 최소 점수 |
| `MIN_SCORE_FOR_BRIEFING` | 40 | v1 LLM 브리핑 대상 |
| `MIN_SCORE_FOR_AI_PIPELINE` | 40 | v2 AI 파이프라인 대상 |

---

## 3. 현재 구현 상태: 뭐가 되고 뭐가 안 되는가

### 되는 것 (실제 동작)

| 기능 | 상태 | 비고 |
|------|------|------|
| FDA 데이터 수집 + 파싱 | 동작 | openFDA API |
| EMA 데이터 수집 + 파싱 | 동작 | 2,655건, 4종 (의약품/희귀/부족/DHPC) |
| MFDS 데이터 수집 + 파싱 | 동작 | 공공데이터포털 API, 284,477건 |
| CRIS 임상시험 수집 + 파싱 | 동작 | 11,500건 |
| HIRA 보험인정기준 크롤링 | 동작 | Playwright |
| MOHW 행정예고 크롤링 | 동작 | Playwright |
| INN 기준 FDA+EMA+MFDS 병합 | 동작 | GlobalStatusBuilder |
| 핫이슈 스코어링 (0-100) | 동작 | HotIssueScorer |
| MFDS↔HIRA 성분명 브릿지 | 동작 | 75.7% 매칭률 |
| WHO ATC 코드 매칭 | 동작 | 6,440건 |
| 국내 영향 분석 (DomesticImpact) | 동작 | 8단계 분류 |
| v1 LLM 브리핑 생성 | 동작 | Claude/GPT, score>=40 |
| FastAPI REST API | 동작 | 14개 엔드포인트 |
| Cloud Run + PostgreSQL 배포 | 동작 | GCP |
| 일간 배치 파이프라인 | 동작 | APScheduler, 매일 08:00 |
| 점수 기반 필터링 | 동작 | 2/11 구현, 저점 약물 AI 제외 |

**테스트:** 89/89 통과 (v1 52 + v2 29 + 기타)

### 코드는 있지만 실 연동 안 된 것 (v2)

| 기능 | 상태 | 막혀있는 이유 |
|------|------|-------------|
| ASTI 시장 리포트 수집 | 코드 완성, 미테스트 | Playwright 실 테스트 필요 |
| Health.kr 전문가 리뷰 수집 | 코드 완성, 미테스트 | Playwright 실 테스트 필요 |
| bioRxiv 프리프린트 수집 | 코드 완성, 미테스트 | API 실 테스트 필요 |
| Gemini PDF 파서 | 코드 완성, 미테스트 | GEMINI_API_KEY 필요 |
| AI 3단 파이프라인 (o4-mini + GPT-5.2) | 코드 완성, 미테스트 | OPENAI_API_KEY 필요 |
| v2 DB 테이블 5개 | 스키마 정의됨, 데이터 없음 | 위 소스들이 돌아야 채워짐 |
| v2 API 엔드포인트 4개 | 코드 완성 | 데이터 없어서 빈 응답 |

### 아예 없는 것

| 기능 | 비고 |
|------|------|
| **이벤트 트리거 (변경 감지)** | 현재 가장 시급한 미구현 |
| Delta Analyzer (버전 비교) | 문서 수준 변경점 계산 |
| KR 조-항-호-목 파서 | 한국 법령 구조 파싱 |
| 개인화 (역할/기관별) | Phase 2 |
| ClinicalTrials.gov 연동 | CRIS 대안 |
| PMDA (일본) 연동 | 후순위 |

---

## 4. 현재 부딪힌 핵심 문제

### 문제 1: 카탈로그식 전수 발행 → 의미 없는 기사 양산

**증상:**
- 매일 파이프라인이 돌면 134개 약물 전부에 대해 기사를 만들려고 함
- MFDS-only OTC 같은 저점 약물은 데이터 자체가 없어서 "데이터 없음" 기사가 대부분
- AI API 비용만 낭비

**임시 조치 (2/11):**
- 점수 기반 필터링 상수화: score < 10은 DB 적재 차단, score < 40은 AI 파이프라인 제외
- 이걸로 저점 약물의 불필요한 AI 호출은 막음

**근본 해결 필요:**
- 점수 필터링만으로는 부족 — 점수 40 이상이라도 **아무 변화가 없으면** 매일 같은 기사를 쓸 이유 없음
- **이벤트 트리거(변경 감지)** 가 없으면 매일 동일한 약물에 동일한 AI 파이프라인을 태우게 됨

### 문제 2: 이벤트 트리거 미구현 (어제부터 고민 중)

**현재 흐름:**
```
매일 전수 스캔 → 점수 필터 → 점수 넘는 약물 전부 AI
```

**목표 흐름:**
```
매일 전수 스캔 → 변경 감지("이번에 뭐가 바뀌었나?") → 변경된 약물만 AI
```

**설계 선택지:**
1. `regulatory_events` 테이블에 `is_new` / `is_changed` 플래그 추가
2. `scan_snapshots` 비교 (이전 스냅샷 vs 현재 스냅샷 diff)
3. 별도 `change_log` / `event_queue` 테이블 신설

**고민 포인트:**
- "변경"의 기준이 뭔가? (새 승인? 상태 변경? 날짜 갱신?)
- 최초 수집 시 모든 게 "new"로 잡히는 문제
- 이벤트가 없는 날에도 뭔가 보여줘야 하는 니즈는 있는가?

### 문제 3: v2 소스들 실 연동이 안 됨

코드는 다 짜놨는데 실제로 돌려본 적이 없음:
- ASTI/Health.kr: Playwright 설치 + 실제 사이트 접근 테스트 필요
- bioRxiv: API 호출 테스트 필요
- Gemini PDF: API 키 필요
- AI 3단 파이프라인: OpenAI API 키 필요

이건 이벤트 트리거보다 후순위 — 트리거 없이 v2 소스를 켜봐야 매일 전수 호출하게 됨.

### 문제 4: AI 파이프라인 기준선 (40 vs 60)

- 원래 설계: score >= 60 (HIGH 이상만)
- 2/11 변경: score >= 40 (MID 포함)
- 40점이면 "FDA+EMA 동시승인" 수준이라 기사 가치는 있음
- 하지만 대상 약물 수가 늘어나면 API 비용 증가
- 이벤트 트리거 구현 후에 자연스럽게 해결될 문제이기도 함 (변경 있는 약물만 태우면 됨)

---

## 5. 다음 단계 우선순위

```
[1순위] 이벤트 트리거 설계 + 구현    ← 현재 막혀있는 핵심
   ↓
[2순위] v2 소스 실 연동 테스트       ← API 키 + Playwright
   ↓
[3순위] AI 3단 파이프라인 E2E        ← OpenAI 키 필요
   ↓
[4순위] 대시보드에 "이번 주 변경" 뷰
   ↓
[후순위] Delta Analyzer, KR 파서, 개인화
```

---

## 6. 기술 스택 요약

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 웹 프레임워크 | FastAPI |
| DB | PostgreSQL (프로덕션), SQLite+aiosqlite (로컬) |
| ORM | SQLAlchemy 2.x (async) |
| 크롤링 | httpx (API), Playwright (브라우저) |
| AI/LLM | OpenAI (o4-mini, GPT-5.2), Google Gemini, Anthropic Claude |
| 스케줄러 | APScheduler |
| 인프라 | GCP Cloud Run + Cloud SQL |
| 테스트 | pytest (89건 통과) |
| 설정 | pydantic-settings + .env |
