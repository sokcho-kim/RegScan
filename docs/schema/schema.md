# Feed Card 스키마

> 메인화면에 표출되는 카드 콘텐츠의 데이터 구조 정의
> 최종 수정: 2026-01-29

---

## 설계 원칙

- RegScan은 **답을 하지 않는다**
- RegScan은 **보여줄 정보를 만든다**
- 모든 카드는 **1차 소스 기반** (뉴스 기사 X)
- 사용자가 **질문하지 않아도** 보여줄 정보

---

## FeedCard 스키마

모든 데이터 소스(국내 규제, FDA, EMA 등)는 이 스키마로 정규화됩니다.

```typescript
interface FeedCard {
  // === 식별 ===
  id: string;                    // 고유 ID (uuid)
  source_type: SourceType;       // 데이터 소스 구분

  // === 콘텐츠 ===
  title: string;                 // 카드 제목 (50자 이내)
  summary: string;               // 요약 (100자 이내)
  why_it_matters: string;        // 왜 중요한가 (1문장, 80자 이내)

  // === 분류 ===
  change_type: ChangeType;       // 신규 / 개정 / 삭제 / 정보
  domain: Domain[];              // 약제 / 행위 / 재료 / 기준 등
  impact_level: ImpactLevel;     // high / mid / low

  // === 시간 ===
  published_at: string;          // 원문 발행일 (ISO 8601)
  effective_at?: string;         // 적용일 (있는 경우)
  collected_at: string;          // 수집 시점

  // === 출처 (Citation Metadata) ===
  citation: Citation;

  // === 개인화 태그 (Phase 2) ===
  tags?: string[];               // 진료과, 상병코드 등
  target_roles?: Role[];         // 심사간호사 / 의사 / 경영진
}
```

---

## Enum 정의

### SourceType (데이터 소스)

| 값 | 설명 | Phase |
|----|------|-------|
| `HIRA_NOTICE` | 심평원 공지 | 1 |
| `HIRA_GUIDELINE` | 심사지침 | 1 |
| `MOHW_NOTICE` | 복지부 고시 | 1 |
| `MOHW_ADMIN_NOTICE` | 행정예고 | 1 |
| `FDA_APPROVAL` | FDA 승인 | 1 |
| `FDA_GUIDANCE` | FDA 가이드라인 | 1 |
| `EMA_DECISION` | EMA 결정 | 2 |
| `CMS_COVERAGE` | CMS 급여 결정 | 2 |
| `PUBMED_ABSTRACT` | PubMed 초록 | 2 |
| `PREPRINT` | bioRxiv/medRxiv | 2 |

### ChangeType (변경 유형)

| 값 | 설명 |
|----|------|
| `NEW` | 신규 |
| `REVISED` | 개정 |
| `DELETED` | 삭제/폐지 |
| `INFO` | 단순 정보 |

### Domain (도메인)

| 값 | 설명 |
|----|------|
| `DRUG` | 약제 |
| `PROCEDURE` | 행위/시술 |
| `MATERIAL` | 재료 |
| `CRITERIA` | 심사기준 |
| `REIMBURSEMENT` | 급여/수가 |
| `SAFETY` | 안전성 |
| `EFFICACY` | 유효성 |

### ImpactLevel (영향도)

| 값 | 설명 | UI 표현 |
|----|------|--------|
| `HIGH` | 즉시 확인 필요 | 빨간 배지 |
| `MID` | 참고 권장 | 주황 배지 |
| `LOW` | 일반 정보 | 회색 배지 |

### Role (대상 역할)

| 값 | 설명 |
|----|------|
| `REVIEWER_NURSE` | 심사간호사 |
| `PHYSICIAN` | 의사 |
| `ADMIN` | 원무/경영진 |
| `PHARMACIST` | 약사 |

---

## Citation (출처 메타데이터)

```typescript
interface Citation {
  source_id: string;           // 원문 문서 ID (고시번호 등)
  source_url: string;          // 원문 URL
  source_title: string;        // 원문 제목
  version?: string;            // 버전 (있는 경우)
  section_ref?: string;        // 섹션/조항 참조
  snapshot_date: string;       // 스냅샷 시점
}
```

> **주의**: Citation UI/정책은 MedClaim 본체 책임입니다.
> RegScan은 메타데이터만 제공합니다.

---

## 카드 예시

### 국내 규제 카드

```json
{
  "id": "card-20260129-001",
  "source_type": "MOHW_ADMIN_NOTICE",
  "title": "무릎관절 인공관절 재료대 급여기준 개정 행정예고",
  "summary": "인공관절 재료대 급여 상한금액 조정 및 적용 기준 변경",
  "why_it_matters": "정형외과 인공관절 수술 청구에 직접 영향",
  "change_type": "REVISED",
  "domain": ["MATERIAL", "REIMBURSEMENT"],
  "impact_level": "HIGH",
  "published_at": "2026-01-28T09:00:00+09:00",
  "effective_at": "2026-03-01T00:00:00+09:00",
  "collected_at": "2026-01-29T10:30:00+09:00",
  "citation": {
    "source_id": "복지부고시 제2026-12호",
    "source_url": "https://www.mohw.go.kr/...",
    "source_title": "건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수 일부개정",
    "snapshot_date": "2026-01-29"
  },
  "tags": ["정형외과", "인공관절", "재료대"],
  "target_roles": ["REVIEWER_NURSE", "ADMIN"]
}
```

### FDA 승인 카드

```json
{
  "id": "card-20260129-002",
  "source_type": "FDA_APPROVAL",
  "title": "FDA, 새로운 GLP-1 수용체 작용제 승인",
  "summary": "비만 치료 적응증으로 신규 GLP-1 제제 승인",
  "why_it_matters": "국내 도입 시 비만 약제 급여기준 논의 예상",
  "change_type": "NEW",
  "domain": ["DRUG", "EFFICACY"],
  "impact_level": "MID",
  "published_at": "2026-01-27T00:00:00Z",
  "collected_at": "2026-01-29T10:30:00+09:00",
  "citation": {
    "source_id": "NDA 215678",
    "source_url": "https://www.accessdata.fda.gov/...",
    "source_title": "Drug Approval Package: [Drug Name]",
    "snapshot_date": "2026-01-29"
  },
  "tags": ["내분비", "비만", "GLP-1"],
  "target_roles": ["PHYSICIAN", "PHARMACIST"]
}
```

---

## Python 모델

스키마는 Pydantic 모델로 구현되어 있습니다.

- 파일: `regscan/models/feed_card.py`
- 테스트: `tests/test_models.py`

---

## 관련 문서

- [프로젝트 개요](./overview.md)
- [파이프라인 구조](./pipeline.md)
- [데이터 소스](./data-sources.md)
