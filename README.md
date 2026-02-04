# RegScan

**Scanning Global Regulation into Local Impact**

글로벌 의약품 규제 인텔리전스 시스템 - FDA/EMA 승인 약물의 국내 시장 영향 분석 및 메드클레임 시사점 제공

## 핵심 기능

- **글로벌 규제 통합**: FDA, EMA, MFDS, CRIS 데이터 수집 및 통합
- **국내 영향 분석**: 글로벌 승인 약물의 국내 허가/급여 현황 추적
- **HIRA 매칭**: MFDS ↔ HIRA 성분 브릿징 (75.7% 커버리지)
- **메드클레임 인사이트**: 급여 현황, 본인부담금, 산정특례 분석

## 프로젝트 구조

```
RegScan/
├── regscan/                 # 메인 패키지
│   ├── api/                 # FastAPI 엔드포인트
│   ├── parse/               # 데이터 파서 (FDA, EMA, MFDS, CRIS)
│   ├── map/                 # 매핑 로직 (global_status, ingredient_bridge)
│   ├── scan/                # 분석 엔진 (domestic impact)
│   ├── report/              # 리포트 생성
│   └── db/                  # 데이터베이스
├── data/                    # 데이터 파일
│   ├── fda/                 # FDA 승인 데이터
│   ├── ema/                 # EMA 승인 데이터
│   ├── mfds/                # MFDS 허가 데이터
│   ├── cris/                # CRIS 임상시험 데이터
│   ├── hira/                # HIRA 급여 데이터
│   └── archive/             # 임시/실험 파일
├── scripts/                 # 실행 스크립트
│   └── archive/             # 실험 스크립트
├── docs/                    # 문서
│   ├── worklog/             # 작업일지
│   ├── research/            # 리서치 리포트
│   ├── design/              # 설계 문서
│   └── analysis/            # 초기 분석 자료
└── tests/                   # 테스트
```

## API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/v1/stats` | 전체 통계 |
| `GET /api/v1/hot-issues` | 핫이슈 목록 (score >= 60) |
| `GET /api/v1/imminent` | 국내 도입 임박 약물 |
| `GET /api/v1/drugs` | 약물 목록 |
| `GET /api/v1/drugs/{inn}` | 약물 상세 |
| `GET /api/v1/drugs/{inn}/medclaim` | 메드클레임 시사점 |
| `GET /api/v1/drugs/search` | 약물 검색 |

## 실행

```bash
# API 서버
uvicorn regscan.api.main:app --reload

# API 테스트
python scripts/test_api.py
```

## 데이터 현황

| 소스 | 건수 | 설명 |
|------|------|------|
| FDA | 1,462 | 승인 약물 |
| EMA | 2,655 | 승인 약물 |
| MFDS | 44,035 | 허가 품목 |
| CRIS | 11,551 | 임상시험 |
| HIRA | 15,107 | 급여 성분 |

## 분석 결과

- **Hot Issues**: 17건 (글로벌 승인 + 국내 미허가 + 높은 관심)
- **Imminent**: 16건 (글로벌 승인 + 국내 미허가 + 임상 진행)
- **Reimbursed**: 1,642건 (HIRA 급여 적용)
