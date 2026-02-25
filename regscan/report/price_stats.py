"""HIRA 가격 스펙트럼 — 사전 계산 + 조회 모듈

HIRA 원본 JSON(~30,000건 급여)에서 class_no(약효분류코드) × segment(original/generic)별
백분위 가격 통계를 사전 계산하여 hira_price_stats 테이블에 저장.

주요 함수:
    rebuild_price_stats()           — 전체 재구축
    get_price_spectrum()            — 특정 그룹 스펙트럼 조회
    compute_drug_position()         — 약물의 백분위 위치 계산
    check_and_rebuild_if_needed()   — 해시 비교 후 필요 시 재구축
    get_class_name()                — class_no → 한글 분류명
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
from bisect import bisect_left
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, delete

from regscan.config import settings
from regscan.db.database import get_sync_engine
from regscan.db.models import Base, HiraPriceStatsDB

logger = logging.getLogger(__name__)

HIRA_DATA_DIR = settings.BASE_DIR / "data" / "hira"

# ═══════════════════════════════════════════════════════
# KD 약효분류코드 → 한글 분류명 매핑 (120개)
# ═══════════════════════════════════════════════════════

CLASS_NO_NAMES: dict[str, str] = {
    # ── 1xx: 신경계용약 ──
    "110": "전신마취제",
    "111": "최면진정제",
    "112": "항불안제",
    "113": "항간질제",
    "114": "해열진통소염제",
    "115": "각성제·정신신경용제",
    "116": "진훈제",
    "117": "정신신경용제",
    "119": "기타 중추신경용약",
    "121": "골격근이완제",
    "122": "자율신경제",
    "123": "진경제",
    "124": "뇌혈관용제",
    "129": "기타 말초신경용약",
    "131": "안과용제",
    "132": "이비과용제",
    "140": "진통제",
    "141": "합성마약",
    "142": "마약성진통제",
    "149": "기타 감각기관용약",
    # ── 2xx: 순환기관·혈액·체액용약 ──
    "211": "강심제",
    "212": "부정맥용제",
    "213": "이뇨제",
    "214": "혈압강하제",
    "215": "혈관확장제",
    "216": "관상혈관확장제",
    "217": "말초혈관확장제",
    "218": "고지혈증용제",
    "219": "기타 순환기관용약",
    "220": "혈액응고저지제",
    "221": "지혈제",
    "222": "혈액대용제",
    "223": "혈액응고인자",
    "229": "기타 혈액·체액용약",
    "230": "간장용제",
    "231": "해독제",
    "232": "소화성궤양용제",
    "234": "건위소화제",
    "235": "정장제",
    "236": "이담제",
    "237": "소화관운동조절제",
    "238": "제산제",
    "239": "기타 소화기관용약",
    "241": "뇌하수체호르몬제",
    "243": "갑상선·부갑상선호르몬제",
    "244": "단백동화스테로이드",
    "245": "부신호르몬제",
    "247": "남성호르몬제",
    "249": "기타 호르몬제(내분비계)",
    "250": "비타민제",
    "252": "비타민B",
    "255": "비타민제(복합)",
    "256": "비타민C",
    "259": "기타 자양강장제",
    "261": "칼슘제",
    "263": "무기질제제",
    "264": "당뇨병용제(인슐린)",
    "265": "당뇨병용제(경구)",
    "266": "당뇨병합병증용제",
    "269": "기타 대사성의약품",
    # ── 3xx: 호흡기·비뇨생식기·외피용약 ──
    "310": "호흡기관용약",
    "311": "기관지확장제",
    "312": "거담제",
    "313": "진해제",
    "314": "함소흡입제",
    "315": "호흡촉진제",
    "316": "비충혈제거제",
    "319": "기타 호흡기관용약",
    "321": "이뇨제(비뇨기)",
    "322": "요산배설촉진제",
    "323": "비뇨기관용제",
    "325": "생식기관용약",
    "329": "기타 비뇨기관용약",
    "331": "외피용살균소독제",
    "332": "창상보호제",
    "333": "화농성질환용제",
    "339": "기타 외피용약",
    "341": "치과구강용약",
    "349": "기타 치과구강용약",
    # ── 3xx (계속): 대사·면역 ──
    "391": "효소제제",
    "392": "당류제제",
    "394": "유전자재조합의약품",
    "395": "면역억제제",
    "396": "당뇨병용제(기타)",
    "399": "기타 대사성의약품(종합)",
    # ── 4xx: 항생물질·항암제 ──
    "421": "항악성종양제",
    "429": "기타 종양용약",
    "431": "항히스타민제",
    "439": "기타 알레르기용약",
    "490": "항바이러스제(항암)",
    # ── 6xx: 외용약·호르몬제 ──
    "611": "항생물질(외용)",
    "612": "화학요법제(외용)",
    "613": "항진균제(외용)",
    "614": "기생충질환용제",
    "615": "백신류",
    "616": "면역혈청",
    "617": "혈액제제",
    "618": "항생물질(주사)",
    "619": "기타 화학요법제",
    "621": "부신호르몬제(외용)",
    "622": "남성호르몬제(외용)",
    "623": "여성호르몬제(외용)",
    "629": "기타 호르몬제",
    "631": "비타민A",
    "632": "비타민B(주사)",
    "633": "비타민C(주사)",
    "634": "비타민D",
    "635": "비타민E",
    "636": "비타민K",
    "639": "기타 비타민제",
    "641": "자양강장제(주사)",
    "642": "기타 자양강장제",
    # ── 7xx: 진단용약 ──
    "713": "기능검사용제",
    "721": "체외진단용약",
    "722": "방사성의약품",
    "728": "조영제",
    "729": "기타 진단용약",
    "799": "기타 시약",
    # ── 8xx: 생물학적제제 ──
    "811": "혈액분획제제",
    "821": "기타 생물학적제제",
}

# ingredient_code → class_no 역인덱스 캐시 (rebuild 시 생성)
_ingredient_class_cache: dict[str, str] = {}

# 통계 계산을 위한 최소 건수 (미만이면 스펙트럼 미생성)
MIN_COUNT_FOR_STATS = 5


# ═══════════════════════════════════════════════════════
# 1. class_no 매핑
# ═══════════════════════════════════════════════════════

def get_class_name(class_no: str) -> str:
    """class_no → 한글 분류명. 매핑에 없으면 'Unknown Class ({code})' 반환."""
    return CLASS_NO_NAMES.get(str(class_no), f"Unknown Class ({class_no})")


# ═══════════════════════════════════════════════════════
# 2. HIRA 파일 탐색 + 해시
# ═══════════════════════════════════════════════════════

def _find_latest_hira_json(hira_dir: Path | None = None) -> Path | None:
    """data/hira/ 에서 drug_prices_*.json 최신 파일 탐색."""
    d = hira_dir or HIRA_DATA_DIR
    if not d.exists():
        return None
    candidates = sorted(d.glob("drug_prices_*.json"), reverse=True)
    return candidates[0] if candidates else None


def _compute_file_hash(path: Path) -> str:
    """파일 SHA-256 해시 계산."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ═══════════════════════════════════════════════════════
# 3. 데이터 로드 + 통계 계산
# ═══════════════════════════════════════════════════════

def _is_nan(v: Any) -> bool:
    """NaN 체크 (float NaN 또는 None)."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def _load_reimbursed_records(hira_json_path: Path) -> list[dict]:
    """HIRA JSON에서 급여 레코드만 로드."""
    with open(hira_json_path, encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data if r.get("급여기준", "") == "급여"]


def _percentile(sorted_values: list[float], pct: float) -> float:
    """정렬된 리스트에서 백분위 값 계산 (linear interpolation)."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    k = (n - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def _compute_group_stats(
    records: list[dict],
    source_file: str,
    source_hash: str,
) -> list[dict]:
    """급여 레코드 → class_no × segment별 통계 딕셔너리 리스트."""
    from collections import defaultdict

    # 그룹핑
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    ingredient_class_map: dict[str, str] = {}

    for r in records:
        class_no = str(r.get("class_no", ""))
        if not class_no:
            continue

        price = r.get("price_ceiling", 0)
        if not price or _is_nan(price):
            continue

        # segment 판별: 동일 의약품 필드
        dong_il = r.get("동일 의약품")
        segment = "generic" if not _is_nan(dong_il) else "original"

        groups[(class_no, segment)].append(float(price))

        # ingredient_code → class_no 역인덱스
        ingr = r.get("ingredient_code", "")
        if ingr:
            ingredient_class_map[ingr] = class_no

    # 캐시 갱신
    global _ingredient_class_cache
    _ingredient_class_cache = ingredient_class_map

    # 통계 계산
    now = datetime.utcnow()
    results = []
    for (class_no, segment), prices in groups.items():
        if len(prices) < MIN_COUNT_FOR_STATS:
            continue

        sorted_prices = sorted(prices)
        results.append({
            "class_no": class_no,
            "segment": segment,
            "class_name": get_class_name(class_no),
            "count": len(sorted_prices),
            "min_price": sorted_prices[0],
            "p25": _percentile(sorted_prices, 25),
            "p50_median": _percentile(sorted_prices, 50),
            "p75": _percentile(sorted_prices, 75),
            "p90": _percentile(sorted_prices, 90),
            "max_price": sorted_prices[-1],
            "source_file": source_file,
            "source_hash": source_hash,
            "computed_at": now,
        })

    return results


# ═══════════════════════════════════════════════════════
# 4. DB 재구축
# ═══════════════════════════════════════════════════════

def rebuild_price_stats(hira_json_path: Path | None = None) -> int:
    """HIRA JSON → hira_price_stats 테이블 전체 재구축.

    Args:
        hira_json_path: HIRA JSON 경로. None이면 최신 파일 자동 탐색.

    Returns:
        생성된 행 수.

    Raises:
        FileNotFoundError: HIRA JSON 파일을 찾을 수 없는 경우.
    """
    path = hira_json_path or _find_latest_hira_json()
    if path is None or not path.exists():
        raise FileNotFoundError(
            f"HIRA JSON 파일을 찾을 수 없습니다: {hira_json_path or HIRA_DATA_DIR}"
        )

    logger.info("가격 스펙트럼 재구축 시작: %s", path.name)

    source_hash = _compute_file_hash(path)
    records = _load_reimbursed_records(path)
    logger.info("  급여 레코드: %d건", len(records))

    stats_rows = _compute_group_stats(records, path.name, source_hash)
    logger.info("  통계 그룹: %d개 (min_count=%d 미만 제외)", len(stats_rows), MIN_COUNT_FOR_STATS)

    # DB 저장 (sync)
    engine = get_sync_engine()
    Base.metadata.create_all(engine, tables=[HiraPriceStatsDB.__table__])

    from sqlalchemy.orm import Session
    with Session(engine) as session:
        with session.begin():
            # 전체 삭제 후 재삽입
            session.execute(delete(HiraPriceStatsDB))
            for row_data in stats_rows:
                session.add(HiraPriceStatsDB(**row_data))

    # ingredient → class_no 캐시를 JSON으로 영속화
    _save_ingredient_cache(path.parent)

    logger.info("가격 스펙트럼 재구축 완료: %d행 저장", len(stats_rows))
    return len(stats_rows)


# ═══════════════════════════════════════════════════════
# 5. 조회
# ═══════════════════════════════════════════════════════

def get_price_spectrum(class_no: str, segment: str = "original") -> dict | None:
    """특정 class_no + segment의 가격 스펙트럼 조회.

    Returns:
        통계 딕셔너리 또는 None (해당 그룹 없음).
    """
    engine = get_sync_engine()
    Base.metadata.create_all(engine, tables=[HiraPriceStatsDB.__table__])

    from sqlalchemy.orm import Session
    with Session(engine) as session:
        row = session.get(HiraPriceStatsDB, (str(class_no), segment))
        if row is None:
            return None
        return {
            "class_no": row.class_no,
            "class_name": row.class_name,
            "segment": row.segment,
            "count": row.count,
            "min_price": row.min_price,
            "p25": row.p25,
            "p50_median": row.p50_median,
            "p75": row.p75,
            "p90": row.p90,
            "max_price": row.max_price,
        }


def compute_drug_position(
    price: float,
    class_no: str,
    segment: str = "original",
    hira_json_path: Path | None = None,
) -> str | None:
    """약물 가격이 스펙트럼 내 어디에 위치하는지 백분위로 계산.

    HIRA 원본에서 해당 class_no + segment의 전체 가격 리스트를 로드,
    bisect로 위치를 산출한다.

    Returns:
        "P72" 등. 데이터 부족 시 None.
    """
    path = hira_json_path or _find_latest_hira_json()
    if path is None or not path.exists():
        return None

    records = _load_reimbursed_records(path)
    prices = []
    for r in records:
        if str(r.get("class_no", "")) != str(class_no):
            continue
        dong_il = r.get("동일 의약품")
        rec_segment = "generic" if not _is_nan(dong_il) else "original"
        if rec_segment != segment:
            continue
        p = r.get("price_ceiling", 0)
        if p and not _is_nan(p):
            prices.append(float(p))

    if len(prices) < MIN_COUNT_FOR_STATS:
        return None

    sorted_prices = sorted(prices)
    pos = bisect_left(sorted_prices, price)
    pct = round(pos / len(sorted_prices) * 100)
    return f"P{pct}"


# ═══════════════════════════════════════════════════════
# 6. 변경 감지 + 자동 재구축
# ═══════════════════════════════════════════════════════

def check_and_rebuild_if_needed(hira_json_path: Path | None = None) -> bool:
    """HIRA 파일 SHA-256 해시 비교 → 변경 시 재구축.

    Returns:
        True: 재구축 수행됨.
        False: 변경 없어 스킵 (또는 파일 없음).
    """
    path = hira_json_path or _find_latest_hira_json()
    if path is None or not path.exists():
        logger.warning("HIRA JSON 파일 없음 — 가격 스펙트럼 스킵")
        return False

    new_hash = _compute_file_hash(path)

    # 현재 DB의 해시 확인
    engine = get_sync_engine()
    Base.metadata.create_all(engine, tables=[HiraPriceStatsDB.__table__])

    from sqlalchemy.orm import Session
    with Session(engine) as session:
        row = session.execute(
            select(HiraPriceStatsDB.source_hash).limit(1)
        ).scalar_one_or_none()

    if row == new_hash:
        logger.debug("HIRA 파일 변경 없음 — 가격 스펙트럼 재구축 스킵")
        return False

    logger.info("HIRA 파일 변경 감지 — 가격 스펙트럼 재구축")
    rebuild_price_stats(path)
    return True


# ═══════════════════════════════════════════════════════
# 7. ingredient_code → class_no 역인덱스
# ═══════════════════════════════════════════════════════

_INGREDIENT_CACHE_FILE = "ingredient_class_map.json"


def _save_ingredient_cache(hira_dir: Path) -> None:
    """ingredient_code → class_no 매핑을 JSON 캐시로 저장."""
    if not _ingredient_class_cache:
        return
    cache_path = hira_dir / _INGREDIENT_CACHE_FILE
    cache_path.write_text(
        json.dumps(_ingredient_class_cache, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug("ingredient→class_no 캐시 저장: %d건", len(_ingredient_class_cache))


def _load_ingredient_cache(hira_dir: Path | None = None) -> dict[str, str]:
    """ingredient_code → class_no 매핑 캐시 로드."""
    global _ingredient_class_cache
    if _ingredient_class_cache:
        return _ingredient_class_cache

    d = hira_dir or HIRA_DATA_DIR
    cache_path = d / _INGREDIENT_CACHE_FILE
    if cache_path.exists():
        _ingredient_class_cache = json.loads(
            cache_path.read_text(encoding="utf-8")
        )
        logger.debug("ingredient→class_no 캐시 로드: %d건", len(_ingredient_class_cache))
    return _ingredient_class_cache


def get_class_no_for_ingredient(ingredient_code: str) -> str | None:
    """ingredient_code → class_no 조회. 캐시 없으면 로드 시도."""
    cache = _load_ingredient_cache()
    return cache.get(ingredient_code)


# ═══════════════════════════════════════════════════════
# 8. therapeutic_areas → class_no 역매핑 (미급여약 fallback)
# ═══════════════════════════════════════════════════════

_THERAPEUTIC_AREA_TO_CLASS: dict[str, str] = {
    "oncology": "421",
    "haematology": "421",
    "immunology": "395",
    "rare_disease": "399",
    "metabolic": "396",
    "cardiovascular": "214",
    "neurology": "117",
    "respiratory": "311",
    "ophthalmology": "131",
    "gastroenterology": "232",
    "endocrinology": "249",
    "dermatology": "339",
    "urology": "323",
    "anti-infective": "618",
    "vaccines": "615",
}


def get_class_no_for_therapeutic_area(therapeutic_area: str) -> str | None:
    """therapeutic_area 문자열 → 대표 class_no. 매핑 없으면 None."""
    ta = therapeutic_area.lower().strip()
    return _THERAPEUTIC_AREA_TO_CLASS.get(ta)
