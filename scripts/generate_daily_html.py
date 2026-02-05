"""일간 브리핑 HTML 페이지 생성 - 뉴스레터 스타일"""

import sys
import io
import json
import asyncio
from pathlib import Path
from datetime import datetime, date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.monitor import DailyScanner, ScanResult, NewApproval
from fastapi.testclient import TestClient
from regscan.api.main import app

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "daily_scan"
client = TestClient(app)


def get_briefing_data(inn: str) -> dict:
    """API에서 브리핑 데이터 가져오기"""
    r = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm=true")
    if r.status_code == 200:
        return r.json()
    return None


def get_drug_detail(inn: str) -> dict:
    """API에서 약물 상세 데이터 가져오기"""
    r = client.get(f"/api/v1/drugs/{inn}")
    if r.status_code == 200:
        return r.json()
    return {}


def generate_daily_html(result: ScanResult) -> str:
    """일간 브리핑 HTML 생성 - 뉴스레터 스타일"""

    today = result.scan_date.strftime("%Y년 %m월 %d일")
    today_short = result.scan_date.strftime("%Y-%m-%d")
    weekday = ['월', '화', '수', '목', '금', '토', '일'][result.scan_date.weekday()]

    # 핫이슈 기사 생성
    hot_articles = ''
    seen = set()
    for approval in result.hot_issues[:4]:
        if approval.generic_name in seen:
            continue
        seen.add(approval.generic_name)

        briefing = get_briefing_data(approval.generic_name)
        detail = get_drug_detail(approval.generic_name)
        hot_articles += generate_article(approval, briefing, detail, is_main=(len(seen)==1))

    # 일반 승인 목록
    all_approvals = result.fda_new + result.ema_new + result.mfds_new
    other_list = ''
    for approval in all_approvals:
        if approval.generic_name not in seen:
            other_list += f'''
                <tr>
                    <td class="name">{approval.generic_name}</td>
                    <td class="brand">{approval.drug_name}</td>
                    <td class="source">{approval.source.value.upper()}</td>
                    <td class="date">{approval.approval_date.strftime("%m/%d")}</td>
                </tr>
            '''

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan Daily - {today_short}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700&family=Noto+Sans+KR:wght@400;500;600&display=swap');

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Noto Sans KR', sans-serif;
            background: #f5f5f5;
            color: #1a1a1a;
            line-height: 1.6;
        }}

        .wrapper {{
            max-width: 720px;
            margin: 0 auto;
            background: #fff;
            min-height: 100vh;
        }}

        /* 헤더 */
        header {{
            padding: 24px 32px;
            border-bottom: 3px solid #1a1a1a;
        }}

        .masthead {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 8px;
        }}

        .logo {{
            font-family: 'Noto Serif KR', serif;
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -1px;
        }}

        .date-area {{
            font-size: 13px;
            color: #666;
        }}

        .tagline {{
            font-size: 12px;
            color: #888;
            letter-spacing: 2px;
            text-transform: uppercase;
        }}

        /* 요약 바 */
        .summary-bar {{
            display: flex;
            justify-content: space-between;
            padding: 12px 32px;
            background: #fafafa;
            border-bottom: 1px solid #eee;
            font-size: 13px;
        }}

        .summary-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .summary-item .num {{
            font-weight: 600;
            color: #1a1a1a;
        }}

        .summary-item.hot .num {{
            color: #c00;
        }}

        /* 메인 콘텐츠 */
        main {{
            padding: 32px;
        }}

        /* 기사 스타일 */
        .article {{
            margin-bottom: 32px;
            padding-bottom: 32px;
            border-bottom: 1px solid #eee;
        }}

        .article:last-child {{
            border-bottom: none;
        }}

        .article.main {{
            margin-bottom: 40px;
            padding-bottom: 40px;
        }}

        .article-meta {{
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }}

        .tag {{
            font-size: 11px;
            padding: 3px 8px;
            background: #1a1a1a;
            color: #fff;
            font-weight: 500;
        }}

        .tag.hot {{
            background: #c00;
        }}

        .tag.orphan {{
            background: #5a4fcf;
        }}

        .tag.fda {{
            background: #0066cc;
        }}

        .tag.ema {{
            background: #cc6600;
        }}

        .tag.mfds {{
            background: #008844;
        }}

        .article-title {{
            font-family: 'Noto Serif KR', serif;
            font-size: 24px;
            font-weight: 700;
            line-height: 1.4;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }}

        .article.main .article-title {{
            font-size: 32px;
        }}

        .article-subtitle {{
            font-size: 15px;
            color: #666;
            margin-bottom: 16px;
        }}

        .article-body {{
            font-size: 15px;
            line-height: 1.8;
            color: #333;
        }}

        .article-body p {{
            margin-bottom: 12px;
        }}

        .key-points {{
            margin: 20px 0;
            padding: 16px 20px;
            background: #f9f9f9;
            border-left: 3px solid #1a1a1a;
        }}

        .key-points li {{
            margin-bottom: 6px;
            font-size: 14px;
        }}

        .medclaim-box {{
            margin: 20px 0;
            padding: 16px 20px;
            background: #fff8f0;
            border: 1px solid #f0e0d0;
        }}

        .medclaim-box .label {{
            font-size: 12px;
            font-weight: 600;
            color: #996633;
            margin-bottom: 8px;
        }}

        .medclaim-box .content {{
            font-size: 14px;
            color: #664422;
        }}

        .price-info {{
            display: inline-flex;
            align-items: baseline;
            gap: 4px;
            margin-top: 8px;
            font-size: 13px;
        }}

        .price-info .price {{
            font-size: 18px;
            font-weight: 600;
            color: #006644;
        }}

        /* 기타 승인 목록 */
        .other-section {{
            margin-top: 32px;
            padding-top: 24px;
            border-top: 2px solid #1a1a1a;
        }}

        .section-title {{
            font-family: 'Noto Serif KR', serif;
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 16px;
        }}

        .other-table {{
            width: 100%;
            font-size: 13px;
            border-collapse: collapse;
        }}

        .other-table th {{
            text-align: left;
            padding: 8px 0;
            border-bottom: 1px solid #1a1a1a;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #666;
        }}

        .other-table td {{
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}

        .other-table .name {{
            font-weight: 500;
        }}

        .other-table .brand {{
            color: #666;
        }}

        .other-table .source {{
            font-size: 11px;
            font-weight: 600;
        }}

        .other-table .date {{
            color: #888;
            text-align: right;
        }}

        /* 푸터 */
        footer {{
            padding: 24px 32px;
            border-top: 1px solid #eee;
            font-size: 11px;
            color: #888;
            text-align: center;
        }}

        footer a {{
            color: #666;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <header>
            <div class="masthead">
                <div class="logo">RegScan</div>
                <div class="date-area">{today} ({weekday})</div>
            </div>
            <div class="tagline">Global Regulatory Intelligence</div>
        </header>

        <div class="summary-bar">
            <div class="summary-item">
                <span>FDA</span>
                <span class="num">{len(result.fda_new)}</span>
            </div>
            <div class="summary-item">
                <span>EMA</span>
                <span class="num">{len(result.ema_new)}</span>
            </div>
            <div class="summary-item">
                <span>MFDS</span>
                <span class="num">{len(result.mfds_new)}</span>
            </div>
            <div class="summary-item hot">
                <span>HOT</span>
                <span class="num">{len(result.hot_issues)}</span>
            </div>
        </div>

        <main>
            {hot_articles}

            {f'''
            <div class="other-section">
                <h3 class="section-title">Other Approvals</h3>
                <table class="other-table">
                    <thead>
                        <tr>
                            <th>성분명</th>
                            <th>제품명</th>
                            <th>출처</th>
                            <th style="text-align:right">승인일</th>
                        </tr>
                    </thead>
                    <tbody>
                        {other_list}
                    </tbody>
                </table>
            </div>
            ''' if other_list else ''}
        </main>

        <footer>
            <p>RegScan AI · Scanning Global Regulation into Local Impact</p>
            <p>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
        </footer>
    </div>
</body>
</html>
'''


def generate_article(approval: NewApproval, briefing: dict, detail: dict, is_main: bool = False) -> str:
    """기사 HTML 생성"""

    # 태그
    tags = []
    if approval.hot_issue_score >= 30:
        tags.append('<span class="tag hot">HOT</span>')
    tags.append(f'<span class="tag {approval.source.value}">{approval.source.value.upper()}</span>')
    if approval.is_orphan or '희귀' in str(approval.hot_issue_reasons):
        tags.append('<span class="tag orphan">희귀의약품</span>')

    tags_html = ''.join(tags)

    # 제목
    if briefing:
        title = briefing.get('headline', f'{approval.generic_name} 규제 동향')
        subtitle = briefing.get('subtitle', '')
    else:
        title = f'{approval.generic_name}, {approval.source.value.upper()} 승인'
        subtitle = f'{approval.drug_name} · {approval.approval_date}'

    # 본문
    body_html = ''
    if briefing:
        # 핵심 포인트
        key_points = briefing.get('key_points', [])
        if key_points:
            points_html = ''.join([f'<li>{p}</li>' for p in key_points[:4]])
            body_html += f'<ul class="key-points">{points_html}</ul>'

        # 글로벌 현황
        if briefing.get('global_section'):
            body_html += f'<p>{briefing["global_section"]}</p>'

        # 국내 현황
        if briefing.get('domestic_section'):
            body_html += f'<p>{briefing["domestic_section"]}</p>'

        # 메드클레임 박스
        if briefing.get('medclaim_section'):
            price_html = ''
            if detail and detail.get('hira_price'):
                price = detail['hira_price']
                price_html = f'<div class="price-info">상한가 <span class="price">₩{price:,.0f}</span></div>'

            body_html += f'''
                <div class="medclaim-box">
                    <div class="label">메드클레임 시사점</div>
                    <div class="content">{briefing["medclaim_section"]}</div>
                    {price_html}
                </div>
            '''

    return f'''
        <article class="article {'main' if is_main else ''}">
            <div class="article-meta">{tags_html}</div>
            <h2 class="article-title">{title}</h2>
            <p class="article-subtitle">{subtitle}</p>
            <div class="article-body">{body_html}</div>
        </article>
    '''


async def main():
    print("RegScan 일간 브리핑 HTML 생성")
    print()

    # 1. 스캔 실행
    print("[1/3] 일간 스캔...")
    scanner = DailyScanner()
    scanner.load_existing_data()

    async with scanner:
        result = await scanner.scan(days_back=7)

    print(f"      FDA {len(result.fda_new)}건 / 핫이슈 {len(result.hot_issues)}건")

    # 2. HTML 생성
    print("[2/3] HTML 생성...")
    html_content = generate_daily_html(result)

    # 3. 저장
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"daily_briefing_{result.scan_date}.html"
    html_file.write_text(html_content, encoding='utf-8')
    print(f"[3/3] 저장: {html_file}")

    # 브라우저 열기
    import subprocess
    subprocess.Popen(['start', '', str(html_file)], shell=True)


if __name__ == "__main__":
    asyncio.run(main())
