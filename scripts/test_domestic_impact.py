"""DomesticImpactAnalyzer 테스트"""

import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.parse.fda_parser import FDADrugParser
from regscan.parse.ema_parser import EMAMedicineParser
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.cris_parser import CRISTrialParser
from regscan.map.global_status import merge_global_status
from regscan.scan.domestic import DomesticImpactAnalyzer, DomesticStatus

DATA_DIR = Path("C:/Jimin/RegScan/data")


def load_data():
    """데이터 로드"""
    data = {}

    files = {
        "fda": DATA_DIR / "fda" / "approvals_20260203.json",
        "ema": DATA_DIR / "ema" / "medicines_20260203.json",
        "mfds": DATA_DIR / "mfds" / "permits_full_20260203.json",  # 전체 데이터
        "cris": DATA_DIR / "cris" / "trials_full_20260204.json",
    }

    for key, path in files.items():
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data[key] = json.load(f)
            print(f"  {key.upper()}: {len(data[key]):,}건")
        else:
            # fallback
            alt_path = path.parent / path.name.replace("_20260203", "_full_20260203")
            if alt_path.exists():
                with open(alt_path, encoding="utf-8") as f:
                    data[key] = json.load(f)
                print(f"  {key.upper()}: {len(data[key]):,}건 (full)")

    return data


def main():
    print("=" * 70)
    print("DomesticImpactAnalyzer 테스트")
    print("=" * 70)

    # 1. 데이터 로드
    print("\n[1] 데이터 로드")
    data = load_data()

    # 2. 파싱
    print("\n[2] 데이터 파싱")
    fda_parsed = FDADrugParser().parse_many(data.get("fda", []))
    ema_parsed = EMAMedicineParser().parse_many(data.get("ema", []))
    mfds_parsed = MFDSPermitParser().parse_many(data.get("mfds", []))
    cris_parsed = CRISTrialParser().parse_many(data.get("cris", []))

    print(f"  FDA: {len(fda_parsed):,}건")
    print(f"  EMA: {len(ema_parsed):,}건")
    print(f"  MFDS: {len(mfds_parsed):,}건")
    print(f"  CRIS: {len(cris_parsed):,}건")

    # 3. GlobalRegulatoryStatus 생성
    print("\n[3] GlobalRegulatoryStatus 생성")
    statuses = merge_global_status(
        fda_list=fda_parsed,
        ema_list=ema_parsed,
        mfds_list=mfds_parsed,
    )
    print(f"  총 {len(statuses):,}건")

    # 4. DomesticImpactAnalyzer 실행
    print("\n[4] DomesticImpactAnalyzer 실행")
    analyzer = DomesticImpactAnalyzer()

    # CRIS 로드
    cris_count = analyzer.load_cris_data(cris_parsed)
    print(f"  CRIS 약물명 인덱스: {cris_count}개")

    # 배치 분석
    impacts = analyzer.analyze_batch(statuses)
    print(f"  분석 완료: {len(impacts)}건")

    # 5. 결과 요약
    print("\n[5] 분석 결과 요약")
    summary = analyzer.get_summary()
    print(f"  총 {summary['total']}건")
    print(f"\n  상태별 분포:")
    for status, count in summary.get("by_status", {}).items():
        print(f"    {status}: {count}건")

    print(f"\n  HIRA 급여: {summary['hira_reimbursed_count']}건")
    print(f"  CRIS 임상 진행: {summary['with_cris_trials']}건")
    print(f"  글로벌 승인 + 국내 미허가: {summary['globally_approved_not_in_korea']}건")

    # 6. 국내 도입 임박 약물
    print("\n" + "=" * 70)
    print("[6] 국내 도입 임박 약물 (글로벌 승인 + MFDS 미허가 + CRIS 진행)")
    print("=" * 70)
    imminent = analyzer.get_imminent_drugs()
    for item in imminent[:15]:
        print(f"\n  {item.inn} (Score: {item.global_score})")
        print(f"    {item.summary}")
        if item.cris_trials:
            for trial in item.cris_trials[:2]:
                print(f"    - {trial.trial_id}: {trial.title[:40]}...")
        if item.analysis_notes:
            for note in item.analysis_notes:
                print(f"    * {note}")

    # 7. 고가 급여 약물
    print("\n" + "=" * 70)
    print("[7] 고가 급여 약물 (상한가 100만원 이상)")
    print("=" * 70)
    high_value = analyzer.get_high_value_reimbursed(min_price=1_000_000)
    for item in high_value[:15]:
        print(f"  {item.inn}")
        print(f"    {item.summary}")

    # 8. 특정 약물 상세 분석
    print("\n" + "=" * 70)
    print("[8] 주요 약물 상세 분석")
    print("=" * 70)

    target_drugs = ["pembrolizumab", "nivolumab", "semaglutide", "adalimumab", "trastuzumab"]
    for impact in impacts:
        if impact.inn.lower() in target_drugs:
            print(f"\n  === {impact.inn} ===")
            print(f"  상태: {impact.domestic_status.value}")
            print(f"  {impact.summary}")
            if impact.analysis_notes:
                for note in impact.analysis_notes:
                    print(f"    * {note}")

    print("\n" + "=" * 70)
    print("완료!")
    print("=" * 70)


if __name__ == "__main__":
    main()
