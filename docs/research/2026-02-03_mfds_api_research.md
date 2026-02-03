# MFDS(식품의약품안전처) 데이터 수집 방법 조사 리포트

> 작성일: 2026-02-03
> 목적: RegScan 프로젝트의 "국내 영향 예측" 기능을 위한 MFDS 데이터 연동 방안 조사

---

## Executive Summary

| 항목 | 결과 |
|------|------|
| 공식 API | ✅ 있음 (공공데이터포털) |
| 상업적 이용 | ✅ 가능 (공공누리 제1유형) |
| 데이터 건수 | 284,477건 (의약품 허가정보) |
| 인증 방식 | API Key (무료 발급) |
| 데이터 포맷 | JSON, XML |
| 구현 난이도 | 낮음 (REST API) |

**결론: 공공데이터포털 API를 활용하면 법적 리스크 없이 안정적으로 MFDS 데이터 수집 가능**

---

## 1. 공식 API 현황

### 1.1 공공데이터포털 (data.go.kr)

| API 명 | 데이터 건수 | 용도 |
|--------|------------|------|
| **의약품 제품 허가정보** | 284,477건 | 허가 현황 (핵심) |
| 의약품개요정보 (e약은요) | - | 일반 의약품 정보 |
| DUR 품목정보 | 192,436건 | 안전사용 정보 |
| 희귀의약품 정보 | - | 희귀의약품 지정 |
| 생산/수입실적 | - | 시장 규모 |
| 생동성인정품목 | - | 제네릭 정보 |
| 행정처분 정보 | - | 위반 이력 |

### 1.2 핵심 API: 의약품 제품 허가정보

**엔드포인트:**
```
https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07
```

**주요 응답 필드:**

| 필드 | 설명 | RegScan 활용 |
|------|------|-------------|
| `ITEM_SEQ` | 품목일련번호 | GlobalStatusDB.mfds_item_seq |
| `ITEM_NAME` | 품목명 | 성분명 매칭 |
| `ITEM_PERMIT_DATE` | 허가일자 | GlobalStatusDB.mfds_approval_date |
| `ENTP_NAME` | 업체명 | 제조사 정보 |
| `RARE_DRUG_YN` | 희귀의약품 여부 | 핫이슈 스코어링 |
| `EDI_CODE` | EDI코드 | HIRA 급여 매칭 |

---

## 2. 기술적 구현 방법

### 2.1 API 호출 예시

```python
import httpx

API_KEY = 'your_api_key_here'
BASE_URL = 'https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07'

async def fetch_drug_permits(page: int = 1, rows: int = 100):
    params = {
        'serviceKey': API_KEY,
        'pageNo': str(page),
        'numOfRows': str(rows),
        'type': 'json',
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f'{BASE_URL}/getDrugPrdtPrmsnInq07',
            params=params,
            timeout=30.0
        )
        return response.json()
```

### 2.2 RegScan 파이프라인 통합

```
[기존 파이프라인]
FDA API → FDAParser → GlobalStatus
EMA API → EMAParser → GlobalStatus

[추가할 파이프라인]
MFDS API → MFDSParser → GlobalStatus
              ↓
         INN 매칭으로 FDA/EMA 데이터와 병합
```

### 2.3 구현 파일

```
regscan/
├── ingest/
│   └── mfds.py          # MFDSClient, MFDSDrugPermitIngestor
├── parse/
│   └── mfds_parser.py   # MFDSDrugParser
```

---

## 3. 데이터 매칭 전략

### 3.1 INN(국제일반명) 기반 매칭

**문제:** MFDS는 한글 품목명 사용, FDA/EMA는 영문 INN 사용

**해결 방안:**
1. MFDS 주성분 정보에서 영문명 추출 (있는 경우)
2. 한글 성분명 → 영문 INN 변환 테이블 구축
3. WHO ATC 코드로 교차 검증

### 3.2 EDI 코드 활용

- MFDS `EDI_CODE` = HIRA 급여 코드
- MFDS 허가 → HIRA 급여 연결 가능

---

## 4. 법적/라이선스

### 4.1 공공누리 제1유형

| 조건 | 내용 |
|------|------|
| 출처표시 | 필수 |
| 상업적 이용 | ✅ 가능 |
| 변경/2차 저작물 | ✅ 가능 |

### 4.2 출처표시 문구

```
본 서비스는 '식품의약품안전처'에서 제공하는 '의약품 제품 허가정보'를 활용하였습니다.
(공공데이터포털: https://www.data.go.kr)
```

---

## 5. 구현 우선순위

### Phase 1 (즉시)
- [ ] 공공데이터포털 API Key 발급
- [ ] MFDSClient 구현 (ingest/mfds.py)
- [ ] MFDSDrugParser 구현 (parse/mfds_parser.py)
- [ ] GlobalStatusDB에 MFDS 데이터 저장

### Phase 2 (매칭)
- [ ] INN 매칭 로직 구현 (한글→영문)
- [ ] FDA/EMA 데이터와 병합
- [ ] Timeline 모델 완성

### Phase 3 (고도화)
- [ ] DUR 정보 연동
- [ ] 희귀의약품 정보 강화
- [ ] 생산/수입실적 연동

---

## 6. 예상 결과물

MFDS 연동 완료 시:

```
GlobalRegulatoryStatus:
  inn: "semaglutide"

  fda:
    status: "approved"
    approval_date: "2021-06-04"
    brand_name: "Wegovy"

  ema:
    status: "approved"
    approval_date: "2022-01-06"
    brand_name: "Wegovy"

  mfds:                          # ← 새로 추가
    status: "approved"
    approval_date: "2024-01-15"
    brand_name: "위고비"
    item_seq: "202400001"

  timeline:
    fda_to_mfds_days: 956        # FDA 승인 → MFDS 허가 소요일
    expected_hira_date: "2025-06-01"  # 급여 예상 시점
```

---

## 7. 참고 URL

| 리소스 | URL |
|--------|-----|
| 공공데이터포털 | https://www.data.go.kr |
| 의약품 허가정보 API | https://www.data.go.kr/data/15095677/openapi.do |
| 의약품안전나라 | https://nedrug.mfds.go.kr |
| 식의약 데이터 포털 | https://data.mfds.go.kr |

---

## 8. 결론

**MFDS 데이터 연동은 기술적으로 쉽고, 법적으로 안전합니다.**

- 공공데이터포털 API 활용 (REST, JSON)
- 상업적 이용 가능 (공공누리 제1유형)
- 284,477건의 허가 데이터 즉시 활용 가능
- FDA/EMA와 INN 기반 매칭으로 글로벌 → 국내 타임라인 완성

**다음 단계:** API Key 발급 → Ingestor 구현 → Parser 구현 → 테스트
