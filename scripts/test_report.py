"""리포트 생성 테스트"""

import asyncio
import sys
import io
from datetime import date
from pathlib import Path

# Windows 콘솔 인코딩 설정 및 버퍼링 비활성화
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.report import ReportGenerator


DB_URL = "sqlite+aiosqlite:///data/e2e_test.db"


async def main():
    print("=" * 60)
    print("MVP 리포트 생성 테스트")
    print("=" * 60)

    generator = ReportGenerator(DB_URL)
    await generator.init()

    # 일간 리포트
    print("\n[일간 리포트 생성]")
    daily = await generator.generate_daily()
    print(f"  - 대상 날짜: {daily.report_date}")
    print(f"  - 전체 카드: {daily.stats.total_cards}건")
    print(f"  - 하이라이트: {len(daily.highlights)}건")
    print(f"  - 핫이슈: {len(daily.hot_issues)}건")

    # 텍스트 출력
    print("\n" + "-" * 60)
    text_report = generator.format_daily_text(daily)
    print(text_report)

    # 마크다운 저장
    md_report = generator.format_daily_markdown(daily)
    output_dir = Path("output/reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    daily_md_path = output_dir / f"daily_{daily.report_date.strftime('%Y%m%d')}.md"
    with open(daily_md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"\n[저장] {daily_md_path}")

    # 주간 리포트
    print("\n" + "=" * 60)
    print("[주간 리포트 생성]")
    weekly = await generator.generate_weekly()
    print(f"  - 기간: {weekly.start_date} ~ {weekly.end_date}")
    print(f"  - 전체 카드: {weekly.stats.total_cards}건")
    print(f"  - 하이라이트: {len(weekly.top_highlights)}건")
    print(f"  - 핫이슈: {len(weekly.hot_issues)}건")

    # 텍스트 출력
    print("\n" + "-" * 60)
    text_report = generator.format_weekly_text(weekly)
    print(text_report)

    # 마크다운 저장
    md_report = generator.format_weekly_markdown(weekly)
    weekly_md_path = output_dir / f"weekly_{weekly.end_date.strftime('%Y%m%d')}.md"
    with open(weekly_md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"\n[저장] {weekly_md_path}")

    print("\n" + "=" * 60)
    print("리포트 생성 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
