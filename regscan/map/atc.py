"""WHO ATC 코드 연동

Anatomical Therapeutic Chemical (ATC) Classification System
- 1단계: 해부학적 주요 그룹 (A-V)
- 2단계: 치료 하위 그룹
- 3단계: 약리학적 하위 그룹
- 4단계: 화학적 하위 그룹
- 5단계: 화학 물질 (성분)
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx


# ATC 1단계 분류
ATC_LEVEL1 = {
    "A": "Alimentary tract and metabolism",
    "B": "Blood and blood forming organs",
    "C": "Cardiovascular system",
    "D": "Dermatologicals",
    "G": "Genito-urinary system and sex hormones",
    "H": "Systemic hormonal preparations",
    "J": "Antiinfectives for systemic use",
    "L": "Antineoplastic and immunomodulating agents",
    "M": "Musculo-skeletal system",
    "N": "Nervous system",
    "P": "Antiparasitic products",
    "R": "Respiratory system",
    "S": "Sensory organs",
    "V": "Various",
}

# 주요 치료 영역 (한글)
ATC_LEVEL1_KO = {
    "A": "소화기계 및 대사",
    "B": "혈액 및 조혈기관",
    "C": "심혈관계",
    "D": "피부과",
    "G": "비뇨생식기계 및 성호르몬",
    "H": "전신 호르몬제",
    "J": "전신 항감염제",
    "L": "항암제 및 면역조절제",
    "M": "근골격계",
    "N": "신경계",
    "P": "항기생충제",
    "R": "호흡기계",
    "S": "감각기관",
    "V": "기타",
}


@dataclass
class ATCEntry:
    """ATC 항목"""
    code: str
    name: str
    ddd: Optional[float] = None
    unit: str = ""
    admin_route: str = ""
    note: str = ""

    @property
    def level(self) -> int:
        """ATC 레벨 (1-5)"""
        code_len = len(self.code)
        if code_len == 1:
            return 1
        elif code_len == 3:
            return 2
        elif code_len == 4:
            return 3
        elif code_len == 5:
            return 4
        else:
            return 5

    @property
    def level1_code(self) -> str:
        """1단계 코드"""
        return self.code[0] if self.code else ""

    @property
    def level1_name(self) -> str:
        """1단계 이름"""
        return ATC_LEVEL1.get(self.level1_code, "")

    @property
    def level1_name_ko(self) -> str:
        """1단계 한글 이름"""
        return ATC_LEVEL1_KO.get(self.level1_code, "")

    @property
    def therapeutic_area(self) -> str:
        """치료 영역 (1단계 기준)"""
        return self.level1_name_ko or self.level1_name


class ATCDatabase:
    """ATC 코드 데이터베이스"""

    # GitHub raw URL
    ATC_CSV_URL = "https://raw.githubusercontent.com/fabkury/atcd/master/WHO%20ATC-DDD%202021-12-03.csv"

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/atc")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "atc_codes.csv"
        self._entries: dict[str, ATCEntry] = {}
        self._name_index: dict[str, list[str]] = {}  # name -> [codes]

    async def load(self) -> int:
        """
        ATC 데이터 로드

        Returns:
            로드된 항목 수
        """
        # 캐시 파일 확인
        if self.cache_file.exists():
            return self._load_from_cache()

        # 다운로드
        return await self._download_and_cache()

    def _load_from_cache(self) -> int:
        """캐시에서 로드"""
        self._entries.clear()
        self._name_index.clear()

        with open(self.cache_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entry = self._parse_row(row)
                if entry:
                    self._entries[entry.code] = entry
                    self._index_name(entry)

        return len(self._entries)

    async def _download_and_cache(self) -> int:
        """다운로드 및 캐시"""
        async with httpx.AsyncClient() as client:
            response = await client.get(self.ATC_CSV_URL, timeout=30.0)
            response.raise_for_status()

            # 캐시 저장
            with open(self.cache_file, "w", encoding="utf-8") as f:
                f.write(response.text)

            # 파싱
            self._entries.clear()
            self._name_index.clear()

            reader = csv.DictReader(io.StringIO(response.text))
            for row in reader:
                entry = self._parse_row(row)
                if entry:
                    self._entries[entry.code] = entry
                    self._index_name(entry)

        return len(self._entries)

    def _parse_row(self, row: dict) -> Optional[ATCEntry]:
        """CSV 행 파싱"""
        code = row.get("atc_code", "").strip()
        name = row.get("atc_name", "").strip()

        if not code or not name:
            return None

        # DDD 파싱
        ddd = None
        ddd_str = row.get("ddd", "").strip()
        if ddd_str and ddd_str.lower() != "na":
            try:
                ddd = float(ddd_str)
            except ValueError:
                pass

        return ATCEntry(
            code=code,
            name=name,
            ddd=ddd,
            unit=row.get("uom", "").strip(),
            admin_route=row.get("adm_r", "").strip(),
            note=row.get("note", "").strip(),
        )

    def _index_name(self, entry: ATCEntry) -> None:
        """이름 인덱싱"""
        name_lower = entry.name.lower()
        if name_lower not in self._name_index:
            self._name_index[name_lower] = []
        self._name_index[name_lower].append(entry.code)

    def get(self, code: str) -> Optional[ATCEntry]:
        """코드로 조회"""
        return self._entries.get(code.upper())

    def search_by_name(self, name: str) -> list[ATCEntry]:
        """이름으로 검색 (정확 매칭)"""
        name_lower = name.lower()
        codes = self._name_index.get(name_lower, [])
        return [self._entries[code] for code in codes if code in self._entries]

    def search(self, query: str, limit: int = 20) -> list[ATCEntry]:
        """이름으로 검색 (부분 매칭)"""
        query_lower = query.lower()
        results = []

        for name, codes in self._name_index.items():
            if query_lower in name:
                for code in codes:
                    if code in self._entries:
                        results.append(self._entries[code])
                        if len(results) >= limit:
                            return results

        return results

    def get_by_level(self, level: int) -> list[ATCEntry]:
        """레벨별 조회"""
        return [e for e in self._entries.values() if e.level == level]

    def get_children(self, parent_code: str) -> list[ATCEntry]:
        """하위 항목 조회"""
        parent_code = parent_code.upper()
        return [
            e for e in self._entries.values()
            if e.code.startswith(parent_code) and e.code != parent_code
        ]

    def get_therapeutic_area(self, code: str) -> str:
        """치료 영역 조회"""
        entry = self.get(code)
        if entry:
            return entry.therapeutic_area
        # 코드만으로 1단계 추론
        if code and code[0].upper() in ATC_LEVEL1_KO:
            return ATC_LEVEL1_KO[code[0].upper()]
        return ""

    @property
    def count(self) -> int:
        """항목 수"""
        return len(self._entries)


class ATCMatcher:
    """ATC 코드 매칭기"""

    def __init__(self, db: ATCDatabase):
        self.db = db

    def match_inn(self, inn: str) -> Optional[ATCEntry]:
        """
        INN으로 ATC 코드 매칭

        Args:
            inn: International Nonproprietary Name

        Returns:
            매칭된 ATCEntry (없으면 None)
        """
        if not inn:
            return None

        # 정규화
        inn_normalized = inn.lower().strip()

        # 정확 매칭
        matches = self.db.search_by_name(inn_normalized)
        if matches:
            # 5단계 (화학물질) 우선
            level5 = [m for m in matches if m.level == 5]
            if level5:
                return level5[0]
            return matches[0]

        # 부분 매칭
        partial = self.db.search(inn_normalized, limit=5)
        if partial:
            # 5단계 우선
            level5 = [m for m in partial if m.level == 5]
            if level5:
                return level5[0]
            return partial[0]

        return None

    def get_therapeutic_areas(self, inn: str) -> list[str]:
        """
        INN의 치료 영역 목록

        Args:
            inn: International Nonproprietary Name

        Returns:
            치료 영역 목록
        """
        entry = self.match_inn(inn)
        if entry:
            return [entry.therapeutic_area]
        return []


# 싱글톤 인스턴스
_atc_db: Optional[ATCDatabase] = None


async def get_atc_database() -> ATCDatabase:
    """ATC 데이터베이스 싱글톤"""
    global _atc_db
    if _atc_db is None:
        _atc_db = ATCDatabase()
        await _atc_db.load()
    return _atc_db


async def enrich_with_atc(inn: str, current_atc: str = "") -> dict:
    """
    INN에 대한 ATC 정보 보강

    Args:
        inn: International Nonproprietary Name
        current_atc: 기존 ATC 코드 (있으면)

    Returns:
        {
            'atc_code': str,
            'atc_name': str,
            'therapeutic_area': str,
            'therapeutic_area_ko': str,
        }
    """
    db = await get_atc_database()
    matcher = ATCMatcher(db)

    result = {
        'atc_code': current_atc,
        'atc_name': '',
        'therapeutic_area': '',
        'therapeutic_area_ko': '',
    }

    # 기존 ATC 코드가 있으면 정보 조회
    if current_atc:
        entry = db.get(current_atc)
        if entry:
            result['atc_name'] = entry.name
            result['therapeutic_area'] = entry.level1_name
            result['therapeutic_area_ko'] = entry.level1_name_ko
            return result

    # INN으로 매칭
    entry = matcher.match_inn(inn)
    if entry:
        result['atc_code'] = entry.code
        result['atc_name'] = entry.name
        result['therapeutic_area'] = entry.level1_name
        result['therapeutic_area_ko'] = entry.level1_name_ko

    return result


async def classify_therapeutic_area(inn: str, atc_code: str = "") -> str:
    """
    치료 영역 분류 (한글)

    Args:
        inn: International Nonproprietary Name
        atc_code: ATC 코드 (있으면)

    Returns:
        치료 영역 한글명
    """
    info = await enrich_with_atc(inn, atc_code)
    return info.get('therapeutic_area_ko', '')
