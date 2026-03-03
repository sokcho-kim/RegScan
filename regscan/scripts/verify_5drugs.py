"""5건 문제 약물 검증 스크립트

크롤러 근본 수정(2026-03-03) 후, 아래 5건 약물의 데이터가 올바르게
수집·조립되는지 파이프라인을 돌려서 확인한다.

대상:
  1. semaglutide         (GLP-1, 비만/당뇨)
  2. cabozantinib        (Multi-kinase inhibitor)
  3. zanidatamab         (Bispecific, HER2)
  4. setmelanotide       (MC4R agonist, 유전성 비만)
  5. polatuzumab vedotin (ADC, CD79b, DLBCL)

사용법:
    # Step 1: DB 현황만 확인 (API 호출 없음, ~2초)
    python -m regscan.scripts.verify_5drugs --check

    # Step 2: DB 중복 정리 (INN 정규화, ~5초)
    python -m regscan.scripts.verify_5drugs --dedup

    # Step 3: 스트림 재수집 + DB 적재 (API 호출, ~수분)
    python -m regscan.scripts.verify_5drugs --collect

    # Step 4: 5건 기사 재생성 (LLM 호출, ~1분)
    python -m regscan.scripts.verify_5drugs --publish

    # Step 5: 스냅샷 비교
    python -m regscan.scripts.verify_5drugs --compare

    # 전체 (2~5 순서대로)
    python -m regscan.scripts.verify_5drugs --full
"""

import io
import json
import logging
import re
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

# Windows cp949 stdout 깨짐 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )

from regscan.config import settings

logger = logging.getLogger(__name__)

TARGET_INNS = [
    "semaglutide",
    "cabozantinib",
    "zanidatamab",
    "setmelanotide",
    "polatuzumab vedotin",
]

OUTPUT_DIR = settings.BASE_DIR / "output" / "briefings"

_SEP = "=" * 70


def _header(title: str):
    print(f"\n{_SEP}")
    print(f"  {title}")
    print(f"{_SEP}")


# ═══════════════════════════════════════════
# Step 1: DB 현황 점검 (sync)
# ═══════════════════════════════════════════

def check_db_status() -> dict:
    """5건 약물의 DB 저장 상태를 sync로 조회한다."""
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.DATABASE_URL_SYNC)

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM drugs")).scalar()

        _header(f"DB 현황 점검 -- 전체 약물: {total}건")
        results = {}

        for inn in TARGET_INNS:
            # 해당 INN과 대소문자 변형 모두 조회
            rows = conn.execute(text(
                "SELECT d.id, d.inn, d.global_score, d.hot_issue_level, "
                "d.therapeutic_areas, d.domestic_status "
                "FROM drugs d WHERE lower(d.inn) LIKE :pat "
                "ORDER BY d.global_score DESC"
            ), {"pat": f"%{inn.lower()}%"}).fetchall()

            # 정확 매칭만 필터 (semaglutide != oral semaglutide)
            exact = [r for r in rows
                     if r[1].lower().strip() == inn.lower()
                     or r[1].lower().strip().startswith(inn.lower() + "-")]

            print(f"\n  {'*' if len(exact) > 1 else '>'} {inn}  "
                  f"({'중복 ' + str(len(exact)) + '건!' if len(exact) > 1 else str(len(exact)) + '건'})")

            drug_info = {"inn": inn, "count": len(exact), "variants": []}

            for r in exact:
                drug_id, db_inn, score, level, areas, domestic = r
                print(f"    id={drug_id:4d} inn={db_inn:30s} "
                      f"score={score:3d} level={level or '-':5s} "
                      f"areas={areas or '-'}")

                # 이벤트 조회
                evts = conn.execute(text(
                    "SELECT agency, status, approval_date, brand_name, "
                    "is_orphan, is_breakthrough, raw_data "
                    "FROM regulatory_events WHERE drug_id = :did "
                    "ORDER BY agency"
                ), {"did": drug_id}).fetchall()

                events = {}
                for ev in evts:
                    agency = ev[0]
                    raw = json.loads(ev[6]) if ev[6] else {}
                    events[agency] = {
                        "status": ev[1], "date": str(ev[2]) if ev[2] else None,
                        "brand": ev[3], "orphan": ev[4], "bt": ev[5],
                        "app_no": raw.get("application_number", ""),
                    }
                    flags = []
                    if ev[4]: flags.append("Orphan")
                    if ev[5]: flags.append("BT")
                    flag_str = f" [{','.join(flags)}]" if flags else ""
                    print(f"      {agency.upper():5s}: {ev[1] or '-':10s} "
                          f"date={ev[2] or '-'}  brand={ev[3] or '-'}{flag_str}")

                if not evts:
                    print(f"      (이벤트 없음)")

                # HIRA
                hira = conn.execute(text(
                    "SELECT status, price_ceiling, ingredient_code "
                    "FROM hira_reimbursements WHERE drug_id = :did"
                ), {"did": drug_id}).fetchall()
                for h in hira:
                    print(f"      HIRA: {h[0]}  price={h[1]}  code={h[2]}")

                drug_info["variants"].append({
                    "id": drug_id, "inn": db_inn, "score": score,
                    "events": events,
                })

            results[inn] = drug_info

    print(f"\n{_SEP}\n")
    return results


# ═══════════════════════════════════════════
# Step 2: DB 리셋 (백업 → 초기화)
# ═══════════════════════════════════════════

def reset_db():
    """현재 DB를 백업하고 빈 DB로 초기화한다."""
    import shutil
    from sqlalchemy import create_engine, text, inspect

    db_path = settings.DATA_DIR / "regscan.db"

    _header("DB 리셋")

    # 1) 백업
    if db_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_suffix(f".bak.{ts}")
        shutil.copy2(db_path, backup_path)
        size_mb = db_path.stat().st_size / 1024 / 1024
        print(f"  백업: {backup_path.name} ({size_mb:.1f} MB)")

    # 2) 전체 테이블 DROP (파일 삭제 대신 — 프로세스 잠금 우회)
    engine = create_engine(settings.DATABASE_URL_SYNC)
    insp = inspect(engine)
    tables = insp.get_table_names()

    if tables:
        with engine.begin() as conn:
            # FK 끄고 드롭
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            for t in tables:
                conn.execute(text(f"DROP TABLE IF EXISTS \"{t}\""))
                print(f"  DROP: {t}")
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(text("VACUUM"))
        print(f"  {len(tables)}개 테이블 제거 + VACUUM 완료")
    else:
        print(f"  테이블 없음 (신규 DB)")

    engine.dispose()
    print(f"  초기화 완료 -- 빈 DB로 파이프라인 실행 준비됨")
    print(f"{_SEP}\n")


# ═══════════════════════════════════════════
# Step 3: 스트림 재수집
# ═══════════════════════════════════════════

async def run_collection():
    """v3 3-Stream 파이프라인으로 데이터 재수집."""
    from regscan.batch.pipeline import run_stream_pipeline

    _header("스트림 재수집 (3-Stream pipeline)")

    result = await run_stream_pipeline(force=True)

    print(f"\n  상태: {result.get('status', 'unknown')}")
    for step, val in result.get("steps", {}).items():
        print(f"    {step}: {val}")
    print(f"{_SEP}\n")
    return result


# ═══════════════════════════════════════════
# Step 4: 5건 기사 생성
# ═══════════════════════════════════════════

async def publish_target_drugs():
    """5건 약물만 LLM V4 기사를 생성한다."""
    from regscan.scripts.publish_articles import (
        load_drugs_from_db, _safe_filename, _fetch_ctgov_results_batch,
        generate_article_html_v4, to_display_case, _get_copay_exemption,
    )
    from regscan.report.llm_generator import LLMBriefingGenerator, BriefingReport
    from regscan.db.database import init_db

    await init_db()

    _header("5건 약물 기사 생성 (V4)")

    target_set = {inn.lower() for inn in TARGET_INNS}

    # CT.gov 임상 결과 사전 조회
    print("  CT.gov 임상 결과 조회 중...")
    ctgov_cache = await _fetch_ctgov_results_batch(TARGET_INNS)
    print(f"  CT.gov: {len(ctgov_cache)}건 결과")

    # DB 전체 로드 후 5건 필터
    print("  DB 로드 중...")
    impacts = await load_drugs_from_db(
        top_n=700, min_score=0,
        ctgov_results_cache=ctgov_cache,
    )
    print(f"  DB 로드: {len(impacts)}건")

    # 5건 필터 (정확 매칭 + USAN 접미사 매칭)
    filtered = []
    for imp in impacts:
        norm = imp.inn.lower().strip()
        base = norm.rsplit("-", 1)[0] if "-" in norm else norm
        if norm in target_set or base in target_set:
            filtered.append(imp)

    if not filtered:
        print("  X 대상 약물 없음!")
        return {}

    print(f"\n  대상: {len(filtered)}건")
    for imp in filtered:
        print(f"    - {imp.inn} (score={imp.global_score})")

    # 뉴스 캐시
    if settings.ENABLE_NEWS_FETCH:
        try:
            from regscan.news.fetcher import fetch_news
            from regscan.news.matcher import match_news_to_inns
            news_articles = await fetch_news(days_back=settings.NEWS_FETCH_DAYS_BACK)
            if news_articles:
                news_cache = match_news_to_inns(news_articles)
                for imp in filtered:
                    imp._news_cache = news_cache
                print(f"  뉴스: {len(news_cache)} INN 매칭")
        except Exception as e:
            print(f"  뉴스 스킵: {e}")

    # LLM 생성
    generator = LLMBriefingGenerator(provider="openai", model="gpt-5.2")
    results = {}

    for i, impact in enumerate(filtered, 1):
        safe_name = _safe_filename(impact.inn)
        print(f"\n  [{i}/{len(filtered)}] {impact.inn} -- LLM 생성 중...")

        try:
            report = await generator.generate_v4(impact)

            # JSON
            report_data = report.to_dict()
            report_data["source_data"] = impact.to_dict()
            report_data["source_data"]["analysis"] = {
                "hot_issue_reasons": getattr(impact, 'hot_issue_reasons', []) or [],
            }
            report_data["source_data"]["therapeutic_areas"] = (
                getattr(impact, 'therapeutic_areas', []) or []
            )

            json_path = OUTPUT_DIR / f"{safe_name}.json"
            json_path.write_text(
                json.dumps(report_data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            # HTML
            _urls = getattr(impact, '_source_urls', None) or {}
            _nct = getattr(impact, 'clinical_results_nct_id', '') or ''
            _comp_inns = [c["inn"] for c in getattr(impact, '_competitors', []) or []]

            facts = {
                "inn": impact.inn,
                "source_data": report_data["source_data"],
                "d_day_text": generator._compute_d_day_text(impact),
                "approval_summary_table": generator._compute_approval_summary_table(impact),
                "cost_scenario_table": generator._compute_cost_scenario_table(impact),
            }
            insights = {
                "headline": report.headline,
                "subtitle": report.subtitle,
                "key_points": report.key_points,
                "global_insight_text": report.global_section,
                "domestic_insight_text": report.domestic_section,
                "medclaim_action_text": report.medclaim_section,
            }
            html_content = generate_article_html_v4(
                facts, insights, score=impact.global_score,
                source_urls=_urls, nct_id=_nct,
                known_inns=_comp_inns,
            )
            html_path = OUTPUT_DIR / f"{safe_name}.html"
            html_path.write_text(html_content, encoding="utf-8")

            results[impact.inn] = {
                "status": "success",
                "headline": report.headline,
                "score": impact.global_score,
            }
            print(f"    OK: {report.headline[:60]}...")

        except Exception as e:
            results[impact.inn] = {"status": "failed", "error": str(e)}
            logger.exception("LLM 생성 실패: %s", impact.inn)
            print(f"    FAIL: {e}")

    ok = sum(1 for v in results.values() if v["status"] == "success")
    fail = sum(1 for v in results.values() if v["status"] == "failed")
    print(f"\n  결과: 성공 {ok}, 실패 {fail}")
    print(f"{_SEP}\n")
    return results


# ═══════════════════════════════════════════
# Step 5: 스냅샷 비교
# ═══════════════════════════════════════════

def compare_with_snapshot():
    """최신 스냅샷과 현재 briefing을 비교한다."""
    snap_dir = OUTPUT_DIR / "snapshots"
    if not snap_dir.exists():
        print("  스냅샷 디렉터리 없음")
        return

    snaps = sorted([d for d in snap_dir.iterdir() if d.is_dir()])
    if not snaps:
        print("  스냅샷 없음")
        return

    latest_snap = snaps[-1]
    _header(f"비교: 현재 vs {latest_snap.name}")

    for inn in TARGET_INNS:
        safe = re.sub(r'[^\w\-]', '_', inn.lower())[:80]

        current_json = OUTPUT_DIR / f"{safe}.json"

        # 스냅샷 파일 찾기
        snap_json = None
        for f in latest_snap.iterdir():
            if f.suffix != ".json" or f.name.startswith("_"):
                continue
            if (safe in f.name.lower()
                    or inn.replace(" ", "_").lower() in f.name.lower()):
                snap_json = f
                break

        print(f"\n  > {inn}")

        if not current_json.exists():
            print(f"    현재: (없음)")
            continue
        if not snap_json:
            print(f"    스냅샷: (없음)")
            continue

        try:
            cur = json.loads(current_json.read_text(encoding="utf-8"))
            old = json.loads(snap_json.read_text(encoding="utf-8"))

            for field in ["headline", "subtitle"]:
                c_val = cur.get(field, "")[:80]
                o_val = old.get(field, "")[:80]
                if c_val != o_val:
                    print(f"    {field}: CHANGED")
                    print(f"      OLD: {o_val}")
                    print(f"      NEW: {c_val}")

            cur_src = cur.get("source_data", {})
            old_src = old.get("source_data", {})
            for key in ["fda_approved", "fda_date", "ema_approved", "ema_date",
                        "mfds_approved", "mfds_date", "global_score"]:
                c_v = cur_src.get(key)
                o_v = old_src.get(key)
                if c_v != o_v:
                    print(f"    {key}: {o_v} -> {c_v}")

            for section in ["global_section", "domestic_section", "medclaim_section"]:
                c_len = len(cur.get(section, ""))
                o_len = len(old.get(section, ""))
                diff = c_len - o_len
                sign = "+" if diff > 0 else ""
                print(f"    {section}: {o_len} -> {c_len} ({sign}{diff})")

        except Exception as e:
            print(f"    비교 실패: {e}")

    print(f"\n{_SEP}\n")


# ═══════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════

def main():
    import asyncio

    parser = ArgumentParser(description="5건 문제 약물 검증")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="DB 현황만 확인 (기본)")
    group.add_argument("--collect", action="store_true",
                       help="스트림 재수집 (API 호출)")
    group.add_argument("--publish", action="store_true",
                       help="5건 기사 재생성 (LLM 호출)")
    group.add_argument("--compare", action="store_true",
                       help="스냅샷 비교")
    group.add_argument("--reset", action="store_true",
                       help="DB 백업 -> 초기화 -> 전체 파이프라인 -> 5건 검증")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.collect:
        asyncio.run(run_collection())
    elif args.publish:
        asyncio.run(publish_target_drugs())
    elif args.compare:
        compare_with_snapshot()
    elif args.reset:
        print("\n>>> Phase 1: DB 리셋 (백업 -> 초기화)")
        reset_db()
        print("\n>>> Phase 2: 스트림 재수집 (3-Stream)")
        asyncio.run(run_collection())
        print("\n>>> Phase 3: DB 검증 (5건 약물)")
        check_db_status()
        print("\n>>> Phase 4: 기사 생성 (V4 LLM)")
        asyncio.run(publish_target_drugs())
        print("\n>>> Phase 5: 스냅샷 비교")
        compare_with_snapshot()
    else:
        check_db_status()


if __name__ == "__main__":
    main()
