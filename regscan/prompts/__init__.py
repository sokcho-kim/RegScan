"""공통 프롬프트 빌딩 블록 패키지

drug-briefing과 stream-briefing이 공유하는 기반 요소를 제공한다.
각 시스템은 여기서 블록을 import하여 자체 시스템 프롬프트를 조립한다.
"""

from regscan.prompts.shared import (  # noqa: F401
    PERSONA,
    TIME_REASONING_RULES,
    ANTI_PATTERN_TABLE,
    DOMAIN_KNOWLEDGE_REIMBURSEMENT,
    DOMAIN_KNOWLEDGE_REGULATORY,
    LIFECYCLE_BRANCHES,
    EXECUTIVE_TONE_RULES,
    OUTPUT_FORMAT_RULES,
    build_system_prompt,
)
