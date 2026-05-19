# Task Plan: Content Pages Expansion

> **Generated from**: docs/prd/PRD_content-pages-expansion.md
> **Created**: 2026-05-12
> **Status**: pending

## Execution Config

| Option | Value | Description |
|--------|-------|-------------|
| `auto_commit` | true | 완료 시 자동 커밋 |
| `commit_per_phase` | true | Phase별 중간 커밋 |
| `quality_gate` | true | /auto-commit 품질 검사 |

## Phases

### Phase 1: 팩트카드 백엔드 MVP
- [ ] fact_cards DB 테이블 + SQLAlchemy 모델 (`regscan/db/models.py`)
- [ ] 팩트카드 생성 파이프라인 (`regscan/factcard/pipeline.py` 신규)
  - [ ] 시그널 → LLM 팩트 추출 프롬프트
  - [ ] 카드 유형별 검증 (필수 필드 체크)
  - [ ] DB 저장
- [ ] RegScan API 엔드포인트 (`regscan/api/routes/fact_cards.py` 신규)
  - [ ] GET /api/v1/fact-cards (리스트 + 필터)
  - [ ] GET /api/v1/fact-cards/{id} (상세)
  - [ ] GET /api/v1/fact-cards/feed (통합 피드)
- [ ] Backend Express 프록시 (`ai-rag-server-backend-ts/src/routes/fact-cards.ts` 신규)
  - [ ] Redis 캐시 (15min)

### Phase 2: 프론트엔드 카드 페이지
- [ ] 대시보드 Feed 페이지 (`/dashboard`)
- [ ] 규제 트래커 페이지 (`/regulation`)
- [ ] 공고/행사 페이지 (`/events`)
- [ ] MedicinePage 실데이터 연동 (`/medicine`)
- [ ] API 서비스 모듈 (`src/apis/factCards.ts` 신규)

### Phase 3: 기사 연동 + 추가 카드
- [ ] 기사 파이프라인에서 팩트카드 참조
- [ ] 특허/임상/보고서/약가 카드 유형 추가
- [ ] 카드 ↔ 기사 연결

### Phase 4: 고도화
- [ ] 태그 기반 관련 카드 추천
- [ ] 약물별/규제별 타임라인 뷰
- [ ] 주간 자동 리포트

## Progress

| Metric | Value |
|--------|-------|
| Total Tasks | 0/18 |
| Current Phase | - |
| Status | pending |
