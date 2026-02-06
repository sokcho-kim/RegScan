# FastAPI 구현 계획

> 작성일: 2026-02-04

## 목적

메드클레임 서비스를 위한 규제 인텔리전스 API 제공

## 엔드포인트 설계

### 1. 대시보드용 API

```
GET /api/v1/stats
  → 전체 통계 (FDA/EMA/MFDS 건수, 핫이슈 수)

GET /api/v1/hot-issues
  → HOT/HIGH 등급 약물 목록

GET /api/v1/imminent
  → 국내 도입 임박 약물 (글로벌 승인 + MFDS 미허가 + CRIS 진행)
```

### 2. 약물 조회 API

```
GET /api/v1/drugs
  → 전체 약물 목록 (페이지네이션)

GET /api/v1/drugs/{inn}
  → 단일 약물 상세 (글로벌 현황 + HIRA 급여 + CRIS)

GET /api/v1/drugs/search?q={query}
  → 약물 검색
```

### 3. 브리핑 리포트 API

```
GET /api/v1/report/{inn}
  → 단일 약물 브리핑 데이터 (리포트 렌더링용)

POST /api/v1/report/{inn}/generate
  → LLM 기반 브리핑 생성 (Phase 2)
```

### 4. 메드클레임 시사점 API

```
GET /api/v1/drugs/{inn}/medclaim
  → 급여/비급여 현황
  → 예상 약가
  → 청구 관련 시사점
```

## 데이터 흐름

```
[JSON 파일]
    ↓
[FastAPI 시작 시 로드]
    ↓
[GlobalRegulatoryStatus + DomesticImpact 생성]
    ↓
[메모리 캐시]
    ↓
[API 응답]
```

## 파일 구조

```
regscan/
├── api/
│   ├── __init__.py
│   ├── main.py           # FastAPI app
│   ├── routes/
│   │   ├── stats.py      # /stats, /hot-issues
│   │   ├── drugs.py      # /drugs
│   │   └── report.py     # /report
│   ├── schemas.py        # Pydantic 모델
│   └── deps.py           # 의존성 (데이터 로더)
```

## 구현 순서

1. FastAPI 기본 구조 + 데이터 로딩
2. /stats, /hot-issues 엔드포인트
3. /drugs 엔드포인트
4. /report 엔드포인트
5. 테스트 및 문서화
