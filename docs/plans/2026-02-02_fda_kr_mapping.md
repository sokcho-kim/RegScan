# FDA→KR 매핑 엔진 구현 계획

> 작성일: 2026-02-02
> 목표: FDA 승인 약물의 국내 급여 상태 분석 및 예측

---

## 1. 배경

### RegScan의 핵심 가치
- **기존 파이프라인 (medclaim-report-pipeline)**: 복지부 입법/행정예고, 보도자료
- **RegScan 차별점**: 해외 승인 → 국내 급여 경로 분석

### 타겟 사용자
- 의료진, 의료행정 전문가
- **필요한 것**: 비교기준, 시간축, 제도통과 경로, 실제 선례 검증

---

## 2. 분석 프레임워크

### 2.1 비교기준
- 동일 ATC 계열 약물
- 동일 적응증 약물
- 대체재 현황 및 급여기준

### 2.2 시간축
```
FDA 승인 → MFDS 허가 → HIRA 급여
   │           │           │
   └───────────┴───────────┘
         소요 기간 분석
```

### 2.3 제도통과 경로
1. FDA 승인
2. MFDS 허가 (식약처)
3. 약가 협상
4. HIRA 급여 평가
5. 고시 등재

### 2.4 선례 검증
- 동일 계열 약물의 실제 경로
- 소요 기간 통계
- 적용된 급여기준

---

## 3. 데이터 소스

| 소스 | 데이터 | 위치 | 상태 |
|------|--------|------|------|
| FDA | 승인 정보 | openFDA API | ✅ 파이프라인 있음 |
| MFDS | 허가 정보 (44,311건) | scrape-hub/mfds | △ 데이터 있음, 파이프라인 필요 |
| HIRA 고시 | 급여기준 | RegScan 크롤러 | ✅ 파이프라인 있음 |
| ATC 매핑 | 성분-ATC 연결 (21,702건) | scrape-hub/kpis | △ 데이터 있음, 파이프라인 필요 |
| 고시 히스토리 | 과거 급여 이력 (4,573건) | scrape-hub/cg_parsed | △ 데이터 있음 |

---

## 4. 구현 계획

### Phase 1: 매칭 로직 (오늘)
- [ ] 성분명 정규화 로직
- [ ] FDA↔MFDS 매칭
- [ ] MFDS↔HIRA 매칭
- [ ] Timeline 테이블 스키마

### Phase 2: Timeline 구축
- [ ] 기존 데이터로 히스토리 테이블 생성
- [ ] FDA→MFDS→HIRA 소요기간 통계
- [ ] ATC 계열별 평균 소요기간

### Phase 3: 분석 엔진
- [ ] 신규 FDA 승인 → 국내 상태 조회
- [ ] 동일 계열 선례 검색
- [ ] 예상 급여 시점 추정

### Phase 4: 리포트 생성
- [ ] 전문가용 리포트 포맷
- [ ] 비교기준/시간축/경로/선례 통합

---

## 5. 기술 설계

### 5.1 매칭 키
```python
# 성분명 정규화
def normalize_ingredient(name: str) -> str:
    # 소문자 변환
    # 특수문자 제거
    # 염/수화물 등 접미사 정규화
    # 예: "Belumosudil Mesylate Micronized" → "belumosudil"
```

### 5.2 Timeline 스키마
```python
@dataclass
class DrugTimeline:
    ingredient_name: str      # 정규화된 성분명
    ingredient_name_kr: str   # 한글 성분명

    # FDA
    fda_approval_date: date
    fda_application_number: str
    fda_indication: str

    # MFDS
    mfds_permit_date: date
    mfds_item_seq: str

    # HIRA
    hira_coverage_date: date
    hira_notification_number: str
    hira_criteria_summary: str

    # 분석
    fda_to_mfds_days: int
    mfds_to_hira_days: int
    total_days: int
```

### 5.3 디렉토리 구조
```
regscan/
├── map/                    # Map Engine (신규)
│   ├── __init__.py
│   ├── timeline.py         # Timeline 모델 및 로직
│   ├── matcher.py          # FDA↔MFDS↔HIRA 매칭
│   ├── analyzer.py         # 선례 분석
│   └── report.py           # 리포트 생성
```

---

## 6. 검증 케이스

| 약물 | FDA | MFDS | HIRA | 예상 |
|------|-----|------|------|------|
| Semaglutide | 2017-12 | 2022-04 | 2026-02 | ~8년 |
| Belumosudil | 2021-07 | 2024-08 | 2026-02 | ~4.5년 |
| Pembrolizumab | 2014-09 | 2015-03 | (기존) | ~6개월 |

---

## 7. 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| 성분명 불일치 | 정규화 + 유의어 사전 |
| MFDS 데이터 최신성 | 파이프라인 구축 (Phase 2) |
| 적응증별 시차 | 적응증 단위 매칭 (향후) |

---

## 8. 성공 기준

1. FDA 승인 약물 → 국내 상태 조회 가능
2. 동일 계열 선례 3건 이상 제시
3. 소요기간 통계 기반 예상 시점 제시
