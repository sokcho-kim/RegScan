"""MFDS GlobalRegulatoryStatus 통합 테스트"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.mfds import MFDSPermitIngestor
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.map.global_status import GlobalStatusBuilder, enrich_with_mfds
from regscan.config import settings


async def test_mfds_to_global_status():
    """MFDS 데이터를 GlobalRegulatoryStatus로 변환"""
    print("\n" + "=" * 60)
    print("MFDS → GlobalRegulatoryStatus 변환 테스트")
    print("=" * 60)

    # MFDS 샘플 데이터 수집
    print("\n[1] MFDS 샘플 수집 (50건)...")
    ingestor = MFDSPermitIngestor(max_items=50)
    raw_items = await ingestor.fetch()
    print(f"    수집: {len(raw_items)}건")

    # 파싱
    print("\n[2] MFDS 데이터 파싱...")
    parser = MFDSPermitParser()
    parsed_items = parser.parse_many(raw_items)
    print(f"    파싱: {len(parsed_items)}건")

    # 신약만 필터링
    new_drugs = [p for p in parsed_items if p.get("is_new_drug")]
    print(f"    신약: {len(new_drugs)}건")

    # GlobalRegulatoryStatus 변환
    print("\n[3] GlobalRegulatoryStatus 변환...")
    builder = GlobalStatusBuilder()

    statuses = []
    for parsed in parsed_items[:10]:  # 샘플 10건
        status = builder.from_mfds(parsed)
        statuses.append(status)

    print(f"    변환: {len(statuses)}건")

    # 결과 출력
    print("\n" + "-" * 60)
    print("변환 결과 샘플")
    print("-" * 60)

    for i, status in enumerate(statuses[:5], 1):
        print(f"\n[{i}] {status.inn or '(성분명 없음)'}")
        if status.mfds:
            print(f"    MFDS 상태: {status.mfds.status.value}")
            print(f"    허가일: {status.mfds.approval_date}")
            print(f"    브랜드명: {status.mfds.brand_name[:30]}...")
        print(f"    Global Score: {status.global_score}")
        print(f"    Level: {status.hot_issue_level.value}")

    return statuses


async def test_enrich_existing():
    """기존 FDA+EMA 데이터에 MFDS 추가"""
    print("\n" + "=" * 60)
    print("기존 GlobalRegulatoryStatus에 MFDS 추가 테스트")
    print("=" * 60)

    # 기존 FDA+EMA 통합 리포트 확인
    ema_data_file = Path("data/ema/medicines_20260203.json")
    fda_data_file = Path("data/fda/approvals_20260203.json")

    if not ema_data_file.exists():
        print("[SKIP] EMA 데이터 파일 없음")
        return

    # EMA 데이터 로드
    print("\n[1] 기존 데이터 로드...")
    with open(ema_data_file, encoding="utf-8") as f:
        ema_raw = json.load(f)
    print(f"    EMA: {len(ema_raw)}건")

    # MFDS 수집
    print("\n[2] MFDS 수집 (1000건)...")
    ingestor = MFDSPermitIngestor(max_items=1000)
    mfds_raw = await ingestor.fetch()
    print(f"    MFDS: {len(mfds_raw)}건")

    # 파싱
    from regscan.parse.ema_parser import EMAMedicineParser
    from regscan.map.global_status import merge_by_inn

    ema_parser = EMAMedicineParser()
    mfds_parser = MFDSPermitParser()

    ema_parsed = ema_parser.parse_many(ema_raw[:100])  # 샘플 100건
    mfds_parsed = mfds_parser.parse_many(mfds_raw)

    print(f"\n[3] 파싱 완료")
    print(f"    EMA: {len(ema_parsed)}건")
    print(f"    MFDS: {len(mfds_parsed)}건")

    # 먼저 EMA만으로 GlobalStatus 생성
    print("\n[4] EMA → GlobalRegulatoryStatus...")
    builder = GlobalStatusBuilder()
    statuses = [builder.from_ema(e) for e in ema_parsed]
    print(f"    생성: {len(statuses)}건")

    # MFDS 추가
    print("\n[5] MFDS 매칭 및 추가...")
    enriched = enrich_with_mfds(statuses, mfds_parsed)

    # 매칭 통계
    mfds_matched = sum(1 for s in enriched if s.mfds is not None)
    print(f"    MFDS 매칭: {mfds_matched}건 / {len(enriched)}건")

    # 매칭된 예시 출력
    print("\n" + "-" * 60)
    print("FDA+EMA+MFDS 매칭 예시")
    print("-" * 60)

    matched = [s for s in enriched if s.mfds is not None][:5]
    for i, status in enumerate(matched, 1):
        print(f"\n[{i}] {status.inn}")
        print(f"    EMA: {status.ema.status.value if status.ema else '-'}")
        print(f"    MFDS: {status.mfds.status.value}")
        print(f"    MFDS 허가일: {status.mfds.approval_date}")
        print(f"    Score: {status.global_score} ({status.hot_issue_level.value})")

    return enriched


async def main():
    print("=" * 60)
    print(" MFDS GlobalRegulatoryStatus 통합 테스트")
    print("=" * 60)

    if not settings.DATA_GO_KR_API_KEY:
        print("\n[ERROR] DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return

    # 테스트 1: MFDS 단독 변환
    await test_mfds_to_global_status()

    # 테스트 2: 기존 데이터에 MFDS 추가
    await test_enrich_existing()

    print("\n" + "=" * 60)
    print(" 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
