# Decision 001: Feed Card 스키마 설계

> 일자: 2026-01-29
> 상태: 승인됨

---

## 배경

MedClaim 메인화면 개편을 위해 RegScan이 제공할 카드 콘텐츠의 데이터 구조가 필요함.

---

## 결정 사항

### 1. 통합 스키마 사용

모든 데이터 소스(국내 규제, FDA, EMA 등)를 **단일 FeedCard 스키마**로 정규화

**이유**:
- 프론트엔드에서 일관된 렌더링 가능
- 소스별 분기 처리 최소화
- 확장성 확보

### 2. 핵심 필드 구성

| 필드 | 선택 이유 |
|------|----------|
| `why_it_matters` | 회의 요구사항 "왜 중요한지 1문장" 반영 |
| `impact_level` | 우선순위 정렬, 시각적 강조용 |
| `change_type` | 신규/개정/삭제 구분으로 변화 감지 |
| `citation` | 출처 신뢰성 확보 (메타데이터 수준) |

### 3. Citation은 메타데이터만

**포함**: source_id, source_url, version, snapshot_date
**제외**: UI 렌더링 방식, 하이라이트 로직

→ Citation UI/정책은 MedClaim 본체 책임

---

## 대안 검토

| 대안 | 기각 이유 |
|------|----------|
| 소스별 개별 스키마 | 프론트 복잡도 증가, 유지보수 어려움 |
| Citation UI 포함 | RegScan 범위 초과 |

---

## 참조

- [Feed Card 스키마 문서](../../analysis/schema/feed_card_schema.md)
- [회의록 260123](../../analysis/meetings/260123.md)
