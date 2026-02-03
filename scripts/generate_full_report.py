"""전체 데이터 통합 리포트 생성"""

import asyncio
import sys
import io
import json
from datetime import datetime, date
from pathlib import Path
from collections import Counter

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.parse.ema_parser import EMAMedicineParser
from regscan.map.global_status import GlobalStatusBuilder, HotIssueLevel
from regscan.map.atc import get_atc_database, ATCMatcher, enrich_with_atc


async def main():
    print("=" * 70)
    print("RegScan 통합 리포트 생성")
    print("=" * 70)
    print(f"생성 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. ATC 데이터베이스 로드
    print("\n[1/4] ATC 데이터베이스 로드...")
    atc_db = await get_atc_database()
    atc_matcher = ATCMatcher(atc_db)
    print(f"  - ATC 코드: {atc_db.count:,}건")

    # 2. EMA 데이터 로드
    print("\n[2/4] EMA 데이터 로드...")
    ema_path = Path("data/ema/medicines_20260203.json")
    with open(ema_path, "r", encoding="utf-8") as f:
        ema_raw = json.load(f)
    print(f"  - EMA Medicines: {len(ema_raw):,}건")

    # 3. 파싱 및 GlobalStatus 생성
    print("\n[3/4] GlobalRegulatoryStatus 생성 중...")
    parser = EMAMedicineParser()
    builder = GlobalStatusBuilder()

    global_statuses = []
    for item in ema_raw:
        parsed = parser.parse_medicine(item)
        if parsed and parsed.get("inn"):
            status = builder.from_ema(parsed)
            global_statuses.append(status)

    print(f"  - GlobalStatus 생성: {len(global_statuses):,}건")

    # 4. ATC 보강 및 분석
    print("\n[4/4] ATC 보강 및 분석...")

    # 통계 수집
    level_counts = Counter()
    therapeutic_areas = Counter()
    hot_issues = []
    high_issues = []

    for status in global_statuses:
        level_counts[status.hot_issue_level.value] += 1

        # ATC 매칭
        atc_entry = atc_matcher.match_inn(status.inn)
        if atc_entry:
            therapeutic_areas[atc_entry.therapeutic_area] += 1

        # 핫이슈 수집
        if status.hot_issue_level == HotIssueLevel.HOT:
            hot_issues.append(status)
        elif status.hot_issue_level == HotIssueLevel.HIGH:
            high_issues.append(status)

    # 정렬
    hot_issues.sort(key=lambda x: x.global_score, reverse=True)
    high_issues.sort(key=lambda x: x.global_score, reverse=True)

    print(f"  - HOT: {level_counts['HOT']}건")
    print(f"  - HIGH: {level_counts['HIGH']}건")
    print(f"  - MID: {level_counts['MID']}건")
    print(f"  - LOW: {level_counts['LOW']}건")

    # 리포트 생성
    print("\n" + "=" * 70)
    print("리포트 생성 완료")
    print("=" * 70)

    report_lines = []
    report_lines.append("# RegScan 글로벌 규제 인텔리전스 리포트")
    report_lines.append(f"**생성일**: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # 요약
    report_lines.append("## Executive Summary")
    report_lines.append("")
    report_lines.append(f"- **분석 대상**: EMA 승인 의약품 {len(global_statuses):,}건")
    report_lines.append(f"- **ATC 코드 DB**: {atc_db.count:,}건")
    report_lines.append(f"- **주목 의약품 (HOT+HIGH)**: {level_counts['HOT'] + level_counts['HIGH']}건")
    report_lines.append("")

    # 등급 분포
    report_lines.append("## 핫이슈 등급 분포")
    report_lines.append("")
    report_lines.append("| 등급 | 건수 | 비율 | 설명 |")
    report_lines.append("|------|------|------|------|")
    total = len(global_statuses)
    report_lines.append(f"| 🔥 HOT | {level_counts['HOT']} | {level_counts['HOT']/total*100:.1f}% | 글로벌 주목 신약 (80점+) |")
    report_lines.append(f"| 🔴 HIGH | {level_counts['HIGH']} | {level_counts['HIGH']/total*100:.1f}% | 높은 관심 (60-79점) |")
    report_lines.append(f"| 🟡 MID | {level_counts['MID']} | {level_counts['MID']/total*100:.1f}% | 중간 (40-59점) |")
    report_lines.append(f"| 🟢 LOW | {level_counts['LOW']} | {level_counts['LOW']/total*100:.1f}% | 일반 (40점 미만) |")
    report_lines.append("")

    # 치료영역 분포
    report_lines.append("## 치료영역별 분포 (ATC 기준)")
    report_lines.append("")
    report_lines.append("| 치료영역 | 건수 | 비율 |")
    report_lines.append("|----------|------|------|")
    for area, count in therapeutic_areas.most_common(10):
        if area:
            report_lines.append(f"| {area} | {count} | {count/total*100:.1f}% |")
    report_lines.append("")

    # HOT 이슈
    if hot_issues:
        report_lines.append("## 🔥 HOT 이슈 (글로벌 주목 신약)")
        report_lines.append("")
        for i, status in enumerate(hot_issues[:10], 1):
            atc_info = await enrich_with_atc(status.inn, status.atc_code)
            report_lines.append(f"### {i}. {status.inn.upper()}")
            report_lines.append(f"- **Global Score**: {status.global_score}점")
            report_lines.append(f"- **치료영역**: {atc_info['therapeutic_area_ko'] or 'N/A'}")
            report_lines.append(f"- **ATC 코드**: {atc_info['atc_code'] or 'N/A'}")
            if status.ema:
                report_lines.append(f"- **EMA 상태**: {status.ema.status.value}")
                report_lines.append(f"- **브랜드명**: {status.ema.brand_name}")
                flags = []
                if status.ema.is_orphan:
                    flags.append("희귀의약품")
                if status.ema.is_prime:
                    flags.append("PRIME")
                if status.ema.is_accelerated:
                    flags.append("신속심사")
                if status.ema.is_conditional:
                    flags.append("조건부승인")
                if flags:
                    report_lines.append(f"- **특수지정**: {', '.join(flags)}")
            report_lines.append(f"- **핫이슈 사유**: {', '.join(status.hot_issue_reasons)}")
            report_lines.append("")

    # HIGH 이슈
    if high_issues:
        report_lines.append("## 🔴 HIGH 이슈 (높은 관심)")
        report_lines.append("")
        report_lines.append("| # | INN | Score | 치료영역 | 브랜드명 | 특수지정 |")
        report_lines.append("|---|-----|-------|----------|----------|----------|")
        for i, status in enumerate(high_issues[:20], 1):
            atc_info = await enrich_with_atc(status.inn, status.atc_code)
            area = atc_info['therapeutic_area_ko'] or '-'
            brand = status.ema.brand_name if status.ema else '-'
            flags = []
            if status.ema:
                if status.ema.is_orphan:
                    flags.append("희귀")
                if status.ema.is_prime:
                    flags.append("PRIME")
                if status.ema.is_accelerated:
                    flags.append("신속")
            flag_str = ', '.join(flags) if flags else '-'
            report_lines.append(f"| {i} | {status.inn} | {status.global_score} | {area} | {brand} | {flag_str} |")
        report_lines.append("")

    # MID 이슈 요약
    mid_issues = [s for s in global_statuses if s.hot_issue_level == HotIssueLevel.MID]
    if mid_issues:
        report_lines.append("## 🟡 MID 이슈 요약")
        report_lines.append("")
        report_lines.append(f"총 {len(mid_issues)}건의 중간 관심 의약품이 있습니다.")
        report_lines.append("")

        # 치료영역별 MID 분포
        mid_areas = Counter()
        for status in mid_issues:
            atc_entry = atc_matcher.match_inn(status.inn)
            if atc_entry:
                mid_areas[atc_entry.therapeutic_area] += 1

        report_lines.append("| 치료영역 | 건수 |")
        report_lines.append("|----------|------|")
        for area, count in mid_areas.most_common(5):
            if area:
                report_lines.append(f"| {area} | {count} |")
        report_lines.append("")

    # 데이터 소스
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 데이터 소스")
    report_lines.append("")
    report_lines.append("| 소스 | 건수 | 업데이트 |")
    report_lines.append("|------|------|----------|")
    report_lines.append(f"| EMA Medicines | {len(ema_raw):,} | 2026-02-03 |")
    report_lines.append(f"| WHO ATC | {atc_db.count:,} | 2024-07 |")
    report_lines.append("")
    report_lines.append("> 본 리포트는 RegScan 시스템에 의해 자동 생성되었습니다.")

    # 파일 저장
    report_content = "\n".join(report_lines)

    output_dir = Path("output/reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / f"global_intelligence_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n[저장완료] {report_path}")

    # 콘솔 출력
    print("\n" + "=" * 70)
    print(report_content)
    print("=" * 70)

    return report_path


if __name__ == "__main__":
    asyncio.run(main())
