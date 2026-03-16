"""V4.1 모델 비교 테스트 — 동일 약물에 대해 여러 LLM 모델의 브리핑 품질 비교

Usage:
    python scripts/compare_v41_models.py --provider openai --model gpt-5.2
    python scripts/compare_v41_models.py --provider gemini --model gemini-2.5-flash
    python scripts/compare_v41_models.py --provider gemini --model gemini-3-flash-preview
"""

import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regscan.config import settings
from regscan.report.llm_generator import LLMBriefingGenerator
from regscan.scan.domestic import DomesticImpact

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def build_polatuzumab_impact() -> DomesticImpact:
    """POLATUZUMAB VEDOTIN의 DomesticImpact를 DB 데이터 기반으로 구성."""
    from regscan.map.ingredient_bridge import ReimbursementStatus

    impact = DomesticImpact.__new__(DomesticImpact)
    impact.inn = "polatuzumab vedotin"
    impact.fda_approved = True
    impact.fda_date = date(2019, 6, 10)
    impact.ema_approved = True
    impact.ema_date = date(2020, 1, 16)
    impact.mfds_approved = False
    impact.mfds_date = None
    impact.mfds_brand_name = ""
    impact.hira_status = ReimbursementStatus.NOT_COVERED
    impact.hira_price = None
    impact.hira_criteria = ""
    impact.hira_code = "691801BIJ"
    impact.cris_trials = []
    impact.domestic_status = ReimbursementStatus.NOT_COVERED
    impact.global_score = 70
    impact.korea_relevance_score = 25
    impact.korea_relevance_reasons = ["FDA 승인", "EMA 승인", "EMA PRIME"]
    # quadrant is a computed property (global_score=70, korea_relevance_score=25 → "watch")
    impact.hot_issue_reasons = [
        "FDA 승인", "EMA 승인", "EMA PRIME",
        "FDA+EMA 근접 승인", "희귀의약품", "주요 질환 치료제",
    ]
    impact.analysis_notes = ["글로벌 승인 후 6년 경과, 국내 미허가"]
    impact.therapeutic_areas = ["oncology"]
    impact.stream_sources = ["therapeutic_area", "innovation"]
    impact.has_active_trial = False
    impact.clinical_results = None
    impact.clinical_results_nct_id = None

    # V4 enrichment
    impact._copay_exemption = {"label": "암환자 산정특례", "rate": 0.05}
    impact._competitors = [
        {"inn": "GLOFITAMAB", "domestic_status": "expected", "mechanism_class": "CD20×CD3 bispecific"},
        {"inn": "LONCASTUXIMAB TESIRINE", "domestic_status": "expected", "mechanism_class": "CD19 ADC"},
    ]
    impact._indication_text = "Treatment of relapsed or refractory diffuse large B-cell lymphoma"
    impact._pharmacotherapeutic_group = "Antineoplastic agents, monoclonal antibodies / CD79b-targeting ADC delivering MMAE"
    impact._limitations_text = (
        "POLARIX 시험에서 OS 차이는 통계적 유의성에 도달하지 못함 "
        "(HR 0.94, 95% CI 0.69–1.28). CR률도 양 군 58%로 동일."
    )
    impact._news_cache = None

    # days_since_global_approval and summary are computed properties — no manual assignment needed

    def _to_dict():
        return {
            "inn": impact.inn,
            "fda_approved": impact.fda_approved,
            "ema_approved": impact.ema_approved,
            "mfds_approved": impact.mfds_approved,
            "domestic_status": "expected",
            "global_score": impact.global_score,
            "therapeutic_areas": impact.therapeutic_areas,
        }
    impact.to_dict = _to_dict

    return impact


async def run_single_model(provider: str, model: str, impact: DomesticImpact) -> dict:
    """단일 모델로 V4.1 브리핑 생성 + 시간 측정."""
    logger.info("━━━ %s / %s 시작 ━━━", provider, model)
    gen = LLMBriefingGenerator(provider=provider, model=model)

    start = time.time()
    try:
        report = await gen.generate_v4(impact)
        elapsed = time.time() - start
        result = {
            "ok": True,
            "provider": provider,
            "model": model,
            "elapsed": round(elapsed, 1),
            "headline": report.headline,
            "subtitle": report.subtitle,
            "key_points": report.key_points,
            "global_section": report.global_section,
            "domestic_section": report.domestic_section,
            "medclaim_section": report.medclaim_section,
            "generated_at": report.generated_at.isoformat(),
        }
        logger.info("✓ %s / %s 완료 (%.1fs)", provider, model, elapsed)
        return result
    except Exception as e:
        elapsed = time.time() - start
        logger.error("✗ %s / %s 실패 (%.1fs): %s", provider, model, elapsed, e)
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "elapsed": round(elapsed, 1),
            "error": str(e),
        }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    impact = build_polatuzumab_impact()
    result = await run_single_model(args.provider, args.model, impact)

    # 결과 저장
    out_dir = Path("output/model_comparison")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_model = args.model.replace("/", "_").replace(".", "_")
    out_path = out_dir / f"v41_{safe_model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("결과 저장: %s", out_path)


if __name__ == "__main__":
    asyncio.run(main())
