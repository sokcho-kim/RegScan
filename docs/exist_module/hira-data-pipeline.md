# 데이터 수집 자동화

## 데이터 파이프라인 구성

<aside>

[수집]
├─► 크롤링(hira)
│     ├─► 고시 ─────────────────────► LLM 파싱 ──┐ # 고시.xlsx
│     ├─► 행정해석  ─── 첨부키워드有: Upstage ──────────┤ # 행정해석.xlsx
│     ├─► 심사지침   ───────────────────────────┤ # 심사지침.xlsx
│     ├─► 심의사례공개 ─ 첨부키워드有: Upstage ─► LLM 파싱  ─┤ # 사례.xlsx
│     └─► 심사사례지침 ─ 첨부키워드有: Upstage ─► LLM 파싱  ─┘         │
│                                                                                                                                │# 요양급여심사지침.xlsx
└─► PDF 다운로드 ─► Upstage ─► 수작업 검수 ─► excel combine ──┤# 요양급여약제.xlsx
                                                                                                     (1차 전처리)         ▼
                                                                                                   기본 전처리(dropna, drop_duplicated)
                                                                                                                                   ▼
                                                                                                                            [저장(xlsx)]

</aside>


## ai-data-cli, opensearch-uploader 수정사항 정리

### 1️⃣ **ai-data-cli 프로젝트**

- `src/ai_data_cli/excel_cli_unified.py`

---

### 📄 **excel_cli_unified.py** (라인 547-564)

**수정 내용**: 수동 전략 모드에서 컬럼 선택 시 입력 검증 강화

**변경 전**:

```python
selected_indices = Prompt.ask(
    "\n포함할 컬럼을 선택하세요 (쉼표로 구분, 예: 1,3,4)",
    validator=lambda x: all(...)  # validator만 사용
)
selected_cols = [columns[int(i.strip()) - 1] for i in selected_indices.split(",")]

```

**변경 후**:

```python
while True:  # 재입력 루프 추가
    selected_indices = Prompt.ask(...)
    try:
        indices = [i.strip() for i in selected_indices.split(",")]
        if all(idx.isdigit() and 1 <= int(idx) <= len(columns) for idx in indices):
            selected_cols = [columns[int(i) - 1] for i in indices]
            break
        else:
            console.print(f"[red]❌ 잘못된 컬럼 번호...[/red]")
    except (ValueError, IndexError):
        console.print("[red]❌ 올바른 형식이 아닙니다...[/red]")
```

**개선 효과**:

- ❌ 이전: 잘못된 입력 시 프로그램 크래시
- ✅ 이후: 에러 메시지 표시 후 재입력 요청

### 2️⃣ **ai-db-opensearch-uploader 프로젝트**

- `scripts/upload_to_opensearch_en.py`

### 📄 **upload_to_opensearch_en.py**

**주요 수정 사항**:

### 1. **SSL 동적 설정** (라인 61-72) → 로컬환경 맞춤, 프로젝트에서는 불필요

```python
# 변경 전
use_ssl=True  # 항상 SSL 사용

# 변경 후
use_ssl = opensearch_url.startswith('https://')  # URL에 따라 자동 결정
```

- HTTP 연결 지원 (로컬 테스트 환경)

### 2. **인덱스 매핑 방식 개선** (라인 74-82)

```python
# 변경 전: 고정 파일명 매핑
self.index_mapping = {
    '고시.xlsx': 'gosi-2025',
    ...
}

# 변경 후: 패턴 기반 매핑 (날짜 자동 처리)
self.index_mapping_patterns = {
    '고시': 'gosi',
    '사례': 'sarae',
    '행정해석': 'hangjeong',
    'hiraNotice': 'hira-notice',
}
```

- **효과**: `고시_20251201.xlsx`, `고시.xlsx` 모두 자동 인식

### 3. **파일명 자동 파싱 함수 추가** (라인 101-133)

```python
def get_index_name_from_filename(self, filename: str) -> str:
    """
    파일명에서 인덱스명 추출 (날짜 포함/미포함 모두 지원)
    예: 고시_20251201.xlsx → gosi
    """
    base_name = filename.replace('.xlsx', '')
    base_name_without_date = re.sub(r'_\d{8}$', '', base_name)
    return self.index_mapping_patterns[base_name_without_date]
```

### 4. **데이터 준비 함수 추가** (신규 3개 함수)

### 4-1. `prepare_sarae_data()` (라인 512-549)

```python
def prepare_sarae_data(self, df: pd.DataFrame) -> List[Dict]:
    """사례 데이터 준비 (심의사례공개 + 심사사례지침 통합)"""
    # 필수: publication_date, title, case_content, url
    # 선택: patient_gender, patient_age, review_result, decision_reason
```

### 4-2. `prepare_hangjeong_data()` (라인 551-620)

```python
def prepare_hangjeong_data(self, df: pd.DataFrame) -> List[Dict]:
    """행정해석 데이터 준비"""
    # 필수: publication_date, title, content, url
    # 선택: attachment, download
```

### 4-3. `prepare_hira_notice_data()` (라인 622-660)

```python
def prepare_hira_notice_data(self, df: pd.DataFrame) -> List[Dict]:
    """심평원 공지사항 데이터 준비"""
    # 필수: publication_date, title, content
    # 선택: chunk, url, download
```

### 5. **고시 데이터 필드 추가** (라인 253-266)

```python
# 추가된 필드
'download': str(row['download']),
'attachment': str(row['attachment']),
```

### 6. **심사지침 데이터 구조 개선** (라인 332-377)

```python
# 변경 전: announcement_info, content만 저장
# 변경 후: publication_date, title, notification_number, content, url, download
```

### 7. **업로드 로직 개선** (라인 805-869)

```python
# 변경 전: 폴더 내 모든 Excel 파일 처리
# 변경 후: 오늘 날짜 기준 5개 파일만 타겟팅
today = datetime.now().strftime('%Y%m%d')
target_files = [
    f'고시_{today}.xlsx',
    f'사례_{today}.xlsx',
    f'행정해석_{today}.xlsx',
    f'심사지침_{today}.xlsx',
    f'hiraNotice_{today}.xlsx',
]
```

### 📌 **핵심 수정 사항**

### **1. ai-data-cli (1개 파일)**

- **파일**: `excel_cli_unified.py`
- **목적**: 사용자 입력 검증 강화
- **내용**: 잘못된 컬럼 번호 입력 시 에러 메시지 표시 후 재입력 요청 (크래시 방지)

### **2. ai-db-opensearch-uploader (1개 파일)**

- **파일**: `upload_to_opensearch_en.py`
- **목적**: 신규 데이터 타입 업로드 지원
- **주요 변경**:
    1. **날짜 포함 파일명 자동 인식** (`고시_20251201.xlsx` → `gosi` 인덱스)
    2. **신규 데이터 타입 3개 추가**
        - 사례 (심의사례공개 + 심사사례지침 통합)
        - 행정해석
        - 심평원 공지사항 (hiraNotice)
    3. **고시/심사지침 필드 확장** (attachment, download)
    4. **일일 업데이트 최적화** (오늘 날짜 파일 5개만 처리)
    5. **HTTP/HTTPS 자동 감지** (로컬 테스트 환경 지원) → 불필요


## 데이터 파이프라인 자동화 정리

# ai-data-cli, opensearch-uploader 수정사항 정리

### 1️⃣ **ai-data-cli 프로젝트**

- `src/ai_data_cli/excel_cli_unified.py`

---

### 📄 **excel_cli_unified.py** (라인 547-564)

**수정 내용**: 수동 전략 모드에서 컬럼 선택 시 입력 검증 강화

**변경 전**:

```python
selected_indices = Prompt.ask(
    "\n포함할 컬럼을 선택하세요 (쉼표로 구분, 예: 1,3,4)",
    validator=lambda x: all(...)  # validator만 사용
)
selected_cols = [columns[int(i.strip()) - 1] for i in selected_indices.split(",")]

```

**변경 후**:

```python
while True:  # 재입력 루프 추가
    selected_indices = Prompt.ask(...)
    try:
        indices = [i.strip() for i in selected_indices.split(",")]
        if all(idx.isdigit() and 1 <= int(idx) <= len(columns) for idx in indices):
            selected_cols = [columns[int(i) - 1] for i in indices]
            break
        else:
            console.print(f"[red]❌ 잘못된 컬럼 번호...[/red]")
    except (ValueError, IndexError):
        console.print("[red]❌ 올바른 형식이 아닙니다...[/red]")
```

**개선 효과**:

- ❌ 이전: 잘못된 입력 시 프로그램 크래시
- ✅ 이후: 에러 메시지 표시 후 재입력 요청

### 2️⃣ **ai-db-opensearch-uploader 프로젝트**

- `scripts/upload_to_opensearch_en.py`

### 📄 **upload_to_opensearch_en.py**

**주요 수정 사항**:

### 1. **SSL 동적 설정** (라인 61-72) → 로컬환경 맞춤, 프로젝트에서는 불필요

```python
# 변경 전
use_ssl=True  # 항상 SSL 사용

# 변경 후
use_ssl = opensearch_url.startswith('https://')  # URL에 따라 자동 결정
```

- HTTP 연결 지원 (로컬 테스트 환경)

### 2. **인덱스 매핑 방식 개선** (라인 74-82)

```python
# 변경 전: 고정 파일명 매핑
self.index_mapping = {
    '고시.xlsx': 'gosi-2025',
    ...
}

# 변경 후: 패턴 기반 매핑 (날짜 자동 처리)
self.index_mapping_patterns = {
    '고시': 'gosi',
    '사례': 'sarae',
    '행정해석': 'hangjeong',
    'hiraNotice': 'hira-notice',
}
```

- **효과**: `고시_20251201.xlsx`, `고시.xlsx` 모두 자동 인식

### 3. **파일명 자동 파싱 함수 추가** (라인 101-133)

```python
def get_index_name_from_filename(self, filename: str) -> str:
    """
    파일명에서 인덱스명 추출 (날짜 포함/미포함 모두 지원)
    예: 고시_20251201.xlsx → gosi
    """
    base_name = filename.replace('.xlsx', '')
    base_name_without_date = re.sub(r'_\d{8}$', '', base_name)
    return self.index_mapping_patterns[base_name_without_date]
```

### 4. **데이터 준비 함수 추가** (신규 3개 함수)

### 4-1. `prepare_sarae_data()` (라인 512-549)

```python
def prepare_sarae_data(self, df: pd.DataFrame) -> List[Dict]:
    """사례 데이터 준비 (심의사례공개 + 심사사례지침 통합)"""
    # 필수: publication_date, title, case_content, url
    # 선택: patient_gender, patient_age, review_result, decision_reason
```

### 4-2. `prepare_hangjeong_data()` (라인 551-620)

```python
def prepare_hangjeong_data(self, df: pd.DataFrame) -> List[Dict]:
    """행정해석 데이터 준비"""
    # 필수: publication_date, title, content, url
    # 선택: attachment, download
```

### 4-3. `prepare_hira_notice_data()` (라인 622-660)

```python
def prepare_hira_notice_data(self, df: pd.DataFrame) -> List[Dict]:
    """심평원 공지사항 데이터 준비"""
    # 필수: publication_date, title, content
    # 선택: chunk, url, download
```

### 5. **고시 데이터 필드 추가** (라인 253-266)

```python
# 추가된 필드
'download': str(row['download']),
'attachment': str(row['attachment']),
```

### 6. **심사지침 데이터 구조 개선** (라인 332-377)

```python
# 변경 전: announcement_info, content만 저장
# 변경 후: publication_date, title, notification_number, content, url, download
```

### 7. **업로드 로직 개선** (라인 805-869)

```python
# 변경 전: 폴더 내 모든 Excel 파일 처리
# 변경 후: 오늘 날짜 기준 5개 파일만 타겟팅
today = datetime.now().strftime('%Y%m%d')
target_files = [
    f'고시_{today}.xlsx',
    f'사례_{today}.xlsx',
    f'행정해석_{today}.xlsx',
    f'심사지침_{today}.xlsx',
    f'hiraNotice_{today}.xlsx',
]
```

### 📌 **핵심 수정 사항**

### **1. ai-data-cli (1개 파일)**

- **파일**: `excel_cli_unified.py`
- **목적**: 사용자 입력 검증 강화
- **내용**: 잘못된 컬럼 번호 입력 시 에러 메시지 표시 후 재입력 요청 (크래시 방지)

### **2. ai-db-opensearch-uploader (1개 파일)**

- **파일**: `upload_to_opensearch_en.py`
- **목적**: 신규 데이터 타입 업로드 지원
- **주요 변경**:
    1. **날짜 포함 파일명 자동 인식** (`고시_20251201.xlsx` → `gosi` 인덱스)
    2. **신규 데이터 타입 3개 추가**
        - 사례 (심의사례공개 + 심사사례지침 통합)
        - 행정해석
        - 심평원 공지사항 (hiraNotice)
    3. **고시/심사지침 필드 확장** (attachment, download)
    4. **일일 업데이트 최적화** (오늘 날짜 파일 5개만 처리)
    5. **HTTP/HTTPS 자동 감지** (로컬 테스트 환경 지원) → 불필요

<aside>
💡

대상 파일

- 심평원 보험인정기준(고시, 행정해석, 심사지침, 심의사례공개, 심사사례지침)
- 심평원 공지사항
</aside>

## 1. 출력 파일 구조 정리

- outputs 디렉토리

```
outputs/
├── 고시_YYYYMMDD.xlsx
├── 사례_YYYYMMDD.xlsx
├── 행정해석_YYYYMMDD.xlsx
├── 심사지침_YYYYMMDD.xlsx
└── hiraNotice_YYYYMMDD.xlsx
```

- 하루 배치 기준:
    - 카테고리별 결과: `고시_20251201.xlsx` 등 5개 파일

## 2. HWP/HWPX 처리

- Docker/Linux 환경에서 **HWP → PDF 직접 변환 로직 제거**
    - LibreOffice / win32com / Wine 등 의존성 최소화
- `upstage_parser_ver2.py`:
    - `.pdf`, `.hwp`, `.hwpx` **모두 Upstage Document API에 그대로 전송**
    - Upstage 내부에서 포맷 처리 (HWP/HWPX 포함)
- 변환 실패 시:
    - 해당 첨부 파싱만 건너뛰고, 로그에 남긴 뒤 **파이프라인은 계속 진행**

## 3. jobs.py – 일일 배치 오케스트레이터

### 3.1 주요 역할

`jobs.py`에서 네 가지 잡 타입 제공:

```bash
python jobs.py --job hira_daily --days-back 1
python jobs.py --job hira_notice_daily --days-back 1
python jobs.py --job upload_vector_db
python jobs.py --job full_daily --days-back 1
```

- `hira_daily` : 심평원 보험인정기준 일일 update
- `hira_notice_daily` : 심평원 공지사항 일일 update
- `upload_vector_db` : 오늘날짜 기준 excel 파일 자동으로 qdrant/opensearch 업로드 (고시,행정해석,사례,심사지침,hiraNotice)
- `full_daily` :  `hira_daily` + `hira_notice_daily` + `upload_vector_db`

### 3.2 HIRA_COLUMN_MAPPINGS (컬럼 매핑 중앙 관리)

- vector_db 업로드 용 : 어떤 컬럼을 쓸지 정의

```python
HIRA_COLUMN_MAPPINGS = {
    "고시": {
        "title_column": "notification_title",
        "content_column": "attachment",
        "metadata_columns": [
            "publication_date",
            "notification_number",
            "url",
            "download",
            "effective_date",
            "revision_type",
        ],
        "collection": "hira_notice",
        "index": "hira_notice",
    },
    "사례": {
        "title_column": "question",
        "content_column": "answer",
        "metadata_columns": ["publication_date", "category", "subcategory", "url"],
        "collection": "hira_case",
        "index": "hira_case",
    },
    "행정해석": {
        "title_column": "title",
        "content_column": "content",
        "metadata_columns": ["publication_date", "category", "url"],
        "collection": "hira_admin",
        "index": "hira_admin",
    },
    "심사지침": {
        "title_column": "title",
        "content_column": "content",
        "metadata_columns": ["publication_date", "category", "url"],
        "collection": "hira_guideline",
        "index": "hira_guideline",
    },
    "hiraNotice": {
        "title_column": "title",
        "content_column": "content",
        "metadata_columns": ["publication_date", "category", "url"],
        "collection": "hira_announcement",
        "index": "hira_announcement",
    },
}
```

### 3.3 Vector DB 업로드 로직 (Qdrant + ai-data-cli)

### 1) 업로드 대상 파일 자동 검색

```python
output_dir = Path("outputs")
today_str = datetime.now().strftime("%Y%m%d")
categories = ["고시", "사례", "행정해석", "심사지침", "hiraNotice"]

files_to_upload = []
for category in categories:
    file_path = output_dir / f"{category}_{today_str}.xlsx"
    if file_path.exists():
        files_to_upload.append((category, str(file_path)))
```

- **오늘 날짜(YYYYMMDD)** 기준 파일만 업로드 대상
- 없는 파일은 건너뛰고 로그만 남김

### 2)  jobs.py에서 vectorDB 업로드 로직 자동실행

```python
cmd = [
    "python", "-m", "ai_data_cli.excel_cli_unified",
    "upload",
    file_path,
    "--user-id", f"hira_{category}",
    "--category", category,
    "--content-col", mapping["content_column"],
    "--collection", mapping["collection"],
    "--batch",         # 비대화식 모드
    "--no-monitoring",
    "--embedding-mode", embedding_mode,
]
if embedding_mode == "ai":
    cmd.extend(["--ai-model", ai_model])
```

## 4. OpenSearch 업로더 (ai-db-opensearch-uploader)

- 파일명 패턴 → 인덱스명 매핑을 **패턴 기반**으로 변경:

```python
self.index_mapping_patterns = {
    "고시": "gosi-2025",
    "사례": "sarae-2025",
    "심사지침": "simsa-jichim-2025",
    "행정해석": "hangjeong-2025",
    "hiraNotice": "hira-notice-2025",
}
```

- 파일명에서 날짜를 제거한 후 인덱스명 결정:

```python
# 예: 고시_20251201.xlsx → "고시" → gosi-2025
base_name = filename.replace(".xlsx", "")
base_name_without_date = re.sub(r"_\d{8}$", "", base_name)
```

- 오늘 날짜의 5개 파일만 대상으로 업로드
    
    (`고시_YYYYMMDD.xlsx`, `사례_YYYYMMDD.xlsx`, …, `hiraNotice_YYYYMMDD.xlsx`)
    

```jsx
#opensearch
cginside19@ai-intern-dev:~$ curl "http://localhost:19200/_cat/indices?v"
health status index                     uuid                   pri rep docs.count docs.deleted store.size pri.store.size
green  open   .opensearch-observability mFxsTTAfQTG_1JwvC3w4aQ   1   0          0            0       208b           208b
green  open   .plugins-ml-config        JgFYOK18QXyK2J5ZuG0xFg   1   0          1            0      3.9kb          3.9kb
yellow open   gosi-2025                 IIPlq9z5TPmqyDz3e39WQQ   1   1         54            0      3.6mb          3.6mb
yellow open   hangjeong-2025            Ugxopaf9SzKZTbEUdpTcRw   1   1         49            0      2.3mb          2.3mb
yellow open   hira-notice-2025          xEUWwLt_ToK2MBJxNmTtbQ   1   1         61            0    362.3kb        362.3kb
yellow open   simsa-jichim-2025         3Nlx7gpgT86N5q-yo1kzTQ   1   1         29            0    829.8kb        829.8kb
yellow open   sarae-2025                -F5AtVbHQGW4rh1C1imGHQ   1   1        100            0    202.5kb        202.5kb

#qdrant
cginside19@ai-intern-dev:~$ curl http://localhost:6333/collections
{"result":{"collections":[{"name":"hira_notice"},{"name":"unified_collection"},{"name":"hira_announcement"}]},"status":"ok","t
```