"""A/B 비교 테스트 — 동일 시그널로 v2(기존) vs v3(2-Pass) 비교

Usage:
    python -m regscan.article.ab_test --signals output/signals/signals_XXXX.json
    python -m regscan.article.ab_test --signals output/signals/signals_XXXX.json --v3-only
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


def _render_md(articles: list[dict], variant: str) -> str:
    """기사 리스트 → MD 렌더링"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    md = f"# RegScan A/B Test — {variant}\n\n> {date_str}\n\n"
    for i, art in enumerate(articles, 1):
        grade = art.get("grade", "A")
        grade_label = {"A": "분석", "B": "해설", "C": "카드"}.get(grade, grade)
        md += f"## {i}. {art.get('headline', '')} [{grade_label}]\n\n"
        if grade != "C":
            md += f"**{art.get('subheadline', '')}**\n\n"
        md += art.get("body", "") + "\n\n"

        # slot_results (v3 only)
        slot_results = art.get("slot_results", {})
        if slot_results:
            md += "| 슬롯 | 결과 |\n|------|------|\n"
            for slot, result in slot_results.items():
                md += f"| {slot} | {result} |\n"
            md += "\n"

        if art.get("_guardrail_corrections"):
            md += f"> guardrail: {len(art['_guardrail_corrections'])} corrections\n\n"
        md += "---\n\n"
    return md


def _score_article(article: dict) -> dict:
    """기사 품질 정량 점수 (비교용)"""
    body = article.get("body", "")
    grade = article.get("grade", "A")

    scores = {}
    scores["body_length"] = len(body)
    scores["grade"] = grade

    # 국내 관점
    domestic_kw = ["국내", "허가", "급여", "심평원", "식약처", "건보", "병원", "약가", "상한가"]
    scores["domestic_keywords"] = sum(1 for kw in domestic_kw if kw in body)

    # 수치 밀도
    import re
    numbers = re.findall(r'\d+[\.,]?\d*', body)
    scores["number_count"] = len(numbers)

    # 비교 표현
    comparison_kw = ["대비", "기존", "달라", "차이", "비교", "vs", "→", "이전"]
    scores["comparison_keywords"] = sum(1 for kw in comparison_kw if kw in body)

    # 구체적 전망 (추상 마무리 감지)
    vague = ["전망이다", "가능성이 있다", "기조를 이어", "주목된다"]
    scores["vague_endings"] = sum(1 for v in vague if body.endswith(v) or body.endswith(v + "."))

    # 문장 완결성 (미완성 문장)
    sentences = [s.strip() for s in body.split(".") if s.strip()]
    incomplete = sum(1 for s in sentences if len(s) < 5)
    scores["incomplete_sentences"] = incomplete

    # slot results (v3)
    slot_results = article.get("slot_results", {})
    if slot_results:
        scores["slots_pass"] = sum(1 for v in slot_results.values() if v == "PASS")
        scores["slots_inserted"] = sum(1 for v in slot_results.values() if "INSERTED" in str(v))
        scores["slots_not_found"] = sum(1 for v in slot_results.values() if "NOT_FOUND" in str(v))

    return scores


async def run_ab_test(signals_path: str, v3_only: bool = False) -> None:
    """A/B 비교 실행"""
    from regscan.config import settings

    sig_path = Path(signals_path)
    if not sig_path.exists():
        logger.error("시그널 파일 없음: %s", sig_path)
        return

    signals = json.loads(sig_path.read_text(encoding="utf-8"))
    logger.info("시그널 로드: %s (%d 소스)", sig_path.name, len(signals))

    out_dir = settings.BASE_DIR / "output" / "ab_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # ── v3 (2-Pass) ──
    logger.info("=== v3 (2-Pass) 실행 ===")
    from regscan.article.pipeline import generate_articles as generate_v3
    articles_v3 = await generate_v3(signals)

    v3_md = _render_md(articles_v3, "v3 (2-Pass)")
    v3_path = out_dir / f"v3_2pass_{timestamp}.md"
    v3_path.write_text(v3_md, encoding="utf-8")
    logger.info("v3 저장: %s (%d건)", v3_path.name, len(articles_v3))

    # ── 점수 비교 ──
    report = f"# A/B Test Report — {timestamp}\n\n"
    report += f"시그널: `{sig_path.name}`\n\n"

    report += "## v3 (2-Pass) 결과\n\n"
    report += "| # | 제목 | 등급 | 길이 | 국내KW | 수치 | 비교KW | 슬롯PASS | 슬롯삽입 |\n"
    report += "|---|------|------|------|--------|------|--------|----------|----------|\n"
    for i, art in enumerate(articles_v3, 1):
        s = _score_article(art)
        report += (
            f"| {i} | {art.get('headline', '')[:25]} | {s['grade']} | {s['body_length']} "
            f"| {s['domestic_keywords']} | {s['number_count']} | {s['comparison_keywords']} "
            f"| {s.get('slots_pass', '-')} | {s.get('slots_inserted', '-')} |\n"
        )

    report += "\n## 기존 출력과 비교\n\n"
    report += "기존 기사(`output/articles/`)와 수동 비교하세요.\n\n"
    report += "### 체크리스트\n\n"
    report += "- [ ] 국내 관점: 구체적 약물명+허가/급여 상태가 있는가?\n"
    report += "- [ ] 비교 블록: A vs B 수치 비교가 있는가?\n"
    report += "- [ ] 관찰 포인트: 구체적 일정/이벤트로 끝나는가?\n"
    report += "- [ ] 문장 완결성: 잘린 문장, 깨진 숫자 없는가?\n"
    report += "- [ ] structural_info: 편집장이 지정한 핵심 정보가 살아있는가?\n"

    report_path = out_dir / f"ab_report_{timestamp}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("리포트 저장: %s", report_path)


def main():
    parser = argparse.ArgumentParser(description="A/B 비교 테스트")
    parser.add_argument("--signals", required=True, help="저장된 시그널 JSON 경로")
    parser.add_argument("--v3-only", action="store_true", help="v3만 실행 (v2 스킵)")
    args = parser.parse_args()
    asyncio.run(run_ab_test(args.signals, v3_only=args.v3_only))


if __name__ == "__main__":
    main()
