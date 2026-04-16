"""HemOnc 온톨로지 인덱스 — 항암 경쟁구도 구조화

ATHENA(https://athena.ohdsi.org/)에서 다운로드한 HemOnc vocabulary 기반.
OMOP CDM 포맷: CONCEPT.csv + CONCEPT_RELATIONSHIP.csv

Usage:
    index = get_hemonc_index()
    card = index.get_competition_card("quizartinib")
    # card.diseases = ["Acute myeloid leukemia"]
    # card.compared_drugs = [{"inn": "midostaurin", ...}]
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# CompetitionCard
# ════════════════════════════════════════════════════════════════════

@dataclass
class CompetitionCard:
    """HemOnc 기반 경쟁 구도 카드."""
    inn: str

    # 레지멘/질환/맥락
    regimens: list[str] = field(default_factory=list)
    diseases: list[str] = field(default_factory=list)
    treatment_contexts: list[str] = field(default_factory=list)  # first-line, salvage, etc

    # 경쟁약 (head-to-head RCT 비교)
    compared_drugs: list[dict] = field(default_factory=list)

    # 같은 레지멘 공간 약물 (동일 질환)
    same_space_drugs: list[str] = field(default_factory=list)

    # 메타
    source: str = "hemonc"
    hemonc_concept_id: str = ""

    def to_compact_dict(self) -> dict:
        """LLM 입력용 압축 dict."""
        d: dict[str, Any] = {"inn": self.inn}
        if self.diseases:
            d["diseases"] = self.diseases
        if self.treatment_contexts:
            d["contexts"] = self.treatment_contexts
        if self.compared_drugs:
            d["compared_to"] = [c["inn"] for c in self.compared_drugs[:5]]
        if self.same_space_drugs:
            d["same_space"] = self.same_space_drugs[:5]
        if self.regimens:
            d["regimens"] = self.regimens[:3]
        return d


# ════════════════════════════════════════════════════════════════════
# HemOncIndex
# ════════════════════════════════════════════════════════════════════

class HemOncIndex:
    """HemOnc 온톨로지 인메모리 인덱스.

    OMOP CDM의 CONCEPT + CONCEPT_RELATIONSHIP 테이블에서
    Drug → Regimen → Disease → Context 관계를 인덱싱.
    """

    # HemOnc vocabulary_id
    VOCAB_ID = "HemOnc"

    # 관심 relationship_id
    REL_CONTAINS = "Has antineoplastic Rx"    # regimen → drug
    REL_HAS_CONTEXT = "Has context"           # regimen → context (line)
    REL_COMPARED = "Has been compared to"     # drug ↔ drug (RCT)
    REL_IS_A = "Is a"                         # hierarchy

    def __init__(self):
        # concept_id → concept dict
        self._concepts: dict[int, dict] = {}
        # INN (lowercase) → concept_id
        self._inn_to_id: dict[str, int] = {}
        # concept_id → [related concept_ids] by relationship
        self._rels: dict[str, dict[int, list[int]]] = {}
        # concept_id → domain_id
        self._loaded = False

    def load(
        self,
        concept_path: str | Path | None = None,
        relationship_path: str | Path | None = None,
    ) -> None:
        """ATHENA TSV/CSV 로드."""
        data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "hemonc"

        concept_file = Path(concept_path) if concept_path else data_dir / "CONCEPT.csv"
        rel_file = Path(relationship_path) if relationship_path else data_dir / "CONCEPT_RELATIONSHIP.csv"

        if not concept_file.exists():
            logger.warning("[HemOnc] CONCEPT 파일 없음: %s", concept_file)
            return
        if not rel_file.exists():
            logger.warning("[HemOnc] CONCEPT_RELATIONSHIP 파일 없음: %s", rel_file)
            return

        self._load_concepts(concept_file)
        self._load_relationships(rel_file)
        self._loaded = True

    def _load_concepts(self, path: Path) -> None:
        """CONCEPT.csv 로드 — HemOnc vocabulary만 필터."""
        count = 0
        for enc in ["utf-8", "utf-8-sig", "cp949"]:
            try:
                with open(path, "r", encoding=enc) as f:
                    # ATHENA는 tab-delimited
                    sample = f.read(1000)
                    delimiter = "\t" if "\t" in sample else ","
                    f.seek(0)
                    reader = csv.DictReader(f, delimiter=delimiter)
                    for row in reader:
                        vocab = row.get("vocabulary_id", "")
                        if vocab != self.VOCAB_ID:
                            continue
                        cid = int(row["concept_id"])
                        self._concepts[cid] = {
                            "concept_id": cid,
                            "concept_name": row.get("concept_name", ""),
                            "domain_id": row.get("domain_id", ""),
                            "concept_class_id": row.get("concept_class_id", ""),
                            "vocabulary_id": vocab,
                        }
                        # Drug 도메인이면 INN 인덱스
                        if row.get("domain_id") == "Drug" or row.get("concept_class_id") in ("Component", "Component Class"):
                            name_lower = row.get("concept_name", "").strip().lower()
                            self._inn_to_id[name_lower] = cid
                        count += 1
                break
            except (UnicodeDecodeError, KeyError):
                continue

        logger.info("[HemOnc] CONCEPT 로드: %d건, Drug INN: %d개", count, len(self._inn_to_id))

    def _load_relationships(self, path: Path) -> None:
        """CONCEPT_RELATIONSHIP.csv 로드 — 관심 관계만 필터."""
        target_rels = {
            self.REL_CONTAINS,
            self.REL_HAS_CONTEXT,
            self.REL_COMPARED,
            self.REL_IS_A,
            # 추가 관계
            "Has antineoplastic Rx",
            "Has been compared to",
            "Has context",
            "Is a",
            "Has finding context",
        }
        count = 0
        for enc in ["utf-8", "utf-8-sig", "cp949"]:
            try:
                with open(path, "r", encoding=enc) as f:
                    sample = f.read(1000)
                    delimiter = "\t" if "\t" in sample else ","
                    f.seek(0)
                    reader = csv.DictReader(f, delimiter=delimiter)
                    for row in reader:
                        rel_id = row.get("relationship_id", "")
                        if rel_id not in target_rels:
                            continue
                        c1 = int(row["concept_id_1"])
                        c2 = int(row["concept_id_2"])

                        if rel_id not in self._rels:
                            self._rels[rel_id] = {}
                        self._rels[rel_id].setdefault(c1, []).append(c2)
                        count += 1
                break
            except (UnicodeDecodeError, KeyError):
                continue

        logger.info("[HemOnc] RELATIONSHIP 로드: %d건, 관계 유형: %s",
                    count, list(self._rels.keys()))

    def get_competition_card(self, inn: str) -> CompetitionCard:
        """INN → CompetitionCard."""
        if not self._loaded:
            self.load()

        inn_lower = inn.strip().lower()
        concept_id = self._inn_to_id.get(inn_lower)

        if concept_id is None:
            return CompetitionCard(inn=inn)

        concept = self._concepts.get(concept_id, {})

        # 1) "Has been compared to" — 직접 경쟁약
        compared_ids = self._rels.get(self.REL_COMPARED, {}).get(concept_id, [])
        compared_drugs = []
        for cid in compared_ids:
            comp = self._concepts.get(cid, {})
            if comp:
                compared_drugs.append({
                    "inn": comp["concept_name"],
                    "concept_id": cid,
                    "relationship": "has been compared to",
                })

        # 2) 이 약물이 포함된 레지멘 찾기
        regimen_names = []
        disease_names = set()
        context_names = set()
        same_space = set()

        # "Has antineoplastic Rx" 역방향: 레지멘 → 이 약물
        rx_rels = self._rels.get(self.REL_CONTAINS, {})
        for regimen_id, drug_ids in rx_rels.items():
            if concept_id in drug_ids:
                reg = self._concepts.get(regimen_id, {})
                if reg:
                    regimen_names.append(reg["concept_name"])

                    # 레지멘의 context (치료라인)
                    ctx_ids = self._rels.get(self.REL_HAS_CONTEXT, {}).get(regimen_id, [])
                    for ctx_id in ctx_ids:
                        ctx = self._concepts.get(ctx_id, {})
                        if ctx:
                            context_names.add(ctx["concept_name"])

                    # 같은 레지멘의 다른 약물
                    for did in drug_ids:
                        if did != concept_id:
                            d = self._concepts.get(did, {})
                            if d:
                                same_space.add(d["concept_name"])

        # 3) Disease (Is a 관계 또는 context에서 추출)
        # HemOnc에서 disease는 보통 regimen의 상위 concept으로 연결
        is_a_rels = self._rels.get(self.REL_IS_A, {})
        for regimen_id, drug_ids in rx_rels.items():
            if concept_id in drug_ids:
                parent_ids = is_a_rels.get(regimen_id, [])
                for pid in parent_ids:
                    parent = self._concepts.get(pid, {})
                    if parent and parent.get("domain_id") == "Condition":
                        disease_names.add(parent["concept_name"])

        return CompetitionCard(
            inn=inn,
            regimens=regimen_names[:10],
            diseases=list(disease_names),
            treatment_contexts=list(context_names),
            compared_drugs=compared_drugs,
            same_space_drugs=list(same_space)[:10],
            hemonc_concept_id=str(concept_id),
        )


# ════════════════════════════════════════════════════════════════════
# 싱글턴
# ════════════════════════════════════════════════════════════════════

_hemonc_instance: Optional[HemOncIndex] = None


def get_hemonc_index() -> HemOncIndex | None:
    """HemOncIndex 싱글턴. 데이터 없으면 None 반환."""
    global _hemonc_instance
    if _hemonc_instance is None:
        idx = HemOncIndex()
        idx.load()
        if idx._loaded:
            _hemonc_instance = idx
        else:
            return None
    return _hemonc_instance
