# 글로벌 규제기관 통합 시스템 설계

> 작성일: 2026-02-02
> 상태: 계획 단계

## 목표

FDA, EMA, PMDA, MFDS, WHO, ICH 데이터를 통합하여 **글로벌 의약품 규제 현황을 그래프 형태로 시각화**

### 핵심 가치
- 의료진/의료행정 전문가가 "이 약물이 글로벌에서 어떤 상태인지" 한눈에 파악
- 단순 키워드 기반이 아닌, 구조화된 데이터 기반 핫이슈 판별
- 규제 승인 타임라인 비교 분석

---

## Phase 1: API/데이터 소스 조사

### 1.1 FDA (미국)
- **상태**: ✅ 이미 연동됨
- **API**: openFDA (https://open.fda.gov)
- **주요 엔드포인트**: `/drug/drugsfda.json`
- **식별자**: application_number, UNII, RxCUI

### 1.2 EMA (유럽)
- **조사 필요 항목**:
  - [ ] 공개 API 존재 여부
  - [ ] 데이터 포맷 (JSON/XML)
  - [ ] 승인 약물 목록 엔드포인트
  - [ ] Orphan Designation 데이터
  - [ ] PRIME (Priority Medicines) 데이터
  - [ ] 인증/Rate limit

- **예상 소스**:
  - EMA Open Data Portal
  - European Public Assessment Reports (EPAR)
  - EU Clinical Trials Register

### 1.3 PMDA (일본)
- **조사 필요 항목**:
  - [ ] 공개 API 또는 데이터 다운로드
  - [ ] 영문 데이터 가용성
  - [ ] 승인 약물 데이터베이스
  - [ ] 심사보고서 접근성

- **예상 난점**:
  - 일본어 위주 데이터
  - API보다 PDF 심사보고서 중심일 가능성

### 1.4 MFDS (한국)
- **상태**: ✅ 이미 연동됨 (44,311건)
- **소스**: 공공데이터포털, 의약품안전나라
- **식별자**: ITEM_SEQ

### 1.5 WHO
- **조사 필요 항목**:
  - [ ] Essential Medicines List (EML) API/다운로드
  - [ ] ATC/DDD 코드 API
  - [ ] Prequalification Database
  - [ ] INN (국제일반명) 데이터베이스

- **예상 소스**:
  - WHO Collaborating Centre for Drug Statistics (ATC)
  - WHO Model Lists of Essential Medicines

### 1.6 ICH
- **조사 필요 항목**:
  - [ ] 공개 데이터 존재 여부
  - [ ] 가이드라인 데이터베이스
  - [ ] MedDRA (의학용어사전) 연계

- **참고**: ICH는 규제 조화 기구로, 개별 약물 승인 데이터보다 가이드라인 중심

---

## Phase 2: 데이터 모델 설계

### 2.1 공통 식별자 (Drug Identifier)
```
Drug
├── INN (International Nonproprietary Name) - WHO 관리
├── ATC Code - WHO 관리
├── UNII - FDA 물질 식별자
├── CAS Number - 화학물질 식별
└── Brand Names (지역별)
```

### 2.2 규제 상태 모델
```python
@dataclass
class GlobalRegulatoryStatus:
    drug_id: str  # INN or normalized name

    # 각 기관별 상태
    fda: Optional[RegulatoryApproval]
    ema: Optional[RegulatoryApproval]
    pmda: Optional[RegulatoryApproval]
    mfds: Optional[RegulatoryApproval]

    # WHO 지정
    who_eml: bool  # Essential Medicines List 등재
    who_prequalified: bool

    # 분석
    global_score: int  # 글로벌 중요도 점수
    hot_issue_reasons: list[str]

@dataclass
class RegulatoryApproval:
    status: str  # "approved", "pending", "rejected", "not_submitted"
    approval_date: Optional[date]
    application_number: str
    special_designations: list[str]  # orphan, breakthrough, priority 등
    indication: str
```

### 2.3 그래프 구조 (시각화용)
```
                    [Drug: Lecanemab]
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
   [FDA 2023-01]      [EMA 2023-07]      [PMDA 2023-09]
   Accelerated        Conditional         Approved
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                    [MFDS: Pending?]
                           │
                    [WHO EML: No]
```

---

## Phase 3: 핫이슈 스코어링 시스템

### 스코어 계산 (100점 만점)

| Factor | Score | Source |
|--------|-------|--------|
| FDA 신속심사 (Breakthrough/Priority) | +15 | FDA |
| EMA PRIME 지정 | +15 | EMA |
| FDA + EMA 동시/근접 승인 | +20 | FDA, EMA 비교 |
| WHO EML 등재 | +20 | WHO |
| Orphan Drug (희귀의약품) | +10 | FDA/EMA |
| First-in-class (신규 MOA) | +15 | ATC/pharm_class |
| 대규모 질환 (암, 당뇨, 치매) | +10 | ATC 분류 |
| 3개국 이상 승인 | +10 | 다기관 비교 |

### 등급 분류
- 🔴 **HOT** (80+): 글로벌 주목 신약
- 🟠 **HIGH** (60-79): 높은 관심
- 🟡 **MID** (40-59): 중간
- 🟢 **LOW** (<40): 일반

---

## Phase 4: 시각화

### 4.1 타임라인 뷰
```
2023-01 ──●──────────────────────────────── FDA 승인
2023-07 ────────────●──────────────────── EMA 승인
2023-09 ──────────────────●────────────── PMDA 승인
2024-?? ────────────────────────────??── MFDS 예상
```

### 4.2 글로벌 상태 그래프 (Node-Edge)
- **노드**: 각 규제기관
- **엣지**: 승인 흐름/관계
- **색상**: 승인 상태 (녹색=승인, 황색=심사중, 회색=미제출)

### 4.3 기술 스택 후보
- **Backend**: Python (기존 regscan)
- **Graph DB**: Neo4j 또는 NetworkX (경량)
- **Visualization**:
  - D3.js (웹)
  - Mermaid (마크다운 리포트용)
  - Plotly (인터랙티브)

---

## 다음 액션

### 즉시 (다음 세션)
1. [ ] EMA Open Data Portal 조사
2. [ ] PMDA 데이터 접근성 조사
3. [ ] WHO ATC/EML 데이터 다운로드 확인

### 단기
4. [ ] 공통 식별자 매핑 테이블 설계
5. [ ] GlobalRegulatoryStatus 모델 구현
6. [ ] 스코어링 시스템 구현

### 중기
7. [ ] 각 기관별 크롤러/API 클라이언트 구현
8. [ ] 그래프 시각화 프로토타입
9. [ ] MedClaim 통합

---

## 참고 자료

- openFDA: https://open.fda.gov/apis/
- EMA: https://www.ema.europa.eu/en/medicines/download-medicine-data
- PMDA: https://www.pmda.go.jp/english/
- WHO ATC: https://www.whocc.no/
- WHO EML: https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists

---

## 메모

- 이 기능은 MedClaim의 핵심 차별점이 될 수 있음
- "FDA에서 승인된 약이 한국에 언제 올까?"에 대한 예측 근거 제공
- 글로벌 비교를 통한 전문가 수준의 인사이트 제공
