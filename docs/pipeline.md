# RegScan 파이프라인 구조

> 최종 수정: 2026-01-29

---

## 전체 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                         데이터 소스                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │  HIRA   │ │  MOHW   │ │   FDA   │ │   EMA   │  ...         │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘              │
│       │           │           │           │                     │
└───────┼───────────┼───────────┼───────────┼─────────────────────┘
        │           │           │           │
        ▼           ▼           ▼           ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. INGEST (수집)                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  BaseIngestor                                            │   │
│  │  - HIRANoticeIngestor                                    │   │
│  │  - MOHWAdminNoticeIngestor                               │   │
│  │  - FDAApprovalIngestor                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│                    raw_data: dict[str, Any]                     │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. SCAN (Signal 생성)                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SignalGenerator                                         │   │
│  │  - 제목/요약 추출                                         │   │
│  │  - change_type 감지                                       │   │
│  │  - domain 분류                                            │   │
│  │  - impact_level 평가                                      │   │
│  │  - why_it_matters 생성 (LLM)                              │   │
│  │  - Citation 메타데이터 구성                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│                         FeedCard                                 │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. STORE (저장)                                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  - data/normalized/cards/                                │   │
│  │  - JSON 형태로 저장                                       │   │
│  │  - 날짜별 파티셔닝                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. SERVE (API)                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  GET /api/feed/cards                                     │   │
│  │  GET /api/feed/today                                     │   │
│  │  GET /api/feed/cards/{id}                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│                    MedClaim 메인화면                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 단계별 상세

### 1. Ingest (수집)

**책임**: 원본 데이터 가져오기

```python
# regscan/ingest/base.py
class BaseIngestor(ABC):
    async def fetch(self) -> list[dict[str, Any]]:
        """원본 데이터 수집"""
        pass
```

**구현체**:
- `HIRANoticeIngestor` - 심평원 공지
- `HIRAGuidelineIngestor` - 심사지침
- `MOHWNoticeIngestor` - 복지부 고시
- `MOHWAdminNoticeIngestor` - 행정예고
- `FDAApprovalIngestor` - FDA 승인
- `FDAGuidanceIngestor` - FDA 가이드라인

---

### 2. Scan (Signal 생성)

**책임**: 원본 → FeedCard 변환

```python
# regscan/scan/signal_generator.py
class SignalGenerator:
    def generate(self, raw_data: dict, source_type: SourceType) -> FeedCard:
        """원본 데이터를 FeedCard로 변환"""
        pass
```

**주요 로직**:
| 필드 | 생성 방법 |
|------|----------|
| `title` | 원문 제목 추출 (50자 제한) |
| `summary` | 원문 요약 (100자 제한) |
| `why_it_matters` | LLM 생성 또는 템플릿 |
| `change_type` | 키워드 기반 감지 |
| `domain` | 분류 모델 또는 규칙 |
| `impact_level` | 규칙 기반 평가 |

---

### 3. Store (저장)

**저장 구조**:
```
data/
├── raw/                    # 원본 데이터
│   ├── hira/
│   ├── mohw/
│   └── fda/
│
└── normalized/             # 정규화된 FeedCard
    └── cards/
        ├── 2026-01-29/
        │   ├── card-20260129-001.json
        │   └── card-20260129-002.json
        └── 2026-01-30/
```

---

### 4. Serve (API)

**엔드포인트**:

| 메서드 | 경로 | 설명 |
|-------|------|------|
| GET | `/api/feed/cards` | 카드 목록 조회 |
| GET | `/api/feed/cards/{id}` | 카드 상세 |
| GET | `/api/feed/today` | 오늘의 변경사항 |

**쿼리 파라미터**:
- `limit` - 개수 제한
- `domain` - 도메인 필터
- `impact_level` - 영향도 필터
- `source_type` - 소스 필터

---

## 실행 흐름 예시

```python
import asyncio
from regscan.ingest.fda import FDAApprovalIngestor
from regscan.scan import SignalGenerator
from regscan.models import SourceType

async def main():
    # 1. 수집
    async with FDAApprovalIngestor() as ingestor:
        raw_items = await ingestor.fetch()

    # 2. 변환
    generator = SignalGenerator()
    cards = [
        generator.generate(item, SourceType.FDA_APPROVAL)
        for item in raw_items
    ]

    # 3. 저장
    for card in cards:
        save_card(card)

    # 4. API에서 제공
    # ...

asyncio.run(main())
```

---

## Phase 구분

### Phase 1 (현재)

```
Ingest → Scan → Store → Serve
```

- 기본 수집 파이프라인
- FeedCard 생성
- API 제공

### Phase 2

```
Ingest → Parse → Scan → Map → Personalize → Report
```

- Parse: 문서 구조 상세 분석
- Map: 글로벌 → 한국 제도 연결
- Personalize: 역할/기관별 맞춤
- Report: 리포트 자동 생성
