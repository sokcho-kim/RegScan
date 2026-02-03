"""EMA 데이터 수집 스크립트"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.ema import EMAClient, EMAMedicineIngestor
from regscan.parse.ema_parser import EMAMedicineParser, EMAOrphanParser, EMAShortageParser


async def test_ema_connection():
    """EMA API connection test"""
    print("=" * 60)
    print("EMA API Connection Test")
    print("=" * 60)

    async with EMAClient() as client:
        # Medicines list
        print("\n[1] Fetching medicines...")
        medicines = await client.fetch_medicines()
        print(f"    -> Total: {len(medicines)} medicines")

        if medicines:
            # Sample data
            sample = medicines[0]
            inn = sample.get('international_non_proprietary_name_common_name', 'N/A')
            atc = sample.get('atc_code_human', 'N/A')
            mah = sample.get('marketing_authorisation_developer_applicant_holder', 'N/A')

            print(f"\n    Sample (first item):")
            print(f"    - Name: {sample.get('name_of_medicine', 'N/A')}")
            print(f"    - INN: {inn}")
            print(f"    - ATC: {atc}")
            print(f"    - Status: {sample.get('medicine_status', 'N/A')}")
            print(f"    - MAH: {mah}")
            print(f"    - MA Date: {sample.get('marketing_authorisation_date', 'N/A')}")

        # Orphan designations
        print("\n[2] Fetching orphan designations...")
        orphans = await client.fetch_orphan_designations()
        print(f"    -> Total: {len(orphans)} designations")

        # Supply shortages
        print("\n[3] Fetching supply shortages...")
        shortages = await client.fetch_shortages()
        print(f"    -> Total: {len(shortages)} shortages")

        # DHPC
        print("\n[4] Fetching DHPC (safety communications)...")
        dhpc = await client.fetch_dhpc()
        print(f"    -> Total: {len(dhpc)} communications")

        return {
            "medicines": len(medicines),
            "orphans": len(orphans),
            "shortages": len(shortages),
            "dhpc": len(dhpc),
        }


async def collect_and_parse():
    """EMA 데이터 수집 및 파싱"""
    print("\n" + "=" * 60)
    print("EMA 데이터 수집 및 파싱")
    print("=" * 60)

    # 수집
    ingestor = EMAMedicineIngestor()
    raw_medicines = await ingestor.fetch()
    print(f"\n[수집] {len(raw_medicines)}건 수집됨")

    # 파싱
    parser = EMAMedicineParser()
    parsed = parser.parse_many(raw_medicines[:10])  # 샘플 10건만

    print(f"[파싱] {len(parsed)}건 파싱됨")

    # 파싱 결과 샘플 출력
    if parsed:
        print("\n[파싱 결과 샘플]")
        sample = parsed[0]
        for key in ["name", "inn", "atc_code", "medicine_status", "approval_date", "sponsor", "is_orphan"]:
            print(f"    - {key}: {sample.get(key, 'N/A')}")

    return parsed


async def save_sample_data():
    """샘플 데이터 저장"""
    print("\n" + "=" * 60)
    print("샘플 데이터 저장")
    print("=" * 60)

    output_dir = Path(__file__).parent.parent / "data" / "ema"
    output_dir.mkdir(parents=True, exist_ok=True)

    async with EMAClient() as client:
        # 의약품 데이터 저장
        medicines = await client.fetch_medicines()
        medicines_file = output_dir / f"medicines_{datetime.now().strftime('%Y%m%d')}.json"
        with open(medicines_file, "w", encoding="utf-8") as f:
            json.dump(medicines, f, ensure_ascii=False, indent=2)
        print(f"[저장] {medicines_file} ({len(medicines)}건)")

        # 희귀의약품 데이터 저장
        orphans = await client.fetch_orphan_designations()
        orphans_file = output_dir / f"orphans_{datetime.now().strftime('%Y%m%d')}.json"
        with open(orphans_file, "w", encoding="utf-8") as f:
            json.dump(orphans, f, ensure_ascii=False, indent=2)
        print(f"[저장] {orphans_file} ({len(orphans)}건)")

        # 공급 부족 데이터 저장
        shortages = await client.fetch_shortages()
        shortages_file = output_dir / f"shortages_{datetime.now().strftime('%Y%m%d')}.json"
        with open(shortages_file, "w", encoding="utf-8") as f:
            json.dump(shortages, f, ensure_ascii=False, indent=2)
        print(f"[저장] {shortages_file} ({len(shortages)}건)")

    return {
        "medicines": str(medicines_file),
        "orphans": str(orphans_file),
        "shortages": str(shortages_file),
    }


async def find_recent_approvals(days: int = 30):
    """최근 승인 의약품 찾기"""
    print("\n" + "=" * 60)
    print(f"Recent {days} days approvals")
    print("=" * 60)

    from datetime import timedelta

    cutoff_date = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    async with EMAClient() as client:
        medicines = await client.fetch_medicines()

    parser = EMAMedicineParser()
    parsed = parser.parse_many(medicines)

    # 최근 승인 필터링 (marketing_authorisation_date 사용)
    recent = []
    for med in parsed:
        ma_date = med.get("marketing_authorisation_date", "")
        if ma_date and ma_date >= cutoff_str:
            recent.append(med)

    # 날짜순 정렬
    recent.sort(key=lambda x: x.get("marketing_authorisation_date", ""), reverse=True)

    print(f"\nTotal: {len(recent)} medicines\n")

    for med in recent[:20]:  # 상위 20건
        ma_date = med.get("marketing_authorisation_date", "N/A")
        name = med.get("name", "N/A")
        inn = med.get("inn", "") or med.get("active_substance", "N/A")
        mah = med.get("sponsor", "N/A")

        print(f"  [{ma_date}] {name}")
        print(f"      INN: {inn}")
        print(f"      MAH: {mah}")
        if med.get("is_orphan"):
            print(f"      ** Orphan Medicine")
        if med.get("is_biosimilar"):
            print(f"      ** Biosimilar")
        print()

    return recent


async def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="EMA 데이터 수집")
    parser.add_argument("--test", action="store_true", help="연결 테스트만 실행")
    parser.add_argument("--save", action="store_true", help="데이터 저장")
    parser.add_argument("--recent", type=int, default=0, help="최근 N일 승인 조회")

    args = parser.parse_args()

    if args.test:
        await test_ema_connection()
    elif args.save:
        await save_sample_data()
    elif args.recent > 0:
        await find_recent_approvals(days=args.recent)
    else:
        # 기본: 전체 테스트
        await test_ema_connection()
        await collect_and_parse()


if __name__ == "__main__":
    asyncio.run(main())
