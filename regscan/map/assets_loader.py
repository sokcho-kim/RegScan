"""Decomposer 사전 로더 — JSON → frozenset/tuple 캐싱 + regex 컴파일

최초 import 시 1회 로드, 이후 모듈 레벨 캐싱.
데이터 갱신 시 JSON만 수정하면 코드 변경 불필요.

갱신 주기: HIRA 마스터 연 1회 (10월), RxNorm 월 1회 → 사전 재검증은 연 1회 권장.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _load_json(filename: str) -> list | dict:
    path = _ASSETS_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ════════════════════════════════════════════════════════════════════
# 사전 로드 (모듈 최초 import 시 1회)
# ════════════════════════════════════════════════════════════════════

SALT_FORMS: frozenset[str] = frozenset(_load_json("salt_forms.json"))

REF_NORMALIZATION_MAP: dict[str, str] = _load_json("ref_normalization_map.json")

# longest-match-first 순서 유지
FORMULATION_TOKENS: tuple[str, ...] = tuple(
    sorted(_load_json("formulation_tokens.json"), key=len, reverse=True)
)


# ════════════════════════════════════════════════════════════════════
# 정규식 컴파일 (사전 로드 후 1회)
# ════════════════════════════════════════════════════════════════════

# Formulation (longest-match-first, 문자열 끝)
RE_FORMULATION = re.compile(
    r"\s+(" + "|".join(re.escape(f) for f in FORMULATION_TOKENS) + r")\s*$",
    re.IGNORECASE,
)

# Salt (longest-match-first, 문자열 끝)
# REF_NORMALIZATION_MAP 키도 포함
ALL_SALT_TOKENS: frozenset[str] = SALT_FORMS | frozenset(REF_NORMALIZATION_MAP.keys())

RE_SALT = re.compile(
    r"\s+(" + "|".join(
        re.escape(s) for s in sorted(ALL_SALT_TOKENS, key=len, reverse=True)
    ) + r")\s*$",
    re.IGNORECASE,
)
