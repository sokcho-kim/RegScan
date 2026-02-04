# FDA 수집 파이프라인 구현 계획 (v2)

> 작성일: 2026-01-29
> 상태: 결정사항 반영

---

## 결정 사항 요약

| 항목 | 결정 | 비고 |
|------|------|------|
| API 키 | **발급 (무료)** | 일일 120,000건 |
| why_it_matters | **LLM + 템플릿 폴백** | 상세 설계 아래 |
| 수집 주기 | **일 1회** | 배치 작업 |
| 저장 형식 | **DB** | SQLite 권장 |

---

## 1. API 키 (무료)

### 비용

| 항목 | 내용 |
|------|------|
| 가격 | **무료** |
| 발급 방법 | https://open.fda.gov 에서 계정 생성 후 발급 |

### Rate Limit 비교

| 조건 | 분당 | 일일 |
|------|------|------|
| 키 없음 | 240 | 1,000 |
| **키 있음** | 240 | **120,000** |

→ **발급 권장**: 무료이고, 일일 한도 120배 증가

### 사용 방법

```python
# 환경 변수
FDA_API_KEY=your_api_key_here

# 요청
https://api.fda.gov/drug/drugsfda.json?api_key={FDA_API_KEY}&search=...
```

---

## 2. why_it_matters 생성 전략

### 아키텍처: LLM + 템플릿 폴백

```
┌─────────────────────────────────────────────────────────┐
│                    FDA 승인 데이터                       │
│  (brand_name, generic_name, indication, sponsor)        │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              WhyItMattersGenerator                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │  1. LLM 시도 (OpenAI / Claude)                   │   │
│  │     - 타임아웃: 5초                              │   │
│  │     - 실패 시 → 폴백                             │   │
│  │                                                  │   │
│  │  2. 템플릿 폴백                                  │   │
│  │     - LLM 실패/비용 초과/긴급 시                 │   │
│  │     - 즉시 응답                                   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.1 LLM 프롬프트 설계

```python
# regscan/scan/why_it_matters.py

LLM_PROMPT = """
당신은 한국 의료/보험 규제 전문가입니다.

FDA가 다음 의약품을 승인했습니다:
- 약제명: {brand_name} ({generic_name})
- 적응증: {indication}
- 제약사: {sponsor}
- 승인 유형: {submission_type}

이 승인이 **한국 의료/보험 시장**에 미칠 영향을 1문장으로 설명하세요.

규칙:
1. 80자 이내
2. "국내", "급여", "허가", "도입" 등 한국 관점 키워드 포함
3. 구체적 영향 명시 (예: "급여 확대 논의", "허가 심사 가속화")
4. 불확실한 경우 "~가능성", "~예상" 표현 사용

예시:
- "국내 도입 시 비만 치료제 급여기준 확대 논의 예상"
- "동일 계열 국내 허가 약제 적응증 추가 심사 가속화 가능"
- "희귀질환 급여 특례 적용 검토 촉발 전망"
"""

async def generate_with_llm(data: dict) -> str:
    """LLM으로 why_it_matters 생성"""
    prompt = LLM_PROMPT.format(
        brand_name=data.get("brand_name", ""),
        generic_name=data.get("generic_name", ""),
        indication=data.get("indication", "정보 없음"),
        sponsor=data.get("sponsor", ""),
        submission_type=data.get("submission_type", ""),
    )

    # OpenAI 또는 Claude 호출
    response = await llm_client.chat(
        model="gpt-4o-mini",  # 비용 효율
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        timeout=5.0,
    )

    return response.strip()[:80]  # 80자 제한
```

### 2.2 템플릿 폴백 설계

```python
# regscan/scan/why_it_matters.py

TEMPLATES = {
    # submission_type 기반
    "ORIG": "국내 도입 시 {domain} 분야 급여기준 논의 예상",
    "SUPPL": "기존 승인 약제의 적응증 확대, 국내 허가 변경 가능",
    "ABBREV": "제네릭 승인으로 국내 동일 성분 약가 인하 압력 예상",

    # domain 기반 (indication 키워드 매칭)
    "oncology": "항암제 급여 확대 및 신속심사 대상 검토 가능",
    "rare_disease": "희귀질환 급여 특례 적용 검토 촉발 전망",
    "cardiovascular": "심혈관계 약제 급여기준 재검토 가능성",
    "diabetes": "당뇨병 치료제 급여 범위 확대 논의 예상",
    "obesity": "비만 치료제 급여 적용 논의 본격화 가능",

    # 기본값
    "default": "국내 허가 및 급여기준 검토에 참고 자료로 활용 예상",
}

def generate_with_template(data: dict) -> str:
    """템플릿으로 why_it_matters 생성"""
    submission_type = data.get("submission_type", "")
    indication = data.get("indication", "").lower()
    domain = data.get("domain", "의약품")

    # 1. submission_type 매칭
    if submission_type in TEMPLATES:
        return TEMPLATES[submission_type].format(domain=domain)

    # 2. indication 키워드 매칭
    keyword_map = {
        "cancer": "oncology",
        "tumor": "oncology",
        "leukemia": "oncology",
        "orphan": "rare_disease",
        "rare": "rare_disease",
        "heart": "cardiovascular",
        "cardiac": "cardiovascular",
        "diabetes": "diabetes",
        "obesity": "obesity",
        "weight": "obesity",
    }

    for keyword, template_key in keyword_map.items():
        if keyword in indication:
            return TEMPLATES[template_key]

    # 3. 기본값
    return TEMPLATES["default"]
```

### 2.3 통합 Generator

```python
# regscan/scan/why_it_matters.py

class WhyItMattersGenerator:
    def __init__(self, use_llm: bool = True, llm_client = None):
        self.use_llm = use_llm
        self.llm_client = llm_client

    async def generate(self, data: dict) -> tuple[str, str]:
        """
        why_it_matters 생성

        Returns:
            tuple: (text, method) - 생성된 텍스트와 사용된 방법
        """
        # LLM 시도
        if self.use_llm and self.llm_client:
            try:
                text = await generate_with_llm(data)
                return (text, "llm")
            except Exception as e:
                logger.warning(f"LLM 실패, 템플릿 폴백: {e}")

        # 템플릿 폴백
        text = generate_with_template(data)
        return (text, "template")
```

### 2.4 비용 추정 (LLM)

| 모델 | 입력 토큰 | 출력 토큰 | 건당 비용 | 일 100건 |
|------|----------|----------|----------|---------|
| GPT-4o-mini | ~300 | ~50 | ~$0.0001 | ~$0.01 |
| Claude Haiku | ~300 | ~50 | ~$0.0001 | ~$0.01 |

→ **일 $0.01 수준**: 비용 부담 거의 없음

---

## 3. 수집 주기: 일 1회 배치

### 스케줄

```
┌─────────────────────────────────────────────────────────┐
│  매일 오전 9:00 KST (00:00 UTC)                          │
│  ─────────────────────────────────────────────────────  │
│  1. FDA API 호출 (전일 승인 건 조회)                     │
│  2. 파싱 + FeedCard 변환                                 │
│  3. DB 저장                                              │
│  4. (선택) 슬랙/이메일 알림                              │
└─────────────────────────────────────────────────────────┘
```

### 쿼리 전략

```python
# 어제 날짜 기준 조회
from datetime import datetime, timedelta

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
today = datetime.now().strftime("%Y%m%d")

query = f"submissions.submission_status_date:[{yesterday}+TO+{today}]"
```

### 실행 방법

```bash
# 수동 실행
python -m regscan.scripts.collect_fda

# 스케줄러 (cron)
0 9 * * * cd /path/to/regscan && python -m regscan.scripts.collect_fda

# 또는 Windows Task Scheduler
```

---

## 4. 저장 형식: DB

### 추천: SQLite (초기) → PostgreSQL (확장 시)

| 옵션 | 장점 | 단점 | 추천 상황 |
|------|------|------|----------|
| **SQLite** | 설치 불필요, 파일 기반, 간단 | 동시 쓰기 제한 | **초기 개발, 단일 서버** |
| PostgreSQL | 동시성, 확장성, JSON 지원 | 설치/운영 필요 | 프로덕션, 다중 서버 |
| MongoDB | 스키마 유연, JSON 네이티브 | 운영 복잡 | 비정형 데이터 많을 때 |

→ **SQLite로 시작, 필요 시 PostgreSQL 마이그레이션**

### 테이블 설계

```sql
-- feed_cards 테이블
CREATE TABLE feed_cards (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,

    -- 콘텐츠
    title TEXT NOT NULL,
    summary TEXT,
    why_it_matters TEXT,
    why_it_matters_method TEXT,  -- 'llm' or 'template'

    -- 분류
    change_type TEXT,
    domain TEXT,  -- JSON array
    impact_level TEXT,

    -- 시간
    published_at TIMESTAMP,
    effective_at TIMESTAMP,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 출처
    citation TEXT,  -- JSON object

    -- 개인화
    tags TEXT,  -- JSON array
    target_roles TEXT,  -- JSON array

    -- 메타
    raw_data TEXT,  -- 원본 JSON (디버깅용)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX idx_source_type ON feed_cards(source_type);
CREATE INDEX idx_published_at ON feed_cards(published_at);
CREATE INDEX idx_impact_level ON feed_cards(impact_level);
CREATE INDEX idx_collected_at ON feed_cards(collected_at);
```

### Python 모델 (SQLAlchemy)

```python
# regscan/db/models.py

from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class FeedCardDB(Base):
    __tablename__ = "feed_cards"

    id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)

    title = Column(String(100), nullable=False)
    summary = Column(String(200))
    why_it_matters = Column(String(100))
    why_it_matters_method = Column(String(20))

    change_type = Column(String(20))
    domain = Column(JSON)
    impact_level = Column(String(10))

    published_at = Column(DateTime)
    effective_at = Column(DateTime)
    collected_at = Column(DateTime)

    citation = Column(JSON)
    tags = Column(JSON)
    target_roles = Column(JSON)

    raw_data = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

### 저장소 클래스

```python
# regscan/db/repository.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

class FeedCardRepository:
    def __init__(self, db_url: str = "sqlite+aiosqlite:///data/regscan.db"):
        self.engine = create_async_engine(db_url)

    async def save(self, card: FeedCard) -> None:
        """카드 저장 (upsert)"""
        pass

    async def get_by_date(self, date: str) -> list[FeedCard]:
        """날짜별 조회"""
        pass

    async def get_recent(self, limit: int = 10) -> list[FeedCard]:
        """최근 카드 조회"""
        pass
```

---

## 5. 수정된 구현 계획

### 디렉토리 구조 (수정)

```
regscan/
├── ingest/
│   └── fda.py              # FDA API 클라이언트
├── parse/
│   └── fda_parser.py       # FDA 응답 파서
├── scan/
│   ├── signal_generator.py # FeedCard 변환
│   └── why_it_matters.py   # LLM + 템플릿 (신규)
├── db/                     # DB 레이어 (신규)
│   ├── __init__.py
│   ├── models.py           # SQLAlchemy 모델
│   └── repository.py       # 저장소 클래스
├── config/
│   └── settings.py         # 설정 (API 키 등)
└── scripts/
    └── collect_fda.py      # 일일 수집 스크립트
```

### 구현 단계 (수정)

| Step | 작업 | 예상 |
|------|------|------|
| 1 | DB 레이어 (SQLite + SQLAlchemy) | 2시간 |
| 2 | FDA API 클라이언트 | 2시간 |
| 3 | FDA 파서 | 1시간 |
| 4 | WhyItMattersGenerator (LLM + 템플릿) | 2시간 |
| 5 | FeedCard 변환 + 저장 | 1시간 |
| 6 | 일일 수집 스크립트 | 1시간 |
| 7 | 테스트 | 2시간 |
| **합계** | | **11시간** |

---

## 6. 의존성 추가

```toml
# pyproject.toml 수정

[project]
dependencies = [
    # 기존
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
    "pydantic>=2.5.0",

    # DB
    "sqlalchemy>=2.0.0",
    "aiosqlite>=0.19.0",

    # LLM (선택)
    "openai>=1.0.0",
]
```

---

## 다음 단계

1. [ ] 의존성 설치
2. [ ] DB 레이어 구현
3. [ ] FDA API 클라이언트 구현
4. [ ] WhyItMattersGenerator 구현
5. [ ] 통합 테스트

---

## 참고 자료

- [openFDA API 인증](https://open.fda.gov/apis/authentication/) - API 키 무료 발급
- [Drugs@FDA API](https://open.fda.gov/apis/drug/drugsfda/)
