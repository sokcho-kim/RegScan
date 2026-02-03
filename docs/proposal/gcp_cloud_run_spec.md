# RegScan GCP Cloud Run 리소스 요청서

## 1. Cloud Run Jobs (배치 수집)

| 항목 | 값 |
|------|-----|
| **서비스명** | `regscan-collector` |
| **리전** | `asia-northeast3` (서울) |
| **CPU** | 1 vCPU |
| **메모리** | 2GB |
| **타임아웃** | 30분 |
| **실행 주기** | 매일 02:00 KST |
| **컨테이너 이미지** | `asia-northeast3-docker.pkg.dev/{PROJECT}/regscan/collector:latest` |

### 환경 변수
```
FDA_API_KEY=***
DATA_GO_KR_API_KEY=***
GCS_BUCKET=regscan-data
```

### 예상 비용
- 1회 실행: ~$0.10
- 월 30회: **~$3/월**

---

## 2. Cloud Run Service (API 서빙)

| 항목 | 값 |
|------|-----|
| **서비스명** | `regscan-api` |
| **리전** | `asia-northeast3` (서울) |
| **CPU** | 1 vCPU |
| **메모리** | 1GB |
| **최소 인스턴스** | 0 (Scale to Zero) |
| **최대 인스턴스** | 3 |
| **동시 요청** | 80/인스턴스 |
| **컨테이너 이미지** | `asia-northeast3-docker.pkg.dev/{PROJECT}/regscan/api:latest` |

### 환경 변수
```
GCS_BUCKET=regscan-data
LOG_LEVEL=INFO
```

### 예상 비용
- 트래픽 적음: **~$5/월**
- 사용 안 할 때: **$0**

---

## 3. Cloud Storage

| 항목 | 값 |
|------|-----|
| **버킷명** | `regscan-data` |
| **리전** | `asia-northeast3` (서울) |
| **스토리지 클래스** | Standard |
| **예상 용량** | ~500MB |

### 디렉토리 구조
```
regscan-data/
├── fda/
│   └── approvals_YYYYMMDD.json
├── ema/
│   └── medicines_YYYYMMDD.json
├── mfds/
│   └── permits_YYYYMMDD.json
├── cris/
│   └── trials_YYYYMMDD.json
└── output/
    └── global_status_YYYYMMDD.json
```

### 예상 비용
- 스토리지: **~$0.50/월**
- 네트워크: **~$0.50/월**

---

## 4. Cloud Scheduler

| 항목 | 값 |
|------|-----|
| **작업명** | `regscan-daily-collect` |
| **스케줄** | `0 2 * * *` (매일 02:00 KST) |
| **타임존** | `Asia/Seoul` |
| **대상** | Cloud Run Jobs `regscan-collector` |

### 예상 비용
- **무료** (월 3개까지)

---

## 5. Artifact Registry

| 항목 | 값 |
|------|-----|
| **저장소명** | `regscan` |
| **형식** | Docker |
| **리전** | `asia-northeast3` |

### 예상 비용
- **~$1/월** (이미지 저장)

---

## 6. 필요 IAM 권한

```yaml
# Cloud Run Jobs 서비스 계정
roles:
  - roles/storage.objectAdmin      # GCS 읽기/쓰기
  - roles/logging.logWriter        # 로그 기록

# Cloud Run Service 서비스 계정
roles:
  - roles/storage.objectViewer     # GCS 읽기 전용
  - roles/logging.logWriter        # 로그 기록
```

---

## 7. 필요 API 활성화

- [x] Cloud Run Admin API
- [x] Cloud Scheduler API
- [x] Cloud Storage API
- [x] Artifact Registry API
- [x] Cloud Build API (CI/CD용)

---

## 8. 총 예상 비용

| 항목 | 월 비용 |
|------|--------:|
| Cloud Run Jobs | $3 |
| Cloud Run Service | $5 |
| Cloud Storage | $1 |
| Artifact Registry | $1 |
| Cloud Scheduler | 무료 |
| **합계** | **$10/월** |

※ 트래픽/사용량에 따라 변동 가능
※ 사용 안 할 때는 **$1~2/월** (스토리지만)

---

## 9. 담당자

| 역할 | 담당 |
|------|------|
| 요청자 | (이름) |
| 승인자 | (팀장님) |
| 요청일 | 2026-02-04 |
| 희망 구축일 | 2026-02-10 |

---

## 10. 배포 명령어 (참고)

```bash
# Collector 배포
gcloud run jobs deploy regscan-collector \
  --image asia-northeast3-docker.pkg.dev/{PROJECT}/regscan/collector:latest \
  --region asia-northeast3 \
  --memory 2Gi \
  --cpu 1 \
  --task-timeout 30m

# API 배포
gcloud run deploy regscan-api \
  --image asia-northeast3-docker.pkg.dev/{PROJECT}/regscan/api:latest \
  --region asia-northeast3 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --allow-unauthenticated

# 스케줄러 설정
gcloud scheduler jobs create http regscan-daily-collect \
  --schedule "0 2 * * *" \
  --time-zone "Asia/Seoul" \
  --uri "https://asia-northeast3-run.googleapis.com/..." \
  --http-method POST
```
