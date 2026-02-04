# INN 매칭 및 코드 연계 조사 리포트

> 작성일: 2026-02-04
> 목적: MFDS ↔ HIRA 매칭을 위한 데이터 불균형 해결 방안 조사

---

## 1. 문제 정의

### 1.1 현재 상황

| 데이터 | 건수 | 비고 |
|--------|------|------|
| ATC 매핑 주성분코드 | 4,415개 | 브릿지 테이블 |
| HIRA ingredient_code | 9,002개 | 타겟 |
| **커버리지** | **~49%** | 절반만 매칭 가능 |

### 1.2 제외 방안

| 방안 | 이유 |
|------|------|
| ❌ Fuzzy Matching | 신뢰도 낮음, 오매칭 위험 |
| ❌ 수동 매핑 | 시간 부족 |

---

## 2. scrape-hub 기존 데이터 분석

### 2.1 핵심 문서

| 문서 | 위치 | 핵심 내용 |
|------|------|----------|
| DATA_SOURCE_MASTER_REPORT.md | project/drug_data/docs/reports/ | 데이터 소스 현황 |
| drug_matching_master_plan.md | project/drug_data/docs/plans/ | 매칭 전략 |
| drug_dictionary_reconstruction_strategy.md | project/drug_data/docs/reports/ | 통합 스키마 |

### 2.2 데이터 소스 현황 (scrape-hub)

| 소스 | 건수 | 매칭키 | 우선순위 |
|------|------|--------|----------|
| **적용약가파일** | 55,471 | 의성분코드 8,910개 | ⭐⭐⭐ SoT |
| **ATC 매핑** | 23,027 | 의성분코드, ATC코드 | ⭐⭐ |
| **약가마스터** | 58,576 | 일반명코드, 성분명 | ⭐ |
| **drug_dictionary** | 91,706 | 검색키 70,431개 | 통합 |

### 2.3 교집합 분석 (핵심 발견)

```
적용약가 ∩ ATC매핑    = 4,458개 (50.0%)
적용약가 ∩ 약가마스터 = 8,849개 (99.3%) ← 핵심!
```

**결론**: 약가마스터를 추가하면 커버리지 99.3%까지 증가

### 2.4 데이터 위치

```
scrape-hub/data/
├── hira_master/
│   ├── drug_dictionary.json          # 91,706건
│   └── drug_dictionary_normalized.json
├── hira_biz/
│   └── 적용약가/                      # 55,471건
├── kpis/
│   └── ATC 부여결과/                  # 23,027건
└── data_go/
    └── yakga_master/                  # 58,576건 (약가마스터)
```

---

## 3. 외부 DB 조사

### 3.1 RxNorm (NLM)

| 항목 | 내용 |
|------|------|
| 제공처 | National Library of Medicine (NLM) |
| 비용 | **무료** |
| API | https://lhncbc.nlm.nih.gov/RxNav/APIs/ |
| 커버리지 | 미국 처방약 99.995% |
| INN 지원 | 제한적 (미국 약물 중심) |

**장점**:
- 무료 API
- Approximate Matching 기능 (유사 약물명 검색)
- 다양한 약물 DB 연동 (DrugBank, First Databank 등)

**단점**:
- **미국 약물 중심** → 한국 약물 커버리지 낮음
- INN 매핑 직접 제공 안 함
- 한글 미지원

**활용 가능성**: 낮음 (글로벌 약물 INN 확인용으로만 활용)

### 3.2 DrugBank

| 항목 | 내용 |
|------|------|
| 제공처 | OMx Personal Health Analytics |
| 비용 | **유료** (Academic Free 있음) |
| 데이터 | 약물 15,000+, 표적 5,000+ |
| INN 지원 | 있음 |

**장점**:
- 체계적인 INN 매핑
- 글로벌 커버리지
- RxNorm과 연동

**단점**:
- 상업적 사용 유료
- API 호출 제한

**활용 가능성**: 중간 (학술용 무료 버전 검토 필요)

### 3.3 MFDS 데이터 포털

| 항목 | 내용 |
|------|------|
| URL | https://data.mfds.go.kr/ |
| 비용 | **무료** |
| 데이터 | 284,477건 의약품 허가정보 |
| API | OpenAPI 제공 |

**제공 데이터**:
- 의약품 허가정보 (XML, JSON)
- DUR 정보 (192,436건)
- 낱알식별 정보

**KD코드 (의약품표준코드)**:
- 13자리: 국가코드(3) + 제조사(4) + 제품(5) + 검증(1)
- "880"으로 시작
- nedrug.mfds.go.kr에서 조회 가능

**활용 가능성**: 높음 (한국 공식 데이터)

### 3.4 공공데이터포털 약가마스터

| 항목 | 내용 |
|------|------|
| URL | https://www.data.go.kr/data/15067462/fileData.do |
| 비용 | **무료** |
| 데이터 | 의약품표준코드 매핑 |
| 갱신 | 월별 |

**핵심**: HIRA 의성분코드 ↔ 의약품표준코드 매핑 제공

---

## 4. 해결 전략

### 4.1 최종 전략: 약가마스터 활용

```
┌─────────────────────────────────────────────────────────────┐
│  MFDS (ITEM_INGR_NAME)                                      │
│      ↓                                                      │
│  약가마스터 (일반명/성분명 → 의성분코드)                      │
│      ↓                                                      │
│  HIRA (ingredient_code)                                     │
│      ↓                                                      │
│  급여여부                                                    │
└─────────────────────────────────────────────────────────────┘

예상 커버리지: 99.3%
```

### 4.2 데이터 통합 순서

1. **적용약가파일** (SoT) - 55,471건
2. **+ 약가마스터** - 58,576건 → 의성분코드 확장
3. **+ ATC 매핑** - 23,027건 → INN 영문명 추가
4. **= 통합 브릿지** - 커버리지 99%+

### 4.3 필요 데이터 복사

```bash
# scrape-hub → RegScan 복사 필요
data/data_go/yakga_master/*.csv   # 약가마스터 (58,576건)
```

### 4.4 매칭 우선순위 (수정)

| 순위 | 매칭키 | 커버리지 |
|------|--------|----------|
| 1 | 의성분코드 직접 매칭 | 50% |
| 2 | 약가마스터 → 의성분코드 | +49% |
| 3 | INN 정규화 (ATC명칭) | 보조 |

---

## 5. INN 정규화 개선

### 5.1 현재 문제

단순 문자열 처리로는 불충분:
- "Pembrolizumab" vs "pembrolizumab hydrochloride"
- 조합제: "Levodopa/Carbidopa"
- 언어 차이: "니볼루맙" vs "Nivolumab"

### 5.2 개선 방안

| 방안 | 설명 | 우선순위 |
|------|------|----------|
| 약가마스터 성분명 | 한글/영문 성분명 모두 제공 | 높음 |
| ATC 명칭 | 표준 영문 INN | 중간 |
| RxNorm Approximate Match | 글로벌 약물 fallback | 낮음 |

### 5.3 구현 전략

```python
def match_ingredient(mfds_name: str, bridge: IngredientBridge) -> str | None:
    """다단계 매칭"""

    # 1단계: 약가마스터 성분명 직접 매칭
    if code := bridge.match_by_ingredient_name(mfds_name):
        return code

    # 2단계: ATC 영문명 매칭 (정규화 후)
    normalized = normalize_inn(mfds_name)
    if code := bridge.match_by_atc_name(normalized):
        return code

    # 3단계: 약가마스터 일반명 매칭
    if code := bridge.match_by_general_name(mfds_name):
        return code

    return None
```

---

## 6. 결론

### 6.1 핵심 발견

1. **scrape-hub에 이미 99.3% 커버리지 달성 가능한 데이터 있음**
2. 약가마스터 추가 시 커버리지 50% → 99% 증가
3. 외부 DB (RxNorm, DrugBank)는 한국 데이터에 제한적
4. Fuzzy matching 없이 Exact match로 충분

### 6.2 필요 작업

| 작업 | 우선순위 |
|------|----------|
| 약가마스터 데이터 복사 | 높음 |
| IngredientBridge 확장 (약가마스터 통합) | 높음 |
| 다단계 매칭 로직 구현 | 중간 |
| RxNorm API 연동 (글로벌 fallback) | 낮음 |

### 6.3 예상 결과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 커버리지 | 49% | **99%+** |
| 매칭 방식 | Exact only | Exact only |
| 데이터 소스 | ATC 매핑 | ATC + 약가마스터 |

---

## 7. 참고 자료

### 7.1 외부 링크

- [RxNorm API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)
- [RxNorm Overview](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html)
- [DrugBank](https://www.drugbank.com/)
- [MFDS 데이터 포털](https://data.mfds.go.kr/)
- [공공데이터포털 약가마스터](https://www.data.go.kr/data/15067462/fileData.do)
- [의약품안전나라](https://nedrug.mfds.go.kr/)

### 7.2 내부 문서

- `scrape-hub/project/drug_data/docs/reports/DATA_SOURCE_MASTER_REPORT.md`
- `scrape-hub/project/drug_data/docs/plans/drug_matching_master_plan.md`
- `scrape-hub/project/drug_data/docs/reports/drug_dictionary_reconstruction_strategy.md`

---

**문서 버전**: 1.0
**작성자**: Claude
