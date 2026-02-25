# Phase C-2: 가격 스펙트럼 시스템 상세 설계

> **계획 버전**: article-quality-v3.0 Phase C-2
> **작성일**: 2026-02-25
> **설계 방식**: Plan B — 사전 계산 테이블 (Pre-computed Stats Table)
> **선택 사유**: HIRA 데이터는 월 1회 갱신, 매 기사마다 59,004건 파싱은 낭비. 240행 경량 테이블로 즉시 조회.

---

## 1. 배경 및 문제 정의

### 기존 문제

v3.0 계획 원안은 `therapeutic_areas` 기반 단순 평균 가격 통계를 제안했으나:

1. **분류 키 문제**: DB `therapeutic_areas` 컬럼은 EMA 기반으로 급여 353건 중 79건(22.4%) 미분류
2. **평균의 무의미성**: 항암제(421) 내 1,000원 제네릭 주사제와 3.6억 원 CAR-T가 공존 → 단순 평균 무의미
3. **데이터 소스 미스매치**: DB의 353건은 RegScan 추적 약물만, HIRA 원본은 30,418건 급여

### 해결 방향: 가격 스펙트럼

- **분류 키**: `class_no` (약효분류코드, HIRA 원본 필드) — 120개 카테고리, 미분류 0%
- **세그먼트**: `동일 의약품` 필드로 최초의약품(original) / 제네릭(generic) 분리
- **통계**: 백분위 기반 스펙트럼 (P25, P50, P75, P90) — 평균 대신 분포 제공
- **데이터 소스**: HIRA 원본 JSON (30,418건) 직접 사용, DB 353건 의존 제거

---

## 2. 데이터 현황 (2026-02-25 실측)

### 원본 파일

| 항목 | 수치 |
|------|------|
| 파일 | `data/hira/drug_prices_20260204.json` |
| 전체 레코드 | 59,004건 |
| 급여 레코드 | 30,418건 |
| 고유 class_no | 120개 |
| 고유 ingredient_code | 4,527개 |
| 원본 공시일 | ~2026-01-30 |

### 동일 의약품 분포 (급여 30,418건)

| 세그먼트 | 기준 | 건수 |
|----------|------|------|
| Original (최초의약품) | `동일 의약품` = NaN | 27,564건 (90.6%) |
| Generic (제네릭) | `동일 의약품` ≠ NaN | 2,854건 (9.4%) |

### 주요 class_no 실측치

| class_no | 분류명 | orig건수 | gen건수 | orig P50 | orig P90 | orig max |
|----------|--------|---------|---------|----------|----------|---------|
| 421 | 항악성종양제 | 976 | 45 | 90,896 | 528,394 | 360,039,359 |
| 131 | 안과용제 | 49 | 1,010 | 27,199 | 735,546 | 3,072,036 |
| 721 | 체외진단용약 | 473 | 43 | 50,100 | 211,314 | 1,213,485 |
| 399 | 기타 대사성의약품 | 799 | 12 | 4,556 | 53,972 | 439,098 |
| 629 | 기타 호르몬제 | 1,235 | 32 | 1,516 | 12,684 | 1,070,220 |

---

## 3. DB 스키마

### 테이블: `hira_price_stats`

```sql
CREATE TABLE hira_price_stats (
    class_no    VARCHAR(10)   NOT NULL,    -- 약효분류코드 (421 등)
    segment     VARCHAR(10)   NOT NULL,    -- 'original' | 'generic'
    class_name  VARCHAR(100)  NOT NULL,    -- 약효분류명 (한글)
    count       INTEGER       NOT NULL,    -- 해당 그룹 레코드 수
    min_price   FLOAT         NOT NULL,    -- 최솟값
    p25         FLOAT         NOT NULL,    -- 25백분위
    p50_median  FLOAT         NOT NULL,    -- 중앙값
    p75         FLOAT         NOT NULL,    -- 75백분위
    p90         FLOAT         NOT NULL,    -- 90백분위 (고가약 벤치마크)
    max_price   FLOAT         NOT NULL,    -- 최댓값
    source_file VARCHAR(200)  NOT NULL,    -- 원본 파일명
    source_hash VARCHAR(64)   NOT NULL,    -- SHA-256 해시 (변경 감지)
    computed_at DATETIME      NOT NULL,    -- 계산 시각

    PRIMARY KEY (class_no, segment)
);
```

### SQLAlchemy 모델

```python
class HiraPriceStatsDB(Base):
    """HIRA 가격 스펙트럼 사전 계산 통계"""
    __tablename__ = "hira_price_stats"

    class_no    = Column(String(10), primary_key=True)
    segment     = Column(String(10), primary_key=True)  # 'original' | 'generic'
    class_name  = Column(String(100), nullable=False)
    count       = Column(Integer, nullable=False)
    min_price   = Column(Float, nullable=False)
    p25         = Column(Float, nullable=False)
    p50_median  = Column(Float, nullable=False)
    p75         = Column(Float, nullable=False)
    p90         = Column(Float, nullable=False)
    max_price   = Column(Float, nullable=False)
    source_file = Column(String(200), nullable=False)
    source_hash = Column(String(64), nullable=False)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

### 테이블 규모

- 최대 행: 120 class_no × 2 segments = **240행**
- 실제: 많은 class_no에 generic이 없으므로 **~160행** 예상
- 저장 크기: **< 10KB**

---

## 4. class_no → class_name 매핑

HIRA 원본에는 코드만 포함. KD 약효분류번호 표준 매핑을 코드에 내장.

### Fallback 규칙

```python
def get_class_name(class_no: str) -> str:
    """class_no → 한글 분류명. 매핑에 없으면 'Unknown Class ({code})' 반환."""
    return CLASS_NO_NAMES.get(str(class_no), f"Unknown Class ({class_no})")
```

### 전체 매핑 (120개 + fallback)

KD 약효분류번호 체계:
- 1xx: 신경계용약
- 2xx: 순환기관·혈액·체액용약
- 3xx: 소화기관·호흡기관·비뇨생식기관용약
- 4xx: 항생물질·항암제·알레르기용약
- 6xx: 외용약·치과구강용약·호르몬제
- 7xx: 진단용약·체외진단용약
- 8xx: 생물학적제제·방사성의약품

```python
CLASS_NO_NAMES: dict[str, str] = {
    # ── 1xx: 신경계용약 ──
    "110": "전신마취제",
    "111": "최면진정제",
    "112": "항불안제",
    "113": "항간질제",
    "114": "해열진통소염제",
    "115": "각성제·정신신경용제",
    "116": "진훈제",
    "117": "정신신경용제",
    "119": "기타 중추신경용약",
    "121": "골격근이완제",
    "122": "자율신경제",
    "123": "진경제",
    "124": "뇌혈관용제",
    "129": "기타 말초신경용약",
    "131": "안과용제",
    "132": "이비과용제",
    "140": "진통제",
    "141": "합성마약",
    "142": "마약성진통제",
    "149": "기타 감각기관용약",
    # ── 2xx: 순환기관·혈액·체액용약 ──
    "211": "강심제",
    "212": "부정맥용제",
    "213": "이뇨제",
    "214": "혈압강하제",
    "215": "혈관확장제",
    "216": "관상혈관확장제",
    "217": "말초혈관확장제",
    "218": "고지혈증용제",
    "219": "기타 순환기관용약",
    "220": "혈액응고저지제",
    "221": "지혈제",
    "222": "혈액대용제",
    "223": "혈액응고인자",
    "229": "기타 혈액·체액용약",
    "230": "간장용제",
    "231": "해독제",
    "232": "소화성궤양용제",
    "234": "건위소화제",
    "235": "정장제",
    "236": "이담제",
    "237": "소화관운동조절제",
    "238": "제산제",
    "239": "기타 소화기관용약",
    "241": "뇌하수체호르몬제",
    "243": "갑상선·부갑상선호르몬제",
    "244": "단백동화스테로이드",
    "245": "부신호르몬제",
    "247": "남성호르몬제",
    "249": "기타 호르몬제(내분비계)",
    "250": "비타민제",
    "252": "비타민B",
    "255": "비타민제(복합)",
    "256": "비타민C",
    "259": "기타 자양강장제",
    "261": "칼슘제",
    "263": "무기질제제",
    "264": "당뇨병용제(인슐린)",
    "265": "당뇨병용제(경구)",
    "266": "당뇨병합병증용제",
    "269": "기타 대사성의약품",
    # ── 3xx: 호흡기·비뇨생식기·외피용약 ──
    "310": "호흡기관용약",
    "311": "기관지확장제",
    "312": "거담제",
    "313": "진해제",
    "314": "함소흡입제",
    "315": "호흡촉진제",
    "316": "비충혈제거제",
    "319": "기타 호흡기관용약",
    "321": "이뇨제(비뇨기)",
    "322": "요산배설촉진제",
    "323": "비뇨기관용제",
    "325": "생식기관용약",
    "329": "기타 비뇨기관용약",
    "331": "외피용살균소독제",
    "332": "창상보호제",
    "333": "화농성질환용제",
    "339": "기타 외피용약",
    "341": "치과구강용약",
    "349": "기타 치과구강용약",
    # ── 3xx (계속): 대사·면역 ──
    "391": "효소제제",
    "392": "당류제제",
    "394": "유전자재조합의약품",
    "395": "면역억제제",
    "396": "당뇨병용제(기타)",
    "399": "기타 대사성의약품(종합)",
    # ── 4xx: 항생물질·항암제 ──
    "421": "항악성종양제",
    "429": "기타 종양용약",
    "431": "항히스타민제",
    "439": "기타 알레르기용약",
    "490": "항바이러스제(항암)",
    # ── 6xx: 외용약·호르몬제 ──
    "611": "항생물질(외용)",
    "612": "화학요법제(외용)",
    "613": "항진균제(외용)",
    "614": "기생충질환용제",
    "615": "백신류",
    "616": "면역혈청",
    "617": "혈액제제",
    "618": "항생물질(주사)",
    "619": "기타 화학요법제",
    "621": "부신호르몬제(외용)",
    "622": "남성호르몬제(외용)",
    "623": "여성호르몬제(외용)",
    "629": "기타 호르몬제",
    "631": "비타민A",
    "632": "비타민B(주사)",
    "633": "비타민C(주사)",
    "634": "비타민D",
    "635": "비타민E",
    "636": "비타민K",
    "639": "기타 비타민제",
    "641": "자양강장제(주사)",
    "642": "기타 자양강장제",
    # ── 7xx: 진단용약 ──
    "713": "기능검사용제",
    "721": "체외진단용약",
    "722": "방사성의약품",
    "728": "조영제",
    "729": "기타 진단용약",
    "799": "기타 시약",
    # ── 8xx: 생물학적제제 ──
    "811": "혈액분획제제",
    "821": "기타 생물학적제제",
}
```

---

## 5. 모듈 구조: `regscan/report/price_stats.py`

### 함수 시그니처

```python
# ── 1. 재구축 ──

def rebuild_price_stats(hira_json_path: Path | None = None) -> int:
    """HIRA JSON → hira_price_stats 테이블 전체 재구축.

    1. HIRA JSON 로드 (급여만 필터)
    2. class_no × segment 그룹핑
    3. 백분위 통계 계산
    4. 기존 테이블 DELETE → 신규 INSERT

    Args:
        hira_json_path: HIRA JSON 경로. None이면 최신 파일 자동 탐색.

    Returns:
        생성된 행 수
    """

# ── 2. 조회 ──

def get_price_spectrum(class_no: str, segment: str = "original") -> dict | None:
    """특정 class_no + segment의 가격 스펙트럼 조회.

    Returns:
        {
            "class_no": "421",
            "class_name": "항악성종양제",
            "segment": "original",
            "count": 976,
            "min_price": 48,
            "p25": 15_840,
            "p50_median": 90_896,
            "p75": 237_000,
            "p90": 528_394,
            "max_price": 360_039_359,
        }
        또는 None (해당 그룹 없음)
    """

# ── 3. 약물 위치 계산 ──

def compute_drug_position(
    price: float, class_no: str, segment: str = "original"
) -> str | None:
    """약물 가격이 스펙트럼 내 어디에 위치하는지 백분위로 계산.

    HIRA 원본에서 해당 class_no+segment의 전체 가격 리스트를 로드,
    bisect로 위치 산출.

    Returns:
        "P72" (72백분위) 등. 데이터 없으면 None.
    """

# ── 4. 변경 감지 + 자동 재구축 ──

def check_and_rebuild_if_needed(hira_json_path: Path | None = None) -> bool:
    """HIRA 파일 SHA-256 해시 비교 → 변경 시 재구축.

    파이프라인 실행 시 호출. 해시가 동일하면 스킵.

    Returns:
        True: 재구축 수행됨
        False: 변경 없어 스킵
    """

# ── 5. class_no 매핑 ──

def get_class_name(class_no: str) -> str:
    """class_no → 한글 분류명. 매핑에 없으면 'Unknown Class ({code})' 반환."""
    return CLASS_NO_NAMES.get(str(class_no), f"Unknown Class ({class_no})")
```

---

## 6. 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│  data/hira/drug_prices_YYYYMMDD.json  (59,004건)                │
│  ↓ SHA-256 해시 비교                                            │
│  check_and_rebuild_if_needed()                                  │
│  ↓ 변경 감지 시                                                 │
│  rebuild_price_stats()                                          │
│  ↓ 급여 필터 (30,418건)                                         │
│  ↓ class_no × segment 그룹핑 (120 × 2)                          │
│  ↓ numpy percentile 계산                                        │
│  hira_price_stats 테이블 (≤240행)                                │
└─────────────────────────────────────────────────────────────────┘

                         ↓ 기사 생성 시

┌─────────────────────────────────────────────────────────────────┐
│  _prepare_drug_data_v4(impact)                                  │
│  ↓ drug의 class_no 확인 (HIRA ingredient_code → class_no 매칭)  │
│  get_price_spectrum(class_no, segment)                          │
│  ↓ 급여약이면 compute_drug_position(price, class_no, segment)   │
│  ↓                                                              │
│  data["price_spectrum"] = {                                     │
│      "class_no": "421",                                         │
│      "class_name": "항악성종양제",                                │
│      "segment": "original",                                     │
│      "count": 976,                                              │
│      "p50_median": "90,896원",                                  │
│      "p90": "528,394원",                                        │
│      "max_price": "360,039,359원",                              │
│      "drug_position": "P72"        ← 급여약만                   │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘

                         ↓ LLM 출력

┌─────────────────────────────────────────────────────────────────┐
│  미급여 약물:                                                    │
│  "동일 계열(항악성종양제) 급여 원개발약 976종 중앙값 90,896원,    │
│   상위 10%는 528,394원 이상. 최고가 3.6억 원(CAR-T 등)."         │
│                                                                  │
│  급여 약물 (상한가 150,000원):                                   │
│  "항악성종양제 원개발약 976종 중 P60 수준(상한가 150,000원)."     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. class_no 조회 전략

### 문제
RegScan DB의 약물(`drugs` 테이블)에는 `class_no` 컬럼이 없다.
HIRA raw JSON에는 `ingredient_code` + `class_no`가 있다.
DB `hira_reimbursements` 테이블에는 `ingredient_code`가 있지만 `class_no`는 없다.

### 해결: ingredient_code → class_no 조회

1. **급여약**: `hira_reimbursements.ingredient_code` → HIRA raw에서 해당 ingredient_code의 class_no 조회
2. **미급여약**: `drugs.therapeutic_areas` → class_no 역매핑 (oncology→421 등)
3. **fallback**: therapeutic_areas도 없으면 price_spectrum 미생성 (LLM에 주입 안 함)

이를 위해 rebuild 시 `ingredient_code → class_no` 역인덱스도 함께 생성:

```python
# 부가 테이블 or 딕셔너리: ingredient_code → class_no 매핑
# rebuild 시 메모리에 캐시, 필요 시 JSON 파일로 영속화
_INGREDIENT_CLASS_MAP: dict[str, str] = {}  # {"636401ACH": "114", ...}
```

---

## 8. 프롬프트 통합 규칙

`BRIEFING_REPORT_PROMPT_V4`에 추가할 규칙:

```
## 가격 스펙트럼 해석 규칙
- price_spectrum이 제공된 경우, 국내 섹션에서 반드시 인용하라.
- 미급여 약물: "동일 계열({class_name}) 급여 {segment} {count}종 기준, 상한가 중앙값 {p50_median}, 상위 10%는 {p90} 이상"
- 급여 약물: "이 약물의 상한가({price})는 {class_name} {segment} {count}종 중 {drug_position} 수준"
- 단순 평균은 인용하지 마라. 반드시 중앙값(P50)과 P90을 사용하라.
- max_price가 중앙값의 100배 이상이면 "CAR-T 등 초고가 치료제 포함" 맥락을 추가하라.
```

---

## 9. 재계산 트리거 설계

```
파이프라인 실행 (publish_articles.py 또는 daily_scanner)
  │
  ├─ check_and_rebuild_if_needed(hira_json_path)
  │   ├─ HIRA JSON 파일 SHA-256 해시 계산
  │   ├─ hira_price_stats 테이블에서 source_hash 조회 (첫 행)
  │   ├─ 해시 동일 → return False (스킵)
  │   └─ 해시 다름 → rebuild_price_stats() → return True
  │
  ├─ 기사 생성 루프
  │   └─ _prepare_drug_data_v4()에서 get_price_spectrum() 호출
  │
  └─ 완료
```

### HIRA 파일 갱신 감지

HIRA는 매월 비정기(보통 15~20일) 갱신. 현재 수동 다운로드.

향후 자동화 시:
1. 스케줄러가 HIRA 파일 체크 (해시 비교)
2. 변경 시 `rebuild_price_stats()` 자동 실행
3. `drug_change_log`에 "hira_price_update" 기록

---

## 10. 수정 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `regscan/db/models.py` | **수정** | `HiraPriceStatsDB` 모델 추가 |
| `regscan/report/price_stats.py` | **신규** | 가격 스펙트럼 모듈 전체 |
| `regscan/report/llm_generator.py` | **수정** | `_prepare_drug_data_v4()`에 `price_spectrum` 주입 |
| `regscan/report/prompts.py` | **수정** | V4 프롬프트에 가격 스펙트럼 해석 규칙 추가 |
| `regscan/scripts/publish_articles.py` | **수정** | 기사 생성 전 `check_and_rebuild_if_needed()` 호출 |

---

## 11. 구현 순서

```
Step 1: DB 모델 추가
  └─ HiraPriceStatsDB → models.py

Step 2: price_stats.py 구현
  ├─ CLASS_NO_NAMES 딕셔너리 (120개 + Unknown fallback)
  ├─ rebuild_price_stats()
  ├─ get_price_spectrum()
  ├─ compute_drug_position()
  └─ check_and_rebuild_if_needed()

Step 3: V4 파이프라인 통합
  ├─ llm_generator.py: _prepare_drug_data_v4()에 price_spectrum 주입
  ├─ prompts.py: 가격 스펙트럼 해석 규칙 추가
  └─ publish_articles.py: 기사 생성 전 check_and_rebuild_if_needed()

Step 4: 테스트 및 검증
  ├─ rebuild → DB 행 수 확인 (~160행)
  ├─ get_price_spectrum("421", "original") → 실측치 대조
  ├─ compute_drug_position(150000, "421") → P~60 예상
  └─ 기사 재생성 → 가격 스펙트럼 반영 확인
```

---

## 12. 리스크 및 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| HIRA 파일 포맷 변경 | 낮음 | JSON 키 불일치 시 경고 로그 + 스킵 |
| class_no 신규 코드 추가 | 중간 | `get_class_name()` fallback: `Unknown Class ({code})` |
| 특정 class_no에 데이터 1~2건 | 중간 | count < 5이면 스펙트럼 미생성 (통계적 의미 없음) |
| ingredient_code → class_no 매핑 실패 | 낮음 | therapeutic_areas fallback, 최종 실패 시 미주입 |
