"""Cloud Run Jobs 배치 파이프라인

v3: 3-Stream Top-Down Architecture
  --stream therapeutic|innovation|external  특정 스트림만 실행
  --area oncology                           특정 치료영역만 실행
  --legacy                                  기존 DailyScanner 모드 유지

기본 모드: 3-stream 전체 실행
레거시 모드: 기존 v2 파이프라인 (DailyScanner → DB → AI)

실행 예시:
    python -m regscan.batch.pipeline                            # 전체 3-stream
    python -m regscan.batch.pipeline --stream therapeutic       # Stream 1만
    python -m regscan.batch.pipeline --stream innovation        # Stream 2만
    python -m regscan.batch.pipeline --stream external          # Stream 3만
    python -m regscan.batch.pipeline --stream therapeutic --area oncology
    python -m regscan.batch.pipeline --legacy --days-back 7     # 기존 모드
"""

import asyncio
import json
import logging
import sys
import uuid
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from regscan.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# v3: 3-Stream Pipeline
# ═══════════════════════════════════════════════

async def run_stream_pipeline(
    streams: list[str] | None = None,
    area: str | None = None,
    force: bool = False,
) -> dict:
    """v3 스트림 기반 파이프라인

    Args:
        streams: 실행할 스트림 목록 (None이면 settings에서 읽음)
        area: 치료영역 필터 (therapeutic 스트림 전용)
        force: True면 변경 감지 무시

    Returns:
        실행 결과 요약 dict
    """
    started_at = datetime.now()
    pipeline_run_id = str(uuid.uuid4())

    stream_label = ", ".join(streams) if streams else "all"
    area_label = area or "all"
    logger.info(
        "=== v3 스트림 파이프라인 시작 (run_id=%s, streams=%s, area=%s) ===",
        pipeline_run_id, stream_label, area_label,
    )

    result = {
        "started_at": started_at.isoformat(),
        "pipeline_run_id": pipeline_run_id,
        "mode": "v3_stream",
        "streams": streams or "all",
        "area": area,
        "force": force,
        "status": "running",
        "steps": {},
    }

    try:
        # Step 1: DB 초기화
        logger.info("[1/6] DB 초기화...")
        from regscan.db.database import init_db
        await init_db()
        result["steps"]["init_db"] = "ok"

        # Step 1.5: PDUFA 시드 데이터 자동 투입
        try:
            from regscan.db.models import PdufaDateDB
            from sqlalchemy import select, func
            from regscan.db.database import get_async_session as _gas

            async with _gas()() as _sess:
                cnt_result = await _sess.execute(select(func.count(PdufaDateDB.id)))
                pdufa_count = cnt_result.scalar() or 0

            if pdufa_count == 0:
                seed_file = settings.DATA_DIR / "fda" / "pdufa_dates_2026.json"
                if seed_file.exists():
                    from regscan.scripts.seed_pdufa import seed_pdufa
                    seeded = await seed_pdufa(seed_file)
                    logger.info("[1.5/6] PDUFA 자동 시드: %d건", seeded)
                    result["steps"]["pdufa_seed"] = seeded
                else:
                    logger.debug("[1.5/6] PDUFA 시드 파일 없음, 건너뜀")
            else:
                logger.debug("[1.5/6] PDUFA 데이터 이미 존재 (%d건), 시드 건너뜀", pdufa_count)
        except Exception as e:
            logger.debug("[1.5/6] PDUFA 자동 시드 건너뜀: %s", e)

        # Step 2: 스트림 오케스트레이터 실행
        logger.info("[2/6] 스트림 수집 실행...")
        from regscan.stream.orchestrator import StreamOrchestrator

        areas_list = [area] if area else None
        orchestrator = StreamOrchestrator(
            enabled_streams=streams,
            areas=areas_list,
        )
        stream_results = await orchestrator.run_all()

        # 스트림별 결과 요약
        stream_summary = {}
        for sname, sresults in stream_results.items():
            total_drugs = sum(r.drug_count for r in sresults)
            total_signals = sum(r.signal_count for r in sresults)
            total_errors = sum(len(r.errors) for r in sresults)
            stream_summary[sname] = {
                "result_count": len(sresults),
                "drugs": total_drugs,
                "signals": total_signals,
                "errors": total_errors,
                "categories": [r.sub_category for r in sresults if r.sub_category],
            }
        result["steps"]["stream_collect"] = stream_summary

        # Step 3: 결과 병합 + GlobalRegulatoryStatus 빌드
        logger.info("[3/6] 결과 병합...")
        merged = orchestrator.merge_results(stream_results)
        global_statuses = orchestrator.build_global_statuses(merged)

        result["steps"]["merge"] = {
            "total_unique_drugs": len(merged),
            "global_statuses_built": len(global_statuses),
        }
        logger.info("  병합 완료: %d개 고유 약물", len(merged))

        # Step 4: DB 적재
        logger.info("[4/6] DB 적재...")
        from regscan.db.loader import DBLoader

        loader = DBLoader()

        # GlobalRegulatoryStatus → DomesticImpact 변환 (기존 분석기 재사용)
        try:
            from regscan.scan.domestic import DomesticImpactAnalyzer
            analyzer = DomesticImpactAnalyzer()
            impacts = analyzer.analyze_batch(global_statuses)
        except Exception:
            # 분석기 사용 불가 시 직접 변환
            impacts = global_statuses

        qualified = [
            d for d in impacts
            if getattr(d, "global_score", 0) >= settings.MIN_SCORE_FOR_DB
        ]
        skipped_count = len(impacts) - len(qualified)

        if qualified:
            load_result = await loader.upsert_impacts(
                qualified, pipeline_run_id=pipeline_run_id
            )
            result["steps"]["db_load"] = {
                "drugs": load_result.get("drugs", 0),
                "events": load_result.get("events", 0),
                "changed": load_result.get("changes", 0),
                "skipped_low_score": skipped_count,
            }
        else:
            result["steps"]["db_load"] = {
                "drugs": 0,
                "skipped_low_score": skipped_count,
                "note": "No drugs met MIN_SCORE_FOR_DB threshold",
            }
        logger.info(
            "  DB 적재 완료: %d건 적재, %d건 제외 (score<%d)",
            len(qualified), skipped_count, settings.MIN_SCORE_FOR_DB,
        )

        # Step 4.5: 스트림 스냅샷 저장
        try:
            await _save_stream_snapshots(stream_results, pipeline_run_id)
            result["steps"]["stream_snapshots"] = "ok"
        except Exception as e:
            logger.warning("  스트림 스냅샷 저장 실패: %s", e)
            result["steps"]["stream_snapshots"] = f"error: {e}"

        # Step 5: 스트림별 브리핑 생성
        if settings.ENABLE_STREAM_BRIEFINGS:
            logger.info("[5/6] 스트림 브리핑 생성...")
            try:
                briefing_result = await _generate_stream_briefings(
                    stream_results, pipeline_run_id,
                )
                result["steps"]["stream_briefings"] = briefing_result
            except Exception as e:
                logger.warning("  스트림 브리핑 실패: %s", e)
                result["steps"]["stream_briefings"] = f"error: {e}"
        else:
            logger.info("[5/6] 스트림 브리핑 건너뜀 (ENABLE_STREAM_BRIEFINGS=false)")
            result["steps"]["stream_briefings"] = "skipped"

        # Step 6: 결과 JSON 저장 (로컬)
        logger.info("[6/6] 결과 JSON 저장...")
        output_dir = settings.BASE_DIR / "output" / "stream_results"
        output_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        json_path = output_dir / f"stream_{date_str}_{pipeline_run_id[:8]}.json"

        # StreamResult는 직접 직렬화 필요
        serializable = {}
        for sname, sresults in stream_results.items():
            serializable[sname] = [
                {
                    "stream_name": r.stream_name,
                    "sub_category": r.sub_category,
                    "drug_count": r.drug_count,
                    "signal_count": r.signal_count,
                    "inn_list": r.inn_list[:50],
                    "errors": r.errors,
                }
                for r in sresults
            ]

        json_path.write_text(
            json.dumps(serializable, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        result["steps"]["save_json"] = str(json_path)

        # 완료
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "success"
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.info("=== v3 스트림 파이프라인 완료 (%.1f초) ===", duration)

    except Exception as e:
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "error"
        result["error"] = str(e)
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.error("=== v3 파이프라인 실패: %s (%.1f초) ===", e, duration, exc_info=True)

    return result


async def _save_stream_snapshots(
    stream_results: dict,
    pipeline_run_id: str,
) -> None:
    """스트림 스냅샷 DB 저장"""
    try:
        from regscan.db.database import get_async_session
        from regscan.db.models import StreamSnapshotDB

        async with get_async_session()() as session:
            for sname, sresults in stream_results.items():
                for sr in sresults:
                    snap = StreamSnapshotDB(
                        stream_name=sr.stream_name,
                        sub_category=sr.sub_category,
                        drug_count=sr.drug_count,
                        signal_count=sr.signal_count,
                        inn_list=sr.inn_list[:100],
                        pipeline_run_id=pipeline_run_id,
                    )
                    session.add(snap)
            await session.commit()
    except Exception as e:
        logger.debug("스트림 스냅샷 DB 저장 건너뜀: %s", e)


async def _generate_stream_briefings(
    stream_results: dict,
    pipeline_run_id: str,
) -> dict:
    """스트림별 + 통합 브리핑 생성"""
    from regscan.stream.briefing import StreamBriefingGenerator
    from regscan.stream.therapeutic import TherapeuticAreaConfig

    generator = StreamBriefingGenerator()
    briefing_counts = {"stream": 0, "unified": 0, "failed": 0}
    stream_briefings: list[dict] = []

    # 스트림별 브리핑
    for sname, sresults in stream_results.items():
        for sr in sresults:
            try:
                if sname == "therapeutic_area":
                    area_config = TherapeuticAreaConfig.get_area(sr.sub_category)
                    area_ko = area_config.label_ko if area_config else sr.sub_category
                    briefing = await generator.generate_therapeutic_briefing(
                        sr.sub_category, area_ko, sr,
                    )
                elif sname == "innovation":
                    briefing = await generator.generate_innovation_briefing(sr)
                elif sname == "external":
                    briefing = await generator.generate_external_briefing(sr)
                else:
                    continue

                stream_briefings.append(briefing)
                await _save_briefing_to_db(
                    sname, sr.sub_category, "stream",
                    briefing.get("headline", ""), briefing,
                    pipeline_run_id,
                )
                briefing_counts["stream"] += 1
            except Exception as e:
                logger.warning("  스트림 브리핑 생성 실패 (%s/%s): %s", sname, sr.sub_category, e)
                briefing_counts["failed"] += 1

    # 통합 브리핑
    if settings.ENABLE_UNIFIED_BRIEFING and stream_briefings:
        try:
            unified = await generator.generate_unified_briefing(
                stream_results, stream_briefings,
            )
            await _save_briefing_to_db(
                "unified", "", "unified",
                unified.get("headline", ""), unified,
                pipeline_run_id,
            )
            briefing_counts["unified"] = 1
        except Exception as e:
            logger.warning("  통합 브리핑 생성 실패: %s", e)
            briefing_counts["failed"] += 1

    return briefing_counts


async def _save_briefing_to_db(
    stream_name: str,
    sub_category: str,
    briefing_type: str,
    headline: str,
    content: dict,
    pipeline_run_id: str,
) -> None:
    """브리핑 DB 저장"""
    try:
        from regscan.db.database import get_async_session
        from regscan.db.models import StreamBriefingDB

        async with get_async_session()() as session:
            row = StreamBriefingDB(
                stream_name=stream_name,
                sub_category=sub_category,
                briefing_type=briefing_type,
                headline=headline,
                content_json=content,
                pipeline_run_id=pipeline_run_id,
            )
            session.add(row)
            await session.commit()
    except Exception as e:
        logger.debug("브리핑 DB 저장 건너뜀: %s", e)


# ═══════════════════════════════════════════════
# Legacy v2 Pipeline
# ═══════════════════════════════════════════════

async def run_pipeline(days_back: int = 7, force: bool = False) -> dict:
    """레거시 배치 파이프라인 (기존 DailyScanner 기반)

    Args:
        days_back: 최근 N일 수집
        force: True면 변경 감지 무시, 모든 약물 AI 처리

    Returns:
        실행 결과 요약 dict
    """
    started_at = datetime.now()
    pipeline_run_id = str(uuid.uuid4())
    logger.info("=== 레거시 배치 파이프라인 시작 (run_id=%s, force=%s) ===", pipeline_run_id, force)

    result = {
        "started_at": started_at.isoformat(),
        "pipeline_run_id": pipeline_run_id,
        "mode": "legacy",
        "force": force,
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

        # Step 4: DB 적재 (변경 감지 포함)
        logger.info("[4/9] DB 적재 (변경 감지)...")
        from regscan.api.deps import reload_data
        from regscan.db.loader import DBLoader

        store = reload_data()

        loader = DBLoader()
        qualified = [
            d for d in store.impacts
            if d.global_score >= settings.MIN_SCORE_FOR_DB
        ]
        skipped_count = len(store.impacts) - len(qualified)
        load_result = await loader.upsert_impacts(
            qualified, pipeline_run_id=pipeline_run_id
        )

        changed_drug_ids: set[int] = load_result["changed_drug_ids"]

        result["steps"]["db_load"] = {
            "drugs": load_result["drugs"],
            "events": load_result["events"],
            "hira": load_result["hira"],
            "trials": load_result["trials"],
            "changed": load_result["changes"],
        }
        logger.info(
            f"  DB 적재 완료: drugs={load_result['drugs']}, changed={load_result['changes']} "
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

        # Step 4.5: v2 신규 소스 수집
        v2_data = {"asti": [], "healthkr": [], "biorxiv": []}
        any_v2_enabled = (
            settings.ENABLE_ASTI or settings.ENABLE_HEALTHKR or settings.ENABLE_BIORXIV
        )
        if any_v2_enabled:
            logger.info("[4.5/9] v2 신규 소스 수집...")
            v2_counts = {}

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
        else:
            logger.info("[4.5/9] v2 소스 수집 건너뜀 (ENABLE_*=false)")
            result["steps"]["v2_ingest"] = "skipped"

        # 변경 필터 결정
        if force:
            target_filter = None
        elif changed_drug_ids:
            target_filter = changed_drug_ids
        else:
            target_filter = set()

        result["steps"]["change_detection"] = {
            "changed_count": len(changed_drug_ids),
            "mode": "force" if force else "event_trigger",
        }

        # Step 5: LLM 브리핑 생성
        logger.info("[5/9] 핫이슈 LLM 브리핑 생성...")
        try:
            from regscan.api.routes.drugs import get_llm_generator

            generator = get_llm_generator()
            hot_issues = store.get_hot_issues(min_score=settings.MIN_SCORE_FOR_BRIEFING)
            generated, failed, skipped_unchanged = 0, 0, 0

            for drug in hot_issues:
                if target_filter is not None:
                    drug_id = await _get_drug_id_by_inn(loader, drug.inn)
                    if drug_id not in target_filter:
                        skipped_unchanged += 1
                        continue

                try:
                    report = await generator.generate(drug)
                    await loader.save_briefing(report)
                    report.save()
                    generated += 1
                except Exception as e:
                    logger.warning(f"  브리핑 실패 ({drug.inn}): {e}")
                    failed += 1

            result["steps"]["briefings"] = {
                "generated": generated, "failed": failed,
                "skipped_unchanged": skipped_unchanged,
            }
        except Exception as e:
            logger.warning(f"  브리핑 배치 실패: {e}")
            result["steps"]["briefings"] = f"error: {e}"

        # Step 6: 스캔 결과 JSON 저장
        logger.info("[6/9] 스캔 결과 JSON 저장...")
        output_dir = settings.BASE_DIR / "output" / "daily_scan"
        output_dir.mkdir(parents=True, exist_ok=True)
        scan_json_path = output_dir / f"scan_{scan_result.scan_date}.json"
        scan_json_path.write_text(
            json.dumps(scan_result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["steps"]["save_json"] = str(scan_json_path)

        # 완료
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "success"
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.info(f"=== 레거시 파이프라인 완료 ({duration:.1f}초) ===")

    except Exception as e:
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        result["status"] = "error"
        result["error"] = str(e)
        result["finished_at"] = finished_at.isoformat()
        result["duration_seconds"] = round(duration, 1)
        logger.error(f"=== 레거시 파이프라인 실패: {e} ({duration:.1f}초) ===", exc_info=True)

    return result


async def _get_drug_id_by_inn(loader, inn: str) -> int | None:
    """INN으로 drug_id를 조회하는 헬퍼."""
    async with loader._session_factory() as session:
        from sqlalchemy import select
        from regscan.db.models import DrugDB
        stmt = select(DrugDB.id).where(DrugDB.inn == inn)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


def main():
    """CLI 진입점"""
    parser = ArgumentParser(description="RegScan 배치 파이프라인 (v3 3-Stream)")
    parser.add_argument("--days-back", type=int, default=settings.SCAN_DAYS_BACK)
    parser.add_argument("--log-level", default=settings.LOG_LEVEL)
    parser.add_argument(
        "--force", action="store_true",
        help="변경 감지 무시, 전수 처리",
    )
    parser.add_argument(
        "--stream", type=str, default=None,
        help="특정 스트림만 실행 (therapeutic, innovation, external)",
    )
    parser.add_argument(
        "--area", type=str, default=None,
        help="특정 치료영역만 실행 (oncology, rare_disease, immunology, cardiovascular, metabolic)",
    )
    parser.add_argument(
        "--legacy", action="store_true",
        help="기존 DailyScanner 기반 레거시 모드",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.legacy:
        # 레거시 모드
        result = asyncio.run(run_pipeline(days_back=args.days_back, force=args.force))
    else:
        # v3 스트림 모드
        streams = [args.stream] if args.stream else None
        result = asyncio.run(run_stream_pipeline(
            streams=streams,
            area=args.area,
            force=args.force,
        ))

    # 결과 출력
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 실패 시 비정상 종료 코드
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
