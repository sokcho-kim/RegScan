"""브리핑 품질 테스트 — 실제 데이터로 브리핑 생성 + 버전별 저장

Usage:
    python scripts/test_briefing_quality.py [--version v5.0] [--area oncology]
"""

from __future__ import annotations

import asyncio
import json
import sys
import io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regscan.stream.base import StreamResult
from regscan.stream.briefing import StreamBriefingGenerator


def load_real_drugs(area: str = "oncology", max_drugs: int = 5) -> list[dict]:
    """실제 FDA/EMA/MFDS 데이터 기반 테스트 약물 구성"""

    # 실제 약물 데이터 (FDA 승인 기반, 다양한 HIRA 상태 포함)
    test_drugs = {
        "oncology": [
            {
                "inn": "PEMBROLIZUMAB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2014-09-04",
                    "brand_name": "KEYTRUDA",
                    "submission_class_code_description": "Type 1 - New Molecular Entity",
                    "pharm_class_epc": ["Programmed Death Receptor 1 (PD-1)-Blocking Antibody"],
                },
                "ema_data": {"marketing_authorisation_date": "2015-07-17", "medicine_status": "Authorised"},
                "mfds_data": {"approval_status": "허가", "approval_date": "2015-03-25"},
                "atc_code": "L01FF02",
                "designations": ["NME"],
                "therapeutic_areas": ["oncology"],
            },
            {
                "inn": "NIVOLUMAB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2014-12-22",
                    "brand_name": "OPDIVO",
                    "submission_class_code_description": "Type 1 - New Molecular Entity",
                    "pharm_class_epc": ["Programmed Death Receptor 1 (PD-1)-Blocking Antibody"],
                },
                "ema_data": {"marketing_authorisation_date": "2015-06-19", "medicine_status": "Authorised"},
                "mfds_data": {"approval_status": "허가", "approval_date": "2016-03-24"},
                "atc_code": "L01FF01",
                "designations": ["NME", "orphan"],
                "therapeutic_areas": ["oncology"],
            },
            {
                "inn": "SOTORASIB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2021-05-28",
                    "brand_name": "LUMAKRAS",
                    "submission_class_code_description": "Type 1 - New Molecular Entity",
                    "pharm_class_epc": ["KRAS G12C Inhibitor"],
                },
                "ema_data": {"marketing_authorisation_date": "2022-01-06", "medicine_status": "Authorised"},
                "mfds_data": {"approval_status": "미허가"},
                "atc_code": "L01XX73",
                "designations": ["NME", "breakthrough"],
                "therapeutic_areas": ["oncology"],
            },
            {
                "inn": "TRASTUZUMAB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "1998-09-25",
                    "brand_name": "HERCEPTIN",
                    "submission_class_code_description": "Type 1 - New Molecular Entity",
                    "pharm_class_epc": ["HER2/ErbB2 Receptor Inhibitor"],
                },
                "ema_data": {"marketing_authorisation_date": "2000-08-28", "medicine_status": "Authorised"},
                "mfds_data": {"approval_status": "허가", "approval_date": "2003-06-18"},
                "atc_code": "L01FD01",
                "designations": [],
                "therapeutic_areas": ["oncology"],
            },
            {
                "inn": "RILZABRUTINIB",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2025-03-28",
                    "brand_name": "",
                    "submission_class_code_description": "Type 1 - New Molecular Entity",
                    "pharm_class_epc": ["Bruton Tyrosine Kinase Inhibitor"],
                },
                "mfds_data": {"approval_status": "미허가"},
                "designations": ["NME"],
                "therapeutic_areas": ["oncology"],
            },
        ],
        "rare_disease": [
            {
                "inn": "DIQUAFOSOL TETRASODIUM",
                "fda_data": {},
                "mfds_data": {"approval_status": "허가"},
                "designations": [],
                "therapeutic_areas": ["rare_disease"],
            },
            {
                "inn": "SEBELIPASE ALFA",
                "fda_data": {
                    "submission_status": "AP",
                    "submission_status_date": "2015-12-08",
                    "brand_name": "KANUMA",
                    "pharm_class_epc": ["Lysosomal Acid Lipase"],
                },
                "mfds_data": {"approval_status": "미허가"},
                "designations": ["orphan", "breakthrough"],
                "therapeutic_areas": ["rare_disease"],
            },
        ],
    }

    drugs = test_drugs.get(area, test_drugs["oncology"])
    return drugs[:max_drugs]


async def run_test(version: str, area: str, area_ko: str):
    """브리핑 생성 + 결과 저장"""
    print(f"\n{'='*60}")
    print(f"  Briefing Quality Test — {version}")
    print(f"  Area: {area_ko} ({area})")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 실제 약물 데이터 로드
    drugs = load_real_drugs(area, max_drugs=5)
    if not drugs:
        print("ERROR: 약물 데이터 없음")
        return

    print(f"[1] 약물 {len(drugs)}건 로드")
    for d in drugs:
        print(f"  - {d.get('inn', 'UNKNOWN')}")

    # StreamResult 구성
    result = StreamResult(
        stream_name="therapeutic_area",
        sub_category=area,
        drugs_found=drugs,
        signals=[],
        errors=[],
    )

    # 브리핑 생성
    gen = StreamBriefingGenerator()
    print(f"\n[2] Therapeutic Briefing 생성 중...")
    briefing = await gen.generate_therapeutic_briefing(
        area=area, area_ko=area_ko, result=result
    )

    # 결과 출력
    print(f"\n[3] 결과:")
    print(json.dumps(briefing, ensure_ascii=False, indent=2))

    # HIRA 필드 체크
    print(f"\n[4] HIRA 반영 체크:")
    text = json.dumps(briefing, ensure_ascii=False)
    hira_keywords = ["급여", "HIRA", "상한가", "미등재", "산정특례", "비급여", "KODC", "긴급도입"]
    found = [kw for kw in hira_keywords if kw in text]
    print(f"  HIRA 키워드 검출: {len(found)}/{len(hira_keywords)} — {found}")

    # hallucination 체크 (미래 시제)
    print(f"\n[5] Hallucination 체크:")
    today = datetime.now().strftime("%Y-%m-%d")
    suspicious = ["승인 완료" if "2027" in text or "2028" in text else None]
    suspicious = [s for s in suspicious if s]
    if suspicious:
        print(f"  WARNING: 의심 표현 발견 — {suspicious}")
    else:
        print(f"  OK — 명백한 hallucination 미검출")

    # 버전별 저장
    snapshot_dir = Path("output/briefings/snapshots") / version
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # 브리핑 결과
    out_path = snapshot_dir / f"{area}_therapeutic.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    print(f"\n[6] 저장: {out_path}")

    # 메타데이터
    meta = {
        "version": version,
        "timestamp": datetime.now().isoformat(),
        "area": area,
        "drug_count": len(drugs),
        "drugs": [d.get("inn") for d in drugs],
        "hira_keywords_found": found,
        "hira_coverage": f"{len(found)}/{len(hira_keywords)}",
        "model": "gpt-5.2 (primary) / gemini-2.5-flash (fallback)",
        "max_completion_tokens": 3500,
        "changes": [
            "few-shot HIRA 3패턴 (급여/미등재/데이터없음)",
            "네거티브 few-shot (날짜없음 → 승인일 미공개)",
            "access_routes 유무 분기",
            "max_completion_tokens 2500→3500",
        ],
    }
    meta_path = snapshot_dir / "_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  메타: {meta_path}")

    # 입력 데이터 저장 (재현용)
    input_path = snapshot_dir / f"{area}_input.json"
    input_data = [
        {
            "inn": d.get("inn"),
            "fda_data": d.get("fda_data"),
            "ema_data": d.get("ema_data"),
            "mfds_data": d.get("mfds_data"),
            "hira_data": d.get("hira_data"),
        }
        for d in drugs
    ]
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(input_data, f, ensure_ascii=False, indent=2)
    print(f"  입력: {input_path}")

    # 프롬프트 저장 (system + user 분리)
    prompt_path = snapshot_dir / f"{area}_prompts.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"MODEL: {gen._last_model_used}\n")
        f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")
        f.write("### SYSTEM PROMPT ###\n\n")
        f.write(gen._last_system_prompt)
        f.write("\n\n" + "=" * 60 + "\n\n")
        f.write("### USER PROMPT ###\n\n")
        f.write(gen._last_user_prompt)
    print(f"  프롬프트: {prompt_path}")

    return briefing


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=f"v5.0_{datetime.now().strftime('%Y%m%d')}")
    parser.add_argument("--area", default="oncology")
    parser.add_argument("--area-ko", default="항암")
    args = parser.parse_args()

    asyncio.run(run_test(args.version, args.area, args.area_ko))
