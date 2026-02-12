"""주2회 vs 주1회 시나리오별 샘플 브리핑 생성"""
import asyncio
import json
import httpx
from datetime import datetime, timedelta

OPENAI_API_KEY = None  # settings에서 로드

async def generate_briefing(content: str, scenario: str) -> str:
    """GPT-4o-mini로 브리핑 생성"""
    from regscan.config import settings
    api_key = settings.OPENAI_API_KEY

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": (
                        "당신은 제약/바이오 규제 동향 전문 애널리스트입니다. "
                        "주어진 데이터를 기반으로 한국 제약사 의사결정자를 위한 "
                        "간결하고 실용적인 브리핑을 작성하세요. "
                        "항목이 적어도 인사이트와 시사점을 도출하세요. "
                        "한국어로 작성하세요."
                    )},
                    {"role": "user", "content": content},
                ],
                "temperature": 0.3,
            },
        )
        return r.json()["choices"][0]["message"]["content"]


async def main():
    today = datetime.now()
    today_s = today.strftime("%Y-%m-%d")
    d4 = (today - timedelta(days=4)).strftime("%Y-%m-%d")
    d7 = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    headers = {"User-Agent": "RegScan/3.0 (Python aiohttp/3.12)"}
    api_key = "bnBZWNhcTfKsR04Fw5clAltjBAlvleSUsPG0ilkO"

    # ===== Collect real data for both windows =====
    scenarios = {}

    for label, start, days_label in [("biweekly", d4, "3-4d"), ("weekly", d7, "7d")]:
        data = {"fda": [], "ctgov": [], "ctgov_fails": [], "medrxiv": []}

        # FDA
        async with httpx.AsyncClient(timeout=30) as c:
            url = (
                f"https://api.fda.gov/drug/drugsfda.json?"
                f"search=submissions.submission_status_date:"
                f"[{start.replace('-', '')}+TO+{today_s.replace('-', '')}]"
                f"+AND+submissions.submission_status:\"AP\""
                f"&limit=20&api_key={api_key}"
            )
            r = await c.get(url)
            if r.status_code == 200:
                for res in r.json().get("results", []):
                    openfda = res.get("openfda", {})
                    gn = openfda.get("generic_name", [""])[0] or "?"
                    bn = openfda.get("brand_name", [""])[0] or ""
                    app = res.get("application_number", "")
                    epc = openfda.get("pharm_class_epc", [])
                    data["fda"].append({
                        "generic_name": gn, "brand_name": bn,
                        "application_number": app,
                        "pharm_class": ", ".join(epc[:2]) if epc else "N/A",
                    })

            # CT.gov
            conditions = [
                "Cancer", "Neoplasm", "Diabetes Mellitus", "Heart Failure",
                "Obesity", "Cardiovascular Disease", "Psoriasis",
                "Atopic Dermatitis", "Multiple Sclerosis", "Leukemia",
                "Carcinoma", "Lymphoma", "Crohn Disease", "Cystic Fibrosis",
            ]
            seen = set()
            for cond in conditions:
                p = {
                    "format": "json", "pageSize": 100, "query.cond": cond,
                    "filter.overallStatus": "COMPLETED,TERMINATED,SUSPENDED",
                    "filter.advanced": f"AREA[Phase]PHASE3 AND AREA[CompletionDate]RANGE[{start},{today_s}]",
                }
                try:
                    r = await c.get(
                        "https://clinicaltrials.gov/api/v2/studies",
                        params=p, headers=headers,
                    )
                    if r.status_code != 200:
                        continue
                    for s in r.json().get("studies", []):
                        proto = s.get("protocolSection", {})
                        nct = proto.get("identificationModule", {}).get("nctId", "")
                        if nct in seen:
                            continue
                        seen.add(nct)
                        status = proto.get("statusModule", {}).get("overallStatus", "")
                        title = proto.get("identificationModule", {}).get("briefTitle", "")
                        why = proto.get("statusModule", {}).get("whyStopped", "")
                        has_results = s.get("hasResults", False)

                        entry = {
                            "nct_id": nct, "status": status, "title": title[:100],
                            "condition": cond, "has_results": has_results,
                        }
                        if why:
                            entry["why_stopped"] = why

                        if status in ("TERMINATED", "SUSPENDED"):
                            data["ctgov_fails"].append(entry)
                        else:
                            data["ctgov"].append(entry)
                except:
                    continue

            # medRxiv
            try:
                url = f"https://api.biorxiv.org/details/medrxiv/{start}/{today_s}/0"
                r = await c.get(url)
                if r.status_code == 200:
                    articles = r.json().get("collection", [])
                    keywords = [
                        "phase 3", "phase III", "clinical trial",
                        "cost-effectiveness", "real-world evidence",
                        "drug approval", "regulatory",
                    ]
                    for art in articles:
                        title = art.get("title", "").lower()
                        abstract = art.get("abstract", "").lower()
                        text = f"{title} {abstract}"
                        if any(kw in text for kw in keywords):
                            data["medrxiv"].append({
                                "title": art.get("title", "")[:100],
                                "doi": art.get("doi", ""),
                                "date": art.get("date", ""),
                            })
            except:
                pass

        scenarios[label] = data

    # ===== Generate briefings =====
    for label, friendly in [("biweekly", "Bi-Weekly (3-4 days)"), ("weekly", "Weekly (7 days)")]:
        data = scenarios[label]

        prompt = f"""아래는 {friendly} 주기로 수집된 규제 동향 데이터입니다.
이 데이터를 기반으로 한국 제약사 규제팀을 위한 브리핑을 작성하세요.

## 수집 기간
{d4 if label == 'biweekly' else d7} ~ {today_s}

## FDA 승인 ({len(data['fda'])}건)
{json.dumps(data['fda'][:15], indent=2, ensure_ascii=False)}

## CT.gov Phase 3 완료 ({len(data['ctgov'])}건)
{json.dumps(data['ctgov'][:10], indent=2, ensure_ascii=False)}

## CT.gov Phase 3 실패/중단 ({len(data['ctgov_fails'])}건)
{json.dumps(data['ctgov_fails'][:10], indent=2, ensure_ascii=False)}

## medRxiv 키워드 매칭 논문 ({len(data['medrxiv'])}건)
{json.dumps(data['medrxiv'][:10], indent=2, ensure_ascii=False)}

---
요구사항:
1. 헤드라인 (1줄)
2. 핵심 요약 (3-5줄, 불릿)
3. 주요 이벤트 상세 (각 소스별)
4. 한국 시사점 (국내 제약사에 미치는 영향)
5. 데이터가 부족하면 솔직히 "이번 주기 주요 변동 없음"이라고 언급

형식: 마크다운
"""
        print("=" * 70)
        print(f"  SCENARIO: {friendly}")
        print(f"  Data: FDA={len(data['fda'])}, CT.gov completed={len(data['ctgov'])}, "
              f"CT.gov fail={len(data['ctgov_fails'])}, medRxiv={len(data['medrxiv'])}")
        print("=" * 70)

        briefing = await generate_briefing(prompt, label)
        print(briefing)
        print()

        # Save to file
        out_path = f"output/sample_briefing_{label}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Sample Briefing: {friendly}\n")
            f.write(f"Generated: {today_s}\n\n")
            f.write(f"Data volume: FDA={len(data['fda'])}, "
                    f"CT.gov={len(data['ctgov'])+len(data['ctgov_fails'])}, "
                    f"medRxiv={len(data['medrxiv'])}\n\n")
            f.write("---\n\n")
            f.write(briefing)
        print(f"  => Saved to {out_path}")
        print()


asyncio.run(main())
