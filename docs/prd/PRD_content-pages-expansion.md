# RegScan 콘텐츠 페이지 확장 PRD

> **Version**: 1.0
> **Created**: 2026-05-12
> **Status**: Draft
> **Scale Grade**: Startup (DAU < 10,000)

## 1. Overview

### 1.1 Problem Statement

RegScan은 13+ 데이터 소스에서 매일 100건 이상의 규제/약물/산업 시그널을 수집하지만, 프론트엔드에 표출되는 콘텐츠는 **주 1-2회 기사**와 **더미 데이터 MedicinePage**뿐이다. 수집 데이터 대비 콘텐츠 활용률이 극히 낮아 사용자에게 전달되는 가치가 제한적.

회사 DNA(FiscalNote 영감 리걸테크)에 맞는 **규제 트래킹 + 산업 인텔리전스** 콘텐츠가 부재.

### 1.2 Goals

- 매일 업데이트되는 카드형 콘텐츠 7종으로 일일 콘텐츠 볼륨 확보
- FiscalNote 모델의 규제 변경 트래킹 카드 구현
- 기사 파이프라인의 입력 데이터로 팩트카드 재활용 → 기사 품질 향상
- MedicinePage를 실데이터로 전환

### 1.3 Non-Goals (Out of Scope)

- 사용자 커스텀 알림/구독 (Phase 2 이후)
- 유료 결제/구독 모델
- 모바일 앱 (웹 반응형으로 대응)
- 실시간 WebSocket 푸시 (polling으로 충분)

### 1.4 Scope

| 포함 | 제외 |
|------|------|
| 팩트카드 7종 백엔드 파이프라인 | 사용자 알림 시스템 |
| 팩트카드 API (RegScan + Backend 프록시) | 결제/구독 |
| 프론트엔드 카드 리스트/상세 페이지 | 모바일 네이티브 앱 |
| 대시보드 통합 Feed | 관리자 콘텐츠 편집 UI |
| MedicinePage 실데이터 연동 | AI 챗봇 연동 |

---

## 2. User Stories

### 2.1 Primary Users

- **병원 약제팀장**: 매일 아침 규제 변경과 신약 동향을 5분 안에 스캔하고 싶다
- **제약사 RA 담당자**: 글로벌 인허가 변경이 국내에 어떤 영향을 주는지 빠르게 파악하고 싶다
- **제약사 BD 담당자**: 라이선스 딜, 특허 출원 동향을 놓치지 않고 싶다

### 2.2 Acceptance Criteria (Gherkin)

```
Scenario: 약제팀장이 규제 변경 카드를 확인한다
  Given 이번 주 고시 개정이 2건 수집됐다
  When 사용자가 규제 변경 페이지에 접속한다
  Then 변경 전/후 비교가 포함된 카드 2장이 보인다
  And 각 카드에 시행일과 영향 대상이 명시돼 있다

Scenario: RA 담당자가 대시보드 피드를 확인한다
  Given 오늘 규제카드 3건, 신약카드 2건, 특허카드 1건이 생성됐다
  When 사용자가 대시보드에 접속한다
  Then 전체 카드가 시간순으로 피드에 노출된다
  And 카드 유형별 필터링이 가능하다

Scenario: 사용자가 공모전/행사 정보를 확인한다
  Given MFDS에서 컨설팅 모집 공고가 수집됐다
  When 사용자가 행사/공고 페이지에 접속한다
  Then 신청 기한, 대상, 링크가 포함된 카드가 보인다
```

---

## 3. Functional Requirements

### 3.1 팩트카드 유형 정의

| ID | 카드 유형 | 데이터 소스 | 업데이트 주기 | Priority |
|----|----------|-----------|-------------|----------|
| FR-001 | **규제 변경 카드** | ASSEMBLY_BILL, MOHW, MFDS, KHIDI 법령·고시 | 매일 | P0 |
| FR-002 | **신약 카드** | FDA, EMA, MFDS, PMDA 승인 | 수시 | P0 |
| FR-003 | **공모전/교육/행사 카드** | MFDS, KHIDI 공고/행사 | 수시 | P0 |
| FR-004 | **특허 동향 카드** | KIPRIS | 주간 | P1 |
| FR-005 | **임상시험 현황 카드** | KHIDI 임상·비임상, CT.gov, CRIS | 주간 | P1 |
| FR-006 | **산업 보고서 카드** | KHIDI 보고서, 전문가 Insight | 월간 | P1 |
| FR-007 | **약가/급여 변경 카드** | HIRA, MOHW 건보정책 | 수시 | P1 |

### 3.2 팩트카드 공통 기능

| ID | Requirement | Priority | Dependencies |
|----|------------|----------|--------------|
| FR-010 | 카드 생성 파이프라인 (시그널 → 구조화 JSON → DB) | P0 | - |
| FR-011 | 카드 리스트 API (필터/정렬/페이지네이션) | P0 | FR-010 |
| FR-012 | 카드 상세 API | P0 | FR-010 |
| FR-013 | 대시보드 통합 Feed API (전체 카드 시간순) | P0 | FR-011 |
| FR-014 | 카드 유형별 프론트 리스트 페이지 | P0 | FR-011 |
| FR-015 | 카드 유형별 필터 탭 | P1 | FR-014 |
| FR-016 | 기사 파이프라인에서 팩트카드 참조 | P1 | FR-010 |

### 3.3 페이지 구성

| ID | 페이지 | URL | 설명 | Priority |
|----|--------|-----|------|----------|
| FR-020 | 대시보드 Feed | `/` or `/dashboard` | 전체 카드 통합 피드 (시간순) | P0 |
| FR-021 | 규제 트래커 | `/regulation` | 규제 변경 카드 타임라인 | P0 |
| FR-022 | 신약 도입정보 | `/medicine` (기존) | 실데이터 연동 | P0 |
| FR-023 | 공고/행사 | `/events` | 공모전/교육/행사 일정 | P0 |
| FR-024 | 특허 동향 | `/patents` | 특허 출원 요약 | P1 |
| FR-025 | 임상시험 | `/clinical-trials` | 주간 임상 현황 | P1 |
| FR-026 | 보고서/리서치 | `/reports` | 산업 보고서 링크 | P1 |

---

## 4. Non-Functional Requirements

### 4.0 Scale Grade: Startup

| 항목 | 값 |
|------|-----|
| 예상 DAU | 100-1,000 |
| 피크 동시접속 | ~100 |
| 데이터량 | 1-5GB (카드 + 기사 + 메타데이터) |

### 4.1 Performance SLA

| 지표 | 목표값 |
|------|--------|
| 카드 리스트 API (p95) | < 500ms |
| 카드 상세 API (p95) | < 300ms |
| 대시보드 Feed (p95) | < 500ms |
| 카드 생성 파이프라인 | < 5min/배치 |

### 4.2 Availability SLA

| 등급 | Uptime | 허용 다운타임(월) |
|------|--------|-----------------|
| Startup | 99% | 7.3시간 |

### 4.3 Data Requirements

| 항목 | 값 |
|------|-----|
| 일일 카드 생성량 | 10-50건 |
| 카드 보존 기간 | 1년 |
| 월간 데이터 증가 | ~50MB |

### 4.5 Security

- Authentication: Required (기존 JWT)
- 공개 카드 없음 (로그인 필수)
- API Rate Limit: 기존 600 req/min 유지

---

## 5. Technical Design

### 5.1 팩트카드 스키마

```json
{
  "id": "fc_uuid",
  "card_type": "regulation_change | drug_approval | event_notice | patent_filing | clinical_update | industry_report | reimbursement_change",
  "title": "급여 상한금액표 일부개정 고시 제2026-91호",
  "summary": "항암제 3종 급여 적응증 확대",
  "source": "보건복지부",
  "source_type": "MFDS_PRESS",
  "source_url": "https://...",
  "date": "2026-05-01",
  "created_at": "2026-05-01T09:00:00Z",
  
  "metadata": {
    // regulation_change
    "before": "A약제 2차 치료 이후 급여",
    "after": "A약제 1차 치료까지 확대",
    "effective_date": "2026-05-01",
    "affected_drugs": ["pembrolizumab"],
    "affected_entities": ["종합병원 약제팀"],
    "deadline": "의견조회 5/20 종료",
    
    // drug_approval
    "drug_name": "Otarmeni",
    "inn": "...",
    "indication": "...",
    "agency": "FDA",
    "korea_status": "미허가",
    
    // event_notice
    "event_type": "공모전 | 교육 | 행사 | 컨설팅",
    "apply_start": "2026-05-11",
    "apply_end": "2026-06-07",
    "target": "중소제약사 9곳",
    
    // patent_filing
    "applicant": "리제너론",
    "patent_title": "항-PD-1+CD20/CD3 조합",
    "target_molecule": "PD-1",
    "reference_drug": "PEMBROLIZUMAB",
    
    // clinical_update
    "region": "US | KR | CN | JP | EU",
    "phase": "Phase 3",
    "new_trials_count": 59,
    "monitoring_period": "2026.04.27~05.03",
    
    // industry_report
    "publisher": "한국바이오의약품협회",
    "report_type": "시장분석 | R&D | 정책",
    "market_size": "41억 달러",
    "growth_rate": "12.4%",
    
    // reimbursement_change
    "hira_code": "...",
    "price_before": 50000,
    "price_after": 45000,
    "category": "항암제"
  },
  
  "tags": ["급여확대", "항암제", "고시개정"],
  "impact_score": 8,
  "related_article_ids": [],
  "related_card_ids": []
}
```

### 5.2 Database Schema (RegScan)

```sql
CREATE TABLE fact_cards (
    id TEXT PRIMARY KEY,                -- fc_uuid
    card_type TEXT NOT NULL,            -- enum: 7 types
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT,                        -- 발표 기관
    source_type TEXT,                   -- MFDS_PRESS, ASSEMBLY_BILL, etc.
    source_url TEXT,
    date DATE,                          -- 원본 날짜
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB,                     -- 카드 유형별 상세
    tags TEXT[],                        -- 태그 배열
    impact_score INTEGER DEFAULT 5,     -- 1-10
    related_article_ids TEXT[],
    related_card_ids TEXT[]
);

CREATE INDEX idx_fact_cards_type ON fact_cards(card_type);
CREATE INDEX idx_fact_cards_date ON fact_cards(date DESC);
CREATE INDEX idx_fact_cards_source_type ON fact_cards(source_type);
CREATE INDEX idx_fact_cards_tags ON fact_cards USING GIN(tags);
```

### 5.3 API Specification

#### `GET /api/v1/fact-cards`

**Description**: 팩트카드 리스트 조회

**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| card_type | string | No | 카드 유형 필터 (comma-separated) |
| since | date | No | 이 날짜 이후 카드만 |
| limit | int | No | default 20, max 100 |
| offset | int | No | default 0 |
| q | string | No | 제목/요약 검색 |
| tags | string | No | 태그 필터 (comma-separated) |

**Response 200**:
```json
{
  "cards": [
    {
      "id": "fc_abc123",
      "card_type": "regulation_change",
      "title": "...",
      "summary": "...",
      "source": "보건복지부",
      "date": "2026-05-01",
      "tags": ["급여확대"],
      "impact_score": 8,
      "metadata": { ... }
    }
  ],
  "total_count": 42,
  "offset": 0,
  "limit": 20
}
```

#### `GET /api/v1/fact-cards/{id}`

**Description**: 팩트카드 상세

#### `GET /api/v1/fact-cards/feed`

**Description**: 대시보드 통합 피드 (전체 카드 + 기사 시간순)

**Query Parameters**:
| Param | Type | Description |
|-------|------|-------------|
| limit | int | default 30 |
| since | date | 기준 날짜 |
| card_types | string | 유형 필터 (comma-separated) |

**Response 200**:
```json
{
  "items": [
    {
      "item_type": "fact_card",
      "id": "fc_abc123",
      "card_type": "regulation_change",
      "title": "...",
      "date": "2026-05-01",
      "impact_score": 8
    },
    {
      "item_type": "article",
      "id": "art_xyz789",
      "headline": "...",
      "date": "2026-05-01",
      "grade": "A"
    }
  ],
  "total_count": 55
}
```

### 5.4 Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Frontend (React + Vite)                                  │
│                                                          │
│  /dashboard  /regulation  /medicine  /events  /patents   │
│       ↕           ↕          ↕         ↕         ↕       │
│  apiClient (Axios + JWT)                                 │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Backend (Express + TS)                                   │
│                                                          │
│  /api/v1/fact-cards    → factCardService (Redis 15min)   │
│  /api/v1/fact-cards/feed → feedService (Redis 10min)     │
│  /api/v1/drugs         → drugService (Redis 30min)       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ RegScan API (FastAPI)                                    │
│                                                          │
│  /api/v1/fact-cards    → fact_cards 테이블               │
│  /api/v1/drugs/cards   → drugs + regulatory_events       │
│                                                          │
│  팩트카드 생성 파이프라인:                                 │
│  시그널 → LLM 팩트 추출 → 검증 → DB 저장                 │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Data Layer                                               │
│  PostgreSQL/SQLite: fact_cards, drugs, articles           │
│  Redis: API 캐시                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Implementation Phases

### Phase 1: 팩트카드 백엔드 (MVP)
- [ ] fact_cards DB 테이블 생성
- [ ] 팩트카드 생성 파이프라인 (시그널 → 구조화 JSON → DB)
- [ ] RegScan API 엔드포인트 (/fact-cards, /fact-cards/{id}, /fact-cards/feed)
- [ ] Backend 프록시 + Redis 캐시

**Deliverable**: API에서 팩트카드 조회 가능

### Phase 2: 프론트엔드 카드 페이지
- [ ] 대시보드 Feed 페이지 (통합 타임라인)
- [ ] 규제 트래커 페이지 (regulation_change 카드)
- [ ] 공고/행사 페이지 (event_notice 카드)
- [ ] MedicinePage 실데이터 연동

**Deliverable**: 사용자가 카드를 브라우저에서 확인 가능

### Phase 3: 기사 연동 + 추가 카드 유형
- [ ] 기사 파이프라인에서 팩트카드 참조 데이터 활용
- [ ] 특허/임상/보고서/약가 카드 유형 추가
- [ ] 카드 ↔ 기사 연결 (related_article_ids)

**Deliverable**: 기사 품질 향상 + 전체 7종 카드

### Phase 4: 고도화
- [ ] 카드 태그 기반 관련 카드 추천
- [ ] 약물별/규제별 타임라인 뷰
- [ ] 주간/월간 자동 리포트 생성

**Deliverable**: 규제 트래킹 플랫폼 완성

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| 일일 카드 생성량 | 10건+ | DB 카운트 |
| 대시보드 DAU | 50+ (론칭 1개월) | 로그인 + 페이지뷰 |
| 카드 → 기사 참조율 | 80%+ | 기사 내 팩트카드 ID 포함 비율 |
| 기사 내 "뻔한 소리" 비율 | 0% | 가드레일 삭제 문장 수 |
| 콘텐츠 업데이트 주기 | 매일 | 파이프라인 실행 기록 |
