"""FDA + EMA 통합 리포트 생성"""

import asyncio
import sys
import io
import json
from datetime import datetime, date
from pathlib import Path
from collections import Counter

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from regscan.parse.fda_parser import FDADrugParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.map.global_status import GlobalStatusBuilder, HotIssueLevel, merge_by_inn
from regscan.map.atc import get_atc_database, ATCMatcher, enrich_with_atc


async def collect_fda_data():
    """FDA openFDA API에서 NDA/BLA 신약 승인 데이터 수집"""
    print("[FDA 데이터 수집 (NDA/BLA)]")

    base_url = "https://api.fda.gov/drug/drugsfda.json"
    all_results = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # NDA (New Drug Application) - 신약
        for skip in range(0, 1000, 100):
            params = {
                "search": "application_number:NDA* AND submissions.submission_status:AP",
                "limit": 100,
                "skip": skip,
            }

            try:
                response = await client.get(base_url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    all_results.extend(results)
                    print(f"  - NDA: {len(all_results)}건...")
                    if len(results) < 100:
                        break
                else:
                    break
            except Exception as e:
                print(f"  - 요청 오류: {e}")
                break
            await asyncio.sleep(0.2)

        # BLA (Biologics License Application) - 바이오의약품
        for skip in range(0, 500, 100):
            params = {
                "search": "application_number:BLA* AND submissions.submission_status:AP",
                "limit": 100,
                "skip": skip,
            }

            try:
                response = await client.get(base_url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    all_results.extend(results)
                    print(f"  - BLA: +{len(results)}건...")
                    if len(results) < 100:
                        break
                else:
                    break
            except Exception as e:
                break
            await asyncio.sleep(0.2)

    print(f"  - 총 {len(all_results)}건 수집 완료")

    # 저장
    data_dir = Path("data/fda")
    data_dir.mkdir(parents=True, exist_ok=True)

    output_path = data_dir / f"approvals_{datetime.now().strftime('%Y%m%d')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"  - 저장: {output_path}")

    return all_results


async def main():
    print("=" * 70)
    print("RegScan FDA + EMA 통합 리포트")
    print("=" * 70)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. ATC 데이터베이스 로드
    print("\n[1/5] ATC 데이터베이스 로드...")
    atc_db = await get_atc_database()
    atc_matcher = ATCMatcher(atc_db)
    print(f"  - ATC 코드: {atc_db.count:,}건")

    # 2. FDA 데이터 수집
    print("\n[2/5] FDA 데이터 수집...")
    fda_raw = await collect_fda_data()

    # 3. EMA 데이터 로드
    print("\n[3/5] EMA 데이터 로드...")
    ema_path = Path("data/ema/medicines_20260203.json")
    with open(ema_path, "r", encoding="utf-8") as f:
        ema_raw = json.load(f)
    print(f"  - EMA Medicines: {len(ema_raw):,}건")

    # 4. 파싱
    print("\n[4/5] 데이터 파싱...")
    fda_parser = FDADrugParser()
    ema_parser = EMAMedicineParser()

    fda_parsed = []
    for item in fda_raw:
        try:
            parsed = fda_parser.parse_approval(item)
            if parsed and parsed.get("generic_name"):
                fda_parsed.append(parsed)
        except Exception as e:
            pass
    print(f"  - FDA 파싱: {len(fda_parsed)}건")

    ema_parsed = ema_parser.parse_many(ema_raw)
    print(f"  - EMA 파싱: {len(ema_parsed)}건")

    # 5. INN 기준 병합 및 스코어링
    print("\n[5/5] GlobalRegulatoryStatus 생성 (FDA+EMA 병합)...")
    global_statuses = merge_by_inn(fda_parsed, ema_parsed)
    print(f"  - 병합 완료: {len(global_statuses):,}건")

    # 통계 수집
    level_counts = Counter()
    therapeutic_areas = Counter()
    hot_issues = []
    high_issues = []
    mid_issues = []

    for status in global_statuses:
        level_counts[status.hot_issue_level.value] += 1

        # ATC 매칭
        atc_entry = atc_matcher.match_inn(status.inn)
        if atc_entry:
            therapeutic_areas[atc_entry.therapeutic_area] += 1

        # 등급별 수집
        if status.hot_issue_level == HotIssueLevel.HOT:
            hot_issues.append(status)
        elif status.hot_issue_level == HotIssueLevel.HIGH:
            high_issues.append(status)
        elif status.hot_issue_level == HotIssueLevel.MID:
            mid_issues.append(status)

    # 정렬
    hot_issues.sort(key=lambda x: x.global_score, reverse=True)
    high_issues.sort(key=lambda x: x.global_score, reverse=True)
    mid_issues.sort(key=lambda x: x.global_score, reverse=True)

    print(f"\n[등급 분포]")
    print(f"  - 🔥 HOT: {level_counts['HOT']}건")
    print(f"  - 🔴 HIGH: {level_counts['HIGH']}건")
    print(f"  - 🟡 MID: {level_counts['MID']}건")
    print(f"  - 🟢 LOW: {level_counts['LOW']}건")

    # 리포트 생성
    report_lines = []
    report_lines.append("# RegScan 글로벌 규제 인텔리전스 리포트")
    report_lines.append(f"**생성일**: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Executive Summary
    report_lines.append("## Executive Summary")
    report_lines.append("")
    report_lines.append("| 항목 | 수치 |")
    report_lines.append("|------|------|")
    report_lines.append(f"| FDA 승인 의약품 | {len(fda_parsed):,}건 |")
    report_lines.append(f"| EMA 승인 의약품 | {len(ema_parsed):,}건 |")
    report_lines.append(f"| INN 기준 병합 | {len(global_statuses):,}건 |")
    report_lines.append(f"| ATC 코드 DB | {atc_db.count:,}건 |")
    report_lines.append(f"| **🔥 HOT 의약품** | **{level_counts['HOT']}건** |")
    report_lines.append(f"| **🔴 HIGH 의약품** | **{level_counts['HIGH']}건** |")
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
    report_lines.append("## 치료영역별 분포 (WHO ATC 기준)")
    report_lines.append("")
    report_lines.append("| 치료영역 | 건수 | 비율 |")
    report_lines.append("|----------|------|------|")
    for area, count in therapeutic_areas.most_common(10):
        if area:
            report_lines.append(f"| {area} | {count} | {count/total*100:.1f}% |")
    report_lines.append("")

    # HOT 이슈
    if hot_issues:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## 🔥 HOT 이슈 (글로벌 주목 신약)")
        report_lines.append("")
        for i, status in enumerate(hot_issues[:10], 1):
            atc_info = await enrich_with_atc(status.inn, status.atc_code)
            report_lines.append(f"### {i}. {status.inn.upper()}")
            report_lines.append(f"- **Global Score**: {status.global_score}점")
            report_lines.append(f"- **치료영역**: {atc_info['therapeutic_area_ko'] or 'N/A'}")
            report_lines.append(f"- **ATC 코드**: {atc_info['atc_code'] or 'N/A'}")

            # FDA 정보
            if status.fda:
                report_lines.append(f"- **FDA**: {status.fda.status.value}")
                if status.fda.brand_name:
                    report_lines.append(f"  - 브랜드: {status.fda.brand_name}")
                fda_flags = []
                if status.fda.is_breakthrough: fda_flags.append("Breakthrough")
                if status.fda.is_accelerated: fda_flags.append("Accelerated")
                if status.fda.is_priority: fda_flags.append("Priority")
                if status.fda.is_orphan: fda_flags.append("Orphan")
                if fda_flags:
                    report_lines.append(f"  - 특수지정: {', '.join(fda_flags)}")

            # EMA 정보
            if status.ema:
                report_lines.append(f"- **EMA**: {status.ema.status.value}")
                if status.ema.brand_name:
                    report_lines.append(f"  - 브랜드: {status.ema.brand_name}")
                ema_flags = []
                if status.ema.is_prime: ema_flags.append("PRIME")
                if status.ema.is_accelerated: ema_flags.append("Accelerated")
                if status.ema.is_orphan: ema_flags.append("Orphan")
                if status.ema.is_conditional: ema_flags.append("Conditional")
                if ema_flags:
                    report_lines.append(f"  - 특수지정: {', '.join(ema_flags)}")

            report_lines.append(f"- **핫이슈 사유**: {', '.join(status.hot_issue_reasons)}")
            report_lines.append("")

    # HIGH 이슈
    if high_issues:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## 🔴 HIGH 이슈 (높은 관심)")
        report_lines.append("")
        report_lines.append("| # | INN | Score | FDA | EMA | 치료영역 | 특수지정 |")
        report_lines.append("|---|-----|-------|-----|-----|----------|----------|")

        for i, status in enumerate(high_issues[:20], 1):
            atc_info = await enrich_with_atc(status.inn, status.atc_code)
            area = atc_info['therapeutic_area_ko'] or '-'
            fda_status = status.fda.status.value if status.fda else '-'
            ema_status = status.ema.status.value if status.ema else '-'

            flags = []
            if status.fda:
                if status.fda.is_breakthrough: flags.append("BT")
                if status.fda.is_orphan: flags.append("Orphan")
            if status.ema:
                if status.ema.is_prime: flags.append("PRIME")
            flag_str = ', '.join(flags) if flags else '-'

            report_lines.append(f"| {i} | {status.inn} | {status.global_score} | {fda_status} | {ema_status} | {area} | {flag_str} |")
        report_lines.append("")

    # MID 요약
    if mid_issues:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## 🟡 MID 이슈 요약")
        report_lines.append("")
        report_lines.append(f"총 **{len(mid_issues)}건**의 중간 관심 의약품")
        report_lines.append("")

        # 상위 10개만
        report_lines.append("| # | INN | Score | FDA | EMA |")
        report_lines.append("|---|-----|-------|-----|-----|")
        for i, status in enumerate(mid_issues[:10], 1):
            fda_status = status.fda.status.value if status.fda else '-'
            ema_status = status.ema.status.value if status.ema else '-'
            report_lines.append(f"| {i} | {status.inn} | {status.global_score} | {fda_status} | {ema_status} |")
        report_lines.append("")

    # 다중 승인 분석
    multi_approved = [s for s in global_statuses if s.approval_count >= 2]
    if multi_approved:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## 다중 승인 의약품 (FDA + EMA)")
        report_lines.append("")
        report_lines.append(f"FDA와 EMA 모두 승인된 의약품: **{len(multi_approved)}건**")
        report_lines.append("")

    # 스코어링 기준
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 스코어링 기준")
    report_lines.append("")
    report_lines.append("| 항목 | 점수 |")
    report_lines.append("|------|------|")
    report_lines.append("| FDA 승인 | +10 |")
    report_lines.append("| EMA 승인 | +10 |")
    report_lines.append("| FDA Breakthrough | +15 |")
    report_lines.append("| EMA PRIME | +15 |")
    report_lines.append("| 희귀의약품 | +15 |")
    report_lines.append("| FDA Accelerated | +10 |")
    report_lines.append("| EMA Accelerated | +10 |")
    report_lines.append("| 3개국+ 다중승인 | +10 |")
    report_lines.append("| FDA+EMA 근접승인 (1년내) | +10 |")
    report_lines.append("")

    # 데이터 소스
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 데이터 소스")
    report_lines.append("")
    report_lines.append("| 소스 | 건수 | 업데이트 |")
    report_lines.append("|------|------|----------|")
    report_lines.append(f"| FDA Drugs@FDA | {len(fda_raw):,} | {datetime.now().strftime('%Y-%m-%d')} |")
    report_lines.append(f"| EMA Medicines | {len(ema_raw):,} | 2026-02-03 |")
    report_lines.append(f"| WHO ATC | {atc_db.count:,} | 2024-07 |")
    report_lines.append("")
    report_lines.append("> 본 리포트는 **RegScan** 글로벌 규제 인텔리전스 시스템에 의해 자동 생성되었습니다.")

    # 파일 저장
    report_content = "\n".join(report_lines)

    output_dir = Path("output/reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / f"fda_ema_intelligence_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n[저장완료] {report_path}")
    print("\n" + "=" * 70)
    print(report_content)
    print("=" * 70)

    return report_path


if __name__ == "__main__":
    asyncio.run(main())
