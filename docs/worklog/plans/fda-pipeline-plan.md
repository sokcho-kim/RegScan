# FDA 수집 파이프라인 구현 계획

> 작성일: 2026-01-29
> 상태: 계획 수립 중

---

## 1. 목표

FDA의 신약 승인 정보를 수집하여 FeedCard로 변환, MedClaim 메인화면 "글로벌 동향" 섹션에 표출

---

## 2. 데이터 소스 분석

### openFDA API

| 항목 | 내용 |
|------|------|
| 기본 URL | `https://api.fda.gov` |
| 형식 | JSON |
| 인증 | API 키 (선택, 무료) |
| 업데이트 | 월~금 일일 |

### Rate Limit

| 조건 | 분당 | 일일 |
|------|------|------|
| API 키 없음 | 240 | 1,000 |
| API 키 있음 | 240 | 120,000 |

→ 초기에는 API 키 없이 시작, 필요 시 발급

### 주요 엔드포인트

| 엔드포인트 | 설명 | 우선순위 |
|-----------|------|---------|
| `/drug/drugsfda.json` | 신약 승인 정보 (1939~현재) | **1순위** |
| `/drug/label.json` | 의약품 라벨 정보 | 2순위 |
| `/drug/ndc.json` | NDC 코드 정보 | 3순위 |

---

## 3. 수집 대상 선정

### Phase 1: Drug Approvals (`/drug/drugsfda`)

**수집 대상:**
- 최근 N일간 승인된 신약
- New Drug Application (NDA)
- Biologics License Application (BLA)

**주요 필드:**

| 필드 | 설명 | FeedCard 매핑 |
|------|------|--------------|
| `application_number` | NDA/BLA 번호 | `citation.source_id` |
| `sponsor_name` | 제약사 | `tags` |
| `products[].brand_name` | 브랜드명 | `title` |
| `products[].generic_name` | 성분명 | `title`, `tags` |
| `products[].dosage_form` | 제형 | `tags` |
| `submissions[].submission_type` | 제출 유형 | `change_type` |
| `submissions[].submission_status_date` | 승인일 | `published_at` |

---

## 4. 구현 계획

### 4.1 디렉토리 구조

```
regscan/
├── ingest/
│   └── fda.py              # FDA 수집기 (기존 파일 확장)
├── parse/
│   └── fda_parser.py       # FDA 응답 파싱 (신규)
└── config/
    └── fda_config.py       # FDA API 설정 (신규)
```

### 4.2 구현 단계

#### Step 1: API 클라이언트 구현

```python
# regscan/ingest/fda.py

class FDAClient:
    BASE_URL = "https://api.fda.gov"

    async def search_drug_approvals(
        self,
        from_date: str,      # YYYYMMDD
        to_date: str,
        limit: int = 100
    ) -> dict:
        """최근 승인 의약품 조회"""
        pass
```

**구현 내용:**
- [ ] httpx 기반 비동기 클라이언트
- [ ] Rate limit 처리 (재시도 로직)
- [ ] 날짜 범위 쿼리
- [ ] 페이지네이션 처리

#### Step 2: 응답 파서 구현

```python
# regscan/parse/fda_parser.py

class FDADrugParser:
    def parse_approval(self, raw: dict) -> dict:
        """FDA 응답을 중간 형식으로 변환"""
        pass
```

**파싱 내용:**
- [ ] 브랜드명/성분명 추출
- [ ] 승인일 파싱
- [ ] 적응증 추출 (가능한 경우)
- [ ] 제약사 정보

#### Step 3: FeedCard 변환

```python
# regscan/scan/signal_generator.py (기존 파일 확장)

def _generate_fda_why_it_matters(self, raw_data: dict) -> str:
    """FDA 승인 → why_it_matters 생성"""
    # 템플릿 또는 LLM
    pass
```

**변환 규칙:**
| FDA 데이터 | FeedCard 필드 | 변환 로직 |
|-----------|--------------|----------|
| brand_name + generic_name | `title` | "FDA, {brand_name}({generic_name}) 승인" |
| submission_type | `change_type` | ORIG → NEW, SUPPL → REVISED |
| - | `domain` | 기본 [DRUG], 적응증 기반 추가 |
| - | `impact_level` | 규칙 기반 (신약=MID, 적응증 확장=LOW) |
| - | `why_it_matters` | 템플릿 또는 LLM |

#### Step 4: 스케줄러/실행기

```python
# scripts/collect_fda.py

async def main():
    """FDA 데이터 수집 실행"""
    # 1. 최근 7일 승인 조회
    # 2. 파싱
    # 3. FeedCard 변환
    # 4. 저장
```

---

## 5. why_it_matters 생성 전략

### Option A: 템플릿 기반 (빠름, 단순)

```python
templates = {
    "NEW": "국내 도입 시 {domain} 분야 급여기준 논의 예상",
    "REVISED": "기존 승인 약제의 적응증 확대, 국내 허가 변경 가능성",
}
```

### Option B: LLM 기반 (정교함, 비용)

```python
prompt = """
FDA가 다음 약제를 승인했습니다:
- 약제명: {brand_name} ({generic_name})
- 적응증: {indication}
- 제약사: {sponsor}

이 승인이 한국 의료/보험 시장에 미칠 영향을 1문장(80자 이내)으로 설명하세요.
"""
```

**결정 필요**: 초기에는 템플릿, 이후 LLM으로 확장?

---

## 6. API 쿼리 예시

### 최근 7일 승인 조회

```
GET https://api.fda.gov/drug/drugsfda.json
  ?search=submissions.submission_status_date:[20260122+TO+20260129]
  &limit=100
```

### 특정 제약사 조회

```
GET https://api.fda.gov/drug/drugsfda.json
  ?search=sponsor_name:"pfizer"
  &limit=10
```

---

## 7. 예상 출력 (FeedCard)

```json
{
  "id": "card-20260129-fda-001",
  "source_type": "FDA_APPROVAL",
  "title": "FDA, Wegovy(semaglutide) 심혈관 적응증 추가 승인",
  "summary": "기존 비만 치료제에 심혈관 질환 위험 감소 적응증 추가",
  "why_it_matters": "국내 GLP-1 제제 급여기준 확대 논의 촉발 가능",
  "change_type": "REVISED",
  "domain": ["DRUG", "EFFICACY"],
  "impact_level": "MID",
  "published_at": "2026-01-25T00:00:00Z",
  "collected_at": "2026-01-29T15:00:00+09:00",
  "citation": {
    "source_id": "NDA 215256",
    "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=215256",
    "source_title": "Wegovy (semaglutide) Approval",
    "snapshot_date": "2026-01-29"
  },
  "tags": ["내분비", "비만", "GLP-1", "Novo Nordisk"],
  "target_roles": ["PHYSICIAN", "PHARMACIST"]
}
```

---

## 8. 일정

| 단계 | 작업 | 예상 소요 |
|------|------|----------|
| Step 1 | API 클라이언트 | 2-3시간 |
| Step 2 | 응답 파서 | 2시간 |
| Step 3 | FeedCard 변환 | 2시간 |
| Step 4 | 테스트 + 디버깅 | 2시간 |
| **합계** | | **8-9시간** |

---

## 9. 리스크 및 고려사항

| 리스크 | 대응 |
|--------|------|
| Rate limit 초과 | 재시도 로직 + 지수 백오프 |
| 필드 누락 | Optional 처리 + 기본값 |
| 적응증 정보 부족 | `/drug/label` API 추가 조회 검토 |
| 한글 번역 | Phase 2에서 LLM 번역 검토 |

---

## 10. 결정 필요 사항

1. **API 키 발급 여부**: 일일 1,000건이면 충분할까?
2. **why_it_matters 생성**: 템플릿 vs LLM?
3. **수집 주기**: 일 1회? 실시간?
4. **저장 형식**: JSON 파일 vs DB?

---

## 다음 단계

계획 승인 후:
1. [ ] FDAClient 구현
2. [ ] 테스트 쿼리 실행
3. [ ] 파서 구현
4. [ ] FeedCard 변환 테스트
