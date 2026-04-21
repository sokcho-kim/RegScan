# 수집 모듈 이식 가이드

> 작성일: 2026-04-21
> 목적: RegScan의 수집(ingest) 모듈을 다른 파이프라인에 독립 이식할 때의 가이드

---

## 1. 이식 대상 모듈

### 핵심 파일

```
regscan/ingest/
├── base.py                 # BaseIngestor — 모든 수집기의 부모 클래스
├── __init__.py             # 35개 클래스 export
│
│  # ── 글로벌 규제 ──
├── fda.py                  # FDA openFDA (승인/Safety/AdCom/PDUFA)
├── orange_book.py          # FDA Orange Book (특허/독점권)
├── purple_book.py          # FDA Purple Book (BLA/바이오시밀러)
├── ema.py                  # EMA (의약품/오펀/부족/안전성)
├── pmda.py                 # PMDA 일본 (RSS + HTML, TLS 1.2)
│
│  # ── 해외 HTA ──
├── nice.py                 # NICE 영국 (Excel 벌크)
│
│  # ── 국내 규제 ──
├── mfds.py                 # MFDS 허가 (공공데이터 API)
├── mfds_safety.py          # MFDS 안전성 서한 + 회수 (httpx+bs4 + API)
├── hira.py                 # HIRA 약가/급여 (Playwright)
├── mohw.py                 # MOHW 입법예고 (Playwright)
├── mohw_insurance.py       # MOHW 건강보험정책 (httpx+bs4)
├── assembly.py             # 국회 의안정보 (열린국회정보 API)
├── cris.py                 # CRIS 임상시험 (공공데이터 API)
│
│  # ── 산업/학술/뉴스 ──
├── khidi.py                # KHIDI 보건산업진흥원
├── kdca.py                 # KDCA 질병관리청 (Playwright)
├── asti.py                 # ASTI 시장 조사
├── healthkr.py             # Health.kr 약학정보원 (Playwright)
└── biorxiv.py              # bioRxiv/medRxiv
```

### 필수 의존 파일

```
regscan/config/settings.py  # API 키 + ENABLE_* 토글
.env                        # 실제 키 값
```

### Python 패키지 의존성

```
httpx              # 모든 수집기의 HTTP 클라이언트
beautifulsoup4     # HTML/XML 파싱 (mfds_safety, mohw_insurance, pmda)
lxml               # XML 파서 (pmda RSS)
openpyxl           # Excel 파싱 (nice, orange_book)
playwright         # JS 렌더링 (hira, mohw, kdca, asti, healthkr)
parsel             # CSS/XPath 셀렉터 (mohw)
```

---

## 2. BaseIngestor 패턴

모든 수집기는 동일한 인터페이스를 따른다:

```python
from regscan.ingest.base import BaseIngestor

class MyIngestor(BaseIngestor):
    def source_type(self) -> str:
        return "MY_SOURCE"

    async def fetch(self) -> list[dict[str, Any]]:
        # 수집 로직
        response = await self.client.get(url)
        return parsed_records

# 사용
async with MyIngestor(days_back=30) as ingestor:
    results = await ingestor.fetch()
```

**핵심 규칙:**
- `async with` 컨텍스트 매니저로 사용 (httpx.AsyncClient 수명 관리)
- `fetch()` → `list[dict]` 반환 (표준화된 필드 + `_fetched_at`)
- 실패해도 다른 수집기에 영향 없음 (파이프라인에서 try/except)
- TLS 1.2 강제가 필요한 정부 사이트는 `__aenter__`에서 ssl context 오버라이드

---

## 3. 수집기별 특이사항

### API 키가 필요한 수집기

| 수집기 | 환경 변수 | 발급처 |
|--------|----------|--------|
| FDA | `FDA_API_KEY` | api.fda.gov (없어도 동작, rate limit만) |
| MFDS/CRIS | `DATA_GO_KR_API_KEY` | data.go.kr |
| 국회 의안 | `OPEN_ASSEMBLY_API_KEY` | open.assembly.go.kr |
| KIPRIS* | `KIPRIS_API_KEY` | plus.kipris.or.kr (미구현) |
| DART* | `DART_API_KEY` | opendart.fss.or.kr (미구현) |

### TLS 1.2 강제가 필요한 사이트

| 사이트 | 수집기 | 이유 |
|--------|--------|------|
| nedrug.mfds.go.kr | MFDSSafetyLetterIngestor | TLS 1.3 미지원, ConnectError |
| pmda.go.jp | PMDA*Ingestor | TLS 1.3 미지원 |

해결 패턴:
```python
import ssl
ctx = ssl.create_default_context()
ctx.maximum_version = ssl.TLSVersion.TLSv1_2
self._client = httpx.AsyncClient(verify=ctx)
```

### User-Agent 필수

| 사이트 | 이유 |
|--------|------|
| open.assembly.go.kr | User-Agent 없으면 400 Bad Request |
| purplebooksearch.fda.gov | Bot 감지 (Akamai), 세션 쿠키 필요 |

### Playwright 필요 수집기

| 수집기 | 이유 |
|--------|------|
| HIRA | Nexacro SSV 기반, JS 렌더링 필수 |
| MOHW 입법예고 | iframe 기반 게시판 |
| KDCA | JS 렌더링 |
| ASTI | JS 렌더링 |
| Health.kr | JS 렌더링 |

**httpx+bs4로 충분한 수집기 (Playwright 불필요):**
MFDS 안전성 서한, MOHW 건강보험, PMDA, NICE, Orange Book, Purple Book, 국회 의안

---

## 4. 파이프라인 통합 패턴

```python
# pipeline.py에서의 표준 통합 패턴
if settings.ENABLE_PMDA:
    try:
        from regscan.ingest.pmda import PMDAReviewIngestor
        async with PMDAReviewIngestor(days_back=30) as ing:
            data = await ing.fetch()
        counts["pmda"] = len(data)
        logger.info("PMDA: %d건", len(data))
    except Exception as e:
        logger.warning("PMDA 수집 실패: %s", e)
        counts["pmda"] = f"error: {e}"
```

**원칙:**
- 각 수집기는 settings 토글로 ON/OFF
- try/except로 개별 실패 격리
- 수집 결과는 counts dict에 기록
- 로깅은 `logger.info` (성공) / `logger.warning` (실패)

---

## 5. 이식 시 체크리스트

### 최소 이식 (수집만)

- [ ] `regscan/ingest/` 디렉토리 전체 복사
- [ ] `regscan/ingest/base.py` — BaseIngestor
- [ ] `regscan/config/settings.py` — API 키 + 토글 (필요한 것만)
- [ ] `.env` — 실제 키 값
- [ ] `requirements.txt`에 httpx, bs4, lxml, openpyxl 추가
- [ ] Playwright 수집기 사용 시 `playwright install chromium`

### 데이터 파이프라인 연동

- [ ] 수집 결과(`list[dict]`)를 대상 파이프라인의 저장 포맷으로 변환
- [ ] `source_type` 필드로 소스 식별
- [ ] `_fetched_at` 필드로 수집 시점 추적
- [ ] 중복 방지 로직 (list_no, bill_id 등 고유 ID 활용)

### 기존 파이프라인과의 연결점

- [ ] 심평원 고시 → `HIRA_NOTICE` / `HIRA_GUIDELINE` source_type으로 연결
- [ ] 급여 상태 변경 → `MOHW_HEALTH_INSURANCE`의 `is_relevant_dept` 플래그 활용
- [ ] 벡터DB 적재 시 `title` + `date` + `source_type` 조합으로 중복 체크

---

## 6. 알려진 한계 및 개선 방향

| 수집기 | 한계 | 개선 방향 |
|--------|------|----------|
| MOHW 건보심 | 보도자료 키워드 필터 (정밀도 낮음) | 담당부서 필터 강화, 또는 복지부 건보심 전용 페이지 발견 시 전환 |
| PMDA | RSS 영문만, 약가 수재 미포함 | 일본어 페이지 크롤링 추가 (NHI 약가와 통합 검토) |
| MFDS 회수 API | data.go.kr 키 401 | 키 갱신 후 정상화 |
| 국회 의안 | 보건의료 키워드 16개 고정 | 소관위원회(보건복지위원회) 필터 추가 검토 |
| Purple Book | Akamai bot 감지 | 세션 쿠키 방식 — 장기적으로 불안정할 수 있음 |

### 미구현 수집기 (이번 프로젝트 범위)

| 항목 | 난이도 | API | 우선순위 |
|------|--------|-----|---------|
| KIPRIS (국내 특허) | 중간 | plus.kipris.or.kr | P2 — 다음 구현 |
| DART (전자공시) | 낮음 | opendart.fss.or.kr | P2 — 다음 구현 |
| CADTH (캐나다 HTA) | 중간 | 웹 크롤링 | P3 — 이식 후 협의 |

### 이식 대상 파이프라인 사전 파악 필요사항

- 심평원 고시/심사사례의 벡터DB 적재 구조 (스키마, 청킹 전략)
- 고시 데이터와 RegScan 급여 상태(`HIRA_NOTICE`)의 중복/보완 관계
- 의료 기관/법 움직임의 구조적 매핑 (법 발의 → 고시 → 급여 결정 흐름)
