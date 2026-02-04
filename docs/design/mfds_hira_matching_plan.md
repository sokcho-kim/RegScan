# MFDS ↔ HIRA 매칭 계획서

> 작성일: 2026-02-04
> 목적: 글로벌 규제 현황(MFDS)과 국내 보험 급여(HIRA) 연결

---

## 1. 배경

### 1.1 문제점 (1차 시도 실패)

| 시도 | 결과 | 원인 |
|------|------|------|
| 품목코드 직접 매칭 | 0건 | MFDS ITEM_SEQ ≠ HIRA 품목코드 (체계 상이) |
| 품목명 정규화 | 26,413건 | 신뢰도 낮음 (오탈자, 표기 차이) |
| 브랜드명 매칭 | 19,659건 | 신뢰도 낮음 |

### 1.2 해결 방안

**브릿지 테이블 활용**: ATC 코드 매핑 데이터를 통해 `주성분코드(ingredient_code)`와 `INN(국제일반명)` 연결

---

## 2. 데이터 현황

### 2.1 보유 데이터

| 파일 | 위치 | 건수 | 핵심 필드 |
|------|------|------|----------|
| MFDS 허가정보 | `data/mfds/permits_full_20260203.json` | 44,035 | ITEM_INGR_NAME (INN) |
| HIRA 적용약가 | `data/hira/drug_prices_20260204.json` | 59,004 | ingredient_code |
| **ATC 매핑** | `data/bridge/건강보험심사평가원_ATC코드_매핑_목록_20250630.csv` | 21,953 | 주성분코드, ATC코드 명칭 |
| 통합 사전 | `data/bridge/drug_dictionary_normalized.json` | 91,706 | 참고용 |

### 2.2 ATC 매핑 데이터 구조

```
약제분류 | 주성분코드 | 제품코드 | 제품명 | 업체명 | ATC코드 | ATC코드 명칭
112     | 130830ASY | 645302132 | 렉탄시럽 | 한림제약 | N05CC01 | chloral hydrate
```

**핵심 필드:**
- `주성분코드` (8자리): HIRA ingredient_code와 동일
- `ATC코드 명칭`: 영문 INN (국제일반명)

### 2.3 데이터 통계

| 항목 | 건수 |
|------|------|
| ATC 매핑 전체 | 21,953 |
| 고유 주성분코드 | 4,415 |
| 고유 ATC명칭 (INN) | 1,385 |
| HIRA 고유 ingredient_code | 9,002 |
| MFDS 고유 성분명 | 3,922 |

---

## 3. 매칭 전략

### 3.1 매칭 흐름

```
┌─────────────────────────────────────────────────────────────┐
│  MFDS                                                        │
│  ITEM_INGR_NAME: "Pembrolizumab"                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ INN 정규화
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Bridge (ATC 매핑)                                           │
│  ATC코드 명칭: "pembrolizumab" → 주성분코드: "XXXXXXXX"      │
└──────────────────────┬──────────────────────────────────────┘
                       │ ingredient_code
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  HIRA                                                        │
│  ingredient_code: "XXXXXXXX" → 급여여부: "급여"              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 매칭 우선순위

| 우선순위 | 방식 | 설명 |
|---------|------|------|
| 1 | INN 정확 매칭 | MFDS 성분명 = ATC명칭 (정규화 후) |
| 2 | INN 부분 매칭 | 첫 번째 성분 기준 (조합제) |
| 3 | 품목코드 매칭 | MFDS ITEM_SEQ ↔ ATC 제품코드 (Fallback) |

### 3.3 INN 정규화 규칙

```python
def normalize_inn(name: str) -> str:
    """INN 정규화"""
    if not name:
        return ""

    # 1. 소문자 변환
    name = name.lower()

    # 2. 염 형태 제거 (hydrochloride, sodium, etc.)
    salts = ['hydrochloride', 'sodium', 'potassium', 'sulfate',
             'acetate', 'maleate', 'fumarate', 'citrate']
    for salt in salts:
        name = name.replace(salt, '')

    # 3. 특수문자/공백 제거
    name = re.sub(r'[^a-z]', '', name)

    return name.strip()
```

---

## 4. 구현 계획

### 4.1 파일 구조

```
regscan/
├── map/
│   ├── ingredient_bridge.py    # [NEW] 주성분코드 ↔ INN 브릿지
│   └── global_status.py        # [UPDATE] HIRA 급여 통합
├── ingest/
│   └── hira.py                 # [NEW] HIRA 데이터 로더
└── parse/
    └── hira_parser.py          # [NEW] HIRA 파서
```

### 4.2 핵심 클래스

#### IngredientBridge

```python
class IngredientBridge:
    """주성분코드 ↔ INN 브릿지"""

    def __init__(self, atc_mapping_path: str):
        self.inn_to_code: dict[str, str] = {}   # INN → 주성분코드
        self.code_to_inn: dict[str, str] = {}   # 주성분코드 → INN
        self._load(atc_mapping_path)

    def get_ingredient_code(self, inn: str) -> str | None:
        """INN으로 주성분코드 조회"""
        normalized = normalize_inn(inn)
        return self.inn_to_code.get(normalized)

    def get_inn(self, ingredient_code: str) -> str | None:
        """주성분코드로 INN 조회"""
        return self.code_to_inn.get(ingredient_code)
```

#### HIRAStatus

```python
@dataclass
class HIRAStatus:
    """HIRA 급여 정보"""
    ingredient_code: str        # 주성분코드
    item_code: str             # 품목코드
    item_name: str             # 품목명
    reimbursement: str         # 급여/삭제/급여정지/선별급여
    price_ceiling: float       # 상한가
    company: str               # 업체명
    apply_date: date           # 적용일자
```

#### GlobalRegulatoryStatus 확장

```python
@dataclass
class GlobalRegulatoryStatus:
    inn: str
    fda: FDAStatus | None
    ema: EMAStatus | None
    mfds: MFDSStatus | None
    hira: HIRAStatus | None     # [NEW] HIRA 급여 정보
    cris: list[CRISStatus]

    # 추가 분석
    @property
    def is_globally_approved_kr_not_reimbursed(self) -> bool:
        """글로벌 승인 + 국내 미급여"""
        global_approved = self.fda or self.ema
        kr_not_reimbursed = self.hira is None or self.hira.reimbursement != "급여"
        return global_approved and kr_not_reimbursed
```

### 4.3 매칭 함수

```python
def enrich_with_hira(
    statuses: list[GlobalRegulatoryStatus],
    hira_list: list[dict],
    bridge: IngredientBridge
) -> list[GlobalRegulatoryStatus]:
    """GlobalRegulatoryStatus에 HIRA 급여 정보 추가"""

    # HIRA 인덱스 (ingredient_code → 최신 급여정보)
    hira_index = build_hira_index(hira_list)

    for status in statuses:
        # INN → 주성분코드
        ingredient_code = bridge.get_ingredient_code(status.inn)
        if not ingredient_code:
            continue

        # 주성분코드 → HIRA 급여정보
        hira_info = hira_index.get(ingredient_code)
        if hira_info:
            status.hira = HIRAStatus(**hira_info)

    return statuses
```

---

## 5. 테스트 계획

### 5.1 단위 테스트

| 테스트 | 설명 |
|--------|------|
| test_inn_normalization | INN 정규화 정확성 |
| test_bridge_loading | ATC 매핑 로딩 |
| test_inn_to_code | INN → 주성분코드 변환 |
| test_hira_matching | HIRA 급여 매칭 |

### 5.2 통합 테스트

| 테스트 | 기대 결과 |
|--------|----------|
| 글로벌 주요 약물 매칭 | pembrolizumab, nivolumab 등 급여 확인 |
| 매칭률 측정 | MFDS 중 HIRA 매칭 비율 |
| 미급여 약물 탐지 | 글로벌 승인 + 국내 미급여 목록 |

### 5.3 검증 대상 약물

| INN | 기대 결과 |
|-----|----------|
| pembrolizumab | 급여 |
| nivolumab | 급여 |
| semaglutide | 급여 (당뇨) / 비급여 (비만) |
| adalimumab | 급여 |
| trastuzumab | 급여 |

---

## 6. 예상 결과

### 6.1 매칭률

| 항목 | 예상 |
|------|------|
| INN 정확 매칭 | 60-70% |
| 부분 매칭 포함 | 75-85% |
| 미매칭 | 15-25% (신약, 표기 차이) |

### 6.2 산출물

1. **브릿지 테이블**: INN ↔ 주성분코드 매핑 (4,415건)
2. **HIRA 급여 현황**: GlobalRegulatoryStatus에 통합
3. **분석 리포트**: 글로벌 승인 + 국내 미급여 약물 목록

---

## 7. 일정

| 단계 | 작업 | 예상 |
|------|------|------|
| 1 | IngredientBridge 구현 | - |
| 2 | HIRAStatus 모델 추가 | - |
| 3 | enrich_with_hira 구현 | - |
| 4 | 단위 테스트 | - |
| 5 | 통합 테스트 | - |
| 6 | 결과 검증 | - |

---

## 8. 참고

### 8.1 관련 문서

- `docs/research/2026-02-04_hira_data_research.md` - HIRA 데이터 분석
- `scrape-hub/project/drug_data/docs/reports/drug_dictionary_reconstruction_strategy.md` - 통합 스키마 설계

### 8.2 데이터 출처

- HIRA 적용약가파일: 건강보험심사평가원
- ATC 매핑: 공공데이터포털 (건강보험심사평가원_ATC코드_매핑_목록)
- MFDS 허가정보: 공공데이터포털 (식품의약품안전처_의약품 제품 허가정보)

---

**문서 버전**: 1.0
**작성자**: Claude
**다음 단계**: IngredientBridge 구현
