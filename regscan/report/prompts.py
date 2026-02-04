"""LLM 프롬프트 템플릿

프롬프트 엔지니어링 기법 적용:
- Few-Shot: 좋은 예시 제공
- Chain-of-Thought: 단계별 추론
- 도메인 지식 주입: 의약품 규제/급여 전문 지식
"""

# === 시스템 프롬프트 ===

SYSTEM_PROMPT = """당신은 의약품 규제 전문 기자이자 건강보험 전문가입니다.

## 전문 분야
- FDA/EMA/MFDS 승인 절차 및 규제 동향
- HIRA 급여 심사 및 약가 결정
- 희귀의약품, 항암제, 바이오의약품 급여 정책
- 메드클레임(의료비 청구) 실무

## 작성 원칙
1. 객관적 사실만 기술 - 데이터에 없는 정보 작성 금지
2. 전문 용어 사용하되 명확하게 설명
3. 메드클레임 시사점은 구체적 수치 포함
4. 한국어로 작성, 약물명/기관명은 영문 유지

## 급여 관련 도메인 지식
- 일반 급여: 본인부담 30%
- 희귀질환 산정특례: 본인부담 10%
- 암환자 산정특례: 본인부담 5%
- 고가약제(100만원 이상): 사전심사 대상 가능
- 비급여: 전액 환자부담, 실손보험 청구 가능"""


# === 브리핑 리포트 프롬프트 (Few-Shot + CoT) ===

BRIEFING_REPORT_PROMPT = """아래 약물 데이터를 분석하여 브리핑 리포트를 작성하세요.

## 입력 데이터
{drug_data}

---

## 분석 단계 (Chain-of-Thought)

단계별로 분석하세요:

### 1단계: 글로벌 승인 현황 파악
- FDA 승인 여부/일자
- EMA 승인 여부/일자
- Breakthrough/Orphan/PRIME 지정 여부

### 2단계: 국내 현황 파악
- MFDS 허가 여부/일자
- HIRA 급여 상태 (급여/삭제/비급여/미등재)
- CRIS 임상시험 진행 상황

### 3단계: 메드클레임 시사점 분석
- 급여 적용 시: 본인부담률, 고가약제 여부
- 비급여 시: 환자 부담, 실손보험 청구
- 희귀질환/암 산정특례 해당 여부

### 4단계: 핵심 메시지 도출
- 가장 중요한 4가지 포인트 정리

---

## Few-Shot 예시

### 예시 1: 급여 적용 고가 항암제

입력:
```json
{{"inn": "PEMBROLIZUMAB", "fda": {{"approved": true, "date": "2014-09-04"}},
"ema": {{"approved": true, "date": "2015-07-17"}},
"hira": {{"status": "reimbursed", "price": 2103620}}}}
```

출력:
```json
{{
  "headline": "면역항암제 PEMBROLIZUMAB, FDA·EMA·MFDS 승인 완료 - 국내 급여 적용 중",
  "subtitle": "다양한 암종 적응증 보유, 고가약제로 사전심사 대상",
  "key_points": [
    "FDA 2014년, EMA 2015년 승인으로 글로벌 표준치료제 지위 확보",
    "MFDS 허가 및 HIRA 급여 적용 완료",
    "상한가 약 210만원 - 고가약제로 사전심사 대상",
    "일반 급여 시 본인부담 약 63만원(30%), 암환자 산정특례 시 약 10만원(5%)"
  ],
  "global_section": "PEMBROLIZUMAB은 2014년 9월 FDA, 2015년 7월 EMA 승인을 받은 PD-1 면역관문억제제입니다. 흑색종, 비소세포폐암, 두경부암 등 다양한 암종에 적응증을 보유하고 있습니다.",
  "domestic_section": "국내에서는 MFDS 허가를 받았으며, HIRA 급여가 적용되어 건강보험 혜택을 받을 수 있습니다. 키트루다주(제품명)로 시판 중이며, 9건의 임상시험이 CRIS에 등록되어 있습니다.",
  "medclaim_section": "급여 적용 약제로 상한가 약 210만원입니다. 일반 급여 시 본인부담 30%(약 63만원), 암환자 산정특례 적용 시 5%(약 10만원)입니다. 100만원 이상 고가약제로 사전심사 대상이 될 수 있습니다."
}}
```

### 예시 2: 국내 미허가 신약

입력:
```json
{{"inn": "ELRANATAMAB", "fda": {{"approved": true, "date": "2023-08-14"}},
"ema": {{"approved": true, "date": "2023-12-14"}},
"mfds": {{"approved": false}}, "hira": {{"status": null}},
"cris": {{"trial_count": 1}}}}
```

출력:
```json
{{
  "headline": "다발골수종 치료제 ELRANATAMAB, 글로벌 승인 완료 - 국내 도입 임박",
  "subtitle": "FDA·EMA 승인, 국내 임상 1건 진행 중",
  "key_points": [
    "FDA 2023년 8월, EMA 2023년 12월 승인 - 글로벌 동시 출시",
    "MFDS 미허가로 국내 정식 처방 불가",
    "CRIS 등록 임상시험 1건 진행 - 임상 참여로 약물 접근 가능",
    "비급여 상태로 처방 시 전액 환자부담 예상"
  ],
  "global_section": "ELRANATAMAB은 2023년 FDA와 EMA에서 승인받은 BCMA×CD3 이중특이항체입니다. 재발/불응성 다발골수종 치료에 사용됩니다.",
  "domestic_section": "현재 MFDS 허가 전으로 국내 정식 판매가 불가능합니다. 그러나 CRIS에 1건의 임상시험이 등록되어 있어, 임상 참여를 통한 약물 접근이 가능합니다.",
  "medclaim_section": "국내 미허가 상태로 급여 적용이 불가합니다. 긴급도입 또는 임상시험 외 처방 시 전액 환자부담입니다. 희귀의약품센터를 통한 긴급도입 가능성을 모니터링하시기 바랍니다."
}}
```

---

## 출력 형식

위 예시와 동일한 JSON 형식으로 출력하세요.
반드시 실제 데이터에 기반한 구체적인 내용을 작성하세요.
추측하지 말고, 데이터에 없는 정보는 "정보 없음"으로 표기하세요.

```json
{{
  "headline": "30자 이내 헤드라인",
  "subtitle": "50자 이내 서브타이틀",
  "key_points": ["포인트1", "포인트2", "포인트3", "포인트4"],
  "global_section": "글로벌 승인 현황 2-3문장",
  "domestic_section": "국내 현황 2-3문장",
  "medclaim_section": "메드클레임 시사점 2-3문장"
}}
```"""


# === 메드클레임 시사점 전용 프롬프트 ===

MEDCLAIM_INSIGHT_PROMPT = """이 약물의 메드클레임(의료비 청구) 시사점을 분석하세요.

## 약물 정보
{drug_data}

## 분석 프레임워크

단계별로 분석하세요:

### 1단계: 급여 상태 확인
- 급여/삭제/비급여/미등재 중 어디에 해당?
- 급여 기준(적응증 제한) 있는지?

### 2단계: 본인부담금 계산
- 상한가 확인
- 일반 급여: 상한가 × 30%
- 희귀질환 산정특례: 상한가 × 10%
- 암환자 산정특례: 상한가 × 5%

### 3단계: 특이사항 확인
- 고가약제(100만원 이상) 여부 → 사전심사
- 희귀의약품 지정 여부 → 산정특례
- 임상시험 진행 여부 → 약물 접근 경로

### 4단계: 환자 안내사항 정리

## 출력 형식 (JSON)
```json
{{
  "reimbursement_status": "급여 상태 요약",
  "out_of_pocket": {{
    "general": "일반 급여 시 본인부담",
    "special": "산정특례 시 본인부담"
  }},
  "considerations": ["고려사항1", "고려사항2"],
  "patient_guidance": "환자 안내 요약"
}}
```"""


# === 간단 요약 프롬프트 ===

QUICK_SUMMARY_PROMPT = """아래 약물 데이터를 2-3문장으로 요약하세요.

{drug_data}

요약 작성 시:
1. 글로벌 승인 현황 (FDA/EMA)
2. 국내 현황 (MFDS/HIRA)
3. 핵심 시사점

출력: 간결한 한국어 요약 (추측 없이 사실만)"""


# === 모델별 최적화 프롬프트 ===

def get_optimized_prompt(model: str, drug_data: str) -> str:
    """모델에 따른 최적화된 프롬프트 반환

    - gpt-4o-mini: 간결한 지시, JSON 출력 강조
    - gpt-4o: 상세한 CoT, 복잡한 추론
    - claude: 구조화된 XML 태그 활용
    """
    if "gpt-4o-mini" in model or "gpt-3.5" in model:
        # 간결한 프롬프트, 토큰 효율성
        return f"""의약품 브리핑 리포트를 JSON으로 작성하세요.

데이터:
{drug_data}

출력 (JSON만):
{{"headline": "제목", "subtitle": "부제", "key_points": ["1", "2", "3", "4"], "global_section": "글로벌", "domestic_section": "국내", "medclaim_section": "메드클레임"}}"""

    elif "gpt-4" in model or "gpt-5" in model:
        # 상세한 CoT 프롬프트
        return BRIEFING_REPORT_PROMPT.format(drug_data=drug_data)

    else:  # claude 등
        return BRIEFING_REPORT_PROMPT.format(drug_data=drug_data)
