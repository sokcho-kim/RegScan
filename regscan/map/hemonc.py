"""HemOnc 온톨로지 인덱스 — 항암 경쟁구도 구조화

Harvard Dataverse HemOncKB CC BY subset 기반.
파일: data/hemonc/YYYY-MM-DD.ccby_concepts.csv + ccby_rels.csv + ccby_synonyms.csv

Usage:
    index = get_hemonc_index()
    card = index.get_competition_card("quizartinib")
    # card.diseases = ["Acute myeloid leukemia"]
    # card.same_indication_drugs = ["midostaurin", "gilteritinib", ...]
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompetitionCard:
    """HemOnc 기반 경쟁 구도 카드."""
    inn: str

    # 적응증
    fda_indications: list[str] = field(default_factory=list)

    # 분류
    major_class: str = ""           # e.g. "Tyrosine kinase inhibitor"
    minor_class: str = ""           # e.g. "FLT3 inhibitor"

    # 경쟁약 — 같은 FDA indication
    same_indication_drugs: list[str] = field(default_factory=list)

    # 경쟁약 — 같은 minor class (기전)
    same_class_drugs: list[str] = field(default_factory=list)

    # 메타
    brand_name: str = ""
    fda_approved_year: str = ""
    route: str = ""
    source: str = "hemonc_ccby"
    hemonc_code: str = ""

    def to_compact_dict(self) -> dict:
        """LLM 입력용 압축 dict."""
        d: dict[str, Any] = {"inn": self.inn}
        if self.fda_indications:
            d["indications"] = self.fda_indications
        if self.major_class:
            d["major_class"] = self.major_class
        if self.minor_class:
            d["minor_class"] = self.minor_class
        if self.same_indication_drugs:
            d["same_indication"] = self.same_indication_drugs[:8]
        if self.same_class_drugs:
            d["same_class"] = self.same_class_drugs[:5]
        if self.brand_name:
            d["brand"] = self.brand_name
        return d


class HemOncIndex:
    """HemOnc CC BY 온톨로지 인메모리 인덱스."""

    def __init__(self):
        self._code_to_name: dict[str, str] = {}
        self._code_to_class: dict[str, str] = {}  # concept_class_id
        self._name_to_code: dict[str, str] = {}    # lowercase name → code
        # 관계 인덱스: relationship_id → {code_1 → [code_2]}
        self._rels_fwd: dict[str, dict[str, list[str]]] = {}
        # 역방향: relationship_id → {code_2 → [code_1]}
        self._rels_rev: dict[str, dict[str, list[str]]] = {}
        self._loaded = False

    def load(
        self,
        concepts_path: str | Path | None = None,
        rels_path: str | Path | None = None,
        synonyms_path: str | Path | None = None,
    ) -> None:
        """HemOnc CC BY CSV 로드."""
        data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "hemonc"

        # 파일 자동 탐색 (날짜 prefix)
        if concepts_path is None:
            files = sorted(data_dir.glob("*ccby_concepts.csv"), reverse=True)
            concepts_path = files[0] if files else data_dir / "ccby_concepts.csv"
        if rels_path is None:
            files = sorted(data_dir.glob("*ccby_rels.csv"), reverse=True)
            rels_path = files[0] if files else data_dir / "ccby_rels.csv"
        if synonyms_path is None:
            files = sorted(data_dir.glob("*ccby_synonyms.csv"), reverse=True)
            synonyms_path = files[0] if files else None

        concepts_path = Path(concepts_path)
        rels_path = Path(rels_path)

        if not concepts_path.exists():
            logger.warning("[HemOnc] concepts 파일 없음: %s", concepts_path)
            return
        if not rels_path.exists():
            logger.warning("[HemOnc] rels 파일 없음: %s", rels_path)
            return

        self._load_concepts(concepts_path)
        self._load_relationships(rels_path)
        if synonyms_path and Path(synonyms_path).exists():
            self._load_synonyms(Path(synonyms_path))
        self._loaded = True

    def _load_concepts(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("concept_code", "")
                name = row.get("concept_name", "")
                cls = row.get("concept_class_id", "")
                if not code or not name:
                    continue
                self._code_to_name[code] = name
                self._code_to_class[code] = cls
                # Component(약물)만 INN 인덱스
                if cls in ("Component", "Component Class"):
                    self._name_to_code[name.lower()] = code

        logger.info("[HemOnc] concepts 로드: %d건, drugs: %d개",
                    len(self._code_to_name), len(self._name_to_code))

    def _load_relationships(self, path: Path) -> None:
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rel = row.get("relationship_id", "")
                c1 = row.get("concept_code_1", "")
                c2 = row.get("concept_code_2", "")
                # HemOnc 내부 관계만 (외부 vocab 매핑 제외)
                v1 = row.get("vocabulary_id_1", "")
                v2 = row.get("vocabulary_id_2", "")
                if v1 != "HemOnc" or v2 != "HemOnc":
                    continue
                if not rel or not c1 or not c2:
                    continue

                self._rels_fwd.setdefault(rel, {}).setdefault(c1, []).append(c2)
                self._rels_rev.setdefault(rel, {}).setdefault(c2, []).append(c1)
                count += 1

        logger.info("[HemOnc] relationships 로드: %d건", count)

    def _load_synonyms(self, path: Path) -> None:
        """동의어 로드 → INN 매칭 보강."""
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("concept_code", "")
                syn = row.get("concept_synonym_name", "")
                cls = self._code_to_class.get(code, "")
                if cls in ("Component", "Component Class") and syn:
                    syn_lower = syn.lower()
                    if syn_lower not in self._name_to_code:
                        self._name_to_code[syn_lower] = code
                        count += 1
        logger.info("[HemOnc] synonyms 로드: %d건 추가", count)

    def _get_related(self, rel: str, code: str, direction: str = "fwd") -> list[str]:
        """관계 조회. direction: fwd(code→target) / rev(target→code)."""
        idx = self._rels_fwd if direction == "fwd" else self._rels_rev
        return idx.get(rel, {}).get(code, [])

    def get_competition_card(self, inn: str) -> CompetitionCard:
        """INN → CompetitionCard."""
        if not self._loaded:
            self.load()
            if not self._loaded:
                return CompetitionCard(inn=inn)

        code = self._name_to_code.get(inn.lower())
        if code is None:
            return CompetitionCard(inn=inn)

        # FDA indications
        ind_codes = self._get_related("Has FDA indication", code)
        indications = [self._code_to_name.get(c, "") for c in ind_codes if c in self._code_to_name]

        # Major/Minor class
        major_codes = self._get_related("Has major class", code)
        minor_codes = self._get_related("Has minor class", code)
        major = self._code_to_name.get(major_codes[0], "") if major_codes else ""
        minor = self._code_to_name.get(minor_codes[0], "") if minor_codes else ""

        # Brand name
        brand_codes = self._get_related("Has brand name", code)
        brand = self._code_to_name.get(brand_codes[0], "") if brand_codes else ""

        # FDA approved year
        yr_codes = self._get_related("Was FDA approved yr", code)
        year = self._code_to_name.get(yr_codes[0], "") if yr_codes else ""

        # Route
        route_codes = self._get_related("Has route", code)
        route = self._code_to_name.get(route_codes[0], "") if route_codes else ""

        # 같은 FDA indication 약물 (경쟁약)
        same_ind_drugs: list[str] = []
        for ind_code in ind_codes:
            # 역방향: indication → 이 적응증을 가진 약물들
            drug_codes = self._get_related("Has FDA indication", ind_code, direction="rev")
            for dc in drug_codes:
                if dc != code and self._code_to_class.get(dc) == "Component":
                    name = self._code_to_name.get(dc, "")
                    if name and name not in same_ind_drugs:
                        same_ind_drugs.append(name)

        # 같은 minor class 약물
        same_class_drugs: list[str] = []
        for mc in minor_codes:
            drug_codes = self._get_related("Has minor class", mc, direction="rev")
            for dc in drug_codes:
                if dc != code and self._code_to_class.get(dc) == "Component":
                    name = self._code_to_name.get(dc, "")
                    if name and name not in same_class_drugs:
                        same_class_drugs.append(name)

        return CompetitionCard(
            inn=inn,
            fda_indications=indications,
            major_class=major,
            minor_class=minor,
            same_indication_drugs=same_ind_drugs,
            same_class_drugs=same_class_drugs,
            brand_name=brand,
            fda_approved_year=year,
            route=route,
            hemonc_code=code,
        )


# 싱글턴
_hemonc_instance: Optional[HemOncIndex] = None


def get_hemonc_index() -> HemOncIndex | None:
    """HemOncIndex 싱글턴. 데이터 없으면 None."""
    global _hemonc_instance
    if _hemonc_instance is None:
        idx = HemOncIndex()
        idx.load()
        if idx._loaded:
            _hemonc_instance = idx
        else:
            return None
    return _hemonc_instance
