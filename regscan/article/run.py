"""기사 전용 실행기 — 전체 배치 없이 기사만 생성

Usage:
    python -m regscan.article.run
    python -m regscan.article.run --days-back 14
"""

from __future__ import annotations

import asyncio
import argparse
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_articles(days_back: int = 30) -> None:
    """보조 소스 전체 수집 → 시그널 추출 → 엔리칭 → 4-Agent 기사 생성."""
    from regscan.batch.pipeline import _run_ingestor
    from regscan.stream.intelligence_signals import extract_signals
    from regscan.article.pipeline import generate_articles
    from regscan.config import settings

    started = datetime.now()
    logger.info("=== 기사 전용 파이프라인 시작 (days_back=%d) ===", days_back)

    # ── 전체 보조 소스 수집 (PMDA/NICE 포함) ──
    _aux_sources = []

    if settings.ENABLE_PMDA:
        from regscan.ingest.pmda import (
            PMDAReviewIngestor, PMDASafetyIngestor, PMDAApprovalIngestor,
        )
        _aux_sources += [
            (PMDAReviewIngestor, {"days_back": days_back}, "PMDA_REVIEW"),
            (PMDASafetyIngestor, {"days_back": days_back}, "PMDA_SAFETY"),
            (PMDAApprovalIngestor, {"years": 1, "days_back": days_back}, "PMDA_APPROVAL"),
        ]
    if settings.ENABLE_NICE_HTA:
        from regscan.ingest.nice import NICERecentTAIngestor
        _aux_sources.append(
            (NICERecentTAIngestor, {"years_back": 2}, "NICE_TA"),
        )
    if settings.ENABLE_MFDS_SAFETY:
        from regscan.ingest.mfds_safety import MFDSSafetyLetterIngestor
        _aux_sources.append(
            (MFDSSafetyLetterIngestor, {"days_back": days_back}, "MFDS_SAFETY_LETTER"),
        )
    if settings.ENABLE_MOHW_INSURANCE:
        from regscan.ingest.mohw_insurance import MOHWHealthInsuranceIngestor
        _aux_sources.append(
            (MOHWHealthInsuranceIngestor, {"days_back": days_back}, "MOHW_HEALTH_INSURANCE"),
        )
    if settings.ENABLE_ASSEMBLY_BILL:
        from regscan.ingest.assembly import AssemblyBillIngestor
        _aux_sources.append(
            (AssemblyBillIngestor, {"days_back": days_back}, "ASSEMBLY_BILL"),
        )
    if settings.ENABLE_DART:
        from regscan.ingest.dart import DARTDisclosureIngestor
        _aux_sources.append(
            (DARTDisclosureIngestor, {"days_back": days_back}, "DART_DISCLOSURE"),
        )
    if settings.ENABLE_KIPRIS:
        from regscan.ingest.kipris import KIPRISPatentIngestor
        _aux_sources.append(
            (KIPRISPatentIngestor, {"years": 3}, "KIPRIS_PATENT"),
        )
    if settings.ENABLE_KHIDI_NEWS:
        from regscan.ingest.khidi_news import KHIDIPharmaNewsIngestor
        _aux_sources.append(
            (KHIDIPharmaNewsIngestor, {"days_back": 7}, "KHIDI_PHARMA_NEWS"),
        )
    if settings.ENABLE_MFDS_SAFETY:
        from regscan.ingest.mfds_press import MFDSPressIngestor
        _aux_sources.append(
            (MFDSPressIngestor, {"days_back": 14}, "MFDS_PRESS"),
        )
    if settings.ENABLE_KHIDI_GLOBAL:
        from regscan.ingest.khidi_global import KHIDIGlobalInfoIngestor
        _aux_sources.append(
            (KHIDIGlobalInfoIngestor, {"days_back": days_back}, "KHIDI_GLOBAL_INFO"),
        )

    # ── 수집 ──
    aux_data: dict[str, list] = {}
    for cls, kwargs, src_type in _aux_sources:
        data = await _run_ingestor(cls, kwargs, src_type, "article-run")
        aux_data[src_type.lower()] = data

    # ── 시그널 추출 ──
    signals = extract_signals(aux_data)
    logger.info("시그널 소스 %d개:", len(signals))
    for k, v in signals.items():
        logger.info("  %s: %d건", k, len(v))

    if not signals:
        logger.warning("시그널 없음 — 기사 생성 중단")
        return

    # ── 기사 생성 (엔리칭 포함) ──
    articles = await generate_articles(signals)

    # ── MD 저장 ──
    if articles:
        date_str = datetime.now().strftime("%Y-%m-%d")
        article_dir = settings.BASE_DIR / "output" / "articles"
        article_dir.mkdir(parents=True, exist_ok=True)

        md = f"# RegScan Daily Articles\n\n> {date_str}\n\n"
        for i, art in enumerate(articles, 1):
            md += f"## {i}. {art.get('headline', '')}\n\n"
            md += f"**{art.get('subheadline', '')}**\n\n"
            md += art.get("body", "") + "\n\n"
            if art.get("_guardrail_corrections"):
                md += f"> guardrail: {len(art['_guardrail_corrections'])} corrections\n\n"
            md += "---\n\n"

        out_path = article_dir / f"articles_{date_str}.md"
        out_path.write_text(md, encoding="utf-8")
        logger.info("저장: %s", out_path)

    duration = (datetime.now() - started).total_seconds()
    logger.info("=== 기사 전용 파이프라인 완료: %d건 (%.1f초) ===", len(articles), duration)


def main():
    parser = argparse.ArgumentParser(description="기사 전용 파이프라인")
    parser.add_argument("--days-back", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run_articles(days_back=args.days_back))


if __name__ == "__main__":
    main()
