# 기사 깊이 강화 계획

> 2026-04-24 | 엔리칭 v2 적용 후 "더 깊은 기사"를 위한 데이터 파이프 설계

---

## 현재 상태 (v2)

| 소스 | 엔리칭 | 한계 |
|------|--------|------|
| NICE TA | Excel 권고 결과만 | 심사 요약 없음, 영국만 |
| 국회 법안 | Playwright로 제안이유 (상위 3건) | 조문 요약 없음, 원문 링크만 |
| KIPRIS 특허 | 타겟→FDA label 참조 약물 | 청구항 없음, 임상 연결 없음 |
| PMDA 승인 | openFDA label | 일본 자체 심사 정보 없음 |
| EMA | 수집만 | 심사 보고서(EPAR) 미연결 |

---

## 1. 규제 심사 정보 — 어떤 나라든 시그널이면 심사 요약 제공

### 목표
NICE뿐 아니라 FDA·EMA·PMDA·MFDS 어디서 시그널이 잡히든, 해당 약물의 **글로벌 심사 이력**을 크로스레퍼런스로 제공.

### 설계: 약물명 기반 멀티소스 심사 조회

```
시그널 (어디서든) → 약물명(INN) 추출
                    ↓
        ┌──────────┼──────────┬──────────┐
        ↓          ↓          ↓          ↓
    openFDA     EMA EPAR    PMDA 심사   MFDS 허가
    label       요약        보고서      상세
```

### 소스별 구현

#### A. openFDA (이미 구현)
- endpoint: `api.fda.gov/drug/label.json`
- 필드: indications, dosage, clinical_studies, adverse_reactions, boxed_warning
- **추가할 것**: `api.fda.gov/drug/drugsfda.json`에서 **승인 이력(submissions)** — 승인일, 리뷰 유형(Priority/Standard), 스폰서

#### B. EMA EPAR 요약
- **현재**: EMA 수집기(`regscan/ingest/ema.py`)에서 승인 정보만
- **추가할 것**: 개별 의약품 EPAR(European Public Assessment Report) 페이지
- endpoint: `https://www.ema.europa.eu/en/medicines/human/EPAR/{product-name}`
- 데이터: 승인일, 적응증, 치료영역, **ATC 코드, 승인 조건, 심사 요약(assessment summary)**
- 구현: httpx로 EPAR 페이지 크롤링 → 요약 섹션 추출
- 난이도: **중간** — URL 패턴이 제품명 기반이라 INN→제품명 매핑 필요

#### C. PMDA 심사보고서
- **현재**: RSS에서 심사 동향(review updates) 수집
- **추가할 것**: 개별 승인 약물의 심사보고서(審査報告書) 요약
- endpoint: `https://www.pmda.go.jp/drugs/YYYY/P{YYYYMMDD}/index.html`
- 데이터: 승인일, 적응증, 심사 포인트, 조건부 승인 여부
- 구현: PMDA 승인 목록(Excel)에서 심사보고서 URL 추출 → 일본어 텍스트 LLM 요약
- 난이도: **높음** — 일본어 PDF, URL 패턴 불규칙

#### D. MFDS 허가 상세
- **현재**: `MFDSClient`에서 목록만 수집
- **추가할 것**: `getDrugPrdtPrmsnDtlInq04` API 호출
- 데이터: **EE_DOC_DATA(효능효과)**, **UD_DOC_DATA(용법용량)**, NB_DOC_DATA(주의사항) — HTML 원문
- 구현: 이미 API 키 보유, 메서드만 호출하면 됨
- 난이도: **낮음**

#### E. e약은요 (이미 구현)
- endpoint: `apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList`
- 데이터: 한글 효능/용법/부작용/주의사항 평문
- 상태: **동작 확인 완료**

### 크로스레퍼런스 흐름

기사 생성 시 약물명이 등장하면:

```python
async def cross_reference_drug(inn: str) -> dict:
    """약물명 → 글로벌 심사 이력 통합 조회"""
    results = {}
    
    # 병렬 조회
    fda_label, fda_approval, ema_epar, mfds_detail, easy_drug, faers = await asyncio.gather(
        fetch_fda_label_full(inn),           # 적응증/용법/임상/부작용
        fetch_fda_approval_history(inn),      # 승인일/리뷰유형/스폰서  [신규]
        fetch_ema_epar_summary(inn),          # EPAR 요약              [신규]
        fetch_mfds_permit_detail(inn),        # 효능효과/용법용량       [신규]
        fetch_easy_drug_info(inn),            # 한글 평문
        fetch_faers_summary(inn),             # 부작용 보고
    )
    
    return {
        "fda": fda_label | fda_approval,
        "ema": ema_epar,
        "mfds": mfds_detail,
        "easy_drug": easy_drug,
        "faers": faers,
    }
```

### 기사에 반영되는 형태

**Before (현재):**
> pembrolizumab+gemcitabine/cisplatin(담도암, TA966)이 'non submission'으로 평가가 종료됐다.

**After (계획):**
> pembrolizumab+gemcitabine/cisplatin(담도암, TA966)이 NICE에서 기업 미제출로 평가가 종료됐다. 같은 조합은 FDA에서 2024년 Priority Review로 승인됐고(KEYTRUDA+GC), EMA에서도 2024년 조건부 승인을 받은 바 있다. 국내에서는 식약처 허가 후 급여 등재가 진행 중이다.

### 우선순위

| 순위 | 작업 | 난이도 | 효과 |
|------|------|--------|------|
| 1 | MFDS 허가 상세 (효능효과/용법) | 낮음 | 높음 — 한글 데이터 |
| 2 | FDA 승인 이력 (submissions) | 낮음 | 높음 — Priority/Standard 구분 |
| 3 | EMA EPAR 요약 | 중간 | 높음 — 유럽 심사 맥락 |
| 4 | PMDA 심사보고서 | 높음 | 중간 — 일본어 장벽 |

---

## 2. 법안 — 조문 요약 + 원문 링크

### 목표
"법안이 발의됐다"가 아니라 **"뭐가 바뀌는지"**를 기사에 쓸 수 있게.

### 현재 상태
- 열린국회 API: 제목, 발의자, 날짜, URL만 제공 (제안이유 API 없음)
- Playwright: 의안정보시스템에서 제안이유/주요내용 크롤링 **동작 확인**
- 상위 3건만 크롤링 중

### 강화 계획

#### A. 크롤링 범위 확대
- 상위 3건 → **기사에 선별된 법안 전체** (편집장이 선택한 스토리의 법안만)
- 법안 수가 많으면 최근 발의 순으로 5건까지

#### B. 조문 요약 생성
현재 제안이유 원문을 통째로 넘기고 있는데, LLM이 직접 기사에 쓰기엔 너무 길고 법률 용어가 많음.

**추가 단계: 제안이유 → LLM 3문장 요약**

```python
BILL_SUMMARY_PROMPT = """다음은 법률 개정안의 제안이유 및 주요내용입니다.
기자가 기사에 쓸 수 있도록 3문장으로 요약하세요.

1문장: 현행법의 문제점 (왜 바꾸려는지)
2문장: 개정안의 핵심 변경 내용 (뭐가 바뀌는지)
3문장: 영향받는 대상/기관 (누가 영향받는지)

제안이유:
{proposal_reason}
"""
```

#### C. 원문 링크 삽입
기사 말미에 원문 링크 제공:

```
> 원문: [약사법 일부개정법률안 (의안번호 2218146)](https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_...)
```

구현: `post_process_article`에서 법안 소스 기사에 자동 삽입.

#### D. 신구조문 대비표 (장기)
- medclaim-report-pipeline에서 이미 구현된 기능
- Upstage API로 HWP/PDF 파싱 → Before/After 테이블
- RegScan에 이식 가능하지만 별도 프로젝트이므로 **당장은 하지 않음**
- medclaim과 겹치지 않도록 주의 (별도 유지 방침)

### 기사에 반영되는 형태

**Before (현재):**
> 의료법 일부개정안 1건이 2026년 4월 발의된 것으로 소개되면서, 질병관리청장의 '보고 및 검사' 권한을 법 조문에 명시하는 내용이 핵심으로 나타났다.

**After (계획):**
> 4월 14일 발의된 의료법 개정안(소병훈의원 등 11인)은 의료관련감염 관리에서 질병관리청장의 '보고 및 검사' 권한을 신설한다(안 제61조제1항). 현행법은 감염관리를 권고 수준에서 다루지만, 개정안은 자료제출 요구·시정명령까지 법적 근거를 마련했다. 병원은 감염 발생 현황·격리 조치·교육 이력을 제출 가능한 형태로 관리해야 하는 부담이 생긴다.
>
> [원문: 의료법 일부개정법률안 (의안번호 2218XXX)](https://likms.assembly.go.kr/bill/billDetail.do?billId=...)

### 우선순위

| 순위 | 작업 | 난이도 | 효과 |
|------|------|--------|------|
| 1 | 크롤링 범위 확대 (3건→5건) | 낮음 | 중간 |
| 2 | 제안이유 LLM 3문장 요약 | 낮음 | 높음 — 법률 용어 제거 |
| 3 | 원문 링크 자동 삽입 | 낮음 | 중간 — 출처 투명성 |
| 4 | 신구조문 대비표 | 높음 | 높음 — 하지만 medclaim 겹침 주의 |

---

## 3. 특허 — 청구항 요약 + 임상 연결 + 글로벌 현황

### 목표
"특허가 출원됐다"가 아니라 **"이 특허가 어떤 산업적 의미가 있는지"**를 쓸 수 있게.

### 현재 상태
- KIPRIS API: 제목, 출원인, IPC 코드, 날짜
- 엔리칭: 타겟 키워드(PD-1, CD137 등)→ 대표 약물 FDA label 조회
- FDA label에서 적응증, 임상시험(NCT 번호) 자동 연결

### 강화 계획

#### A. 특허 초록/청구항 요약

KIPRIS API에서 특허 초록은 현재 수집 안 하고 있음.

**방법 1: KIPRIS Plus 상세 조회 API**
- `getWordSearch`는 목록만. 상세 조회 API가 별도로 있음.
- `patUtiModInfoSearchSevice/getPatentDetailInfo` 등
- 데이터: 초록(abstract), 대표 청구항(claim 1), 출원인 주소

**방법 2: 특허 공보 직접 조회**
- 특허 공개번호로 특허 공보 PDF/XML 접근
- KIPRIS 또는 한국특허정보원 공보 서비스

**구현:**
```python
async def fetch_patent_abstract(application_number: str) -> str:
    """KIPRIS에서 특허 초록 가져오기"""
    # 상세 조회 API 호출
    # → 초록 텍스트 반환
```

**LLM 요약:**
```python
PATENT_SUMMARY_PROMPT = """다음은 의약품 특허의 초록과 대표 청구항입니다.
기자가 기사에 쓸 수 있도록 2문장으로 요약하세요.

1문장: 이 특허가 다루는 핵심 기술/약물 (뭘 보호하려는지)
2문장: 기존 기술 대비 차별점 (왜 이 특허가 중요한지)

초록:
{abstract}

대표 청구항:
{claim_1}
"""
```

#### B. 임상시험 연결 (ClinicalTrials.gov)

현재 FDA label에서 NCT 번호가 나오면 기사에 기재되지만, 임상 상세는 미조회.

**추가할 것:**
```python
async def fetch_clinical_trial(nct_id: str) -> dict:
    """ClinicalTrials.gov v2 API에서 임상시험 상세 조회"""
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    # 필드: BriefTitle, Phase, OverallStatus, EnrollmentCount,
    #       PrimaryOutcomeMeasure, StartDate, CompletionDate, HasResults
```

**기사에 반영:**
> 참조 약물 pembrolizumab의 관련 임상(NCT05722015)은 3상 진행 중이며, 참여자 1,200명, 주요 평가변수는 무진행 생존기간(PFS)이다.

#### C. 글로벌 특허/승인 현황 크로스체크

같은 약물/타겟에 대해 다른 나라에서 승인·특허가 있는지 확인.

**구현:**
```python
async def cross_check_global_status(inn_or_target: str) -> dict:
    """약물명/타겟 → 글로벌 승인·특허 현황"""
    results = {}
    
    # FDA 승인 여부
    fda = await fetch_fda_label_full(inn_or_target)
    if fda:
        results["fda_approved"] = True
        results["fda_indications"] = fda.get("indications", "")[:200]
    
    # EMA 승인 여부 (EMA 수집기 데이터 활용)
    # PMDA 승인 여부 (PMDA 수집기 데이터 활용)
    # MFDS 허가 여부 (MFDS 수집기 데이터 활용)
    
    return results
```

**기사에 반영:**
> CD137 표적 항체(누맙 세러퓨틱스)는 국내에서 출원됐지만, FDA에서 같은 타겟의 urelumab(BMS)은 2019년 임상 중단된 바 있다. 반면 nivolumab(OPDIVO)은 CD137 경로와 연관된 PD-1 억제제로 FDA·EMA·PMDA·식약처 4개국에서 모두 승인됐다.

### 기사에 반영되는 형태

**Before (현재):**
> 4월 20일 리제너론은 '항-PD-1 항체와 이특이적 항-CD20/항-CD3 항체의 조합'을 출원했다. 참조 약물로 pembrolizumab이 기재됐다.

**After (계획):**
> 4월 20일 리제너론은 항-PD-1 항체(pembrolizumab)와 이특이적 항-CD20/항-CD3 항체를 조합한 암 치료 조성물을 출원했다. 이 조합의 핵심은 PD-1 억제에 T세포 유도형 이특이 항체를 결합해 종양 미세환경 내 면역 반응을 다중 축으로 활성화하는 전략이다. 관련 임상(NCT05722015)은 현재 3상 진행 중이며 참여자 1,200명, 주요 평가변수는 무진행 생존기간(PFS)이다. pembrolizumab은 이미 FDA·EMA·PMDA·식약처 4개국에서 30개 이상 적응증으로 승인됐다.

### 우선순위

| 순위 | 작업 | 난이도 | 효과 |
|------|------|--------|------|
| 1 | ClinicalTrials.gov NCT 상세 조회 | 낮음 | 높음 — 임상 수치 |
| 2 | 글로벌 승인 현황 크로스체크 | 낮음 | 높음 — 맥락 |
| 3 | KIPRIS 특허 초록 수집 | 중간 | 중간 — API 확인 필요 |
| 4 | 청구항 LLM 요약 | 낮음 | 중간 — 초록 수집 후 |

---

## 4. 통합 구현 로드맵

### Phase 1 — 즉시 (1~2일)
| 작업 | 파일 | 난이도 |
|------|------|--------|
| MFDS 허가 상세 (효능효과/용법) | enrichment.py | 낮음 |
| FDA 승인 이력 (Priority/Standard) | enrichment.py | 낮음 |
| ClinicalTrials.gov NCT 상세 | enrichment.py | 낮음 |
| 법안 크롤링 3건→5건 | enrichment.py | 낮음 |
| 제안이유 LLM 3문장 요약 | enrichment.py | 낮음 |
| 원문 링크 자동 삽입 | guardrails.py | 낮음 |

### Phase 2 — 이번 주 (3~5일)
| 작업 | 파일 | 난이도 |
|------|------|--------|
| EMA EPAR 요약 크롤링 | enrichment.py + ema.py | 중간 |
| 글로벌 승인 현황 크로스체크 | enrichment.py | 중간 |
| KIPRIS 특허 초록 API | enrichment.py + kipris.py | 중간 |
| 청구항 LLM 요약 | enrichment.py | 낮음 (초록 수집 후) |

### Phase 3 — 다음 주
| 작업 | 파일 | 난이도 |
|------|------|--------|
| PMDA 심사보고서 요약 | enrichment.py + pmda.py | 높음 |
| 기사 유형별 템플릿 분기 (P4) | pipeline.py | 중간 |
| 기사 자동 발행 채널 (대시보드/이메일) | routes/ + templates/ | 중간 |

---

## 5. 아키텍처 최종 형태

```
시그널 수집 (28개 소스)
    ↓
시그널 추출 (intelligence_signals.py)
    ↓
자동 취재 — 엔리칭 (enrichment.py)
    ├── 약물명 → FDA label + FAERS + e약은요 + MFDS 허가상세
    ├── 약물명 → FDA 승인이력 + EMA EPAR + 글로벌 크로스체크
    ├── 법안 → Playwright 제안이유 크롤링 + LLM 3문장 요약
    ├── 특허 → 타겟→FDA label + NCT 임상 상세 + 초록 요약
    └── 보도자료 → e약은요 약물 정보
    ↓
편집장 (스토리 선별 + 유형 판정)
    ↓
기자 (유형별 프롬프트 + 엔리칭 데이터 활용)
    ↓
팩트체커 (근거 불명 → 기사 폐기)
    ↓
편집자 (최종 정제)
    ↓
가드레일 (금지표현 + 문체 치환 + 절단 삭제)
    ↓
발행
```
