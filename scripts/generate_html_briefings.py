"""핫이슈 약물 HTML 브리핑 리포트 생성"""

import sys
import io
import json
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from regscan.api.main import app

client = TestClient(app)
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "briefings"


def get_html_template(data: dict, detail: dict) -> str:
    """브리핑 HTML 템플릿 생성"""
    today = datetime.now().strftime("%Y년 %m월 %d일")
    today_iso = datetime.now().strftime("%Y-%m-%d")

    # 태그 생성
    tags = []
    if detail.get('global_score', 0) >= 70:
        tags.append('<span class="px-3 py-1 bg-red-600 text-white text-xs font-semibold rounded">HOT ISSUE</span>')
    elif detail.get('global_score', 0) >= 60:
        tags.append('<span class="px-3 py-1 bg-orange-500 text-white text-xs font-semibold rounded">HIGH</span>')

    if any('희귀' in r or 'Orphan' in r for r in detail.get('hot_issue_reasons', [])):
        tags.append('<span class="px-3 py-1 bg-gray-100 text-gray-600 text-xs rounded">희귀의약품</span>')
    if any('Breakthrough' in r for r in detail.get('hot_issue_reasons', [])):
        tags.append('<span class="px-3 py-1 bg-gray-100 text-gray-600 text-xs rounded">혁신신약</span>')
    if detail.get('cris_trial_count', 0) > 0:
        tags.append('<span class="px-3 py-1 bg-blue-100 text-blue-600 text-xs rounded">국내 임상 진행</span>')

    tags_html = '\n            '.join(tags) if tags else '<span class="px-3 py-1 bg-gray-100 text-gray-600 text-xs rounded">신약</span>'

    # 핵심 요약 리스트
    key_points_html = '\n'.join([
        f'''                <li class="flex items-start">
                    <span class="text-red-500 mr-2">▸</span>
                    <span>{point}</span>
                </li>'''
        for point in data.get('key_points', [])
    ])

    # 타임라인 생성
    timeline_items = []

    if detail.get('fda_date'):
        fda_date = detail['fda_date']
        timeline_items.append({
            'date': fda_date,
            'color': 'blue',
            'flag': '🇺🇸',
            'label': 'FDA 승인',
            'desc': 'Approved'
        })

    if detail.get('ema_date'):
        ema_date = detail['ema_date']
        timeline_items.append({
            'date': ema_date,
            'color': 'yellow',
            'flag': '🇪🇺',
            'label': 'EMA 승인',
            'desc': 'Authorised'
        })

    if detail.get('mfds_date'):
        mfds_date = detail['mfds_date']
        timeline_items.append({
            'date': mfds_date,
            'color': 'green',
            'flag': '🇰🇷',
            'label': 'MFDS 허가',
            'desc': detail.get('mfds_brand_name', '')[:30]
        })
    else:
        timeline_items.append({
            'date': '미정',
            'color': 'gray',
            'flag': '🇰🇷',
            'label': 'MFDS 허가',
            'desc': '허가 신청 미확인',
            'pending': True
        })

    # 타임라인 정렬 (날짜순)
    timeline_items.sort(key=lambda x: x['date'] if x['date'] != '미정' else '9999-99-99')

    timeline_html = ''
    for item in timeline_items:
        dot_class = f"bg-{item['color']}-500" if not item.get('pending') else "bg-gray-300 border-2 border-dashed border-gray-400"
        text_class = f"text-{item['color']}-600" if not item.get('pending') else "text-gray-400"

        timeline_html += f'''
                    <div class="relative flex items-center mb-6">
                        <div class="timeline-dot {dot_class} z-10"></div>
                        <div class="ml-6">
                            <div class="meta-text text-xs {text_class} font-semibold">{item['date']}</div>
                            <div class="font-medium {'text-gray-400' if item.get('pending') else ''}">{item['flag']} {item['label']}</div>
                            <div class="text-sm text-gray-500">{item['desc']}</div>
                        </div>
                    </div>'''

    # 메드클레임 박스
    medclaim_html = data.get('medclaim_section', '')
    if detail.get('hira_price'):
        price = detail['hira_price']
        burden_30 = int(price * 0.3)
        burden_10 = int(price * 0.1)
        burden_5 = int(price * 0.05)
        medclaim_extra = f'''
                    <div class="mt-4 pt-4 border-t border-indigo-200">
                        <div class="grid grid-cols-3 gap-4 text-center">
                            <div>
                                <div class="text-xs text-gray-500">상한가</div>
                                <div class="font-bold text-indigo-700">₩{price:,.0f}</div>
                            </div>
                            <div>
                                <div class="text-xs text-gray-500">일반 급여 (30%)</div>
                                <div class="font-bold text-gray-700">₩{burden_30:,}</div>
                            </div>
                            <div>
                                <div class="text-xs text-gray-500">암환자 특례 (5%)</div>
                                <div class="font-bold text-green-600">₩{burden_5:,}</div>
                            </div>
                        </div>
                    </div>'''
    else:
        medclaim_extra = ''

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan 브리핑 - {data['inn']}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

        body {{
            font-family: 'Noto Serif KR', serif;
            background: #fafafa;
        }}

        .report-title {{
            font-family: 'Noto Serif KR', serif;
            font-weight: 700;
        }}

        .report-body {{
            font-family: 'Noto Serif KR', serif;
            line-height: 1.9;
            font-size: 17px;
        }}

        .meta-text {{
            font-family: 'Inter', sans-serif;
        }}

        .highlight-box {{
            border-left: 4px solid #dc2626;
            background: linear-gradient(90deg, #fef2f2 0%, #ffffff 100%);
        }}

        .timeline-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }}
    </style>
</head>
<body class="min-h-screen">
    <!-- Header -->
    <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div class="max-w-4xl mx-auto px-6 py-4">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <span class="text-xl font-bold text-gray-900">MedClaim</span>
                    <span class="text-gray-300">|</span>
                    <span class="text-sm text-gray-500 meta-text">RegScan 브리핑</span>
                </div>
                <div class="meta-text text-sm text-gray-500">
                    {today}
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-4xl mx-auto px-6 py-10">
        <!-- Category & Tags -->
        <div class="flex items-center space-x-3 mb-6 meta-text">
            {tags_html}
        </div>

        <!-- Title -->
        <h1 class="report-title text-4xl text-gray-900 mb-4 leading-tight">
            {data['headline']}
        </h1>

        <!-- Subtitle -->
        <p class="text-xl text-gray-600 mb-8 leading-relaxed">
            {data['subtitle']}
        </p>

        <!-- Author & Date -->
        <div class="flex items-center space-x-4 mb-10 pb-10 border-b border-gray-200 meta-text">
            <div class="flex items-center space-x-2">
                <div class="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center">
                    <span class="text-indigo-600 text-xs font-bold">AI</span>
                </div>
                <span class="text-sm text-gray-600">RegScan AI 리포터</span>
            </div>
            <span class="text-gray-300">·</span>
            <span class="text-sm text-gray-500">Hot Issue Score: {detail.get('global_score', 0)}</span>
        </div>

        <!-- Key Points Box -->
        <div class="highlight-box p-6 rounded-r-lg mb-10">
            <h3 class="font-bold text-gray-900 mb-3 meta-text text-sm">핵심 요약</h3>
            <ul class="space-y-2 text-gray-800">
{key_points_html}
            </ul>
        </div>

        <!-- Article Body -->
        <article class="report-body text-gray-800">
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">글로벌 승인 현황</h2>

            <p class="mb-6">
                {data['global_section']}
            </p>

            <!-- Timeline Visual -->
            <div class="my-10 p-6 bg-gray-50 rounded-xl">
                <h4 class="meta-text text-sm font-semibold text-gray-500 mb-6">승인 타임라인</h4>
                <div class="relative">
                    <div class="absolute left-2 top-0 bottom-0 w-0.5 bg-gray-300"></div>
{timeline_html}
                </div>
            </div>

            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">국내 도입 전망</h2>

            <p class="mb-6">
                {data['domestic_section']}
            </p>

            <!-- MedClaim Box -->
            <div class="my-10 p-6 bg-indigo-50 rounded-xl border border-indigo-100">
                <h4 class="meta-text text-sm font-semibold text-indigo-600 mb-3">💡 메드클레임 시사점</h4>
                <div class="space-y-3 text-gray-800">
                    <p>{medclaim_html}</p>
{medclaim_extra}
                </div>
            </div>

            <!-- CRIS Trials -->
            {generate_cris_section(detail)}
        </article>

        <!-- Source & Disclaimer -->
        <footer class="mt-16 pt-8 border-t border-gray-200 meta-text text-sm text-gray-500">
            <div class="mb-4">
                <strong>데이터 출처:</strong> FDA Drug Approvals Database, EMA Public Assessment Reports,
                MFDS 의약품통합정보시스템, CRIS 임상연구정보서비스, HIRA 건강보험심사평가원
            </div>
            <div class="text-xs text-gray-400">
                본 리포트는 RegScan AI가 공개 데이터를 기반으로 자동 생성한 브리핑 자료입니다.
                의사결정에 활용 시 원문 확인을 권장합니다.
                마지막 업데이트: {today_iso}
            </div>
        </footer>
    </main>
</body>
</html>
'''


def generate_cris_section(detail: dict) -> str:
    """CRIS 임상시험 섹션 생성"""
    trials = detail.get('cris_trials', [])
    if not trials:
        return ''

    trials_html = ''
    for t in trials[:5]:
        trials_html += f'''
                    <tr class="border-b border-gray-100">
                        <td class="py-3 px-4 font-mono text-sm text-blue-600">{t.get('trial_id', '')}</td>
                        <td class="py-3 px-4 text-sm">{t.get('title', '')[:60]}...</td>
                        <td class="py-3 px-4 text-sm text-center">{t.get('phase', '-')}</td>
                        <td class="py-3 px-4 text-sm text-center">{t.get('status', '-')}</td>
                    </tr>'''

    return f'''
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">국내 임상시험 현황</h2>

            <div class="my-6 overflow-hidden rounded-lg border border-gray-200">
                <table class="w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="py-3 px-4 text-left text-xs font-semibold text-gray-600">CRIS ID</th>
                            <th class="py-3 px-4 text-left text-xs font-semibold text-gray-600">연구제목</th>
                            <th class="py-3 px-4 text-center text-xs font-semibold text-gray-600">Phase</th>
                            <th class="py-3 px-4 text-center text-xs font-semibold text-gray-600">상태</th>
                        </tr>
                    </thead>
                    <tbody>{trials_html}
                    </tbody>
                </table>
            </div>
            <p class="text-sm text-gray-500 mb-10">
                총 {len(detail.get('cris_trials', []))}건의 임상시험이 CRIS에 등록되어 있습니다.
            </p>
'''


def generate_index_html(reports: list) -> str:
    """목록 페이지 HTML 생성"""
    today = datetime.now().strftime("%Y년 %m월 %d일")

    cards_html = ''
    for r in reports:
        inn = r['inn']
        score = r['score']
        data = r['data']

        score_color = 'red' if score >= 70 else 'orange' if score >= 60 else 'gray'

        cards_html += f'''
            <a href="{inn.lower().replace(' ', '_')}.html" class="block bg-white rounded-xl shadow-sm hover:shadow-md transition-shadow border border-gray-100 overflow-hidden">
                <div class="p-6">
                    <div class="flex items-center justify-between mb-3">
                        <span class="px-2 py-1 bg-{score_color}-100 text-{score_color}-700 text-xs font-bold rounded">
                            Score {score}
                        </span>
                        <span class="text-xs text-gray-400">{r.get('detail', {}).get('domestic_status', '')}</span>
                    </div>
                    <h3 class="font-bold text-lg text-gray-900 mb-2">{inn}</h3>
                    <p class="text-sm text-gray-600 line-clamp-2">{data['subtitle'][:80]}...</p>
                    <div class="mt-4 flex items-center text-xs text-gray-500">
                        <span>{'🇺🇸 FDA' if r.get('detail', {}).get('fda_approved') else ''}</span>
                        <span class="mx-2">{'🇪🇺 EMA' if r.get('detail', {}).get('ema_approved') else ''}</span>
                        <span>{'🇰🇷 MFDS' if r.get('detail', {}).get('mfds_approved') else ''}</span>
                    </div>
                </div>
            </a>'''

    return f'''<!DOCTYPE html>
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
                <div class="text-sm text-gray-500">{today}</div>
            </div>
        </div>
    </header>

    <main class="max-w-6xl mx-auto px-6 py-10">
        <div class="mb-8">
            <h2 class="text-lg font-semibold text-gray-800">핫이슈 약물 ({len(reports)}건)</h2>
            <p class="text-sm text-gray-500">글로벌 승인 + 국내 미허가/미급여 약물</p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
{cards_html}
        </div>
    </main>

    <footer class="border-t border-gray-200 mt-16 py-8">
        <div class="max-w-6xl mx-auto px-6 text-center text-sm text-gray-400">
            RegScan AI - 글로벌 의약품 규제 인텔리전스
        </div>
    </footer>
</body>
</html>
'''


def generate_html_reports(use_llm: bool = True, limit: int = 10):
    """HTML 브리핑 리포트 일괄 생성"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 핫이슈 목록 조회
    print(f"[1] 핫이슈 약물 조회 (limit={limit})...")
    r = client.get(f"/api/v1/hot-issues?limit={limit}")
    if r.status_code != 200:
        print(f"Error: {r.text}")
        return

    hot_issues = r.json()
    print(f"    → {len(hot_issues)}건 조회됨\n")

    reports = []

    for i, item in enumerate(hot_issues, 1):
        inn = item['inn']
        score = item['global_score']
        print(f"[{i}/{len(hot_issues)}] {inn} (score: {score})...", end=" ")

        # 상세 정보 조회
        r_detail = client.get(f"/api/v1/drugs/{inn}")
        detail = r_detail.json() if r_detail.status_code == 200 else {}

        # 브리핑 생성
        r = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm={str(use_llm).lower()}")
        if r.status_code == 200:
            data = r.json()
            reports.append({
                "inn": inn,
                "score": score,
                "data": data,
                "detail": detail
            })

            # HTML 파일 저장
            html_content = get_html_template(data, detail)
            html_file = OUTPUT_DIR / f"{inn.lower().replace(' ', '_')}.html"
            html_file.write_text(html_content, encoding='utf-8')
            print("OK")
        else:
            print(f"FAILED ({r.status_code})")

    # 인덱스 페이지 생성
    index_html = generate_index_html(reports)
    index_file = OUTPUT_DIR / "index.html"
    index_file.write_text(index_html, encoding='utf-8')
    print(f"\n인덱스 페이지: {index_file}")
    print(f"총 {len(reports)}건 HTML 브리핑 생성 완료")

    return reports


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HTML 브리핑 리포트 생성")
    parser.add_argument("--limit", type=int, default=10, help="핫이슈 개수")
    parser.add_argument("--no-llm", action="store_true", help="템플릿 기반 (LLM 미사용)")

    args = parser.parse_args()
    use_llm = not args.no_llm

    generate_html_reports(use_llm=use_llm, limit=args.limit)
