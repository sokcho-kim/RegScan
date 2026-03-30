# V3 브리핑 테스트 전체 리포트 — 2026-03-30

## 테스트 환경
- 모델: gpt-5.2 (OpenAI)
- temperature: 0.3
- max_completion_tokens: 2500
- 프롬프트 소스: `regscan/stream/briefing.py`
- 테스트 소스: `tests/test_v3_briefing.py`
- 총 13건 (오프라인 6 + E2E 7)
- **결과: 13/13 PASSED**

---

## Part A. 프롬프트 원문

### A-1. SYSTEM PROMPT (공통, 모든 LLM 호출에 주입)

> 소스: `regscan/stream/briefing.py:26-62` — `SYSTEM_PROMPT`

```
당신은 제약·바이오 산업의 규제 인텔리전스 전문 분석가이며,
국내 종합병원 약제팀·경영진을 위한 Executive Briefing을 작성합니다.

오늘 날짜: 2026-03-30

## 원칙
1. **BLUF**: 첫 문장에서 "그래서 뭐?"에 대한 답을 제시하라.
2. **Fact/Insight 분리**: 아래 [FACT DATA]는 검증된 사실이다. LLM이 할 일은 사실을 기반으로 인사이트와 시사점을 도출하는 것이다.
3. **기사체**: 병원장이 출근길 1분 만에 읽는 톤. 짧은 문장(40자 이내), 능동태, 전문용어 최소화.
4. **숫자는 구체적으로**: "많은" 대신 "17건", "최근" 대신 "2026-03-17 기준".
5. **행동 지향**: 각 섹션 끝에 "So What" — 약제팀이 내일 할 일을 명시.
6. **허위 생성 금지**: [FACT DATA]에 없는 승인일, 점수, 임상 결과를 절대 만들지 마라.

## 시간 추론 규칙 (필수)
- 승인일/허가일 < 오늘(2026-03-30) → "승인 완료", "허가됨" (과거형)
- 승인일/허가일 > 오늘(2026-03-30) → "승인 예정", "심사 중" (미래형)
- 승인일이 없으면 → "승인일 미정", "일정 미공개"
- 절대로 [FACT DATA]에 없는 날짜를 추정하거나 생성하지 마라.

## 필수 필드 규칙
- 출력 JSON 스키마에 명시된 모든 필드를 반드시 포함하라.
- 특히 `key_takeaway`는 절대 누락 금지.
- 필드 값을 채울 수 없으면 "데이터 부족"으로 표기하라.

## 톤 예시

### GOOD (이렇게 써라)
"headline": "FDA, KRAS G12C 이중억제제 sotorasib 병용요법 2026-02-14 승인 완료"
"why_it_matters": "국내 비소세포폐암 2차 치료 시장(연 4,200명)에서 기존 docetaxel 대비 PFS 2.8개월 우위. 급여 등재 시 약제비 연 15억 원 증가 예상."

### BAD (이렇게 쓰지 마라)
"headline": "새로운 항암제가 승인될 예정입니다"
"why_it_matters": "새로운 Kinase 억제제로 환자에게 도움이 될 것입니다."

## 출력
- 반드시 순수 JSON만 출력 (코드블록/마크다운 금지).
- 한글로 작성.
```

### A-2. THERAPEUTIC_BRIEFING_PROMPT (치료영역)

> 소스: `regscan/stream/briefing.py:68-99`

```
[FACT DATA]
치료영역: {area_ko} ({area})
오늘 날짜: {date}
총 수집 약물: {drug_count}건

## 주요 약물 상세 (상위 {top_n}건)
{drug_details}

## 수집 에러
{errors}

[TASK]
위 데이터를 기반으로 {area_ko} 치료영역 주간 Executive Briefing을 작성하라.
시간 추론 규칙을 반드시 준수하라 (승인일 vs 오늘 날짜 비교).

출력 JSON:
{
  "headline": "40자 이내 BLUF 헤드라인 — 이번 주 가장 중요한 한 가지",
  "key_takeaway": "경영진이 알아야 할 핵심 1문장 (필수 — 절대 누락 금지)",
  "top_drugs": [
    {
      "inn": "약물명",
      "status": "FDA/EMA 승인 현황 1줄 (과거/미래 시제 정확히)",
      "why_it_matters": "4관점으로 분석: ..."
    }
  ],
  "trend_analysis": "...",
  "action_items": ["..."]
}
```

### A-3. INNOVATION_BRIEFING_PROMPT (혁신)

> 소스: `regscan/stream/briefing.py:105-138`

```
[FACT DATA]
오늘 날짜: {date}
총 약물: {drug_count}건
NME(신규물질) 수: {nme_count}건
PRIME 지정: {prime_count}건
희귀의약품 지정: {orphan_count}건
조건부 승인: {conditional_count}건

## NME 및 혁신 지정 약물 (상위 {top_n}건)
{drug_details}

## 시그널 상세 (상위 20건)
{signals}

[TASK]
위 데이터를 기반으로 혁신 시그널 Executive Briefing을 작성하라.
...
```

### A-4. UNIFIED_BRIEFING_PROMPT (통합)

> 소스: `regscan/stream/briefing.py:194-236`

```
[FACT DATA]
오늘 날짜: {date}

## 치료영역 스트림 브리핑 (drug_count: {therapeutic_drug_count}, signal_count: {therapeutic_signal_count})
{therapeutic_summary}

## 혁신지표 스트림 브리핑 (drug_count: {innovation_drug_count}, signal_count: {innovation_signal_count})
{innovation_summary}

## 외부시그널 스트림 브리핑 (drug_count: {external_drug_count}, signal_count: {external_signal_count})
{external_summary}

## 스트림별 Top 약물 (교차 등장)
{cross_stream_drugs}

[TASK]
3개 스트림을 종합한 오늘의 RegScan Executive Daily Briefing을 작성하라.
**중요**: 위 스트림 브리핑을 단순 반복·요약하지 마라. 스트림 간 교차·종합 인사이트를 도출하라.
...
```

---

## Part B. 테스트 입력 데이터 (Fixture)

### B-1. 과거 약물: RILZABRUTINIB

> 소스: `tests/test_v3_briefing.py:47-81` — `rilzabrutinib_drug()`

```json
{
  "inn": "RILZABRUTINIB",
  "fda_data": {
    "submission_status": "AP",
    "submission_status_date": "2025-03-28",
    "submission_class_code_description": "Type 1 - New Molecular Entity",
    "brand_name": "TYVAZO",
    "pharm_class_epc": ["Bruton's Tyrosine Kinase Inhibitor [EPC]"]
  },
  "ema_data": {
    "marketing_authorisation_date": "2025-06-15",
    "medicine_status": "authorised",
    "is_orphan": true,
    "therapeutic_indication": "Treatment of immune thrombocytopenia (ITP) in adult patients who have had an insufficient response to a previous treatment."
  },
  "atc_code": "L01EL04",
  "designations": ["NME", "orphan"],
  "clinical_results": { "trial_phase": "Phase III", "trial_status": "Completed" },
  "mfds_data": { "approval_status": "미허가", "approval_date": null },
  "therapeutic_areas": ["hematology", "rare_disease"]
}
```

### B-2. 미래 약물: VELONATINIB

> 소스: `tests/test_v3_briefing.py:155-196` — `future_drug()`

```json
{
  "inn": "VELONATINIB",
  "fda_data": {
    "submission_status": "TA",
    "submission_status_date": "2026-09-15",
    "submission_class_code_description": "Type 1 - New Molecular Entity",
    "brand_name": "",
    "pharm_class_epc": ["VEGFR/FGFR Kinase Inhibitor [EPC]"]
  },
  "ema_data": {
    "medicine_status": "under_review",
    "is_orphan": false,
    "is_prime": true,
    "therapeutic_indication": "Treatment of advanced hepatocellular carcinoma (HCC) in patients who have progressed on prior systemic therapy."
  },
  "atc_code": "L01EX99",
  "designations": ["NME", "breakthrough"],
  "clinical_results": { "trial_phase": "Phase III", "trial_status": "Ongoing" },
  "mfds_data": { "approval_status": "미허가", "approval_date": null },
  "therapeutic_areas": ["oncology"]
}
```

---

## Part C. LLM 결과 전문 (7건)

### C-1. 치료영역 브리핑 — 과거 약물 (RILZABRUTINIB)

**테스트**: `test_therapeutic_briefing_e2e` — **PASSED**

```json
{
  "headline": "ITP BTK억제제 rilzabrutinib 미·EU 승인 완료",
  "key_takeaway": "2025-03-28 FDA, 2025-06-15 EMA에서 ITP 성인 치료로 승인 완료돼, 국내 도입 시 ITP 2차 이상 치료 옵션과 약제비 변동을 동시에 점검해야 한다.",
  "top_drugs": [
    {
      "inn": "RILZABRUTINIB",
      "status": "FDA 2025-03-28 승인 완료(AP), EMA 2025-06-15 승인 완료(authorised, orphan)",
      "why_it_matters": "(a)경쟁구도: ITP는 스테로이드·IVIG·TPO-RA·rituximab·비장절제 등 다중 라인 치료가 흔하다. BTK 억제제는 면역기전 표적 옵션으로 2차 이상에서 대체·병용 논의가 늘 수 있다. (b)급여/가격: NME+orphan 지정으로 국내 도입 시 고가 약제 가능성이 높다. 급여 등재 전에는 비급여·환자부담 증가 리스크가 크다. (d)처방변화: 경구 표적치료로 자리 잡으면 주사제(IVIG/rituximab) 사용 빈도와 외래·주사실 운영에 영향을 줄 수 있다. (c)환자규모: 국내 ITP 성인 2차 이상 대상 규모는 데이터 부족으로 산정 불가."
    }
  ],
  "trend_analysis": "이번 주 수집 1건 중 1건이 orphan 지정(100%). 적응증은 희귀 혈액질환(ITP) 1건. 개발단계는 Phase III 완료 1건. 규제 상태는 FDA 승인 완료 1건, EMA 승인 완료 1건으로, '심사 중' 파이프라인보다 '승인 후 도입·급여' 이슈가 중심이다.",
  "action_items": [
    "ITP 2차 이상 치료 환자군을 병원 EMR로 2025년 기준 추출해(진단코드+치료라인) 잠재 처방 규모를 내부 추정하라.",
    "rilzabrutinib 국내 도입 시나리오를 가정해 비급여 사용 프로세스(약사위원회 보고, 사전승인, 환자설명서)와 대체 가능 약제(IVIG, TPO-RA, rituximab) 재고·예산 영향 체크리스트를 이번 주 내 작성하라."
  ]
}
```

**시제 검증**: "승인 완료" 포함 → PASS

---

### C-2. 혁신 브리핑 — 과거 약물 (RILZABRUTINIB)

**테스트**: `test_innovation_briefing_e2e` — **PASSED**

```json
{
  "headline": "ITP BTK 억제제 rilzabrutinib 미·EU 승인 완료",
  "key_takeaway": "희귀의약품 지정 ITP 신약이 허가됨에 따라, 병원은 조기 도입·재정영향·사용기준을 동시에 준비해야 한다.",
  "nme_spotlight": [
    {
      "inn": "RILZABRUTINIB",
      "designation": "NME, orphan",
      "implication": "(a)혁신성: BTK 억제제(NME)로 ITP에서 면역조절 계열 내 신규 기전 옵션을 제시. (b)도입 시점: FDA 2025-03-28 승인 완료, EMA 2025-06-15 허가됨. 국내 도입·급여 일정은 데이터 부족으로 미정. (c)포지셔닝: 희귀의약품 지정으로 처방 대상이 '이전 치료 반응 불충분 성인 ITP'로 좁아질 가능성. 고가·고위험 관리 약제로 약사 주도 모니터링 수요가 커질 전망."
    }
  ],
  "pdufa_watch": ["해당 없음(제공 데이터 내 PDUFA 일정 없음)"],
  "strategic_implications": "이번 시그널은 '희귀+NME' 조합이다.\n병원 관점에선 도입 압력은 높고, 환자 수는 제한적이다.\n희귀의약품은 공급·계약·재정 변동성이 커진다.\n사용기준이 엄격해져 사전승인·투약관리 프로세스가 핵심이 된다.",
  "action_items": [
    "ITP 현행 치료경로 점검: '이전 치료 반응 불충분' 정의를 병원 기준으로 문서화",
    "약제위원회(DC) 안건 사전 준비: NME/희귀 지정 근거, 예상 사용군, 대체·병용 가능성 정리",
    "재정영향 프레임 선제 구축: 약가·급여 데이터 부족 상태로 '시나리오(고가/초고가)'별 예산 영향 템플릿 마련",
    "희귀약 운영체계 점검: 처방 사전승인, 출고·재고 최소화, 이상반응·출혈/감염 모니터링 체크리스트 초안 작성",
    "국내 허가·급여 트래킹 시작: MFDS 허가, HIRA 급여평가, 위험분담제 적용 여부는 데이터 부족이므로 주간 모니터링 항목으로 등록"
  ]
}
```

**시제 검증**: "승인 완료", "허가됨" 포함 → PASS

---

### C-3. 외부시그널 브리핑 (RILZABRUTINIB + FOSTAMATINIB)

**테스트**: `test_external_briefing_e2e` — **PASSED**

```json
{
  "headline": "ITP: fostamatinib 3상 실패, BTK 장기효과 부상",
  "key_takeaway": "ITP 치료는 단기적으로 기존 처방 유지·재고 리스크 관리가 핵심이고, 중장기적으로 BTK 억제제 장기반응 데이터가 치료 알고리즘 변화를 촉발할 수 있다.",
  "trial_failures": [
    {
      "inn": "FOSTAMATINIB",
      "verdict": "ITP 3상에서 1차 평가변수 미달",
      "hospital_impact": "(a)재고영향 — 신규 선매입·안전재고 상향을 중단하고, 현재 재고는 유효기간·회전율 기준으로 단계적 소진 계획을 수립. (b)대체약물 — ITP 표준 옵션(스테로이드, IVIG, TPO-RA, rituximab, splenectomy 등)로 즉시 전환 경로를 처방세트에 반영. (c)보험청구 — 급여 기준이 즉시 바뀐 근거는 없으나, 근거 약화로 사전승인/심사 강화 가능성에 대비해 적응증·라인·반응평가 기록을 청구 서류에 표준화."
    }
  ],
  "medrxiv_insights": [
    {
      "topic": "ITP에서 BTK 억제제 장기 치료 성과",
      "finding": "RILZABRUTINIB 3년 추적에서 혈소판 반응 72% 지속",
      "timeline": "데이터는 프리프린트 단계로 즉시 임상표준 변경은 제한적. 다만 장기추적 근거가 축적되면 1–3년 내(추가 확증시험·가이드라인 반영 시점) 처방 패턴 변화 가능."
    }
  ],
  "watch_list": ["RILZABRUTINIB", "FOSTAMATINIB"],
  "action_items": [
    "ITP 처방 현황 점검: 최근 3개월 fostamatinib 사용 환자 수·라인·반응률을 내부 데이터로 즉시 집계",
    "재고 관리: fostamatinib 발주 보류, 유효기간 임박 물량 우선 소진 및 반품/전환 가능 조건을 도매상과 재확인",
    "대체 경로 정비: ITP 표준치료(스테로이드/IVIG/TPO-RA/rituximab 등) 처방세트·진료지침을 최신화하고 전환 기준(불응/재발 정의)을 한 장으로 배포",
    "청구 리스크 대비: ITP 약제 청구에 필요한 핵심 문서(진단 근거, 이전 치료 실패, 혈소판 수치 추이)를 EMR 템플릿으로 표준화",
    "미래 준비: BTK 억제제(특히 rilzabrutinib) 관련 후속 임상/규제 업데이트를 주간 모니터링 항목에 추가하고, 도입 시 예상 환자군·예산 영향 산출 틀을 사전 마련"
  ]
}
```

**시제 검증**: PASS

---

### C-4. 통합 브리핑 — 과거 약물만 (3스트림 합산)

**테스트**: `test_unified_briefing_e2e` — **PASSED**

```json
{
  "headline": "ITP 치료축 이동: BTK는 강화, SYK는 흔들",
  "key_takeaway": "rilzabrutinib는 2025년 미·EU 승인 완료로 국내 도입 논의가 빨라질 수 있고, fostamatinib 3상 실패 신호까지 겹쳐 병원은 ITP 불응군 약제 포트폴리오·재정·재고를 동시에 재정렬해야 한다.",
  "executive_summary": "ITP 불응군에서 '경구 표적치료' 비중이 커진다.\nrilzabrutinib는 미·EU 승인 완료로 도입 압력이 올라간다.\nfostamatinib 3상 실패로 기존 처방·재고 전략을 보수적으로 바꿔야 한다.\n희귀·고가(NME+orphan) 조합이라 약제비 변동성이 커진다.\n내부 사용 기준(라인·중단·모니터링)을 먼저 정해야 혼선이 줄어든다.",
  "cross_analysis": "3개 스트림 모두 rilzabrutinib가 교차 등장해 신호 강도가 높다(도입 '가능성'이 아니라 '준비 과제'로 전환).\n치료영역/혁신 스트림은 '승인 완료→옵션 확대'를, 외부시그널은 '경쟁약 실패+장기반응 프리프린트'로 BTK 쏠림을 보완한다.\n다만 BTK 장기효과 72% 지속은 프리프린트 단계라, 병원 내 채택 근거로는 '참고' 수준에 두고 프로세스(기준·재정·공급)를 선행해야 한다.\nSYK 축(fostamatinib) 불확실성이 커져, ITP 불응군에서 약제 선택의 중심이 '근거·공급·청구 리스크'로 이동한다.",
  "top_5_drugs": [
    { "rank": 1, "inn": "RILZABRUTINIB", "reason": "therapeutic+innovation에서 미·EU 승인 완료(NME+orphan)로 도입 압력 상승, external에서 BTK 장기반응 프리프린트로 관심 증폭", "action": "혈액내과와 '이전 치료 반응 불충분 성인 ITP' 사용 기준(라인/중단/반응평가) 1페이지 초안 작성 후 신약평가 안건으로 상정" },
    { "rank": 2, "inn": "FOSTAMATINIB", "reason": "external에서 ITP 3상 1차 평가지표 미달로 처방 확대·재고 상향의 근거 약화", "action": "48시간 내 사용 환자·재고(로트/유효기간) 점검, 신규 발주 보류 기준을 약사위원회에 보고하고 소진 계획 확정" },
    { "rank": 3, "inn": "RITUXIMAB", "reason": "therapeutic/external에서 불응군 대체 옵션으로 반복 언급, 경구 BTK 도입 시 주사 기반 치료 일부 대체 가능", "action": "ITP 오더셋에서 rituximab 사용 위치(라인/전처치/감염 모니터링) 재확인하고, BTK 도입 시 전환 시나리오(외래/입원) 2안 작성" },
    { "rank": 4, "inn": "IVIG", "reason": "therapeutic/external에서 표준 치료로 유지되나, 경구 표적치료 확산 시 입원 기반 사용량 변동 가능", "action": "ITP 응급·출혈 상황에서 IVIG 우선순위는 유지하되, 불응군 장기유지 목적 사용은 적정성 점검 항목으로 분리" },
    { "rank": 5, "inn": "TPO-RA", "reason": "therapeutic/external에서 2차 옵션으로 언급, BTK 신약 도입 시 경쟁·병용 가능성으로 처방 패턴 변화 예상", "action": "TPO-RA 기존 급여 기준·반응평가 기록 템플릿을 점검하고, BTK 도입 시 '순차/병용 금지 또는 제한' 내부 원칙 초안 마련" }
  ],
  "risk_alerts": [
    "희귀·고가(NME+orphan) 약 도입 시 약제비 급증 및 분기별 변동성 확대(환자수 데이터 부족으로 예산 오차 위험)",
    "희귀의약품 특성상 공급·리드타임 불확실성으로 치료 공백 리스크",
    "fostamatinib 실패 신호로 향후 심사 강화 가능성—적응증/라인/반응평가 기록 미흡 시 삭감 리스크"
  ],
  "opportunities": [
    "ITP 불응군에서 경구 표적치료 도입에 맞춘 외래 중심 관리 모델(모니터링·상호작용·복약순응) 선제 구축",
    "신약평가 단계에서 사용 기준을 먼저 고정해 '소수 환자 고비용'의 내부 통제력 확보",
    "주사 기반 치료(IVIG/rituximab) 사용 일부를 외래 경구로 전환할 경우 병상·주사실 운영 부담 완화 여지"
  ],
  "tomorrow_watch": "rilzabrutinib 국내 허가·급여(MFDS/HIRA) 진행 공지와 BTK 장기추적 근거의 동료심사 게재 여부를 모니터링 항목으로 고정하라(현재 일정 미공개)."
}
```

**시제 검증**: "승인 완료" 포함, RILZABRUTINIB에 "승인 예정" 없음 → PASS

---

### C-5. 치료영역 브리핑 — 미래 약물 (VELONATINIB)

**테스트**: `test_therapeutic_future_tense` — **PASSED**

```json
{
  "headline": "VELONATINIB, HCC 2차 2026-09-15 FDA 승인 예정",
  "key_takeaway": "진행성 HCC 2차 치료에서 신규 VEGFR/FGFR TKI가 2026-09-15 FDA 결정을 앞둬, 하반기 항암제 포뮬러리·예산 변동 가능성이 커졌다.",
  "top_drugs": [
    {
      "inn": "VELONATINIB",
      "status": "FDA: 2026-09-15 승인 예정(TA, NME) / EMA: 심사 중(PRIME)",
      "why_it_matters": "(a)경쟁구도 — 진행성 HCC에서 기존 2차 표준(다중 TKI·면역항암제 이후 옵션)과 직접 경쟁할 NME로, 병원 내 2차 라인업 재정렬 이슈. (b)급여/가격 — NME·breakthrough 지정으로 출시 시 약가 프리미엄 가능성. 국내 급여 등재 시 고가 항암제 예산 압력 확대. (c)환자규모 — 국내 대상 환자 수는 데이터 부족('이전 전신치료 후 진행' 조건으로 2차 이상 환자군에 한정). (d)처방변화 — 경구 TKI 계열로 외래 처방 비중이 늘 수 있어, 복약순응도·이상반응 모니터링(혈압, 단백뇨 등 TKI 공통) 프로토콜 정비 필요."
    }
  ],
  "trend_analysis": "이번 주 수집 1건 중 1건이 간세포암(HCC) 2차 치료 표적치료제였다. FDA는 2026-09-15로 일정이 공개돼 '승인 예정' 단계다. EMA는 PRIME 지정 상태로 심사 중이다. 기전은 VEGFR/FGFR 억제로, 혈관신생·FGFR 축을 동시에 겨냥하는 다중 키나아제 전략이 지속된다.",
  "action_items": [
    "포뮬러리 사전검토 착수: HCC 2차 이상 현재 사용 약제(경구 TKI/면역항암제 포함)와 비교표 1장으로 정리하고, 대체·추가 여부 시나리오(추가 등재 vs 교체)를 이번 주 내 초안 작성.",
    "운영·안전 준비: 경구 TKI 공통 모니터링(혈압·간기능·단백뇨)과 외래 추적 주기 표준안을 점검하고, 간센터·종양내과와 '출시 시 처방 경로(외래/입원)·교육자료' 협의 일정 확정."
  ]
}
```

**시제 검증**: "승인 예정", "심사 중" 포함 / "승인 완료" 없음 → PASS

---

### C-6. 혁신 브리핑 — 미래 약물 (VELONATINIB)

**테스트**: `test_innovation_future_tense` — **PASSED**

```json
{
  "headline": "VELONATINIB, HCC 2차 혁신신약 심사 중",
  "key_takeaway": "2026-09-15 FDA 결정 전, HCC 2차 치료에 VEGFR/FGFR 이중억제 NME가 들어올 수 있어 예산·프로토콜·대체약 포지션을 지금부터 정리해야 한다.",
  "nme_spotlight": [
    {
      "inn": "VELONATINIB",
      "designation": "NME, breakthrough, (EMA) PRIME",
      "implication": "(a)혁신성: VEGFR/FGFR 이중 억제 기전으로 HCC 2차 치료에서 기존 단일축 표적/면역치료 이후 옵션을 확장할 여지. (b)도입 시점: FDA 상태 TA이며 2026-09-15 결정 예정. EMA는 under_review로 승인일 미정. 국내 도입은 해외 허가 후 순차 진행 가능성이 높아, 2026년 하반기~이후를 전제로 준비 필요. (c)포지셔닝: 적응증이 '이전 전신치료 실패 후 진행'으로 명확해, 1차 표준요법 대체보다 2차 라인업 재편(기존 TKI/항체/IO 이후) 쪽 영향이 큼."
    }
  ],
  "pdufa_watch": ["VELONATINIB — FDA 2026-09-15 (TA, Type 1 NME) 결정 예정"],
  "strategic_implications": "이번 시그널은 '지정 자체'가 도입 속도를 당길 수 있다는 점이 핵심이다.\nBreakthrough는 심사·라벨 협의가 빨라질 수 있어, 병원은 허가 직후 처방 수요 급증을 대비해야 한다.\nEMA PRIME(FACT 상 PRIME 0건과 상충) 표기대로라면 유럽에서도 개발 우선순위가 높아, 글로벌 가이드라인 반영이 빨라질 수 있다.\n희귀·조건부 지정은 없어, 초고가·초소수 환자 모델보다는 '중증암 2차 표준 옵션'으로 예산 영향이 더 넓게 나타날 수 있다.",
  "action_items": [
    "HCC 2차 치료 현행 처방 경로(이전 전신치료 실패 후)와 대체약 리스트를 1페이지로 정리",
    "2026-09-15 FDA 결정 전까지 월 1회 PDUFA/EMA 심사 상태 업데이트 루틴화",
    "약사위원회(또는 신약평가) 사전 검토 템플릿에 MOA(VEGFR/FGFR) 기반 이상반응·모니터링 항목 초안 작성",
    "도입 시나리오 2개로 예산 영향 프레임 준비: (1)2차 일부 대체, (2)2차 환자군 확대(추가 사용) — 수요 추정은 데이터 부족으로 내부 환자수부터 산출",
    "FACT 상 PRIME 건수(0건)와 개별 약물의 PRIME 표기(있음) 불일치 확인: 원천 데이터/공식 공지로 교차검증 후 경영진 보고"
  ]
}
```

**시제 검증**: "심사 중", "결정 예정", "승인일 미정" 포함 / "승인 완료" 없음 → PASS

---

### C-7. 혼합 시제 통합 브리핑 — RILZABRUTINIB(과거) + VELONATINIB(미래)

**테스트**: `test_mixed_tense_unified` — **PASSED**

```json
{
  "headline": "ITP는 BTK로 재편, HCC 2차는 9월 결전",
  "key_takeaway": "rilzabrutinib는 미·EU 허가 완료로 국내 도입 압력이 커졌고, velonatinib는 2026-09-15 FDA 결정 예정이라 두 축(희귀혈액·간암) 모두 '선별처방+예산' 준비가 지금 필요하다.",
  "executive_summary": "ITP: rilzabrutinib는 2025-03-28 FDA, 2025-06-15 EMA 허가됨. 국내 도입 논의가 빨라질 신호다.\nITP: fostamatinib 3상 실패로 기존 처방 근거가 흔들린다. 대체·전환 프로토콜을 즉시 점검하라.\nHCC 2차: velonatinib는 2026-09-15 FDA 결정 예정. 하반기 외래 TKI 모니터링 부담이 커진다.\n공통: 두 약물 모두 NME 성격이 강하다. 약가·급여 불확실성이 예산 리스크다.\n결론: '사전승인 기준+모니터링 표준+재정 시나리오' 3종 세트를 이번 분기 안에 갖춰라.",
  "cross_analysis": "rilzabrutinib는 therapeutic·innovation·external 3개 스트림 동시 등장이다. 신호 강도가 높고, 환자 문의·비급여 요구가 먼저 올 수 있다.\nITP에서는 '신약 허가 완료'(rilzabrutinib)와 '기존약 임상실패'(fostamatinib)가 동시에 발생했다. 처방 알고리즘 재정렬 압력이 커진다.\nvelonatinib는 therapeutic·innovation 2개 스트림 동시 등장이다. 승인 예정(2026-09-15)이라 지금은 '라벨 미확정' 전제의 시나리오 준비가 최적이다.\n두 영역 모두 '이전 치료 실패 후'로 대상군이 제한된다. 병원은 실패 정의를 표준화해야 청구·심사 리스크를 줄인다.",
  "top_5_drugs": [
    { "rank": 1, "inn": "RILZABRUTINIB", "reason": "3개 스트림 교차 신호. FDA 2025-03-28 승인 완료, EMA 2025-06-15 허가됨. orphan/NME로 고가·선별처방 가능성.", "action": "혈액내과와 '이전 치료 반응 불충분' 원내 정의를 확정하고, 사전승인(Pre-auth) 체크리스트 1페이지를 이번 주 배포하라." },
    { "rank": 2, "inn": "VELONATINIB", "reason": "2개 스트림 교차 신호. FDA 2026-09-15 결정 예정, EMA 심사 중(PRIME). HCC 2차 외래 경구 TKI 도입 변수.", "action": "HCC 2차 포뮬러리 도입/미도입 2안과 재정영향 템플릿을 만들고, 간기능·상호작용·혈압 중심 모니터링 표준안을 간센터와 합의하라." },
    { "rank": 3, "inn": "FOSTAMATINIB", "reason": "external 스트림에서 ITP 3상 1차 평가지표 미달(임상실패). 처방 근거 약화로 심사 강화 가능성.", "action": "2026-03-30 기준 원내 사용 환자 전수 점검(반응·부작용·적응증) 후, 발주량을 4주 단위로 재산정하라." },
    { "rank": 4, "inn": "RITUXIMAB", "reason": "ITP 대체치료 축으로 즉시 전환 가능한 옵션(외부 시그널의 전환 권고에 포함). 단기 수요 변동 가능.", "action": "ITP 전환 체크리스트에 rituximab 사용 조건(순차/병용 원칙, 모니터링)을 반영하고, 외래·입원 공통 오더셋을 점검하라." },
    { "rank": 5, "inn": "TPO-RA", "reason": "ITP 표준 대체치료 축. fostamatinib 불확실성 확대 시 처방 쏠림 가능.", "action": "TPO-RA 처방 환자군을 '구제요법'과 '유지요법'으로 분류해 월별 사용량을 모니터링하고, 재고 안전재고 기준을 재설정하라." }
  ],
  "risk_alerts": [
    "ITP: fostamatinib 3상 실패로 처방 근거 약화 → 청구 심사 강화 가능성. 처방 사유·반응 기록 표준화가 지연되면 삭감 리스크.",
    "ITP: rilzabrutinib 해외 허가 완료로 비급여 선사용 요구가 먼저 발생 가능 → 원내 사용기준 부재 시 처방 편차·민원 리스크.",
    "HCC: velonatinib 승인 예정(2026-09-15)으로 하반기 외래 경구 TKI 모니터링 수요 급증 가능 → 간기능·상호작용 관리 미흡 시 안전성 리스크."
  ],
  "opportunities": [
    "rilzabrutinib 도입 전 '선별처방+사전승인' 체계를 선제 구축하면, 고가 희귀약 도입 시 예산 통제 모델로 재사용 가능.",
    "HCC 2차는 승인 전부터 AMT 템플릿을 표준화할 기회. 2026-09-15 전후 신속 의사결정이 가능해진다.",
    "ITP 치료 알고리즘을 '실패 정의' 중심으로 재정렬하면, 진료과 간 처방 편차와 청구 변동성을 동시에 줄일 수 있다."
  ],
  "tomorrow_watch": "rilzabrutinib 국내 허가·급여 관련 공지(식약처/심평원)와 velonatinib EMA 심사 상태 업데이트를 주간 리포트 추적 항목에 즉시 반영하라."
}
```

**시제 검증**:
- RILZABRUTINIB → "허가 완료", "승인 완료" (과거) → PASS
- VELONATINIB → "결정 예정", "승인 예정", "심사 중" (미래) → PASS

---

## Part D. 테스트 결과 요약

| # | 테스트 | 약물 | 시제 | 결과 |
|---|--------|------|------|------|
| 1 | test_system_prompt_has_today_placeholder | - | - | PASSED |
| 2 | test_system_prompt_has_time_rules | - | - | PASSED |
| 3 | test_system_prompt_has_few_shot | - | - | PASSED |
| 4 | test_system_prompt_key_takeaway_rule | - | - | PASSED |
| 5 | test_extract_drug_intel_v3_fields | RILZABRUTINIB | - | PASSED |
| 6 | test_extract_drug_intel_max_14 | TEST | - | PASSED |
| 7 | test_therapeutic_briefing_e2e | RILZABRUTINIB | 과거 | PASSED |
| 8 | test_innovation_briefing_e2e | RILZABRUTINIB | 과거 | PASSED |
| 9 | test_external_briefing_e2e | RILZABRUTINIB+FOSTAMATINIB | 과거 | PASSED |
| 10 | test_unified_briefing_e2e | 3스트림 합산 | 과거 | PASSED |
| 11 | test_therapeutic_future_tense | VELONATINIB | 미래 | PASSED |
| 12 | test_innovation_future_tense | VELONATINIB | 미래 | PASSED |
| 13 | test_mixed_tense_unified | RILZABRUTINIB+VELONATINIB | 혼합 | PASSED |

## Part E. 관련 파일 목록

| 파일 | 역할 |
|------|------|
| `regscan/stream/briefing.py` | SYSTEM_PROMPT + 스트림별 프롬프트 + LLM 호출 |
| `tests/test_v3_briefing.py` | 오프라인 6건 + E2E 7건 테스트 |
| `output/test_v3_full_results.log` | pytest 실행 로그 원본 (UTF-8) |
| `output/v3_briefing_test_report_2026-03-30.md` | 이 리포트 |
