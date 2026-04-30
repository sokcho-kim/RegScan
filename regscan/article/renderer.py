"""기사 MD → 신문형 HTML 렌더러 (각주 포함)

Usage:
    python -m regscan.article.renderer output/articles/articles_2026-04-30-v14.md
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path


def parse_articles_md(md_text: str) -> dict:
    """기사 MD 파일을 파싱."""
    lines = md_text.strip().split("\n")
    date_str = ""
    articles = []
    current: dict | None = None

    for line in lines:
        m = re.match(r"^>\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            date_str = m.group(1)
            continue

        m = re.match(r"^##\s+\d+\.\s+(.+?)\s*\[(\S+)\]\s*$", line)
        if m:
            if current:
                articles.append(current)
            current = {
                "headline": m.group(1).strip(),
                "grade": m.group(2),
                "subheadline": "",
                "body_lines": [],
                "citations": [],
            }
            continue

        if current is None:
            continue

        if not current["body_lines"] and not current["subheadline"] and line.strip() == "":
            continue

        if line.startswith("**") and not current["body_lines"] and not current["subheadline"]:
            current["subheadline"] = line.strip("* ")
            continue

        if line.strip() == "---":
            if current:
                articles.append(current)
                current = None
            continue

        if line.strip().startswith("> guardrail:"):
            continue

        if line.strip() == "**출처**":
            current["_in_citations"] = True
            continue
        if current.get("_in_citations"):
            if line.startswith("- "):
                current["citations"].append(line[2:].strip())
            elif line.strip() == "":
                current["_in_citations"] = False
            continue

        current["body_lines"].append(line)

    if current:
        articles.append(current)

    for art in articles:
        art.pop("_in_citations", None)
        body = "\n".join(art.pop("body_lines")).strip()
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        art["paragraphs"] = paragraphs

    return {"date": date_str, "articles": articles}


def _build_body_and_sources(paragraphs: list[str], citations: list[str]) -> tuple[str, str]:
    """본문 HTML + 기사 하단 '더 알아보기' 링크 생성. 인라인 각주 없음."""
    # 본문
    body_html = "\n".join(f"<p>{_render_inline(p)}</p>" for p in paragraphs if p)

    # 출처 → "더 알아보기" 링크 카드 (최대 3개)
    if not citations:
        return body_html, ""

    links = []
    for c in citations[:3]:
        m = re.search(r"(https?://\S+)", c)
        if not m:
            continue
        url = m.group(1)
        label = c[:c.index(url)].rstrip(": ").strip()
        # 도메인 추출
        dm = re.search(r"https?://(?:www\.)?([^/\s]+)", url)
        domain = dm.group(1) if dm else ""
        # 라벨이 없거나 너무 길면 도메인으로
        if not label or len(label) > 50:
            label = domain
        links.append(f'<a href="{url}" target="_blank" rel="noopener">'
                     f'{_escape(label)}<span class="src-domain">{_escape(domain)}</span></a>')

    if not links:
        return body_html, ""

    sources_html = (
        '<div class="read-more">'
        '<span class="read-more-label">더 알아보기</span>'
        + "".join(links)
        + '</div>'
    )
    return body_html, sources_html


def _extract_match_keywords(label: str) -> list[str]:
    """출처 라벨에서 본문 매칭용 키워드 추출."""
    keywords = []
    # TA 번호
    for m in re.finditer(r"TA\d{3,4}", label):
        keywords.append(m.group())
    # 법안명 핵심 (일부개정법률안 제거)
    cleaned = re.sub(r"\s*(일부|전부)개정.*$", "", label).strip()
    if len(cleaned) > 4:
        keywords.append(cleaned)
    # 약물명 (영문)
    for m in re.finditer(r"[A-Z][a-z]{3,}", label):
        keywords.append(m.group().lower())
    return keywords


def render_html(data: dict) -> str:
    """파싱된 기사 데이터 → HTML."""
    date_str = data["date"]
    articles = data["articles"]

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        date_display = f"{dt.year}년 {dt.month}월 {dt.day}일 {weekdays[dt.weekday()]}요일"
    except ValueError:
        date_display = date_str

    grade_color = {"분석": "#c0392b", "해설": "#2980b9", "카드": "#27ae60"}

    articles_html = ""
    for i, art in enumerate(articles):
        grade = art["grade"]
        color = grade_color.get(grade, "#666")
        is_top = i == 0

        body_html, sources_html = _build_body_and_sources(art["paragraphs"], art["citations"])

        cls = "article-top" if is_top else "article-sub"

        articles_html += f"""
        <article class="{cls}">
            <div class="article-meta">
                <span class="grade-badge" style="background:{color}">{grade}</span>
                <span class="article-num">Article {i+1}</span>
            </div>
            <h2 class="headline">{_escape(art['headline'])}</h2>
            <p class="subheadline">{_escape(art['subheadline'])}</p>
            <div class="body">
                {body_html}
            </div>
            {sources_html}
        </article>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RegScan Daily — {date_str}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700;900&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');

:root {{
    --bg: #f5f3ef;
    --paper: #fffef9;
    --ink: #1a1a1a;
    --muted: #666;
    --accent: #c0392b;
    --border: #d4d0c8;
    --fn-bg: #f9f8f5;
}}

* {{ margin:0; padding:0; box-sizing:border-box; }}

body {{
    font-family: 'Noto Sans KR', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--ink);
    line-height: 1.8;
}}

.wrap {{
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 16px;
}}

/* ── 헤더 ── */
header {{
    background: var(--paper);
    border-bottom: 3px double var(--ink);
    padding: 20px 28px 16px;
    margin-bottom: 2px;
}}
.header-row {{
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 12px;
}}
.masthead {{
    text-align: center;
    padding: 8px 0;
    border-top: 1px solid var(--border);
}}
.logo {{
    font-family: 'Noto Serif KR', serif;
    font-size: 42px;
    font-weight: 900;
    letter-spacing: -1px;
    line-height: 1;
    margin-bottom: 2px;
}}
.tagline {{
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 4px;
    font-weight: 300;
}}

/* ── 기사 ── */
article {{
    background: var(--paper);
    padding: 28px;
    margin-bottom: 2px;
}}

.article-meta {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}}
.grade-badge {{
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 2px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
.article-num {{
    font-size: 10px;
    color: var(--muted);
    letter-spacing: 1px;
}}

.headline {{
    font-family: 'Noto Serif KR', serif;
    font-weight: 700;
    line-height: 1.35;
    margin-bottom: 6px;
    word-break: keep-all;
}}
.article-top .headline {{ font-size: 26px; }}
.article-sub .headline {{ font-size: 20px; }}

.subheadline {{
    font-size: 14px;
    color: var(--muted);
    font-weight: 500;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
}}

.body p {{
    font-size: 15.5px;
    margin-bottom: 14px;
    text-align: justify;
    word-break: keep-all;
    line-height: 1.85;
}}

/* 톱기사 드롭캡 */
.article-top .body p:first-child::first-letter {{
    font-family: 'Noto Serif KR', serif;
    font-size: 3.2em;
    float: left;
    line-height: 0.85;
    margin: 4px 8px 0 0;
    font-weight: 900;
    color: var(--accent);
}}

/* ── 더 알아보기 ── */
.read-more {{
    margin-top: 20px;
    padding: 14px 18px;
    background: var(--fn-bg);
    border-top: 1px solid var(--border);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
}}
.read-more-label {{
    font-size: 11px;
    font-weight: 600;
    color: var(--muted);
    letter-spacing: 0.5px;
    margin-right: 4px;
}}
.read-more a {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    color: #2471a3;
    text-decoration: none;
    padding: 4px 12px;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    background: white;
    transition: border-color 0.15s, background 0.15s;
}}
.read-more a:hover {{
    border-color: #2471a3;
    background: #f0f7fc;
}}
.src-domain {{
    font-size: 10px;
    color: #999;
    margin-left: 2px;
}}

/* ── 푸터 ── */
footer {{
    background: var(--paper);
    padding: 14px 28px;
    border-top: 2px solid var(--ink);
    font-size: 11px;
    color: var(--muted);
    text-align: center;
}}

/* ── 반응형 ── */
@media (max-width: 640px) {{
    .wrap {{ padding: 8px; }}
    article {{ padding: 18px 16px; }}
    .article-top .headline {{ font-size: 21px; }}
    .logo {{ font-size: 32px; }}
}}
</style>
</head>
<body>
<div class="wrap">
    <header>
        <div class="header-row">
            <span>{date_display}</span>
            <span>{len(articles)}건의 기사</span>
        </div>
        <div class="masthead">
            <div class="logo">RegScan</div>
            <div class="tagline">PHARMACEUTICAL REGULATORY INTELLIGENCE</div>
        </div>
    </header>

    <main>
        {articles_html}
    </main>

    <footer>
        RegScan Daily &mdash; AI-curated pharma regulatory intelligence
        &bull; {datetime.now().strftime('%Y-%m-%d %H:%M')} generated
    </footer>
</div>
</body>
</html>"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_inline(text: str) -> str:
    escaped = _escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m regscan.article.renderer <articles.md>")
        sys.exit(1)
    md_path = Path(sys.argv[1])
    if not md_path.exists():
        print(f"파일 없음: {md_path}")
        sys.exit(1)
    md_text = md_path.read_text(encoding="utf-8")
    data = parse_articles_md(md_text)
    html = render_html(data)
    out_path = md_path.with_suffix(".html")
    out_path.write_text(html, encoding="utf-8")
    print(f"생성: {out_path} ({len(data['articles'])}건)")


if __name__ == "__main__":
    main()
