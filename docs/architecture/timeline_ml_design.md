# Timeline ML 예측 모델 설계

> 작성일: 2026-02-03
> 목적: FDA/EMA 승인 → MFDS 허가까지의 소요 기간 예측

---

## 1. 핵심 철학

### 예측 표현 방식

| 방식 | 예시 | 위험도 | 채택 |
|------|------|--------|------|
| **회귀** | "2026년 3월 허가 예상" | 🔴 높음 | ❌ |
| **생존분석** | "24개월 내 허가 확률 62%" | 🟢 낮음 | ✅ |

### 이유

1. 규제는 **이산적 사건**(심사 중단, 보완요구, 정치적 이벤트)의 조합
2. 회귀는 "부드러운 평균"을 가정 → 규제 현실과 불일치
3. 틀렸을 때 **신뢰 박살** + 법적 리스크
4. 미허가 약물(검열 데이터)을 버리지 않고 학습 가능

### RegScan 표현 원칙

```
❌ "이 약은 2026년에 허가됩니다"
⭕ "동일 계열 기준, 24개월 내 MFDS 허가 확률은 60~70% 구간입니다"
```

---

## 2. 데이터 전략

### 역할 분담

| 데이터 | 역할 | 신뢰도 |
|--------|------|--------|
| **MFDS 전체 스캔** | y (정답 레이블) - 허가일 | 주력 |
| **openFDA** | 기준축 - FDA 승인일 | 1차 소스 |
| **EMA** | 기준축 - EMA 승인일 | 1차 소스 |
| **DrugBank** | x (피처) - INN, ATC, 기전 | 보조 |
| **ChEMBL** | x (피처) - 임상 단계, 타깃 | 보조 |

### MFDS 전체 스캔 한계

1. **노이즈 과다**: 제네릭/위탁/수입변경/재허가 다수 포함
2. **글로벌 매칭 불완전**: INN 없음, salt/formulation 차이
3. **급여 데이터 아님**: MFDS = 허가, HIRA = 급여 (별도 단계)

→ **필터링 파이프라인 필수**

---

## 3. 구현 순서

### Phase 1: 데이터 준비

```
1️⃣ MFDS 필터링 규칙 설계
   - 신약 판별 기준 정의
   - 제네릭/재허가/위탁 제외 로직
   - 최초 허가 여부 판별

2️⃣ 매칭 로직 고도화
   - INN 정규화 강화
   - salt/formulation 처리
   - 조합제 분리/태깅
   - 동의어 사전 확장
```

### Phase 2: 데이터 수집

```
3️⃣ MFDS 전체 수집
   - 284,477건 전체 스캔
   - 필터링 후 신약 추출

4️⃣ FDA/EMA 매칭
   - INN 기반 매칭
   - 매칭률 측정 및 개선

5️⃣ 외부 DB 연동 (보조)
   - DrugBank: ATC, 기전
   - openFDA: 신속심사 태그
```

### Phase 3: 모델 개발

```
6️⃣ Kaplan-Meier (baseline)
   - 계열별 생존곡선
   - ATC/기전/신속심사로 stratification

7️⃣ Cox Proportional Hazards
   - feature: ATC, 희귀질환, 신속심사, 글로벌 임상
   - 출력: Hazard Ratio, 24/36개월 내 event 확률
```

---

## 4. Feature 후보

### 약물 특성

| Feature | 출처 | 설명 |
|---------|------|------|
| `atc_level1` | EMA/DrugBank | 치료영역 (L=항암제 등) |
| `atc_level2` | EMA/DrugBank | 세부 분류 |
| `is_orphan` | EMA/FDA | 희귀의약품 여부 |
| `is_biologic` | DrugBank | 바이오의약품 여부 |
| `mechanism_class` | DrugBank/ChEMBL | 기전 분류 |

### 규제 지정

| Feature | 출처 | 설명 |
|---------|------|------|
| `fda_breakthrough` | openFDA | FDA Breakthrough 지정 |
| `fda_accelerated` | openFDA | FDA Accelerated Approval |
| `fda_priority` | openFDA | FDA Priority Review |
| `ema_prime` | EMA | EMA PRIME 지정 |
| `ema_conditional` | EMA | EMA 조건부 승인 |

### 시장 요인

| Feature | 출처 | 설명 |
|---------|------|------|
| `sponsor_type` | 파싱 | global_big_pharma / domestic |
| `has_korean_partner` | 추론 | 국내 파트너사 유무 |
| `competitor_count` | 분석 | 동일 적응증 경쟁 약물 수 |

### 타이밍

| Feature | 출처 | 설명 |
|---------|------|------|
| `fda_year` | openFDA | FDA 승인 연도 |
| `ema_year` | EMA | EMA 승인 연도 |
| `global_lag` | 계산 | FDA↔EMA 간 lag |

---

## 5. 출력 형식

### Survival Curve 기반

```python
{
    "inn": "pembrolizumab",
    "prediction": {
        "p_12m": 0.45,   # 12개월 내 허가 확률
        "p_24m": 0.72,   # 24개월 내 허가 확률
        "p_36m": 0.85,   # 36개월 내 허가 확률
        "median_days": 540,  # 중앙값 (50% 지점)
        "iqr": [320, 890],   # 사분위 범위
    },
    "similar_drugs": [
        {"name": "nivolumab", "actual_days": 91},
        {"name": "atezolizumab", "actual_days": 450},
    ],
    "factors": {
        "orphan_drug": "+15% faster",
        "ema_prime": "+10% faster",
        "global_big_pharma": "+8% faster",
    }
}
```

### UI 표현 예시

```
┌─────────────────────────────────────────────────┐
│ Pembrolizumab (키트루다)                         │
│                                                 │
│ MFDS 허가 예측 (EMA 승인 기준)                  │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│                                                 │
│ 12개월 내 허가 확률:  ████████░░░░░  45%        │
│ 24개월 내 허가 확률:  ██████████████░  72%      │
│ 36개월 내 허가 확률:  █████████████████  85%    │
│                                                 │
│ 예상 소요 기간: 약 18개월 (중앙값)              │
│ 범위: 10~29개월 (25~75 백분위)                  │
│                                                 │
│ 📊 유사 약물 사례:                              │
│   • 옵디보: 91일 (신속)                         │
│   • 테센트릭: 450일                             │
│                                                 │
│ 📈 유리한 요인:                                 │
│   • 희귀의약품 지정 (+15%)                      │
│   • EMA PRIME (+10%)                           │
└─────────────────────────────────────────────────┘
```

---

## 6. 현재 상태

### 완료

- [x] MFDS API 연동 (`ingest/mfds.py`)
- [x] MFDS 파서 (`parse/mfds_parser.py`)
- [x] EMA↔MFDS INN 매칭 기본 로직
- [x] Timeline 데이터 모델 (`map/timeline.py`)
- [x] 샘플 데이터 분석 (18건)

### 진행 필요

- [ ] MFDS 필터링 규칙 (신약 판별)
- [ ] 매칭 로직 고도화 (salt, 조합제)
- [ ] MFDS 전체 스캔 (284K건)
- [ ] 외부 DB 연동 (DrugBank, ChEMBL)
- [ ] Kaplan-Meier 분석
- [ ] Cox 모델 학습

---

## 7. 참고 자료

- Kaplan-Meier: https://en.wikipedia.org/wiki/Kaplan%E2%80%93Meier_estimator
- Cox Proportional Hazards: https://en.wikipedia.org/wiki/Proportional_hazards_model
- lifelines (Python): https://lifelines.readthedocs.io/

---

> 이 문서는 RegScan Timeline ML 예측 모델의 설계 문서입니다.
> 최종 업데이트: 2026-02-03
