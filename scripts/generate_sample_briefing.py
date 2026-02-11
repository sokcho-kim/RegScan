"""DB에서 고점수 약물을 동적 조회 → AI 브리핑 기사 생성 → HTML 파일 저장"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from regscan.db.database import get_sync_engine
from regscan.ai.pipeline import AIIntelligencePipeline
from regscan.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

settings.ENABLE_AI_REASONING = True
settings.ENABLE_AI_VERIFIER = True
settings.ENABLE_AI_WRITER = True


def get_qualified_drug_ids(min_score: int) -> list[int]:
    """global_score >= min_score인 약물 ID 목록을 조회한다."""
    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, inn, global_score FROM drugs "
                "WHERE global_score >= :min_score "
                "ORDER BY global_score DESC"
            ),
            {"min_score": min_score},
        ).mappings().fetchall()
    logger.info(
        "global_score >= %d 인 약물: %d건", min_score, len(rows),
    )
    for r in rows:
        logger.info("  #%d %s (score=%s)", r["id"], r["inn"], r["global_score"])
    return [r["id"] for r in rows]


def load_drug(drug_id):
    engine = get_sync_engine()
    with engine.connect() as conn:
        d = conn.execute(
            text("SELECT * FROM drugs WHERE id = :id"), {"id": drug_id}
        ).mappings().fetchone()
        drug = {
            "inn": d["inn"],
            "global_score": d["global_score"] or 0,
            "hot_issue_level": d["hot_issue_level"],
            "domestic_status": d["domestic_status"],
            "fda_approved": False, "fda_date": None,
            "ema_approved": False, "ema_date": None,
            "mfds_approved": False, "mfds_date": None,
            "hira_status": None, "hira_price": None,
        }
        evts = conn.execute(
            text("SELECT agency, status, approval_date, brand_name "
                 "FROM regulatory_events WHERE drug_id = :id"),
            {"id": drug_id},
        ).mappings().fetchall()
        for e in evts:
            ag = e["agency"]
            drug[f"{ag}_approved"] = e["status"] == "approved"
            drug[f"{ag}_date"] = str(e["approval_date"]) if e["approval_date"] else None
            if e["brand_name"]:
                drug[f"{ag}_brand"] = e["brand_name"]
        hira = conn.execute(
            text("SELECT status, price_ceiling FROM hira_reimbursements WHERE drug_id = :id"),
            {"id": drug_id},
        ).mappings().fetchall()
        for h in hira:
            drug["hira_status"] = h["status"]
            drug["hira_price"] = h["price_ceiling"]
    return drug


def build_article_card(drug, insight, art):
    score = insight.get("verified_score") or insight.get("impact_score", 0)
    confidence = insight.get("confidence_level", "-")
    corrections = len(insight.get("corrections", []))

    # 배지
    badges = ""
    for ag in ["fda", "ema", "mfds"]:
        ok = drug.get(f"{ag}_approved")
        color = "#22c55e" if ok else "#94a3b8"
        badges += (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
            f'background:{color};color:#fff;font-size:12px;margin-right:4px;">'
            f'{ag.upper()}</span>'
        )
    hc = "#3b82f6" if drug.get("hira_status") == "reimbursed" else "#f59e0b"
    hl = drug.get("hira_status", "N/A")
    badges += (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
        f'background:{hc};color:#fff;font-size:12px;">HIRA: {hl}</span>'
    )

    # 점수 색상
    if score >= 70:
        sc = "#ef4444"
    elif score >= 40:
        sc = "#f59e0b"
    else:
        sc = "#22c55e"

    risks = "".join(f"<li>{r}</li>" for r in insight.get("risk_factors", [])[:3])
    opps = "".join(f"<li>{o}</li>" for o in insight.get("opportunity_factors", [])[:3])
    tags = "".join(
        f'<span style="display:inline-block;padding:3px 10px;margin:2px 4px 2px 0;'
        f'border-radius:16px;background:#eff6ff;color:#3b82f6;font-size:12px;">'
        f'#{t}</span>'
        for t in art.get("tags", [])
    )

    reasoning_tokens = insight.get("reasoning_tokens", 0)
    verifier_tokens = insight.get("verifier_tokens", 0)
    writer_tokens = art.get("writer_tokens", 0)
    total_tokens = reasoning_tokens + verifier_tokens + writer_tokens

    return f"""
    <article style="background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);margin-bottom:32px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#1e293b,#334155);padding:24px 28px;color:#fff;">
        <div style="margin-bottom:8px;">{badges}</div>
        <h2 style="margin:8px 0 4px;font-size:22px;font-weight:700;border:none;padding:0;color:#fff;">{art.get("headline","")}</h2>
        <p style="margin:0;opacity:0.85;font-size:14px;">{art.get("subtitle","")}</p>
      </div>

      <div style="display:flex;align-items:center;padding:16px 28px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">
        <div style="text-align:center;margin-right:24px;">
          <div style="font-size:36px;font-weight:800;color:{sc};">{score}</div>
          <div style="font-size:11px;color:#64748b;">AI Score</div>
        </div>
        <div style="flex:1;">
          <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;">
            <div style="background:{sc};height:100%;width:{score}%;border-radius:4px;"></div>
          </div>
        </div>
        <div style="text-align:center;margin-left:24px;">
          <div style="font-size:14px;font-weight:600;color:#475569;">{confidence}</div>
          <div style="font-size:11px;color:#64748b;">Confidence</div>
        </div>
        <div style="text-align:center;margin-left:24px;">
          <div style="font-size:14px;font-weight:600;color:#475569;">{corrections}건</div>
          <div style="font-size:11px;color:#64748b;">Corrections</div>
        </div>
        <div style="text-align:center;margin-left:24px;">
          <div style="font-size:14px;font-weight:600;color:#475569;">{total_tokens:,}</div>
          <div style="font-size:11px;color:#64748b;">Tokens</div>
        </div>
      </div>

      <div style="padding:20px 28px;border-bottom:1px solid #f1f5f9;">
        <p style="margin:0;font-size:15px;line-height:1.7;color:#334155;">{art.get("lead_paragraph","")}</p>
      </div>

      <div style="display:flex;padding:16px 28px;gap:24px;border-bottom:1px solid #f1f5f9;">
        <div style="flex:1;">
          <h4 style="margin:0 0 8px;color:#ef4444;font-size:13px;">Risk Factors</h4>
          <ul style="margin:0;padding-left:18px;font-size:13px;color:#475569;line-height:1.6;">{risks}</ul>
        </div>
        <div style="flex:1;">
          <h4 style="margin:0 0 8px;color:#22c55e;font-size:13px;">Opportunities</h4>
          <ul style="margin:0;padding-left:18px;font-size:13px;color:#475569;line-height:1.6;">{opps}</ul>
        </div>
      </div>

      <div class="article-body" style="padding:20px 28px;font-size:14px;line-height:1.8;color:#334155;">
        {art.get("body_html","")}
      </div>

      <div style="padding:12px 28px 20px;border-top:1px solid #f1f5f9;">
        {tags}
      </div>
    </article>
    """


def build_html(cards_html):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RegScan v2 AI Briefing</title>
<style>
  body {{
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f1f5f9; margin: 0; padding: 0;
  }}
  .article-body h2 {{
    font-size: 17px; color: #1e293b; margin: 24px 0 8px;
    border-bottom: 2px solid #3b82f6; padding-bottom: 4px;
  }}
  .article-body p {{ margin: 8px 0; }}
  .article-body strong {{ color: #1e293b; }}
</style>
</head>
<body>
<div style="max-width:800px;margin:0 auto;padding:24px 16px;">
  <div style="text-align:center;margin-bottom:32px;">
    <h1 style="font-size:28px;color:#1e293b;margin:0;">RegScan v2 AI Briefing</h1>
    <p style="color:#64748b;font-size:14px;margin:8px 0 0;">
      3-Stage AI Pipeline: o4-mini Reasoning + GPT-5.2 Verification + GPT-5.2 Writing
    </p>
    <p style="color:#94a3b8;font-size:12px;margin:4px 0 0;">Generated: {now}</p>
  </div>

  {cards_html}

  <div style="text-align:center;padding:24px;color:#94a3b8;font-size:12px;">
    <p>Powered by RegScan v2.0 AI Intelligence Pipeline</p>
  </div>
</div>
</body>
</html>"""


async def main(min_score: int):
    drug_ids = get_qualified_drug_ids(min_score)
    if not drug_ids:
        logger.warning("대상 약물 없음 (min_score=%d)", min_score)
        return

    cards = []
    for drug_id in drug_ids:
        drug = load_drug(drug_id)
        logger.info("=== Generating: %s ===", drug["inn"])

        pipeline = AIIntelligencePipeline()
        insight, article = await pipeline.run(
            drug=drug, preprints=[], market_reports=[],
            expert_opinions=[], article_type="briefing",
        )
        cards.append(build_article_card(drug, insight, article))
        logger.info("Done: %s (score=%s)", drug["inn"], insight.get("verified_score"))

    html = build_html("\n".join(cards))

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "briefing_sample.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = os.path.abspath(out_path)
    logger.info("HTML saved: %s", abs_path)
    print(abs_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 브리핑 기사 생성")
    parser.add_argument(
        "--min-score", type=int,
        default=settings.MIN_SCORE_FOR_AI_PIPELINE,
        help=f"최소 global_score (기본: {settings.MIN_SCORE_FOR_AI_PIPELINE})",
    )
    args = parser.parse_args()
    asyncio.run(main(min_score=args.min_score))
