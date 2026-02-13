# 기사 품질 개선 계획 — v2.0 "뉴스 기사화"

## 현황 진단

### Gemini 분석 요약

현재 20건 기사를 분석한 결과, 3가지 구조적 문제가 확인됨.

| 문제 | 증상 | 근본 원인 |
|------|------|-----------|
| 앵무새 반복 | 20건 기사가 동일 구조·어투 | LLM 입력 데이터가 규제 상태(approved/not, 날짜)뿐이라 차별화 불가 |
| 맥락 부재 | 경쟁약·시장·임상 스토리 없음 | `_prepare_drug_data()`가 규제 데이터만 전달, 치료영역·경쟁약 정보 미포함 |
| 전망 부재 | "모니터링 필요" 반복 | 타임라인 예측 데이터 없음 + 프롬프트가 예측을 요구하지 않음 |

### 현재 LLM 입력 데이터 (`_prepare_drug_data`)

```
inn, fda(approved/date), ema(approved/date), mfds(approved/date/brand),
hira(status/price/criteria), cris(trial_count/trials[5]),
analysis(domestic_status/global_score/hot_issue_reasons/notes)
```

**누락된 데이터**: therapeutic_areas, 경쟁약, 적응증 텍스트, days_since_approval, stream_sources, indication detail

### 현재 프롬프트 (`prompts.py`)

- `SYSTEM_PROMPT`: "의약품 규제 전문 기자이자 건강보험 전문가" — 좋은 페르소나지만 "기자"보다 "요약기"로 동작
- `BRIEFING_REPORT_PROMPT`: CoT 4단계 + Few-Shot 2예시 — 구조는 좋지만 "사실 나열" 중심
- Few-Shot 예시 2개가 모두 같은 패턴 → LLM이 이 패턴을 따라함

---

## 개선 전략 (3단계)

```
Phase A: 프롬프트 리팩토링 (코드 변경 최소, 효과 즉시)  ← 오늘
Phase B: 입력 데이터 보강 (기존 데이터 활용)            ← 오늘~내일
Phase C: 신규 데이터 소스 (ClinicalTrials.gov 등)       ← 추후
```

---

## Phase A: 프롬프트 리팩토링

**목표**: 동일한 입력 데이터로 기사 품질 50% 이상 개선. 코드 변경은 `prompts.py` 1개 파일.

### A-1. 시스템 프롬프트 재작성

현재:
```
당신은 의약품 규제 전문 기자이자 건강보험 전문가입니다.
```

변경:
```
당신은 "메드클레임 인사이트"의 수석 의약 전문기자입니다.
10년간 FDA/EMA/MFDS 규제 동향을 취재해 온 베테랑으로,
단순 사실 나열이 아니라 "왜 이 약물이 지금 중요한가"를
독자(의료전문직, 보험심사자)에게 설득력 있게 전달합니다.
```

핵심 변경:
- "전문가" → "수석 기자" (기자 정체성 강화)
- 독자 타겟 명시 (의료전문직, 보험심사자)
- "왜 중요한가" 관점 주입

### A-2. 기사 구조 v2.0

현재 구조:
```
headline / subtitle / key_points / global_section / domestic_section / medclaim_section
```

문제: 3섹션이 각각 "사실 나열"이라 기사가 아니라 보고서처럼 읽힘.

**변경**: 구조는 유지하되, 각 섹션의 역할을 재정의.

| 섹션 | 현재 역할 | v2.0 역할 |
|------|-----------|-----------|
| `global_section` | "FDA X일 승인, EMA Y일 승인" 사실 | **리드(lead)**: 왜 지금 이 약물이 주목받는가 + 기전·적응증 + 경쟁 포지셔닝 |
| `domestic_section` | "MFDS 미허가, HIRA 미등재" 사실 | **국내 전망 분석**: 허가·급여 타임라인 예측 + 경과일 기반 근거 + 시사점 |
| `medclaim_section` | "급여 시 30%, 산정특례 시 10%" 공식 | **실무 가이드**: 현 시점 실무 대응 + 시나리오별 비용 + 준비사항 |

### A-3. 프롬프트 핵심 변경사항

1. **"뉴스 리드" 패턴 강제**
   - global_section 첫 문장: "왜 지금 이 약물이 주목받는가" (뉴스 가치 먼저)
   - 나머지: 기전 → 경쟁 포지션 → 승인 의의

2. **"앵무새 방지" 지시**
   ```
   금지 표현: "~할 것으로 예상된다", "모니터링이 필요하다", "주목된다"
   대신: 구체적 근거와 수치로 전망 제시
   예: "FDA 승인 후 18개월이 경과했으나 MFDS 허가 미신청 —
        국내 판매권자 부재 가능성"
   ```

3. **"차별화된 분석" 요구**
   ```
   - 이 약물만의 고유한 특징 1가지를 반드시 포함
   - 같은 적응증 기존 치료제 대비 포지셔닝 언급
   - 승인 경과일에 기반한 타임라인 분석
   ```

4. **Few-Shot 예시 다양화**
   - 예시 1: 글로벌 승인 + 국내 급여 (긍정 기사)
   - 예시 2: 글로벌 승인 + 국내 미허가 (경고 기사)
   - 예시 3: EMA만 승인 + 희귀질환 (탐색 기사) ← 신규
   - 각 예시의 어투와 구조를 의도적으로 다르게 작성

### A-4. 수정 파일

| 파일 | 변경 |
|------|------|
| `regscan/report/prompts.py` | `SYSTEM_PROMPT` 재작성, `BRIEFING_REPORT_PROMPT` v2.0 전면 교체 |

### A-5. 검증

- 기존 20건 중 5건 선별 (score 상위 3 + 하위 2)
- 동일 입력 데이터로 v1 vs v2 프롬프트 비교 생성
- 평가 기준: (1) 리드 차별성, (2) 경쟁약 언급 여부, (3) 전망 구체성

---

## Phase B: 입력 데이터 보강

**목표**: LLM에 전달하는 데이터를 보강하여 기사 차별화의 물리적 근거 제공.

### B-1. 기존 데이터 활용 (즉시 가능)

`DomesticImpact`에 이미 있지만 `_prepare_drug_data()`가 LLM에 전달하지 않는 데이터:

| 필드 | 현재 전달 | 변경 |
|------|-----------|------|
| `therapeutic_areas` | X | O — 치료영역 문맥 제공 |
| `stream_sources` | X | O — 어떤 스트림에서 발견되었는지 |
| `days_since_global_approval` | X | O — 경과일 기반 타임라인 분석용 |
| `korea_relevance_score` | X | O — 국내 연관성 수치화 |
| `korea_relevance_reasons` | X | O — 연관성 근거 |
| `quadrant` | X | O — 4분면 분류 (top_priority/watch/track/normal) |

**수정 파일**: `regscan/report/llm_generator.py` — `_prepare_drug_data()` 메서드에 6개 필드 추가

### B-2. 경쟁약 데이터 (DB 조회)

같은 치료영역 약물을 DB에서 조회하여 LLM 입력에 포함.

```python
# _prepare_drug_data() 확장
"competitors": [
    {"inn": "PEMBROLIZUMAB", "score": 95, "fda": true, "mfds": true},
    {"inn": "NIVOLUMAB", "score": 90, "fda": true, "mfds": true},
]
```

**구현 방식**:
- `publish_articles.py`의 `load_drugs_from_db()`에서 therapeutic_area별 그룹핑
- 같은 area의 다른 약물 상위 3개를 `competitors` 필드로 주입
- LLM이 "경쟁약 대비 포지셔닝" 작성 가능

**수정 파일**:
| 파일 | 변경 |
|------|------|
| `regscan/report/llm_generator.py` | `_prepare_drug_data()` — competitors 파라미터 수용 |
| `regscan/scripts/publish_articles.py` | `run_publish()` — DB에서 therapeutic_area별 경쟁약 조회 후 주입 |

### B-3. 적응증 상세 텍스트

현재: `therapeutic_areas` = `["oncology"]` (범주만)
필요: `"적응증: 재발·불응성 미만성 거대 B세포 림프종(DLBCL)"` (구체적)

**데이터 소스**:
- FDA `openfda.indications_and_usage` 필드 (기존 검색 결과에 포함될 수 있음)
- EMA JSON의 `therapeutic_indication` 필드

**구현**:
- Stream 1 수집 시 indication 텍스트를 `GlobalRegulatoryStatus`에 저장
- DB에 `indication_text` 컬럼 추가 (또는 기존 필드 활용)
- LLM 입력에 포함

**수정 파일**:
| 파일 | 변경 |
|------|------|
| `regscan/map/global_status.py` | `indication_text` 필드 추가 |
| `regscan/stream/therapeutic.py` | FDA/EMA 수집 시 indication 텍스트 추출·저장 |
| `regscan/db/loader.py` | indication_text DB 저장 |
| `regscan/report/llm_generator.py` | `_prepare_drug_data()`에 indication 포함 |

### B-4. 승인 경과일 기반 타임라인 예측

현재 `analysis_notes`에 "글로벌 승인 후 6년 경과" 같은 텍스트가 있지만, 더 정밀한 데이터를 제공.

```python
"timeline": {
    "first_global_approval": "2020-01-16",
    "days_since_approval": 2220,
    "avg_fda_to_mfds_lag_days": 730,  # 통계 기반
    "expected_mfds_window": "overdue",  # normal / expected / overdue
}
```

**수정 파일**: `regscan/report/llm_generator.py` — `_prepare_drug_data()` 내 타임라인 계산 로직 추가

---

## Phase C: 신규 데이터 소스 (추후)

### C-1. ClinicalTrials.gov 상세 결과

현재 Stream 3에서 CT.gov를 수집하지만, 시험 **결과**(efficacy, safety)는 미수집.

- `ClinicalTrials.gov API v2` → `resultsSection` 필드로 primary outcome 조회 가능
- 핵심: "ORR 40%, mPFS 12개월" 같은 수치를 기사에 포함
- 구현 규모: 신규 파서 + API 호출 + DB 저장 → **중규모 작업**

### C-2. 약가 시뮬레이션

해외 약가(US WAC, UK NICE) 기반 국내 예상 약가 범위 추정.

- 데이터 소스: GoodRx API (미국), NICE TA (영국) — 둘 다 공개 데이터 아님
- 대안: 같은 치료영역 기존 급여 약물의 HIRA 상한가 중앙값으로 범위 추정
- 구현: DB에서 동일 area 급여 약물 가격 통계 → "유사 약물 기준 예상 약가 범위" 제시
- **기존 데이터로 가능** → Phase B 후반에 병행 가능

### C-3. 뉴스 소스 크롤링

약물별 최신 뉴스 헤드라인을 1~2건 가져와서 LLM 컨텍스트로 제공.

- 데이터 소스: PubMed RSS, FDA Press Release, 팜뉴스/히트뉴스 등
- 구현 난이도: 높음 (크롤링 + 필터링 + 저장 + 갱신)
- **추후 검토**

---

## 실행 순서

```
Phase A (프롬프트만, 오늘):
  A-1: SYSTEM_PROMPT 재작성                          [15분]
  A-2: BRIEFING_REPORT_PROMPT v2.0 전면 교체          [30분]
  A-3: Few-Shot 예시 3개로 확대 + 다양화               [20분]
  A-4: 5건 비교 생성 → 품질 검증                       [10분]

Phase B (데이터 보강, 오늘~내일):
  B-1: _prepare_drug_data() 기존 필드 6개 추가         [10분]
  B-2: 경쟁약 DB 조회 + LLM 입력 주입                  [30분]
  B-3: 적응증 텍스트 수집·저장·전달                     [45분]
  B-4: 타임라인 예측 데이터 추가                        [15분]
  → 20건 전체 재생성 + 품질 검증                        [15분]

Phase C (추후):
  C-1: CT.gov 임상 결과 수집                           [별도 계획]
  C-2: 약가 시뮬레이션                                 [별도 계획]
```

---

## 예상 결과

| 지표 | 현재 (v1) | Phase A 후 | Phase A+B 후 |
|------|-----------|------------|--------------|
| 기사 차별성 | 20건 동일 패턴 | 어투·구조 다양화 | 치료영역별 고유 기사 |
| 경쟁약 언급 | 0건 | LLM 지식 의존 | DB 기반 팩트 |
| 적응증 명시 | LLM 추론 (부정확) | LLM 추론 | 원본 데이터 기반 |
| 타임라인 전망 | "모니터링 필요" | 경과일 기반 분석 | 정량적 예측 |
| 실무 가이드 | 공식적 요약 | 시나리오별 안내 | 가격 범위 포함 |

---

## 기사 v2.0 예시 (목표 톤)

### 현재 (v1):

> polatuzumab vedotin은 CD79b를 표적으로 하는 항체-약물 복합체(ADC)로,
> 비호지킨 림프종(NHL) 모집단 중 특히 치료 저항성 환자에게 새로운 치료 옵션을
> 제시할 수 있다. 이 약물은 항체가 암세포에 결합하여 독성 화합물을 전달함으로써
> 세포 사멸을 유도하는 방식으로 작용한다.

### 목표 (v2):

> 기존 R-CHOP 요법에 실패한 미만성 거대 B세포 림프종(DLBCL) 환자에게
> polatuzumab vedotin은 게임 체인저가 될 수 있다. CD79b 표적 ADC로서
> POLARIX 3상 시험에서 R-CHOP 대비 무진행생존율(PFS) 우위를 입증했고,
> 이미 FDA(2023.4)·EMA(2020.1) 양대 기관 승인을 획득한 상태다.
> 같은 적응증의 glofitamab, loncastuximab tesirine과 함께 2차 이후
> DLBCL 치료 시장의 판도를 바꾸고 있다.

**차이**: 경쟁약 언급, 임상시험명·결과, "왜 중요한가" 선행, 구체적 사실 근거
