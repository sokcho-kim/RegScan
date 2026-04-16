"""의약품 코드 다단계 매칭 — ATC → EDI → 품목기준코드 → INN fallback

4단계 fallback 체인:
  1순위: ATC 코드 (EMA 직접 제공, FDA→RxNorm→ATC는 별도 태스크)
  2순위: 제품코드(EDI_CODE) — IngredientBridge → raw_data["제품코드"]
  3순위: 품목기준코드 — 약가마스터 경유 (TODO)
  4순위: INN 문자열 — IngredientBridge 기존 매칭

Usage:
    resolver = get_code_resolver()
    match = resolver.resolve("pembrolizumab", atc_code="L01FF02")
    # match.edi_code = "655501901", match.match_tier = 1
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 매칭 결과
# ════════════════════════════════════════════════════════════════════

@dataclass
class DrugCodeMatch:
    """다단계 매칭 결과."""
    inn: str
    atc_code: str = ""
    edi_code: str = ""             # = HIRA 제품코드 (9자리)
    ingredient_code: str = ""      # HIRA 주성분코드 (9자리, 예: 639001BIJ)
    item_seq: str = ""             # MFDS 품목기준코드
    match_tier: int = 0            # 1=ATC, 2=EDI, 3=품목기준코드, 4=INN, 0=미매칭
    match_detail: str = ""
    hira_status: str = ""          # reimbursed / non_reimbursed / ...
    price_ceiling: Optional[float] = None
    raw_data: dict = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return self.match_tier > 0

    @property
    def tier_label(self) -> str:
        labels = {1: "ATC", 2: "EDI", 3: "PRDLST", 4: "INN", 0: "unmatched"}
        return labels.get(self.match_tier, "unknown")


# ════════════════════════════════════════════════════════════════════
# DrugCodeResolver
# ════════════════════════════════════════════════════════════════════

class DrugCodeResolver:
    """4단계 fallback 매칭 — ATC → EDI → 품목기준코드 → INN"""

    def __init__(self):
        # ATC코드 → {edi_code, ingredient_code, product_name}
        self._atc_to_codes: dict[str, list[dict]] = {}
        # IngredientBridge (lazy load)
        self._bridge = None
        self._loaded = False

    def load(
        self,
        atc_csv: str | Path | None = None,
        bridge_master: str | Path | None = None,
        bridge_atc: str | Path | None = None,
        bridge_hira: str | Path | None = None,
    ) -> None:
        """데이터 로드."""
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"

        # 1) ATC 매핑 인덱스
        atc_path = Path(atc_csv) if atc_csv else (
            data_dir / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"
        )
        if atc_path.exists():
            self._load_atc_index(atc_path)

        # 2) IngredientBridge
        self._load_bridge(data_dir, bridge_master, bridge_atc, bridge_hira)
        self._loaded = True

    def _load_atc_index(self, path: Path) -> None:
        """HIRA ATC 매핑 CSV → ATC코드 → 제품코드/주성분코드 인덱스."""
        count = 0
        with open(path, "r", encoding="cp949", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                atc = (row.get("ATC코드", "") or "").strip()
                edi = (row.get("제품코드", "") or "").strip().zfill(9)  # 9자리 0-padding
                ingr = (row.get("주성분코드", "") or "").strip()
                name = (row.get("제품명", "") or "").strip()
                if not atc or not edi:
                    continue
                if atc not in self._atc_to_codes:
                    self._atc_to_codes[atc] = []
                self._atc_to_codes[atc].append({
                    "edi_code": edi,
                    "ingredient_code": ingr,
                    "product_name": name,
                })
                count += 1
        logger.info("[CodeResolver] ATC 인덱스 로드: %d건, 고유 ATC: %d개", count, len(self._atc_to_codes))

    def _load_bridge(
        self, data_dir: Path,
        master: str | Path | None,
        atc: str | Path | None,
        hira: str | Path | None,
    ) -> None:
        """IngredientBridge 로드 (기존 싱글턴 재사용 시도)."""
        try:
            from regscan.stream.briefing import _get_bridge
            self._bridge = _get_bridge()
        except Exception:
            pass

        if self._bridge is not None:
            return

        try:
            from regscan.map.ingredient_bridge import IngredientBridge
            bridge = IngredientBridge()

            master_path = Path(master) if master else data_dir / "bridge" / "yakga_ingredient_master.csv"
            atc_path = Path(atc) if atc else data_dir / "bridge" / "건강보험심사평가원_ATC코드_매핑_목록_20250630.csv"
            hira_dir = data_dir / "hira"
            hira_files = sorted(hira_dir.glob("drug_prices_*.json"), reverse=True) if hira_dir.exists() else []

            if master_path.exists():
                bridge.load_master(master_path)
            if atc_path.exists():
                bridge.load_atc_mapping(atc_path)
            if hira_files:
                bridge.load_hira(hira_files[0])

            self._bridge = bridge
        except Exception as e:
            logger.warning("[CodeResolver] Bridge 로드 실패: %s", e)

    def resolve(
        self,
        inn: str,
        atc_code: str = "",
        rxcui: str = "",
    ) -> DrugCodeMatch:
        """다단계 매칭 실행.

        Args:
            inn: 영문 INN (예: "pembrolizumab")
            atc_code: ATC 코드 (예: "L01FF02", EMA에서 직접 제공)
            rxcui: RxNorm CUI (향후 사용, 현재 미구현)

        Returns:
            DrugCodeMatch — 매칭 결과
        """
        if not self._loaded:
            self.load()

        # ── 1순위: ATC 코드 매칭 ──
        if atc_code:
            result = self._match_by_atc(atc_code, inn)
            if result:
                return result

        # ── 2순위: Bridge → 제품코드(EDI) ──
        bridge_match = self._match_by_bridge(inn)
        if bridge_match and bridge_match.edi_code:
            return bridge_match

        # ── 3순위: 품목기준코드 경유 (TODO — 약가마스터 로드 필요) ──
        # 현재 미구현, Bridge가 이미 약가마스터 일부를 커버

        # ── 4순위: INN 문자열 (Bridge 결과, edi_code 없어도 status 있으면) ──
        if bridge_match and bridge_match.hira_status and bridge_match.hira_status != "unmatched":
            bridge_match.match_tier = 4
            bridge_match.match_detail = "INN fallback (Bridge matched, no EDI code)"
            return bridge_match

        return DrugCodeMatch(
            inn=inn,
            match_tier=0,
            match_detail="unmatched",
        )

    def _match_by_atc(self, atc_code: str, inn: str) -> Optional[DrugCodeMatch]:
        """ATC 코드로 HIRA 제품코드 매칭."""
        entries = self._atc_to_codes.get(atc_code)
        if not entries:
            return None

        # 복수 매칭 시 첫 번째 사용 (동일 ATC에 여러 제품 가능)
        # TODO: INN으로 추가 필터링
        entry = entries[0]

        # Bridge에서 가격/상태 보충
        hira_status = ""
        price = None
        raw = {}
        if self._bridge:
            try:
                br = self._bridge.lookup(inn)
                hira_status = br.status.value
                price = br.price_ceiling
                raw = br.raw_data or {}
            except Exception:
                pass

        return DrugCodeMatch(
            inn=inn,
            atc_code=atc_code,
            edi_code=entry["edi_code"],
            ingredient_code=entry.get("ingredient_code", ""),
            match_tier=1,
            match_detail=f"ATC {atc_code} → EDI {entry['edi_code']}",
            hira_status=hira_status,
            price_ceiling=price,
            raw_data=raw,
        )

    def _match_by_bridge(self, inn: str) -> Optional[DrugCodeMatch]:
        """IngredientBridge로 INN → HIRA 매칭."""
        if not self._bridge:
            return None

        try:
            result = self._bridge.lookup(inn)
        except Exception:
            return None

        if result.match_method == "unmatched":
            return DrugCodeMatch(
                inn=inn,
                hira_status="unmatched",
                match_tier=0,
                match_detail="Bridge unmatched",
            )

        edi_code = (result.raw_data or {}).get("제품코드", "")
        return DrugCodeMatch(
            inn=inn,
            edi_code=edi_code,
            ingredient_code=result.ingredient_code,
            match_tier=2,
            match_detail=f"Bridge {result.match_method} → EDI {edi_code}",
            hira_status=result.status.value,
            price_ceiling=result.price_ceiling,
            raw_data=result.raw_data or {},
        )


# ════════════════════════════════════════════════════════════════════
# 싱글턴
# ════════════════════════════════════════════════════════════════════

_resolver_instance: Optional[DrugCodeResolver] = None


def get_code_resolver() -> DrugCodeResolver:
    """DrugCodeResolver 싱글턴."""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = DrugCodeResolver()
        _resolver_instance.load()
    return _resolver_instance
