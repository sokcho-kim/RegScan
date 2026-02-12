"""데이터 소스별 주기별 볼륨 측정 스크립트"""
import asyncio
import httpx
import json
from datetime import datetime, timedelta
from collections import Counter

async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    d4 = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    d14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    headers = {"User-Agent": "RegScan/3.0 (Python aiohttp/3.12)"}
    api_key = "bnBZWNhcTfKsR04Fw5clAltjBAlvleSUsPG0ilkO"

    results = {}

    async with httpx.AsyncClient(timeout=30) as c:

        # =============================================
        # 1. FDA: submission_status_date 기준 승인
        # =============================================
        print("=" * 60)
        print("1. FDA 승인 (submission_status=AP)")
        print("=" * 60)
        for label, start in [("4d", d4), ("7d", d7), ("14d", d14), ("30d", d30)]:
            try:
                url = (
                    f"https://api.fda.gov/drug/drugsfda.json?"
                    f"search=submissions.submission_status_date:"
                    f"[{start.replace('-', '')}+TO+{today.replace('-', '')}]"
                    f"+AND+submissions.submission_status:\"AP\""
                    f"&limit=10&api_key={api_key}"
                )
                r = await c.get(url)
                if r.status_code == 200:
                    data = r.json()
                    total = data.get("meta", {}).get("results", {}).get("total", 0)
                    names = []
                    for res in data.get("results", [])[:5]:
                        gn = (res.get("openfda", {}).get("generic_name", [""])[0]
                              or res.get("openfda", {}).get("brand_name", [""])[0]
                              or "?")
                        names.append(gn[:35])
                    results[f"fda_{label}"] = total
                    print(f"  {label}: {total} approvals  ex) {', '.join(names[:3])}")
                else:
                    results[f"fda_{label}"] = 0
                    print(f"  {label}: HTTP {r.status_code}")
            except Exception as e:
                results[f"fda_{label}"] = 0
                print(f"  {label}: error {e}")

        # =============================================
        # 2. CT.gov Phase 3 - CompletionDate 기준 (큰 구간)
        # =============================================
        print()
        print("=" * 60)
        print("2. CT.gov Phase 3 (CompletionDate)")
        print("=" * 60)

        conditions = [
            "Cancer", "Neoplasm", "Carcinoma", "Leukemia", "Lymphoma",
            "Melanoma", "Sarcoma", "Myeloma", "Glioblastoma",
            "Diabetes Mellitus", "Type 2 Diabetes", "Obesity", "NASH",
            "Heart Failure", "Cardiovascular Disease",
            "Pulmonary Arterial Hypertension",
            "Psoriasis", "Atopic Dermatitis", "Crohn Disease",
            "Ulcerative Colitis", "Multiple Sclerosis",
            "Cystic Fibrosis", "Duchenne Muscular Dystrophy",
        ]

        for label, start, days in [("30d", d30, 30), ("90d", (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), 90),
                                   ("180d", (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"), 180)]:
            ncts = set()
            fail_count = 0
            completed_count = 0
            for cond in conditions:
                p = {
                    "format": "json", "pageSize": 100, "query.cond": cond,
                    "filter.overallStatus": "COMPLETED,TERMINATED,SUSPENDED",
                    "filter.advanced": f"AREA[Phase]PHASE3 AND AREA[CompletionDate]RANGE[{start},{today}]",
                }
                try:
                    r = await c.get("https://clinicaltrials.gov/api/v2/studies", params=p, headers=headers)
                    if r.status_code != 200:
                        continue
                    for s in r.json().get("studies", []):
                        proto = s.get("protocolSection", {})
                        nct = proto.get("identificationModule", {}).get("nctId", "")
                        if nct in ncts:
                            continue
                        ncts.add(nct)
                        status = proto.get("statusModule", {}).get("overallStatus", "")
                        if status in ("TERMINATED", "SUSPENDED"):
                            fail_count += 1
                        else:
                            completed_count += 1
                except:
                    continue

            daily = round(len(ncts) / days, 2)
            fail_daily = round(fail_count / days, 2)
            results[f"ctgov_{label}"] = len(ncts)
            results[f"ctgov_daily_{label}"] = daily
            results[f"ctgov_fail_{label}"] = fail_count
            print(f"  {label}: total={len(ncts)} (completed={completed_count}, fail={fail_count})")
            print(f"       daily avg: {daily}/day, fail: {fail_daily}/day")
            print(f"       => 3.5d estimate: ~{round(daily*3.5)}, 7d estimate: ~{round(daily*7)}")

        # =============================================
        # 3. medRxiv
        # =============================================
        print()
        print("=" * 60)
        print("3. medRxiv preprints")
        print("=" * 60)
        for label, start in [("4d", d4), ("7d", d7), ("14d", d14), ("30d", d30)]:
            try:
                url = f"https://api.biorxiv.org/details/medrxiv/{start}/{today}/0"
                r = await c.get(url)
                if r.status_code == 200:
                    data = r.json()
                    total_str = data.get("messages", [{}])[0].get("total", "0")
                    total = int(str(total_str))
                    match_est = max(1, round(total * 0.024))
                    results[f"med_{label}"] = total
                    results[f"med_match_{label}"] = match_est
                    print(f"  {label}: total={total}, keyword match est ~{match_est}")
                else:
                    results[f"med_{label}"] = 0
                    results[f"med_match_{label}"] = 0
                    print(f"  {label}: HTTP {r.status_code}")
            except Exception as e:
                results[f"med_{label}"] = 0
                results[f"med_match_{label}"] = 0
                print(f"  {label}: error {e}")

        # =============================================
        # 4. EMA - revision_date 분석
        # =============================================
        print()
        print("=" * 60)
        print("4. EMA medicines (revision_date)")
        print("=" * 60)
        try:
            r = await c.get(
                "https://www.ema.europa.eu/en/documents/report/"
                "medicines-output-medicines_json-report_en.json"
            )
            if r.status_code == 200:
                raw = r.json()
                # EMA JSON may be dict with nested list or direct list
                if isinstance(raw, dict):
                    meds = raw.get("data", raw.get("medicines", raw.get("results", [])))
                    if isinstance(meds, dict):
                        meds = list(meds.values())
                elif isinstance(raw, list):
                    meds = raw
                else:
                    meds = []

                # Filter to actual medicine dicts
                med_list = [m for m in meds if isinstance(m, dict)]
                print(f"  Total medicines: {len(med_list)} (type: {type(meds).__name__}, "
                      f"first elem type: {type(meds[0]).__name__ if meds else 'N/A'})")

                count_4d = 0
                count_7d = 0
                count_14d = 0
                samples = []
                for m in med_list:
                    rd = m.get("revision_date", "") or m.get("revisionDate", "") or ""
                    if not rd:
                        continue
                    d = str(rd)[:10]
                    inn = (m.get("active_substance", "") or m.get("activeSubstance", "")
                           or m.get("international_non_proprietary_name_common_name", "")
                           or m.get("name_of_medicine", "") or "?")
                    if d >= d14:
                        count_14d += 1
                    if d >= d7:
                        count_7d += 1
                    if d >= d4:
                        count_4d += 1
                        if len(samples) < 10:
                            samples.append(f"{d} | {str(inn)[:50]}")

                results["ema_4d"] = count_4d
                results["ema_7d"] = count_7d
                results["ema_14d"] = count_14d
                print(f"  Updated 4d: {count_4d}")
                print(f"  Updated 7d: {count_7d}")
                print(f"  Updated 14d: {count_14d}")
                for s in samples[:8]:
                    print(f"    {s}")
            else:
                print(f"  HTTP {r.status_code}")
        except Exception as e:
            print(f"  error: {e}")
            import traceback; traceback.print_exc()

    # =============================================
    # SUMMARY TABLE
    # =============================================
    # CT.gov: use 180d daily average to estimate
    ct_daily = results.get("ctgov_daily_180d", results.get("ctgov_daily_90d", 0))
    ct_fail_rate = results.get("ctgov_fail_180d", 0) / max(results.get("ctgov_180d", 1), 1)

    ct_3d = round(ct_daily * 3.5)
    ct_7d = round(ct_daily * 7)
    ct_fail_3d = round(ct_3d * ct_fail_rate)
    ct_fail_7d = round(ct_7d * ct_fail_rate)

    print()
    print("=" * 70)
    print("  FINAL SUMMARY: Estimated briefing data per cycle")
    print("=" * 70)
    print()
    print(f"| Source              | Bi-weekly (3-4d) | Weekly (7d) |")
    print(f"|---------------------|------------------|-------------|")
    print(f"| FDA approvals       | ~{results.get('fda_4d', '?')}            | ~{results.get('fda_7d', '?')}         |")
    print(f"| EMA updates         | ~{results.get('ema_4d', '?')}             | ~{results.get('ema_7d', '?')}          |")
    print(f"| CT.gov Phase3 total | ~{ct_3d}             | ~{ct_7d}          |")
    print(f"|   fail (TERM/SUSP)  | ~{ct_fail_3d}             | ~{ct_fail_7d}          |")
    print(f"| medRxiv keyword     | ~{results.get('med_match_4d', '?')}             | ~{results.get('med_match_7d', '?')}          |")

    total_3d = results.get("fda_4d", 0) + results.get("ema_4d", 0) + ct_3d + results.get("med_match_4d", 0)
    total_7d = results.get("fda_7d", 0) + results.get("ema_7d", 0) + ct_7d + results.get("med_match_7d", 0)
    print(f"| TOTAL               | ~{total_3d}            | ~{total_7d}         |")
    print()

    # Qualitative assessment
    print("ASSESSMENT:")
    if total_3d >= 10:
        print(f"  Bi-weekly: ~{total_3d} items per cycle => SUFFICIENT for briefing")
    elif total_3d >= 5:
        print(f"  Bi-weekly: ~{total_3d} items per cycle => MARGINAL (thin briefings)")
    else:
        print(f"  Bi-weekly: ~{total_3d} items per cycle => INSUFFICIENT")

    if total_7d >= 10:
        print(f"  Weekly:    ~{total_7d} items per cycle => SUFFICIENT for briefing")
    elif total_7d >= 5:
        print(f"  Weekly:    ~{total_7d} items per cycle => MARGINAL")
    else:
        print(f"  Weekly:    ~{total_7d} items per cycle => INSUFFICIENT")


asyncio.run(main())
