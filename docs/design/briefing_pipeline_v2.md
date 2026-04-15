# 브리핑 파이프라인 V2 — 팩트카드 기반 재설계

> 확정일: 2026-04-16
> 상태: 설계 완료, 구현 미착수

## 핵심 원칙

**LLM은 팩트를 만들지 않는다. 코드가 팩트를 만들고, LLM은 문장으로 바꾸기만 한다.**

---

## 4-Step 구조

```
Step 1: 코드 → 개별 팩트카드 JSON (LLM 없음)
Step 2: 팩트카드 N개 → LLM → 트렌드/교차분석 (인사이트만)
Step 3: 트렌드 + 팩트카드 → LLM → 최종 기사 (문장화만)
Step 4: 코드 → Validator → 사실/표현 검증 (LLM 없음)
```

---

## Step 1: Fact Card Generator

### 파일: `regscan/stream/fact_card.py` (신규)

LLM 호출 없음. 순수 코드.

### ALLOWED_PHRASES 매트릭스

#### HIRA (상태 × 신뢰도 → 고정 문구)

| 상태 | 신뢰도 | 문구 |
|------|--------|------|
| REIMBURSED | EXACT | 심평원 급여 등재 확인 (상한가 {price}원) |
| REIMBURSED | NORMALIZED | 심평원 급여 등재 확인 (상한가 {price}원, 정규화 매칭) |
| REIMBURSED | BASE_FALLBACK | 심평원 급여 등재 추정 — 매칭 신뢰도 낮음, 수동 확인 필요 |
| REIMBURSED | ATC_FALLBACK | 심평원 급여 등재 추정 — ATC 기반 매칭, 수동 확인 필요 |
| NON_REIMBURSED | * | 심평원 비급여 (전액 환자부담) |
| DELISTED | * | 심평원 급여 삭제 (과거 등재 이력) |
| NOT_FOUND | * | 심평원 원천 데이터 미확인 — 미등재 또는 수집 누락 가능 |
| BRIDGE_UNMATCHED | * | 심평원 매핑 실패 — 급여/가격 정보 확인 불가 |
| HERBAL | * | 한약재/생약 (별도 급여 체계) |

#### MFDS

| 상태 | 조건 | 문구 |
|------|------|------|
| APPROVED | 허가일 있음 | 국내 식약처 허가 완료 ({date}) |
| APPROVED | 허가일 없음 | 국내 식약처 허가 확인 (허가일 미확인) |
| UNAPPROVED_CONFIRMED | - | 국내 식약처 미허가 확인 |
| NOT_FOUND | - | 국내 식약처 허가 여부 추가 확인 필요 |
| AMBIGUOUS_MATCH | - | 국내 식약처 허가 정보 모호 — 수동 확인 필요 |

#### FDA

| 상태 | 조건 | 문구 |
|------|------|------|
| AP | date < today | {date} FDA 승인 완료 |
| AP | date >= today | {date} FDA 승인 예정 |
| TA | - | FDA 잠정 승인 |
| 없음 | PDUFA 있음 | PDUFA {pdufa_date} 심사 예정 |
| 없음 | PDUFA 없음 | FDA 승인일 미정 |

### FactCard 스키마

```python
@dataclass
class FactCard:
    inn: str
    generated_at: str

    # 기관별 코드 확정 문구
    fda_phrase: str
    ema_phrase: str
    mfds_phrase: str
    hira_phrase: str

    # 상세
    fda_date: str | None
    ema_date: str | None
    mfds_date: str | None
    hira_price: float | None
    hira_confidence: str            # MatchConfidence value
    hira_source_date: str
    hira_evidence_type: str         # exact_price_match / board_missing / bridge_unmatched / source_not_loaded
    ema_designations: list[str]
    copay_phrase: str | None
    access_phrase: str | None

    # 가드레일
    is_guardrailed: bool
    guardrail_notes: list[str]

    # LLM 컨텍스트용 (팩트 아닌 배경)
    brand_name: str
    moa: str
    indication: str
    therapeutic_areas: list[str]
    atc_code: str

    def to_compact_dict(self) -> dict:
        """LLM 입력용 ~10줄 JSON"""

    @property
    def all_fact_phrases(self) -> list[str]:
        """최종 기사에 포함되어야 할 문구 목록"""

    @property
    def hard_check_values(self) -> dict:
        """날짜/가격/상태 — exact match 대상"""
```

---

## Step 2: Trend Analyzer

### 파일: `regscan/stream/trend_analyzer.py` (신규)

LLM 1회 호출. 짧은 컨텍스트.

### 입력
- 팩트카드 N개의 `to_compact_dict()` (~10줄/약물, 최대 100줄)
- stream/unified 구분 없이 동일 구조 (범위만 다름)

### 출력
```json
{
  "trends": [{"pattern": str, "drugs": [str], "significance": str}],
  "cross_stream_signals": [{"drug": str, "streams": [str]}],
  "key_insight": str
}
```

### 프롬프트 규칙
- "DO NOT state drug approval status, prices, or regulatory facts."
- "Those are already determined. Only identify patterns."

---

## Step 3: Article Writer

### 파일: `regscan/stream/briefing.py` (리팩터)

LLM 1회 호출. 팩트카드 + 트렌드를 입력.

### 규칙
- 팩트 문구(Step 1)를 그대로 사용
- LLM은 문장 연결 + 구조화만 담당
- action item 톤: "확인 필요", "검토 권고" (명령형 금지)
- orphan → "orphan 지정 약물" (희귀질환 일반화 금지)

### Unified Briefing
- 별도 수정 불필요
- Step 2에 전체 팩트카드 top 5를 넣으면 동일 구조
- 현재: 33,000자 → 변경: ~200줄

---

## Step 4: Validator

### 파일: `regscan/stream/fact_validator.py` (신규)

LLM 호출 없음. 순수 코드.

### 2단계 체크

#### 하드 체크 (exact match)
- 날짜: 팩트카드에 없는 YYYY-MM-DD 패턴 → 위반
- 가격: 팩트카드 가격과 불일치 → 위반
- 상태: "급여 등재"/"미허가" 등이 팩트카드와 불일치 → 위반
- 가드레일 약물에 단정문 사용 → 위반

#### 소프트 체크 (semantic 허용)
- 문장 표현은 의미 동일하면 허용
- 한국어 조사/어순 차이 감안
- verbatim 강제는 숫자/상태에만

### 위반 처리 (자동 교정 금지)

```
위반 감지
  → 해당 문단 폐기
  → fallback fact-only 문단 삽입
  → 위반 로그 기록
```

"몰래 고치기" 금지. silent corruption 방지.

---

## hira_evidence_type

NON_REIMBURSED / NOT_FOUND 판정 시 근거 출처:

| 값 | 의미 |
|----|------|
| exact_price_match | 약가 파일에서 직접 매칭 |
| board_missing | 마스터에 있으나 약가 없음 |
| bridge_unmatched | 브릿지 매칭 실패 |
| source_not_loaded | 약가 파일 자체 미로드 |

---

## 데이터 흐름

```
drug_dict (StreamResult.drugs_found)
    │
    ▼
[Step 1] generate_fact_card(drug, today)     ← 코드, LLM 없음
    │
    ▼
FactCard JSON (~10줄/약물)
    │
    ├─[Step 2] analyze_trends(fact_cards)     ← LLM 1회
    │      입력: ~100줄, 출력: ~30줄
    ▼
Trend JSON
    │
    ├─[Step 3] write_article(fact_cards, trends) ← LLM 1회
    │      팩트 문구 verbatim 사용
    ▼
Raw Briefing JSON
    │
    ├─[Step 4] validate_briefing(briefing, fact_cards) ← 코드, LLM 없음
    │      하드 체크 → 소프트 체크 → 위반 시 폐기+fallback
    ▼
Validated Briefing → DB

Unified: 전체 팩트카드 top 5 → Step 2 → Step 3 → Step 4
```

---

## 마이그레이션

| Phase | 내용 |
|-------|------|
| A | `ENABLE_FACT_CARD_PIPELINE` 플래그로 기존/신규 병렬 실행 |
| B | 신규 기본값 전환 |
| C | 레거시 제거 (`_extract_drug_intel()`, 기존 프롬프트 템플릿) |

---

## 일정

| Step | 소요 | 의존 |
|------|------|------|
| Step 1: Fact Card Generator | 2-3일 | 없음 |
| Step 2: Trend Analyzer | 1-2일 | Step 1 |
| Step 3: Article Writer 리팩터 | 2-3일 | Step 1, 2 |
| Step 4: Validator | 2일 | Step 1 |
| 마이그레이션 + 테스트 | 2-3일 | 전체 |
| **합계** | **10-15일** |
