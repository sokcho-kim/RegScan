"""Cloud Run Jobs 배치 파이프라인

매일 실행: 수집 → GCS 아카이브 → DB 적재 → LLM 브리핑 → (선택) HTML

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
        logger.info("[1/6] DB 초기화...")
        from regscan.db.database import init_db
        await init_db()
        result["steps"]["init_db"] = "ok"

        # Step 2: 일간 스캔
        logger.info("[2/6] 일간 스캔 실행...")
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
            logger.info("[3/6] GCS 아카이브...")
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
            logger.info("[3/6] GCS 아카이브 건너뜀 (GCS_BUCKET 미설정)")
            result["steps"]["gcs"] = "skipped"

        # Step 4: DB 적재
        logger.info("[4/6] DB 적재...")
        from regscan.api.deps import reload_data
        from regscan.db.loader import DBLoader

        # DataStore를 통해 파싱+분석 실행 (기존 로직 재사용)
        store = reload_data()

        loader = DBLoader()
        load_result = await loader.upsert_impacts(store.impacts)
        result["steps"]["db_load"] = load_result
        logger.info(f"  DB 적재 완료: {load_result}")

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

        # Step 5: LLM 브리핑 생성
        logger.info("[5/6] 핫이슈 LLM 브리핑 생성...")
        try:
            from regscan.api.routes.drugs import get_llm_generator

            generator = get_llm_generator()
            hot_issues = store.get_hot_issues(min_score=40)
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

        # Step 6: 스캔 결과 JSON 저장 (로컬 호환)
        logger.info("[6/6] 스캔 결과 JSON 저장...")
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
