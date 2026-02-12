# RegScan v3.0 — 3-Stream 전체 실행 보고서
**작성일**: 2026-02-12

---

## 1. 전체 실행 요약

| 스트림 | 영역 | FDA | EMA | 병합 | DB 저장 | 소요시간 |
|--------|------|-----|-----|------|---------|----------|
| **Stream 1** | 항암 (oncology) | 103 | 258 | **315** | 298 | 29.2초 |
| **Stream 1** | 희귀질환 (rare_disease) | 16 | 26 | **40** | 39 | 33.1초 |
| **Stream 1** | 면역 (immunology) | 48 | 60 | **89** | 81 | 33.5초 |
| **Stream 1** | 심혈관 (cardiovascular) | 39 | 69 | **98** | 89 | 28.4초 |
| **Stream 1** | 대사/당뇨 (metabolic) | 19 | 89 | **99** | 97 | 27.5초 |
| **Stream 2** | 혁신지표 (innovation) | 39 NME | 3,102 Orphan | **2,309** | 37 | 27.6초 |
| **Stream 3** | 외부시그널 (external) | CT.gov 163 | medRxiv 12 | **248** | 0* | 67.6초 |
| **합계** | — | — | — | — | **671 drugs** | ~4분 30초 |

\* Stream 3 약물은 기존 DB 약물과 겹치는 것만 score≥10으로 저장 (현재 0건 매칭)

---

## 2. 최종 DB 현황

| 지표 | 값 |
|------|-----|
| **총 약물 수** | 671개 |
| **총 규제 이벤트** | 706건 |
| **스트림 스냅샷** | 8건 (5영역 + innovation + external + 초기oncology) |
| **스트림 브리핑** | 16건 (8 스트림 + 8 통합) |

---

## 3. v2 → v3 전환 효과

| 지표 | v2 (기존) | v3 (전체 스트림) | 변화 |
|------|----------|-----------------|------|
| 수집 약물 수 | ~100개 | **671개** | +571% |
| global_score ≥ 50 | 0건 | **5건** | ∞ |
| global_score ≥ 40 | 0건 | **18건** | ∞ |
| global_score ≥ 30 | ~4건 | **70건** | +1650% |
| global_score ≥ 20 | ~10건 | **256건** | +2460% |
| 최고 점수 | 35점 | **55점** | +57% |
| 브리핑 생성 | 0건 | **16건** | ∞ |

---

## 4. 최종 점수 분포

```
score 55:    2 약물  ██
score 50:    3 약물  ███
score 45:    1 약물  █
score 40:   12 약물  ████████████
score 35:   18 약물  ██████████████████
score 30:   34 약물  ██████████████████████████████████
score 25:   31 약물  ███████████████████████████████
score 20:  155 약물  ████████████████████████████████████████████████████
score 15:   21 약물  █████████████████████
score 10:  320 약물  ████████████████████████████████████████████████████████████████
score  5:   59 약물  ███████████████████████████████
score  0:   15 약물  ███████████████
```

---

## 5. Top 18 약물 (score ≥ 40)

| 순위 | INN | 점수 | 등급 | 유형 |
|------|-----|------|------|------|
| 1 | brexucabtagene autoleucel | 55 | MID | CAR-T (CD19, 맨틀세포 림프종) |
| 2 | dorocubicel | 55 | MID | 세포치료제 (제대혈 유래) |
| 3 | polatuzumab vedotin | 50 | MID | ADC (CD79b, DLBCL) |
| 4 | tisagenlecleucel | 50 | MID | CAR-T (CD19, ALL/DLBCL) |
| 5 | axicabtagene ciloleucel | 50 | MID | CAR-T (CD19, DLBCL) |
| 6 | talquetamab | 45 | MID | 이중특이항체 (GPRC5D, 다발골수종) |
| 7 | setmelanotide | 40 | MID | MC4R 작용제 (유전성 비만) |
| 8 | sotatercept | 40 | MID | ActRIIA-Fc (폐동맥고혈압) |
| 9 | entrectinib | 40 | MID | 키나제 억제제 (NTRK/ROS1) |
| 10 | obecabtagene autoleucel | 40 | MID | CAR-T (BCMA, 다발골수종) |
| 11 | odronextamab | 40 | MID | 이중특이항체 (CD20×CD3) |
| 12 | idecabtagene vicleucel | 40 | MID | CAR-T (BCMA, 다발골수종) |
| 13 | zanidatamab | 40 | MID | 이중특이항체 (HER2) |
| 14 | mosunetuzumab | 40 | MID | 이중특이항체 (CD20×CD3) |
| 15 | tafasitamab | 40 | MID | CD19 항체 (DLBCL) |
| 16 | ciltacabtagene autoleucel | 40 | MID | CAR-T (BCMA, 다발골수종) |
| 17 | lenvatinib | 40 | MID | 멀티키나제 억제제 (간암/갑상선암) |
| 18 | pemigatinib | 40 | MID | FGFR 억제제 (담관암) |

**패턴**: CAR-T(6건), 이중특이항체(4건), ADC(1건) — 면역치료 혁신이 최고점 독점.

---

## 6. Stream별 상세 분석

### Stream 1: 치료영역 (5개 영역)

| 영역 | FDA EPC 성공/전체 | FDA 약물 | EMA 약물 | 병합 |
|------|-------------------|----------|----------|------|
| 항암 | 12/12 | 103 | 258 | 315 |
| 희귀질환 | 3/4 | 16 | 26 | 40 |
| 면역 | 10/10 | 48 | 60 | 89 |
| 심혈관 | 7/8 | 39 | 69 | 98 |
| 대사/당뇨 | 4/5 | 19 | 89 | 99 |

**FDA EPC 검색 최적화**: 실제 FDA API의 `pharm_class_epc` 값으로 교체하여 200 OK 비율 극적 개선.
**EMA 필드명 수정**: `therapeutic_area_mesh` + `pharmacotherapeutic_group_human` 결합 검색으로 0건→258건 이상.

### Stream 2: 혁신지표

| 수집 소스 | 건수 | 비고 |
|----------|------|------|
| FDA NME (TYPE 1) | 39 | submission_class_code "TYPE 1" 성공 |
| FDA Breakthrough (code 5) | 0 | 404 (코드 형식 확인 필요) |
| EMA PRIME | 0→수정 중* | 필드명 `prime_priority_medicine` 추가 |
| EMA Orphan | 3,102 | 희귀의약품 지정 전체 |
| EMA Conditional | 0→수정 중* | 필드명 `conditional_approval` 추가 |
| PDUFA | 0 | 수동 입력 테이블 (아직 데이터 없음) |
| **총 약물** | **2,309** | 고유 INN 기준 |
| **DB 저장** | **37** | 기존 DB 약물과 겹치는 것만 score≥10 |

\* EMA PRIME/Conditional 필드명 수정 커밋 완료, 재실행 시 반영 예정

### Stream 3: 외부시그널

| 소스 | 결과 | 상태 |
|------|------|------|
| ClinicalTrials.gov Phase 3 | **163건** | 200 OK (전 condition) — 403 해결 완료 |
| medRxiv (복합 키워드) | **12건** | 500개 논문 중 12개 매칭 |

**CT.gov Triage 결과**:
| 판정 | 건수 | 설명 |
|------|------|------|
| FAIL | 22 | TERMINATED/SUSPENDED — 임상 실패/중단 속보 |
| PENDING | 105 | COMPLETED + 결과 미공개 — 워치리스트 |
| NEEDS_AI | 36 | COMPLETED + 결과 있음 — AI 판독 필요 |

**CT.gov 주요 수집 건수**:
- Cancer: 80, Neoplasm: 80, Cardiovascular Disease: 33, Carcinoma: 26
- Atopic Dermatitis: 10, Diabetes Mellitus: 10, Type 2 Diabetes: 8, Obesity: 7

**CT.gov 403 해결 방법** (2026-02-12):
- **원인**: httpx 기본 User-Agent(`python-httpx/0.x`)가 CT.gov WAF에 의해 차단
- **수정 1**: `User-Agent: RegScan/3.0 (Python aiohttp/3.12)` 헤더 추가
- **수정 2**: 쿼리 형식 개선 — `query.term` + `AREA[Condition]` → `query.cond` 전용 파라미터 사용
- **수정 3**: Phase/Date를 `filter.advanced`로 분리

---

## 7. 수정 사항 요약

### FDA EPC 용어 교체 (therapeutic.py)
| 영역 | 변경 전 → 후 | 효과 |
|------|-------------|------|
| 항암 | 20개 가상→12개 실제 | 200 OK 2/20 → 12/12 |
| 면역 | 11개 가상→10개 실제 | 200 OK ?→ 10/10 |
| 심혈관 | 13개 가상→8개 실제 | 200 OK ?→ 7/8 |
| 대사 | 10개 가상→5개 실제 | 200 OK ?→ 4/5 |
| 희귀질환 | 7개 가상→4개 실제 | 200 OK ?→ 3/4 |

### EMA JSON 필드명 수정
- `therapeuticArea` → `therapeutic_area_mesh` 추가
- `pharmacotherapeutic_group_human` 결합 검색
- `activeSubstance` → `active_substance`, `international_non_proprietary_name_common_name` 폴백
- `atcCode` → `atc_code_human` 폴백
- `primeMedicine` → `prime_priority_medicine` 추가 (innovation.py)
- `conditionalApproval` → `conditional_approval` 추가 (innovation.py)

### DB 스키마 마이그레이션
ALTER TABLE로 추가한 컬럼:
- `drugs.korea_relevance_score`, `therapeutic_areas`, `stream_sources`, `first_seen_at`
- `regulatory_events.created_at`

---

## 8. 파이프라인 6단계 흐름

```
[1/6] DB 초기화         — SQLite 테이블 create_all
[2/6] 스트림 수집        — FDA API + EMA JSON + CT.gov + medRxiv
[3/6] 병합             — INN 기준 중복 제거 + GlobalRegulatoryStatus 빌드
[4/6] DB 저장          — drugs/events/hira upsert + 변경 감지 로그
[5/6] 브리핑 생성       — GPT-4o-mini로 스트림 브리핑 + 통합 브리핑
[6/6] JSON 저장        — output/stream_results/ 에 실행 결과 JSON 보존
```

---

## 9. 남은 이슈 및 다음 단계

### 즉시 수정 필요
- [x] FDA EPC 용어 교체 (완료)
- [x] EMA JSON 필드명 수정 (완료)
- [x] DB 스키마 마이그레이션 (완료)
- [x] innovation.py EMA PRIME/Conditional 필드명 수정 (완료)
- [x] ClinicalTrials.gov 403 해결 — User-Agent 추가 + query.cond 파라미터 분리 (완료, 163건 수집 확인)

### 향후 개선
- [ ] FDA Breakthrough (code 5) 검색 실패 원인 확인
- [ ] `therapeutic_areas`, `stream_sources` 필드가 DB에 실제 반영되도록 DBLoader 수정
- [ ] 전체 3-stream 동시 실행 테스트 (`--stream` 없이)
- [ ] EMA PRIME/Conditional 재실행으로 결과 확인
- [ ] PDUFA 수동 입력 데이터 추가
- [ ] 임상시험 NEEDS_AI 36건에 대한 AI 판독 (TrialResultReader) 연결
- [ ] Stream 3 약물을 기존 DB 약물과 교차 매칭하여 score 반영

---

## 10. 실행 커맨드 레퍼런스

```bash
# Stream 1: 치료영역별
python -m regscan.batch.pipeline --stream therapeutic --area oncology
python -m regscan.batch.pipeline --stream therapeutic --area rare_disease
python -m regscan.batch.pipeline --stream therapeutic --area immunology
python -m regscan.batch.pipeline --stream therapeutic --area cardiovascular
python -m regscan.batch.pipeline --stream therapeutic --area metabolic

# Stream 2: 혁신지표
python -m regscan.batch.pipeline --stream innovation

# Stream 3: 외부시그널
python -m regscan.batch.pipeline --stream external

# 전체 실행
python -m regscan.batch.pipeline

# 레거시 모드
python -m regscan.batch.pipeline --legacy --days-back 7
```
