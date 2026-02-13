"""기사 발행 스크립트 — DB 상위 약물 LLM 브리핑 → HTML 기사 생성

사용법:
    python -m regscan.scripts.publish_articles                # 상위 20개 약물
    python -m regscan.scripts.publish_articles --top 50       # 상위 50개
    python -m regscan.scripts.publish_articles --min-score 60 # score>=60만
    python -m regscan.scripts.publish_articles --skip-llm     # LLM 건너뜀 (기존 JSON만 HTML 변환)
"""

import asyncio
import json
import logging
import re
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from regscan.config import settings

logger = logging.getLogger(__name__)

OUTPUT_DIR = settings.BASE_DIR / "output" / "briefings"
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_KR = datetime.now().strftime("%Y년 %m월 %d일")


# ── HTML 템플릿 ──

ARTICLE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan 브리핑 - {inn}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');
        body {{ font-family: 'Noto Serif KR', serif; background: #fafafa; }}
        .report-title {{ font-family: 'Noto Serif KR', serif; font-weight: 700; }}
        .report-body {{ font-family: 'Noto Serif KR', serif; line-height: 1.9; font-size: 17px; }}
        .meta-text {{ font-family: 'Inter', sans-serif; }}
        .highlight-box {{ border-left: 4px solid #dc2626; background: linear-gradient(90deg, #fef2f2 0%, #ffffff 100%); }}
        .timeline-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
    </style>
</head>
<body class="min-h-screen">
    <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div class="max-w-4xl mx-auto px-6 py-4">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <a href="index.html" class="text-xl font-bold text-gray-900 hover:text-indigo-600">MedClaim</a>
                    <span class="text-gray-300">|</span>
                    <span class="text-sm text-gray-500 meta-text">RegScan 브리핑</span>
                </div>
                <div class="meta-text text-sm text-gray-500">{date_kr}</div>
            </div>
        </div>
    </header>
    <main class="max-w-4xl mx-auto px-6 py-10">
        <div class="flex items-center space-x-3 mb-6 meta-text">
            <span class="px-3 py-1 {score_badge_class} text-white text-xs font-semibold rounded">{score_label}</span>
            {tag_badges}
        </div>
        <h1 class="report-title text-4xl text-gray-900 mb-4 leading-tight">{headline}</h1>
        <p class="text-xl text-gray-600 mb-8 leading-relaxed">{subtitle}</p>
        <div class="flex items-center space-x-4 mb-10 pb-10 border-b border-gray-200 meta-text">
            <div class="flex items-center space-x-2">
                <div class="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center">
                    <span class="text-indigo-600 text-xs font-bold">AI</span>
                </div>
                <span class="text-sm text-gray-600">RegScan AI 리포터</span>
            </div>
            <span class="text-gray-300">&middot;</span>
            <span class="text-sm text-gray-500">Hot Issue Score: {score}</span>
        </div>
        <div class="highlight-box p-6 rounded-r-lg mb-10">
            <h3 class="font-bold text-gray-900 mb-3 meta-text text-sm">핵심 요약</h3>
            <ul class="space-y-2 text-gray-800">{key_points_html}</ul>
        </div>
        <article class="report-body text-gray-800">
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">글로벌 승인 현황</h2>
            <p class="mb-6">{global_section}</p>
            {timeline_html}
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">국내 도입 전망</h2>
            <p class="mb-6">{domestic_section}</p>
            <div class="my-10 p-6 bg-indigo-50 rounded-xl border border-indigo-100">
                <h4 class="meta-text text-sm font-semibold text-indigo-600 mb-3">메드클레임 시사점</h4>
                <div class="space-y-3 text-gray-800"><p>{medclaim_section}</p></div>
            </div>
        </article>
        <footer class="mt-16 pt-8 border-t border-gray-200 meta-text text-sm text-gray-500">
            <div class="mb-4">
                <strong>데이터 출처:</strong> FDA Drug Approvals Database, EMA Public Assessment Reports,
                MFDS 의약품통합정보시스템, CRIS 임상연구정보서비스, HIRA 건강보험심사평가원
            </div>
            <div class="text-xs text-gray-400">
                본 리포트는 RegScan AI가 공개 데이터를 기반으로 자동 생성한 브리핑 자료입니다.
                의사결정에 활용 시 원문 확인을 권장합니다.
                마지막 업데이트: {date}
            </div>
        </footer>
    </main>
</body>
</html>"""


INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan - Hot Issue 브리핑</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');
        body {{ font-family: 'Noto Sans KR', sans-serif; background: #f8fafc; }}
        .line-clamp-2 {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    </style>
</head>
<body class="min-h-screen">
    <header class="bg-white border-b border-gray-200">
        <div class="max-w-6xl mx-auto px-6 py-6">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-bold text-gray-900">RegScan Hot Issue</h1>
                    <p class="text-sm text-gray-500 mt-1">글로벌 규제 동향 브리핑 리포트</p>
                </div>
                <div class="text-sm text-gray-500">{date_kr}</div>
            </div>
        </div>
    </header>
    <main class="max-w-6xl mx-auto px-6 py-10">
        <div class="mb-8">
            <h2 class="text-lg font-semibold text-gray-800">핫이슈 약물 ({count}건)</h2>
            <p class="text-sm text-gray-500">글로벌 규제 동향 + 국내 도입 전망 브리핑</p>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
{cards}
        </div>
    </main>
    <footer class="border-t border-gray-200 mt-16 py-8">
        <div class="max-w-6xl mx-auto px-6 text-center text-sm text-gray-400">
            RegScan AI - 글로벌 의약품 규제 인텔리전스
        </div>
    </footer>
</body>
</html>"""


INDEX_CARD_TEMPLATE = """            <a href="{filename}" class="block bg-white rounded-xl shadow-sm hover:shadow-md transition-shadow border border-gray-100 overflow-hidden">
                <div class="p-6">
                    <div class="flex items-center justify-between mb-3">
                        <span class="px-2 py-1 {badge_class} text-xs font-bold rounded">
                            Score {score}
                        </span>
                        <span class="text-xs text-gray-400">{status}</span>
                    </div>
                    <h3 class="font-bold text-lg text-gray-900 mb-2">{inn}</h3>
                    <p class="text-sm text-gray-600 line-clamp-2">{summary}</p>
                    <div class="mt-4 flex items-center text-xs text-gray-500">{flags}</div>
                </div>
            </a>"""


def _safe_filename(inn: str) -> str:
    return re.sub(r'[^\w\-]', '_', inn.lower())[:80]


def _score_badge(score: int) -> tuple[str, str, str]:
    """Returns (css_class, label, card_badge_class)"""
    if score >= 80:
        return "bg-red-600", "HOT", "bg-red-100 text-red-700"
    elif score >= 60:
        return "bg-orange-500", "HIGH", "bg-orange-100 text-orange-700"
    elif score >= 40:
        return "bg-yellow-500", "MEDIUM", "bg-yellow-100 text-yellow-700"
    else:
        return "bg-gray-400", "LOW", "bg-gray-100 text-gray-700"


def _build_timeline_html(source_data: dict | None) -> str:
    """승인 타임라인 HTML 생성"""
    if not source_data:
        return ""

    entries = []
    fda = source_data.get("fda", {})
    ema = source_data.get("ema", {})
    mfds = source_data.get("mfds", {})

    if fda.get("approved") and fda.get("date"):
        entries.append(("blue", fda["date"], "FDA 승인", "Approved"))
    if ema.get("approved") and ema.get("date"):
        entries.append(("yellow", ema["date"], "EMA 승인", "Authorised"))
    if mfds.get("approved") and mfds.get("date"):
        brand = mfds.get("brand_name", "")
        entries.append(("green", mfds["date"], "MFDS 허가", brand or "Approved"))

    if not entries:
        return ""

    items_html = ""
    for color, date, label, desc in entries:
        items_html += f"""
                    <div class="relative flex items-center mb-6">
                        <div class="timeline-dot bg-{color}-500 z-10"></div>
                        <div class="ml-6">
                            <div class="meta-text text-xs text-{color}-600 font-semibold">{date}</div>
                            <div class="font-medium">{label}</div>
                            <div class="text-sm text-gray-500">{desc}</div>
                        </div>
                    </div>"""

    return f"""
            <div class="my-10 p-6 bg-gray-50 rounded-xl">
                <h4 class="meta-text text-sm font-semibold text-gray-500 mb-6">승인 타임라인</h4>
                <div class="relative">
                    <div class="absolute left-2 top-0 bottom-0 w-0.5 bg-gray-300"></div>{items_html}
                </div>
            </div>"""


def _build_flags_html(source_data: dict | None) -> str:
    if not source_data:
        return ""
    parts = []
    if source_data.get("fda", {}).get("approved"):
        parts.append('<span>FDA</span>')
    if source_data.get("ema", {}).get("approved"):
        parts.append('<span class="mx-2">EMA</span>')
    if source_data.get("mfds", {}).get("approved"):
        parts.append('<span>MFDS</span>')
    return " ".join(parts)


def _build_tag_badges(source_data: dict | None) -> str:
    if not source_data:
        return ""
    tags = []
    reasons = source_data.get("analysis", {}).get("hot_issue_reasons", [])
    for r in reasons[:3]:
        if "희귀" in r or "Orphan" in r:
            tags.append("희귀의약품")
        elif "Breakthrough" in r:
            tags.append("혁신치료제")
        elif "PRIME" in r:
            tags.append("EMA PRIME")
        elif "Fast Track" in r:
            tags.append("신속심사")
    seen = set()
    html = ""
    for t in tags:
        if t not in seen:
            seen.add(t)
            html += f'<span class="px-3 py-1 bg-gray-100 text-gray-600 text-xs rounded">{t}</span>\n'
    return html


def generate_article_html(report_data: dict, score: int = 0) -> str:
    """BriefingReport JSON → HTML 기사"""
    inn = report_data.get("inn", "")
    headline = report_data.get("headline", f"{inn} 규제 동향 브리핑")
    subtitle = report_data.get("subtitle", "")
    key_points = report_data.get("key_points", [])
    global_section = report_data.get("global_section", "")
    domestic_section = report_data.get("domestic_section", "")
    medclaim_section = report_data.get("medclaim_section", "")
    source_data = report_data.get("source_data")

    badge_class, score_label, _ = _score_badge(score)

    key_points_html = ""
    for kp in key_points:
        key_points_html += f"""
                <li class="flex items-start">
                    <span class="text-red-500 mr-2">&#x25B8;</span>
                    <span>{kp}</span>
                </li>"""

    timeline_html = _build_timeline_html(source_data)
    tag_badges = _build_tag_badges(source_data)

    return ARTICLE_HTML_TEMPLATE.format(
        inn=inn,
        date_kr=TODAY_KR,
        date=TODAY,
        score_badge_class=badge_class,
        score_label=score_label,
        score=score,
        tag_badges=tag_badges,
        headline=headline,
        subtitle=subtitle,
        key_points_html=key_points_html,
        global_section=global_section,
        domestic_section=domestic_section,
        medclaim_section=medclaim_section,
        timeline_html=timeline_html,
    )


def generate_index_html(articles: list[dict]) -> str:
    """인덱스 페이지 HTML 생성"""
    cards = ""
    for art in articles:
        inn = art["inn"]
        score = art.get("score", 0)
        _, _, card_badge = _score_badge(score)
        filename = _safe_filename(inn) + ".html"
        headline = art.get("headline", "")
        status = art.get("status_label", "")
        flags = _build_flags_html(art.get("source_data"))

        # 요약: headline에서 따옴표 안 부분 추출 or 첫 key_point
        summary = ""
        kps = art.get("key_points", [])
        if kps:
            summary = kps[0][:80] + "..."
        elif headline:
            summary = headline[:80]

        cards += INDEX_CARD_TEMPLATE.format(
            filename=filename,
            badge_class=card_badge,
            score=score,
            status=status,
            inn=inn,
            summary=summary,
            flags=flags,
        ) + "\n"

    return INDEX_HTML_TEMPLATE.format(
        date_kr=TODAY_KR,
        count=len(articles),
        cards=cards,
    )


async def _fetch_ema_indication_index() -> dict[str, dict]:
    """EMA API에서 약물별 적응증·therapeutic_area 조회 (1회 호출, INN→정보 인덱스)"""
    from regscan.ingest.ema import EMAClient
    from regscan.map.matcher import IngredientMatcher

    matcher = IngredientMatcher()
    index: dict[str, dict] = {}

    try:
        async with EMAClient() as client:
            medicines = await client.fetch_medicines()
    except Exception as e:
        logger.warning("EMA API 조회 실패 — 적응증 보강 건너뜀: %s", e)
        return index

    for med in medicines:
        inn = (med.get("activeSubstance", "") or
               med.get("inn", "") or
               med.get("active_substance", "") or
               med.get("international_non_proprietary_name_common_name", "") or "")
        if not inn:
            continue

        norm = matcher.normalize(inn)
        indication = (med.get("therapeuticIndication", "") or
                      med.get("therapeutic_indication", "") or "")
        ta = (med.get("therapeuticArea", "") or
              med.get("therapeutic_area", "") or "")
        ptg = (med.get("pharmacotherapeuticGroup", "") or
               med.get("pharmacotherapeutic_group_human", "") or "")

        entry = {
            "indication": indication,
            "therapeutic_area": ta,
            "pharmacotherapeutic_group": ptg,
        }
        if norm not in index or len(indication) > len(index[norm].get("indication", "")):
            index[norm] = entry
        # FDA 접미사 대응: base INN도 등록 (e.g. zanidatamab-hrii → zanidatamab)
        if '-' in norm:
            base = norm.rsplit('-', 1)[0]
            if base not in index or len(indication) > len(index[base].get("indication", "")):
                index[base] = entry

    logger.info("EMA 적응증 인덱스 구축: %d건", len(index))
    return index


async def load_drugs_from_db(
    top_n: int = 20,
    min_score: int = 40,
):
    """DB에서 상위 약물 → DomesticImpact 리스트 (경쟁약·적응증 포함)"""
    from regscan.db.database import init_db, get_async_session
    from regscan.db.models import DrugDB, RegulatoryEventDB
    from regscan.scan.domestic import DomesticImpactAnalyzer
    from regscan.map.global_status import (
        GlobalRegulatoryStatus, RegulatoryApproval, ApprovalStatus,
    )
    from regscan.map.matcher import IngredientMatcher
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    await init_db()
    matcher = IngredientMatcher()

    # EMA API에서 적응증 인덱스 구축
    ema_index = await _fetch_ema_indication_index()

    async with get_async_session()() as session:
        # ── 1) 대상 약물 로드 ──
        stmt = (
            select(DrugDB)
            .options(selectinload(DrugDB.events))
            .where(DrugDB.global_score >= min_score)
            .order_by(DrugDB.global_score.desc())
            .limit(top_n)
        )
        result = await session.execute(stmt)
        drugs = result.scalars().all()

        if not drugs:
            logger.error("DB에 score >= %d 약물 없음", min_score)
            return []

        # ── 2) 경쟁약 조회용: 전체 약물의 therapeutic_area → INN 인덱스 ──
        all_stmt = (
            select(DrugDB.inn, DrugDB.global_score, DrugDB.therapeutic_areas,
                   DrugDB.domestic_status)
            .where(DrugDB.global_score >= 20)
            .order_by(DrugDB.global_score.desc())
        )
        all_result = await session.execute(all_stmt)
        all_rows = all_result.all()

        # area → [(inn, score, domestic_status)] 매핑
        area_index: dict[str, list[dict]] = {}
        for row in all_rows:
            areas = row.therapeutic_areas.split(",") if row.therapeutic_areas else []
            for area in areas:
                area = area.strip()
                if not area:
                    continue
                area_index.setdefault(area, []).append({
                    "inn": row.inn,
                    "score": row.global_score,
                    "domestic_status": row.domestic_status or "",
                })

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

            # ── 3) 이벤트 → RegulatoryApproval + 적응증 추출 ──
            indication_parts = []
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
                    # EMA raw_data에서 적응증 추출
                    if ev.raw_data and isinstance(ev.raw_data, dict):
                        ti = ev.raw_data.get("therapeutic_indication", "")
                        if ti:
                            indication_parts.append(ti[:300])
                elif ev.agency == "mfds":
                    status.mfds = approval
                    # MFDS raw_data에서 적응증 추출
                    if ev.raw_data and isinstance(ev.raw_data, dict):
                        ind = ev.raw_data.get("indication", "")
                        if ind:
                            indication_parts.append(ind[:300])

            impact = analyzer.analyze(status)

            # ── 4) 적응증 텍스트 주입 (EMA API 우선, DB raw_data 폴백) ──
            norm_inn = matcher.normalize(drug.inn)
            ema_info = ema_index.get(norm_inn, {})
            # FDA 생물학적 제제 접미사 폴백 (e.g. zanidatamab-hrii → zanidatamab)
            if not ema_info and '-' in norm_inn:
                base_inn = norm_inn.rsplit('-', 1)[0]
                ema_info = ema_index.get(base_inn, {})
            ema_indication = ema_info.get("indication", "")
            ema_ta = ema_info.get("therapeutic_area", "")
            ema_ptg = ema_info.get("pharmacotherapeutic_group", "")

            if ema_indication:
                indication_text = ema_indication[:500]
            elif indication_parts:
                indication_text = " | ".join(indication_parts)
            else:
                indication_text = ""
            impact._indication_text = indication_text

            # pharmacotherapeutic_group도 전달 (기전 정보)
            if ema_ptg:
                impact._pharmacotherapeutic_group = ema_ptg

            # ── 5) 경쟁약 주입 ──
            # EMA therapeutic_area가 있으면 이를 우선 사용 (더 구체적)
            # 없으면 DB therapeutic_areas 사용
            competitors = []
            seen = {drug.inn}

            # 5-a) EMA therapeutic_area 기반 (같은 EMA 분류 약물)
            if ema_ta:
                for other_inn, other_info in ema_index.items():
                    if other_info.get("therapeutic_area", "") == ema_ta:
                        # DB에서 해당 약물 score 조회
                        for area_list in area_index.values():
                            for comp in area_list:
                                if matcher.normalize(comp["inn"]) == other_inn:
                                    if comp["inn"] not in seen:
                                        seen.add(comp["inn"])
                                        comp_with_indication = dict(comp)
                                        comp_indication = other_info.get("indication", "")
                                        if comp_indication:
                                            comp_with_indication["indication"] = comp_indication[:150]
                                        competitors.append(comp_with_indication)

            # 5-b) DB therapeutic_area 폴백
            if len(competitors) < 3:
                for area in status.therapeutic_areas:
                    area = area.strip()
                    for comp in area_index.get(area, []):
                        if comp["inn"] in seen:
                            continue
                        seen.add(comp["inn"])
                        competitors.append(comp)

            # score 내림차순 정렬 후 상위 5개
            competitors.sort(key=lambda x: x["score"], reverse=True)
            impact._competitors = competitors[:5]

            impacts.append(impact)

    return impacts


async def run_publish(
    top_n: int = 20,
    min_score: int = 40,
    skip_llm: bool = False,
):
    """기사 발행 메인 로직"""
    from regscan.report.llm_generator import LLMBriefingGenerator, BriefingReport
    from regscan.db.loader import DBLoader

    logger.info("=== 기사 발행 시작 ===")
    logger.info("  대상: score >= %d, 최대 %d건", min_score, top_n)

    impacts = await load_drugs_from_db(top_n=top_n, min_score=min_score)
    if not impacts:
        logger.error("발행 대상 약물 없음")
        return

    logger.info("  DB 로드: %d건", len(impacts))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generator = LLMBriefingGenerator(provider="openai", model="gpt-4o-mini")
    loader = DBLoader()
    articles_meta = []
    generated = 0
    failed = 0
    skipped = 0

    for i, impact in enumerate(impacts, 1):
        safe_name = _safe_filename(impact.inn)
        json_path = OUTPUT_DIR / f"{safe_name}.json"
        html_path = OUTPUT_DIR / f"{safe_name}.html"

        # LLM 브리핑 생성
        if skip_llm and json_path.exists():
            # 기존 JSON 로드
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                report = BriefingReport(
                    inn=data["inn"],
                    headline=data["headline"],
                    subtitle=data.get("subtitle", ""),
                    key_points=data.get("key_points", []),
                    global_section=data.get("global_section", ""),
                    domestic_section=data.get("domestic_section", ""),
                    medclaim_section=data.get("medclaim_section", ""),
                    source_data=data.get("source_data"),
                )
                logger.info("  [%d/%d] %s — 기존 JSON 로드", i, len(impacts), impact.inn)
                skipped += 1
            except Exception as e:
                logger.warning("  [%d/%d] %s — JSON 로드 실패: %s", i, len(impacts), impact.inn, e)
                failed += 1
                continue
        else:
            try:
                logger.info("  [%d/%d] %s (score=%d) — LLM 브리핑 생성 중...",
                           i, len(impacts), impact.inn, impact.global_score)
                report = await generator.generate(impact)
                # JSON 저장
                report.save(OUTPUT_DIR)
                # DB 저장
                try:
                    await loader.save_briefing(report)
                except Exception as e:
                    logger.debug("  DB 저장 건너뜀: %s", e)
                generated += 1
            except Exception as e:
                logger.warning("  [%d/%d] %s — 브리핑 생성 실패: %s", i, len(impacts), impact.inn, e)
                failed += 1
                continue

        # HTML 기사 생성
        report_data = report.to_dict()
        report_data["source_data"] = report.source_data
        html_content = generate_article_html(report_data, score=impact.global_score)
        html_path.write_text(html_content, encoding="utf-8")

        # 인덱스용 메타
        status_label = ""
        if impact.mfds_approved and impact.hira_status:
            status_label = impact.hira_status.value
        elif impact.mfds_approved:
            status_label = "approved_not_reimbursed"
        elif impact.fda_approved or impact.ema_approved:
            status_label = "expected"
        else:
            status_label = "monitoring"

        articles_meta.append({
            "inn": impact.inn,
            "score": impact.global_score,
            "headline": report.headline,
            "key_points": report.key_points,
            "status_label": status_label,
            "source_data": report.source_data,
            "html_file": str(html_path.name),
        })

    # 인덱스 페이지 생성
    articles_meta.sort(key=lambda x: x["score"], reverse=True)
    index_html = generate_index_html(articles_meta)
    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    # hot_issues JSON 저장
    hot_path = OUTPUT_DIR / f"hot_issues_{TODAY}.json"
    hot_path.write_text(
        json.dumps(articles_meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # hot_issues Markdown
    md_lines = [
        f"# RegScan Hot Issue 브리핑 ({TODAY})",
        f"",
        f"총 {len(articles_meta)}건의 핫이슈 약물 브리핑",
        f"",
    ]
    for art in articles_meta:
        md_lines.append(f"## [{art['score']}점] {art['inn']}")
        md_lines.append(f"**{art['headline']}**")
        if art.get("key_points"):
            for kp in art["key_points"][:3]:
                md_lines.append(f"- {kp}")
        md_lines.append("")

    md_path = OUTPUT_DIR / f"hot_issues_{TODAY}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # 결과 요약
    logger.info("\n=== 기사 발행 완료 ===")
    logger.info("  LLM 생성: %d건", generated)
    logger.info("  기존 로드: %d건", skipped)
    logger.info("  실패: %d건", failed)
    logger.info("  HTML 기사: %s/*.html (%d건)", OUTPUT_DIR, len(articles_meta))
    logger.info("  인덱스: %s", index_path)
    logger.info("  핫이슈: %s", hot_path)

    print(f"\n{'='*60}")
    print(f"  RegScan 기사 발행 완료")
    print(f"{'='*60}")
    print(f"  LLM 생성: {generated}건 | 기존: {skipped}건 | 실패: {failed}건")
    print(f"  HTML 기사: {len(articles_meta)}건")
    print(f"  인덱스: {index_path}")
    print(f"\n  상위 5건:")
    for art in articles_meta[:5]:
        print(f"    [{art['score']}] {art['inn']}")
        headline = art['headline'][:60].encode('ascii', 'replace').decode('ascii')
        print(f"         {headline}")
    print(f"{'='*60}")


def main():
    parser = ArgumentParser(description="RegScan 기사 발행")
    parser.add_argument("--top", type=int, default=20, help="상위 N개 약물 (기본 20)")
    parser.add_argument("--min-score", type=int, default=40, help="최소 점수 (기본 40)")
    parser.add_argument("--skip-llm", action="store_true", help="LLM 건너뜀 (기존 JSON만 HTML 변환)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asyncio.run(run_publish(top_n=args.top, min_score=args.min_score, skip_llm=args.skip_llm))


if __name__ == "__main__":
    main()
