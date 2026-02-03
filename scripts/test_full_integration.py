"""FDA + EMA + MFDS + CRIS 전체 통합 테스트"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.parse.ema_parser import EMAMedicineParser
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.cris_parser import CRISTrialParser
from regscan.map.matcher import IngredientMatcher
from regscan.map.global_status import GlobalStatusBuilder, merge_global_status


def load_data():
    """데이터 로드"""
    data = {}

    # EMA
    ema_file = Path("data/ema/medicines_20260203.json")
    if ema_file.exists():
        with open(ema_file, encoding="utf-8") as f:
            data["ema_raw"] = json.load(f)
        print(f"[EMA] {len(data['ema_raw']):,}건 로드")

    # MFDS
    mfds_file = Path("data/mfds/permits_20260203.json")
    if mfds_file.exists():
        with open(mfds_file, encoding="utf-8") as f:
            data["mfds_raw"] = json.load(f)
        print(f"[MFDS] {len(data['mfds_raw']):,}건 로드")

    # CRIS
    cris_file = Path("data/cris/trials_20260203.json")
    if cris_file.exists():
        with open(cris_file, encoding="utf-8") as f:
            data["cris_raw"] = json.load(f)
        print(f"[CRIS] {len(data['cris_raw']):,}건 로드")

    # FDA (있으면)
    fda_file = Path("data/fda/approvals_20260203.json")
    if fda_file.exists():
        with open(fda_file, encoding="utf-8") as f:
            data["fda_raw"] = json.load(f)
        print(f"[FDA] {len(data['fda_raw']):,}건 로드")

    return data


def analyze_domestic_impact(statuses, cris_parsed):
    """국내 영향 분석"""
    print("\n" + "=" * 60)
    print("국내 영향 분석")
    print("=" * 60)

    matcher = IngredientMatcher()

    # CRIS 약물명 인덱싱
    cris_drugs = {}
    for trial in cris_parsed:
        for drug in trial.get("drug_names", []):
            normalized = matcher.normalize(drug)
            if normalized and len(normalized) > 2:
                if normalized not in cris_drugs:
                    cris_drugs[normalized] = []
                cris_drugs[normalized].append(trial)

    print(f"\n[CRIS] 고유 약물명: {len(cris_drugs)}개")

    # 케이스 분류
    cases = {
        "imminent": [],      # 글로벌 승인 + MFDS 미허가 + CRIS 진행
        "expected": [],      # MFDS 허가 + (추가 분석 필요)
        "uncertain": [],     # 글로벌 승인 + MFDS 미허가 + CRIS 없음
        "available": [],     # MFDS 허가됨
    }

    for status in statuses:
        has_global = status.ema is not None or status.fda is not None
        has_mfds = status.mfds is not None

        # CRIS에서 임상 진행 중인지 확인
        normalized_inn = matcher.normalize(status.inn)
        has_cris = normalized_inn in cris_drugs

        if has_global and not has_mfds:
            if has_cris:
                cases["imminent"].append({
                    "status": status,
                    "cris": cris_drugs[normalized_inn],
                })
            else:
                cases["uncertain"].append(status)
        elif has_mfds:
            cases["available"].append(status)

    print(f"\n[분류 결과]")
    print(f"  국내 도입 임박 (글로벌O + MFDS X + CRIS O): {len(cases['imminent'])}건")
    print(f"  국내 도입 불투명 (글로벌O + MFDS X + CRIS X): {len(cases['uncertain'])}건")
    print(f"  국내 가용 (MFDS O): {len(cases['available'])}건")

    # 국내 도입 임박 샘플
    if cases["imminent"]:
        print(f"\n[국내 도입 임박 샘플]")
        for item in cases["imminent"][:10]:
            status = item["status"]
            cris_trials = item["cris"]
            print(f"  {status.inn}")
            if status.ema:
                print(f"    EMA: {status.ema.approval_date}")
            if status.fda:
                print(f"    FDA: {status.fda.approval_date}")
            print(f"    CRIS 임상: {len(cris_trials)}건")
            for trial in cris_trials[:2]:
                print(f"      - {trial['trial_id']}: {trial.get('title', '')[:30]}...")

    return cases


def main():
    print("=" * 60)
    print(" FDA + EMA + MFDS + CRIS 전체 통합 테스트")
    print("=" * 60)

    # 1. 데이터 로드
    print("\n[1] 데이터 로드")
    data = load_data()

    if not data:
        print("데이터 없음")
        return

    # 2. 파싱
    print("\n[2] 데이터 파싱")

    from regscan.parse.fda_parser import FDADrugParser

    ema_parser = EMAMedicineParser()
    mfds_parser = MFDSPermitParser()
    cris_parser = CRISTrialParser()
    fda_parser = FDADrugParser()

    ema_parsed = ema_parser.parse_many(data.get("ema_raw", []))
    mfds_parsed = mfds_parser.parse_many(data.get("mfds_raw", []))
    cris_parsed = cris_parser.parse_many(data.get("cris_raw", []))
    fda_parsed = fda_parser.parse_many(data.get("fda_raw", []))

    print(f"  FDA: {len(fda_parsed):,}건")
    print(f"  EMA: {len(ema_parsed):,}건")
    print(f"  MFDS: {len(mfds_parsed):,}건")
    print(f"  CRIS: {len(cris_parsed):,}건")

    # 3. GlobalRegulatoryStatus 병합
    print("\n[3] GlobalRegulatoryStatus 생성")

    statuses = merge_global_status(
        fda_list=fda_parsed,
        ema_list=ema_parsed,
        mfds_list=mfds_parsed,
    )

    print(f"  총 {len(statuses):,}건 생성")

    # 통계
    both = [s for s in statuses if s.ema and s.mfds]
    ema_only = [s for s in statuses if s.ema and not s.mfds]
    mfds_only = [s for s in statuses if s.mfds and not s.ema]

    print(f"\n  EMA + MFDS 둘 다: {len(both)}건")
    print(f"  EMA만: {len(ema_only)}건")
    print(f"  MFDS만: {len(mfds_only)}건")

    # 4. 국내 영향 분석
    cases = analyze_domestic_impact(statuses, cris_parsed)

    # 5. 스코어 분포
    print("\n" + "=" * 60)
    print("핫이슈 스코어 분포")
    print("=" * 60)

    by_level = {"HOT": [], "HIGH": [], "MID": [], "LOW": []}
    for s in statuses:
        by_level[s.hot_issue_level.value].append(s)

    for level in ["HOT", "HIGH", "MID", "LOW"]:
        count = len(by_level[level])
        print(f"  {level}: {count}건")

    # HIGH 이상 샘플
    high_plus = by_level["HOT"] + by_level["HIGH"]
    if high_plus:
        print(f"\n[HIGH 이상 샘플]")
        for s in sorted(high_plus, key=lambda x: -x.global_score)[:10]:
            agencies = []
            if s.fda:
                agencies.append("FDA")
            if s.ema:
                agencies.append("EMA")
            if s.mfds:
                agencies.append("MFDS")
            print(f"  {s.inn}: {s.global_score}점 ({', '.join(agencies)})")

    print("\n" + "=" * 60)
    print(" 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
