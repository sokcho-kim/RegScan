"""Cloud Run Jobs 배치 파이프라인

매일 실행: 수집 → GCS 아카이브 → DB 적재 → (v2) 신규 소스 수집
          → (v2) Gemini PDF → LLM 브리핑 → (v2) AI 파이프라인 → HTML

실행:
    python -m regscan.batch.pipeline
    python -m regscan.batch.pipeline --days-back 7
"""

import asyncio
import json
import logging
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from regscan.config import settings

logger = logging.getLogger(__name__)


async def run_pipeline(days_back: int = 7) -> dict:
    """배치 파이프라인 메인 로직

    Returns:
        실행 결과 요약 dict
    """
    started_at = datetime.now()
    logger.info("=== 배치 파이프라인 시작 ===")

    result = {
        "started_at": started_at.isoformat(),
        "status": "running",
        "steps": {},
    }

    try:
        # Step 1: DB 초기화
        logger.info("[1/9] DB 초기화...")
        from regscan.db.database import init_db
        await init_db()
        result["steps"]["init_db"] = "ok"

        # Step 2: 일간 스캔
        logger.info("[2/9] 일간 스캔 실행...")
        from regscan.monitor import DailyScanner

        scanner = DailyScanner()
        scanner.load_existing_data()

        async with scanner:
            scan_result = await scanner.scan(days_back=days_back)

        result["steps"]["scan"] = {
            "fda_new": len(scan_result.fda_new),
            "ema_new": len(scan_result.ema_new),
            "mfds_new": len(scan_result.mfds_new),
            "hot_issues": len(scan_result.hot_issues),
            "errors": scan_result.errors,
        }
        logger.info(
            f"  스캔 완료: FDA {len(scan_result.fda_new)}, "
            f"EMA {len(scan_result.ema_new)}, MFDS {len(scan_result.mfds_new)}, "
            f"핫이슈 {len(scan_result.hot_issues)}"
        )

        # Step 3: GCS 아카이브 (설정된 경우에만)
        if settings.GCS_BUCKET:
            logger.info("[3/9] GCS 아카이브...")
            from regscan.storage.gcs import get_gcs_storage

            gcs = get_gcs_storage()
            scan_date = scan_result.scan_date
            gcs_paths = {}

            if scan_result.fda_new:
                path = gcs.archive_scan(scan_date, "fda", [a.to_dict() for a in scan_result.fda_new])
                gcs_paths["fda"] = path
            if scan_result.ema_new:
                path = gcs.archive_scan(scan_date, "ema", [a.to_dict() for a in scan_result.ema_new])
                gcs_paths["ema"] = path
            if scan_result.mfds_new:
                path = gcs.archive_scan(scan_date, "mfds", [a.to_dict() for a in scan_result.mfds_new])
                gcs_paths["mfds"] = path

            result["steps"]["gcs"] = gcs_paths
            logger.info(f"  GCS 아카이브 완료: {len(gcs_paths)}개 소스")
        else:
            logger.info("[3/9] GCS 아카이브 건너뜀 (GCS_BUCKET 미설정)")
            result["steps"]["gcs"] = "skipped"

        # Step 4: DB 적재
        logger.info("[4/9] DB 적재...")
        from regscan.api.deps import reload_data
        from regscan.db.loader import DBLoader

        # DataStore를 통해 파싱+분석 실행 (기존 로직 재사용)
        store = reload_data()

        loader = DBLoader()
        qualified = [
            d for d in store.impacts
            if d.global_score >= settings.MIN_SCORE_FOR_DB
        ]
        skipped_count = len(store.impacts) - len(qualified)
        load_result = await loader.upsert_impacts(qualified)
        result["steps"]["db_load"] = load_result
        logger.info(
            f"  DB 적재 완료: {load_result} "
            f"(score<{settings.MIN_SCORE_FOR_DB} 제외: {skipped_count}건)"
        )

        # 스냅샷 메타 저장
        from datetime import date as date_type
        scan_date_obj = date_type.fromisoformat(scan_result.scan_date)
        for source, count in [
            ("fda", len(scan_result.fda_new)),
            ("ema", len(scan_result.ema_new)),
            ("mfds", len(scan_result.mfds_new)),
        ]:
            if count > 0:
                gcs_path = result["steps"].get("gcs", {}).get(source, "")
                await loader.save_snapshot(source, scan_date_obj, count, gcs_path)

        # Step 4.5: v2 신규 소스 수집 (ENABLE_* 플래그 체크)
        v2_data = {"asti": [], "healthkr": [], "biorxiv": []}
        any_v2_enabled = (
            settings.ENABLE_ASTI or settings.ENABLE_HEALTHKR or settings.ENABLE_BIORXIV
        )
        if any_v2_enabled:
            logger.info("[4.5/9] v2 신규 소스 수집...")
            v2_counts = {}

            # ASTI
            if settings.ENABLE_ASTI:
                try:
                    from regscan.ingest.asti import ASTIIngestor
                    from regscan.parse.asti_parser import ASTIReportParser

                    async with ASTIIngestor() as ingestor:
                        raw = await ingestor.fetch()
                    parser = ASTIReportParser()
                    v2_data["asti"] = parser.parse_many(raw)
                    v2_counts["asti"] = len(v2_data["asti"])
                    logger.info("  ASTI: %d건", v2_counts["asti"])
                except Exception as e:
                    logger.warning("  ASTI 수집 실패: %s", e)
                    v2_counts["asti"] = f"error: {e}"

            # Health.kr
            if settings.ENABLE_HEALTHKR:
                try:
                    from regscan.ingest.healthkr import HealthKRIngestor
                    from regscan.parse.healthkr_parser import HealthKRParser

                    hot_inns = [d.inn for d in store.get_hot_issues(min_score=settings.MIN_SCORE_FOR_AI_PIPELINE)]
                    ingestor = HealthKRIngestor(drug_names=hot_inns[:20])
                    async with ingestor:
                        raw = await ingestor.fetch()
                    parser = HealthKRParser()
                    v2_data["healthkr"] = parser.parse_many(raw)
                    v2_counts["healthkr"] = len(v2_data["healthkr"])
                    logger.info("  Health.kr: %d건", v2_counts["healthkr"])
                except Exception as e:
                    logger.warning("  Health.kr 수집 실패: %s", e)
                    v2_counts["healthkr"] = f"error: {e}"

            # bioRxiv
            if settings.ENABLE_BIORXIV:
                try:
                    from regscan.ingest.biorxiv import BioRxivIngestor
                    from regscan.parse.biorxiv_parser import BioRxivParser

                    hot_inns = [d.inn for d in store.get_hot_issues(min_score=settings.MIN_SCORE_FOR_AI_PIPELINE)]
                    ingestor = BioRxivIngestor(
                        drug_keywords=hot_inns[:20], days_back=days_back
                    )
                    async with ingestor:
                        raw = await ingestor.fetch()
                    parser = BioRxivParser()
                    v2_data["biorxiv"] = parser.parse_many(raw)
                    v2_counts["biorxiv"] = len(v2_data["biorxiv"])
                    logger.info("  bioRxiv: %d건", v2_counts["biorxiv"])
                except Exception as e:
                    logger.warning("  bioRxiv 수집 실패: %s", e)
                    v2_counts["biorxiv"] = f"error: {e}"

            result["steps"]["v2_ingest"] = v2_counts

            # v2 데이터 DB 적재
            try:
                from regscan.db.v2_loader import V2Loader
                v2_loader = V2Loader()

                for report in v2_data["asti"]:
                    try:
                        drug_id = await v2_loader.get_drug_id(report.get("title", "unknown"))
                        await v2_loader.upsert_market_report(drug_id, report)
                    except Exception as e:
                        logger.debug("ASTI DB 적재 오류: %s", e)

                for review in v2_data["healthkr"]:
                    try:
                        inn = review.get("drug_name", review.get("title", "unknown"))
                        drug_id = await v2_loader.get_drug_id(inn)
                        await v2_loader.upsert_expert_opinion(drug_id, review)
                    except Exception as e:
                        logger.debug("Health.kr DB 적재 오류: %s", e)

                for preprint in v2_data["biorxiv"]:
                    try:
                        inn = preprint.get("search_keyword", "unknown")
                        drug_id = await v2_loader.get_drug_id(inn)
                        await v2_loader.upsert_preprint(drug_id, preprint)
                    except Exception as e:
                        logger.debug("bioRxiv DB 적재 오류: %s", e)

            except Exception as e:
                logger.warning("  v2 DB 적재 실패: %s", e)
        else:
            logger.info("[4.5/9] v2 소스 수집 건너뜀 (ENABLE_*=false)")
            result["steps"]["v2_ingest"] = "skipped"

        # Step 4.6: Gemini PDF 파싱 (ENABLE_GEMINI_PARSING 체크)
        if settings.ENABLE_GEMINI_PARSING and v2_data["biorxiv"]:
            logger.info("[4.6/9] Gemini PDF 파싱...")
            try:
                from regscan.ai.gemini_parser import GeminiParser
                from regscan.db.v2_loader import V2Loader

                gemini = GeminiParser()
                v2_loader = V2Loader()
                parsed_count = 0

                # 핫이슈(score>=60) 논문만 파싱
                for preprint in v2_data["biorxiv"]:
                    if preprint.get("pdf_url") and parsed_count < 20:
                        try:
                            parse_result = await gemini.parse_pdf_url(preprint["pdf_url"])
                            if parse_result.get("facts"):
                                await v2_loader.update_preprint_gemini(
                                    preprint["doi"], parse_result["facts"]
                                )
                                parsed_count += 1
                        except Exception as e:
                            logger.debug("Gemini 파싱 오류 (%s): %s", preprint.get("doi"), e)

                result["steps"]["gemini_parse"] = {"parsed": parsed_count}
                logger.info("  Gemini 파싱 완료: %d건", parsed_count)
            except Exception as e:
                logger.warning("  Gemini 파싱 실패: %s", e)
                result["steps"]["gemini_parse"] = f"error: {e}"
        else:
            logger.info("[4.6/9] Gemini 파싱 건너뜀")
            result["steps"]["gemini_parse"] = "skipped"

        # Step 5: LLM 브리핑 생성
        logger.info("[5/9] 핫이슈 LLM 브리핑 생성...")
        try:
            from regscan.api.routes.drugs import get_llm_generator

            generator = get_llm_generator()
            hot_issues = store.get_hot_issues(min_score=settings.MIN_SCORE_FOR_BRIEFING)
            generated, failed = 0, 0

            for drug in hot_issues:
                try:
                    report = await generator.generate(drug)
                    # DB에 저장
                    await loader.save_briefing(report)
                    # 파일에도 저장 (호환)
                    report.save()
                    generated += 1
                except Exception as e:
                    logger.warning(f"  브리핑 실패 ({drug.inn}): {e}")
                    failed += 1

            result["steps"]["briefings"] = {"generated": generated, "failed": failed}
            logger.info(f"  브리핑 {generated}건 생성, {failed}건 실패")
        except Exception as e:
            logger.warning(f"  브리핑 배치 실패: {e}")
            result["steps"]["briefings"] = f"error: {e}"

        # Step 5.5: v2 AI 3단 파이프라인 (Reasoning→Verify→Write)
        ai_enabled = (
            settings.ENABLE_AI_REASONING
            or settings.ENABLE_AI_VERIFIER
            or settings.ENABLE_AI_WRITER
        )
        if ai_enabled:
            logger.info("[5.5/9] AI 3단 파이프라인...")
            try:
                from regscan.ai.pipeline import AIIntelligencePipeline
                from regscan.db.v2_loader import V2Loader

                ai_pipeline = AIIntelligencePipeline()
                v2_loader = V2Loader()
                ai_generated, ai_failed = 0, 0

                hot_issues = store.get_hot_issues(min_score=settings.MIN_SCORE_FOR_AI_PIPELINE)
                for drug in hot_issues:
                    try:
                        drug_dict = {
                            "inn": drug.inn,
                            "fda_approved": drug.fda_approved,
                            "fda_date": str(drug.fda_date) if drug.fda_date else None,
                            "ema_approved": drug.ema_approved,
                            "ema_date": str(drug.ema_date) if drug.ema_date else None,
                            "mfds_approved": drug.mfds_approved,
                            "mfds_date": str(drug.mfds_date) if drug.mfds_date else None,
                            "hira_status": drug.hira_status.value if drug.hira_status else None,
                            "hira_price": drug.hira_price,
                            "global_score": drug.global_score,
                        }

                        insight, article = await ai_pipeline.run(
                            drug=drug_dict,
                            preprints=v2_data.get("biorxiv", []),
                            market_reports=v2_data.get("asti", []),
                            expert_opinions=v2_data.get("healthkr", []),
                        )

                        # DB 저장
                        drug_id = await v2_loader.get_drug_id(drug.inn)
                        if insight:
                            await v2_loader.save_ai_insight(drug_id, insight)
                        if article and article.get("headline"):
                            await v2_loader.save_article(drug_id, article)

                        ai_generated += 1
                    except Exception as e:
                        logger.warning("  AI 파이프라인 실패 (%s): %s", drug.inn, e)
                        ai_failed += 1

                result["steps"]["ai_pipeline"] = {
                    "generated": ai_generated, "failed": ai_failed,
                    "usage": ai_pipeline.get_daily_usage(),
                }
                logger.info("  AI 파이프라인 %d건 성공, %d건 실패", ai_generated, ai_failed)
            except Exception as e:
                logger.warning("  AI 파이프라인 실패: %s", e)
                result["steps"]["ai_pipeline"] = f"error: {e}"
        else:
            logger.info("[5.5/9] AI 파이프라인 건너뜀 (ENABLE_AI_*=false)")
            result["steps"]["ai_pipeline"] = "skipped"

        # Step 6: 스캔 결과 JSON 저장 (로컬 호환)
        logger.info("[6/9] 스캔 결과 JSON 저장...")
        output_dir = settings.BASE_DIR / "output" / "daily_scan"
        output_dir.mkdir(parents=True, exist_ok=True)
        scan_json_path = output_dir / f"scan_{scan_result.scan_date}.json"
        scan_json_path.write_text(
            json.dumps(scan_result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["steps"]["save_json"] = str(scan_json_path)
        logger.info(f"  저장: {scan_json_path}")

        # 완료
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "success"
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.info(f"=== 배치 파이프라인 완료 ({duration:.1f}초) ===")

    except Exception as e:
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "error"
        result["error"] = str(e)
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.error(f"=== 배치 파이프라인 실패: {e} ({duration:.1f}초) ===", exc_info=True)

    return result


def main():
    """CLI 진입점"""
    parser = ArgumentParser(description="RegScan 배치 파이프라인")
    parser.add_argument("--days-back", type=int, default=settings.SCAN_DAYS_BACK)
    parser.add_argument("--log-level", default=settings.LOG_LEVEL)
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    result = asyncio.run(run_pipeline(days_back=args.days_back))

    # 결과 출력
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 실패 시 비정상 종료 코드
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
