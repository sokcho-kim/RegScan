"""WHO ATC 연동 테스트"""

import asyncio
import sys
import io
from pathlib import Path

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.map.atc import ATCDatabase, ATCMatcher, ATC_LEVEL1_KO, enrich_with_atc, classify_therapeutic_area


async def main():
    print("=" * 60)
    print("WHO ATC 코드 연동 테스트")
    print("=" * 60)

    # 데이터베이스 로드
    print("\n[ATC 데이터베이스 로드]")
    db = ATCDatabase()
    count = await db.load()
    print(f"  - 로드 완료: {count:,}건")

    # 레벨별 통계
    print("\n[레벨별 통계]")
    for level in range(1, 6):
        entries = db.get_by_level(level)
        print(f"  - Level {level}: {len(entries):,}건")

    # 1단계 분류
    print("\n[1단계 분류 (해부학적 주요 그룹)]")
    for code, name_ko in ATC_LEVEL1_KO.items():
        entry = db.get(code)
        if entry:
            children = db.get_children(code)
            print(f"  - {code}: {name_ko} ({len(children)}개 하위 항목)")

    # 코드 조회 테스트
    print("\n[코드 조회 테스트]")
    test_codes = ["L01XC", "N07XX", "L01EX", "A10BJ"]
    for code in test_codes:
        entry = db.get(code)
        if entry:
            print(f"  - {code}: {entry.name}")
            print(f"      치료영역: {entry.therapeutic_area}")
        else:
            print(f"  - {code}: 없음")

    # 이름 검색 테스트
    print("\n[이름 검색 테스트]")
    test_names = ["lecanemab", "semaglutide", "pembrolizumab", "adalimumab", "trastuzumab"]

    matcher = ATCMatcher(db)
    for name in test_names:
        entry = matcher.match_inn(name)
        if entry:
            print(f"  - {name}: {entry.code} ({entry.name})")
            print(f"      치료영역: {entry.therapeutic_area}")
        else:
            print(f"  - {name}: 매칭 없음")

    # 부분 검색 테스트
    print("\n[부분 검색 테스트]")
    query = "mab"  # 단클론 항체 접미사
    results = db.search(query, limit=10)
    print(f"  '{query}' 검색 결과: {len(results)}건")
    for entry in results[:5]:
        print(f"    - {entry.code}: {entry.name}")

    # 치료 영역 조회 테스트
    print("\n[치료 영역 조회]")
    test_codes = ["L01", "N07", "A10", "C09"]
    for code in test_codes:
        area = db.get_therapeutic_area(code)
        print(f"  - {code}: {area}")

    # 보강 기능 테스트
    print("\n[ATC 보강 테스트]")
    test_drugs = [
        ("semaglutide", ""),  # ATC 없이
        ("pembrolizumab", "L01XC18"),  # ATC 있음
        ("adalimumab", ""),  # ATC 없이
        ("unknown_drug", ""),  # 없는 약물
    ]

    for inn, atc in test_drugs:
        info = await enrich_with_atc(inn, atc)
        area = await classify_therapeutic_area(inn, atc)
        print(f"  - {inn}:")
        print(f"      ATC: {info['atc_code']} ({info['atc_name']})")
        print(f"      치료영역: {area}")

    print("\n" + "=" * 60)
    print("테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
