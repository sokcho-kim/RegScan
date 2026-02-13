"""3-Model 브리핑 비교 스크립트

GPT-4o-mini, GPT-5, Gemini 3개 모델로 동일 약물에 대한 브리핑을 생성하고
품질을 비교한다.

사용법:
    python -m regscan.scripts.compare_models                    # 상위 3개 약물 자동 선정
    python -m regscan.scripts.compare_models --inn pembrolizumab  # 특정 약물 지정
    python -m regscan.scripts.compare_models --top 5             # 상위 5개 약물
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

OUTPUT_DIR = settings.BASE_DIR / "output" / "model_comparison"


async def load_top_impacts(top_n: int = 3, inn: str | None = None):
    """DB에서 상위 약물의 DomesticImpact 로드"""
    from regscan.db.database import init_db, get_async_session
    from regscan.db.models import DrugDB, RegulatoryEventDB
    from regscan.scan.domestic import DomesticImpactAnalyzer
    from regscan.map.global_status import (
        GlobalRegulatoryStatus, RegulatoryApproval, ApprovalStatus,
    )
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await init_db()

    async with get_async_session()() as session:
        if inn:
            stmt = (
                select(DrugDB)
                .options(selectinload(DrugDB.events))
                .where(DrugDB.inn == inn)
            )
        else:
            stmt = (
                select(DrugDB)
                .options(selectinload(DrugDB.events))
                .where(DrugDB.global_score > 0)
                .order_by(DrugDB.global_score.desc())
                .limit(top_n)
            )
        result = await session.execute(stmt)
        drugs = result.scalars().all()

        if not drugs:
            logger.error("DB에 약물 데이터 없음. 파이프라인을 먼저 실행하세요.")
            return []

        # DrugDB → GlobalRegulatoryStatus → DomesticImpact 변환 (세션 내)
        analyzer = DomesticImpactAnalyzer()
        impacts = []

        for drug in drugs:
            status = GlobalRegulatoryStatus(inn=drug.inn)
            status.global_score = drug.global_score
            status.hot_issue_reasons = drug.hot_issue_reasons or []
            status.therapeutic_areas = (
                drug.therapeutic_areas.split(",") if drug.therapeutic_areas else []
            )
            status.stream_sources = drug.stream_sources or []

            # FDA/EMA/MFDS 이벤트에서 RegulatoryApproval 생성
            for ev in drug.events:
                approval = RegulatoryApproval(
                    agency=ev.agency.upper(),
                    status=(ApprovalStatus.APPROVED if ev.status == "approved"
                            else ApprovalStatus.PENDING),
                    approval_date=ev.approval_date,
                    brand_name=ev.brand_name or "",
                )
                if ev.agency == "fda":
                    status.fda = approval
                elif ev.agency == "ema":
                    status.ema = approval
                elif ev.agency == "mfds":
                    status.mfds = approval

            impact = analyzer.analyze(status)
            impacts.append(impact)
            logger.info("  로드: %s (score=%d)", drug.inn, drug.global_score)

    return impacts


async def run_comparison(
    top_n: int = 3,
    inn: str | None = None,
):
    """3-Model 비교 실행"""
    from regscan.report.llm_generator import LLMBriefingGenerator, compare_models

    impacts = await load_top_impacts(top_n=top_n, inn=inn)
    if not impacts:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 사용 가능한 모델 확인
    models = []
    if settings.OPENAI_API_KEY:
        models.append(("openai", "gpt-4o-mini"))
        models.append(("openai", "gpt-5"))
    else:
        logger.warning("OPENAI_API_KEY 미설정 — OpenAI 모델 건너뜀")

    if settings.GEMINI_API_KEY:
        models.append(("gemini", settings.GEMINI_MODEL))
    else:
        logger.warning("GEMINI_API_KEY 미설정 — Gemini 모델 건너뜀")

    if not models:
        logger.error("사용 가능한 API 키 없음. .env 파일에 OPENAI_API_KEY / GEMINI_API_KEY 설정 필요.")
        return

    logger.info("=== 3-Model 브리핑 비교 시작 ===")
    logger.info("  대상 약물: %d건", len(impacts))
    logger.info("  비교 모델: %s", ", ".join(f"{p}/{m}" for p, m in models))

    all_comparisons = []

    for impact in impacts:
        logger.info("\n--- %s (score=%d) ---", impact.inn, impact.global_score)

        results = await compare_models(impact, models=models)

        comparison = {
            "inn": impact.inn,
            "global_score": impact.global_score,
            "hot_issue_reasons": impact.hot_issue_reasons,
            "models": {},
        }

        for model_key, report in results.items():
            if report is None:
                logger.warning("  %s: 실패", model_key)
                comparison["models"][model_key] = {"status": "failed"}
                continue

            comparison["models"][model_key] = {
                "status": "success",
                "headline": report.headline,
                "subtitle": report.subtitle,
                "key_points": report.key_points,
                "global_section_len": len(report.global_section),
                "domestic_section_len": len(report.domestic_section),
                "medclaim_section_len": len(report.medclaim_section),
            }

            logger.info("  %s:", model_key)
            logger.info("    헤드라인: %s", report.headline)
            logger.info("    서브타이틀: %s", report.subtitle)

            # 개별 마크다운 저장
            safe_name = impact.inn.replace(" ", "_").replace("/", "_")[:60]
            provider_name = model_key.replace("/", "_")
            md_path = OUTPUT_DIR / f"{safe_name}_{provider_name}.md"
            md_path.write_text(report.to_markdown(), encoding="utf-8")

        all_comparisons.append(comparison)

    # 비교 결과 JSON 저장
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    json_path = OUTPUT_DIR / f"comparison_{date_str}.json"
    json_path.write_text(
        json.dumps(all_comparisons, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("\n=== 비교 완료 ===")
    logger.info("  결과 저장: %s", json_path)
    logger.info("  마크다운: %s/*.md", OUTPUT_DIR)

    # 콘솔 요약
    print("\n" + "=" * 60)
    print("  3-Model Briefing Comparison Summary")
    print("=" * 60)
    for comp in all_comparisons:
        print(f"\n[{comp['inn']}] (score={comp['global_score']})")
        for model_key, data in comp["models"].items():
            if data["status"] == "failed":
                print(f"  {model_key}: FAILED")
            else:
                print(f"  {model_key}:")
                print(f"    headline: {data['headline'][:60]}...")
                total_len = (
                    data["global_section_len"]
                    + data["domestic_section_len"]
                    + data["medclaim_section_len"]
                )
                print(f"    total content length: {total_len:,} chars")
    print("=" * 60)


def main():
    parser = ArgumentParser(description="3-Model 브리핑 비교")
    parser.add_argument("--inn", type=str, help="특정 약물 INN")
    parser.add_argument("--top", type=int, default=3, help="상위 N개 약물 (기본 3)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asyncio.run(run_comparison(top_n=args.top, inn=args.inn))


if __name__ == "__main__":
    main()
