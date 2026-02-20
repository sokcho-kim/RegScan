"""기존 브리핑 JSON에 DB 메타데이터(source_urls, score, source_data) 패치.

LLM 호출 없이 DB 조회만으로 ~10초.
사용법: python scripts/patch_json_metadata.py
"""
import asyncio
import json
from pathlib import Path


async def patch():
    from regscan.db.database import init_db, get_async_session
    from regscan.db.models import DrugDB
    from regscan.map.matcher import IngredientMatcher
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await init_db()
    matcher = IngredientMatcher()
    d = Path("output/briefings")

    async with get_async_session()() as session:
        stmt = select(DrugDB).options(selectinload(DrugDB.events))
        result = await session.execute(stmt)
        drugs = {matcher.normalize(drug.inn): drug for drug in result.scalars().all()}

    patched = 0
    skipped = 0

    for jf in sorted(d.glob("*.json")):
        if jf.name.startswith("hot_issues_") or jf.name.startswith("all_articles_"):
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("inn"):
            continue

        inn = data["inn"]
        norm = matcher.normalize(inn)
        drug = drugs.get(norm)
        if not drug and "-" in norm:
            drug = drugs.get(norm.rsplit("-", 1)[0])
        if not drug:
            skipped += 1
            continue

        # source_urls 구축
        source_urls = {}
        sd = {
            "inn": drug.inn,
            "fda_approved": False, "fda_date": None,
            "ema_approved": False, "ema_date": None,
            "mfds_approved": False, "mfds_date": None,
            "mfds_brand_name": "",
            "domestic_status": drug.domestic_status or "",
            "hira_status": "",
            "global_score": drug.global_score,
        }

        for ev in drug.events:
            agency = (ev.agency or "").upper()
            if agency == "FDA":
                sd["fda_approved"] = ev.status == "approved"
                sd["fda_date"] = str(ev.approval_date) if ev.approval_date else None
                if ev.source_url:
                    source_urls["fda"] = ev.source_url
                elif ev.raw_data and isinstance(ev.raw_data, dict):
                    app_no = ev.raw_data.get("application_number", "")
                    if app_no:
                        clean = app_no.replace("BLA", "").replace("NDA", "")
                        source_urls["fda"] = (
                            f"https://www.accessdata.fda.gov/scripts/cder/daf/"
                            f"index.cfm?event=overview.process&ApplNo={clean}"
                        )
            elif agency == "EMA":
                sd["ema_approved"] = ev.status == "approved"
                sd["ema_date"] = str(ev.approval_date) if ev.approval_date else None
                if ev.source_url:
                    source_urls["ema"] = ev.source_url
                elif ev.raw_data and isinstance(ev.raw_data, dict):
                    ema_name = ev.raw_data.get("name_of_medicine", "")
                    if ema_name:
                        slug = ema_name.lower().replace(" ", "-")
                        source_urls["ema"] = (
                            f"https://www.ema.europa.eu/en/medicines/human/EPAR/{slug}"
                        )
            elif agency == "MFDS":
                sd["mfds_approved"] = ev.status == "approved"
                sd["mfds_date"] = str(ev.approval_date) if ev.approval_date else None
                sd["mfds_brand_name"] = ev.brand_name or ""

        sd["analysis"] = {"hot_issue_reasons": drug.hot_issue_reasons or []}
        ta = drug.therapeutic_areas.split(",") if drug.therapeutic_areas else []
        sd["therapeutic_areas"] = ta

        data["source_data"] = sd
        data["_source_urls"] = source_urls
        data["_score"] = drug.global_score
        data["_hot_issue_reasons"] = drug.hot_issue_reasons or []
        data["_therapeutic_areas"] = ta

        jf.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        patched += 1

    print(f"패치 완료: {patched}건, 스킵: {skipped}건")


if __name__ == "__main__":
    asyncio.run(patch())
