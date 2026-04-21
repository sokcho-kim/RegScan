# RegScan Backlog

> 마지막 갱신: 2026-04-20

## 범례

| 상태 | 의미 |
|------|------|
| `TODO` | 미착수 |
| `BLOCKED` | 선행 작업 대기 |
| `IN_PROGRESS` | 진행 중 |
| `DONE` | 완료 |

---

## 1. 데이터 수집 확장

### 1.1 수집기 신규 구현

| # | 항목 | 우선순위 | 상태 | 비고 |
|---|------|---------|------|------|
| 1 | FDA Orange Book | P1 | DONE | `2e98c40` |
| 2 | FDA Purple Book | P1 | DONE | `e166c56` |
| 3 | MFDS 안전성 서한 (httpx+bs4) | P1 | DONE | `f5fc401`, TLS 1.2 fix |
| 4 | MFDS 회수/판매중지 API | P1 | DONE | 활용신청 완료, API 키 갱신 필요 |
| 5 | NICE HTA | P1 | DONE | `629b2f5` |
| 6 | PMDA (일본) | P2 | DONE | `c811f91`, RSS+HTML, TLS 1.2 |
| 7a | 건보심 (MOHW 보도자료) | P2 | DONE | httpx+bs4, 키워드 필터 |
| 7b | 국회 의안정보 | P2 | DONE | 열린국회정보 API, 104건 테스트 통과 |
| 8 | DART/EDGAR 공시 | P3 | TODO | 라이선스 딜 선행지표 |
| 9 | 학술/임상 가이드라인 | P3 | TODO | 적응증 확장 근거 |
| 10 | 글로벌 약가 비교 | P3 | TODO | IRP 벤치마크 |
| 11 | FDA Guidance 수집 | P3 | TODO | `fda.py:355` TODO |

### 1.2 파이프라인 통합

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 12 | Purple Book → DailyScanner 통합 | TODO | |
| 13 | NICE TA → DailyScanner 통합 | TODO | |
| 14 | MFDS 안전성 서한 → DailyScanner 통합 | TODO | |

### 1.3 크롤러 운영 (신규)

| # | 항목 | 상태 | 비고 | Issue |
|---|------|------|------|-------|
| 15 | **크롤러 장애 모니터링 시스템** | TODO | DB 테이블(`ingest_runs`) + 대시보드 + Slack 알림 | #2 |

**상세 설계:**
- `ingest_runs` 테이블: source_type, status(SUCCESS/PARTIAL/FAILED), record_count, error_message, traceback, started_at, finished_at
- DailyScanner에서 각 ingestor 실행 결과 자동 기록
- `/dashboard/health` 관리자 페이지에서 전체 수집기 상태 조회
- Slack webhook으로 실패 시 즉시 알림 (연속 실패 시에만, 노이즈 방지)

---

## 2. V2 브리핑 파이프라인

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 16 | Step 1~4 구현 | DONE | fact_card → trend → briefing → validator |
| 17 | 프로덕션 배치 실행 (oncology 1개 영역) | TODO | 실제 LLM 호출 + 결과 검증 |
| 18 | 레거시 코드 제거 | BLOCKED | #17 완료 후 |
| 19 | Cloud Run 배포 | BLOCKED | #17, #18 완료 후 |

---

## 3. 코드 체계 표준화 (Issue #1)

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 20 | DrugCodeResolver 4단계 fallback | DONE | ATC→EDI→품목기준→INN |
| 21 | 품목기준코드 yakga_master 연동 | TODO | 3단계 fallback 보강 |
| 22 | RxCUI → ATC 변환 | TODO | RxNorm API, 저장은 완료 |

---

## 4. 인프라/배포

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 23 | Cloud Run Service 배포 | BLOCKED | V2 파이프라인 검증 후 |
| 24 | 레거시 worker 코드 정리 | BLOCKED | #18과 동일 |
| 25 | data.go.kr API 키 갱신 | TODO | 현재 401 반환 |

---

## 5. 대시보드/품질

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 26 | FDA indication 추출 | TODO | `report.py:197` TODO |
| 27 | 모델 비교 리포트 갱신 | TODO | Gemini 2.0 Flash, GPT-5 벤치마크 |

---

## 우선순위 로드맵

```
NOW (P1)
  ├─ #12~14  신규 수집기 DailyScanner 통합
  ├─ #17     프로덕션 배치 실행
  └─ #25     API 키 갱신

NEXT (P2)
  ├─ #6,7    PMDA + 건보심 수집기
  ├─ #15     크롤러 장애 모니터링
  ├─ #18,19  레거시 제거 + 배포
  └─ #21     품목기준코드 연동

LATER (P3)
  ├─ #8~11   추가 데이터 소스
  ├─ #22     RxCUI→ATC
  ├─ #26     FDA indication
  └─ #27     모델 비교
```
