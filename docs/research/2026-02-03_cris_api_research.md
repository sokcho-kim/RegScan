# CRIS (임상시험정보서비스) 데이터 수집 방법 조사 리포트

> 작성일: 2026-02-03
> 목적: RegScan 프로젝트의 "국내 임상시험 진행 현황" 파악을 위한 CRIS 연동 방안 조사

---

## Executive Summary

| 항목 | 결과 |
|------|------|
| 공식 API | ✅ 있음 (공공데이터포털) |
| 상업적 이용 | ⚠️ **불가** (공공누리 제2유형) |
| 데이터 건수 | 11,547건 (2025.12 기준) |
| 인증 방식 | API Key (무료, 자동승인) |
| 데이터 포맷 | JSON, XML |
| 크롤링 | ❌ robots.txt 전체 금지 |

**결론: API는 사용 가능하나 상업적 이용 불가. 내부 분석/연구 목적으로만 활용 가능**

---

## 1. 공식 API 현황

### 공공데이터포털 API

**엔드포인트:**
```
http://apis.data.go.kr/1352159/crisinfodataview/list    # 목록
http://apis.data.go.kr/1352159/crisinfodataview/detail  # 상세
```

**제공 데이터:**
- 목록 조회: 16개 항목
- 상세 조회: 70개 항목
- 통계: 18개 항목

**요청 파라미터:**

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| serviceKey | 필수 | API 인증키 |
| resultType | 필수 | JSON 또는 XML |
| numOfRows | 옵션 | 페이지당 결과 수 (최대 50) |
| pageNo | 옵션 | 페이지 번호 |
| srchWord | 옵션 | 검색어 (URL 인코딩 필요) |

---

## 2. 수집 가능한 데이터

### 주요 응답 필드

| 필드 | 설명 | RegScan 활용 |
|------|------|-------------|
| `trial_id` | CRIS 등록번호 | 고유 식별자 |
| `scientific_title_kr` | 연구제목 | 검색/매칭 |
| `study_type_kr` | 연구종류 | 중재연구/관찰연구 |
| `date_registration` | 등록일 | 타임라인 |
| `phase` | 임상시험 단계 | 1상/2상/3상 |
| `recruitment_status` | 모집 현황 | 모집중/완료/종료 |
| `intervention_type` | 중재 유형 | 의약품/의료기기/시술 |
| `primary_sponsor` | 스폰서 | 기업/기관 정보 |

### 연구 종류 분포 (2014년 기준)

| 유형 | 비율 |
|------|------|
| 의약품 | 48.7% |
| 의료기기 | 13.1% |
| 시술/수술 | 12.8% |
| 혼합 | 5.6% |
| 기타 | 19.9% |

---

## 3. 법적 제한 사항

### ⚠️ 핵심: 상업적 이용 불가

| 조건 | 내용 |
|------|------|
| 라이선스 | 공공누리 제2유형 |
| 출처표시 | 필수 |
| **상업적 이용** | **❌ 불가** |
| 변경/2차 저작물 | 가능 |

### 크롤링 금지

```
# robots.txt
User-agent: *
Disallow: /
```

---

## 4. 글로벌 연계

### WHO ICTRP

- CRIS는 **Primary Registry** (세계 11번째)
- 매월 1회 WHO에 XML 전송
- WHO ICTRP 검색 포털에서 CRIS 데이터 검색 가능

### ClinicalTrials.gov 비교

| 항목 | CRIS | ClinicalTrials.gov |
|------|------|-------------------|
| 한국 임상시험 | ~3,000건 | ~4,300건 |
| 다국적 연구 | 3.5% | 대부분 |
| 중복 등록 | 14% |  |

**참고:** 다국적 제약사들은 ClinicalTrials.gov 선호

---

## 5. RegScan 활용 방안

### 가능한 활용 (비상업적)

```
글로벌 신약 A가 있을 때:
1. CRIS에서 해당 성분/약물 검색
2. "국내 임상 진행 중" 여부 확인
3. 임상 단계 (1상/2상/3상) 확인
4. 모집 현황 확인

→ "국내 도입 가능성" 판단 근거로 활용
```

### 제한 사항

- MedClaim 서비스에 직접 노출 시 **상업적 이용**에 해당할 수 있음
- **내부 분석 용도**로만 활용 권장
- 사용자에게 보여줄 때는 "국내 임상 진행 여부" 정도의 간접 정보만

---

## 6. 대안: ClinicalTrials.gov

### 장점

| 항목 | 내용 |
|------|------|
| 상업적 이용 | ✅ 가능 (Public Domain) |
| 한국 임상시험 | 4,300건+ |
| API | 공식 REST API 제공 |
| 다국적 연구 | 포함 |

### API 엔드포인트

```
https://clinicaltrials.gov/api/v2/studies
```

### RegScan 활용

- CRIS 대신 ClinicalTrials.gov API 사용 가능
- 한국에서 진행 중인 임상시험 필터링: `location.country=Korea`
- 법적 제한 없음

---

## 7. 권장 접근법

### Option A: CRIS API (내부 분석용)
- 국내 임상시험 현황 파악
- 내부 의사결정 참고용
- 서비스에 직접 노출 ❌

### Option B: ClinicalTrials.gov (서비스 연동용)
- 상업적 이용 가능
- 한국 임상시험 포함
- 서비스에 직접 노출 ⭕

### Option C: 병행 사용
- 내부 분석: CRIS
- 서비스 표출: ClinicalTrials.gov

---

## 8. 결론

| 소스 | 상업적 이용 | 권장 용도 |
|------|------------|----------|
| CRIS | ❌ 불가 | 내부 분석 |
| ClinicalTrials.gov | ✅ 가능 | 서비스 연동 |

**MFDS가 우선순위 높음.** CRIS/ClinicalTrials.gov는 "국내 임상 진행 여부" 보조 지표로 활용.

---

## 9. 참고 URL

| 리소스 | URL |
|--------|-----|
| CRIS | https://cris.nih.go.kr |
| 공공데이터포털 API | https://www.data.go.kr/data/3033869/openapi.do |
| WHO ICTRP | https://trialsearch.who.int |
| ClinicalTrials.gov API | https://clinicaltrials.gov/data-api/api |
