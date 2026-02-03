"""MFDS 전체 데이터 수집 및 EMA 매칭 테스트"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.mfds import MFDSPermitIngestor
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.map.matcher import IngredientMatcher
from regscan.map.global_status import GlobalStatusBuilder, enrich_with_mfds, merge_global_status
from regscan.config import settings


async def collect_mfds_sample(max_items: int = 5000):
    """MFDS 샘플 수집"""
    print(f"\n[MFDS] {max_items:,}건 수집 시작...")

    ingestor = MFDSPermitIngestor(max_items=max_items)
    items = await ingestor.fetch()

    # 저장
    output_dir = Path("data/mfds")
    output_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    output_file = output_dir / f"permits_{today}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2, default=str)

    print(f"[MFDS] 저장: {output_file} ({len(items):,}건)")
    return items


def analyze_matching(mfds_items: list, ema_items: list):
    """MFDS ↔ EMA 매칭 분석"""
    print("\n" + "=" * 60)
    print("MFDS ↔ EMA 성분 매칭 분석")
    print("=" * 60)

    # 파싱
    mfds_parser = MFDSPermitParser()
    ema_parser = EMAMedicineParser()

    mfds_parsed = mfds_parser.parse_many(mfds_items)
    ema_parsed = ema_parser.parse_many(ema_items)

    print(f"\nMFDS: {len(mfds_parsed):,}건")
    print(f"EMA: {len(ema_parsed):,}건")

    # 정규화 및 인덱싱
    matcher = IngredientMatcher()

    mfds_inns = set()
    for m in mfds_parsed:
        inn = m.get("main_ingredient", "")
        if inn:
            mfds_inns.add(matcher.normalize(inn))

    ema_inns = set()
    for e in ema_parsed:
        inn = e.get("inn", "") or e.get("active_substance", "")
        if inn:
            ema_inns.add(matcher.normalize(inn))

    print(f"\nMFDS 고유 성분: {len(mfds_inns):,}개")
    print(f"EMA 고유 성분: {len(ema_inns):,}개")

    # 매칭
    common = mfds_inns & ema_inns
    print(f"\n공통 성분: {len(common)}개")

    if common:
        print("\n공통 성분 샘플 (20개):")
        for i, inn in enumerate(sorted(list(common))[:20], 1):
            print(f"  {i:2}. {inn}")

    return {
        "mfds_parsed": mfds_parsed,
        "ema_parsed": ema_parsed,
        "common_inns": common,
    }


def create_global_status(analysis: dict):
    """GlobalRegulatoryStatus 생성"""
    print("\n" + "=" * 60)
    print("GlobalRegulatoryStatus 생성 (EMA + MFDS)")
    print("=" * 60)

    mfds_parsed = analysis["mfds_parsed"]
    ema_parsed = analysis["ema_parsed"]

    # 전체 병합
    print("\n[1] 전체 데이터 병합...")
    statuses = merge_global_status(
        fda_list=[],  # FDA 없이 테스트
        ema_list=ema_parsed,
        mfds_list=mfds_parsed,
    )

    print(f"    생성: {len(statuses):,}건")

    # 통계
    both_approved = [s for s in statuses if s.ema and s.mfds]
    ema_only = [s for s in statuses if s.ema and not s.mfds]
    mfds_only = [s for s in statuses if s.mfds and not s.ema]

    print(f"\n[통계]")
    print(f"  EMA + MFDS 둘 다 승인: {len(both_approved)}건")
    print(f"  EMA만 승인: {len(ema_only)}건")
    print(f"  MFDS만 승인: {len(mfds_only)}건")

    # 샘플 출력
    if both_approved:
        print(f"\n[EMA + MFDS 공통 승인 샘플]")
        for status in both_approved[:10]:
            ema_date = status.ema.approval_date if status.ema else None
            mfds_date = status.mfds.approval_date if status.mfds else None
            print(f"  {status.inn}")
            print(f"    EMA: {ema_date} | MFDS: {mfds_date}")
            print(f"    Score: {status.global_score} ({status.hot_issue_level.value})")

    return statuses


async def main():
    if not settings.DATA_GO_KR_API_KEY:
        print("[ERROR] DATA_GO_KR_API_KEY 필요")
        return

    # 1. MFDS 수집 (또는 기존 파일 사용)
    mfds_file = Path("data/mfds/permits_20260203.json")

    if mfds_file.exists():
        print(f"[MFDS] 기존 파일 사용: {mfds_file}")
        with open(mfds_file, encoding="utf-8") as f:
            mfds_items = json.load(f)
    else:
        mfds_items = await collect_mfds_sample(max_items=5000)

    # 2. EMA 로드
    ema_file = Path("data/ema/medicines_20260203.json")
    if not ema_file.exists():
        print("[ERROR] EMA 데이터 없음")
        return

    with open(ema_file, encoding="utf-8") as f:
        ema_items = json.load(f)

    # 3. 매칭 분석
    analysis = analyze_matching(mfds_items, ema_items)

    # 4. GlobalRegulatoryStatus 생성
    if analysis["common_inns"]:
        statuses = create_global_status(analysis)

    print("\n" + "=" * 60)
    print(" 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
