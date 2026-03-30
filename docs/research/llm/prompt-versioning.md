# RegScan 프롬프트 버전 체계

> 작성: 2026-03-30 | 기준: Fastcampus Part 8 시맨틱 버전닝 규칙

## 1. 버전 규칙 (Semantic Versioning)

| 변경 유형 | 버전 업 | 예시 |
|-----------|---------|------|
| 새 기능 / 구조 변경 / 토큰 대폭 변경 | **Major** (X.0.0) | 프롬프트 신규 생성, 출력 스키마 변경 |
| 부분 수정 / 개선 | **Minor** (x.Y.0) | Few-shot 추가, 관점 가이드 추가, 규칙 보강 |
| 오타 / 출력 버그 | **Patch** (x.y.Z) | 오타 수정, 필드명 정정 |
| 피드백 반영 | Minor 또는 Patch | 크기에 따라 판단 |

## 2. 프롬프트 카탈로그

RegScan에는 **4개 프롬프트 시스템**이 있다. 각각 독립적으로 버전을 관리한다.

### 2-1. drug-briefing (약물별 개별 브리핑)

| 항목 | 내용 |
|------|------|
| 파일 | `regscan/report/prompts.py` |
| 역할 | 개별 약물의 Executive Briefing 생성 (headline, key_points, insight 등 6필드) |
| 렌더링 | Jinja2 HTML 템플릿과 결합 |
| 스냅샷 | `output/briefings/snapshots/2026-02-25_v4/` |

**버전 이력:**

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| 1.0.0 | 초기 | 기본 브리핑 생성 |
| 2.0.0 | - | 동적 소제목, 시각적 구조화, 생애주기별 앵글 |
| 3.0.0 | - | Dynamic Headings, Visual Chunking, Contextual Translation |
| **4.0.0** | 2026-02 | Fact/Insight 분리, Python 사전계산, 6필드 strict JSON |
| **4.1.0** | 2026-02 | Executive Tone, KHIDI/KDCA 인용 가이드, Few-shot 3쌍 완전한 입출력 |

**적용 기법:** Persona, Few-shot (3쌍 완전 입출력), CoT (분석 프레임 5단계), Anti-pattern (금지표현 대안표), Domain Knowledge (급여/규제), 생애주기 분기 (미허가/비급여/급여완료)

### 2-2. stream-briefing (스트림 Executive Briefing)

| 항목 | 내용 |
|------|------|
| 파일 | `regscan/stream/briefing.py` |
| 역할 | 3개 스트림(치료영역/혁신/외부시그널) + 통합 브리핑 생성 |
| 프롬프트 | SYSTEM_PROMPT + THERAPEUTIC/INNOVATION/EXTERNAL/UNIFIED_BRIEFING_PROMPT |

**버전 이력:**

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| **1.0.0** | 2026-03 | 스트림 브리핑 신규 생성 (V1) |
| **1.1.0** | 2026-03 | Executive Tone 적용 (V2) |
| **1.2.0** | 2026-03-27 | 시간추론 규칙, GOOD/BAD 톤 예시, _extract_drug_intel 14필드, 통합 브리핑 JSON 직접 주입 |

| **2.0.0** | 2026-03-30 | 공통 기반(shared) 분리, Few-shot 완전 입출력, CoT 추론 시연, 금지표현 대안표, 생애주기 분기, 분석 프레임, Persona 확장, 도메인 지식 주입 |

**V2.0.0 주요 변경:** drug-briefing 4.1.0에서 검증된 기법을 `regscan/prompts/shared.py` 공통 모듈로 추출 → 양쪽 시스템이 동일 기반을 공유. 진단서 P0-P1 전체 적용.

### 2-3. ai-pipeline (Reasoning + Verifier + Writer)

| 항목 | 내용 |
|------|------|
| 파일 | `regscan/ai/prompts/reasoning_prompt.py`, `verifier_prompt.py`, `writer_prompt.py` |
| 역할 | o4-mini 추론 → GPT-5.2 검증 → GPT-5.2 기사 작성 (3단계 Prompt Chaining) |

**버전 이력:**

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| **1.0.0** | 초기 | 3단계 파이프라인 신규 생성 |

### 2-4. llm-curation (보험심사 이슈 큐레이션)

| 항목 | 내용 |
|------|------|
| 파일 | 별도 프로젝트 (scrape-hub 연동) |
| 참고 | `docs/research/llm/llm-curation.md`, `llm-curation-model-prompt.md` |

## 3. 기존 네이밍과의 매핑

기존에 "V3", "V4" 등으로 불렀던 것이 어디에 해당하는지:

| 기존 호칭 | 실제 대상 | 시맨틱 버전 |
|-----------|----------|-------------|
| "V4 프롬프트" | drug-briefing | **4.1.0** |
| "V3 프롬프트 재설계" | stream-briefing | **1.2.0** |
| "V2 Executive Tone" | stream-briefing | 1.1.0 |
| "V1 스트림 브리핑" | stream-briefing | 1.0.0 |

**혼란의 원인:** drug-briefing의 V4와 stream-briefing의 V3이 별개 시스템인데, 같은 "V" 접두사를 쓰면서 버전이 역행하는 것처럼 보였음. 앞으로는 `{시스템명}-{시맨틱버전}` 형식을 사용한다.

예: `stream-briefing-2.0.0`, `drug-briefing-4.2.0`

## 4. 공통 기반 모듈

### `regscan/prompts/shared.py` (shared-1.0.0)

drug-briefing과 stream-briefing이 공유하는 빌딩 블록:

| 블록 | 설명 |
|------|------|
| `PERSONA` | 수석 규제 인텔리전스 분석가, 10년 경력, 독자 타겟 |
| `TIME_REASONING_RULES` | 시간추론 규칙 + CoT 시연 3개 |
| `ANTI_PATTERN_TABLE` | 금지표현 7쌍 + 대안 |
| `DOMAIN_KNOWLEDGE_REIMBURSEMENT` | 급여 5종 테이블 |
| `DOMAIN_KNOWLEDGE_REGULATORY` | 규제 프로세스 5항목 + GIFT |
| `LIFECYCLE_BRANCHES` | 생애주기 4분기 |
| `EXECUTIVE_TONE_RULES` | BLUF, So What, 간결 문장 등 6원칙 |
| `OUTPUT_FORMAT_RULES` | JSON만 출력, HTML 금지 |
| `build_system_prompt()` | 블록 조합 헬퍼 함수 |

## 5. 다음 버전 계획

### stream-briefing 2.0.0 ✅ 완료 (2026-03-30)

- [x] Few-shot: 완전한 입출력 쌍 (치료영역 1쌍 + 혁신 1쌍)
- [x] CoT: 시간추론 과정을 예시로 시연 (shared.TIME_REASONING_RULES)
- [x] 금지표현 대안표 추가 (shared.ANTI_PATTERN_TABLE)
- [x] 생애주기별 분기 (shared.LIFECYCLE_BRANCHES)
- [x] Persona 확장 (shared.PERSONA)
- [x] 도메인 지식 주입 (shared.DOMAIN_KNOWLEDGE_*)
- [x] 스트림별 분석 프레임 추가 (3-4단계)
- [ ] Prompt Chaining 검토 (통합 브리핑 2단계 분리) — P2, 다음 iteration
