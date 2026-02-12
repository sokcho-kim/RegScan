# RegScan v2.1 스코어링 설계: 2축 분류 (Korea Relevance Score)

> 작성일: 2026-02-12
> 상태: 설계 검토 중

---

## 1. 배경 및 문제 정의

### 현재 상태
- `global_score` (0~100점) 단일 축으로 약물의 중요도를 판단
- 점수 산정 기준: FDA/EMA/MFDS 승인, 특수 지정(Breakthrough, Orphan 등), 다국가 승인, 주요 질환 여부
- 소스: `regscan/map/global_status.py` — `HotIssueScorer.calculate_score()`

### 문제점
1. **"FDA에서 상 받으면 점수 주는 방식"** — 한국과 무관한 약물도 고점수
2. 한국 병원 경영진 관점의 **"이 약이 우리 병원에 왜 중요한가?"**에 대한 답이 부족
3. 한국형 가중치를 `global_score`에 합산하면 **혁신 신약이 상대적으로 밀려서 누락** — 서비스 핵심 가치 훼손

### 핵심 원칙
> **혁신 신약 누락은 절대 불가.** RegScan의 존재 이유는 "아직 한국에 안 들어왔지만 곧 올 혁신 신약을 먼저 알려주는 것"이다.

---

## 2. 설계: 2축 분류 시스템

점수 하나로 "혁신성"과 "국내 연관성"을 동시에 표현하려 하면 어느 한쪽이 희생된다.
**축을 분리하여 독립적으로 평가**한다.

```
                    global_score (혁신성 — 기존 유지)
                         ^
                    100  |  [3] 주시        [1] 최우선
                         |   (Watch)         (Top Priority)
                     50  |
                         |  [4] 일반        [2] 추적
                         |   (Normal)        (Track)
                      0  +----------------------------->
                         0        50       100
                              korea_relevance_score (국내 연관성 — 신규)
```

### 4분면 해석

| 분면 | global_score | korea_relevance | 의미 | 액션 |
|------|-------------|-----------------|------|------|
| **1. 최우선** | >= 60 | >= 50 | 혁신 신약 + 한국 진입 중 | 병원장 즉시 보고, AI 기사 최우선 생성 |
| **2. 추적** | < 60 | >= 50 | 기존 약물, 한국에서 활발 | 보험팀/약제팀 참고, 급여 변경 모니터링 |
| **3. 주시** | >= 60 | < 50 | 혁신 신약, 한국 진입 전 | **반드시 리포트 대상** — 놓치면 안 됨 |
| **4. 일반** | < 60 | < 50 | 일반적 약물 | 일상 모니터링 |

---

## 3. korea_relevance_score 산정 기준

### 3-1. 점수 항목 (최대 100점)

| 카테고리 | 항목 | 점수 | 데이터 소스 | 현재 수집 여부 |
|----------|------|------|------------|--------------|
| **허가/급여** | MFDS 허가 | +20 | `DomesticImpact.mfds_approved` | O 수집 중 |
| | HIRA 급여 등재 (REIMBURSED) | +20 | `DomesticImpact.hira_status` | O 수집 중 |
| | HIRA 급여 삭제 이력 (DELETED) | +5 | `DomesticImpact.hira_status` | O 수집 중 |
| **임상시험** | CRIS 활성 임상시험 존재 | +15 | `DomesticImpact.has_active_trial` | O 수집 중 |
| | CRIS 임상 2건 이상 | +5 | `len(DomesticImpact.cris_trials)` | O 수집 중 |
| **시장 존재** | 동일 ATC 코드 약물 HIRA 등재 | +15 | ATC 코드 → HIRA 마스터 조회 | △ ATC 코드 부분 수집 |
| **질환 부담** | 국내 다빈도 질환 해당 | +15 | 키워드 매칭 (아래 목록) | O 적응증 텍스트 있음 |
| **특수 지정** | MFDS 희귀의약품 지정 | +10 | `RegulatoryApproval.is_orphan` (MFDS) | O 수집 중 |

### 3-2. 국내 다빈도 질환 키워드 (질환 부담 +15점)

심평원 다빈도 질환 통계 기반. 적응증 텍스트(indication)에서 매칭.

```python
KOREA_HIGH_BURDEN_KEYWORDS = [
    # 암 (사망원인 1위)
    "cancer", "neoplasm", "tumor", "oncolog", "leukemia", "lymphoma",
    "carcinoma", "melanoma", "myeloma",
    # 심뇌혈관 (사망원인 2, 4위)
    "hypertension", "stroke", "myocardial", "heart failure", "atrial fibrillation",
    "coronary", "thrombosis",
    # 당뇨 (유병률 상위)
    "diabetes", "insulin",
    # 호흡기 (다빈도)
    "asthma", "copd", "pneumonia",
    # 정신건강
    "depression", "schizophrenia", "bipolar", "anxiety",
    # 근골격 (고령화)
    "osteoporosis", "rheumatoid", "arthritis",
    # 감염
    "hepatitis", "hiv", "tuberculosis",
    # 신장
    "chronic kidney", "dialysis", "renal",
    # 희귀질환 (산정특례 대상)
    "rare disease", "orphan",
]
```

### 3-3. ATC 코드 기반 시장 존재 판단 (+15점)

현재 `GlobalRegulatoryStatus.atc_code`가 EMA 데이터에서 수집됨.
동일 ATC 3단계(약리학적 분류)에 HIRA 급여 약물이 있으면 = "이미 시장이 형성된 치료 영역".

```
예: atc_code = "L01FF" (PD-1 inhibitor)
    → ATC 3단계 "L01" (항암제)에 HIRA 급여 약물 다수 존재
    → +15점
```

**구현 방식:** HIRA 성분 마스터의 ATC 코드 목록을 메모리에 로드하고, 대상 약물의 ATC 3단계가 해당 목록에 존재하면 가산.

---

## 4. 기존 시스템과의 관계

### 4-1. global_score: 변경 없음

| 항목 | 값 |
|------|-----|
| 산정 로직 | 그대로 유지 (`HotIssueScorer.calculate_score()`) |
| 범위 | 0~100 |
| 용도 | "이 약의 글로벌 혁신성/중요도" |
| 파이프라인 임계값 | `MIN_SCORE_FOR_DB=10`, `MIN_SCORE_FOR_BRIEFING=40`, `MIN_SCORE_FOR_AI_PIPELINE=40` — 변경 없음 |

### 4-2. korea_relevance_score: 신규 추가

| 항목 | 값 |
|------|-----|
| 산정 시점 | `DomesticImpactAnalyzer.analyze()` 내부 (HIRA/CRIS 정보 확보 후) |
| 범위 | 0~100 |
| 저장 | `DrugDB.korea_relevance_score` (신규 컬럼) |
| 용도 | "이 약의 한국 시장 연관성" |

### 4-3. domestic_status: 유지

현재 `DomesticStatus` enum (REIMBURSED, IMMINENT, EXPECTED 등)은 **범주형 분류**로서 그대로 유지.
`korea_relevance_score`는 이 범주 내에서의 **수치적 정렬/비교**를 가능하게 하는 보완 지표.

```
예: IMMINENT 상태 약물이 3개 있을 때
    - 약물 A: korea_relevance = 85 (CRIS 2건 + HIRA 유사 약물 + 다빈도 질환)
    - 약물 B: korea_relevance = 55 (CRIS 1건)
    - 약물 C: korea_relevance = 40 (CRIS 1건, ATC 매칭 없음)
    → 약물 A를 가장 먼저 보여줘야 한다는 판단이 가능
```

---

## 5. 변경 대상 파일

| 파일 | 변경 내용 | 난이도 |
|------|----------|--------|
| `regscan/db/models.py` | `DrugDB.korea_relevance_score` 컬럼 추가 | 낮음 |
| `regscan/scan/domestic.py` | `DomesticImpact.korea_relevance_score` 필드 추가, `KoreaRelevanceScorer` 클래스 신규 | 중간 |
| `regscan/db/loader.py` | `_upsert_drug()` / `_upsert_drug_with_changes()`에 `korea_relevance_score` 저장 추가 | 낮음 |
| `regscan/api/schemas.py` | `DrugSummary`, `DrugDetail`에 `korea_relevance_score` 필드 추가 | 낮음 |
| `regscan/api/routes/drugs.py` | API 응답에 `korea_relevance_score` 포함 | 낮음 |
| `regscan/db/loader.py` | 변경 감지: `korea_relevance_score` 변경 시 `score_change` 기록 | 낮음 |

### 변경하지 않는 파일

| 파일 | 이유 |
|------|------|
| `regscan/map/global_status.py` | `global_score` 로직 유지 — 건드리지 않음 |
| `regscan/batch/pipeline.py` | 파이프라인 필터 임계값 변경 없음 (`MIN_SCORE_FOR_*`는 `global_score` 기준 유지) |
| `regscan/config/settings.py` | 임계값 상수 변경 없음 |

---

## 6. KoreaRelevanceScorer 클래스 설계

```python
# regscan/scan/domestic.py 에 추가

class KoreaRelevanceScorer:
    """한국 시장 연관성 점수 산정"""

    WEIGHTS = {
        "mfds_approved": 20,
        "hira_reimbursed": 20,
        "hira_deleted": 5,
        "cris_active": 15,
        "cris_multiple": 5,       # 2건 이상
        "atc_market_exists": 15,  # 동일 ATC 치료영역에 급여 약물 존재
        "high_burden_disease": 15,
        "mfds_orphan": 10,
    }

    def __init__(self, hira_atc_codes: set[str] | None = None):
        """
        Args:
            hira_atc_codes: HIRA 급여 약물의 ATC 3단계 코드 집합
                            (없으면 ATC 시장 존재 항목 스킵)
        """
        self._hira_atc_codes = hira_atc_codes or set()

    def calculate(self, impact: DomesticImpact, atc_code: str = "", indication: str = "") -> tuple[int, list[str]]:
        """
        Args:
            impact: 국내 영향 분석 결과
            atc_code: 약물의 ATC 코드 (EMA 소스)
            indication: 적응증 텍스트

        Returns:
            (점수, 사유 목록)
        """
        score = 0
        reasons = []

        # 1. MFDS 허가
        if impact.mfds_approved:
            score += self.WEIGHTS["mfds_approved"]
            reasons.append("MFDS 허가")

        # 2. HIRA 급여
        if impact.hira_status == ReimbursementStatus.REIMBURSED:
            score += self.WEIGHTS["hira_reimbursed"]
            reasons.append("HIRA 급여 등재")
        elif impact.hira_status == ReimbursementStatus.DELETED:
            score += self.WEIGHTS["hira_deleted"]
            reasons.append("HIRA 급여 삭제 이력")

        # 3. CRIS 임상
        if impact.has_active_trial:
            score += self.WEIGHTS["cris_active"]
            reasons.append(f"국내 임상시험 {len(impact.cris_trials)}건")
            if len(impact.cris_trials) >= 2:
                score += self.WEIGHTS["cris_multiple"]

        # 4. ATC 코드 기반 시장 존재
        if atc_code and len(atc_code) >= 3:
            atc_3level = atc_code[:3]
            if atc_3level in self._hira_atc_codes:
                score += self.WEIGHTS["atc_market_exists"]
                reasons.append(f"동일 치료영역({atc_3level}) 급여 약물 존재")

        # 5. 국내 다빈도 질환
        if indication and self._is_high_burden(indication):
            score += self.WEIGHTS["high_burden_disease"]
            reasons.append("국내 다빈도 질환")

        # 6. MFDS 희귀의약품
        if impact.mfds_approved:
            # mfds orphan 여부는 hot_issue_reasons에서 추정
            if any("희귀" in r for r in impact.hot_issue_reasons):
                score += self.WEIGHTS["mfds_orphan"]
                reasons.append("MFDS 희귀의약품")

        return min(score, 100), reasons

    @staticmethod
    def _is_high_burden(indication: str) -> bool:
        """적응증이 국내 다빈도 질환에 해당하는지 확인"""
        text = indication.lower()
        return any(kw in text for kw in KOREA_HIGH_BURDEN_KEYWORDS)
```

---

## 7. API 응답 변경

### 기존 DrugSummary 응답
```json
{
    "inn": "pembrolizumab",
    "global_score": 85,
    "hot_issue_level": "HOT",
    "domestic_status": "imminent"
}
```

### 변경 후 DrugSummary 응답
```json
{
    "inn": "pembrolizumab",
    "global_score": 85,
    "korea_relevance_score": 70,
    "hot_issue_level": "HOT",
    "domestic_status": "imminent",
    "quadrant": "top_priority"
}
```

### quadrant 값
| 값 | 조건 |
|----|------|
| `top_priority` | global >= 60 AND korea >= 50 |
| `watch` | global >= 60 AND korea < 50 |
| `track` | global < 60 AND korea >= 50 |
| `normal` | global < 60 AND korea < 50 |

---

## 8. 대시보드 활용 (향후)

### 정렬 옵션
- **기본 정렬:** `global_score` DESC (기존 유지, 혁신 신약 누락 방지)
- **국내 연관성 정렬:** `korea_relevance_score` DESC
- **종합 정렬:** `global_score * 0.6 + korea_relevance_score * 0.4` DESC (가중 합산)

### 필터 옵션
- 분면별 필터: "최우선만 보기", "주시 목록만 보기" 등
- 기존 `domestic_status` 필터와 병행

---

## 9. 리스크 및 한계

| 리스크 | 대응 |
|--------|------|
| ATC 코드 누락 (FDA 데이터에는 ATC 없음) | EMA 데이터의 ATC만 사용. 매칭 안 되면 해당 항목 스킵 (0점 가산) |
| HIRA ATC 마스터 로딩 비용 | 파이프라인 시작 시 1회 로드 (메모리 ~2MB, 성분 약 20,000건) |
| 다빈도 질환 키워드 관리 | 하드코딩 + settings.py로 오버라이드 가능하게 설계 |
| 점수 변경 시 change_detection 연동 | 기존 `score_change` 감지 로직에 `korea_relevance_score` 추가 |

---

## 10. 구현 우선순위

| 순서 | 작업 | 의존성 |
|------|------|--------|
| 1 | `DrugDB.korea_relevance_score` 컬럼 추가 | 없음 |
| 2 | `DomesticImpact.korea_relevance_score` 필드 추가 | 없음 |
| 3 | `KoreaRelevanceScorer` 클래스 구현 (ATC 매칭 제외) | #2 |
| 4 | `DomesticImpactAnalyzer.analyze()`에 scorer 통합 | #3 |
| 5 | `DBLoader`에 저장/변경감지 추가 | #1, #4 |
| 6 | API 스키마 + 엔드포인트 업데이트 | #1 |
| 7 | ATC 코드 기반 시장 매칭 (HIRA 마스터 로드) | #3 |
| 8 | 테스트 작성 | #3, #5 |

### 즉시 구현 가능 (외부 데이터 불필요)
- MFDS 허가 (+20), HIRA 급여 (+20/+5), CRIS 임상 (+15/+5), MFDS 희귀 (+10), 다빈도 질환 (+15)
- **이것만으로 최대 85점** — ATC 매칭 없이도 충분한 변별력

### 후속 구현 (HIRA ATC 마스터 필요)
- ATC 코드 기반 시장 존재 (+15)
