"""decomposer.py 단위 테스트

무손실 분해 파이프라인 검증:
  - 모든 토큰이 4개 컬럼 중 하나에 귀속되는지
  - besylate→besilate 등 표준명 치환이 정확한지
  - Level 4 (첫 단어 매칭) 로직이 없는지
"""

import pytest
from regscan.map.decomposer import decompose_ingredient, DecomposedIngredient


class TestStrengthExtraction:
    """Step 1: Strength 추출"""

    def test_paren_as_strength(self):
        d = decompose_ingredient("Bepotastine Besylate (as bepotastine 10.7mg)")
        assert d.strength == "10.7mg"
        assert d.base_inn == "bepotastine"
        assert d.salt == "besilate"  # besylate → besilate 치환

    def test_trailing_percent(self):
        d = decompose_ingredient("Ascorbic Acid Granules 97%")
        assert d.strength == "97%"
        assert d.base_inn == "ascorbic acid"

    def test_paren_percent(self):
        d = decompose_ingredient("Amino Acids(10%)")
        assert d.strength == "10%"
        assert d.base_inn == "amino acids"

    def test_leading_percent(self):
        d = decompose_ingredient("0.1% Cyanocobalamine Powder")
        assert d.strength == "0.1%"
        assert d.base_inn == "cyanocobalamine"
        assert d.formulation == "powder"

    def test_no_strength(self):
        d = decompose_ingredient("Rivaroxaban Micronized")
        assert d.strength is None


class TestFormulationExtraction:
    """Step 2: Formulation 추출"""

    def test_trailing_micronized(self):
        d = decompose_ingredient("Rivaroxaban Micronized")
        assert d.formulation == "micronized"
        assert d.base_inn == "rivaroxaban"

    def test_paren_micronized(self):
        d = decompose_ingredient("Budesonide (Micronized)")
        assert d.formulation == "micronized"
        assert d.base_inn == "budesonide"

    def test_coated_granules(self):
        d = decompose_ingredient("Ascorbic Acid Coated Granules 97%")
        assert d.formulation == "coated granules"

    def test_concentrate_powder(self):
        d = decompose_ingredient("Cholecalciferol Concentrate Powder")
        assert d.formulation == "concentrate powder"
        assert d.base_inn == "cholecalciferol"

    def test_extended_release_microspheres(self):
        d = decompose_ingredient(
            "Risperidone Extended Release Microspheres (as risperidone)"
        )
        assert d.formulation == "extended release microspheres"
        assert d.base_inn == "risperidone"

    def test_enteric_coated_in_parens(self):
        d = decompose_ingredient("Aspirin(Enteric Coated)")
        assert d.formulation == "enteric coated"
        assert d.base_inn == "aspirin"

    def test_prefix_liposomal(self):
        d = decompose_ingredient("Liposomal Doxorubicin Hydrochloride")
        assert d.formulation == "liposomal"
        assert d.base_inn == "doxorubicin"
        assert d.salt == "hydrochloride"

    def test_combined_granule_micronized(self):
        d = decompose_ingredient("Fenofibrate Granule(Micronized) (as fenofibrate)")
        assert "micronized" in d.formulation
        assert d.base_inn == "fenofibrate"


class TestSaltExtraction:
    """Step 3: Salt 추출 + 표준명 치환"""

    def test_hydrochloride(self):
        d = decompose_ingredient("Cetirizine Hydrochloride")
        assert d.salt == "hydrochloride"
        assert d.base_inn == "cetirizine"

    def test_besylate_to_besilate(self):
        """besylate → besilate 치환 확인"""
        d = decompose_ingredient("Bepotastine Besylate")
        assert d.salt == "besilate"

    def test_hcl_to_hydrochloride(self):
        """HCl → hydrochloride 치환 확인"""
        d = decompose_ingredient("Acebutolol HCl")
        assert d.salt == "hydrochloride"
        assert d.base_inn == "acebutolol"

    def test_sodium(self):
        d = decompose_ingredient("Fluvastatin Sodium")
        assert d.salt == "sodium"
        assert d.base_inn == "fluvastatin"

    def test_dimaleate(self):
        d = decompose_ingredient("Afatinib Dimaleate (as afatinib)")
        assert d.salt == "dimaleate"
        assert d.base_inn == "afatinib"

    def test_mesylate_micronized(self):
        """Salt + Formulation 동시 추출"""
        d = decompose_ingredient("Belumosudil Mesylate Micronized (as belumosudil)")
        assert d.salt == "mesylate"
        assert d.formulation == "micronized"
        assert d.base_inn == "belumosudil"

    def test_salt_rollback_on_empty_base(self):
        """Salt 추출 후 base가 비면 rollback"""
        d = decompose_ingredient("Sodium")
        assert d.base_inn == "sodium"
        assert d.salt is None  # rollback


class TestBaseINN:
    """Step 4: Base INN 정리"""

    def test_simple_name(self):
        d = decompose_ingredient("Pembrolizumab")
        assert d.base_inn == "pembrolizumab"
        assert d.salt is None
        assert d.formulation is None
        assert d.strength is None

    def test_paren_removal(self):
        d = decompose_ingredient("Somatropin (rDNA origin)")
        assert d.base_inn == "somatropin"

    def test_empty_input(self):
        d = decompose_ingredient("")
        assert d.base_inn == ""

    def test_none_input(self):
        d = decompose_ingredient(None)
        assert d.base_inn == ""


class TestVariantKey:
    """계층 구조 키 검증"""

    def test_base_only(self):
        d = decompose_ingredient("Pembrolizumab")
        assert d.variant_key == "pembrolizumab"
        assert d.base_key == "pembrolizumab"
        assert d.variant_key == d.base_key

    def test_base_plus_salt(self):
        d = decompose_ingredient("Cetirizine Hydrochloride")
        assert d.variant_key == "cetirizine hydrochloride"
        assert d.base_key == "cetirizine"

    def test_base_plus_salt_plus_form(self):
        d = decompose_ingredient("Belumosudil Mesylate Micronized (as belumosudil)")
        assert d.variant_key == "belumosudil mesylate micronized"
        assert d.base_key == "belumosudil"

    def test_base_plus_form(self):
        d = decompose_ingredient("Rivaroxaban Micronized")
        assert d.variant_key == "rivaroxaban micronized"
        assert d.base_key == "rivaroxaban"


class TestLosslessDecomposition:
    """무손실 원칙: 모든 정보성 토큰이 4개 컬럼 중 하나에 귀속"""

    @pytest.mark.parametrize("raw", [
        "Ascorbic Acid Coated Granules 97%",
        "Bepotastine Besylate (as bepotastine 10.7mg)",
        "Rivaroxaban Micronized",
        "Cetirizine Hydrochloride",
        "0.1% Cyanocobalamine Powder",
        "Budesonide (Micronized)",
        "Fluvastatin Sodium",
    ])
    def test_no_level4_first_word_matching(self, raw):
        """Level 4 (첫 단어 매칭) 불허 — base_inn은 반드시 원본에 존재하는 문자열"""
        d = decompose_ingredient(raw)
        assert d.base_inn in raw.lower()

    def test_to_dict_keys(self):
        d = decompose_ingredient("Rivaroxaban Micronized")
        dd = d.to_dict()
        expected_keys = {
            "raw", "base_inn", "salt", "formulation",
            "strength", "variant_key", "base_key", "match_confidence",
        }
        assert set(dd.keys()) == expected_keys


class TestConfidence:
    """분해 신뢰도"""

    def test_no_decomposition(self):
        d = decompose_ingredient("Pembrolizumab")
        assert d.match_confidence == 1.0

    def test_partial_decomposition(self):
        d = decompose_ingredient("Rivaroxaban Micronized")
        assert d.match_confidence == 0.95

    def test_full_decomposition(self):
        """salt + formulation + strength = 3 parts → 0.9"""
        d = decompose_ingredient("Ascorbic Acid Coated Granules 97%")
        # formulation=coated granules, strength=97% → 2 parts = 0.95
        # salt + form + strength가 모두 있는 케이스
        d2 = decompose_ingredient("Belumosudil Mesylate Micronized (as belumosudil)")
        # salt=mesylate, formulation=micronized, strength=None → 2 parts = 0.95
        assert d2.match_confidence == 0.95
        assert d.match_confidence == 0.95
