"""APScheduler 기반 일간 파이프라인 스케줄러

매일 지정 시간에 일간 스캔 → 브리핑 생성 → HTML 생성 → 데이터 리로드를 실행합니다.
"""

import importlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from regscan.config import settings

logger = logging.getLogger(__name__)

# 모듈 레벨 상태
_scheduler: Optional[AsyncIOScheduler] = None
_last_run: Optional[dict] = None  # 마지막 실행 결과

OUTPUT_DIR = settings.BASE_DIR / "output" / "daily_scan"


async def run_daily_pipeline() -> dict:
    """일간 파이프라인 실행

    Cloud Run 환경에서는 batch/pipeline.py를 사용하세요.
    이 함수는 로컬 APScheduler 용입니다.

    1. DailyScanner.scan(days_back)
    2. 결과 JSON 저장
    3. HTML 뉴스레터 생성
    4. DataStore 리로드
    5. LLM 브리핑 생성·저장
    """
    global _last_run

    started_at = datetime.now()
    logger.info("=== 일간 파이프라인 시작 ===")

    result_summary = {
        "started_at": started_at.isoformat(),
        "status": "running",
        "steps": {},
    }

    try:
        # Step 1: 일간 스캔
        logger.info("[1/5] 일간 스캔 실행...")
        from regscan.monitor import DailyScanner

        scanner = DailyScanner()
        scanner.load_existing_data()

        async with scanner:
            scan_result = await scanner.scan(days_back=settings.SCAN_DAYS_BACK)

        result_summary["steps"]["scan"] = {
            "fda_new": len(scan_result.fda_new),
            "ema_new": len(scan_result.ema_new),
            "mfds_new": len(scan_result.mfds_new),
            "hot_issues": len(scan_result.hot_issues),
            "errors": scan_result.errors,
        }
        logger.info(
            f"      스캔 완료: FDA {len(scan_result.fda_new)}건, "
            f"EMA {len(scan_result.ema_new)}건, MFDS {len(scan_result.mfds_new)}건, "
            f"핫이슈 {len(scan_result.hot_issues)}건"
        )

        # Step 2: 결과 JSON 저장
        logger.info("[2/5] 스캔 결과 JSON 저장...")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        scan_json_path = OUTPUT_DIR / f"scan_{scan_result.scan_date}.json"
        scan_json_path.write_text(
            json.dumps(scan_result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result_summary["steps"]["save_json"] = str(scan_json_path)
        logger.info(f"      저장: {scan_json_path}")

        # Step 3: HTML 뉴스레터 생성
        if settings.GENERATE_HTML:
            logger.info("[3/5] HTML 뉴스레터 생성...")
            try:
                # scripts/ is not a package (no __init__.py), so we
                # temporarily add the project root to sys.path for import.
                # NOTE: importing this module has side-effects at module
                # level (sys.stdout reassignment, TestClient creation).
                _project_root = str(settings.BASE_DIR)
                _need_cleanup = _project_root not in sys.path
                if _need_cleanup:
                    sys.path.insert(0, _project_root)
                try:
                    mod = importlib.import_module("scripts.generate_daily_html")
                    generate_daily_html = mod.generate_daily_html
                finally:
                    if _need_cleanup and _project_root in sys.path:
                        sys.path.remove(_project_root)

                html_content = generate_daily_html(scan_result)
                html_path = OUTPUT_DIR / f"daily_briefing_{scan_result.scan_date}.html"
                html_path.write_text(html_content, encoding="utf-8")
                result_summary["steps"]["html"] = str(html_path)
                logger.info(f"      HTML 저장: {html_path}")
            except Exception as e:
                logger.warning(f"      HTML 생성 실패: {e}")
                result_summary["steps"]["html"] = f"error: {e}"
        else:
            logger.info("[3/5] HTML 생성 건너뜀 (GENERATE_HTML=False)")
            result_summary["steps"]["html"] = "skipped"

        # Step 4: DataStore 리로드
        logger.info("[4/6] DataStore 리로드...")
        from regscan.api.deps import reload_data

        store = reload_data()
        result_summary["steps"]["reload"] = {
            "drug_count": len(store.impacts),
            "loaded_at": store.loaded_at.isoformat() if store.loaded_at else None,
        }
        logger.info(f"      리로드 완료: {len(store.impacts)}개 약물")

        # Step 4.5: DB 적재 (PostgreSQL 모드일 때)
        if settings.is_postgres:
            logger.info("[4.5/6] DB 적재...")
            try:
                from regscan.db.loader import DBLoader
                loader = DBLoader()
                load_result = await loader.upsert_impacts(store.impacts)
                result_summary["steps"]["db_load"] = load_result
                logger.info(f"      DB 적재 완료: {load_result}")
            except Exception as e:
                logger.warning(f"      DB 적재 실패: {e}")
                result_summary["steps"]["db_load"] = f"error: {e}"

        # Step 5: 핫이슈 LLM 브리핑 일괄 생성·저장
        logger.info("[5/6] 핫이슈 LLM 브리핑 생성...")
        try:
            from regscan.api.routes.drugs import get_llm_generator
            from regscan.report.llm_generator import BriefingReport

            generator = get_llm_generator()
            hot_issues = store.get_hot_issues(min_score=40)
            generated, failed = 0, 0
            for drug in hot_issues:
                try:
                    report = await generator.generate(drug)
                    report.save()
                    generated += 1
                except Exception as e:
                    logger.warning(f"      브리핑 생성 실패 ({drug.inn}): {e}")
                    failed += 1
            result_summary["steps"]["briefings"] = {
                "generated": generated,
                "failed": failed,
            }
            logger.info(f"      브리핑 {generated}건 생성, {failed}건 실패")
        except Exception as e:
            logger.warning(f"      브리핑 배치 실패: {e}")
            result_summary["steps"]["briefings"] = f"error: {e}"

        # 완료
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result_summary["status"] = "success"
        result_summary["finished_at"] = finished_at.isoformat()
        result_summary["duration_seconds"] = round(duration, 1)

        logger.info(f"=== 일간 파이프라인 완료 ({duration:.1f}초) ===")

    except Exception as e:
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result_summary["status"] = "error"
        result_summary["error"] = str(e)
        result_summary["finished_at"] = finished_at.isoformat()
        result_summary["duration_seconds"] = round(duration, 1)
        logger.error(f"=== 일간 파이프라인 실패: {e} ({duration:.1f}초) ===", exc_info=True)

    _last_run = result_summary
    return result_summary


def start_scheduler() -> None:
    """스케줄러 시작"""
    global _scheduler

    if _scheduler is not None:
        logger.warning("스케줄러가 이미 실행 중입니다")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(
            hour=settings.DAILY_SCAN_HOUR,
            minute=settings.DAILY_SCAN_MINUTE,
        ),
        id="daily_pipeline",
        name="일간 규제 스캔 파이프라인",
        replace_existing=True,
    )
    _scheduler.start()

    next_run = _scheduler.get_job("daily_pipeline").next_run_time
    logger.info(
        f"스케줄러 시작: 매일 {settings.DAILY_SCAN_HOUR:02d}:{settings.DAILY_SCAN_MINUTE:02d} 실행 "
        f"(다음 실행: {next_run})"
    )


def stop_scheduler() -> None:
    """스케줄러 종료"""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("스케줄러 종료")


def get_scheduler_status() -> dict:
    """스케줄러 상태 조회"""
    if _scheduler is None:
        return {
            "enabled": settings.SCHEDULER_ENABLED,
            "running": False,
            "next_run": None,
            "last_run": _last_run,
        }

    job = _scheduler.get_job("daily_pipeline")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None

    return {
        "enabled": settings.SCHEDULER_ENABLED,
        "running": _scheduler.running,
        "schedule": f"{settings.DAILY_SCAN_HOUR:02d}:{settings.DAILY_SCAN_MINUTE:02d} daily",
        "scan_days_back": settings.SCAN_DAYS_BACK,
        "generate_html": settings.GENERATE_HTML,
        "next_run": next_run,
        "last_run": _last_run,
    }
