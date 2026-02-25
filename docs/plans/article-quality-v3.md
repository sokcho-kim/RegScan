# 기사 품질 개선 계획 — v3.0 "Executive Briefing"

> **이전 버전**: [article-quality-v2.md](./article-quality-v2.md) (2026-02-19)
> **작성일**: 2026-02-25
> **변경 사유**: v2 계획의 Phase A~C-1 완료 후, 남은 항목 정리 + Gemini 전략 자문 반영

---

## v2 → v3 변경 이력

| 항목 | v2 상태 | v3 변경 |
|------|---------|---------|
| Phase A (프롬프트) | v3.0→v4.0 완료 | 완료 확인, V4.1 톤 조정 추가 |
| Phase B-1 (기존 필드 6개) | 완료 | 완료 확인 |
| Phase B-2 (경쟁약 DB) | 완료 | 완료 확인 |
| Phase B-3 (EMA 적응증) | 완료 | 완료 확인 |
| Phase B-4 (타임라인 예측) | 휴리스틱만 | **통계 모델은 별도 데이터 수집 후 진행으로 변경** |
| Phase C-1 (CT.gov 결과) | 완료 | 완료 확인 |
| Phase C-2 (약가 시뮬레이션) | 미착수 | **구체화: therapeutic_areas 기반 가격 통계** |
| Phase C-3 (뉴스 → LLM) | 미착수 | 스크래퍼 프레임워크 존재, 연동만 필요로 재정의 |
| — (신규) KHIDI 시장 맥락 | — | **신규 추가 (C-4)** |
| — (신규) 프롬프트 V4.1 | — | **신규 추가 (Phase D)** |

---

## 완료된 항목 (v2 기준)

### Phase A: 프롬프트 — ✅ 완료

- A-1: SYSTEM_PROMPT → 수석 기자 페르소나, 독자 타겟 명시
- A-2: 섹션 역할 재정의 (사실 나열 → 분석 기사)
- A-3: Few-Shot 3종 (긍정/경고/탐색), 금지 표현 16개
- A-4: V4 팩트/인사이트 분리 + Prompt A(Positive Framing) A/B 테스트 통과
- **구현 파일**: `regscan/report/prompts.py` (SYSTEM_PROMPT_V4, BRIEFING_REPORT_PROMPT_V4)

### Phase B-1~3: 입력 데이터 보강 — ✅ 완료

- B-1: therapeutic_areas, quadrant, days_since, korea_relevance 등 6필드 LLM 주입
- B-2: EMA therapeutic_area + indication 키워드 매칭 → 경쟁약 Top 5 주입
- B-3: EMA API `_fetch_ema_indication_index()` → indication 텍스트 LLM 주입
- **구현 파일**: `regscan/report/llm_generator.py`, `regscan/scripts/publish_articles.py`

### Phase C-1: CT.gov 임상 결과 — ✅ 완료

- `parse_results_section()`: primary/secondary outcome, adverse events, 한계점 자동 추출
- HR, CI, p-value → LLM 입력에 포함
- **구현 파일**: `regscan/parse/clinicaltrials_parser.py`, `regscan/report/llm_generator.py`

---

## 남은 항목: 실행 계획

### Phase B-4: 타임라인 통계 예측 — 🔒 데이터 수집 선행 필요

**현재 상태**: 휴리스틱 분류만 구현 (`d_day_text`: "승인 후 1028일, 장기 미허가")

**필요한 데이터 (미보유)**:
- FDA→MFDS 허가 지연 이력 (신약 기준, 최소 수십 건)
- EMA→MFDS 허가 지연 이력
- 치료영역별/적응증별 지연 패턴

**현재 DB 상태**: FDA+MFDS 동시 승인 날짜가 있는 약물 6건뿐, 모두 제네릭(이부프로펜 등)으로 신약 허가 패턴과 무관

**실행 계획**:
1. **데이터 수집 (별도 프로젝트)**: MFDS 공개 허가 이력 전수 DB 확보 → FDA/EMA 매칭
2. **모델 구축**: 치료영역별 중앙값/사분위 지연일수 산출
3. **파이프라인 통합**: `_prepare_drug_data_v4()`에 `expected_mfds_window` 주입

**선행 조건**: 외부 데이터 수집 완료 후 진행. 현재 휴리스틱 유지.

---

### Phase C-2: 가격 스펙트럼 시스템 — ⬅️ 다음 구현 대상 (착수)

> **상세 설계**: [c2-price-spectrum-design.md](./c2-price-spectrum-design.md) (2026-02-25)

**목표**: HIRA 원본 데이터(30,418건 급여)에서 `class_no`(약효분류코드) × original/generic 세그먼트별 백분위 가격 스펙트럼을 사전 계산하여 LLM에 제공

**v3 원안 대비 변경 (2026-02-25 데이터 조사 후)**:

| 항목 | v3 원안 | 변경 후 |
|------|---------|---------|
| 분류 키 | therapeutic_areas (EMA) | **class_no** (HIRA 원본, 120개, 미분류 0%) |
| 데이터 소스 | DB 353건 | **HIRA 원본 30,418건** (DB 의존 제거) |
| 통계 방식 | 단순 평균 | **백분위 스펙트럼** (P25/P50/P75/P90) |
| 세그먼트 | 없음 | **original/generic 분리** (`동일 의약품` 필드) |
| 선행 작업 | therapeutic_areas 79건 보정 | **불필요** (class_no는 HIRA 원본 필드) |

**설계 방식**: Plan B — 사전 계산 테이블 (`hira_price_stats`, ≤240행)

**수정 파일**:

| 파일 | 변경 |
|------|------|
| `regscan/db/models.py` | `HiraPriceStatsDB` 모델 추가 |
| `regscan/report/price_stats.py` | **신규** — 가격 스펙트럼 모듈 |
| `regscan/report/llm_generator.py` | `_prepare_drug_data_v4()`에 `price_spectrum` 주입 |
| `regscan/report/prompts.py` | V4 프롬프트에 가격 스펙트럼 해석 규칙 추가 |
| `regscan/scripts/publish_articles.py` | 기사 생성 전 `check_and_rebuild_if_needed()` 호출 |

---

### Phase C-3: 뉴스 → LLM 연동 — 프레임워크 존재, 연결만 필요

**현재 상태**:
- `scripts/scraping/multi_news_scraper.py` — 스크래퍼 프레임워크 구현 완료
- 메디게이트뉴스, 약업신문, Endpoints News, FiercePharma 지원
- `data/scraping/` 에 크롤링 데이터 존재
- **LLM 입력에 미연결** — `_prepare_drug_data()`에 뉴스 데이터 미포함

**구현 계획**:
1. INN 기준으로 관련 뉴스 최신 1~2건 매칭
2. `_prepare_drug_data_v4()`에 `recent_news` 필드 추가
3. 프롬프트에 "최근 뉴스를 맥락으로 인용하라" 규칙 추가

**수정 파일**:

| 파일 | 변경 |
|------|------|
| `regscan/report/llm_generator.py` | `recent_news` 필드 추가 |
| `regscan/report/prompts.py` | 뉴스 인용 규칙 |

---

### Phase C-4: KHIDI 시장 맥락 주입 — 신규

**목표**: 치료영역별 거시적 시장 트렌드를 기사에 반영 (단발 인용, 기사 맥락 제공)

**데이터 소스**: KHIDI (한국보건산업진흥원) PDF 리포트 → 수작업 발췌

**구현 계획**:
1. 치료영역별 2~3문장 요약을 JSON으로 관리
   ```
   data/context/market_context.json
   {
     "oncology": "2025년 글로벌 항암제 시장은 2,800억 달러로...",
     "rare_disease": "FDA 희귀질환 바우처 부활 기조 속...",
     "immunology": "..."
   }
   ```
2. `_prepare_drug_data_v4()`에 `market_context` 주입
3. 프롬프트에 "도입부에서 market_context를 인용하라" 규칙 추가

**선행 작업**: KHIDI 리포트에서 영역별 핵심 문단 수동 발췌 (자동화 불가)

---

### Phase D: 프롬프트 V4.1 (Executive Tone) — C-2 이후 진행

**목표**: "전문기자" → "병원 행정 전략가" 톤 미세 조정

**주의사항**:
- 현재 V4 프롬프트는 A/B 테스트(2026-02-24)를 거쳐 안정화된 상태
- 톤 변경은 새 A/B 테스트 필수
- 현재 V4도 이미 유사한 톤 달성 ("2,232일째, DLBCL ADC Polatuzumab 국내는 공백")
- 큰 변경보다 미세 튜닝 수준 예상

**변경 방향**:
- 감정적 형용사 제거 → 드라이한 행정 용어 ("처방 공백", "재정 영향")
- 헤드라인: 의학 용어 중심 → 의사결정 키워드 중심
- 가격/시장 데이터(C-2, C-4) 반영 후 프롬프트 조정이 효과적

**의존성**: C-2(약가), C-4(KHIDI) 완료 후 진행 권장

---

## 실행 순서

```
C-2 약가 시뮬레이션 ←── 다음 구현
  ├─ 선행: therapeutic_areas 미분류 79건 보정
  ├─ get_price_stats() 함수
  ├─ V4 팩트에 price_simulation 주입
  └─ 프롬프트 가격 참조 규칙 추가

C-4 KHIDI 시장 맥락 (수작업 데이터 준비 후)
  ├─ market_context.json 작성
  └─ 프롬프트 인용 규칙 추가

C-3 뉴스 → LLM 연동
  ├─ INN 기준 뉴스 매칭
  └─ recent_news 필드 주입

Phase D 프롬프트 V4.1 (C-2 + C-4 완료 후)
  ├─ Executive Tone A/B 테스트
  └─ 스냅샷 비교 뷰어로 품질 검증

B-4 타임라인 통계 (별도 데이터 수집 프로젝트)
  ├─ MFDS 허가 이력 전수 DB 확보
  ├─ FDA/EMA 매칭 + 지연일수 산출
  └─ 파이프라인 통합
```

---

## 품질 검증 체계

모든 프롬프트/데이터 변경 후:
1. `snapshot_articles.py --name "{날짜}_{변경내용}"` — 변경 전 스냅샷
2. 기사 재생성 (`publish_articles --v4`)
3. 자동 스냅샷 (파이프라인 완료 시 자동 저장 + 프롬프트 보관)
4. `compare_articles.py --a {before} --b {after}` — 비교 HTML로 품질 확인
5. 품질 지표 자동 체크 (반복 문구, 금지 표현, 숫자 훅, MOA 연쇄, 한계점)
