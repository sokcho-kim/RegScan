# 글로벌 규제기관 API/데이터 소스 조사 리포트

> 작성일: 2026-02-03
> 목적: FDA 외 글로벌 규제기관 데이터 연동 가능성 조사

---

## Executive Summary

| 기관 | API 제공 | 데이터 형식 | 연동 난이도 | 우선순위 |
|------|----------|-------------|-------------|----------|
| **EMA** | ✅ JSON API (16개) | JSON, XLSX | 🟢 쉬움 | 🔴 1순위 |
| **WHO ATC** | ❌ 없음 | 웹/유료 | 🟡 중간 | 🟡 2순위 |
| **WHO EML** | ⚠️ 제한적 | PDF, eEML DB | 🟡 중간 | 🟡 2순위 |
| **PMDA** | ❌ 없음 | PDF (일본어) | 🔴 어려움 | 🟢 3순위 |

**결론**: EMA를 1순위로 즉시 연동하고, WHO ATC는 GitHub 스크래퍼 활용, PMDA는 KEGG DRUG 대체 검토

---

## 1. EMA (유럽 의약품청)

### 1.1 개요
- **공식 사이트**: https://www.ema.europa.eu
- **데이터 포털**: https://www.ema.europa.eu/en/medicines/download-medicine-data
- **JSON API**: https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format

### 1.2 제공 데이터

#### JSON API 엔드포인트 (16개)

| 카테고리 | 엔드포인트 | 주요 필드 |
|----------|-----------|-----------|
| **Medicines** | `/medicines-output-medicines_json-report_en.json` | name, INN, ATC_code, therapeutic_area, MAH, approval_date |
| **Orphan Designations** | `/medicines-output-orphan_designations-json-report_en.json` | medicine_name, active_substance, designation_date, status |
| **Post-Auth** | `/medicines-output-post_authorisation_json-report_en.json` | variations, withdrawn applications |
| **Referrals** | `/referrals-output-json-report_en.json` | referral_name, INN, safety_referral, status |
| **PIPs** | `/medicines-output-paediatric_investigation_plans-output-json-report_en.json` | decision_number, active_substance, condition |
| **PSUSAs** | `/periodic_safety_update_report_single_assessments-output-json-report_en.json` | active_substances, regulatory_outcome |
| **DHPCs** | `/dhpc-output-json-report_en.json` | medicine_name, dhpc_type, dissemination_date |
| **Shortages** | `/shortages-output-json-report_en.json` | medicine_affected, shortage_status, alternatives |
| **Documents** | `/documents-output-json-report_en.json` | name, type, published_date |
| **EPAR Docs** | `/documents-output-epar_documents_json-report_en.json` | documents with translations |
| **Herbal** | `/medicines-output-herbal_medicines-report-output-json_en.json` | latin_name, therapeutic_area |
| **Outside EU** | `/medicine-use-outside-eu-output-json-report_en.json` | Article 58 opinions |
| **News** | `/news-json-report_en.json` | title, summary, categories |
| **Events** | `/events-json-report_en.json` | title, date, location |
| **General** | `/general-json-report_en.json` | guidance, information |

**Base URL**: `https://www.ema.europa.eu/en/documents/report/`

### 1.3 데이터 특성

- **업데이트 주기**: 하루 2회 (06:00, 18:00 CET)
- **포맷**: JSON, XLSX
- **인증**: 불필요 (공개 API)
- **Rate Limit**: 명시되지 않음
- **데이터량**: 2,641+ EU 승인 의약품

### 1.4 핵심 필드 (Medicines)

```json
{
  "category": "Human",
  "name_of_medicine": "Leqembi",
  "ema_product_number": "EMEA/H/C/005981",
  "medicine_status": "Authorised",
  "INN": "lecanemab",
  "active_substance": "lecanemab",
  "therapeutic_area_mesh": "Alzheimer Disease",
  "ATC_code": "N07XX23",
  "marketing_authorisation_holder": "Eisai GmbH",
  "european_commission_decision_date": "2024-07-24",
  "therapeutic_indication": "Treatment of early Alzheimer's disease..."
}
```

### 1.5 MCP 서버 (비공식)

- **GitHub**: https://github.com/openpharma-org/ema-mcp
- **기능**: 14개 메서드, 통합 검색, 필터링
- **활용**: MCP 호환 시스템에서 직접 사용 가능

### 1.6 구현 계획

```python
# regscan/ingest/ema.py (예시)
EMA_ENDPOINTS = {
    "medicines": "/medicines-output-medicines_json-report_en.json",
    "orphan": "/medicines-output-orphan_designations-json-report_en.json",
    "shortages": "/shortages-output-json-report_en.json",
}

async def fetch_ema_medicines():
    url = f"{EMA_BASE_URL}{EMA_ENDPOINTS['medicines']}"
    response = await httpx.get(url)
    return response.json()
```

### 1.7 평가

| 항목 | 점수 | 비고 |
|------|------|------|
| API 품질 | ⭐⭐⭐⭐⭐ | JSON, 구조화, 풍부한 필드 |
| 문서화 | ⭐⭐⭐⭐ | 공식 문서 존재, 필드 설명 |
| 데이터 범위 | ⭐⭐⭐⭐⭐ | 중앙 승인 의약품 전체 |
| 접근성 | ⭐⭐⭐⭐⭐ | 무료, 인증 불필요 |
| **종합** | **🟢 즉시 연동 권장** | FDA 다음 1순위 |

---

## 2. WHO ATC/DDD

### 2.1 개요

- **공식 사이트**: https://www.whocc.no/atc_ddd_index/
- **관리기관**: WHO Collaborating Centre for Drug Statistics Methodology (노르웨이)
- **현재 버전**: ATC/DDD Index 2026

### 2.2 데이터 접근 방법

#### 방법 1: 공식 유료 구매 (€200)
- 전체 ATC-DDD 인덱스 Excel 파일
- 연간 업데이트
- 상업적 사용 가능

#### 방법 2: 웹 스크래핑 (무료)
- **GitHub 도구**: https://github.com/fabkury/atcd
- 전체 ATC 클래스를 CSV로 추출
- 정기적 업데이트 필요

#### 방법 3: BioPortal API
- https://bioportal.bioontology.org/ontologies/ATC
- 온톨로지 형식, 파싱 필요

### 2.3 ATC 코드 구조

```
A       - 1st level (Anatomical main group)
A10     - 2nd level (Therapeutic main group)
A10B    - 3rd level (Therapeutic/pharmacological subgroup)
A10BA   - 4th level (Chemical/therapeutic/pharmacological subgroup)
A10BA02 - 5th level (Chemical substance) → Metformin
```

### 2.4 구현 계획

```python
# 방법 1: GitHub CSV 활용
ATC_CSV_URL = "https://raw.githubusercontent.com/fabkury/atcd/master/atc.csv"

def load_atc_codes():
    df = pd.read_csv(ATC_CSV_URL)
    return df.set_index('atc_code').to_dict('index')
```

### 2.5 평가

| 항목 | 점수 | 비고 |
|------|------|------|
| API 품질 | ⭐⭐ | 공식 API 없음 |
| 문서화 | ⭐⭐⭐ | 웹사이트 검색 가능 |
| 데이터 범위 | ⭐⭐⭐⭐⭐ | 글로벌 표준 약물 분류 |
| 접근성 | ⭐⭐⭐ | 유료 또는 스크래핑 |
| **종합** | **🟡 GitHub 스크래퍼 활용** | 보조 데이터로 활용 |

---

## 3. WHO Essential Medicines List (EML)

### 3.1 개요

- **공식 사이트**: https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists
- **현재 버전**: 24th EML (2025년 9월)
- **약물 수**: 523개

### 3.2 데이터 접근 방법

#### 방법 1: eEML 온라인 데이터베이스 (권장)
- **URL**: https://list.essentialmeds.org/
- 검색 가능한 온라인 DB
- 2025년 업데이트 반영 중

#### 방법 2: PDF 다운로드
- **URL**: https://www.who.int/publications/i/item/B09474
- 공식 문서, 구조화되지 않음

#### 방법 3: WHO Prequalified Medicines (CSV)
- **URL**: https://extranet.who.int/prequal/medicines/prequalified/finished-pharmaceutical-products/export?page=&_format=csv
- EML과 별개이나 관련 데이터

### 3.3 핵심 정보

- 필수 의약품 지정 여부
- 치료 카테고리 (4th level ATC 기반)
- 핵심/보완 분류 (Core/Complementary)

### 3.4 구현 계획

```python
# eEML 웹 스크래핑 또는 PDF 파싱
def is_essential_medicine(drug_name: str, eml_data: dict) -> bool:
    normalized = normalize_drug_name(drug_name)
    return normalized in eml_data
```

### 3.5 평가

| 항목 | 점수 | 비고 |
|------|------|------|
| API 품질 | ⭐⭐ | 공식 API 없음 |
| 문서화 | ⭐⭐⭐⭐ | PDF 상세 문서 |
| 데이터 범위 | ⭐⭐⭐⭐ | 글로벌 필수 의약품 |
| 접근성 | ⭐⭐⭐ | eEML DB 활용 |
| **종합** | **🟡 eEML 스크래핑** | 핫이슈 스코어링용 |

---

## 4. PMDA (일본 의약품의료기기종합기구)

### 4.1 개요

- **공식 사이트**: https://www.pmda.go.jp/english/
- **승인 목록**: https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0002.html

### 4.2 데이터 접근 현황

| 항목 | 상태 |
|------|------|
| 공개 API | ❌ 없음 |
| 데이터 형식 | PDF (2.98MB) |
| 언어 | 일본어 위주, 영문 제한적 |
| 업데이트 | ~2025년 6월까지 데이터 |

### 4.3 대안: KEGG DRUG

- **URL**: https://www.genome.jp/kegg/drug/br08318.html
- 일본 신약 승인 정보
- 영문/일본어 병기
- 구조화된 데이터

### 4.4 주요 변경 사항 (2026)

- **2026년 4월**: eCTD v4.0 필수화
- **2024년 9월**: 영문 Module 1-2 제출 허용 (일본 법인 없는 경우)

### 4.5 구현 계획

```python
# KEGG DRUG 활용 (우회)
KEGG_DRUG_URL = "https://www.genome.jp/kegg/drug/br08318.html"

def fetch_pmda_approvals():
    # KEGG DRUG 파싱 또는
    # PMDA PDF 파싱 (OCR 필요)
    pass
```

### 4.6 평가

| 항목 | 점수 | 비고 |
|------|------|------|
| API 품질 | ⭐ | API 없음 |
| 문서화 | ⭐⭐ | 영문 제한적 |
| 데이터 범위 | ⭐⭐⭐⭐ | 일본 승인 전체 |
| 접근성 | ⭐⭐ | PDF, 일본어 |
| **종합** | **🔴 후순위** | KEGG DRUG 대체 검토 |

---

## 5. 구현 우선순위 및 로드맵

### 5.1 우선순위

| 순위 | 기관 | 이유 | 예상 공수 |
|------|------|------|-----------|
| **1** | EMA | JSON API 제공, 즉시 연동 가능 | 1-2일 |
| **2** | WHO ATC | GitHub CSV 활용, 약물 분류 필수 | 0.5일 |
| **3** | WHO EML | 핫이슈 스코어링 보조 | 1일 |
| **4** | PMDA | KEGG 대체, 일본 시장 낮은 우선순위 | 2-3일 |

### 5.2 구현 로드맵

```
Week 6 (02/03-07)
├── Day 1: EMA API 클라이언트 구현
├── Day 2: EMA 데이터 파서 + DB 저장
├── Day 3: WHO ATC CSV 연동
├── Day 4: GlobalRegulatoryStatus 모델
└── Day 5: 테스트 + 문서화

Week 7
├── WHO EML 연동
├── 핫이슈 스코어링 통합
└── PMDA (선택)
```

### 5.3 데이터 모델 통합

```python
@dataclass
class GlobalRegulatoryStatus:
    drug_id: str          # INN 기준

    # 기관별 상태
    fda: Optional[Approval]   # ✅ 구현됨
    ema: Optional[Approval]   # 🔄 이번 주
    pmda: Optional[Approval]  # ⬜ 후순위
    mfds: Optional[Approval]  # ✅ 구현됨

    # WHO 지정
    atc_code: Optional[str]   # 🔄 이번 주
    who_eml: bool             # ⬜ 다음 주

    # 분석
    global_score: int
    hot_issue: bool
```

---

## 6. 참고 자료

### 공식 문서
- [EMA Download Medicine Data](https://www.ema.europa.eu/en/medicines/download-medicine-data)
- [EMA JSON API Documentation](https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format)
- [WHO ATC/DDD Index 2026](https://atcddd.fhi.no/atc_ddd_index/)
- [WHO Essential Medicines List](https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists)
- [eEML Database](https://list.essentialmeds.org/)
- [PMDA English](https://www.pmda.go.jp/english/)

### 도구/라이브러리
- [EMA MCP Server (GitHub)](https://github.com/openpharma-org/ema-mcp)
- [ATC Scraper (GitHub)](https://github.com/fabkury/atcd)
- [KEGG DRUG](https://www.genome.jp/kegg/drug/br08318.html)

---

## 7. 결론

1. **EMA 즉시 연동**: JSON API 완비, FDA와 동급 품질
2. **WHO ATC 병행**: 약물 분류 표준화에 필수
3. **PMDA 후순위**: 데이터 접근성 낮음, 대안 검토 필요

**다음 액션**: EMA API 클라이언트 구현 시작 (`regscan/ingest/ema.py`)
