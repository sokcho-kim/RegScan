# 데이터 소스 인벤토리

> 작성일: 2026-02-04
> 목적: MFDS ↔ HIRA 매칭 실험을 위한 데이터 출처 명세
> 상태: PoC (실험 단계) → 성공 시 파이프라인화 예정

---

## 1. 개요

### 1.1 목표
- 글로벌 규제 현황(FDA/EMA/MFDS)과 국내 보험 급여(HIRA) 연결
- 의성분코드(ingredient_code) 기반 매칭

### 1.2 파이프라인화 계획
```
[현재: PoC]
수동 다운로드 → 로컬 저장 → 매칭 실험

[향후: Pipeline]
스케줄러 → API/스크래핑 수집 → 정규화 → DB 저장 → 매칭 → 서빙
```

---

## 2. 데이터 소스 상세

### 2.1 글로벌 규제 데이터

#### FDA (미국 식품의약국)
| 항목 | 내용 |
|------|------|
| **출처** | openFDA API |
| **URL** | https://api.fda.gov/drug/drugsfda.json |
| **수집방식** | API (무료, 키 불필요) |
| **갱신주기** | 실시간 |
| **라이선스** | Public Domain |
| **현재 파일** | `data/fda/approvals_20260203.json` |
| **건수** | 1,462건 |
| **핵심필드** | openfda.substance_name, products.active_ingredients |

#### EMA (유럽의약품청)
| 항목 | 내용 |
|------|------|
| **출처** | EMA Open Data Portal |
| **URL** | https://www.ema.europa.eu/en/medicines/download-medicine-data |
| **수집방식** | JSON API (무료) |
| **갱신주기** | 일간 |
| **라이선스** | Open Data |
| **현재 파일** | `data/ema/medicines_20260203.json` |
| **건수** | 2,655건 |
| **핵심필드** | active_substance, international_non_proprietary_name |

---

### 2.2 국내 규제 데이터

#### MFDS (식품의약품안전처)
| 항목 | 내용 |
|------|------|
| **출처** | 공공데이터포털 |
| **API** | `apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07` |
| **URL** | https://www.data.go.kr/data/15075057/openapi.do |
| **수집방식** | API (키 필요) |
| **갱신주기** | 월간 |
| **라이선스** | 공공누리 제1유형 (상업적 이용 가능) |
| **현재 파일** | `data/mfds/permits_full_20260203.json` |
| **건수** | 44,035건 |
| **핵심필드** | ITEM_SEQ, ITEM_INGR_NAME (INN), ITEM_NAME |

#### CRIS (임상연구정보서비스)
| 항목 | 내용 |
|------|------|
| **출처** | 공공데이터포털 |
| **API** | `apis.data.go.kr/1352159/crisinfodataview` |
| **URL** | https://www.data.go.kr/data/15000650/openapi.do |
| **수집방식** | API (키 필요) |
| **갱신주기** | 수시 |
| **라이선스** | 공공누리 제2유형 (상업적 이용 금지) |
| **현재 파일** | `data/cris/trials_full_20260204.json` |
| **건수** | 11,551건 |
| **핵심필드** | trial_id, i_freetext_kr (시험약) |

---

### 2.3 급여/약가 데이터

#### HIRA 적용약가파일
| 항목 | 내용 |
|------|------|
| **출처** | 건강보험심사평가원 |
| **URL** | https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank |
| **수집방식** | 청구관련기준 마스터 파일 다운로드 |
| **갱신주기** | 월간 (매월 1일 시행) |
| **라이선스** | 공공데이터 |
| **현재 파일** | `data/hira/drug_prices_20260204.json` |
| **원본** | `data/hira/230201_260201 적용약가파일_1.30.수정 1부.xlsx` |
| **건수** | 59,004건 (50,125 고유 품목) |
| **핵심필드** | ingredient_code (주성분코드), 급여여부, 상한가 |

#### HIRA 수가반영내역
| 항목 | 내용 |
|------|------|
| **출처** | 건강보험심사평가원 |
| **URL** | 직접 제공 (Excel 파일) |
| **수집방식** | 수동 다운로드 |
| **현재 파일** | `data/hira/medical_fees_20260204.json` |
| **원본** | `data/hira/★수가반영내역(26.2.1.시행)_전체판_260130업로드.xlsb` |
| **건수** | 413,400건 |
| **용도** | 참고용 (의료행위 수가) |

---

### 2.4 브릿지 데이터 (매핑용)

#### ATC 코드 매핑
| 항목 | 내용 |
|------|------|
| **출처** | 공공데이터포털 (HIRA) |
| **URL** | https://www.data.go.kr/data/15067487/fileData.do |
| **수집방식** | 파일 다운로드 |
| **갱신주기** | 월간 |
| **라이선스** | 공공데이터 |
| **현재 파일** | `data/bridge/건강보험심사평가원_ATC코드_매핑_목록_20250630.csv` |
| **건수** | 21,953건 |
| **핵심필드** | 주성분코드, ATC코드, ATC코드 명칭 (INN) |
| **원본 위치** | scrape-hub/data/data_go/atc/ |

#### 약가마스터 (의약품표준코드)
| 항목 | 내용 |
|------|------|
| **출처** | 공공데이터포털 (HIRA) |
| **URL** | https://www.data.go.kr/data/15067462/fileData.do |
| **수집방식** | 파일 다운로드 |
| **갱신주기** | 연간 (10월경) |
| **라이선스** | 공공데이터 |
| **현재 파일** | `data/bridge/yakga_master_latest.csv` |
| **건수** | 305,522건 |
| **용도** | 참고용 (제품 목록, 일반명코드 45% 미채움) |

#### 의약품주성분 마스터 (핵심!)
| 항목 | 내용 |
|------|------|
| **출처** | 공공데이터포털 (HIRA) |
| **URL** | https://www.data.go.kr/data/15067461/fileData.do |
| **수집방식** | 파일 다운로드 |
| **갱신주기** | 연간 (10월경) |
| **라이선스** | 공공데이터 |
| **현재 파일** | `data/bridge/yakga_ingredient_master.csv` |
| **건수** | 59,631건 (고유 일반명코드 20,114개) |
| **핵심필드** | 일반명코드, 일반명(성분명), 제형, 투여, 함량 |
| **HIRA 커버리지** | 99.6% (9,002개 중 8,962개) |

#### 통합 약제 사전
| 항목 | 내용 |
|------|------|
| **출처** | scrape-hub 프로젝트 (자체 구축) |
| **구축방법** | 적용약가파일 + ATC매핑 + 약가마스터 통합 |
| **현재 파일** | `data/bridge/drug_dictionary_normalized.json` |
| **건수** | 91,706건 |
| **용도** | 참고용 (기존 매칭 결과) |

---

## 3. 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│                        글로벌 규제 데이터                             │
├─────────────────────────────────────────────────────────────────────┤
│  FDA (openFDA API)          →  active_ingredient (INN)              │
│  EMA (Open Data Portal)     →  active_substance (INN)               │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼ INN 정규화
┌─────────────────────────────────────────────────────────────────────┐
│                        브릿지 데이터                                  │
├─────────────────────────────────────────────────────────────────────┤
│  약가마스터 (data.go.kr)    →  일반명코드 = 의성분코드               │
│  ATC 매핑 (data.go.kr)      →  ATC명칭(INN) ↔ 주성분코드            │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼ ingredient_code
┌─────────────────────────────────────────────────────────────────────┐
│                        국내 급여 데이터                               │
├─────────────────────────────────────────────────────────────────────┤
│  HIRA 적용약가파일          →  ingredient_code → 급여여부            │
│  MFDS 허가정보              →  ITEM_INGR_NAME (INN)                  │
│  CRIS 임상시험              →  시험약 정보                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 파일 위치 요약

```
RegScan/data/
├── fda/
│   └── approvals_20260203.json              # FDA 승인 (1,462건)
├── ema/
│   └── medicines_20260203.json              # EMA 의약품 (2,655건)
├── mfds/
│   └── permits_full_20260203.json           # MFDS 허가 (44,035건)
├── cris/
│   └── trials_full_20260204.json            # CRIS 임상 (11,551건)
├── hira/
│   ├── drug_prices_20260204.json            # 적용약가 JSON (59,004건)
│   └── medical_fees_20260204.json           # 수가반영 JSON (413,400건)
└── bridge/
    ├── yakga_master_latest.csv              # 약가마스터 최신 (~298K건)
    ├── 건강보험심사평가원_ATC코드_매핑_목록_20250630.csv  # ATC 매핑 (21,953건)
    └── drug_dictionary_normalized.json      # 통합사전 (91,706건)
```

---

## 5. API 키 요구사항

| 데이터 | API 키 | 환경변수 |
|--------|--------|----------|
| FDA | 불필요 | - |
| EMA | 불필요 | - |
| MFDS | 필요 | `DATA_GO_KR_API_KEY` |
| CRIS | 필요 | `DATA_GO_KR_API_KEY` |
| HIRA 약가마스터 | 불필요 | - |
| ATC 매핑 | 불필요 | - |

---

## 6. 향후 파이프라인화 시 고려사항

### 6.1 수집 자동화
- FDA/EMA: API 직접 호출
- MFDS/CRIS: 공공데이터포털 API
- HIRA 적용약가: biz.hira.or.kr 스크래핑 (Playwright)
- 약가마스터: 직접 다운로드 URL

### 6.2 갱신 주기
| 데이터 | 주기 | 스케줄 |
|--------|------|--------|
| FDA | 일간 | Daily |
| EMA | 일간 | Daily |
| MFDS | 월간 | Monthly |
| HIRA 약가 | 월간 | Monthly (1일) |
| 약가마스터 | 연간 | Yearly (10월) |

### 6.3 참고 스크립트 (scrape-hub)
- `project/drug_data/scripts/collectors/data_go/yakga_master_collector.py`
- `scrape/hira_biz_master_scraper.py`
- `project/hira/scripts/scrape/download_pharma_files.py`

---

## 7. 라이선스 요약

| 데이터 | 상업적 이용 | 출처 표기 |
|--------|------------|----------|
| FDA | O | 권장 |
| EMA | O | 필수 |
| MFDS | O | 필수 |
| CRIS | **X** | 필수 |
| HIRA | O | 필수 |
| 약가마스터 | O | 필수 |

**주의**: CRIS 데이터는 공공누리 제2유형으로 **상업적 이용 금지**

---

**문서 버전**: 1.0
**작성자**: Claude
**다음 업데이트**: 파이프라인 구축 시
