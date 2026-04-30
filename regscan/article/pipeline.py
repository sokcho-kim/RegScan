"""기사 생성 에이전트 파이프라인 v3 (2-Pass)

5-Agent Pipeline (전문지 기사체):
  1. Editor-in-Chief: 핵심 이슈 중심 스토리 선별 + 등급/슬롯 지정
  2. Reporter: 사실→의미→영향→전망 구조의 기사 초안 (1st Pass)
  3. Fact-Checker: 결측 제거 + 지시문 제거 + 수치 검증
  4. Structure-Validator: 슬롯 기반 구조 누락 검증 + 삽입 (2nd Pass)
  5. Copy-Editor: 제목-리드-본문 메시지 일치 + 최종 정제

v2→v3 변경: 3회 보강 루프 제거, 구조검증기 추가로 1회 서술+1회 검증 구조

품질 기준: docs/research/article-reference/article-quality-spec.md
레퍼런스: 약업신문 + 뉴시스 산업 기사 톤
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from regscan.config import settings

logger = logging.getLogger(__name__)


# ── LLM 호출 공통 ──

async def _call_llm(system: str, user: str, temperature: float = 0.3) -> str:
    """LLM 호출 (OpenAI, max_completion_tokens=4096)"""
    if settings.OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=getattr(settings, "LLM_MODEL", "gpt-5.2"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_completion_tokens=4096,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("OpenAI 호출 실패: %s", e)

    raise RuntimeError("LLM 키 없음 (Gemini/OpenAI 모두 실패)")


def _extract_json(text: str) -> dict | list:
    """LLM 응답에서 JSON 추출"""
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        return json.loads(match.group(1))
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    raise ValueError(f"JSON 추출 실패: {text[:200]}")


# ══════════════════════════════════════════════
# Agent 1: 편집장 — 스토리 선별
# ══════════════════════════════════════════════

EDITOR_CHIEF_SYSTEM = """당신은 의약품 전문 매체의 편집장입니다.
독자: 병원 의사, 약제팀, 제약·바이오 업계, 행정인력.

## 임무: 방향 먼저, 근거는 그 다음

데이터를 요약하는 게 아니다. **"이번 주 우리 독자에게 중요한 이야기가 뭔가?"**를 먼저 결정하고,
그 이야기를 뒷받침할 근거를 데이터에서 찾는다. 근거가 약하면 기사를 안 낸다.

### 사고 순서 (반드시 이 순서대로)
1. **이번 주 제약·의료 현장에서 가장 중요한 변화/이슈는 무엇인가?** ← 여기서 출발
2. 그 이슈를 뒷받침할 근거가 제공된 데이터에 있는가?
3. 근거가 2개 소스 이상에서 교차 확인되는가?
4. 국내 독자에게 어떤 영향이 있는가?
5. 위 4개가 모두 성립하면 기사로 낸다. 하나라도 약하면 안 낸다.

### 금지 사항
- "KIPRIS 20건 중 2건", "NICE 179건" 같은 **내부 수집 기준을 기사 제목이나 핵심으로 쓰지 마라.** 이건 보조 근거일 뿐이다.
- 같은 소재를 2개 기사로 분리하지 마라. PD-1 특허 + PD-1 평가 → 1기사.
- "~가 확인됐다", "~가 포함됐다"로 끝나는 기사는 기사가 아니다.

### 기사 방향 유형
- **"regulation"**: 규제/정책 변화 — "뭐가 바뀌는데?"가 핵심. 영향받는 부서·업무 명시.
- **"drug"**: 약물 중심 — 적응증, 임상, 허가, 급여를 글로벌+국내로 연결. "이 약이 국내에 오면 뭐가 달라지는데?"
- **"industry"**: 산업/R&D — 특허, 파이프라인, 기업 전략. "이 흐름이 국내 제약·바이오에 어떤 의미인데?"

### 국�� 관점 연결 — 넓게 잡아라
"국내 관점"은 "이 약이 국내 허가/급여됐는가?"만이 아니다. 대부분의 글로벌 신약은 한국보다 해외에서 먼저 승인된다. 따라서 국내 관점은 아래를 포함한다:
- **글로벌 전략 시그널**: 제약사가 특정 시장 HTA를 포기/지연하는 패턴 → 한국 등재 우선순위에 대한 시사점
- **같은 약의 국내 사용 현황**: 해당 약물이 다른 적응증으로 국내에서 이미 사용 중이라면, 적응증 확장/축소의 의미
- **구조적 패턴**: "항암 고가약 비제출 3건" → 글로벌 제약사의 시장 공략 우선순위에서 한국이 후순위로 밀릴 수 있는 구조
- **제도적 함의**: 해외 규제 변화가 국내 제도(급여 기준, 허가 심사, 가이드라인)에 참고/영향을 줄 수 있는 경로
- **국내 제약·바이오 경쟁**: 글로벌 동향이 국내 기업의 R&D, 바이오시밀러, 라이선스 전략에 미치는 영향

"국내에서 아직 허가/급여 안 됐으니 관계없다"는 판단은 틀렸다. **"아직 안 됐기 때문에 더 중요하다"가 맞는 경우가 많다.**

### 기사 등급 분류 (A/B/C/D) — 반드시 먼저 판정
각 소재를 A/B/C/D로 분류한다. **"왜 이 글을 별도로 읽어야 하는가?"에 답이 없으면 C 또는 D.**

- **A (분석 기사)**: 제도·시장·임상·급여·병원 운영상 구조적 의미가 있는 소재. 700~1,000자. 사건+배경+기존과 차이+영향 대상+관찰 포인트 필수.
- **B (해설형 단신)**: 공식 발표 1개지만 실무 영향이 있는 소재. 400~600자. 핵심 사실+왜 중요한가+영향 대상+다음 확인 포인트.
- **C (카드형 단신)**: 단순 발표·일정·수치 중심. 5줄 카드 형식. **억지로 기사체로 늘리지 마라.**
- **D (병합/폐기)**: 기존 기사와 같은 주제이거나 독자 가치 약함. 상위 기사에 병합하거나 제외.

### 제목 기준
제목에 출처명, 단순 건수, 내부 집계값을 앞세우지 마라. 독자가 얻을 의미를 중심으로.
- 나쁜 예: "NICE TA966 1건, 비제출로 평가 종료" / "CSU 첫 경구 표적치료 1건 승인"
- 좋은 예: "NICE 비제출 종료 사례, 신약 급여 전략 리스크 부각" / "CSU 경구 표적치료 등장…주사제 중심 치료축 흔드나"

### 정보 축소 금지
짧게 만들더라도 구조적 의미를 만드는 정보는 삭제하지 마라.
예: NICE 기사에서 전체 STA 목록 수, 비제출 종료 건수, 권고/Optimised/CDF 건수, 대표 사례, "제출 여부가 절차를 좌우" 해석 — 이것들은 핵심 구조다. 단건으로 축소하면 기사 가치가 떨어진다.

## 출력
```json
[
  {
    "story_id": 1,
    "article_type": "regulation/drug/industry",
    "grade": "A/B/C/D",
    "grade_reason": "왜 이 등급인가 — A라면 구조적 의미 명시, D라면 병합/폐기 대상과 이유",
    "read_reason": "독자가 이 글을 별도로 읽어야 하는 이유 1문장. D등급이면 빈칸.",
    "direction": "이 기사의 방향 — '무엇에 대해, 어떤 관점으로 쓸 것인가' 1~2문장",
    "core_message": "독자가 기억할 핵심 1문장 — 반드시 의미/영향/변화. 사실 서술 금지.",
    "headline_draft": "헤드라인 초안 (25자 이내, 의미 중심 — 출처명·건수 앞세우기 금지)",
    "evidence": ["이 방향을 뒷받침하는 근거 1 (소스+수치)", "근거 2", "근거 3"],
    "structural_info": ["기사 구조에 반드시 포함할 핵심 정보 (삭제 금지)", "예: 전체 N건 중 M건"],
    "domestic_angle": "국내 영향 — 허가/급여/R&D/병원실무 중 어떤 관점으로 연결할 것인가",
    "sources_used": ["KIPRIS_PATENT", "NICE_TA", "FDA_LABEL"],
    "publishable": "가능/보류/불가",
    "publishable_reason": "가능하면 빈칸, 보류/불가면 이유",
    "priority": "high/medium"
  }
]
```"""


async def agent_editor_chief(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """Agent 1: 시그널 → 스토리 선별"""
    from regscan.stream.intelligence_signals import format_for_prompt

    signal_text = ""
    for src_type, sigs in signals.items():
        signal_text += format_for_prompt(src_type, sigs) + "\n\n"

    user_prompt = f"""오늘 날짜: {datetime.now().strftime('%Y-%m-%d')}

수집된 전체 시그널:

{signal_text}

위에서 기사 가치가 있는 스토리 3~5개를 선별하세요.
데이터가 빈약한 소스는 반드시 제외하세요."""

    response = await _call_llm(EDITOR_CHIEF_SYSTEM, user_prompt)
    stories = _extract_json(response)
    logger.info("[편집장] %d개 스토리 선별", len(stories))
    return stories


# ══════════════════════════════════════════════
# Agent 2: 기자 — 초안 작성
# ══════════════════════════════════════════════

REPORTER_SYSTEM = """당신은 약업신문·뉴시스 수준의 의약품 전문 기자입니다.
독자: 병원 의사, 약제팀, 행정인력.

## 기사 구조 (반드시 이 순서)
1. **리드** (정확히 2문장, 3요소 필수):
   - 문장 1: **무엇이** 일어났는지 (핵심 사실 + 숫자)
   - 문장 2: **왜 중요한지** + **누가** 영향받는지
   - 이 3요소가 없으면 불합격. 다른 정보는 본문으로.
2. **대표 사례** (1~2단락, 최대 3개): 가장 강한 구체적 예시만. 약물명, 적응증, 날짜, 수치.
   - 사례 4개 이상 나열 금지. 많아질수록 기사성이 내려간다.
   - 대표 2~3개만 남기고 나머지는 버려라.
3. **맥락/비교** (1단락, 필수): 기존 대비 뭐가 달라졌는지. 반드시 "A vs B" 형태의 비교를 수치와 함께 포함.
   - 예: "기존 52% → AI 적용 후 80~90%", "전작 대비 25.5개월 vs 16.7개월"
   - 비교 대상이 없으면 시간축("지난해 같은 기간 대비")이나 규모("전체 N건 중 M건") 활용.
   - **이 단락이 없으면 기사 불합격.**
4. **해석** (1단락): "그래서 뭐가 바뀌는데?"에 답하는 문단. 추상적 코멘트 금지, 구체적 영향을 쓸 것.
   - 나쁜 예: "현장 부담이 커질 수 있다" (누구? 뭐가?)
   - 좋은 예: "병원 약제팀은 급여 등재 일정을 재점검해야 하는 상황이다"
   - 법안 기사: 영향받는 부서(감염관리위, 원무, 약제 등)와 준비할 자료/프로세스를 구체적으로
   - 특허 기사: 국내 R&D 경쟁, 후속 특허 전략, 병용요법 도입 가능성 중 최소 2개 관점
5. **마무리** (1~2문장): 구체적 관전 포인트 1개를 명시하고, "~가 될 전망이다" 수준의 강한 표현 사용. "가능성이 있다" 같은 약한 표현 금지.

## 문체 규칙
- 보도체: "~로 나타났다", "~로 풀이된다", "~전망이다"
- 수치가 근거: 주장마다 구체적 숫자가 붙어야 한다
- 일본어/영어 원문은 한글 번역 후 괄호에 원문 병기
- 간결하고 건조하게. 감탄사, 의문문 사용하지 않음
- **컬럼 나열 금지**: "FDA 승인 정보는 PRIORITY로 분류돼 있고, 일자는 X, 스폰서는 Y" → 이건 데이터 덤프다. 대신 "FDA에서 우선심사(Priority Review)로 승인된 이력이 있어, 임상적 차별화가 인정된 제품"처럼 해석하라.
- **해석 문장 의무**: 사실만 쓰지 마라. "~가 확인됐다"로 끝내지 말고 "이는 ~를 시사한다", "국내에서는 ~가 쟁점이 될 수 있다"를 반드시 붙여라.
- **국내 관점 필수**: 해외 데이터만 나열하면 불합격. 국내 허가·급여·R&D·병원 실무 중 최소 1개 관점 연결.
- 기관명 규칙: 첫 등장 시 "풀네임(이하 약어)" → 이후 약어만. 매 기사 반복 금지.
  - "일본 의약품의료기기종합기구(이하 PMDA)" → 이후 "PMDA". 반드시 "(이하 PMDA)" 포함.
  - "미국 식품의약국(이하 FDA)" → 이후 "FDA"
  - "유럽의약품청(이하 EMA)" → 이후 "EMA"
  - "식품의약품안전처(이하 식약처)" → 이후 "식약처"
  - "건강보험심사평가원(이하 심평원)" → 이후 "심평원"
  - "영국 국립보건의료연구원(이하 NICE)" → 이후 "NICE"
  - 풀네임을 2회 이상 반복하면 불합격.
- 분량은 등급에 따라 다름 (아래 등급별 포맷 참조)

## 전망 문장 구체화 규칙
"쟁점이 될 전망이다"로 끝내지 마라. 무엇이 쟁점인지 최소 2~3개로 풀어라.
- 나쁜: "국내 급여 논의에서 쟁점이 될 전망이다."
- 좋은: "국내 급여 논의에서는 H1 항히스타민 불충분 환자의 정의, 오말리주맙 대비 투여 단계, 경구 복용 편의성을 비용효과성 평가에서 어떻게 반영할지가 쟁점이 될 수 있다."

## 절대 금지 (위반 시 기사 불합격)
- "데이터 부족", "확인 불가", "분석 불가" → 모르면 안 쓴다
- "약제팀은 ~하라", "즉시 점검하라" → 실무 지시 금지
- "RA/MA는", "병원은 ~해야" → 특정 대상 지시 금지
- "그래서 뭐?", "[FACT DATA]" → 메타 코멘트 금지
- 데이터에 없는 내용 추측
- "전망이다" 2회 이상 반복

## 좋은 리드 예시
> 일본 PMDA가 3월 23일 항암 신약 6건을 일괄 승인하면서, 국내 허가·급여 일정에도 변화가 예상된다. 같은 날 승인된 20건 중 희귀질환 지정 5건이 포함돼, 고가약 급여 논의가 앞당겨질 전망이다.

> 국회에 4월 한 달간 보건의료 법안 15건이 쏟아졌다. 의료법 5건, 건강보험법 3건이 집중 발의되면서 병원 운영과 급여 체계에 변화가 예고되고 있다.

## 나쁜 리드 예시 (이렇게 쓰면 불합격)
> PMDA는 엔허투를 승인했다. 향후 관련 변화가 주목된다.
> 국회에서 법안이 발의됐다. 보건의료 관련 법안이다.
> PMDA는 2026년 3월 23일 승인 20건을 공개했으며... (보도자료 재진술)

## 참조 기사 (이 수준으로 써야 합격)

아래는 약업신문 실제 기사의 구조입니다. 이 톤과 깊이를 따르세요.

> **제목:** AI 설계 신약 173개 임상…첫 허가 '초읽기'
>
> **리드:** 인공지능이 설계한 신약이 임상 단계에서 성과를 내며, 2026년 첫 허가 승인 가능성이 나타나고 있다. AI 기반 신약 후보물질 173개가 임상시험에 진입했고, 이 중 15~20개는 올해 임상 3상에 돌입할 것으로 예상된다.
>
> **대표 사례:** 인실리코 메디슨이 개발한 '렌토세르팁'이 대표 사례다. 특발성 폐섬유증 치료제로 개발 중이며, 임상 2a상에서 최고 용량 투여군의 폐활량이 평균 98.4mL 증가한 반면 위약군은 62.3mL 감소하여 160mL 이상의 유의미한 차이를 보였다.
>
> **비교:** AI 신약은 임상 1상 성공률이 80~90% 수준으로, 전통적 신약 개발의 약 52% 대비 우위를 보인다.
>
> **마무리:** 2026년 첫 허가 사례와 임상 3상 결과는 향후 제약 산업의 주도권을 가를 분수령이 될 전망이다.

위 기사의 특징: (1) 리드 2문장에 수치 3개, (2) 대표 사례에 임상 수치, (3) "80~90% vs 52%" 비교, (4) "분수령" 강한 마무리.

## 출력
```json
{
  "headline": "최종 헤드라인 (25자 이내, 숫자 포함)",
  "subheadline": "부제 (40자 이내)",
  "body": "전체 기사 본문 (리드~마무리 포함, 단락 사이 빈 줄)"
}
```"""


async def agent_reporter(
    story: dict,
    signals: dict[str, list[dict]],
) -> dict:
    """Agent 2: 스토리 → 기사 초안"""
    from regscan.stream.intelligence_signals import format_for_prompt

    sources_used = story.get("sources_used", [])
    relevant_data = ""
    for src in sources_used:
        if src in signals:
            relevant_data += format_for_prompt(src, signals[src]) + "\n\n"
    if not relevant_data:
        for src_type, sigs in list(signals.items())[:3]:
            relevant_data += format_for_prompt(src_type, sigs) + "\n\n"

    grade = story.get("grade", "A")

    # 등급별 작성 지시
    if grade == "A":
        grade_instruction = """## A등급: 분석 기사 — 반드시 5블록 구조 (700~1,000자)

**블록 1. 사건** (2~3문장): 무슨 일이 일어났는가. 핵심 사실 + 수치 + 누가 발표했는가.
**블록 2. 배경** (1단락): 왜 이게 중요한가. 기존에 어떤 치료/제도가 있었는가.
**블록 3. 기존과 차이** (1단락): 구체적으로 뭐가 다른가. 반드시 비교 수치 포함. "최초", "기존 대비 X%", "이전에는 ~였으나 이제는 ~" 등.
**블록 4. 영향 대상** (1단락): 국내 시장/병원/제약사/환자에게 어떤 영향이 있는가. 추상적 "영향이 클 수 있다" 금지 — 구체적으로.
**블록 5. 다음 관찰 포인트** (1단락): 구체적 이벤트(허가 신청일, 임상 결과 발표, 급여 심의 일정, 경쟁 약물 동향).

**5블록이 하나라도 빠지면 불합격. 700자 미만이면 불합격.**

### 정보 축소 금지
편집장이 structural_info로 지정한 핵심 정보는 절대 삭제하지 마라. 기사가 길어지더라도 구조적 의미를 만드는 정보를 유지하라."""

    elif grade == "C":
        grade_instruction = """## C등급: 카드형 단신 — 5줄 카드 형식

아래 형식 그대로 작성. 억지로 기사체 문단으로 늘리지 마라.

제목:
핵심 사실:
왜 중요한가:
영향 대상:
실무 체크:
다음 확인 포인트:"""

    else:  # B (해설형 단신)
        grade_instruction = """## B등급: 해설형 단신 — 400~600자

핵심 사실 + 왜 중요한가 + 영향 대상 + 다음 확인 포인트.
기사체로 작성하되 간결하게. 배경/비교 블록은 생략 가능."""

    # 재작성 피드백이 있으면 추가
    rewrite_feedback = story.get("_rewrite_feedback", [])
    rewrite_section = ""
    if rewrite_feedback:
        rewrite_section = "\n## ⚠️ 재작성 지시 — 이전 초안이 아래 기준에서 불합격됨:\n"
        for fb in rewrite_feedback:
            rewrite_section += f"- {fb}\n"
        rewrite_section += "위 문제를 반드시 해결하여 다시 작성하라.\n"

    structural_info = story.get("structural_info", [])
    structural_section = ""
    if structural_info:
        structural_section = "\n## ⚠️ 정보 축소 금지 — 아래 정보는 반드시 기사에 포함하라:\n"
        for info in structural_info:
            structural_section += f"- {info}\n"

    user_prompt = f"""## 편집장 지시

기사 등급: {grade}
기사 방향: {story.get('direction', story.get('angle', ''))}
핵심 메시지: {story.get('core_message', '')}
독자가 읽어야 하는 이유: {story.get('read_reason', '')}
헤드라인 초안: {story.get('headline_draft', '')}
국내 관점: {story.get('domestic_angle', '')}
근거: {json.dumps(story.get('evidence', story.get('key_facts', [])), ensure_ascii=False)}

{grade_instruction}
{structural_section}
{rewrite_section}

## 원본 데이터

{relevant_data}

## 공통 규칙
1. **방향이 먼저다.** 편집장이 정한 방향에 맞춰 써라. 데이터를 나열하지 마라.
2. **컬럼 나열 금지.** "FDA 승인 정보는 PRIORITY로 분류, 일자는 X" → 이건 데이터 덤프. 해석하라.
3. **국내 관점 필수.** domestic_angle을 반드시 반영.
4. **국내 크로스레퍼런스 활용.** 원본 데이터에 국내 허가·급여·임상 태그가 있으면 기사에 녹여라.
5. **데이터에 없는 건 단정하지 마라.** 합리적 해석은 "가능성", "관찰 포인트"로."""

    response = await _call_llm(REPORTER_SYSTEM, user_prompt)
    article = _extract_json(response)
    logger.info("[기자] 초안: %s", article.get("headline", "")[:30])
    return article


# ══════════════════════════════════════════════
# Agent 3: 팩트체커 — 검증 + 결측 제거
# ══════════════════════════════════════════════

FACT_CHECKER_SYSTEM = """당신은 의약품 전문 매체의 팩트체커입니다.

## 검토 항목 (체크리스트)

### 하드 룰 위반 (1개라도 있으면 해당 문장 삭제/수정)
- [ ] "데이터 부족", "확인 불가", "분석 불가" → 해당 문장 삭제
- [ ] "추가 확인이 필요하다", "후속 자료를 통해 확인" → 해당 문장 삭제
- [ ] "공문서와 허가사항에서 확인" → 해당 문장 삭제
- [ ] "약제팀은", "RA/MA는", "병원은 ~해야" → 해당 문장 삭제
- [ ] "즉시 점검하라", "재검토해야 한다" → 해당 문장 삭제
- [ ] "그래서 뭐?", "[FACT DATA]" → 해당 문장 삭제
- [ ] "전망이다" 2회 이상 → 1회로 축소
- [ ] "~으로 정리된다", "~으로 집계됐다"가 마무리 → 의미 있는 전망으로 교체
- [ ] 외국어 기관명 음역(엥스띠뛰, 위니베르시떼 등) → 영문 약어 또는 삭제. 독자가 읽을 수 없는 음역 금지.
- [ ] 기관명 "(이하 약어)" 누락 → 첫 등장에 반드시 "(이하 PMDA)" 등 삽입

### 팩트 검증
- [ ] 기사의 수치가 원본 데이터와 일치하는가?
- [ ] 약물명·적응증·날짜가 원본과 일치하는가?
- [ ] 데이터에 없는 내용을 추측하고 있지 않은가?

### 구조 검증
- [ ] 리드가 2문장 이내인가?
- [ ] 리드에 숫자가 1개 이상 있는가?
- [ ] 제목과 리드의 메시지가 일치하는가?

## 출력
수정된 기사를 반환하되, 수정 사항을 명시:
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "...",
  "corrections": ["수정 1: ~문장 삭제 (결측 노출)", "수정 2: ~"]
}
```"""


async def agent_fact_checker(
    article: dict,
    original_data: str,
) -> dict:
    """Agent 3: 기사 팩트체크 + 하드 룰 검증"""
    user_prompt = f"""## 기사 초안

{json.dumps(article, ensure_ascii=False, indent=2)}

## 원본 데이터 (검증 기준)

{original_data[:4000]}

위 체크리스트에 따라 검토하고 수정해주세요."""

    response = await _call_llm(FACT_CHECKER_SYSTEM, user_prompt, temperature=0.1)
    checked = _extract_json(response)
    corrections = checked.get("corrections", [])
    logger.info("[팩트체커] %d건 수정", len(corrections))
    return checked


# ══════════════════════════════════════════════
# Agent 5: 구조검증기 — 2nd Pass 슬롯 검증+삽입
# ══════════════════════════════════════════════

STRUCTURE_VALIDATOR_SYSTEM = """당신은 의약품 전문 매체의 구조검증 편집자입니다.

## 역할
기자가 쓴 기사(1st Pass)를 받아, **빠진 구조 요소를 원본 데이터에서 찾아 삽입**합니다.
기사를 다시 쓰는 것이 아닙니다. 기존 기사의 흐름을 유지하면서, 누락된 슬롯만 채워 넣습니다.

## 검증 슬롯 (A등급)

### 슬롯 1: 핵심 정보 (structural_info)
편집장이 지정한 핵심 정보가 본문에 있는가?
- 수치, 건수, 비율 등 구체적 팩트가 본문에 반영돼야 함
- 누락 시: 원본 데이터에서 해당 정보를 찾아 가장 적절한 단락에 삽입

### 슬롯 2: 국내 관점 (domestic_angle)
국내 허가·급여·R&D·병원실무 중 1개 이상 **구체적** 언급이 있는가?
- "국내에서도 주목된다" 수준은 불합격 — 약물명+허가상태/급여상태/상한가/임상 단계 등 구체적 팩트 필요
- 누락 시: 원본 데이터의 [국내 크로스레퍼런스] 태그에서 추출하여 영향 대상 단락 뒤에 삽입

### 슬롯 3: 근거 반영 (evidence)
편집장이 제시한 근거(evidence)가 본문에 반영됐는가?
- 소스+수치가 본문 어딘가에 있어야 함
- 누락 시: 해당 근거를 배경 또는 대표 사례 단락에 삽입

### 슬롯 4: 비교 블록
"A vs B" 형태의 수치 비교가 있는가?
- "기존 X → 현재 Y", "A 대비 B", "전작 대비" 등
- 누락 시: 원본 데이터에서 비교 가능한 수치 쌍을 찾아 맥락/비교 단락에 삽입
- 원본에 비교 데이터 없으면 "N/A" 표기

### 슬롯 5: 관찰 포인트
구체적 이벤트(날짜, 일정, 심의 예정, 임상 발표 등)가 마무리에 있는가?
- "전망이다"로 끝나면 불합격 — 무엇을/언제 지켜볼지 명시 필요
- 누락 시: 원본 데이터에서 일정/이벤트를 찾아 마무리 단락에 삽입

## B등급
슬롯 1(핵심 정보) + 슬롯 2(국내 관점) + 슬롯 5(관찰 포인트)만 검증.
슬롯 3, 4는 생략 가능.

## C/D등급
검증 불필요. 입력 그대로 반환.

## 작업 규칙
- 기존 문장을 삭제하지 마라. 추가/삽입만 한다.
- 삽입한 문장은 주변 문체와 톤을 맞춘다 (보도체).
- 원본 데이터에 없는 내용을 만들어내지 마라.
- 삽입 불가(원본에 해당 정보 없음)면 해당 슬롯을 "NOT_FOUND"로 표기.

## 출력
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "보강된 전체 기사 본문",
  "slot_results": {
    "structural_info": "PASS / INSERTED: 삽입 내용 요약 / NOT_FOUND",
    "domestic_angle": "PASS / INSERTED: ... / NOT_FOUND",
    "evidence": "PASS / INSERTED: ... / NOT_FOUND",
    "comparison": "PASS / INSERTED: ... / NOT_FOUND / SKIPPED(B등급)",
    "observation_point": "PASS / INSERTED: ... / NOT_FOUND"
  }
}
```"""


async def agent_structure_validator(
    article: dict,
    story: dict,
    original_data: str,
) -> dict:
    """Agent 5: 구조검증 — 슬롯 기반 누락 검증 + 삽입 (2nd Pass)"""
    grade = story.get("grade", "A")

    # C/D 등급은 검증 불필요
    if grade in ("C", "D"):
        article["slot_results"] = {
            "structural_info": "SKIPPED",
            "domestic_angle": "SKIPPED",
            "evidence": "SKIPPED",
            "comparison": "SKIPPED",
            "observation_point": "SKIPPED",
        }
        return article

    structural_info = story.get("structural_info", [])
    evidence = story.get("evidence", story.get("key_facts", []))
    domestic_angle = story.get("domestic_angle", "")

    user_prompt = f"""## 기사 (1st Pass 완료)

{json.dumps(article, ensure_ascii=False, indent=2)}

## 편집장 지시 — 이것들이 기사에 있어야 한다

기사 등급: {grade}

### structural_info (핵심 정보 — 삭제 금지 항목):
{json.dumps(structural_info, ensure_ascii=False) if structural_info else "(없음)"}

### domestic_angle (국내 관점):
{domestic_angle or "(없음)"}

### evidence (근거):
{json.dumps(evidence, ensure_ascii=False) if evidence else "(없음)"}

## 원본 데이터 (삽입 시 여기서 팩트를 가져와라)

{original_data[:6000]}

위 슬롯을 하나씩 검증하고, 누락된 것만 삽입하라."""

    response = await _call_llm(STRUCTURE_VALIDATOR_SYSTEM, user_prompt, temperature=0.15)
    validated = _extract_json(response)

    slot_results = validated.get("slot_results", {})
    inserted = sum(1 for v in slot_results.values() if "INSERTED" in str(v))
    not_found = sum(1 for v in slot_results.values() if "NOT_FOUND" in str(v))
    logger.info(
        "[구조검증] grade=%s, PASS=%d, INSERTED=%d, NOT_FOUND=%d",
        grade,
        sum(1 for v in slot_results.values() if v == "PASS"),
        inserted,
        not_found,
    )
    return validated


# ══════════════════════════════════════════════
# Agent 4: 편집자 — 최종 정제
# ══════════════════════════════════════════════

COPY_EDITOR_SYSTEM = """당신은 의약품 전문 매체의 최종 편집자입니다.

## 편집 기준

### 제목-리드-본문 메시지 일치
제목이 말하는 것, 리드가 말하는 것, 본문이 전개하는 것이 하나의 메시지를 향해야 합니다.
제목은 세게, 리드는 팩트로, 본문은 깊이로.

### 헤드라인
- 25자 이내
- 숫자 1개 이상 포함
- 핵심 이슈가 바로 보여야 함
- 예시: "PMDA 3월 승인 20건, 희귀·항암 집중"
- 예시: "국회 4월 보건 법안 15건, 의료법 개정 집중"

### 부제
- 40자 이내
- 헤드라인의 보완 정보

### 본문 흐름
- 리드 → 사례 → 맥락 → 영향 → 마무리 순서 확인
- 단락 간 자연스러운 연결 ("이에 따라", "한편", "반면")
- 사실→의미 흐름 (사실만 나열하면 수정)

### 해석 톤 규칙
- "기준선이다", "좌우한다", "변수가 된다" 같은 단정은 해석이지 사실이 아님
- 해석 문장은 "~로 거론된다", "~가능성이 있다", "~관찰 포인트다"로 톤을 낮출 것
- 가격·수치가 다른 제품의 '기준'이 된다고 단정하지 말 것 — "비교 참고점으로 언급된다" 수준

### 분량
- 800~1200자
- 너무 짧으면 사례/맥락 보강 지시
- 너무 길면 중복 삭제

## 출력
최종 기사:
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "...",
  "editor_note": "편집 포인트 1줄 요약"
}
```"""


async def agent_copy_editor(article: dict) -> dict:
    """Agent 4: 최종 편집 — 메시지 일치 + 흐름 + 분량"""
    user_prompt = f"""다음 기사를 최종 편집해주세요.

{json.dumps(article, ensure_ascii=False, indent=2)}

제목-리드-본문의 메시지가 일치하는지 확인하고, 흐름을 다듬어주세요.
800~1200자 분량으로 조절해주세요."""

    response = await _call_llm(COPY_EDITOR_SYSTEM, user_prompt, temperature=0.2)
    final = _extract_json(response)
    logger.info("[편집자] 최종: %s", final.get("headline", "")[:30])
    return final


# ══════════════════════════════════════════════
# 전체 파이프라인
# ══════════════════════════════════════════════

async def generate_articles(
    signals: dict[str, list[dict]],
) -> list[dict]:
    """5-Agent 기사 생성 파이프라인 v3 (2-Pass).

    흐름: 편집장 → 기자 → 팩트체커 → 구조검증기(2nd Pass) → 편집자
    - 기존 3회 보강 루프 제거
    - 구조검증기가 슬롯 단위로 누락 검증+삽입
    - 삽입 불가 시 등급 다운그레이드

    Args:
        signals: extract_signals()의 결과

    Returns:
        최종 기사 리스트
    """
    from regscan.stream.intelligence_signals import format_for_prompt

    from regscan.article.guardrails import (
        filter_signals, dedupe_stories, post_process_article,
        validate_article_grounding,
    )

    logger.info("=== 기사 생성 파이프라인 v3 (2-Pass) 시작 ===")

    # 엔리칭: API로 시그널에 취재 컨텍스트 추가
    try:
        from regscan.article.enrichment import enrich_signals
        signals = await enrich_signals(signals)
        logger.info("[엔리칭] 시그널 컨텍스트 보강 완료")
    except Exception as e:
        logger.warning("[엔리칭] 실패, 원본 시그널로 진행: %s", e)

    # 전처리: 시그널 5건 미만 소스 제거
    filtered = filter_signals(signals)
    if not filtered:
        logger.warning("전처리 후 기사 가치 있는 소스 없음")
        return []
    logger.info("[전처리] %d → %d 소스", len(signals), len(filtered))

    # Agent 1: 편집장
    stories = await agent_editor_chief(filtered)
    if not stories:
        logger.warning("편집장이 스토리를 선별하지 않음")
        return []

    # 중간검증: 같은 소스 중복 제거
    stories = dedupe_stories(stories)

    # 법안 고정 슬롯: 편집장이 ASSEMBLY_BILL을 안 골랐으면 강제 추가
    _assembly_aliases = {"ASSEMBLY_BILL", "KOREA_LEGISLATION", "ASSEMBLY", "LEGISLATION"}
    has_assembly = any(
        any(src in _assembly_aliases for src in s.get("sources_used", []))
        for s in stories
    )
    if not has_assembly and "ASSEMBLY_BILL" in filtered:
        # 최근 법안 중 제안이유가 있는 것만 후보
        assembly_sigs = filtered["ASSEMBLY_BILL"]
        top_bills = [
            s for s in assembly_sigs
            if s.get("proposal_reason") or s.get("statute_articles")
        ][:3]
        if top_bills:
            bill_titles = ", ".join(b.get("title", "")[:30] for b in top_bills)
            stories.append({
                "story_id": len(stories) + 1,
                "article_type": "regulation",
                "grade": "B",
                "grade_reason": "법안 고정 슬롯 — 편집장 미선택 보완",
                "read_reason": "최근 발의된 보건의료 법안 동향",
                "direction": "최근 발의 법안의 핵심 조문과 영향을 정리",
                "core_message": f"최근 보건의료 법안: {bill_titles}",
                "headline_draft": "보건의료 법안 동향",
                "domestic_angle": "국내 의료기관·제약사에 직접 영향",
                "sources_used": ["ASSEMBLY_BILL"],
                "publishable": "가능",
                "priority": "medium",
            })
            logger.info("[법안 고정] 편집장 미선택 → 법안 스토리 강제 추가")

    logger.info("[중간검증] %d개 스토리 확정", len(stories))

    articles = []
    for story in stories:
        # 편집장 판정: "불가" 또는 D등급이면 스킵
        publishable = story.get("publishable", "가능")
        grade = story.get("grade", "A")
        if publishable == "불가" or grade == "D":
            logger.info(
                "  기사 #%d 스킵 (등급=%s, 판정=%s): %s",
                story.get("story_id", 0), grade, publishable,
                story.get("publishable_reason", story.get("grade_reason", "")),
            )
            continue

        try:
            # 원본 데이터 (팩트체크 + 구조검증용)
            # 편집장이 소스명을 다르게 쓰는 경우 대비 alias 매핑
            _SOURCE_ALIAS = {
                "KOREA_LEGISLATION": "ASSEMBLY_BILL",
                "ASSEMBLY": "ASSEMBLY_BILL",
                "LEGISLATION": "ASSEMBLY_BILL",
                "MFDS": "MFDS_PRESS",
                "MFDS_SAFETY": "MFDS_SAFETY_LETTER",
                "KHIDI": "KHIDI_PHARMA_NEWS",
                "KHIDI_NEWS": "KHIDI_PHARMA_NEWS",
                "KHIDI_GLOBAL": "KHIDI_GLOBAL_INFO",
                "GNW": "GNW_PRESS",
                "GLOBENEWSWIRE": "GNW_PRESS",
                "PMDA": "PMDA_REVIEW",
                "DART": "DART_DISCLOSURE",
                "KIPRIS": "KIPRIS_PATENT",
                "MOHW": "MOHW_HEALTH_INSURANCE",
                "NICE": "NICE_TA",
            }
            sources_used = story.get("sources_used", [])
            original_data = ""
            seen_sources: set[str] = set()
            for src in sources_used:
                resolved = _SOURCE_ALIAS.get(src, src)
                if resolved in filtered and resolved not in seen_sources:
                    original_data += format_for_prompt(resolved, filtered[resolved]) + "\n"
                    seen_sources.add(resolved)
                elif src in filtered and src not in seen_sources:
                    original_data += format_for_prompt(src, filtered[src]) + "\n"
                    seen_sources.add(src)

            # ── 1st Pass: 기자 → 팩트체커 ──
            draft = await agent_reporter(story, filtered)
            checked = await agent_fact_checker(draft, original_data)
            logger.info(
                "  기사 #%d 1st Pass 완료 (corrections=%d)",
                story.get("story_id", 0),
                len(checked.get("corrections", [])),
            )

            # ── 2nd Pass: 구조검증기 ──
            validated = await agent_structure_validator(checked, story, original_data)
            slot_results = validated.get("slot_results", {})

            # 등급 다운그레이드 판단: A등급에서 핵심 슬롯 NOT_FOUND 2개 이상
            if grade == "A":
                critical_slots = ["structural_info", "domestic_angle", "evidence"]
                not_found_count = sum(
                    1 for s in critical_slots
                    if "NOT_FOUND" in str(slot_results.get(s, ""))
                )
                if not_found_count >= 2:
                    grade = "B"
                    story["grade"] = "B"
                    logger.info(
                        "  기사 #%d A→B 다운그레이드 (NOT_FOUND=%d/3)",
                        story.get("story_id", 0), not_found_count,
                    )

            # ── 편집 + 후처리 ──
            final = post_process_article(await agent_copy_editor(validated))
            grounding_issues = validate_article_grounding(story, final, original_data)
            if grounding_issues:
                logger.warning(
                    "  기사 #%d 근거 불일치 탐지: %s",
                    story.get("story_id", 0),
                    "; ".join(grounding_issues),
                )

                # 날짜/조문 불일치 → 팩트 교정 재작성 1회
                has_factual_issue = any(
                    k in issue for issue in grounding_issues
                    for k in ("unsupported_dates", "unsupported_statutes")
                )
                if has_factual_issue:
                    logger.info(
                        "  기사 #%d 팩트 교정 재작성 시작",
                        story.get("story_id", 0),
                    )
                    # 기자에게 구체적 오류를 피드백으로 전달
                    story["_rewrite_feedback"] = [
                        f"팩트 교정: {issue} — 이 정보는 원본 데이터에 없다. "
                        "원본 데이터에 실제로 있는 날짜/조문/단계만 사용해서 다시 써라. "
                        "원본에 없으면 해당 내용을 빼라."
                        for issue in grounding_issues
                    ]
                    # 1st pass 재실행
                    draft2 = await agent_reporter(story, filtered)
                    checked2 = await agent_fact_checker(draft2, original_data)
                    validated2 = await agent_structure_validator(checked2, story, original_data)
                    slot_results = validated2.get("slot_results", {})
                    final = post_process_article(await agent_copy_editor(validated2))

                    # 재검증
                    grounding_issues2 = validate_article_grounding(story, final, original_data)
                    if grounding_issues2 and any(
                        k in issue for issue in grounding_issues2
                        for k in ("unsupported_dates", "unsupported_statutes")
                    ):
                        logger.warning(
                            "  기사 #%d 재작성 후에도 팩트 불일치 — 발행 보류",
                            story.get("story_id", 0),
                        )
                        continue
                    elif grounding_issues2:
                        final["_grounding_issues"] = grounding_issues2
                    logger.info(
                        "  기사 #%d 팩트 교정 완료",
                        story.get("story_id", 0),
                    )
                else:
                    # 범위 불일치 등 나머지는 등급 강등
                    if grade == "A":
                        grade = "B"
                        story["grade"] = "B"
                    elif grade == "B":
                        grade = "C"
                        story["grade"] = "C"
                    final["_grounding_issues"] = grounding_issues

            body_len = len(final.get("body", ""))
            logger.info("  기사 #%d 2-Pass 완료: %d자, grade=%s",
                        story.get("story_id", 0), body_len, grade)

            # 최소 길이 미달 시 등급 다운그레이드
            min_len = {"A": 700, "B": 400}.get(grade, 0)
            if min_len and body_len < min_len:
                if grade == "A":
                    grade = "B"
                    story["grade"] = "B"
                    logger.info("  기사 #%d A→B (길이 %d < 700)", story.get("story_id", 0), body_len)
                elif grade == "B":
                    grade = "C"
                    story["grade"] = "C"
                    logger.info("  기사 #%d B→C (길이 %d < 400)", story.get("story_id", 0), body_len)

            final["story_id"] = story.get("story_id", 0)
            final["core_message"] = story.get("core_message", "")
            final["sources_used"] = sources_used
            final["priority"] = story.get("priority", "medium")
            final["grade"] = grade
            final["slot_results"] = slot_results
            final["generated_at"] = datetime.now().isoformat()

            articles.append(final)
            logger.info(
                "  기사 #%d 완성: %s",
                story.get("story_id", 0),
                final.get("headline", "")[:40],
            )

        except Exception as e:
            logger.warning(
                "  기사 #%d 생성 실패: %s",
                story.get("story_id", 0), e,
            )

    logger.info("=== 기사 생성 완료: %d건 ===", len(articles))
    return articles
