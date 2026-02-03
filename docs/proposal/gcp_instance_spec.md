# RegScan GCP 인스턴스 요청서

## 1. Compute Engine (VM)

| 항목 | 값 |
|------|-----|
| **인스턴스명** | `regscan-prod` |
| **리전** | `asia-northeast3` (서울) |
| **존** | `asia-northeast3-a` |
| **머신 타입** | `e2-medium` (2 vCPU, 4GB RAM) |
| **OS 이미지** | Ubuntu 22.04 LTS |
| **부팅 디스크** | 30GB SSD (pd-balanced) |
| **네트워크 태그** | `http-server`, `https-server` |

### 예상 비용
- e2-medium: ~$24.27/월 (서울 리전)
- 디스크 30GB: ~$3.06/월
- **소계: ~$27/월**

---

## 2. Cloud SQL (선택사항)

> 초기에는 SQLite로 시작 가능. 데이터 증가 시 마이그레이션.

| 항목 | 값 |
|------|-----|
| **인스턴스명** | `regscan-db` |
| **DB 엔진** | PostgreSQL 15 |
| **머신 타입** | `db-f1-micro` (공유 vCPU, 0.6GB) |
| **스토리지** | 10GB SSD |
| **리전** | `asia-northeast3` (서울) |

### 예상 비용
- db-f1-micro: ~$7.67/월
- 스토리지 10GB: ~$1.70/월
- **소계: ~$10/월**

---

## 3. 방화벽 규칙

| 규칙명 | 포트 | 소스 | 용도 |
|--------|------|------|------|
| `allow-http` | 80 | 0.0.0.0/0 | HTTP |
| `allow-https` | 443 | 0.0.0.0/0 | HTTPS |
| `allow-api` | 8000 | 회사 IP만 | FastAPI |
| `allow-ssh` | 22 | 회사 IP만 | SSH |

---

## 4. 필요 권한/서비스

- [x] Compute Engine API
- [x] Cloud SQL Admin API (DB 사용 시)
- [x] Cloud Scheduler API (배치 스케줄링)
- [ ] Secret Manager (API 키 관리, 선택)

---

## 5. 총 예상 비용

| 구성 | 월 비용 |
|------|--------:|
| Compute Engine (e2-medium) | $27 |
| Cloud SQL (선택) | $10 |
| 네트워크 이그레스 | $5 |
| **합계** | **$37~$42** |

※ DB 없이 SQLite 사용 시: **~$32/월**

---

## 6. 설치 예정 소프트웨어

```bash
# 시스템
Python 3.11+
uv (패키지 관리)
Git

# 애플리케이션
RegScan (FastAPI + 배치)
Nginx (리버스 프록시)
Supervisor (프로세스 관리)
```

---

## 7. 담당자

| 역할 | 담당 |
|------|------|
| 요청자 | (이름) |
| 승인자 | (팀장님) |
| 요청일 | 2026-02-04 |
| 희망 구축일 | 2026-02-07 |
