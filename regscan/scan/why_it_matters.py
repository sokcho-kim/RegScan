"""why_it_matters 생성기 - LLM + 템플릿 폴백"""

import logging
from typing import Any, Optional

from regscan.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# 템플릿 정의
# =============================================================================

TEMPLATES = {
    # submission_type 기반
    "ORIG": "국내 도입 시 {domain} 분야 급여기준 논의 예상",
    "SUPPL": "기존 승인 약제의 적응증 확대, 국내 허가 변경 가능",
    "ABBREV": "제네릭 승인으로 국내 동일 성분 약가 인하 압력 예상",
    "NDA": "신약 승인으로 국내 허가 심사 및 급여 검토 촉발 예상",
    "BLA": "생물학적 제제 승인, 국내 바이오의약품 급여 정책 참고",

    # 약리학적 분류 기반
    "oncology": "항암제 급여 확대 및 신속심사 대상 검토 가능",
    "rare_disease": "희귀질환 급여 특례 적용 검토 촉발 전망",
    "cardiovascular": "심혈관계 약제 급여기준 재검토 가능성",
    "diabetes": "당뇨병 치료제 급여 범위 확대 논의 예상",
    "obesity": "비만 치료제 급여 적용 논의 본격화 가능",
    "immunology": "면역질환 치료제 급여기준 변경 검토 예상",
    "neurology": "신경계 약제 급여 확대 논의 촉발 가능",
    "infectious": "감염병 치료제 급여 및 비축 정책 검토 예상",

    # 기본값
    "default": "국내 허가 및 급여기준 검토에 참고 자료로 활용 예상",
}

# 적응증/분류 키워드 → 템플릿 키 매핑
KEYWORD_MAP = {
    # Oncology
    "cancer": "oncology",
    "tumor": "oncology",
    "leukemia": "oncology",
    "lymphoma": "oncology",
    "carcinoma": "oncology",
    "melanoma": "oncology",
    "oncolog": "oncology",
    "antineoplastic": "oncology",

    # Rare disease
    "orphan": "rare_disease",
    "rare": "rare_disease",

    # Cardiovascular
    "heart": "cardiovascular",
    "cardiac": "cardiovascular",
    "hypertension": "cardiovascular",
    "cholesterol": "cardiovascular",

    # Diabetes
    "diabetes": "diabetes",
    "glycemic": "diabetes",
    "insulin": "diabetes",
    "glp-1": "diabetes",
    "sglt": "diabetes",

    # Obesity
    "obesity": "obesity",
    "weight": "obesity",
    "bariatric": "obesity",

    # Immunology
    "immune": "immunology",
    "autoimmune": "immunology",
    "rheumatoid": "immunology",
    "psoriasis": "immunology",

    # Neurology
    "neuro": "neurology",
    "alzheimer": "neurology",
    "parkinson": "neurology",
    "epilepsy": "neurology",
    "seizure": "neurology",

    # Infectious
    "antiviral": "infectious",
    "antibiotic": "infectious",
    "antimicrobial": "infectious",
    "hiv": "infectious",
    "hepatitis": "infectious",
}


# =============================================================================
# LLM 프롬프트
# =============================================================================

LLM_PROMPT = """당신은 한국 의료/보험 규제 전문가입니다.

FDA가 다음 의약품을 승인했습니다:
- 약제명: {brand_name} ({generic_name})
- 적응증/분류: {indication}
- 제약사: {sponsor}
- 승인 유형: {submission_type}

이 승인이 **한국 의료/보험 시장**에 미칠 영향을 1문장으로 설명하세요.

규칙:
1. 80자 이내 (한글 기준)
2. "국내", "급여", "허가", "도입" 등 한국 관점 키워드 포함
3. 구체적 영향 명시 (예: "급여 확대 논의", "허가 심사 가속화")
4. 불확실한 경우 "~가능성", "~예상", "~전망" 표현 사용
5. 문장 끝에 마침표 없이

예시:
- 국내 도입 시 비만 치료제 급여기준 확대 논의 예상
- 동일 계열 국내 허가 약제 적응증 추가 심사 가속화 가능
- 희귀질환 급여 특례 적용 검토 촉발 전망"""


# =============================================================================
# Generator 클래스
# =============================================================================

class WhyItMattersGenerator:
    """why_it_matters 생성기"""

    def __init__(
        self,
        use_llm: bool = True,
        openai_api_key: Optional[str] = None,
    ):
        self.use_llm = use_llm and settings.USE_LLM
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY
        self._openai_client = None

    async def generate(self, data: dict[str, Any]) -> tuple[str, str]:
        """
        why_it_matters 생성

        Args:
            data: 파싱된 FDA 데이터

        Returns:
            tuple: (생성된 텍스트, 사용된 방법 'llm' or 'template')
        """
        # LLM 시도
        if self.use_llm and self.openai_api_key:
            try:
                text = await self._generate_with_llm(data)
                if text:
                    return (text, "llm")
            except Exception as e:
                logger.warning(f"LLM 생성 실패, 템플릿 폴백: {e}")

        # 템플릿 폴백
        text = self._generate_with_template(data)
        return (text, "template")

    async def _generate_with_llm(self, data: dict[str, Any]) -> Optional[str]:
        """LLM으로 생성"""
        try:
            import openai

            if self._openai_client is None:
                self._openai_client = openai.AsyncOpenAI(api_key=self.openai_api_key)

            # 적응증 정보 구성
            indication_parts = []
            if data.get("pharm_class"):
                indication_parts.extend(data["pharm_class"][:3])
            if data.get("route"):
                indication_parts.extend(data["route"][:2])
            indication = ", ".join(indication_parts) if indication_parts else "정보 없음"

            prompt = LLM_PROMPT.format(
                brand_name=data.get("brand_name", ""),
                generic_name=data.get("generic_name", ""),
                indication=indication,
                sponsor=data.get("sponsor", ""),
                submission_type=data.get("submission_type", ""),
            )

            response = await self._openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
                timeout=settings.LLM_TIMEOUT,
            )

            if not response.choices:
                logger.warning("OpenAI API 응답에 choices가 비어 있음")
                return None

            text = response.choices[0].message.content.strip()
            # 80자 제한
            return text[:80] if len(text) > 80 else text

        except ImportError:
            logger.warning("openai 패키지가 설치되지 않음")
            return None
        except Exception as e:
            logger.warning(f"OpenAI API 호출 실패: {e}")
            return None

    def _generate_with_template(self, data: dict[str, Any]) -> str:
        """템플릿으로 생성"""
        submission_type = data.get("submission_type", "")
        pharm_class = data.get("pharm_class", [])
        generic_name = data.get("generic_name", "").lower()

        # 도메인 추론
        domain = self._infer_domain(pharm_class, generic_name)

        # 1. submission_type 매칭
        if submission_type in TEMPLATES:
            return TEMPLATES[submission_type].format(domain=domain)

        # 2. 약리학적 분류 키워드 매칭
        search_text = " ".join(pharm_class).lower() + " " + generic_name

        for keyword, template_key in KEYWORD_MAP.items():
            if keyword in search_text:
                return TEMPLATES[template_key]

        # 3. 기본값
        return TEMPLATES["default"]

    def _infer_domain(
        self,
        pharm_class: list[str],
        generic_name: str,
    ) -> str:
        """약리학적 분류에서 도메인 추론"""
        search_text = " ".join(pharm_class).lower() + " " + generic_name

        for keyword, template_key in KEYWORD_MAP.items():
            if keyword in search_text:
                # 한글 도메인명으로 변환
                domain_map = {
                    "oncology": "항암",
                    "rare_disease": "희귀질환",
                    "cardiovascular": "심혈관",
                    "diabetes": "당뇨",
                    "obesity": "비만",
                    "immunology": "면역",
                    "neurology": "신경계",
                    "infectious": "감염",
                }
                return domain_map.get(template_key, "의약품")

        return "의약품"


# =============================================================================
# 편의 함수
# =============================================================================

async def generate_why_it_matters(
    data: dict[str, Any],
    use_llm: bool = True,
) -> tuple[str, str]:
    """why_it_matters 생성 (편의 함수)"""
    generator = WhyItMattersGenerator(use_llm=use_llm)
    return await generator.generate(data)
