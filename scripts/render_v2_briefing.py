"""V2 브리핑 JSON → HTML 렌더러

새 프롬프트 구조(top_stories, brief_updates, outlook) 반영.
빈 섹션 자동 숨김.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path


def _section(title: str, content: str, card_class: str = "bg-white") -> str:
    """비어있으면 빈 문자열 반환 (섹션 숨김)."""
    if not content or not content.strip():
        return ""
    return f"""
            <div class="{card_class} rounded-lg shadow-sm border p-6 mb-6">
                <h3 class="font-bold text-gray-900 mb-3">{title}</h3>
                <div class="report-body text-gray-700 whitespace-pre-line">{content}</div>
            </div>"""


def _list_section(title: str, items: list, card_class: str = "bg-white", item_class: str = "text-gray-700") -> str:
    """리스트가 비어있으면 빈 문자열."""
    if not items:
        return ""
    li = "".join(f"<li class='mb-1'>&bull; {item}</li>" for item in items)
    return f"""
            <div class="{card_class} rounded-lg shadow-sm border p-5 mb-6">
                <h4 class="font-bold text-gray-900 mb-3 meta-text text-sm">{title}</h4>
                <ul class="text-sm {item_class} space-y-1">{li}</ul>
            </div>"""


def render_briefing_html(stream: dict, unified: dict, date_str: str = "") -> str:
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    parts = []

    # ── Header ──
    parts.append(f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan Weekly Briefing — {date_str}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');
        body {{ font-family: 'Noto Serif KR', serif; background: #fafafa; }}
        .report-title {{ font-family: 'Noto Serif KR', serif; font-weight: 700; }}
        .report-body {{ font-family: 'Noto Serif KR', serif; line-height: 1.9; font-size: 17px; }}
        .meta-text {{ font-family: 'Inter', sans-serif; }}
        .highlight-box {{ border-left: 4px solid #1e40af; background: linear-gradient(90deg, #eff6ff 0%, #ffffff 100%); }}
        .story-card {{ border-left: 3px solid #6366f1; }}
    </style>
</head>
<body class="min-h-screen">
    <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div class="max-w-4xl mx-auto px-6 py-4">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <span class="text-xl font-bold text-gray-900">MedClaim</span>
                    <span class="text-gray-300">|</span>
                    <span class="text-sm text-gray-500 meta-text">RegScan Weekly Briefing</span>
                </div>
                <span class="meta-text text-sm text-gray-500">{date_str}</span>
            </div>
        </div>
    </header>
    <main class="max-w-4xl mx-auto px-6 py-10">""")

    # ── Main Briefing (stream) ──
    headline = stream.get("headline", "")
    takeaway = stream.get("key_takeaway", "")
    top_stories = stream.get("top_stories", [])
    brief_updates = stream.get("brief_updates", [])
    outlook = stream.get("outlook", "")

    parts.append(f"""
        <article>
            <h1 class="report-title text-3xl text-gray-900 mb-4 leading-tight">{headline}</h1>
            <div class="highlight-box p-6 rounded-r-lg mb-10">
                <p class="report-body text-gray-800">{takeaway}</p>
            </div>""")

    # Top Stories
    if top_stories:
        parts.append('<h2 class="font-bold text-gray-900 mb-4 text-lg">Top Stories</h2>')
        for i, s in enumerate(top_stories):
            inn = s.get("inn", "")
            event = s.get("event", "")
            indication = s.get("indication", "")
            competition = s.get("competition", "")
            domestic = s.get("domestic_impact", s.get("domestic", ""))
            significance = s.get("significance", "")

            parts.append(f"""
            <div class="story-card bg-white rounded-r-lg shadow-sm p-5 mb-5 ml-1">
                <div class="flex items-center space-x-2 mb-2">
                    <span class="text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">{i+1}</span>
                    <h3 class="text-lg font-semibold text-gray-900">{inn}</h3>
                </div>
                <p class="text-sm text-gray-800 mb-3 font-medium">{event}</p>""")

            if indication:
                parts.append(f'<p class="text-sm text-gray-600 mb-2"><span class="font-semibold text-gray-700">적응증:</span> {indication}</p>')
            if competition:
                parts.append(f'<p class="text-sm text-gray-600 mb-2"><span class="font-semibold text-gray-700">경쟁구도:</span> {competition}</p>')
            if domestic:
                parts.append(f'<p class="text-sm text-gray-600 mb-2"><span class="font-semibold text-gray-700">국내:</span> {domestic}</p>')
            if significance:
                parts.append(f'<p class="text-sm text-gray-600 mb-2"><span class="font-semibold text-gray-700">의의:</span> {significance}</p>')

            parts.append("</div>")

    # Brief Updates
    if brief_updates:
        parts.append(_list_section("Brief Updates", brief_updates, "bg-gray-50", "text-gray-600"))

    # Outlook
    if outlook:
        parts.append(f"""
            <div class="bg-blue-50 rounded-lg border border-blue-100 p-5 mb-6">
                <h4 class="font-bold text-blue-800 mb-2 meta-text text-sm">OUTLOOK</h4>
                <p class="text-sm text-blue-900">{outlook}</p>
            </div>""")

    parts.append("</article>")

    # ── Unified Briefing (있으면) ──
    u_headline = unified.get("headline", "")
    u_summary = unified.get("executive_summary", "")
    u_stories = unified.get("top_stories", unified.get("top_5_drugs", []))
    u_brief = unified.get("brief_updates", [])
    u_outlook = unified.get("outlook", unified.get("tomorrow_watch", ""))

    if u_headline and u_stories:
        parts.append(f"""
        <section class="border-t pt-10 mt-10">
            <div class="flex items-center space-x-3 mb-4">
                <span class="px-3 py-1 bg-gray-800 text-white text-xs font-semibold rounded">WEEKLY OVERVIEW</span>
            </div>
            <h2 class="report-title text-2xl text-gray-900 mb-4">{u_headline}</h2>""")

        if u_summary:
            parts.append(f"""
            <div class="bg-white rounded-lg shadow-sm border p-6 mb-6">
                <div class="report-body text-gray-700 whitespace-pre-line">{u_summary}</div>
            </div>""")

        for s in u_stories:
            rank = s.get("rank", "")
            inn = s.get("inn", "")
            event = s.get("event", s.get("reason", ""))
            sig = s.get("significance", s.get("action", ""))
            domestic = s.get("domestic", "")

            parts.append(f"""
            <div class="bg-white rounded-lg shadow-sm border p-4 mb-3">
                <div class="flex items-center space-x-2 mb-1">
                    {"<span class='text-xs font-bold text-gray-500'>#{rank}</span>" if rank else ""}
                    <span class="font-semibold text-gray-900">{inn}</span>
                </div>
                <p class="text-sm text-gray-600">{event}</p>""")
            if sig:
                parts.append(f'<p class="text-sm text-gray-500 mt-1">{sig}</p>')
            if domestic:
                parts.append(f'<p class="text-sm text-indigo-600 mt-1">{domestic}</p>')
            parts.append("</div>")

        if u_brief:
            parts.append(_list_section("Updates", u_brief, "bg-gray-50", "text-gray-500"))

        if u_outlook:
            parts.append(f"""
            <div class="bg-gray-50 rounded-lg p-4 border mt-4">
                <span class="meta-text text-xs text-gray-500 font-semibold">NEXT WEEK:</span>
                <span class="text-sm text-gray-700"> {u_outlook}</span>
            </div>""")

        parts.append("</section>")

    # ── Footer ──
    parts.append(f"""
        <footer class="mt-16 pt-8 border-t text-center meta-text text-xs text-gray-400">
            <p>Generated by RegScan | MedClaim Insight</p>
            <p>{date_str} | Weekly Drug Regulatory Briefing</p>
        </footer>
    </main>
</body>
</html>""")

    return "\n".join(parts)


if __name__ == "__main__":
    db_path = Path(__file__).parent.parent / "data" / "regscan.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT briefing_type, content_json FROM stream_briefings
        ORDER BY generated_at DESC LIMIT 2
    """)
    rows = cur.fetchall()
    conn.close()

    stream_data = {}
    unified_data = {}
    for btype, cjson in rows:
        c = json.loads(cjson)
        if btype == "stream" and not stream_data:
            stream_data = c
        elif btype == "unified" and not unified_data:
            unified_data = c

    html = render_briefing_html(stream_data, unified_data)
    out = Path(__file__).parent.parent / "output" / "briefings" / "snapshots" / "2026-04-16_v2_journalist" / "briefing_v2.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Saved: {out}")
