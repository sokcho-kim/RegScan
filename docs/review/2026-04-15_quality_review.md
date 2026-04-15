# 브리핑 품질 리뷰 — 2026-04-15

> GPT 팩트체크 + 구조 리뷰 결과 종합

## 핵심 진단

**"더 똑똑한 모델"보다 "더 엄밀한 상태 엔진"이 먼저다.**

현재 문제의 70%는 프롬프트가 아니라 입력 state/ontology 쪽이다.
모델이 말을 못 알아듣는 게 아니라, 입력 state가 빈약한데 그걸 말 잘하는 모델이 그럴듯하게 포장하는 것.

---

## 우선순위

### 1순위: 상태 모델 재설계

현재 HIRA 4단계(급여/비급여/삭제/확인자료없음)는 실무 의미 부족.

#### HIRA 상태 확장

| 현재 | 확장 |
|------|------|
| reimbursed | reimbursed (변동 없음) |
| not_covered | non_reimbursed |
| deleted | delisted |
| not_found | evaluation_history_exists |
| - | not_found_in_hira_source |
| - | bridge_unmatched |
| - | manual_review_required |

#### MFDS 상태 확장

| 현재 | 확장 |
|------|------|
| 허가 | approved |
| 미허가 | unapproved_confirmed |
| - | not_found (수집 누락 가능) |
| - | ambiguous_match |
| - | manual_review_required |

#### Match confidence

| 현재 | 확장 |
|------|------|
| normalized | exact_match |
| decomposed_variant | normalized_match |
| decomposed_base_fallback | base_fallback_match |
| atc | fuzzy_match |
| unmatched | unmatched |

**이유**: "진짜 없음" / "브리지 실패" / "수집 누락" / "삭제" / "평가 이력 있음"이 서로 다른데 결과물에서 비슷하게 보임. 이거 안 고치면 데이터 보강을 아무리 해도 오판 구조는 유지.

---

### 2순위: 데이터 보강 — "양"보다 "보강 위치"

#### A. HIRA 쪽

- 급여 적정성 심의 이력
- 삭제/변경 이력
- 산정특례/적응증 조건
- 규격 추가/삭제 이력

#### B. Bridge 쪽

- salt/ester/formulation alias
- 제품명 ↔ 성분명 보정 사전
- orphan/희귀약 전용 예외 사전
- unmatched 768건 분류 결과 재학습 자산화

#### C. Therapeutic context 쪽

- 국내 진료과/센터 맥락
- 대체약/동일 계열 약물
- 환자 수/진료권역
- 도입 사례

**핵심**: "브리핑이 잘 써지게" 보강이 아니라 "상태 판정이 정확해지게" 보강.

---

### 3순위: 웹서치 — 검증 계층으로 도입

**1차 truth**: 수집 DB + HIRA/MFDS 원천
**2차 verifier**: 웹서치
**3차 narrative**: LLM

웹서치는 "모르는 걸 채우는 도구"가 아니라 "내가 알고 있는 걸 재검증하는 도구".

---

### 4순위: 프롬프팅 미세조정

- fact / inference / recommendation 구분 출력
- confidence field 추가
- `bridge_unmatched`면 단정문 금지
- `not_found`와 `confirmed_unapproved` 구분
- 액션 아이템은 evidence 기반일 때만 강하게 제시

---

## 핵심 개선안

### A. 3층 출력 구조

| Layer | 내용 | 용도 |
|-------|------|------|
| Layer 1: Machine truth | raw name, matched ids, mfds/hira status, source date, evidence, confidence | 자동 판정 |
| Layer 2: Analyst note | 중요 포인트 3줄, manual review 필요 여부, 이유 | 전문가 검토 |
| Layer 3: Executive briefing | 사람이 읽는 문장 | 최종 발행 |

### B. 선별/브리핑 분리 평가

- **선별 평가**: 정말 이슈 약물인가, 누락 없는가, 실무 relevance
- **브리핑 평가**: facts 준수, 추론 분리, action item 적절성, 과장/할루시네이션

### C. 확정 문장 금지 규칙 (코드 강제)

| 상태 | 규칙 |
|------|------|
| bridge_unmatched | "매핑 실패로 확인 필요" |
| manual_review_required | "추가 확인 필요" |
| hira missing | 가격/급여 단정 금지 |
| mfds not_found | "미허가" 단정 금지 |

### D. 기준일 필수 노출

- FDA/EMA/MFDS snapshot date
- HIRA price snapshot date
- bridge/master version
- prompt version

---

## 실행 로드맵

### 바로 할 것

1. HIRA/MFDS/match 상태 enum 확장
2. `bridge_unmatched` 등 위험 상태 문장 가드레일 추가
3. output에 source date / confidence 표시

### 그 다음

4. unmatched 768건 재분류 자산화
5. HIRA 관련 보조 데이터 보강
6. 웹서치 verifier 추가

### 마지막

7. 프롬프트를 fact/inference/recommendation 분리형으로 수정
