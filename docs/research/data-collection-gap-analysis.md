# 데이터 수집 갭 분석 — 타 레포 이식 대비

> 작성일: 2026-04-17
> 목적: RegScan 데이터 수집 체계를 다른 레포에 이식할 때, 현재 누락된 소스를 식별하고 추가 수집 우선순위를 정리

---

## 1. 현재 수집 현황 (16개 소스)

### 글로벌 규제

| 소스 | 수집 방식 | 수집 데이터 |
|------|----------|------------|
| FDA (openFDA) | REST API | 승인, NDA/BLA, Breakthrough, PDUFA, Safety, AdCom |
| EMA | REST API | 허가 의약품, 오펀, 부족, 안전성(DHPC/referral/PSUSA) |

### 국내 규제

| 소스 | 수집 방식 | 수집 데이터 |
|------|----------|------------|
| MFDS (식약처) | 공공데이터 API | 284K+ 허가 품목, 제형, 업체 |
| HIRA (심평원) | Playwright 크롤링 + Excel 다운로드 | 심사기준, 약가(상한가), 급여 상태 |
| MOHW (복지부) | Playwright 크롤링 | 입법/행정예고 |
| KDCA (질병청) | Playwright 크롤링 | 보도자료, 백신/질병/약물 정책 |

### 임상시험

| 소스 | 수집 방식 | 수집 데이터 |
|------|----------|------------|
| ClinicalTrials.gov | REST API | Phase 3 (완료/중단/보류) |
| CRIS (국내) | 공공데이터 API | 11.5K+ 국내 임상시험 |

### 산업/시장 정보

| 소스 | 수집 방식 | 수집 데이터 |
|------|----------|------------|
| KHIDI (보건산업진흥원) | Web API (httpx) | 바이오헬스 산업 브리프, 시장 보고서 |
| ASTI | Playwright 크롤링 | 바이오/제약 시장 조사 보고서 |
| Health.kr (약학정보원) | Playwright 크롤링 | 전문가 리뷰, KPIC 콘텐츠 |

### 뉴스 (RSS)

| 소스 | 수집 데이터 |
|------|------------|
| Endpoints News | 글로벌 제약 뉴스 |
| FiercePharma | 글로벌 제약 뉴스 |
| Fierce Biotech | 바이오텍 뉴스 |

### 학술

| 소스 | 수집 방식 | 수집 데이터 |
|------|----------|------------|
| bioRxiv/medRxiv | REST API | 최근 30일 의약품 관련 프리프린트 |

### 참조 DB

| 소스 | 용도 |
|------|------|
| OMOP/RxNorm | 약물 개념 매핑 (2M+ concepts) |
| ATC 코드 | 치료 분류 계층 구조 |
| HeMonc (CC BY) | 종양 온톨로지, 경쟁 구도 |
| HIRA 약가마스터 | 국내 약물 사전 (305K건, ATC 매핑 포함) |

---

## 2. 갭 분석 — 추가 수집 검토 대상

### 2.1 특허/IP 데이터 ⭐ 우선순위 1

**왜 필요한가:** 제네릭 진입 시점 = 시장 변동의 핵심 트리거. 현재 수집 체계에서 가장 크게 빠진 영역.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **FDA Orange Book** | 공개 다운로드 (CSV/ZIP) | 특허 만료일, 독점권(exclusivity), 치료적 동등성 |
| **KIPRIS (특허정보원)** | 공공데이터 API | 국내 의약품 특허 현황, 등록/소멸 |

- Orange Book: https://www.fda.gov/drugs/drug-approvals-and-databases/approved-drug-products-therapeutic-equivalence-evaluations-orange-book
- KIPRIS API: https://plus.kipris.or.kr

**활용:** 특허 만료 → 제네릭 경쟁 시작 → 약가 인하 예측 → 급여 변동 선제 파악

---

### 2.2 국내 안전성/약물감시 ⭐ 우선순위 2

**왜 필요한가:** EMA safety는 수집 중이나, 국내 안전성 정보가 누락. 구현 난이도 낮음.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **의약품안전나라 (nedrug.mfds.go.kr)** | 크롤링 또는 API | 안전성 서한, 회수/판매중지, 부작용 정보 |
| **KAERS (이상반응 보고)** | 공개 통계 크롤링 | 국내 부작용 동향, 시그널 |

- 현재: EMA DHPC/referral + FDA enforcement만 수집
- 누락: 국내 식약처 안전성 서한, 회수 명령

---

### 2.3 해외 HTA(경제성평가) 의사결정 ⭐ 우선순위 3

**왜 필요한가:** 해외 HTA 선례는 국내 급여 가능성 예측의 가장 강력한 선행지표.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **NICE (영국)** | 공개 API 있음 | Technology Appraisals, 권고 결과 |
| **CADTH (캐나다)** | 웹 크롤링 | CDR/pCODR 리뷰, 권고 |
| **PBAC (호주)** | 웹 크롤링 | 약가 결정, 등재 권고 |

- NICE API: https://www.nice.org.uk/about/what-we-do/nice-and-health-technology-evaluation
- CADTH: https://www.cadth.ca/reimbursement-reviews
- PBAC: https://www.pbs.gov.au/pbs/industry/listing/elements/pbac-outcomes

**활용:** 해외 HTA 긍정 → 국내 급여 가능성 ↑, 부정 → 급여 지연/거절 가능성 ↑

---

### 2.4 주요국 규제기관 — 우선순위 4

**왜 필요한가:** 한국 IRP(국제참조가격제) A7 비교 대상국. 이들의 승인/약가가 국내 약가에 직접 영향.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **PMDA (일본)** | 웹 크롤링 | 승인, 약가 수재, 오펀 지정 |
| **Health Canada** | API | Drug Product Database, 승인 |
| **TGA (호주)** | 웹 크롤링/API | ARTG 등재, 승인 |

- PMDA: https://www.pmda.go.jp/english/
- Health Canada DPD API: https://health-products.canada.ca/api/
- TGA: https://www.tga.gov.au/resources/artg

**활용:** A7 참조국 승인 현황 → 약가 산정 기초자료, IRP 비교 분석

---

### 2.5 국내 정책/법령 파이프라인 — 우선순위 5

**왜 필요한가:** 현재 MOHW 입법예고만 수집. 법안 발의~통과 전체 파이프라인 추적 불가.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **국회 의안정보시스템** | 웹 크롤링/API | 약사법 개정안, 보건의료 법안 발의/심의/통과 |
| **법제처 국가법령정보센터** | API 있음 | 시행령/시행규칙 변경, 고시 개정 |
| **건보심 (건강보험정책심의위원회)** | 회의록 크롤링 | 급여 결정 최종 의사결정 |

- 의안정보: https://likms.assembly.go.kr/bill/
- 법제처 API: https://www.law.go.kr/LSW/openApi.do
- 건보심: 복지부 산하, 회의 결과 공개

**활용:** 법안 발의 → 위원회 심의 → 본회의 → 공포 전체 추적, 급여 결정 과정 완전 파악

---

### 2.6 재무/기업 공시 — 우선순위 6

**왜 필요한가:** 라이선스 딜, 파이프라인 변동은 규제 동향보다 빠른 선행지표.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **DART (전자공시)** | 공개 API | 국내 제약사 공시, 라이선스인/아웃 계약 |
| **SEC EDGAR** | API | 글로벌 빅파마 10-K/8-K, 파이프라인 공시 |

- DART API: https://opendart.fss.or.kr
- EDGAR: https://www.sec.gov/edgar/searchedgar/companysearch

---

### 2.7 학회/진료지침 — 우선순위 7

**왜 필요한가:** 진료지침 변경 → 적응증 확대 → 급여 확대 경로.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **NCCN Guidelines** | 구독 필요 | 종양 치료 표준 변경 |
| **대한의학회/전문학회** | 크롤링 | 국내 진료지침 발표/개정 |

- 제약: NCCN은 유료 구독 필요. 국내 학회는 구조화 안 됨.

---

### 2.8 글로벌 약가 데이터 — 우선순위 8

**왜 필요한가:** IRP 비교 및 국내 약가 협상 시 벤치마크.

| 소스 | 접근 방식 | 수집 가능 데이터 |
|------|----------|----------------|
| **Medicaid NADAC (미국)** | 공개 다운로드 | 미국 약가 |
| **BNF (영국)** | 크롤링 | 영국 약가 |
| **NHI (일본)** | 크롤링 | 일본 약가 |

---

## 3. 우선순위 요약 및 구��� 현황

> 갱신일: 2026-04-21 — 우선순위 1~5 구현 완료, 파이프라인 통합 완료

| 순위 | 소스 | 핵심 이유 | 난이도 | 상태 | 구현 파일 |
|-----|------|----------|-------|------|----------|
| **1** | FDA Orange Book | 제네릭 진입 시점 핵심 트리거 | 낮음 | **DONE** | `orange_book.py` |
| **1** | FDA Purple Book | 생물의약품 ��점권/바이오시밀러 | 낮음 | **DONE** | `purple_book.py` |
| **1** | KIPRIS (국내 특허) | 국내 제네릭 진입 예측 | 중간 | TODO | API 있음 |
| **2** | MFDS 안전성 서한 | 국내 안전성 사각지대 해소 | 낮음 | **DONE** | `mfds_safety.py` (httpx+bs4, TLS 1.2) |
| **2** | MFDS 회수/판매중지 | 국내 안전성 사각지대 해소 | 낮음 | **DONE** | `mfds_safety.py` (data.go.kr API) |
| **2** | KAERS (이상반응) | 부작용 시그널 사전 감지 | 중간 | TODO | 공개 통계만 |
| **3** | NICE (영국 HTA) | 급여 가능성 최강 선행지표 | 중간 | **DONE** | `nice.py` (Excel 벌크) |
| **3** | CADTH (캐나다 HTA) | NICE와 2대 HTA, 정확도 보강 | 중간 | TODO | 웹 크롤링 필요 |
| **3** | PBAC (호주 HTA) | A7 참조국 | 중간 | TODO | 웹 크롤링 필요 |
| **4** | PMDA (일본) | IRP 참조국, 아시아 규제 동조화 | 중간 | **DONE** | `pmda.py` (RSS+HTML, TLS 1.2) |
| **4** | Health Canada | IRP A7 참조국 | 낮음 | TODO | API 있음 |
| **4** | TGA (호주) | IRP A7 참조국 | 중간 | TODO | |
| **5** | 국회 의안정보 | 약사법/건강보험법 추적 | 중간 | **DONE** | `assembly.py` (열린국회정보 API) |
| **5** | 건보심 | 급여 결정 최종 의사결정 | 중간 | **DONE** | `mohw_insurance.py` (보도자료 키워드) |
| **5** | 법제처 국가법령정보 | 시행령/고시 변경 추적 | 중간 | TODO | IP 등록 필요 |
| **6** | DART (전자공시) | 라이선스 딜 선행지표 | 낮음 | TODO | API 있음 |
| **6** | SEC EDGAR | 글로벌 빅파마 공시 | 낮음 | TODO | |
| **7** | NCCN Guidelines | 종양 치료 표준 변경 | 높음 | TODO | 유료 구독 필요 |
| **7** | 대한의학회/전문학회 | 국내 진료지침 | 높음 | TODO | 비구조화 |
| **8** | Medicaid NADAC (미국) | IRP 약가 벤치마크 | 낮음 | TODO | 공개 CSV |
| **8** | BNF (영국 약가) | IRP 비교 | 중간 | TODO | |
| **8** | NHI (일본 약가) | IRP 비교 | 중간 | TODO | |

**커버리지:** 22/33 소스 구현 (67%), 핵심 사이클(승인→급여→시장) 커버 완성

---

## 4. 수집 체계 전체 지도 (2026-04-21 갱신)

```
┌──────────┬──────────┬──────────┬──────────┬──────────────────┐
│  전임상   │  임상     │  승인     │  급여     │  시장              │
├──────────┼──────────┼──────────┼──────────┼──────────────────┤
│ ✅ bioRxiv│ ✅ CT.gov │ ✅ FDA    │ ✅ HIRA   │ ✅ Orange Book     │
│ ✅ medRxiv│ ✅ CRIS   │ ✅ EMA    │ ✅ MOHW   │ ✅ Purple Book     │
│          │          │ ✅ MFDS   │ ✅ 건보심  │ ❌ DART (공시)     │
│          │          │ ✅ PMDA   │ ✅ NICE   │ ❌ KIPRIS (특허)   │
│          │          │ ❌ HC     │ ❌ CADTH  │ ❌ 글로벌 약가     │
│          │          │ ❌ TGA    │ ❌ PBAC   │                    │
├──────────┴──────────┴──────────┴──────────┴──────────────────┤
│  안전성: ✅ EMA safety │ ✅ MFDS 안전성 서한 │ ❌ KAERS          │
│  법령:   ✅ MOHW 예고  │ ✅ 국회 법안        │ ❌ 법제처          │
│  특허:   ✅ Orange Book│ ✅ Purple Book      │ ❌ KIPRIS         │
│  학술:   ✅ bioRxiv    │ ❌ 학회 가이드라인   │ ❌ NCCN           │
└─────────────────────────────────────────────────────────────┘

✅ = 수집 중 (22개)   ❌ = 미수집 (11개)
```

---

## 5. 남은 갭 — 실질 영향도별 분류

### 높음 (다음 구현 권장)

| 항목 | 이유 | 난이도 | 비고 |
|------|------|--------|------|
| **KIPRIS** (국내 특허) | Orange Book은 미국만. 국내 제네릭 진입엔 국내 특허 필요 | 중간 | 공공데이터 API |
| **DART** (전자공시) | 라이선스 딜이 승인보다 6~12개월 빠른 선행지표 | 낮음 | opendart.fss.or.kr |
| **CADTH** (캐나다 HTA) | NICE와 함께 2대 HTA, 급여 예측 정확도 보강 | 중간 | 웹 크롤링 |

### 중간 (있으면 좋지만 급하진 않음)

| 항목 | 이유 | 난이도 |
|------|------|--------|
| Health Canada | IRP A7이지만 PMDA로 아시아 커버됨 | 낮음 (API) |
| 법제처 국가법령정보 | 국회 법안으로 발의 추적 됨, 시행령/고시 변경만 누락 | 중간 (IP 등록) |
| KAERS (이상반응) | 안전성 서한으로 사후 경고 수집 중, 시그널 단계 추가 가치 | 중간 |
| Medicaid NADAC | IRP 약가 비교 벤치마크, 공개 CSV | 낮음 |

### 낮음 (장기 검토)

| 항목 | 이유 |
|------|------|
| TGA (호주), PBAC | A7 참조국이나 Health Canada보다 우선순위 낮음 |
| NCCN/학회 가이드라인 | 유료 구독 + 비구조화, ROI 낮음 |
| SEC EDGAR | DART로 국내 커버되면 글로벌은 뉴스 RSS로 충분 |
| BNF/NHI 약가 | NADAC 하나면 벤치마크 시작 가능 |

### 구현된 소스의 알려진 한계

| 수집기 | 한계 | 영향 |
|--------|------|------|
| MOHW 건보심 | 보도자료 키워드 필터 (회의록 직접 수집 아님) | 비관련 결과 혼입 가능, `is_relevant_dept`로 완화 |
| PMDA | RSS(영문) + 안전성 테이블만. 일본 약가 수재 미포함 | 약가 데이터�� NHI(우선순위 8)에서 별도 구��� 필요 |
| MFDS 회수 API | data.go.kr API 키 401 반환 중 | 키 갱신 필요 (활용신청 완료) |
| MFDS 안전성 서한 | nedrug.mfds.go.kr TLS 1.3 미지원 | ssl.maximum_version=TLSv1_2로 해결 완료 |

---

## 6. 파이프라인 통합 현황

모든 신규 수집기는 `regscan/batch/pipeline.py`에 통합 완료.

```
v3 Stream Pipeline:
  [4.8] 보조 인텔리전스 수집 (Step 4.8, 2026-04-21 추가)
        ├─ PMDAReviewIngestor + PMDASafetyIngestor   ENABLE_PMDA
        ├─ NICERecentTAIngestor                      ENABLE_NICE_HTA
        ├─ MFDSSafetyLetterIngestor                  ENABLE_MFDS_SAFETY
        ├─ MOHWHealthInsuranceIngestor               ENABLE_MOHW_INSURANCE
        └─ AssemblyBillIngestor                      ENABLE_ASSEMBLY_BILL

Legacy v2 Pipeline:
  [4.6] 동일 수집기 통합 (Step 4.6)
```

각 수집기는 `settings.py`에서 개별 ON/OFF 가능. 실패해도 다른 수집기에 영향 없음 (try/except + graceful skip).

---

## 7. 이식 시 고려사항

### 소스별 의존성

- **API 키 필요:** FDA, data.go.kr, 열린국회정보 (`OPEN_ASSEMBLY_API_KEY`), LLM
- **Playwright 필요:** HIRA, MOHW 입법예고, KDCA, ASTI, Health.kr
- **httpx+bs4 (Playwright 불필요):** MFDS 안전성 서한, MOHW 건강보험, PMDA
- **TLS 1.2 강제 필요:** nedrug.mfds.go.kr, pmda.go.jp (정부 사이트 공통 패턴)
- **User-Agent 필수:** 열린국회정보 API (없으면 400 Bad Request)
- **참조 DB 필요:** OMOP/RxNorm (2.8GB), HIRA 약가마스터 (53MB), HeMonc

### 독립 이식 가능 모듈

| 모듈 | 외부 의존성 | 독립 실행 가능 |
|------|-----------|--------------|
| FDA ingest | API 키 1개 | ✅ |
| FDA Orange Book / Purple Book | 없음 (공�� CSV) | ✅ |
| EMA ingest | 없음 (공개) | ✅ |
| MFDS ingest | data.go.kr 키 | ✅ |
| MFDS 안전성 서한 | 없음 (공개, TLS 1.2) | ✅ |
| CRIS ingest | data.go.kr 키 | ✅ |
| ClinicalTrials.gov | 없음 (공개) | ✅ |
| bioRxiv/medRxiv | 없음 (공개) | ✅ |
| PMDA | 없음 (공개 RSS, TLS 1.2) | ✅ |
| NICE HTA | 없음 (공개 Excel) | ✅ |
| 국회 의안정보 | API 키 1개 + User-Agent | ✅ |
| MOHW 건강보험 | 없음 (공개) | ✅ |
| HIRA 크롤러 | Playwright | ✅ (JS 렌더링 필요) |
| IngredientBridge | 약가마스터 CSV | ⚠️ 참조 데이터 동반 필요 |
| DrugCodeResolver | ATC 매핑 CSV + Bridge | ⚠️ 참조 데이터 동반 필요 |
| FactCard pipeline | 전체 ingest + 참조 DB | ❌ 전체 의존 |

### 최소 이식 세트 (데이터 수집만)

```
regscan/ingest/          # 22개 수집기
regscan/config/settings.py  # 수집 설정 + 토글
regscan/ingest/base.py   # BaseIngestor (async context manager)
.env                     # API 키 (FDA, data.go.kr, OPEN_ASSEMBLY)
requirements.txt         # httpx, bs4, lxml, playwright, openpyxl
```
