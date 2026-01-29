# RegScan Worklog

> 작업 계획, 진행 상황, 의사결정 기록

---

## 폴더 구조

```
worklog/
├── README.md           # 이 파일
├── plans/              # 작업 계획
│   └── 2026-01-week5.md
├── daily/              # 일일 작업 내역
│   └── 2026-01-29.md
└── decisions/          # 주요 의사결정 기록
    └── 001-feed-card-schema.md
```

---

## 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 프로젝트 | RegScan (MedClaim 서브 프로젝트) |
| 목적 | 메인화면 콘텐츠/피드/개인화용 정보 생성 엔진 |
| 데드라인 | 2026-02-09 (메인화면 변경) |
| 파이프라인 구축 | 2026-01-29 ~ 02-07 (이번주 + 다음주) |

---

## 핵심 원칙

> **RegScan은 답을 하지 않는다.**
> **RegScan은 메인화면에 흘릴 정보를 만든다.**

### RegScan이 하는 것
- 규제 변화 감지 → 카드/피드 콘텐츠 생성
- Citation 메타데이터 제공
- 개인화 추천 재료 공급

### RegScan이 하지 않는 것
- Chat 응답
- Hallucination 통제
- Split View UX
- 답변 정책

---

## 빠른 링크

### 공식 문서 (docs/)
- [프로젝트 개요](../docs/overview.md)
- [데이터 소스](../docs/data-sources.md)
- [파이프라인 구조](../docs/pipeline.md)
- [Feed Card 스키마](../docs/schema.md)

### 리서치/회의 (analysis/)
- [회의록](../analysis/meetings/)
- [벤치마크 리서치](../analysis/research/)
