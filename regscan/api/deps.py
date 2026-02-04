"""API 의존성 - 데이터 로딩 및 캐싱"""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from regscan.parse.fda_parser import FDADrugParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.cris_parser import CRISTrialParser
from regscan.map.global_status import merge_global_status, GlobalRegulatoryStatus
from regscan.scan.domestic import DomesticImpactAnalyzer, DomesticImpact, DomesticStatus


class DataStore:
    """데이터 저장소 (싱글톤)"""

    def __init__(self):
        self.statuses: list[GlobalRegulatoryStatus] = []
        self.impacts: list[DomesticImpact] = []
        self.analyzer: Optional[DomesticImpactAnalyzer] = None

        # 인덱스
        self._by_inn: dict[str, DomesticImpact] = {}

        # 메타
        self.loaded_at: Optional[datetime] = None
        self.fda_count = 0
        self.ema_count = 0
        self.mfds_count = 0
        self.cris_count = 0

    def load(self, data_dir: Path) -> None:
        """데이터 로드"""
        # 파일 경로
        files = {
            "fda": data_dir / "fda" / "approvals_20260203.json",
            "ema": data_dir / "ema" / "medicines_20260203.json",
            "mfds": data_dir / "mfds" / "permits_full_20260203.json",
            "cris": data_dir / "cris" / "trials_full_20260204.json",
        }

        # 로드
        raw_data = {}
        for key, path in files.items():
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    raw_data[key] = json.load(f)

        # 파싱
        fda_parsed = FDADrugParser().parse_many(raw_data.get("fda", []))
        ema_parsed = EMAMedicineParser().parse_many(raw_data.get("ema", []))
        mfds_parsed = MFDSPermitParser().parse_many(raw_data.get("mfds", []))
        cris_parsed = CRISTrialParser().parse_many(raw_data.get("cris", []))

        self.fda_count = len(fda_parsed)
        self.ema_count = len(ema_parsed)
        self.mfds_count = len(mfds_parsed)
        self.cris_count = len(cris_parsed)

        # GlobalRegulatoryStatus 생성
        self.statuses = merge_global_status(
            fda_list=fda_parsed,
            ema_list=ema_parsed,
            mfds_list=mfds_parsed,
        )

        # DomesticImpactAnalyzer 실행
        self.analyzer = DomesticImpactAnalyzer()
        self.analyzer.load_cris_data(cris_parsed)
        self.impacts = self.analyzer.analyze_batch(self.statuses)

        # 인덱스 생성
        self._by_inn = {
            impact.inn.lower(): impact
            for impact in self.impacts
            if impact.inn
        }

        self.loaded_at = datetime.now()

    def get_by_inn(self, inn: str) -> Optional[DomesticImpact]:
        """INN으로 조회"""
        return self._by_inn.get(inn.lower())

    def search(self, query: str, limit: int = 20) -> list[DomesticImpact]:
        """검색"""
        query_lower = query.lower()
        results = []
        for impact in self.impacts:
            if query_lower in impact.inn.lower():
                results.append(impact)
                if len(results) >= limit:
                    break
        return results

    def get_hot_issues(self, min_score: int = 60) -> list[DomesticImpact]:
        """핫이슈 조회"""
        return sorted(
            [i for i in self.impacts if i.global_score >= min_score],
            key=lambda x: -x.global_score
        )

    def get_imminent(self) -> list[DomesticImpact]:
        """국내 도입 임박 약물"""
        return sorted(
            [i for i in self.impacts if i.domestic_status == DomesticStatus.IMMINENT],
            key=lambda x: -x.global_score
        )

    def get_high_value(self, min_price: float = 1_000_000) -> list[DomesticImpact]:
        """고가 급여 약물"""
        return sorted(
            [i for i in self.impacts
             if i.hira_price and i.hira_price >= min_price],
            key=lambda x: -(x.hira_price or 0)
        )


# 싱글톤 인스턴스
_store: Optional[DataStore] = None


def get_data_store() -> DataStore:
    """DataStore 싱글톤 반환"""
    global _store
    if _store is None:
        _store = DataStore()
        data_dir = Path(__file__).parent.parent.parent / "data"
        _store.load(data_dir)
    return _store


def reload_data() -> DataStore:
    """데이터 리로드"""
    global _store
    _store = DataStore()
    data_dir = Path(__file__).parent.parent.parent / "data"
    _store.load(data_dir)
    return _store
