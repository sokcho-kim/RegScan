"""OMOP RxNorm 기반 decomposer 사전 검증 스크립트

CONCEPT.csv에서 RxNorm Ingredient / Precise Ingredient / Dose Form을 추출하고
decomposer.py의 SALT_FORMS, REF_NORMALIZATION_MAP, FORMULATION_TOKENS를 교차 검증.

검증 항목:
  1. SALT_FORMS — RxNorm PI→Ingredient 이름 diff에서 추출한 salt와 비교
  2. REF_NORMALIZATION_MAP — 치환 대상이 실제 RxNorm에 존재하는지
  3. FORMULATION_TOKENS — RxNorm Dose Form 키워드와 비교

Usage:
    python scripts/validate_decomposer_vocab.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from regscan.map.decomposer import (
    FORMULATION_TOKENS,
    REF_NORMALIZATION_MAP,
    SALT_FORMS,
)

CONCEPT_PATH = ROOT / "data" / "omop" / "CONCEPT.csv"

# ════════════════════════════════════════════════════════════════════
# 1. CONCEPT.csv 스트리밍 로드
# ════════════════════════════════════════════════════════════════════


def load_rxnorm_concepts() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """CONCEPT.csv에서 RxNorm Ingredient / Precise Ingredient / Dose Form 추출.

    Returns:
        (ingredients, precise_ingredients, dose_forms) — 각 {concept_id: concept_name}
    """
    ingredients: dict[str, str] = {}
    precise_ingredients: dict[str, str] = {}
    dose_forms: dict[str, str] = {}

    print(f"[1/3] Loading {CONCEPT_PATH.name} (streaming)...")
    with open(CONCEPT_PATH, "r", encoding="utf-8") as f:
        header = f.readline()  # skip header
        cols = header.strip().split("\t")
        idx_id = cols.index("concept_id")
        idx_name = cols.index("concept_name")
        idx_vocab = cols.index("vocabulary_id")
        idx_class = cols.index("concept_class_id")

        for lineno, line in enumerate(f, start=2):
            parts = line.split("\t")
            if len(parts) <= max(idx_id, idx_name, idx_vocab, idx_class):
                continue
            vocab = parts[idx_vocab]
            if vocab != "RxNorm" and vocab != "RxNorm Extension":
                continue
            cls = parts[idx_class]
            cid = parts[idx_id]
            name = parts[idx_name]
            if cls == "Ingredient":
                ingredients[cid] = name
            elif cls == "Precise Ingredient":
                precise_ingredients[cid] = name
            elif cls == "Dose Form":
                dose_forms[cid] = name

            if lineno % 1_000_000 == 0:
                print(f"  ... {lineno:,} lines processed")

    print(
        f"  → Ingredient: {len(ingredients):,} | "
        f"Precise Ingredient: {len(precise_ingredients):,} | "
        f"Dose Form: {len(dose_forms):,}"
    )
    return ingredients, precise_ingredients, dose_forms


# ════════════════════════════════════════════════════════════════════
# 2. Salt 추출 (PI name - Ingredient name = salt)
# ════════════════════════════════════════════════════════════════════


def extract_salts(
    ingredients: dict[str, str],
    precise_ingredients: dict[str, str],
) -> tuple[Counter[str], list[str]]:
    """Precise Ingredient 이름에서 Ingredient 이름을 빼서 salt 토큰 추출.

    예: "defactinib hydrochloride" - "defactinib" = "hydrochloride"

    Returns:
        (salt_counter, unresolved_pi_names)
    """
    print("[2/3] Extracting salts from Precise Ingredient names...")
    ing_lower_set: set[str] = {name.lower() for name in ingredients.values()}

    salt_counter: Counter[str] = Counter()
    unresolved: list[str] = []

    for pi_name in precise_ingredients.values():
        pi_lower = pi_name.lower().strip()

        # longest ingredient match first
        best_ing: str | None = None
        best_salt: str | None = None

        for ing in ing_lower_set:
            if pi_lower.startswith(ing + " "):
                remainder = pi_lower[len(ing) :].strip()
                if best_ing is None or len(ing) > len(best_ing):
                    best_ing = ing
                    best_salt = remainder

        if best_ing and best_salt:
            salt_counter[best_salt] += 1
        else:
            unresolved.append(pi_name)

    resolved = sum(salt_counter.values())
    print(
        f"  → Resolved: {resolved:,} PI | "
        f"Unresolved: {len(unresolved):,} PI | "
        f"Unique salts: {len(salt_counter):,}"
    )
    return salt_counter, unresolved


# ════════════════════════════════════════════════════════════════════
# 3. 검증 리포트
# ════════════════════════════════════════════════════════════════════


def validate_salts(salt_counter: Counter[str]) -> None:
    """SALT_FORMS vs RxNorm salt 교차 검증."""
    print("\n" + "=" * 70)
    print("SALT_FORMS 검증 (decomposer.py vs RxNorm)")
    print("=" * 70)

    rxnorm_salts = set(salt_counter.keys())
    our_salts = {s.lower() for s in SALT_FORMS}

    common = our_salts & rxnorm_salts
    missing_from_us = rxnorm_salts - our_salts
    extra_in_us = our_salts - rxnorm_salts

    print(f"\n  공통 (양쪽 다 있음): {len(common)}")
    print(f"  RxNorm에만 있음 (우리 사전 누락 후보): {len(missing_from_us)}")
    print(f"  우리에만 있음 (RxNorm 미등재): {len(extra_in_us)}")

    if missing_from_us:
        print(f"\n  ── RxNorm에만 있는 salt (빈도순, 상위 30) ──")
        for salt, cnt in sorted(
            ((s, salt_counter[s]) for s in missing_from_us),
            key=lambda x: -x[1],
        )[:30]:
            print(f"    {cnt:4d}x  {salt}")

    if extra_in_us:
        print(f"\n  ── 우리에만 있는 salt (RxNorm 미등재) ──")
        for salt in sorted(extra_in_us):
            print(f"    - {salt}")


def validate_normalization_map(salt_counter: Counter[str]) -> None:
    """REF_NORMALIZATION_MAP의 key(변이형)와 value(표준형) 모두 RxNorm에 존재하는지."""
    print("\n" + "=" * 70)
    print("REF_NORMALIZATION_MAP 검증")
    print("=" * 70)

    rxnorm_salts = set(salt_counter.keys())
    # RxNorm salt에서 개별 토큰도 추출 (compound salts like "hydrochloride monohydrate")
    rxnorm_tokens: set[str] = set()
    for s in rxnorm_salts:
        rxnorm_tokens.update(s.lower().split())
    all_rxnorm = rxnorm_salts | rxnorm_tokens

    print(f"\n  {'Key (변이형)':<30} {'Value (표준형)':<20} {'Key in RxNorm':<15} {'Value in RxNorm'}")
    print(f"  {'─'*30} {'─'*20} {'─'*15} {'─'*15}")

    for key, val in sorted(REF_NORMALIZATION_MAP.items()):
        key_found = "OK" if key in all_rxnorm else "--"
        val_found = "OK" if val in all_rxnorm else "--"
        print(f"  {key:<30} {val:<20} {key_found:<15} {val_found}")


def validate_formulations(dose_forms: dict[str, str]) -> None:
    """FORMULATION_TOKENS vs RxNorm Dose Form 교차 검증."""
    print("\n" + "=" * 70)
    print("FORMULATION_TOKENS 검증 (decomposer.py vs RxNorm Dose Form)")
    print("=" * 70)

    df_names = sorted({name.lower() for name in dose_forms.values()})

    # 우리 토큰이 RxNorm Dose Form에 포함되는지
    print(f"\n  RxNorm Dose Form 총: {len(df_names)}")
    print(f"  우리 FORMULATION_TOKENS 총: {len(FORMULATION_TOKENS)}")

    matched: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for token in FORMULATION_TOKENS:
        t = token.lower()
        hits = [df for df in df_names if t in df]
        if hits:
            matched[token] = hits[:3]
        else:
            unmatched.append(token)

    print(f"\n  RxNorm에서 확인됨: {len(matched)}")
    print(f"  RxNorm에 없음 (마스터 고유): {len(unmatched)}")

    if matched:
        print(f"\n  ── RxNorm에서 확인된 토큰 ──")
        for token, hits in sorted(matched.items()):
            examples = ", ".join(hits[:2])
            print(f"    OK {token:<35} -> {examples}")

    if unmatched:
        print(f"\n  ── RxNorm에 없는 토큰 (마스터 고유 or 검토 필요) ──")
        for token in unmatched:
            print(f"    -- {token}")

    # RxNorm Dose Form에서 추출 가능한 키워드 중 우리가 놓친 것
    print(f"\n  ── RxNorm Dose Form에서 관련 키워드 후보 (참고용) ──")
    # "release" 관련, 물리형태 관련 등
    relevant_keywords = {
        "extended", "delayed", "sustained", "modified", "controlled",
        "chewable", "dispersible", "effervescent", "sublingual",
        "lyophilized", "liposomal", "coated", "enteric",
        "granules", "powder", "tablet", "capsule", "suspension",
        "solution", "cream", "gel", "patch", "injectable",
        "implant", "spray", "foam", "emulsion", "pellet",
    }
    for kw in sorted(relevant_keywords):
        hits = [df for df in df_names if kw in df]
        if hits:
            in_ours = "OK" if any(kw in t.lower() for t in FORMULATION_TOKENS) else "  "
            print(f"    {in_ours} {kw:<20} ({len(hits)} dose forms)")


def print_summary(
    salt_counter: Counter[str],
    unresolved_pi: list[str],
    dose_forms: dict[str, str],
) -> None:
    """최종 요약."""
    rxnorm_salts = set(salt_counter.keys())
    our_salts = {s.lower() for s in SALT_FORMS}
    missing_salts = rxnorm_salts - our_salts

    df_names_lower = {name.lower() for name in dose_forms.values()}
    our_tokens_lower = {t.lower() for t in FORMULATION_TOKENS}
    matched_tokens = {t for t in our_tokens_lower if any(t in df for df in df_names_lower)}

    print("\n" + "=" * 70)
    print("요약")
    print("=" * 70)
    print(f"""
  SALT_FORMS
    현재: {len(SALT_FORMS)}개
    RxNorm 확인: {len(our_salts & rxnorm_salts)}개
    RxNorm 누락 후보: {len(missing_salts)}개 (빈도 ≥ 3: {sum(1 for s in missing_salts if salt_counter[s] >= 3)})

  REF_NORMALIZATION_MAP
    현재: {len(REF_NORMALIZATION_MAP)}개 치환 규칙

  FORMULATION_TOKENS
    현재: {len(FORMULATION_TOKENS)}개
    RxNorm Dose Form에서 확인: {len(matched_tokens)}개
    마스터 고유: {len(our_tokens_lower - matched_tokens)}개

  Precise Ingredient 미분해: {len(unresolved_pi)}건 / {len(unresolved_pi) + sum(salt_counter.values())}건
""")


# ════════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════════

def main() -> None:
    if not CONCEPT_PATH.exists():
        print(f"ERROR: {CONCEPT_PATH} not found.")
        print("  → Athena에서 RxNorm vocabulary 다운로드 후 data/omop/에 배치하세요.")
        sys.exit(1)

    ingredients, precise_ingredients, dose_forms = load_rxnorm_concepts()
    salt_counter, unresolved_pi = extract_salts(ingredients, precise_ingredients)

    validate_salts(salt_counter)
    validate_normalization_map(salt_counter)
    validate_formulations(dose_forms)
    print_summary(salt_counter, unresolved_pi, dose_forms)


if __name__ == "__main__":
    main()
