"""MFDS ↔ HIRA 성분명 브릿지

의약품주성분 마스터(data.go.kr/15067461)를 사용하여
MFDS 허가 의약품과 HIRA 급여 정보를 연결

v6 실험 결과: 75.4% 매칭률 (33,194/44,035건)
- 정규화 후 **완전 일치**만 사용 (퍼지매칭 없음)
- 미연결 24.6%: 한약재(46%), 비급여(20%), 화합물차이(10%), 미등재(15%), 기타(9%)
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Any

from .decomposer import decompose_ingredient, DecomposedIngredient


class ReimbursementStatus(str, Enum):
    """HIRA 급여 상태 (7단계)"""
    REIMBURSED = "reimbursed"                       # 급여 등재
    NON_REIMBURSED = "non_reimbursed"               # 비급여 (마스터에 있지만 HIRA 약가 없음)
    DELISTED = "delisted"                           # 급여 삭제 (과거 등재 이력)
    EVALUATION_HISTORY = "evaluation_history"       # 급여평가/심의 이력 있음 (등재 전)
    NOT_FOUND_IN_SOURCE = "not_found_in_source"     # HIRA 원천에 없음 (수집 범위 밖)
    BRIDGE_UNMATCHED = "bridge_unmatched"           # 브릿지 매칭 실패
    MANUAL_REVIEW = "manual_review_required"        # 수동 확인 필요

    # 레거시 호환
    DELETED = "deleted"
    NOT_COVERED = "not_covered"
    NOT_FOUND = "not_found"
    HERBAL = "herbal"


class MFDSStatus(str, Enum):
    """MFDS 허가 상태 (5단계)"""
    APPROVED = "approved"                           # 허가 확인
    UNAPPROVED_CONFIRMED = "unapproved_confirmed"   # 미허가 확인 (공식 DB에서 부재 확인)
    NOT_FOUND = "not_found"                         # 수집 데이터에 없음 (미확인)
    AMBIGUOUS_MATCH = "ambiguous_match"             # 매칭 모호 (동명이의 등)
    MANUAL_REVIEW = "manual_review_required"        # 수동 확인 필요


class MatchConfidence(str, Enum):
    """매칭 신뢰도"""
    EXACT = "exact_match"                           # 정규화 후 완전 일치
    NORMALIZED = "normalized_match"                 # 염/제형 정규화 후 일치
    BASE_FALLBACK = "base_fallback_match"           # base INN만 일치 (variant 불일치)
    ATC_FALLBACK = "atc_fallback"                   # ATC 코드 기반 매칭
    UNMATCHED = "unmatched"                         # 매칭 실패


@dataclass
class HIRAReimbursementInfo:
    """HIRA 급여 정보"""
    ingredient_code: str              # 의성분코드 (예: 639001BIJ)
    ingredient_name: str              # 일반명
    status: ReimbursementStatus

    # 급여 정보
    reimbursement_criteria: str = ""  # 급여기준
    price_ceiling: Optional[float] = None  # 상한가

    # 매칭 메타데이터
    match_method: str = ""            # normalized, atc, exact
    match_confidence: str = ""        # MatchConfidence value
    normalized_name: str = ""         # 매칭에 사용된 정규화 이름

    # 원본 데이터
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingredient_code": self.ingredient_code,
            "ingredient_name": self.ingredient_name,
            "status": self.status.value,
            "reimbursement_criteria": self.reimbursement_criteria,
            "price_ceiling": self.price_ceiling,
            "match_method": self.match_method,
            "match_confidence": self.match_confidence,
            "normalized_name": self.normalized_name,
        }


def normalize_ingredient_name(name: str) -> str:
    """
    성분명 정규화 - v6 실험에서 검증된 규칙

    **정규화 ≠ 퍼지매칭**: 정규화 후 문자열 완전 일치만 수행

    안전한 정규화:
    - 대소문자 통일
    - (as ...) 괄호 제거
    - 수화물 제거 (trihydrate, dihydrate 등)
    - 철자 오류 수정 (besylate→besilate, tartarate→tartrate)

    위험한 정규화 (하지 않음):
    - hydrochloride vs dihydrochloride (다른 화합물)
    """
    if not name:
        return ""

    # 1. 소문자 변환
    name = name.lower().strip()

    # 2. (as ...) 형태의 괄호 제거
    name = re.sub(r'\s*\(as[^)]*\)', '', name)
    # 다른 괄호도 제거
    name = re.sub(r'\s*\([^)]*\)', '', name)

    # 3. 수화물 형태 제거 (같은 성분, 결정수 차이)
    hydrates = [
        'pentahydrate',
        'tetrahydrate',
        'trihydrate',
        'dihydrate',
        'monohydrate',
        'hemihydrate',
        'hydrate',
        'anhydrous',
    ]
    for h in hydrates:
        name = name.replace(h, '')

    # 4. 알려진 철자 오류 수정
    typo_corrections = {
        'besylate': 'besilate',      # 명백한 오타
        'tartarate': 'tartrate',      # 명백한 오타
    }
    for typo, correct in typo_corrections.items():
        name = name.replace(typo, correct)

    # 5. 공백 정리
    name = ' '.join(name.split())

    return name.strip()


def is_herbal_ingredient(name: str) -> bool:
    """한약재/생약 여부 판단"""
    if not name:
        return False

    # 한약재/생약 특징적 패턴
    herbal_patterns = [
        # 라틴어 식물명 (부위)
        r'\b(radix|folium|fructus|cortex|rhizome|semen|herba|flos)\b',
        # 추출물 (비율 표기)
        r'\bextract\b.*\(\d+[→\-]\d+\)',  # Extract (3→1) 또는 (3-1) 패턴
        r'\b\d+%\s*(ethanol|water)\s+(soft\s+)?extract\b',
        # 식물성 추출물 (dried/soft extract)
        r'\b(dried|soft)\s+extract\b',
        # 한약재 학명 끝말
        r'(gigas|japonica|sinensis|chinensis|orientalis)\s*(root|leaf|fruit|bark)?\b',
        # 일반적인 생약 식물명
        r'\b(ginkgo|ginseng|angelica|artemisia|alisma|astragalus|panax)\b',
        # 복합 처방 (중점 기호)
        r'·',
        # Root/Leaf/Bark로 끝나는 식물 성분
        r'\b\w+\s+(root|leaf|bark|fruit|seed|flower)\s*(dried)?\s*(extract)?\b',
    ]

    name_lower = name.lower()
    for pattern in herbal_patterns:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True

    return False


class IngredientBridge:
    """MFDS ↔ HIRA 성분명 브릿지

    의약품주성분 마스터를 브릿지로 사용하여
    MFDS 성분명 → 일반명코드 → HIRA 의성분코드 연결

    사용법:
        bridge = IngredientBridge()
        bridge.load_master("data/bridge/yakga_ingredient_master.csv")
        bridge.load_hira("data/hira/drug_prices_20260204.json")

        result = bridge.lookup("Amlodipine Besylate")
        # HIRAReimbursementInfo(status=REIMBURSED, ...)
    """

    def __init__(self):
        # 정규화된 일반명 → 일반명코드 목록
        self._name_to_codes: dict[str, set[str]] = defaultdict(set)
        # 일반명코드 → 원본 정보
        self._code_to_info: dict[str, dict] = {}
        # ATC 매핑 (보조)
        self._inn_to_code: dict[str, str] = {}
        # HIRA 의성분코드 → 급여정보
        self._hira_by_code: dict[str, list[dict]] = defaultdict(list)

        self._master_loaded = False
        self._hira_loaded = False

    def load_master(self, path: str | Path, encoding: str = 'cp949') -> int:
        """
        의약품주성분 마스터 로드

        Args:
            path: yakga_ingredient_master.csv 경로
            encoding: 파일 인코딩 (기본: cp949)

        Returns:
            로드된 레코드 수
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Master file not found: {path}")

        count = 0
        with open(path, "r", encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name_raw = row.get('일반명', '').strip()
                code = row.get('일반명코드', '').strip()

                if name_raw and code:
                    # 정규화된 이름으로 인덱싱
                    name_norm = normalize_ingredient_name(name_raw)
                    self._name_to_codes[name_norm].add(code)

                    # 원본 소문자도 추가 (exact match용)
                    name_lower = name_raw.lower().strip()
                    self._name_to_codes[name_lower].add(code)

                    # 코드 정보 저장
                    if code not in self._code_to_info:
                        self._code_to_info[code] = {
                            'name': name_raw,
                            'form': row.get('제형', ''),
                            'dosage': row.get('함량', ''),
                            'unit': row.get('단위', ''),
                        }
                    count += 1

        self._master_loaded = True
        return count

    def load_atc_mapping(self, path: str | Path, encoding: str = 'cp949') -> int:
        """
        ATC 매핑 로드 (보조 매칭용)

        Args:
            path: ATC 매핑 CSV 경로

        Returns:
            로드된 레코드 수
        """
        path = Path(path)
        if not path.exists():
            return 0

        count = 0
        with open(path, "r", encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                inn = row.get("ATC코드 명칭", "").strip().lower()
                code = row.get("주성분코드", "").strip()
                if inn and code:
                    self._inn_to_code[inn] = code
                    count += 1

        return count

    def load_hira(self, path: str | Path) -> int:
        """
        HIRA 적용약가 로드

        Args:
            path: drug_prices JSON 경로

        Returns:
            로드된 레코드 수
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"HIRA data not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for row in data:
            code = row.get("ingredient_code", "").strip()
            if code:
                self._hira_by_code[code].append(row)

        self._hira_loaded = True
        return len(data)

    def lookup(self, ingredient_name: str) -> HIRAReimbursementInfo:
        """
        성분명으로 HIRA 급여 정보 조회

        Args:
            ingredient_name: MFDS ITEM_INGR_NAME

        Returns:
            HIRAReimbursementInfo
        """
        if not self._master_loaded:
            raise RuntimeError("Master data not loaded. Call load_master() first.")

        if not ingredient_name:
            return HIRAReimbursementInfo(
                ingredient_code="",
                ingredient_name="",
                status=ReimbursementStatus.NOT_FOUND,
                match_method="no_input",
            )

        # 첫 번째 성분만 추출 (복합제는 첫 성분 기준)
        first_ingredient = ingredient_name.split("/")[0].split(";")[0].split(",")[0].strip()

        # 한약재 체크
        if is_herbal_ingredient(first_ingredient):
            return HIRAReimbursementInfo(
                ingredient_code="",
                ingredient_name=first_ingredient,
                status=ReimbursementStatus.HERBAL,
                match_method="herbal_detected",
                normalized_name=normalize_ingredient_name(first_ingredient),
            )

        # Method 1: 정규화 매칭
        norm_name = normalize_ingredient_name(first_ingredient)
        if norm_name in self._name_to_codes:
            result = self._resolve_codes(
                self._name_to_codes[norm_name], norm_name, "normalized",
            )
            if result:
                return result

        # Method 2: Decomposition 2-Pass Lookup
        # 원본을 [base_inn, salt, formulation, strength]로 분해 후 재매칭
        decomposed = decompose_ingredient(first_ingredient)

        # Pass 1: variant_key (Base+Salt+Formulation) 완전 일치
        vk = decomposed.variant_key
        if vk != norm_name and vk in self._name_to_codes:
            codes = self._name_to_codes[vk]
            result = self._resolve_codes(
                codes, decomposed.variant_key, "decomposed_variant",
            )
            if result:
                result.raw_data["decomposed"] = decomposed.to_dict()
                return result

        # Pass 2: base_key (Base INN만) fallback
        bk = decomposed.base_key
        if bk != norm_name and bk != vk and bk in self._name_to_codes:
            codes = self._name_to_codes[bk]
            result = self._resolve_codes(
                codes, decomposed.base_key, "decomposed_base_fallback",
            )
            if result:
                result.raw_data["decomposed"] = decomposed.to_dict()
                # base fallback은 약가 정확도가 낮으므로 표시
                result.raw_data["base_fallback_note"] = (
                    f"variant={decomposed.variant_key} 미매칭, "
                    f"base={decomposed.base_key}로 대체 매칭"
                )
                return result

        # Method 3: ATC fallback
        inn_lower = first_ingredient.lower()
        if inn_lower in self._inn_to_code:
            code = self._inn_to_code[inn_lower]
            if self._hira_loaded and code in self._hira_by_code:
                hira_info = self._hira_by_code[code][0]
                return HIRAReimbursementInfo(
                    ingredient_code=code,
                    ingredient_name=self._code_to_info.get(code, {}).get('name', ''),
                    status=self._determine_status(hira_info),
                    reimbursement_criteria=hira_info.get("급여기준", ""),
                    price_ceiling=hira_info.get("price_ceiling"),
                    match_method="atc",
                    normalized_name=inn_lower,
                    raw_data=hira_info,
                )

        # 매칭 실패 — decomposed 정보는 보존
        return HIRAReimbursementInfo(
            ingredient_code="",
            ingredient_name=first_ingredient,
            status=ReimbursementStatus.NOT_FOUND,
            match_method="unmatched",
            normalized_name=norm_name,
            raw_data={"decomposed": decomposed.to_dict()},
        )

    def _resolve_codes(
        self,
        codes: set[str],
        normalized_name: str,
        match_method: str,
    ) -> Optional[HIRAReimbursementInfo]:
        """코드 집합에서 HIRA 급여 정보를 조회하는 공통 로직.

        코드가 여러 개일 때, 코드의 원본 이름이 조회 이름과 가장
        유사한 것을 우선 선택하여 오매칭을 방지한다.
        """
        def _name_matches(code: str) -> bool:
            """코드의 원본 이름이 조회 이름과 관련있는지 확인."""
            code_name = self._code_to_info.get(code, {}).get('name', '').lower()
            return (
                normalized_name in code_name
                or code_name in normalized_name
                or code_name == normalized_name
            )

        # HIRA에 존재하는 코드만 필터 + 이름 일치 우선
        hira_codes = [c for c in codes if self._hira_loaded and c in self._hira_by_code]

        if hira_codes:
            # 이름이 일치하는 코드만 우선
            matched_codes = [c for c in hira_codes if _name_matches(c)]
            if not matched_codes:
                # decomposed fallback 경로에서는 이름 불일치 = 오매칭 위험
                # → normalized 매칭(기존 경로)에서만 이름 무관 선택 허용
                if match_method.startswith("decomposed_"):
                    return None  # 오매칭 방지
                best_code = hira_codes[0]
            else:
                best_code = matched_codes[0]

            hira_info = self._hira_by_code[best_code][0]
            return HIRAReimbursementInfo(
                ingredient_code=best_code,
                ingredient_name=self._code_to_info.get(best_code, {}).get('name', ''),
                status=self._determine_status(hira_info),
                reimbursement_criteria=hira_info.get("급여기준", ""),
                price_ceiling=hira_info.get("price_ceiling"),
                match_method=match_method,
                normalized_name=normalized_name,
                raw_data=hira_info,
            )

        # 코드는 있지만 HIRA에 없음 (비급여) — 이름 일치 우선
        matched_codes = [c for c in codes if _name_matches(c)]
        best_code = matched_codes[0] if matched_codes else list(codes)[0]

        return HIRAReimbursementInfo(
            ingredient_code=best_code,
            ingredient_name=self._code_to_info.get(best_code, {}).get('name', ''),
            status=ReimbursementStatus.NOT_COVERED,
            match_method=match_method,
            normalized_name=normalized_name,
        )

    def _determine_status(self, hira_info: dict) -> ReimbursementStatus:
        """HIRA 데이터에서 급여 상태 결정"""
        criteria = hira_info.get("급여기준", "")
        if criteria == "급여":
            return ReimbursementStatus.REIMBURSED
        elif criteria == "삭제":
            return ReimbursementStatus.DELETED
        else:
            return ReimbursementStatus.REIMBURSED  # 기본값

    def batch_lookup(self, ingredient_names: list[str]) -> list[HIRAReimbursementInfo]:
        """여러 성분명 일괄 조회"""
        return [self.lookup(name) for name in ingredient_names]

    def get_stats(self) -> dict[str, Any]:
        """브릿지 통계 정보"""
        return {
            "master_loaded": self._master_loaded,
            "hira_loaded": self._hira_loaded,
            "unique_names": len(self._name_to_codes),
            "unique_codes": len(self._code_to_info),
            "hira_codes": len(self._hira_by_code),
            "atc_mappings": len(self._inn_to_code),
        }


# 싱글톤 인스턴스 (선택적 사용)
_default_bridge: Optional[IngredientBridge] = None


def get_ingredient_bridge(
    master_path: Optional[str | Path] = None,
    hira_path: Optional[str | Path] = None,
    atc_path: Optional[str | Path] = None,
) -> IngredientBridge:
    """
    기본 IngredientBridge 인스턴스 반환

    첫 호출 시 데이터 로드, 이후 캐시된 인스턴스 반환
    """
    global _default_bridge

    if _default_bridge is None:
        _default_bridge = IngredientBridge()

        # 기본 경로 설정
        data_dir = Path(__file__).parent.parent.parent / "data"

        master = master_path or data_dir / "bridge" / "yakga_ingredient_master.csv"
        hira = hira_path or data_dir / "hira" / "drug_prices_20260204.json"
        atc = atc_path or data_dir / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"

        if Path(master).exists():
            _default_bridge.load_master(master)
        if Path(atc).exists():
            _default_bridge.load_atc_mapping(atc)
        if Path(hira).exists():
            _default_bridge.load_hira(hira)

    return _default_bridge


def lookup_hira_reimbursement(ingredient_name: str) -> HIRAReimbursementInfo:
    """
    편의 함수: 성분명으로 HIRA 급여 정보 조회

    사용법:
        from regscan.map.ingredient_bridge import lookup_hira_reimbursement

        info = lookup_hira_reimbursement("Pembrolizumab")
        print(info.status)  # ReimbursementStatus.REIMBURSED
    """
    bridge = get_ingredient_bridge()
    return bridge.lookup(ingredient_name)
