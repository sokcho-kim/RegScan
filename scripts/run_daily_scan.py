"""일간 규제 동향 스캔 실행

매일 아침 실행하여 FDA/EMA/MFDS 신규 승인을 체크합니다.

사용법:
    python scripts/run_daily_scan.py
    python scripts/run_daily_scan.py --days 7  # 최근 7일
    python scripts/run_daily_scan.py --generate-briefing  # 핫이슈 브리핑 생성
"""

import sys
import io
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.monitor import DailyScanner, ScanResult


OUTPUT_DIR = Path(__file__).parent.parent / "output" / "daily_scan"


def print_result(result: ScanResult):
    """스캔 결과 출력"""
    print("=" * 70)
    print(f"  RegScan 일간 스캔 결과 - {result.scan_date}")
    print("=" * 70)
    print()

    # 요약
    print(f"[요약]")
    print(f"  FDA 신규 승인:  {len(result.fda_new)}건")
    print(f"  EMA 신규 승인:  {len(result.ema_new)}건")
    print(f"  MFDS 신규 허가: {len(result.mfds_new)}건")
    print(f"  ─────────────────")
    print(f"  총 신규:        {result.total_new}건")
    print(f"  🔥 핫이슈:      {len(result.hot_issues)}건")
    print()

    # 에러
    if result.errors:
        print(f"[에러]")
        for error in result.errors:
            print(f"  ⚠️  {error}")
        print()

    # FDA 신규
    if result.fda_new:
        print(f"[FDA 신규 승인]")
        for a in result.fda_new:
            hot = "🔥" if a.hot_issue_score >= 20 else "  "
            print(f"  {hot} {a.generic_name}")
            print(f"      제품명: {a.drug_name}")
            print(f"      승인일: {a.approval_date}")
            if a.hot_issue_reasons:
                print(f"      특이사항: {', '.join(a.hot_issue_reasons)}")
            print()

    # EMA 신규
    if result.ema_new:
        print(f"[EMA 신규 승인]")
        for a in result.ema_new:
            hot = "🔥" if a.hot_issue_score >= 20 else "  "
            print(f"  {hot} {a.generic_name}")
            print(f"      제품명: {a.drug_name}")
            print(f"      승인일: {a.approval_date}")
            if a.hot_issue_reasons:
                print(f"      특이사항: {', '.join(a.hot_issue_reasons)}")
            print()

    # MFDS 신규
    if result.mfds_new:
        print(f"[MFDS 신규 허가]")
        for a in result.mfds_new:
            hot = "🔥" if a.hot_issue_score >= 20 else "  "
            print(f"  {hot} {a.generic_name}")
            print(f"      제품명: {a.drug_name}")
            print(f"      허가일: {a.approval_date}")
            if a.matched_existing:
                print(f"      기존 승인: {', '.join(a.existing_approvals).upper()}")
            if a.hot_issue_reasons:
                print(f"      특이사항: {', '.join(a.hot_issue_reasons)}")
            print()

    # 핫이슈 상세
    if result.hot_issues:
        print("=" * 70)
        print(f"  🔥 핫이슈 상세")
        print("=" * 70)
        print()
        for i, a in enumerate(result.hot_issues, 1):
            print(f"  [{i}] {a.generic_name} (Score: {a.hot_issue_score})")
            print(f"      출처: {a.source.value.upper()}")
            print(f"      유형: {a.hot_issue_type.value}")
            print(f"      이유: {', '.join(a.hot_issue_reasons)}")
            if a.matched_existing:
                print(f"      기존: {', '.join(a.existing_approvals).upper()} 승인 기록 있음")
            print()


def save_result(result: ScanResult) -> Path:
    """결과 저장"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON 저장
    filename = f"scan_{result.scan_date.isoformat()}.json"
    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    return filepath


async def generate_hot_issue_briefings(result: ScanResult):
    """핫이슈 브리핑 생성"""
    if not result.hot_issues:
        print("핫이슈가 없습니다.")
        return

    from fastapi.testclient import TestClient
    from regscan.api.main import app

    client = TestClient(app)

    print("\n[핫이슈 브리핑 생성]")

    for issue in result.hot_issues:
        inn = issue.generic_name
        print(f"  {inn}...", end=" ")

        # 기존 API로 브리핑 시도
        r = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm=true")

        if r.status_code == 200:
            data = r.json()
            print("OK")

            # 저장
            briefing_dir = OUTPUT_DIR / "briefings"
            briefing_dir.mkdir(exist_ok=True)

            md_file = briefing_dir / f"{inn.lower().replace(' ', '_')}_{result.scan_date}.md"
            md_file.write_text(data['markdown'], encoding='utf-8')
            print(f"      저장: {md_file}")
        else:
            print(f"SKIP (API 미등록)")


async def main():
    parser = argparse.ArgumentParser(description="일간 규제 동향 스캔")
    parser.add_argument("--days", type=int, default=1, help="스캔 기간 (일)")
    parser.add_argument("--generate-briefing", action="store_true", help="핫이슈 브리핑 생성")
    parser.add_argument("--output", type=str, help="출력 디렉토리")

    args = parser.parse_args()

    print()
    print(f"RegScan 일간 스캔 시작 (최근 {args.days}일)")
    print()

    # 스캐너 실행
    scanner = DailyScanner()
    loaded = scanner.load_existing_data()
    print(f"기존 데이터 로드: {loaded}개 약물")
    print()

    async with scanner:
        result = await scanner.scan(days_back=args.days)

    # 결과 출력
    print_result(result)

    # 결과 저장
    saved_path = save_result(result)
    print(f"결과 저장: {saved_path}")

    # 브리핑 생성
    if args.generate_briefing and result.hot_issues:
        await generate_hot_issue_briefings(result)

    print()
    print("=" * 70)
    print("  스캔 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
