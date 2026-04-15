"""Decomposer 스냅샷 테스트 — 6,414건 전수 분해 결과 고정

골든 데이터: tests/fixtures/decomposer_snapshot.json
decomposer.py 또는 assets/*.json 변경 시 이 테스트가 diff를 감지.

변경이 의도적이면: pytest --snapshot-update 로 스냅샷 갱신.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "decomposer_snapshot.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def current(golden: dict) -> dict:
    from regscan.map.decomposer import decompose_ingredient

    results = {}
    for name in golden:
        d = decompose_ingredient(name)
        results[name] = {
            "base_inn": d.base_inn,
            "salt": d.salt,
            "formulation": d.formulation,
            "strength": d.strength,
        }
    return results


class TestSnapshotDecomposition:
    """분해 결과가 골든 스냅샷과 일치하는지 검증"""

    def test_total_count(self, golden: dict, current: dict):
        assert len(current) == len(golden), (
            f"항목 수 불일치: golden={len(golden)}, current={len(current)}"
        )

    def test_no_regressions(self, golden: dict, current: dict):
        """분해 결과(base_inn, salt, formulation, strength)가 변경된 항목 검출"""
        diffs = []
        for name in golden:
            g = golden[name]
            c = current.get(name)
            if c is None:
                diffs.append(f"  MISSING: {name}")
                continue
            for field in ("base_inn", "salt", "formulation", "strength"):
                if g[field] != c[field]:
                    diffs.append(
                        f"  {name}: {field} "
                        f"golden={g[field]!r} -> current={c[field]!r}"
                    )

        if diffs:
            header = f"\n{'='*60}\nDecomposer snapshot diff: {len(diffs)} changes\n{'='*60}\n"
            detail = "\n".join(diffs[:50])
            if len(diffs) > 50:
                detail += f"\n  ... and {len(diffs) - 50} more"
            pytest.fail(header + detail)


class TestSnapshotIntegrity:
    """스냅샷 파일 자체의 무결성 검증"""

    def test_snapshot_exists(self):
        assert SNAPSHOT_PATH.exists(), f"스냅샷 파일 없음: {SNAPSHOT_PATH}"

    def test_snapshot_min_entries(self, golden: dict):
        assert len(golden) >= 6000, (
            f"스냅샷 항목 수 비정상: {len(golden)} (최소 6000 기대)"
        )

    def test_snapshot_has_required_fields(self, golden: dict):
        sample = next(iter(golden.values()))
        required = {"base_inn", "salt", "formulation", "strength", "match_method", "status"}
        assert required <= set(sample.keys()), (
            f"필수 필드 누락: {required - set(sample.keys())}"
        )
