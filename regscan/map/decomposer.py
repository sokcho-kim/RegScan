"""성분명 무손실 분해(Decomposition) 파이프라인

원본 텍스트를 [base_inn, salt, formulation, strength] 4개 컬럼으로 쪼개되
정보를 버리지 않는다.  "정보는 이동하되 삭제되지 않는다."

엔지니어링 정책:
  - Level 1 (제형): 삭제 금지 → formulation 컬럼으로 분리
  - Level 2 (염):  삭제 금지 → ref_normalization_map 기반 표준명 치환 후 salt 컬럼
  - Level 3 (함량): 삭제 금지 → strength 컬럼으로 파싱
  - Level 4 (첫 단어 매칭): 불허

사전 데이터: regscan/map/assets/*.json (assets_loader.py에서 로드)
"""

from __future__ import annotations

__version__ = "1.0.0"

import re
from dataclasses import dataclass
from typing import Optional

from regscan.map.assets_loader import (
    SALT_FORMS,
    REF_NORMALIZATION_MAP,
    FORMULATION_TOKENS,
    RE_FORMULATION as _RE_FORMULATION,
    RE_SALT as _RE_SALT,
)


# ════════════════════════════════════════════════════════════════════
# 데이터클래스
# ════════════════════════════════════════════════════════════════════

@dataclass
class DecomposedIngredient:
    """성분명 분해 결과 — 원본 텍스트의 무손실 분해"""

    raw: str                              # 원본 그대로
    base_inn: str                         # 핵심 INN (소문자)
    salt: Optional[str] = None            # 표준화된 염 형태
    formulation: Optional[str] = None     # 제형 variant
    strength: Optional[str] = None        # 함량 ("42%", "10.7mg" 등)
    match_confidence: float = 1.0         # 분해 신뢰도 (0.0~1.0)

    @property
    def variant_key(self) -> str:
        """Base + Salt + Formulation → 약가 매칭용 키"""
        parts = [self.base_inn]
        if self.salt:
            parts.append(self.salt)
        if self.formulation:
            parts.append(self.formulation)
        return " ".join(parts)

    @property
    def base_key(self) -> str:
        """Base INN만 → 성분 동일성 확인용 키"""
        return self.base_inn

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "base_inn": self.base_inn,
            "salt": self.salt,
            "formulation": self.formulation,
            "strength": self.strength,
            "variant_key": self.variant_key,
            "base_key": self.base_key,
            "match_confidence": self.match_confidence,
        }


# ════════════════════════════════════════════════════════════════════
# 정규식 (컴파일 — 모듈 로드 시 1회)
# ════════════════════════════════════════════════════════════════════
# _RE_FORMULATION, _RE_SALT → assets_loader.py에서 import

# Step 1-a: 괄호 안 (as BASE DOSE) 패턴
#   "Bepotastine Besylate (as bepotastine 10.7mg)" → strength="10.7mg"
_RE_PAREN_AS_STRENGTH = re.compile(
    r"\s*\(as\s+[\w\s.,-]*?"
    r"(\d+\.?\d*\s*(?:mg|g|mcg|µg|iu|ml|units?|%))"
    r"\s*\)",
    re.IGNORECASE,
)

# Step 1-b: 괄호 안 순수 농도 패턴
#   "Amino Acids(10%)" → strength="10%"
_RE_PAREN_STRENGTH = re.compile(
    r"\s*\((\d+\.?\d*\s*%)\)",
)

# Step 1-c: 후행 퍼센트
#   "Ascorbic Acid Granules 97%" → strength="97%"
_RE_TRAILING_PCT = re.compile(
    r"\s+(\d+\.?\d*\s*%)\s*$",
)

# Step 1-d: 선행 퍼센트 (드문 케이스)
#   "0.1% Cyanocobalamine Powder" → strength="0.1%"
_RE_LEADING_PCT = re.compile(
    r"^(\d+\.?\d*%)\s+",
)

# Step 1-e: 괄호 안 (as BASE) — 용량 없이 base만 있는 경우
#   "Afatinib Dimaleate (as afatinib)" → 제거만 (strength 아님)
_RE_PAREN_AS_PLAIN = re.compile(
    r"\s*\(as\s+[^)]+\)",
    re.IGNORECASE,
)

# Step 1-f: (micronized) 등 괄호 안 제형
_RE_PAREN_FORMULATION = re.compile(
    r"\s*\((micronized|enteric\s+coated|liposomal|lyophilized)\)",
    re.IGNORECASE,
)

# ════════════════════════════════════════════════════════════════════
# 메인 함수
# ════════════════════════════════════════════════════════════════════

def decompose_ingredient(raw_name: str) -> DecomposedIngredient:
    """성분명을 [base_inn, salt, formulation, strength]로 무손실 분해.

    역순 파싱: Strength → Formulation → Salt → Base INN
    모든 토큰은 4개 컬럼 중 하나에 귀속된다.

    Args:
        raw_name: MFDS ITEM_INGR_NAME 원본 (단일 성분)

    Returns:
        DecomposedIngredient
    """
    if not raw_name or not raw_name.strip():
        return DecomposedIngredient(raw=raw_name or "", base_inn="")

    raw = raw_name.strip()
    text = raw  # 작업용 복사본 (원본 보존)
    strength: Optional[str] = None
    formulation: Optional[str] = None
    salt: Optional[str] = None
    confidence = 1.0

    # ── Step 1: Strength 추출 ──

    # 1-a: (as BASE DOSE) — 용량 추출 후 괄호 전체 제거
    m = _RE_PAREN_AS_STRENGTH.search(text)
    if m:
        strength = m.group(1).strip()
        text = text[:m.start()] + text[m.end():]

    # 1-b: 괄호 안 순수 농도 (10%) — strength 아직 없을 때만
    if not strength:
        m = _RE_PAREN_STRENGTH.search(text)
        if m:
            strength = m.group(1).strip()
            text = text[:m.start()] + text[m.end():]

    # 1-c: 후행 퍼센트 — strength 아직 없을 때만
    if not strength:
        m = _RE_TRAILING_PCT.search(text)
        if m:
            strength = m.group(1).strip()
            text = text[:m.start()]

    # 1-d: 선행 퍼센트 — strength 아직 없을 때만
    if not strength:
        m = _RE_LEADING_PCT.match(text)
        if m:
            strength = m.group(1).strip()
            text = text[m.end():]

    # 1-e: (as BASE) 용량 없는 괄호 — 정보 이동 아닌 중복 제거
    #   "Afatinib Dimaleate (as afatinib)" → 괄호 안 base는 이미 base_inn에 귀속
    text = _RE_PAREN_AS_PLAIN.sub("", text)

    # 1-f: (micronized) 등 괄호 안 제형 → formulation으로 이동
    m = _RE_PAREN_FORMULATION.search(text)
    if m:
        formulation = m.group(1).strip().lower()
        text = text[:m.start()] + text[m.end():]

    # 나머지 괄호 내용 제거 (정보가 이미 다른 컬럼에 귀속된 후)
    text = re.sub(r"\s*\([^)]*\)", "", text)

    # ── Step 2: Formulation 추출 ──

    # 2-0: 선행 제형 (prefix 위치) — "Liposomal Doxorubicin" 등
    _prefix_forms = ("liposomal", "pegylated")
    text_lower_stripped = text.lower().strip()
    for pf in _prefix_forms:
        if text_lower_stripped.startswith(pf + " "):
            if formulation:
                formulation = f"{pf} {formulation}"
            else:
                formulation = pf
            text = text.strip()[len(pf):].strip()
            break

    # 2-1: 후행 제형 (괄호 밖, 문자열 끝) ──
    # 괄호 안에서 제형을 이미 추출했더라도, 문자열 끝에 추가 제형 토큰이 있을 수 있음
    # 예: "Fenofibrate Granule(Micronized)" → 괄호 안 micronized + 끝 granule
    text_lower = text.lower().strip()
    m = _RE_FORMULATION.search(text_lower)
    if m:
        trailing_form = m.group(1).strip().lower()
        text = text.strip()[:m.start()].strip()
        if formulation:
            # 괄호 안 제형 + 끝 제형 결합: "granule micronized"
            formulation = f"{trailing_form} {formulation}"
        else:
            formulation = trailing_form

    # 공백 정리
    text = " ".join(text.split()).strip()

    # ── Step 3: Salt 추출 (문자열 끝, 최대 2회 반복) ──
    # 예: "doxorubicin hydrochloride" → salt="hydrochloride", base="doxorubicin"
    # 예: "calcium folinate" → salt="calcium", base="folinate"... 이건 위험
    #   → salt 추출 후 base가 비어버리면 rollback
    salts_found: list[str] = []
    text_before_salt = text
    for _ in range(2):  # dimaleate 등 이중 염 대응
        m = _RE_SALT.search(text.lower())
        if not m:
            break
        matched_salt = m.group(1).strip().lower()
        # 표준명 치환
        normalized_salt = REF_NORMALIZATION_MAP.get(matched_salt, matched_salt)
        salts_found.append(normalized_salt)
        # text에서 제거
        cut_start = len(text) - (len(text.lower()) - m.start())
        text = text[:cut_start].strip()

    if salts_found:
        # base가 비어버리면 rollback (salt가 아니라 성분명 자체인 경우)
        remaining = " ".join(text.split()).strip()
        if remaining:
            salt = " ".join(reversed(salts_found))  # 원래 순서 복원
        else:
            # rollback
            text = text_before_salt
            salts_found = []

    # ── Step 4: Base INN 정리 ──
    base_inn = " ".join(text.lower().split()).strip()

    # 후행 하이픈/공백 정리
    base_inn = base_inn.rstrip(" -")

    # FDA 바이오의약품 4자리 접미사는 유지 (base_inn의 일부)
    # 예: "trastuzumab-dkst" → base_inn에 그대로 보존

    # ── 신뢰도 계산 ──
    # 분해 단계가 많을수록 약간 낮아짐
    parts_extracted = sum(1 for x in [salt, formulation, strength] if x)
    if parts_extracted == 0:
        confidence = 1.0   # 분해할 것 없음 = 원본이 곧 base_inn
    elif parts_extracted <= 2:
        confidence = 0.95
    else:
        confidence = 0.9

    return DecomposedIngredient(
        raw=raw,
        base_inn=base_inn,
        salt=salt,
        formulation=formulation,
        strength=strength,
        match_confidence=confidence,
    )


def batch_decompose(names: list[str]) -> list[DecomposedIngredient]:
    """여러 성분명 일괄 분해"""
    return [decompose_ingredient(name) for name in names]
