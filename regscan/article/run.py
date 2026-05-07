"""기사 전용 실행기 — 수집 → 기사 생성 → 출처 → HTML 일괄 실행

Usage:
    python -m regscan.article.run
    python -m regscan.article.run --days-back 14
    python -m regscan.article.run --save-signals          # 수집 후 시그널 저장
    python -m regscan.article.run --load-signals PATH     # 저장된 시그널로 기사 생성
    python -m regscan.article.run --no-cite               # 출처 후처리 스킵
    python -m regscan.article.run --no-render             # HTML 렌더 스킵
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_articles(
    days_back: int = 30,
    save_signals: bool = False,
    load_signals: str | None = None,
    no_cite: bool = False,
    no_render: bool = False,
) -> None:
    """보조 소스 전체 수집 → 시그널 추출 → 엔리칭 → 기사 생성 → 출처 → HTML."""
    from regscan.stream.intelligence_signals import extract_signals
    from regscan.article.pipeline import generate_articles
    from regscan.config import settings

    started = datetime.now()
    logger.info("=== 기사 전용 파이프라인 시작 (days_back=%d) ===", days_back)

    # ── 시그널 확보: 저장본 로드 또는 신규 수집 ──
    signal_dir = settings.BASE_DIR / "output" / "signals"
    signal_dir.mkdir(parents=True, exist_ok=True)

    if load_signals:
        # 저장된 시그널 로드 — 수집 스킵
        sig_path = Path(load_signals)
        if not sig_path.exists():
            logger.error("시그널 파일 없음: %s", sig_path)
            return
        signals = json.loads(sig_path.read_text(encoding="utf-8"))
        logger.info("=== 저장된 시그널 로드: %s ===", sig_path.name)
        for k, v in signals.items():
            logger.info("  %s: %d건", k, len(v))
    else:
        # 신규 수집
        from regscan.batch.pipeline import _run_ingestor

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
        if settings.ENABLE_GNW_PRESS:
            from regscan.ingest.globenewswire import GlobeNewsWireIngestor
            _aux_sources.append(
                (GlobeNewsWireIngestor, {"days_back": 7}, "GNW_PRESS"),
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

        # ── 시그널 저장 (--save-signals) ──
        if save_signals:
            date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            sig_path = signal_dir / f"signals_{date_str}.json"
            sig_path.write_text(
                json.dumps(signals, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("=== 시그널 저장: %s ===", sig_path)

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
            grade = art.get("grade", "A")
            grade_label = {"A": "분석", "B": "해설", "C": "카드"}.get(grade, grade)
            md += f"## {i}. {art.get('headline', '')} [{grade_label}]\n\n"
            if grade != "C":
                md += f"**{art.get('subheadline', '')}**\n\n"
            md += art.get("body", "") + "\n\n"
            if art.get("_guardrail_corrections"):
                md += f"> guardrail: {len(art['_guardrail_corrections'])} corrections\n\n"
            md += "---\n\n"

        # 자동 버전 넘버링: 기존 파일 중 가장 높은 버전 + 1
        existing = list(article_dir.glob(f"articles_{date_str}*.md"))
        max_ver = 0
        for f in existing:
            name = f.stem  # e.g. articles_2026-04-27-v5
            if "-v" in name:
                try:
                    v = int(name.split("-v")[-1])
                    max_ver = max(max_ver, v)
                except ValueError:
                    pass
            else:
                # articles_2026-04-27.md (버전 없음) → v1 취급
                max_ver = max(max_ver, 1)
        next_ver = max_ver + 1
        out_path = article_dir / f"articles_{date_str}-v{next_ver}.md"
        out_path.write_text(md, encoding="utf-8")
        logger.info("저장: %s (v%d)", out_path, next_ver)

        # ── 출처 후처리 (cite) ──
        if not no_cite and signals:
            from regscan.article.cite import add_citations
            cited_md = add_citations(md, signals)
            cited_path = article_dir / f"articles_{date_str}-v{next_ver}-cited.md"
            cited_path.write_text(cited_md, encoding="utf-8")
            logger.info("출처 추가: %s", cited_path)

            # render 대상은 cited 버전
            render_source = cited_md
            render_path_stem = cited_path
        else:
            render_source = md
            render_path_stem = out_path

        # ── HTML 렌더 ──
        if not no_render:
            from regscan.article.renderer import parse_articles_md, render_html
            data = parse_articles_md(render_source)
            html = render_html(data)
            html_path = render_path_stem.with_suffix(".html")
            html_path.write_text(html, encoding="utf-8")
            logger.info("HTML 생성: %s", html_path)

    duration = (datetime.now() - started).total_seconds()
    logger.info("=== 기사 전용 파이프라인 완료: %d건 (%.1f초) ===", len(articles), duration)


def main():
    parser = argparse.ArgumentParser(description="기사 전용 파이프라인")
    parser.add_argument("--days-back", type=int, default=30)
    parser.add_argument("--save-signals", action="store_true",
                        help="수집 후 시그널을 output/signals/에 JSON 저장")
    parser.add_argument("--load-signals", type=str, default=None,
                        help="저장된 시그널 JSON 경로 — 수집 스킵하고 기사만 생성")
    parser.add_argument("--no-cite", action="store_true",
                        help="출처 후처리 스킵")
    parser.add_argument("--no-render", action="store_true",
                        help="HTML 렌더 스킵")
    args = parser.parse_args()
    asyncio.run(run_articles(
        days_back=args.days_back,
        save_signals=args.save_signals,
        load_signals=args.load_signals,
        no_cite=args.no_cite,
        no_render=args.no_render,
    ))


if __name__ == "__main__":
    main()
