# 데이터 소스 현황

> 최종 수정: 2026-01-29

---

## 개요

RegScan은 **1차 소스(기관 데이터)**만 사용합니다.
- 뉴스 기사 X (저작권 문제 + 2차 가공 정보)
- 공공 데이터 기반 (합법 + 무료)

---

## 국내 데이터 소스

### 1. HIRA (건강보험심사평가원)

| 항목 | 내용 |
|------|------|
| URL | https://www.hira.or.kr |
| 수집 대상 | 공지사항, 심사지침, 보도자료 |
| 파이프라인 | ✅ **기존 구축됨** (MedClaim) |
| 비고 | 보도자료 기반 큐레이션 파이프라인 존재 |

**기존 파이프라인 정보:**
<!-- TODO: 기존 HIRA 파이프라인 상세 정보 추가 -->

---

### 2. 보건복지부

| 항목 | 내용 |
|------|------|
| URL | https://www.mohw.go.kr |
| 수집 대상 | 고시, 훈령, 행정예고 |
| 파이프라인 | ⬜ 구현 예정 |

**행정예고 시스템:**
- URL: https://www.lawmaking.go.kr
- 의견제출 기한 추출 필요

---

### 3. 국민건강보험공단

| 항목 | 내용 |
|------|------|
| URL | https://www.nhis.or.kr |
| 수집 대상 | 급여기준, 요양급여비용 |
| 파이프라인 | ⬜ 검토 중 |

---

## 글로벌 데이터 소스

### 1. FDA (미국)

| 항목 | 내용 |
|------|------|
| API | https://api.fda.gov (openFDA) |
| 수집 대상 | Drug Approvals, Guidance Documents |
| 파이프라인 | ⬜ 구현 예정 |

**주요 엔드포인트:**
- `/drug/drugsfda` - 승인 의약품
- `/drug/label` - 라벨 정보

---

### 2. EMA (유럽)

| 항목 | 내용 |
|------|------|
| URL | https://www.ema.europa.eu |
| 수집 대상 | CHMP 결정, Product Information |
| 파이프라인 | ⬜ Phase 2 |

---

### 3. CMS (미국 메디케어)

| 항목 | 내용 |
|------|------|
| URL | https://www.cms.gov |
| 수집 대상 | Coverage Decisions, NCD/LCD |
| 파이프라인 | ⬜ Phase 2 |

---

## 학술 데이터 소스 (Phase 2)

| 소스 | URL | 수집 대상 |
|------|-----|----------|
| PubMed | https://pubmed.ncbi.nlm.nih.gov | Abstract + Metadata |
| PubMed Central | https://www.ncbi.nlm.nih.gov/pmc | Open Access 전문 |
| bioRxiv | https://www.biorxiv.org | Preprint |
| medRxiv | https://www.medrxiv.org | Preprint |

> 논문은 콘텐츠가 아니라 **근거의 방향성(Evidence Signal)**로만 활용

---

## 데이터 소스 우선순위

### Phase 1 (현재, ~02/07)

1. ✅ HIRA 보도자료 (기존 파이프라인 활용)
2. 🔨 FDA Approvals
3. 🔨 복지부 행정예고

### Phase 2 (02/09 이후)

4. EMA
5. CMS
6. PubMed

---

## 기존 파이프라인 연동

<!--
여기에 기존 MedClaim의 HIRA 파이프라인 정보를 추가해주세요:
- 코드 위치
- 실행 방법
- 출력 형식
- RegScan과의 연동 방안
-->

- 기존 medclaim 관련 사항 참고 
C:\Jimin\RegScan\docs\exist_module