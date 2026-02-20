# UI/UX 기사 포매팅 개선 계획

> 작성일: 2026-02-19
> 출처: Gemini 컨설턴트 피드백 3건 분석

---

## 피드백 요약

| # | 항목 | 핵심 | 난이도 |
|---|------|------|--------|
| 1 | 하이퍼링크/출처 | 약물명에 FDA/CT.gov 링크, 동적 출처 | 높음 |
| 2 | 대소문자 일관성 | ALL CAPS vs lowercase → Title Case 통일 | 중간 |
| 3 | 한국어 현지화 | MFDS→식약처, HIRA→심평원, 의학약어 툴팁 | 중간 |

**권장 구현 순서**: 2번 (가장 기초적) → 3번 (추가적 후처리) → 1번 (가장 구조적)

---

## 피드백 1: 하이퍼링크/출처 (Trustability)

### 현재 상태

- 생성된 HTML 기사에 하이퍼링크가 **전무**
- 약물명, FDA 승인일, EMA 승인일, NCT ID 모두 일반 텍스트
- 출처는 푸터에 일반적 텍스트만 존재:
  ```html
  <strong>데이터 출처:</strong> FDA Drug Approvals Database, EMA Public Assessment Reports, ...
  ```

### 이미 존재하지만 미사용인 URL

| 데이터 | 현재 위치 | 비고 |
|--------|----------|------|
| FDA source_url | `RegulatoryEventDB.source_url` | FDA DAF 페이지 링크 |
| EMA source_url | `RegulatoryEventDB.source_url` | EMA EPAR 페이지 링크 |
| CT.gov NCT ID | `_fetch_ctgov_results_batch()` | `https://clinicaltrials.gov/study/{nct_id}` |
| FDA application_number | `RegulatoryEventDB.application_number` | URL 생성 가능 |

### 변경 필요 파일

| 파일 | 변경 내용 |
|------|----------|
| `regscan/scripts/publish_articles.py` | (A) `_build_timeline_html()`에 하이퍼링크 추가 (B) `_build_sources_html()` 동적 출처 생성 함수 추가 (C) `ARTICLE_HTML_TEMPLATE` 푸터에 `{sources_html}` 자리표시자 (D) `load_drugs_from_db()`에서 `source_url` 전달 |
| `regscan/report/llm_generator.py` | `_prepare_drug_data()`에 기관별 `source_url` 포함 |
| `regscan/report/prompts.py` | LLM에게 `[텍스트](url)` 마크다운 링크 사용 지시 |

### 구현 방향

- `load_drugs_from_db()`에서 각 `RegulatoryEventDB` 이벤트의 `source_url` 추출 → `source_data` dict 구성
- `_build_sources_html()`: FDA DAF 페이지, EMA EPAR 페이지, CT.gov NCT 링크를 클릭 가능한 링크로 생성
- 타임라인 각 항목도 해당 출처로 링크
- 푸터의 정적 텍스트를 약물별 동적 링크로 대체

---

## 피드백 2: 대소문자 일관성

### 현재 상태

약물명 대소문자가 **완전히 불일관**:
- **ALL CAPS**: `POLATUZUMAB VEDOTIN` (FDA API 원본)
- **lowercase**: `polatuzumab vedotin` (EMA API 원본)
- **중복 항목**: 같은 약물이 `POLATUZUMAB VEDOTIN` (60점)과 `polatuzumab vedotin` (50점)으로 **별도 존재**

### 근본 원인

1. FDA API → `generic_name` ALL CAPS 반환
2. EMA API → `inn` lowercase/mixed 반환
3. `global_status.py`에서 INN 할당 시 FDA 우선 → ALL CAPS
4. **어디서도 대소문자 정규화 없음**
5. `DrugDB.normalized_name` 필드 존재하나 실제로 미사용

### 변경 필요 파일

| 파일 | 변경 내용 |
|------|----------|
| `regscan/scripts/publish_articles.py` | `_display_inn()` 헬퍼 함수 추가, `generate_article_html()`과 `generate_index_html()`에서 사용 |
| `regscan/report/llm_generator.py` | `_prepare_drug_data()`에서 INN Title Case 정규화 후 LLM 전달 |
| `regscan/report/prompts.py` | "약물 INN은 Title Case로 표기" 규칙 추가 |
| `regscan/map/global_status.py` | INN 추출 시점에서 `_to_title_case()` 적용 (선택) |
| `regscan/db/loader.py` | `_upsert_drug()`에서 INN Title Case 정규화 후 저장 (선택) |

### Title Case 규칙

```python
def to_display_case(inn: str) -> str:
    """INN을 표시용 케이스로 변환.

    규칙:
    - 메인 단어: Title Case (Polatuzumab Vedotin)
    - 하이픈 뒤 USAN 생물학적 접미사: lowercase (-piiq, -hrii, -csrk)

    예시:
        "POLATUZUMAB VEDOTIN-PIIQ" → "Polatuzumab Vedotin-piiq"
        "ZANIDATAMAB-HRII" → "Zanidatamab-hrii"
        "polatuzumab vedotin" → "Polatuzumab Vedotin"
    """
```

### 안전한 접근

- **최소 침습**: `publish_articles.py`에서만 표시용 정규화 (DB/파이프라인 변경 없음)
- **근본 해결**: `global_status.py`에서 INN 추출 시 정규화 (모든 하류 소비자 영향)

---

## 피드백 3: 한국어 현지화

### 현재 상태

- 규제기관 약어가 영어 그대로 사용: "MFDS", "HIRA"
- 의학 약어 (DLBCL, ADC, PFS 등) `<abbr>` 태그 없이 일반 텍스트
- 푸터에서 일부 한국어 병기 있으나 비일관적

### 예시 (현재 vs 개선)

**현재**: `MFDS의 허가를 받지 못한 상태이며 HIRA에서 비급여로`

**개선**: `<abbr title="식품의약품안전처">식약처(MFDS)</abbr>의 허가를 받지 못한 상태이며 <abbr title="건강보험심사평가원">심평원(HIRA)</abbr>에서 비급여로`

### 변경 필요 파일

| 파일 | 변경 내용 |
|------|----------|
| `regscan/scripts/publish_articles.py` | (A) `abbr` CSS 스타일 추가 (B) `_inject_abbr_tags(html)` 후처리 함수 추가 (C) 타임라인 "MFDS 허가" → "식약처(MFDS) 허가" (D) 푸터 한국어 우선 표기 |
| `regscan/report/prompts.py` | "한국 규제기관은 첫 등장 시 한글 명칭(약어) 형태로 기재" 규칙 추가 |
| `regscan/report/llm_generator.py` | `_generate_fallback()`에서 기관명 일관성 확보 |

### 약어 사전

```python
ABBR_DICT = {
    # 규제기관 (한국어 우선 표기)
    "MFDS": ("식약처", "식품의약품안전처, Ministry of Food and Drug Safety"),
    "HIRA": ("심평원", "건강보험심사평가원, Health Insurance Review & Assessment Service"),

    # 의학 약어 (툴팁만)
    "DLBCL": (None, "미만성 거대 B세포 림프종, Diffuse Large B-Cell Lymphoma"),
    "ADC":   (None, "항체-약물 접합체, Antibody-Drug Conjugate"),
    "PFS":   (None, "무진행생존기간, Progression-Free Survival"),
    "OS":    (None, "전체생존기간, Overall Survival"),
    "ORR":   (None, "객관적 반응률, Objective Response Rate"),
    "NSCLC": (None, "비소세포폐암, Non-Small Cell Lung Cancer"),
    "CAR-T": (None, "키메라 항원 수용체 T세포, Chimeric Antigen Receptor T-cell"),
    "AML":   (None, "급성 골수성 백혈병, Acute Myeloid Leukemia"),
    "PAH":   (None, "폐동맥 고혈압, Pulmonary Arterial Hypertension"),
    "MCL":   (None, "외투세포 림프종, Mantle Cell Lymphoma"),
    "ALL":   (None, "급성 림프구 백혈병, Acute Lymphoblastic Leukemia"),
    "HER2":  (None, "인간 표피성장인자 수용체 2, Human Epidermal Growth Factor Receptor 2"),
    "DMD":   (None, "뒤센형 근디스트로피, Duchenne Muscular Dystrophy"),
}
```

### 후처리 함수 동작

1. **규제기관** (한국어 접두어 있음): 첫 등장의 "MFDS" → `<abbr title="식품의약품안전처">식약처(MFDS)</abbr>`, 이후 → `<abbr title="식품의약품안전처">식약처</abbr>`
2. **의학 약어** (툴팁만): "DLBCL" → `<abbr title="미만성 거대 B세포 림프종">DLBCL</abbr>`
3. 적용 위치: `generate_article_html()` 최종 HTML 조립 직후

---

## 영향 받는 파일 종합

| # | 파일 | 피드백 항목 |
|---|------|-----------|
| 1 | `regscan/scripts/publish_articles.py` | 1, 2, 3 |
| 2 | `regscan/report/llm_generator.py` | 1, 2, 3 |
| 3 | `regscan/report/prompts.py` | 1, 2, 3 |
| 4 | `regscan/map/global_status.py` | 2 |
| 5 | `regscan/map/matcher.py` | 2 |
| 6 | `regscan/db/loader.py` | 2 |

---

## 구현 일정 (권장)

| 순서 | 피드백 | 예상 작업량 | 이유 |
|------|--------|-----------|------|
| 1차 | 대소문자 일관성 (#2) | 소 | 가장 기초적, 파이프라인 데이터 품질에 직접 영향 |
| 2차 | 한국어 현지화 (#3) | 중 | HTML 후처리로 추가적, 기존 코드 깨뜨리지 않음 |
| 3차 | 하이퍼링크/출처 (#1) | 대 | 파이프라인 전체에 URL 데이터 전달 필요, 가장 구조적 |
