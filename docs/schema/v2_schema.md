# v2 DB 스키마

> 최종 수정: 2026-02-10

---

## 개요

v2에서 5개 테이블이 추가되어 총 12개 테이블 (레거시 feed_cards 포함).

```
v1 (기존 6개):
  drugs, regulatory_events, hira_reimbursements,
  clinical_trials, briefing_reports, scan_snapshots

v2 (신규 5개):
  preprints, market_reports, expert_opinions,
  ai_insights, articles
```

모든 v2 테이블은 `drugs.id`를 FK로 참조 (CASCADE 삭제).

---

## ERD

```
drugs (1) ──┬── (N) preprints
             ├── (N) market_reports
             ├── (N) expert_opinions
             ├── (N) ai_insights
             └── (N) articles
```

---

## 테이블 상세

### preprints (bioRxiv/medRxiv 논문)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동증가 |
| drug_id | Integer FK | drugs.id |
| doi | String(200) UNIQUE | DOI 식별자 |
| title | Text NOT NULL | 논문 제목 |
| authors | Text | 저자 (세미콜론 구분) |
| abstract | Text | 초록 |
| server | String(20) | biorxiv / medrxiv |
| category | String(100) | 분류 |
| published_date | Date | 게재일 |
| pdf_url | String(500) | PDF URL |
| gemini_parsed | Boolean | Gemini 파싱 여부 |
| extracted_facts | JSON | Gemini 파싱 결과 |
| collected_at | DateTime | 수집 시각 |

인덱스: `idx_preprint_drug_date (drug_id, published_date)`

---

### market_reports (ASTI/KISTI 시장 리포트)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동증가 |
| drug_id | Integer FK | drugs.id |
| source | String(30) NOT NULL | ASTI / KISTI |
| title | Text NOT NULL | 리포트 제목 |
| publisher | String(200) | 발행처 |
| published_date | Date | 발행일 |
| market_size_krw | Float | 시장 규모 (억 원) |
| growth_rate | Float | 성장률 (%) |
| summary | Text | 요약 |
| source_url | String(500) | 원본 URL |
| raw_data | JSON | 원본 데이터 |
| collected_at | DateTime | 수집 시각 |

인덱스: `idx_market_drug_source (drug_id, source)`

---

### expert_opinions (Health.kr 전문가 리뷰)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동증가 |
| drug_id | Integer FK | drugs.id |
| source | String(30) NOT NULL | KPIC / 약사저널 등 |
| title | Text NOT NULL | 리뷰 제목 |
| author | String(200) | 작성자 |
| summary | Text | 요약 |
| published_date | Date | 작성일 |
| source_url | String(500) | 원본 URL |
| raw_data | JSON | 원본 데이터 |
| collected_at | DateTime | 수집 시각 |

인덱스: `idx_expert_drug_source (drug_id, source)`

---

### ai_insights (AI 추론·검증 결과)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동증가 |
| drug_id | Integer FK | drugs.id |
| impact_score | Integer | Reasoning 영향도 점수 (0-100) |
| risk_factors | JSON | 리스크 요인 리스트 |
| opportunity_factors | JSON | 기회 요인 리스트 |
| reasoning_chain | Text | CoT 논리 전개 |
| market_forecast | Text | 시장 전망 |
| reasoning_model | String(50) | 사용 모델 (o4-mini) |
| reasoning_tokens | Integer | 토큰 사용량 |
| verified_score | Integer | 검증 후 점수 (0-100) |
| corrections | JSON | 수정 사항 리스트 |
| confidence_level | String(20) | high / medium / low |
| verifier_model | String(50) | 검증 모델 (gpt-5.2) |
| verifier_tokens | Integer | 토큰 사용량 |
| generated_at | DateTime | 생성 시각 |

인덱스: `idx_insight_drug_date (drug_id, generated_at)`

> append only — 이력 보존을 위해 기존 행을 갱신하지 않고 새 행을 추가.

---

### articles (AI 기사)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동증가 |
| drug_id | Integer FK | drugs.id |
| article_type | String(30) NOT NULL | briefing / newsletter / press_release |
| headline | Text NOT NULL | 기사 제목 |
| subtitle | Text | 부제목 |
| lead_paragraph | Text | 리드 문단 |
| body_html | Text | 본문 (HTML) |
| tags | JSON | 태그 리스트 |
| writer_model | String(50) | 사용 모델 (gpt-5.2) |
| writer_tokens | Integer | 토큰 사용량 |
| generated_at | DateTime | 생성 시각 |

인덱스: `idx_article_drug_type (drug_id, article_type)`

> (drug_id, article_type) 기준 upsert — 같은 약물/유형이면 최신 기사로 교체.

---

## 마이그레이션

`Base.metadata.create_all` 사용 중이므로 신규 테이블은 자동 생성.
기존 테이블에는 변경 없음 (relationship만 추가).

```python
# 검증 명령
python -c "from regscan.db.database import init_db; import asyncio; asyncio.run(init_db())"
```
