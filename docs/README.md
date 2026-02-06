# RegScan 문서 목차

> 글로벌 의약품 규제 인텔리전스 시스템 -- 프로젝트 문서 인덱스
>
> 최종 정리: 2026-02-06

---

## 프로젝트 개요

| 문서 | 설명 |
|------|------|
| [overview.md](./overview.md) | RegScan 프로젝트 전체 개요 및 목적 |
| [pipeline.md](./pipeline.md) | 데이터 수집 ~ LLM 브리핑까지 파이프라인 구조도 |
| [data-sources.md](./data-sources.md) | 1차 데이터 소스(FDA, EMA, MFDS 등) 현황 |
| [roadmap.md](./roadmap.md) | 아키텍처 로드맵 (Mermaid 다이어그램 포함) |
| [status.md](./status.md) | 구현 현황 및 진행 상태 |
| [project_setting.md](./project_setting.md) | 프로젝트 환경 설정 안내 |

---

## architecture/ -- 설계 문서

| 문서 | 설명 |
|------|------|
| [fastapi_implementation_plan.md](./architecture/fastapi_implementation_plan.md) | FastAPI 서버 구현 계획서 |
| [llm_report_generation.md](./architecture/llm_report_generation.md) | LLM 기반 브리핑 리포트 자동 생성 설계 |
| [mfds_hira_matching_plan.md](./architecture/mfds_hira_matching_plan.md) | MFDS-HIRA 매칭 파이프라인 설계 |
| [timeline_ml_design.md](./architecture/timeline_ml_design.md) | FDA/EMA 승인 → MFDS 허가 소요기간 ML 예측 모델 설계 |
| [project_structure.md](./architecture/project_structure.md) | 프로젝트 디렉토리 구조 가이드 |

---

## research/ -- 조사 및 실험

### research/api/ -- API 조사

| 문서 | 설명 |
|------|------|
| [2026-02-03_cris_api_research.md](./research/api/2026-02-03_cris_api_research.md) | CRIS(임상시험 정보) API 조사 |
| [2026-02-03_global_regulatory_api_research.md](./research/api/2026-02-03_global_regulatory_api_research.md) | 글로벌 규제기관(FDA/EMA/PMDA 등) API 통합 조사 |
| [2026-02-03_mfds_api_research.md](./research/api/2026-02-03_mfds_api_research.md) | 식약처(MFDS) 공공데이터포털 API 조사 |
| [2026-02-04_hira_data_research.md](./research/api/2026-02-04_hira_data_research.md) | 건강보험심사평가원(HIRA) 데이터 조사 |
| [2026-02-04_inn_matching_research.md](./research/api/2026-02-04_inn_matching_research.md) | INN(국제일반명) 매칭 방법론 조사 |

### research/matching/ -- 매칭 실험

| 문서 | 설명 |
|------|------|
| [2026-02-04_matching_experiment_final_report.md](./research/matching/2026-02-04_matching_experiment_final_report.md) | MFDS-HIRA 매칭 실험 최종 보고서 |
| [2026-02-04_matching_experiment_result.md](./research/matching/2026-02-04_matching_experiment_result.md) | 매칭 실험 결과 데이터 및 분석 |

### research/benchmarks/ -- 벤치마크 및 UI 리서치

| 문서 | 설명 |
|------|------|
| [260127_benchmark_scrapbook.md](./research/benchmarks/260127_benchmark_scrapbook.md) | 경쟁 서비스 벤치마크 스크랩북 |
| [260126_gemini_research.md](./research/benchmarks/260126_gemini_research.md) | Gemini 활용 리서치 결과 |
| [260126_perplexity_research.md](./research/benchmarks/260126_perplexity_research.md) | Perplexity 활용 리서치 결과 |
| [260126_ui_research_unified.md](./research/benchmarks/260126_ui_research_unified.md) | UI/UX 리서치 통합 정리 |
| [medclaim_ui_redesign.md](./research/benchmarks/medclaim_ui_redesign.md) | 메드클레임 UI 리디자인 분석 |
| [capture_benchmarks.py](./research/benchmarks/capture_benchmarks.py) | 벤치마크 스크린샷 캡처 스크립트 |
| [crop_key_areas.py](./research/benchmarks/crop_key_areas.py) | 스크린샷 주요 영역 크롭 스크립트 |
| `screenshots/` | 벤치마크 스크린샷 원본 및 크롭 이미지 |

### research/llm/ -- LLM 관련 자료

| 문서 | 설명 |
|------|------|
| [llm-curation.md](./research/llm/llm-curation.md) | LLM 큐레이션 기능 설계 (이슈 해설 노트 생성) |
| [llm-curation-model-prompt.md](./research/llm/llm-curation-model-prompt.md) | LLM 큐레이션 모델별 프롬프트 및 비교 |
| [model_comparison_report.md](./research/llm/model_comparison_report.md) | LLM 모델 비교 통합 보고서 |
| [hira-data-pipeline.md](./research/llm/hira-data-pipeline.md) | HIRA 데이터 수집 자동화 파이프라인 설계 |

---

## schema/ -- 데이터 스키마

| 문서 | 설명 |
|------|------|
| [schema.md](./schema/schema.md) | Feed Card 스키마 정의 (요약) |
| [feed_card_schema.md](./schema/feed_card_schema.md) | Feed Card 스키마 상세 명세 |

---

## changelog/ -- 변경 이력

| 문서 | 설명 |
|------|------|
| [2026-02-06.md](./changelog/2026-02-06.md) | 2026-02-06 품질 개선 리포트 (EMA/MFDS 버그 수정 등) |

---

## meetings/ -- 회의록

| 문서 | 설명 |
|------|------|
| [260123.md](./meetings/260123.md) | 2026-01-23 메드클레임 서비스 개편 및 UI/UX 회의록 |

---

## data/ -- 데이터 인벤토리

| 문서 | 설명 |
|------|------|
| [DATA_SOURCES_INVENTORY.md](./data/DATA_SOURCES_INVENTORY.md) | MFDS-HIRA 매칭 실험용 데이터 소스 인벤토리 |

---

## proposal/ -- 서버 제안서

| 문서 | 설명 |
|------|------|
| [regscan_server_proposal.qmd](./proposal/regscan_server_proposal.qmd) | RegScan 서버 제안서 (Quarto 원본) |
| [regscan_server_proposal.pdf](./proposal/regscan_server_proposal.pdf) | RegScan 서버 제안서 (PDF) |
| [gcp_cloud_run_spec.md](./proposal/gcp_cloud_run_spec.md) | GCP Cloud Run 사양 검토 |
| [gcp_instance_spec.md](./proposal/gcp_instance_spec.md) | GCP 인스턴스 사양 검토 |
| [dashboard_mockup.html](./proposal/dashboard_mockup.html) | 대시보드 목업 (HTML) |
| [detail_mockup.html](./proposal/detail_mockup.html) | 상세 페이지 목업 (HTML) |
| [report_mockup.html](./proposal/report_mockup.html) | 리포트 목업 (HTML) |

---

## worklog/ -- 작업 일지

| 문서 | 설명 |
|------|------|
| [2026-01-29.md](./worklog/2026-01-29.md) | 1/29 작업 일지 |
| [2026-01-31.md](./worklog/2026-01-31.md) | 1/31 작업 일지 |
| [2026-02-02.md](./worklog/2026-02-02.md) | 2/02 작업 일지 |
| [2026-02-03.md](./worklog/2026-02-03.md) | 2/03 작업 일지 |
| [2026-02-04.md](./worklog/2026-02-04.md) | 2/04 작업 일지 |
| [2026-02-05.md](./worklog/2026-02-05.md) | 2/05 작업 일지 |

### worklog/decisions/ -- 의사결정 기록

| 문서 | 설명 |
|------|------|
| [001-feed-card-schema.md](./worklog/decisions/001-feed-card-schema.md) | ADR #001: Feed Card 스키마 결정 |

### worklog/plans/ -- 주간/기능별 계획

| 문서 | 설명 |
|------|------|
| [2026-01-week5.md](./worklog/plans/2026-01-week5.md) | 1월 5주차 계획 |
| [2026-02-02_fda_kr_mapping.md](./worklog/plans/2026-02-02_fda_kr_mapping.md) | FDA-국내 매핑 계획 |
| [2026-02-02_global_regulatory_integration.md](./worklog/plans/2026-02-02_global_regulatory_integration.md) | 글로벌 규제기관 통합 계획 |
| [2026-02-04_domestic_impact_pipeline.md](./worklog/plans/2026-02-04_domestic_impact_pipeline.md) | 국내 영향 분석 파이프라인 계획 |
| [fda-pipeline-plan.md](./worklog/plans/fda-pipeline-plan.md) | FDA 파이프라인 계획 v1 |
| [fda-pipeline-plan2.md](./worklog/plans/fda-pipeline-plan2.md) | FDA 파이프라인 계획 v2 |
