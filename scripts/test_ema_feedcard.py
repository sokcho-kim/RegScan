"""EMA -> FeedCard 변환 테스트"""

import asyncio
import json
import sys
import io
from pathlib import Path

# Windows 콘솔 UTF-8 출력
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.ema import EMAClient
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.scan.signal_generator import SignalGenerator
from regscan.models import SourceType


async def test_ema_to_feedcard():
    """EMA 데이터 -> FeedCard 변환 테스트"""
    print("=" * 60)
    print("EMA -> FeedCard Conversion Test")
    print("=" * 60)

    # 1. EMA 데이터 수집
    print("\n[1] Fetching EMA medicines...")
    async with EMAClient() as client:
        medicines = await client.fetch_medicines()
    print(f"    -> {len(medicines)} medicines fetched")

    # 2. 파싱
    print("\n[2] Parsing...")
    parser = EMAMedicineParser()
    parsed = parser.parse_many(medicines[:10])  # 샘플 10건
    print(f"    -> {len(parsed)} parsed")

    # 3. FeedCard 변환
    print("\n[3] Converting to FeedCards...")
    generator = SignalGenerator(use_llm=False)  # LLM 없이 테스트

    cards = []
    for data in parsed:
        card = await generator.generate(data, SourceType.EMA_MEDICINE)
        cards.append(card)

    print(f"    -> {len(cards)} FeedCards created")

    # 4. 결과 출력
    print("\n" + "=" * 60)
    print("Sample FeedCards")
    print("=" * 60)

    for i, card in enumerate(cards[:5], 1):
        print(f"\n--- Card {i} ---")
        print(f"ID: {card.id}")
        print(f"Title: {card.title}")
        print(f"Summary: {card.summary}")
        print(f"Impact: {card.impact_level.value}")
        print(f"Change: {card.change_type.value}")
        print(f"Domains: {[d.value for d in card.domain]}")
        print(f"Tags: {card.tags[:5]}")
        print(f"Roles: {[r.value for r in card.target_roles]}")
        print(f"Published: {card.published_at.strftime('%Y-%m-%d')}")
        print(f"URL: {card.citation.source_url}")

    # 5. 통계
    print("\n" + "=" * 60)
    print("Statistics")
    print("=" * 60)

    impact_counts = {}
    for card in cards:
        level = card.impact_level.value
        impact_counts[level] = impact_counts.get(level, 0) + 1

    print("\nImpact Level Distribution:")
    for level, count in sorted(impact_counts.items()):
        print(f"  {level}: {count}")

    # HIGH 임팩트 카드 목록
    high_impact = [c for c in cards if c.impact_level.value == "HIGH"]
    if high_impact:
        print(f"\nHIGH Impact Cards ({len(high_impact)}):")
        for card in high_impact:
            print(f"  - {card.title}")

    return cards


async def test_orphan_designation():
    """희귀의약품 지정 테스트"""
    print("\n" + "=" * 60)
    print("EMA Orphan Designation -> FeedCard Test")
    print("=" * 60)

    # 수집
    async with EMAClient() as client:
        orphans = await client.fetch_orphan_designations()
    print(f"\n{len(orphans)} orphan designations fetched")

    # 파싱
    from regscan.parse.ema_parser import EMAOrphanParser
    parser = EMAOrphanParser()
    parsed = parser.parse_many(orphans[:5])

    # 변환
    generator = SignalGenerator(use_llm=False)
    for data in parsed:
        card = await generator.generate(data, SourceType.EMA_ORPHAN)
        print(f"\n[{card.impact_level.value}] {card.title}")
        print(f"  -> {card.summary[:80]}")


async def main():
    """메인"""
    await test_ema_to_feedcard()
    await test_orphan_designation()


if __name__ == "__main__":
    asyncio.run(main())
