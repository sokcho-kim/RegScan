# RegScan v2 → v3 방향 전환 리포트

**작성일**: 2026-02-12

---

## 왜 바꿨나

### v2까지의 상황

RegScan v2는 "최근 7일 FDA/EMA/MFDS 승인"을 수집하는 **Bottom-Up** 방식이었다.
매일 배치를 돌리면 이런 흐름:

```
매일 → FDA/EMA/MFDS 7일치 수집 → 전수 스코어링 → 전수 AI 기사 생성
```

결과:
- 약물 ~100개 수집
- 최고 점수 35점 (MID 등급 진입 실패)
- score ≥ 40 (AI 파이프라인 임계값): **0건**
- bioRxiv 키워드 매칭: **0건**
- 브리핑 생성: **0건**

**사실상 전체 AI 파이프라인이 작동하지 않는 상태.**

v2 코드 자체는 완성되어 있었다 — 3단 AI 엔진(o4-mini→GPT-5.2→GPT-5.2), 4대 스트림(규제팩트/선행기술/시장규모/현장반응), DB 11개 테이블. 하지만 입력 데이터가 임계값을 넘지 못해서 파이프라인 뒷단이 전부 공회전.

### 근본 원인

**"7일치 잡탕 수집"이 너무 좁다.**

FDA가 일주일에 신약 승인을 1~2건 하는데, 그중 한국과 관련 있는 건 더 적다. 7일 윈도우로는 의미 있는 볼륨이 절대 나올 수 없다. 아무리 AI 파이프라인을 정교하게 만들어도 먹일 데이터가 없으면 무용지물.

2/11 작업일지에 적은 고민:
> "카탈로그식 전수 발행 → 의미 없는 기사 양산. 134개 약물 전부에 기사를 쓰려 하니 MFDS-only OTC까지 AI를 태움."

점수 필터링(score < 10 DB 차단, score < 40 AI 제외)으로 임시 조치했지만, 근본적으로 수집 전략 자체를 바꿔야 했다.

---

## 뭘 바꿨나

### 핵심 전환: Bottom-Up → Top-Down

```
[Before] 시간 기준 — "최근 7일에 뭐가 승인됐나?"
                     → 잡탕 수집 → 대부분 저점

[After]  주제 기준 — "항암/희귀/면역/심혈관/대사 영역에서 중요한 약물은?"
                     → 치료영역별 전수 수집 → 고점 약물이 자연스럽게 포함
```

### v3 3-Stream 아키텍처

| 스트림 | 수집 대상 | 기대 효과 |
|--------|----------|----------|
| **Stream 1: 치료영역** | 5개 영역별 FDA pharm_class + EMA therapeutic_area 전수 | 날짜 제한 없이 해당 영역의 모든 승인 약물 포착 |
| **Stream 2: 혁신지표** | FDA NME/Breakthrough + EMA PRIME/Orphan/Conditional + PDUFA | Breakthrough, PRIME 등 고점 지정이 있는 약물 직접 타겟 |
| **Stream 3: 외부시그널** | ClinicalTrials.gov Phase 3 + medRxiv | 승인 전 단계의 미래 시그널 포착 |

각 스트림이 독립 수집 → 독립 브리핑 + 통합 브리핑.

### 신규 구현 파일 (17개)

```
regscan/stream/__init__.py        — 패키지
regscan/stream/base.py            — BaseStream, StreamResult
regscan/stream/therapeutic.py     — Stream 1: 치료영역 (5개 영역 설정 + FDA/EMA 수집)
regscan/stream/innovation.py      — Stream 2: 혁신지표 (NME/BT/PRIME/Orphan/Conditional/PDUFA)
regscan/stream/external.py        — Stream 3: 외부시그널 (CT.gov + medRxiv)
regscan/stream/orchestrator.py    — 스트림 오케스트레이터
regscan/stream/briefing.py        — 스트림별 브리핑 생성기
regscan/stream/trial_triage.py    — CT.gov 3단계 판독 (FAIL/PENDING/NEEDS_AI)
regscan/ingest/clinicaltrials.py  — ClinicalTrials.gov v2 API 클라이언트
regscan/parse/clinicaltrials_parser.py — CT.gov 파서
regscan/map/competitor.py         — 제네릭/바이오시밀러 매핑
regscan/ai/trial_reader.py       — AI 임상결과 판독
regscan/api/routes/pdufa.py      — PDUFA API
regscan/api/routes/briefings.py  — 브리핑 API
tests/test_stream_therapeutic.py
tests/test_stream_innovation.py
tests/test_stream_external.py
```

### 수정 파일 (6개)

```
regscan/config/settings.py   — 스트림 설정 추가
regscan/ingest/fda.py        — search_by_pharm_class(), search_by_submission_class()
regscan/ingest/biorxiv.py    — MedRxivCompoundIngestor
regscan/db/models.py         — 신규 테이블 6개 + DrugDB 컬럼 추가
regscan/batch/pipeline.py    — StreamOrchestrator 통합, --stream/--area/--legacy 플래그
regscan/api/main.py          — 브리핑/PDUFA 라우터 등록
```

---

## 실행하면서 터진 것들

구현 자체는 하루 만에 끝났지만, 실제로 돌려보니 5개의 연쇄 버그가 터졌다.

### 1. DB 스키마 불일치
- **증상**: `no such column: drugs.korea_relevance_score`
- **원인**: SQLAlchemy `create_all()`은 기존 테이블에 컬럼을 추가하지 않음
- **해결**: ALTER TABLE로 5개 컬럼 수동 추가

### 2. FDA EPC 용어 전멸 (18/20 → 404)
- **증상**: "PD-1 Blocking Antibody" 같은 EPC 용어가 FDA API에서 404
- **원인**: 실제 FDA pharm_class_epc 값은 "Programmed Death Receptor-1 Blocking Antibody" 같은 풀네임
- **해결**: pembrolizumab, trastuzumab 등 실제 약물을 조회해서 EPC 값을 역추출. 5개 영역 전부 교체
- **결과**: 200 OK 비율 2/20 → 36/39

### 3. EMA 0건 (필드명 변경)
- **증상**: EMA medicines JSON에서 치료영역 필터링 결과 0건
- **원인**: EMA가 camelCase(`therapeuticArea`) → snake_case(`therapeutic_area_mesh`)로 형식 변경
- **해결**: `therapeutic_area_mesh` + `pharmacotherapeutic_group_human` 결합 검색, `active_substance` 폴백 추가
- **결과**: 0건 → 258건 (항암 기준)

### 4. ClinicalTrials.gov 전면 403
- **증상**: 38개 condition 전부 403 Forbidden
- **원인**: httpx 기본 User-Agent가 CT.gov WAF에 차단됨
- **해결**: User-Agent 헤더 추가 + `query.cond` 전용 파라미터로 쿼리 형식 개선
- **결과**: 0건 → 163건

### 5. EMA PRIME/Conditional 0건
- **증상**: Innovation Stream에서 EMA PRIME, Conditional 모두 0건
- **원인**: 3번과 같은 snake_case 문제 (`primeMedicine` → `prime_priority_medicine`)
- **해결**: 필드명 폴백 추가
- **결과**: PRIME 0→46건, Conditional 0→59건

---

## 결국 어디까지 왔나

### 수치 비교

| 지표 | v2 (어제까지) | v3 (오늘) | 변화 |
|------|-------------|----------|------|
| 수집 약물 수 | ~100개 | **2,979개** (병합 후 633 DB) | +29x |
| score ≥ 40 | **0건** | **18건** | 0→18 |
| score ≥ 30 | ~4건 | **70건** | +17x |
| 최고 점수 | 35점 | **55점** | +57% |
| 브리핑 생성 | **0건** | **8건** (스트림별) + 통합 | 0→8 |
| CT.gov Phase 3 | 없음 | **163건** (FAIL 22, AI판독 36) | 신규 |
| EMA PRIME | 없음 | **46건** | 신규 |
| EMA Orphan | 없음 | **3,102건** | 신규 |
| 전체 실행 시간 | ~30초 | **135.6초** | +4.5x |

### 전체 3-Stream 동시 실행 성공

```bash
python -m regscan.batch.pipeline   # 플래그 없이 전체 실행
```

```
[1/6] DB 초기화         ✓
[2/6] 스트림 수집       ✓  Stream1(641) + Stream2(2368) + Stream3(248)
[3/6] 병합             ✓  2,979개 고유 약물
[4/6] DB 저장          ✓  633건 저장, 73건 변경 감지
[5/6] 브리핑 생성       ✓  8건 (GPT-4o-mini)
[6/6] JSON 저장        ✓
=== 완료 (135.6초) ===
```

### Top 5 약물 (score ≥ 50)

| INN | 점수 | 유형 |
|-----|------|------|
| brexucabtagene autoleucel | 55 | CAR-T (CD19, 맨틀세포 림프종) |
| dorocubicel | 55 | 세포치료제 (제대혈 유래) |
| polatuzumab vedotin | 50 | ADC (CD79b, DLBCL) |
| tisagenlecleucel | 50 | CAR-T (CD19, ALL/DLBCL) |
| axicabtagene ciloleucel | 50 | CAR-T (CD19, DLBCL) |

CAR-T와 ADC가 최상위 — 면역치료 혁신이 점수 상위를 독점.

---

## 아직 안 된 것

### 당장 문제
1. **주간 브리핑 데이터량 부족** — 실측 결과 주 1회 기준 ~29건, LLM이 "주요 변동 없음" 판정
2. **Stream 3 약물이 DB에 안 들어감** — 기존 DB 약물과 INN 매칭이 안 돼서 0건 저장
3. **FDA Breakthrough (code 5) 계속 404**

### 데이터 소스 보강 필요 (다음 작업)
현재 소스만으로는 주간 브리핑이 빈약. 추가 후보:
- FDA Safety Alert / Boxed Warning 변경
- FDA Advisory Committee 회의록
- MFDS 허가/변경사항
- 제약사 프레스릴리즈
- PDUFA D-day 카운트다운

### v2 소스 통합
v2에서 만들어둔 ASTI(시장규모), Health.kr(전문가리뷰), Gemini PDF 파서는 아직 v3에 통합되지 않음. 이것들이 붙으면 브리핑 깊이가 달라질 수 있음.

---

## 한 줄 요약

**"7일치 잡탕" → "치료영역별 전수 수집"으로 전환한 결과, AI 파이프라인 입력이 0건→18건으로 살아났고, 3-Stream 전체 동시 실행이 검증되었다. 다음 과제는 주간 브리핑을 알차게 만들 데이터 소스 보강.**
