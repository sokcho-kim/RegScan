"""MFDS ↔ EMA 성분명 매칭 테스트"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.mfds import MFDSClient
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.map.matcher import IngredientMatcher
from regscan.map.global_status import GlobalStatusBuilder, enrich_with_mfds
from regscan.config import settings


async def find_matching_drugs():
    """EMA 신약과 매칭되는 MFDS 허가 품목 찾기"""
    print("\n" + "=" * 60)
    print("EMA ↔ MFDS 성분명 매칭 분석")
    print("=" * 60)

    # EMA 데이터 로드
    ema_file = Path("data/ema/medicines_20260203.json")
    if not ema_file.exists():
        print("[ERROR] EMA 데이터 없음")
        return

    with open(ema_file, encoding="utf-8") as f:
        ema_raw = json.load(f)

    ema_parser = EMAMedicineParser()
    ema_parsed = ema_parser.parse_many(ema_raw)

    print(f"\n[EMA] {len(ema_parsed)}건 로드")

    # EMA INN 추출
    matcher = IngredientMatcher()
    ema_inns = {}
    for ema in ema_parsed:
        inn = ema.get("inn", "") or ema.get("active_substance", "")
        if inn:
            normalized = matcher.normalize(inn)
            ema_inns[normalized] = {
                "original": inn,
                "name": ema.get("name", ""),
                "status": ema.get("medicine_status", ""),
            }

    print(f"[EMA] 고유 INN: {len(ema_inns)}건")

    # EMA INN 샘플
    print("\n[EMA INN 샘플 (20개)]")
    for i, (norm, info) in enumerate(list(ema_inns.items())[:20], 1):
        print(f"  {i:2}. {info['original']}")

    # MFDS API에서 특정 성분 검색
    print("\n" + "-" * 60)
    print("MFDS에서 EMA 성분 검색 테스트")
    print("-" * 60)

    # 검색할 EMA 성분들 (유명한 약물)
    test_ingredients = [
        "golimumab",       # Simponi (TNF 억제제)
        "adalimumab",      # Humira (TNF 억제제)
        "pembrolizumab",   # Keytruda (면역항암제)
        "nivolumab",       # Opdivo (면역항암제)
        "trastuzumab",     # Herceptin (유방암)
        "bevacizumab",     # Avastin (항암제)
        "lenvatinib",      # Lenvima (갑상선암)
        "sofosbuvir",      # Sovaldi (C형간염)
        "apixaban",        # Eliquis (항응고제)
        "rivaroxaban",     # Xarelto (항응고제)
    ]

    async with MFDSClient() as client:
        mfds_parser = MFDSPermitParser()
        matched = []

        for ingr in test_ingredients:
            # MFDS API에서 검색
            try:
                response = await client.search_permits(
                    item_name=ingr,
                    num_of_rows=5,
                )
                items = response.get("body", {}).get("items", [])

                if items:
                    parsed = mfds_parser.parse_permit(items[0])
                    print(f"  [OK] {ingr}: {len(items)}건 발견")
                    print(f"       → {parsed['item_name'][:40]}...")
                    matched.append({
                        "ema_inn": ingr,
                        "mfds": parsed,
                    })
                else:
                    print(f"  [--] {ingr}: 미발견")

                await asyncio.sleep(0.2)  # Rate limit

            except Exception as e:
                print(f"  [ERR] {ingr}: {e}")

    print(f"\n매칭 결과: {len(matched)} / {len(test_ingredients)} 성분")

    # GlobalRegulatoryStatus 테스트
    if matched:
        print("\n" + "-" * 60)
        print("GlobalRegulatoryStatus 생성 테스트")
        print("-" * 60)

        builder = GlobalStatusBuilder()

        for m in matched[:3]:
            ema_data = None
            norm_inn = matcher.normalize(m["ema_inn"])

            # EMA 데이터 찾기
            for ema in ema_parsed:
                ema_inn = ema.get("inn", "") or ema.get("active_substance", "")
                if matcher.normalize(ema_inn) == norm_inn:
                    ema_data = ema
                    break

            # GlobalRegulatoryStatus 생성
            status = builder.build_from_all(None, ema_data, m["mfds"])

            print(f"\n{m['ema_inn']}:")
            print(f"  EMA: {status.ema.status.value if status.ema else 'N/A'}")
            print(f"  MFDS: {status.mfds.status.value if status.mfds else 'N/A'}")
            print(f"  Score: {status.global_score} ({status.hot_issue_level.value})")
            print(f"  Agencies: {status.approved_agencies}")

    return matched


async def main():
    if not settings.DATA_GO_KR_API_KEY:
        print("[ERROR] DATA_GO_KR_API_KEY 필요")
        return

    await find_matching_drugs()


if __name__ == "__main__":
    asyncio.run(main())
