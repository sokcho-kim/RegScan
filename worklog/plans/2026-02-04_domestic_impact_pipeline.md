# 국내 영향 분석 파이프라인 설계

> 작성일: 2026-02-04
> 상태: 계획 단계

## 배경

### 현재 상태
```
글로벌 동향 ✅
├── FDA: 1,462건 (NDA/BLA)
├── EMA: 2,655건 (Medicines)
├── WHO ATC: 6,440건
└── GlobalRegulatoryStatus: 2,569건 (FDA+EMA 병합)
    ├── HIGH: 3건
    ├── MID: 76건
    └── 다중승인: 347건

국내 영향 ❌
├── MFDS 허가: 없음 (GlobalRegulatoryStatus.mfds = None)
├── CRIS 임상: 없음
├── HIRA 급여목록: 없음 (공지/인정기준만 있음)
└── KIPRIS 특허: 없음
```

### 해결 과제
- "글로벌 승인 → 국내 영향" 분석에 **근거**가 필요
- 예측이 아닌 **팩트 기반** 판단

---

## 목표 파이프라인

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RegScan Pipeline                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [수집 레이어]                                                        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐              │
│  │ FDA  │ │ EMA  │ │ MFDS │ │ CRIS │ │ HIRA │ │KIPRIS│              │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘              │
│     │        │        │        │        │        │                   │
│     ▼        ▼        ▼        ▼        ▼        ▼                   │
│  ┌─────────────────────────────────────────────────────┐            │
│  │                   정규화 레이어                       │            │
│  │  - INN 기준 매칭                                     │            │
│  │  - 성분명 정규화 (IngredientMatcher)                  │            │
│  │  - ATC 코드 부여                                     │            │
│  └─────────────────────────────────────────────────────┘            │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────┐            │
│  │              GlobalRegulatoryStatus                  │            │
│  │  ┌─────┬─────┬─────┬─────┬─────┬─────┐              │            │
│  │  │ FDA │ EMA │ MFDS│ CRIS│ HIRA│KIPRS│              │            │
│  │  └─────┴─────┴─────┴─────┴─────┴─────┘              │            │
│  └─────────────────────────────────────────────────────┘            │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────┐            │
│  │                분석 레이어                            │            │
│  │  - HotIssueScorer (글로벌 중요도)                    │            │
│  │  - DomesticImpactAnalyzer (국내 영향) ← NEW          │            │
│  │  - TimelinePredictor (도입 시점 예측) ← NEW          │            │
│  └─────────────────────────────────────────────────────┘            │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────┐            │
│  │                출력 레이어                            │            │
│  │  - FeedCard (알림)                                   │            │
│  │  - Report (리포트)                                   │            │
│  │  - API (FastAPI)                                    │            │
│  └─────────────────────────────────────────────────────┘            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 국내 영향 판단 로직

### Case 정의

| Case | 조건 | 판단 | 근거 |
|------|------|------|------|
| 1 | FDA/EMA 승인 + MFDS 미허가 + CRIS 임상 진행 | **국내 도입 임박** | CRIS 데이터 |
| 2 | FDA/EMA 승인 + MFDS 허가 + HIRA 미급여 | **급여 논의 예상** | 허가-급여 갭 |
| 3 | FDA/EMA 승인 + MFDS 미허가 + CRIS 없음 | **국내 도입 불투명** | 임상 미진행 |
| 4 | MFDS 허가 + KIPRIS 특허 만료 임박 | **제네릭/바시 진입 예상** | 특허 만료일 |
| 5 | FDA/EMA 승인 + 과거 유사 약제 패턴 분석 | **평균 N개월 소요 예상** | 히스토리 |

### DomesticImpactLevel (신규 Enum)

```python
class DomesticImpactLevel(str, Enum):
    IMMINENT = "imminent"           # 국내 도입 임박
    EXPECTED = "expected"           # 급여/허가 논의 예상
    UNCERTAIN = "uncertain"         # 국내 도입 불투명
    GENERIC_ENTRY = "generic_entry" # 제네릭 진입 예상
    ALREADY_AVAILABLE = "available" # 이미 국내 가용
```

---

## Phase 1: MFDS 허가 현황 연동

### 데이터 소스 조사

| 소스 | URL | 데이터 | 접근 방식 |
|------|-----|--------|----------|
| 의약품안전나라 | nedrug.mfds.go.kr | 허가 품목 | API/스크래핑 |
| 공공데이터포털 | data.go.kr | MFDS 데이터 | 공공 API |
| 식약처 공개 DB | mfds.go.kr | 승인 현황 | 스크래핑 |

### 필요 데이터 필드

```python
@dataclass
class MFDSApproval:
    item_seq: str              # 품목기준코드
    item_name: str             # 품목명
    entp_name: str             # 업체명
    item_permit_date: date     # 허가일
    etc_otc_code: str          # 전문/일반
    class_no: str              # 분류번호
    main_ingr: str             # 주성분 (INN 매칭용)
    permit_kind: str           # 허가구분 (신약/제네릭/바시)
    # 특수 지정
    is_orphan: bool            # 희귀의약품
    is_expedited: bool         # 신속심사
```

### 구현 태스크

- [ ] 1.1 MFDS API 엔드포인트 조사
- [ ] 1.2 `regscan/ingest/mfds.py` - MFDS 수집기
- [ ] 1.3 `regscan/parse/mfds_parser.py` - MFDS 파서
- [ ] 1.4 GlobalStatusBuilder에 MFDS 통합
- [ ] 1.5 INN ↔ 주성분 매칭 로직

---

## Phase 2: CRIS 임상시험 연동

### 데이터 소스

| 소스 | URL | 데이터 |
|------|-----|--------|
| CRIS | cris.nih.go.kr | 국내 임상시험 등록 현황 |

### 필요 데이터 필드

```python
@dataclass
class ClinicalTrial:
    trial_id: str              # 임상시험 등록번호
    title: str                 # 제목
    drug_name: str             # 시험약
    sponsor: str               # 의뢰자
    phase: str                 # Phase I/II/III/IV
    status: str                # 진행/완료/중단
    start_date: date           # 시작일
    target_size: int           # 목표 피험자 수
    indication: str            # 적응증
```

### 구현 태스크

- [ ] 2.1 CRIS 사이트 구조 분석
- [ ] 2.2 `regscan/ingest/cris.py` - CRIS 수집기 (Playwright)
- [ ] 2.3 `regscan/parse/cris_parser.py` - CRIS 파서
- [ ] 2.4 약물명 ↔ INN 매칭

---

## Phase 3: HIRA 급여목록 보강

### 현재 상태
- ✅ 공지사항, 인정기준 크롤링 구현됨
- ❌ 급여 품목 목록 (약가) 없음

### 필요 데이터

```python
@dataclass
class HIRAReimbursement:
    item_code: str             # 약가코드
    item_name: str             # 품목명
    main_ingr: str             # 주성분
    reimbursement_date: date   # 급여 적용일
    price: int                 # 약가
    is_listed: bool            # 등재 여부
```

### 구현 태스크

- [ ] 3.1 HIRA 약가 API/데이터 소스 조사
- [ ] 3.2 `regscan/ingest/hira.py` 확장 - 급여목록 수집
- [ ] 3.3 MFDS 허가 ↔ HIRA 급여 매핑

---

## Phase 4: 통합 분석기

### DomesticImpactAnalyzer

```python
class DomesticImpactAnalyzer:
    """국내 영향 분석기"""

    def analyze(self, status: GlobalRegulatoryStatus) -> DomesticImpact:
        """
        글로벌 현황 + 국내 데이터로 국내 영향 분석
        """
        # Case 판단 로직
        if self._has_global_approval(status) and not self._has_mfds(status):
            if self._has_active_trial(status):
                return DomesticImpact(
                    level=DomesticImpactLevel.IMMINENT,
                    reason="국내 임상시험 진행 중",
                    evidence={"cris_trial_id": "..."}
                )
            else:
                return DomesticImpact(
                    level=DomesticImpactLevel.UNCERTAIN,
                    reason="국내 임상 미진행",
                    evidence={}
                )
        # ... 기타 케이스
```

### 구현 태스크

- [ ] 4.1 `regscan/analyze/domestic_impact.py` 구현
- [ ] 4.2 GlobalRegulatoryStatus 확장 (CRIS, HIRA 필드)
- [ ] 4.3 리포트에 국내 영향 섹션 추가

---

## 일정

### Week 6 (02-03 ~ 02-07)

| 일 | 태스크 |
|----|--------|
| 02-04 | MFDS API 조사, CRIS 구조 분석 |
| 02-05 | MFDS 수집기 구현 |
| 02-06 | CRIS 수집기 구현 |
| 02-07 | GlobalStatus 통합, 테스트 |

### Week 7 (02-10 ~ 02-14)

| 일 | 태스크 |
|----|--------|
| 02-10 | HIRA 급여목록 수집 |
| 02-11 | DomesticImpactAnalyzer 구현 |
| 02-12 | 통합 리포트 생성 |
| 02-13 | 스케줄러 연동 |
| 02-14 | E2E 테스트, 문서화 |

---

## 성공 지표

1. **데이터 커버리지**
   - MFDS 허가 품목 > 10,000건 수집
   - CRIS 진행 중 임상 > 1,000건 수집

2. **매칭률**
   - FDA/EMA → MFDS INN 매칭률 > 80%
   - 글로벌 신약 중 국내 임상 진행 식별 > 50%

3. **분석 품질**
   - 국내 도입 임박 판단 정확도 > 90%
   - 근거 없는 예측 0건

---

## 기술 고려사항

### 파이프라인 아키텍처

```python
# 추상 베이스 클래스
class PipelineStep(ABC):
    @abstractmethod
    async def process(self, data: Any) -> Any:
        pass

# 파이프라인 구성
pipeline = Pipeline([
    CollectStep([FDACollector, EMACollector, MFDSCollector, CRISCollector]),
    NormalizeStep(IngredientMatcher),
    MergeStep(GlobalStatusBuilder),
    AnalyzeStep([HotIssueScorer, DomesticImpactAnalyzer]),
    OutputStep([FeedCardGenerator, ReportGenerator]),
])

# 실행
await pipeline.run()
```

### 스케줄러 통합

```python
# Airflow DAG 또는 간단한 cron
schedule:
  daily:
    - collect_fda
    - collect_ema
    - collect_mfds
    - merge_global_status
    - analyze
    - generate_report
```

---

## 메모

- MFDS nedrug.mfds.go.kr는 공공데이터포털 API가 더 안정적일 수 있음
- CRIS는 Playwright 필요 (JavaScript 렌더링)
- 특허(KIPRIS)는 Phase 2 이후로 미룸 (복잡도 높음)
