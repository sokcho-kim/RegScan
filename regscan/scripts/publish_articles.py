"""기사 발행 스크립트 — DB 상위 약물 LLM 브리핑 → HTML 기사 생성

사용법:
    python -m regscan.scripts.publish_articles                # 상위 20개 약물
    python -m regscan.scripts.publish_articles --top 50       # 상위 50개
    python -m regscan.scripts.publish_articles --min-score 60 # score>=60만
    python -m regscan.scripts.publish_articles --skip-llm     # LLM 건너뜀 (기존 JSON만 HTML 변환)
    python -m regscan.scripts.publish_articles --render-only  # HTML만 재렌더 (LLM·DB 없이, ~2초)
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

# ── 산정특례 매핑 (적응증 기반) ──
COPAY_EXEMPTION_MAP = {
    "oncology": {"label": "암환자 산정특례", "rate": 0.05},
    "rare_disease": {"label": "희귀질환 산정특례", "rate": 0.10},
}


def _get_copay_exemption(impact) -> dict | None:
    """적응증 기반 산정특례 카테고리 결정.

    oncology → 암환자 산정특례(5%), rare_disease/희귀 → 희귀질환(10%), 그 외 → None.
    """
    areas = getattr(impact, 'therapeutic_areas', []) or []
    reasons = getattr(impact, 'hot_issue_reasons', []) or []
    is_orphan = any("희귀" in r or "Orphan" in r for r in reasons)

    if "oncology" in areas:
        return COPAY_EXEMPTION_MAP["oncology"]
    if "rare_disease" in areas or is_orphan:
        return COPAY_EXEMPTION_MAP["rare_disease"]
    return None  # 산정특례 해당 없음


def to_display_case(inn: str) -> str:
    """INN을 표시용 Title Case로 변환.

    Rules:
    - 메인 단어: 첫 글자 대문자 (Polatuzumab Vedotin)
    - 하이픈 뒤 USAN 생물학적 접미사: 소문자 (-piiq, -hrii, -csrk)

    Examples:
        "POLATUZUMAB VEDOTIN-PIIQ" → "Polatuzumab Vedotin-piiq"
        "ZANIDATAMAB-HRII" → "Zanidatamab-hrii"
        "polatuzumab vedotin" → "Polatuzumab Vedotin"
    """
    if not inn:
        return inn
    words = inn.split()
    result = []
    for word in words:
        if '-' in word:
            parts = word.split('-')
            result.append(
                parts[0].capitalize() + '-' + '-'.join(p.lower() for p in parts[1:])
            )
        else:
            result.append(word.capitalize())
    return ' '.join(result)
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_KR = datetime.now().strftime("%Y년 %m월 %d일")


# ── 약어 사전 (한국어 현지화 + 의학 약어 툴팁) ──

# (한국어_약칭 또는 None, 툴팁_풀네임)
ABBR_DICT: dict[str, tuple[str | None, str]] = {
    # 규제기관 — 한국어 약칭 우선 표기
    "MFDS": ("식약처", "식품의약품안전처, Ministry of Food and Drug Safety"),
    "HIRA": ("심평원", "건강보험심사평가원, Health Insurance Review & Assessment Service"),
    "CRIS": ("CRIS", "임상연구정보서비스, Clinical Research Information Service"),
    # 의학 약어 — 툴팁만
    "DLBCL": (None, "미만성 거대 B세포 림프종, Diffuse Large B-Cell Lymphoma"),
    "ADC": (None, "항체-약물 접합체, Antibody-Drug Conjugate"),
    "PFS": (None, "무진행생존기간, Progression-Free Survival"),
    "OS": (None, "전체생존기간, Overall Survival"),
    "ORR": (None, "객관적 반응률, Objective Response Rate"),
    "NSCLC": (None, "비소세포폐암, Non-Small Cell Lung Cancer"),
    "CAR-T": (None, "키메라 항원 수용체 T세포, Chimeric Antigen Receptor T-cell"),
    "AML": (None, "급성 골수성 백혈병, Acute Myeloid Leukemia"),
    "PAH": (None, "폐동맥 고혈압, Pulmonary Arterial Hypertension"),
    "MCL": (None, "외투세포 림프종, Mantle Cell Lymphoma"),
    "ALL": (None, "급성 림프구 백혈병, Acute Lymphoblastic Leukemia"),
    "HER2": (None, "인간 표피성장인자 수용체 2, Human Epidermal Growth Factor Receptor 2"),
    "NTRK": (None, "신경영양성 티로신 수용체 키나제, Neurotrophic Tyrosine Receptor Kinase"),
    "DMD": (None, "뒤센형 근디스트로피, Duchenne Muscular Dystrophy"),
    "PBC": (None, "원발성 담즙성 담관염, Primary Biliary Cholangitis"),
    "NME": (None, "신규 분자 실체, New Molecular Entity"),
    "BLA": (None, "생물학적 제제 허가 신청, Biologics License Application"),
    "NDA": (None, "신약 허가 신청, New Drug Application"),
}


def _md_to_html(text: str) -> str:
    """섹션 본문의 마크다운 문법을 HTML로 변환.

    지원: 불릿 리스트(- ), 마크다운 표(| |), bold(**), 줄바꿈(\\n\\n → <p>)
    """
    if not text:
        return text

    lines = text.split('\n')
    result = []
    in_list = False
    in_table = False
    table_header_done = False

    for line in lines:
        stripped = line.strip()

        # 마크다운 표
        if stripped.startswith('|') and stripped.endswith('|'):
            if not in_table:
                in_table = True
                table_header_done = False
                if in_list:
                    result.append('</ul>')
                    in_list = False
                result.append('<table class="w-full text-sm my-4 border-collapse">')
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            # 구분선(---|---) 건너뛰기
            if all(c.replace('-', '').replace(':', '') == '' for c in cells):
                table_header_done = True
                continue
            tag = 'th' if not table_header_done else 'td'
            cls = ' class="text-left px-3 py-2 border-b border-gray-200 font-semibold bg-gray-50"' if tag == 'th' else ' class="px-3 py-2 border-b border-gray-100"'
            row = ''.join(f'<{tag}{cls}>{c}</{tag}>' for c in cells)
            result.append(f'<tr>{row}</tr>')
            continue
        elif in_table:
            result.append('</table>')
            in_table = False
            table_header_done = False

        # 불릿 리스트
        if stripped.startswith('- '):
            if not in_list:
                in_list = True
                result.append('<ul class="list-disc list-inside space-y-1 my-4 text-gray-700">')
            content = stripped[2:]
            # bold 처리
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            result.append(f'<li>{content}</li>')
            continue
        elif in_list:
            result.append('</ul>')
            in_list = False

        # 일반 텍스트
        if stripped == '':
            continue
        # bold 처리
        stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
        result.append(stripped)

    if in_list:
        result.append('</ul>')
    if in_table:
        result.append('</table>')

    return ' '.join(result)


def _inject_abbr_tags(text: str, seen: set[str] | None = None) -> str:
    """텍스트에서 알려진 약어를 처리.

    - 규제기관(MFDS, HIRA): 첫 등장 → 식약처(MFDS), 이후 → 식약처 (일반 텍스트, 태그 없음)
    - 의학 약어(DLBCL, ADC 등): 첫 등장만 <abbr> 툴팁, 이후 일반 텍스트
    """
    if seen is None:
        seen = set()

    for abbr_key, (kr_short, tooltip) in ABBR_DICT.items():
        pattern = re.compile(
            r'(?<![A-Za-z0-9_(])' + re.escape(abbr_key) + r'(?![A-Za-z0-9_)>"])',
        )

        def _replace(m: re.Match, _key=abbr_key, _kr=kr_short, _tip=tooltip) -> str:
            if _key in seen:
                # 이후 등장: 일반 텍스트만
                return _kr if (_kr and _kr != _key) else _key
            seen.add(_key)
            # 첫 등장
            if _kr and _kr != _key:
                # 규제기관: 식약처(MFDS) 일반 텍스트
                return f'{_kr}({_key})'
            # 의학 약어: 첫 등장만 abbr 툴팁
            return f'<abbr title="{_tip}">{_key}</abbr>'

        text = pattern.sub(_replace, text)

    return text


def _inject_outlinks(
    text: str,
    inn: str = "",
    source_urls: dict[str, str] | None = None,
    nct_id: str = "",
    seen: set[str] | None = None,
) -> str:
    """본문 텍스트에 FDA/EMA/CT.gov 아웃링크 삽입.

    - INN 약물명 → FDA 또는 EMA 승인 페이지 (첫 등장만)
    - "FDA...승인" 컨텍스트 → FDA 출처 (첫 등장만)
    - "EMA...허가" 컨텍스트 → EMA 출처 (첫 등장만)
    - 임상시험 키워드 → CT.gov 페이지 (첫 등장만)

    seen set을 섹션 간 공유하여 전체 기사에서 각 링크 1회만 삽입.
    """
    if seen is None:
        seen = set()
    urls = source_urls or {}
    link_cls = 'class="text-indigo-600 hover:underline"'

    # 1) INN 약물명 → FDA or EMA 페이지 (첫 등장만, bold+link)
    if "inn" not in seen and inn and (urls.get("fda") or urls.get("ema")):
        url = urls.get("fda") or urls["ema"]
        # INN의 Title Case / uppercase / original 형태 모두 매칭
        variants = [re.escape(inn)]
        if inn.upper() != inn:
            variants.append(re.escape(inn.upper()))
        pattern = '|'.join(variants)
        match = re.search(pattern, text)
        if match:
            seen.add("inn")
            link = (
                f'<a href="{url}" target="_blank" '
                f'{link_cls}><strong>{match.group(0)}</strong></a>'
            )
            text = text[:match.start()] + link + text[match.end():]

    # 2) "FDA...승인" 컨텍스트 → FDA 출처 링크
    if "fda" not in seen and urls.get("fda"):
        pat = (
            r'(?:미국\s*)?(?:식품의약국\s*\(?\s*)?'
            r'FDA\)?(?:가|에서|이|의)?'
            r'(?:\s*\d{4}년?\s*\d{1,2}월(?:\s*\d{1,2}일)?)?'
            r'(?:\s*(?:정식\s*|가속\s*)?(?:승인|허가)(?:를\s*(?:완료|부여))?)?'
        )
        match = re.search(pat, text)
        if match and '<a ' not in text[max(0, match.start()-50):match.start()]:
            seen.add("fda")
            link = f'<a href="{urls["fda"]}" target="_blank" {link_cls}>{match.group(0)}</a>'
            text = text[:match.start()] + link + text[match.end():]

    # 3) "EMA...허가" 컨텍스트 → EMA 출처 링크
    if "ema" not in seen and urls.get("ema"):
        pat = (
            r'(?:유럽\s*)?(?:의약품청\s*\(?\s*)?'
            r'EMA\)?(?:가|에서|이|도|의)?'
            r'(?:\s*\d{4}년?\s*\d{1,2}월(?:\s*\d{1,2}일)?)?'
            r'(?:\s*(?:조건부\s*)?(?:승인|허가)(?:를\s*(?:완료|부여))?)?'
        )
        match = re.search(pat, text)
        if match and '<a ' not in text[max(0, match.start()-50):match.start()]:
            seen.add("ema")
            link = f'<a href="{urls["ema"]}" target="_blank" {link_cls}>{match.group(0)}</a>'
            text = text[:match.start()] + link + text[match.end():]

    # 4) 임상시험 키워드 → CT.gov 페이지
    if "ctgov" not in seen and nct_id:
        ct_url = f"https://clinicaltrials.gov/study/{nct_id}"
        patterns = [
            r'3상\s*(?:\S+\s+)?(?:임상시험|시험)',
            r'Phase\s*(?:III|3)\s*(?:\S+\s+)?(?:trial|study|시험)',
            r'임상시험\s*결과',
            r'pivotal\s*(?:trial|study)',
        ]
        combined = '|'.join(f'(?:{p})' for p in patterns)
        match = re.search(combined, text, re.IGNORECASE)
        if match and '<a ' not in text[max(0, match.start()-50):match.start()]:
            seen.add("ctgov")
            link = f'<a href="{ct_url}" target="_blank" {link_cls}>{match.group(0)}</a>'
            text = text[:match.start()] + link + text[match.end():]

    return text


def _inject_competitor_links(
    text: str,
    own_inn: str,
    competitor_inns: list[str],
    seen: set[str] | None = None,
) -> str:
    """경쟁약 INN의 첫 등장에 해당 브리핑 페이지 내부 링크 삽입.

    1순위: competitor_inns (DB 기반 경쟁약 목록)
    2순위: 전체 브리핑 파일 인덱스 (LLM이 언급했지만 DB 경쟁약 목록에 없는 약물)

    own_inn은 이미 FDA/EMA 링크가 걸려 있으므로 제외.
    각 경쟁약은 전체 기사에서 1회만 링크 (seen set 공유).
    """
    if seen is None:
        seen = set()

    link_cls = 'class="text-indigo-600 hover:underline"'
    own_lower = own_inn.lower() if own_inn else ""

    # 전체 브리핑 인덱스에서 확장된 INN 목록 구축
    all_index = _get_all_inns_index()
    # competitor_inns + 전체 인덱스에서 Title Case 복원
    all_candidates: list[tuple[str, str]] = []  # (display_inn, filename)
    added_lowers: set[str] = set()

    # 1순위: 명시적 경쟁약
    for comp_inn in (competitor_inns or []):
        if not comp_inn:
            continue
        cl = comp_inn.lower()
        if cl == own_lower or cl in added_lowers:
            continue
        added_lowers.add(cl)
        fn = all_index.get(cl, _safe_filename(comp_inn) + ".html")
        all_candidates.append((comp_inn, fn))

    # 2순위: 전체 인덱스 (본문에 등장할 수 있는 모든 약물)
    for inn_lower, fn in all_index.items():
        if inn_lower == own_lower or inn_lower in added_lowers:
            continue
        added_lowers.add(inn_lower)
        display = to_display_case(inn_lower)
        all_candidates.append((display, fn))

    # 3순위: 본문에서 ALL CAPS 약물명 패턴 탐지 (브리핑 파일 없어도 CT.gov 검색 링크)
    # 패턴: 대문자 6자 이상 단어 (약물명 특징)
    caps_pattern = re.compile(
        r'\b([A-Z][A-Z]{5,}(?:\s+[A-Z]{3,})*(?:-[a-z]{2,})?)\b'
    )
    # 임상시험 이름 감지용 컨텍스트 (POLARIX, KEYNOTE 등은 약물이 아님)
    trial_context = re.compile(r'시험|trial|study|임상|연구', re.IGNORECASE)
    for m in caps_pattern.finditer(text):
        candidate = m.group(1)
        cl = candidate.lower()
        if cl == own_lower or cl in added_lowers:
            continue
        # 약물명이 아닌 일반 약어(DLBCL, NSCLC 등) 제외
        if cl in {a.lower() for a in ABBR_DICT} or len(candidate.replace(' ', '')) < 7:
            continue
        # 임상시험 이름 제외: 앞뒤 30자에 "시험/trial/study" 있으면 스킵
        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(text), m.end() + 30)
        context = text[ctx_start:m.start()] + text[m.end():ctx_end]
        if trial_context.search(context):
            continue
        added_lowers.add(cl)
        # CT.gov 검색 링크로 연결
        ct_search = f"https://clinicaltrials.gov/search?intr={candidate.replace(' ', '+')}"
        all_candidates.append((candidate, ct_search))

    for comp_inn, comp_filename in all_candidates:
        comp_lower = comp_inn.lower()
        if comp_lower in seen:
            continue

        # Title Case / UPPER CASE / lowercase 모두 매칭
        display = to_display_case(comp_inn)
        variants = {re.escape(display)}
        if comp_inn.upper() != display:
            variants.add(re.escape(comp_inn.upper()))
        if comp_inn != display:
            variants.add(re.escape(comp_inn))
        pattern = '|'.join(variants)

        match = re.search(pattern, text)
        if match:
            # 이미 <a> 태그 안에 있으면 건너뛰기
            pre = text[max(0, match.start() - 80):match.start()]
            if '<a ' in pre and '</a>' not in pre:
                continue
            seen.add(comp_lower)
            # 외부 URL(https://)이면 target="_blank", 내부 파일이면 그냥 링크
            if comp_filename.startswith("http"):
                link = f'<a href="{comp_filename}" target="_blank" {link_cls}>{match.group(0)}</a>'
            else:
                link = f'<a href="{comp_filename}" {link_cls}>{match.group(0)}</a>'
            text = text[:match.start()] + link + text[match.end():]

    return text


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
        abbr {{ text-decoration: none; border-bottom: 1px dashed #9ca3af; cursor: help; }}
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
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">{global_heading}</h2>
            <div class="mb-6">{global_section}</div>
            {timeline_html}
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">{domestic_heading}</h2>
            <div class="mb-6">{domestic_section}</div>
            <div class="my-10 p-6 bg-indigo-50 rounded-xl border border-indigo-100">
                <h4 class="meta-text text-sm font-semibold text-indigo-600 mb-3">메드클레임 시사점</h4>
                <div class="space-y-3 text-gray-800"><p>{medclaim_section}</p></div>
            </div>
        </article>
        <footer class="mt-16 pt-8 border-t border-gray-200 meta-text text-sm text-gray-500">
            <div class="mb-4">
                <strong>데이터 출처:</strong> {sources_html}
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


def _build_timeline_html(source_data: dict | None, source_urls: dict[str, str] | None = None) -> str:
    """승인 타임라인 HTML 생성 (출처 하이퍼링크 포함)"""
    if not source_data:
        return ""
    urls = source_urls or {}

    entries = []
    # 호환 레이어: 플랫 구조(fda_approved)도 중첩 구조(fda.approved)로 변환
    fda = source_data.get("fda") or {
        "approved": source_data.get("fda_approved"),
        "date": source_data.get("fda_date"),
    }
    ema = source_data.get("ema") or {
        "approved": source_data.get("ema_approved"),
        "date": source_data.get("ema_date"),
    }
    mfds = source_data.get("mfds") or {
        "approved": source_data.get("mfds_approved"),
        "date": source_data.get("mfds_date"),
        "brand_name": source_data.get("mfds_brand_name"),
    }

    if fda.get("approved") and fda.get("date"):
        entries.append(("blue", fda["date"], "FDA 승인", "Approved", urls.get("fda", "")))
    if ema.get("approved") and ema.get("date"):
        entries.append(("yellow", ema["date"], "EMA 승인", "Authorised", urls.get("ema", "")))
    if mfds.get("approved") and mfds.get("date"):
        brand = mfds.get("brand_name", "")
        entries.append(("green", mfds["date"], "식약처(MFDS) 허가", brand or "Approved", urls.get("mfds", "")))

    if not entries:
        return ""

    items_html = ""
    for color, date, label, desc, url in entries:
        if url:
            label_html = f'<a href="{url}" target="_blank" class="hover:underline">{label}</a>'
        else:
            label_html = label
        items_html += f"""
                    <div class="relative flex items-center mb-6">
                        <div class="timeline-dot bg-{color}-500 z-10"></div>
                        <div class="ml-6">
                            <div class="meta-text text-xs text-{color}-600 font-semibold">{date}</div>
                            <div class="font-medium">{label_html}</div>
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


def _build_sources_html(source_urls: dict[str, str] | None = None, nct_id: str = "") -> str:
    """동적 출처 링크 HTML 생성"""
    urls = source_urls or {}
    links = []

    if urls.get("fda"):
        links.append(f'<a href="{urls["fda"]}" target="_blank" class="text-indigo-500 hover:underline">FDA Drug Approval</a>')
    else:
        links.append("FDA Drug Approvals Database")

    if urls.get("ema"):
        links.append(f'<a href="{urls["ema"]}" target="_blank" class="text-indigo-500 hover:underline">EMA Assessment Report</a>')
    else:
        links.append("EMA Public Assessment Reports")

    if nct_id:
        ct_url = f"https://clinicaltrials.gov/study/{nct_id}"
        links.append(f'<a href="{ct_url}" target="_blank" class="text-indigo-500 hover:underline">ClinicalTrials.gov ({nct_id})</a>')

    links.append("식약처(MFDS) 의약품통합정보시스템")
    links.append("심평원(HIRA) 건강보험심사평가원")

    return ", ".join(links)


def _build_flags_html(source_data: dict | None) -> str:
    if not source_data:
        return ""
    # 호환 레이어: 플랫 구조도 지원
    fda = source_data.get("fda") or {"approved": source_data.get("fda_approved")}
    ema = source_data.get("ema") or {"approved": source_data.get("ema_approved")}
    mfds = source_data.get("mfds") or {"approved": source_data.get("mfds_approved")}
    parts = []
    if fda.get("approved"):
        parts.append('<span>FDA</span>')
    if ema.get("approved"):
        parts.append('<span class="mx-2">EMA</span>')
    if mfds.get("approved"):
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


def _normalize_inn_in_text(text: str, inn_variants: list[str], display: str) -> str:
    """텍스트에서 INN의 ALL CAPS/lowercase 변형을 Title Case로 강제 치환.

    inn_variants: [원본 INN, uppercase, lowercase] 등 가능한 변형 목록
    display: 표시할 Title Case 문자열
    """
    for variant in inn_variants:
        if variant != display and variant in text:
            text = text.replace(variant, display)
    return text


def _build_all_inns_index() -> dict[str, str]:
    """출력 디렉토리의 모든 브리핑 JSON에서 INN→파일명 인덱스 구축.

    Returns: {inn_lower: safe_filename.html}
    """
    index: dict[str, str] = {}
    for jf in OUTPUT_DIR.glob("*.json"):
        if jf.name.startswith("hot_issues_") or jf.name.startswith("all_articles_"):
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            inn = data.get("inn", "")
            if inn:
                index[inn.lower()] = _safe_filename(inn) + ".html"
        except Exception:
            continue
    return index


# 모듈 레벨 캐시 (render-only 시 1회만 구축)
_ALL_INNS_INDEX: dict[str, str] | None = None


def _get_all_inns_index() -> dict[str, str]:
    global _ALL_INNS_INDEX
    if _ALL_INNS_INDEX is None:
        _ALL_INNS_INDEX = _build_all_inns_index()
    return _ALL_INNS_INDEX


def generate_article_html(
    report_data: dict,
    score: int = 0,
    source_urls: dict[str, str] | None = None,
    nct_id: str = "",
    known_inns: list[str] | None = None,
) -> str:
    """BriefingReport JSON → HTML 기사"""
    inn = to_display_case(report_data.get("inn", ""))
    headline = report_data.get("headline", f"{inn} 규제 동향 브리핑")
    subtitle = report_data.get("subtitle", "")
    key_points = report_data.get("key_points", [])
    global_section = report_data.get("global_section", "")
    domestic_section = report_data.get("domestic_section", "")
    medclaim_section = report_data.get("medclaim_section", "")
    global_heading = report_data.get("global_heading", "글로벌 승인 현황")
    domestic_heading = report_data.get("domestic_heading", "국내 도입 전망")
    source_data = report_data.get("source_data")

    badge_class, score_label, _ = _score_badge(score)

    # INN 대소문자 강제 정규화 (LLM 출력 불신)
    all_inns = set(known_inns or [])
    all_inns.add(report_data.get("inn", ""))
    for inn_raw in all_inns:
        if not inn_raw:
            continue
        display = to_display_case(inn_raw)
        variants = {inn_raw, inn_raw.upper(), inn_raw.lower()}
        variants.discard(display)
        headline = _normalize_inn_in_text(headline, list(variants), display)
        subtitle = _normalize_inn_in_text(subtitle, list(variants), display)
        global_section = _normalize_inn_in_text(global_section, list(variants), display)
        domestic_section = _normalize_inn_in_text(domestic_section, list(variants), display)
        medclaim_section = _normalize_inn_in_text(medclaim_section, list(variants), display)
        key_points = [_normalize_inn_in_text(kp, list(variants), display) for kp in key_points]

    # 약어 → <abbr> 태그 주입 (콘텐츠 섹션에만, seen 공유로 첫등장 추적)
    abbr_seen: set[str] = set()
    headline = _inject_abbr_tags(headline, abbr_seen)
    subtitle = _inject_abbr_tags(subtitle, abbr_seen)

    key_points_html = ""
    for kp in key_points:
        kp = _inject_abbr_tags(kp, abbr_seen)
        key_points_html += f"""
                <li class="flex items-start">
                    <span class="text-red-500 mr-2">&#x25B8;</span>
                    <span>{kp}</span>
                </li>"""

    global_section = _inject_abbr_tags(global_section, abbr_seen)
    domestic_section = _inject_abbr_tags(domestic_section, abbr_seen)
    medclaim_section = _inject_abbr_tags(medclaim_section, abbr_seen)

    # 본문 인라인 아웃링크 (INN→FDA/EMA, FDA/EMA 컨텍스트→출처, 임상시험→CT.gov)
    outlink_seen: set[str] = set()
    global_section = _inject_outlinks(
        global_section, inn=inn, source_urls=source_urls,
        nct_id=nct_id, seen=outlink_seen,
    )
    domestic_section = _inject_outlinks(
        domestic_section, inn=inn, source_urls=source_urls,
        nct_id=nct_id, seen=outlink_seen,
    )
    medclaim_section = _inject_outlinks(
        medclaim_section, inn=inn, source_urls=source_urls,
        nct_id=nct_id, seen=outlink_seen,
    )

    # 경쟁약 내부 링크 (경쟁약 INN → 해당 브리핑 페이지)
    comp_seen: set[str] = set()
    global_section = _inject_competitor_links(global_section, inn, known_inns or [], comp_seen)
    domestic_section = _inject_competitor_links(domestic_section, inn, known_inns or [], comp_seen)
    medclaim_section = _inject_competitor_links(medclaim_section, inn, known_inns or [], comp_seen)

    # 마크다운 → HTML 변환 (표, 불릿 등)
    global_section = _md_to_html(global_section)
    domestic_section = _md_to_html(domestic_section)
    medclaim_section = _md_to_html(medclaim_section)

    timeline_html = _build_timeline_html(source_data, source_urls=source_urls)
    tag_badges = _build_tag_badges(source_data)
    sources_html = _build_sources_html(source_urls=source_urls, nct_id=nct_id)

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
        global_heading=global_heading,
        global_section=global_section,
        domestic_heading=domestic_heading,
        domestic_section=domestic_section,
        medclaim_section=medclaim_section,
        timeline_html=timeline_html,
        sources_html=sources_html,
    )


# ═══════════════════════════════════════════════════════
# V4: Jinja2 HTML 템플릿 — 팩트/인사이트 분리 렌더링
# ═══════════════════════════════════════════════════════

ARTICLE_TEMPLATE_V4 = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RegScan 브리핑 - {{ inn }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');
        body { font-family: 'Noto Serif KR', serif; background: #fafafa; }
        .report-title { font-family: 'Noto Serif KR', serif; font-weight: 700; }
        .report-body { font-family: 'Noto Serif KR', serif; line-height: 1.9; font-size: 17px; }
        .meta-text { font-family: 'Inter', sans-serif; }
        .highlight-box { border-left: 4px solid #dc2626; background: linear-gradient(90deg, #fef2f2 0%, #ffffff 100%); }
        .timeline-dot { width: 12px; height: 12px; border-radius: 50%; }
        .fact-table { width: 100%; text-align: left; font-size: 0.875rem; margin: 1rem 0; border-collapse: collapse; }
        .fact-table th { padding: 0.5rem 0.75rem; border-bottom: 1px solid #e5e7eb; font-weight: 600; background: #f9fafb; }
        .fact-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #f3f4f6; }
        abbr { text-decoration: none; border-bottom: 1px dashed #9ca3af; cursor: help; }
    </style>
</head>
<body class="min-h-screen">
    <header class="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div class="max-w-4xl mx-auto px-6 py-4">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <a href="index.html" class="text-xl font-bold text-gray-900 hover:text-indigo-600">MedClaim</a>
                    <span class="text-gray-300">|</span>
                    <span class="text-sm text-gray-500 meta-text">RegScan 브리핑 V4</span>
                </div>
                <div class="meta-text text-sm text-gray-500">{{ date_kr }}</div>
            </div>
        </div>
    </header>
    <main class="max-w-4xl mx-auto px-6 py-10">
        <div class="flex items-center space-x-3 mb-6 meta-text">
            <span class="px-3 py-1 {{ score_badge_class }} text-white text-xs font-semibold rounded">{{ score_label }}</span>
            {{ tag_badges }}
        </div>
        <h1 class="report-title text-4xl text-gray-900 mb-4 leading-tight">{{ headline }}</h1>
        <p class="text-xl text-gray-600 mb-8 leading-relaxed">{{ subtitle }}</p>
        <div class="flex items-center space-x-4 mb-10 pb-10 border-b border-gray-200 meta-text">
            <div class="flex items-center space-x-2">
                <div class="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center">
                    <span class="text-indigo-600 text-xs font-bold">AI</span>
                </div>
                <span class="text-sm text-gray-600">RegScan AI 리포터</span>
            </div>
            <span class="text-gray-300">&middot;</span>
            <span class="text-sm text-gray-500">Hot Issue Score: {{ score }}</span>
        </div>

        <!-- 핵심 요약 (인사이트) -->
        <div class="highlight-box p-6 rounded-r-lg mb-10">
            <h3 class="font-bold text-gray-900 mb-3 meta-text text-sm">핵심 요약</h3>
            <ul class="space-y-2 text-gray-800">{{ key_points_html }}</ul>
        </div>

        <article class="report-body text-gray-800">
            <!-- 글로벌 섹션: 팩트 테이블 + 인사이트 -->
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">글로벌 승인 현황</h2>
            {% if approval_summary_table_html %}
            <div class="my-4">{{ approval_summary_table_html }}</div>
            {% endif %}
            <div class="mb-6">{{ global_insight_text }}</div>

            <!-- 타임라인 (팩트) -->
            {{ timeline_html }}

            <!-- 국내 섹션: 인사이트 -->
            <h2 class="text-2xl font-bold text-gray-900 mt-10 mb-4">국내 도입 전망</h2>
            {% if d_day_text %}
            <div class="my-4 p-3 bg-gray-50 rounded-lg text-sm text-gray-600 meta-text">
                <strong>경과:</strong> {{ d_day_text }}
            </div>
            {% endif %}
            <div class="mb-6">{{ domestic_insight_text }}</div>

            <!-- 메드클레임: 비용표(팩트) + 인사이트 -->
            <div class="my-10 p-6 bg-indigo-50 rounded-xl border border-indigo-100">
                <h4 class="meta-text text-sm font-semibold text-indigo-600 mb-3">메드클레임 시사점</h4>
                {% if cost_scenario_table_html %}
                <div class="my-4">{{ cost_scenario_table_html }}</div>
                {% endif %}
                <div class="space-y-3 text-gray-800"><p>{{ medclaim_action_text }}</p></div>
            </div>
        </article>

        <footer class="mt-16 pt-8 border-t border-gray-200 meta-text text-sm text-gray-500">
            <div class="mb-4">
                <strong>데이터 출처:</strong> {{ sources_html }}
            </div>
            <div class="text-xs text-gray-400">
                본 리포트는 RegScan AI V4가 공개 데이터를 기반으로 자동 생성한 브리핑 자료입니다.
                팩트(날짜·금액·상태)는 Python이 사전 계산하였으며, 인사이트(분석)는 LLM이 생성했습니다.
                마지막 업데이트: {{ date }}
            </div>
        </footer>
    </main>
</body>
</html>"""


def generate_article_html_v4(
    facts: dict,
    insights: dict,
    score: int = 0,
    source_urls: dict[str, str] | None = None,
    nct_id: str = "",
    known_inns: list[str] | None = None,
) -> str:
    """V4: 팩트(Python) + 인사이트(LLM) → Jinja2 렌더링 HTML 기사"""
    from jinja2 import Environment, BaseLoader

    inn = to_display_case(facts.get("inn", ""))

    # ── 인사이트 텍스트 후처리 (abbr, outlink, competitor, md→html) ──
    abbr_seen: set[str] = set()
    outlink_seen: set[str] = set()
    comp_seen: set[str] = set()
    comp_inns = known_inns or []

    headline = insights.get("headline", f"{inn} 규제 동향 브리핑")
    subtitle = insights.get("subtitle", "")

    # INN 대소문자 정규화
    all_inns = set(comp_inns)
    all_inns.add(facts.get("inn", ""))
    for inn_raw in all_inns:
        if not inn_raw:
            continue
        display = to_display_case(inn_raw)
        variants = {inn_raw, inn_raw.upper(), inn_raw.lower()}
        variants.discard(display)
        headline = _normalize_inn_in_text(headline, list(variants), display)
        subtitle = _normalize_inn_in_text(subtitle, list(variants), display)

    headline = _inject_abbr_tags(headline, abbr_seen)
    subtitle = _inject_abbr_tags(subtitle, abbr_seen)

    # key_points
    key_points = insights.get("key_points", [])
    key_points_html = ""
    for kp in key_points:
        for inn_raw in all_inns:
            if not inn_raw:
                continue
            display = to_display_case(inn_raw)
            variants = {inn_raw, inn_raw.upper(), inn_raw.lower()}
            variants.discard(display)
            kp = _normalize_inn_in_text(kp, list(variants), display)
        kp = _inject_abbr_tags(kp, abbr_seen)
        key_points_html += f"""
                <li class="flex items-start">
                    <span class="text-red-500 mr-2">&#x25B8;</span>
                    <span>{kp}</span>
                </li>"""

    # 인사이트 텍스트 필드 후처리
    processed_insights = {}
    for field in ("global_insight_text", "domestic_insight_text", "medclaim_action_text"):
        text = insights.get(field, "")
        # INN 정규화
        for inn_raw in all_inns:
            if not inn_raw:
                continue
            display = to_display_case(inn_raw)
            variants = {inn_raw, inn_raw.upper(), inn_raw.lower()}
            variants.discard(display)
            text = _normalize_inn_in_text(text, list(variants), display)
        text = _inject_abbr_tags(text, abbr_seen)
        text = _inject_outlinks(
            text, inn=inn, source_urls=source_urls,
            nct_id=nct_id, seen=outlink_seen,
        )
        text = _inject_competitor_links(text, inn, comp_inns, comp_seen)
        text = _md_to_html(text)
        processed_insights[field] = text

    # ── 팩트 HTML 생성 ──
    # 승인 요약 테이블 (마크다운→HTML)
    approval_table_md = facts.get("approval_summary_table", "")
    approval_summary_table_html = _md_to_html(approval_table_md) if approval_table_md else ""

    # 비용 시나리오 테이블 (마크다운→HTML)
    cost_table_md = facts.get("cost_scenario_table", "")
    cost_scenario_table_html = _md_to_html(cost_table_md) if cost_table_md else ""

    # 타임라인 HTML (기존 함수 활용)
    source_data = facts.get("source_data") or {}
    timeline_html = _build_timeline_html(source_data, source_urls=source_urls)

    # d_day_text
    d_day_text = facts.get("d_day_text", "")

    # 스코어 배지
    badge_class, score_label, _ = _score_badge(score)
    tag_badges = _build_tag_badges(source_data)
    sources_html = _build_sources_html(source_urls=source_urls, nct_id=nct_id)

    # ── Jinja2 렌더링 ──
    env = Environment(loader=BaseLoader(), autoescape=False)
    template = env.from_string(ARTICLE_TEMPLATE_V4)
    return template.render(
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
        approval_summary_table_html=approval_summary_table_html,
        global_insight_text=processed_insights.get("global_insight_text", ""),
        timeline_html=timeline_html,
        d_day_text=d_day_text,
        domestic_insight_text=processed_insights.get("domestic_insight_text", ""),
        cost_scenario_table_html=cost_scenario_table_html,
        medclaim_action_text=processed_insights.get("medclaim_action_text", ""),
        sources_html=sources_html,
    )


def generate_index_html(articles: list[dict]) -> str:
    """인덱스 페이지 HTML 생성"""
    cards = ""
    for art in articles:
        inn = to_display_case(art["inn"])
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


async def _fetch_ctgov_results_batch(inns: list[str]) -> dict:
    """CT.gov에서 약물 INN 목록의 임상 결과를 배치 조회 (단계적 확장)

    단계적 조회 전략:
    1) Phase 3 + 결과 있음 (page_size=5)
    2) Phase 3 + 결과 없음 (enrolled > 0인 주요 시험)
    3) Phase 2 + 결과 있음 (Phase 3가 없는 약물용)

    Returns:
        {normalized_inn: {"clinical_results": {...}, "nct_id": "..."}}
    """
    from regscan.ingest.clinicaltrials import ClinicalTrialsGovClient
    from regscan.parse.clinicaltrials_parser import ClinicalTrialsGovParser
    from regscan.map.matcher import IngredientMatcher

    cache: dict[str, dict] = {}
    matcher = IngredientMatcher()
    parser = ClinicalTrialsGovParser()

    async with ClinicalTrialsGovClient(timeout=15.0) as client:
        for inn in inns:
            norm = matcher.normalize(inn)
            if norm in cache:
                continue

            found = False

            # Stage 1: Phase 3 + 결과 있음 (가장 신뢰도 높은 데이터)
            try:
                studies = await client.search_by_intervention(
                    inn, phase="PHASE3", has_results=True, page_size=5,
                )
                for s in studies:
                    parsed = parser.parse_study(s)
                    cr = parsed.get("clinical_results")
                    if cr and cr.get("primary_outcomes"):
                        cache[norm] = {
                            "clinical_results": cr,
                            "nct_id": parsed["nct_id"],
                        }
                        found = True
                        break
            except Exception as e:
                logger.debug("CT.gov Stage 1 실패 (%s): %s", inn, e)

            if found:
                continue

            # Stage 2: Phase 3 + 결과 없음 (대형 시험 메타데이터라도 확보)
            try:
                studies = await client.search_by_intervention(
                    inn, phase="PHASE3", has_results=False, page_size=5,
                )
                for s in studies:
                    parsed = parser.parse_study(s)
                    # 결과가 없어도 enrollment + conditions 정보 활용
                    if parsed.get("enrollment", 0) >= 50:
                        cache[norm] = {
                            "clinical_results": {
                                "primary_outcomes": [],
                                "secondary_outcomes": [],
                                "adverse_events": None,
                                "trial_metadata": {
                                    "nct_id": parsed["nct_id"],
                                    "title": parsed.get("title", ""),
                                    "enrollment": parsed.get("enrollment", 0),
                                    "status": parsed.get("status", ""),
                                    "conditions": parsed.get("conditions", []),
                                },
                            },
                            "nct_id": parsed["nct_id"],
                        }
                        found = True
                        break
            except Exception as e:
                logger.debug("CT.gov Stage 2 실패 (%s): %s", inn, e)

            if found:
                continue

            # Stage 3: Phase 2 + 결과 있음 (Phase 3가 없는 초기 약물용)
            try:
                studies = await client.search_by_intervention(
                    inn, phase="PHASE2", has_results=True, page_size=5,
                )
                for s in studies:
                    parsed = parser.parse_study(s)
                    cr = parsed.get("clinical_results")
                    if cr and cr.get("primary_outcomes"):
                        cache[norm] = {
                            "clinical_results": cr,
                            "nct_id": parsed["nct_id"],
                        }
                        break
            except Exception as e:
                logger.debug("CT.gov Stage 3 실패 (%s): %s", inn, e)

    logger.info("CT.gov 임상 결과 조회: %d/%d건 확보", len(cache), len(inns))
    return cache


async def load_drugs_from_db(
    top_n: int = 20,
    min_score: int = 40,
    ctgov_results_cache: dict | None = None,
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

        # area → [(inn, score, domestic_status)] 매핑 (primary area만 사용)
        area_index: dict[str, list[dict]] = {}
        for row in all_rows:
            areas = row.therapeutic_areas.split(",") if row.therapeutic_areas else []
            primary_area = areas[0].strip() if areas else ""
            if not primary_area:
                continue
            area_index.setdefault(primary_area, []).append({
                "inn": row.inn,
                "score": row.global_score,
                "domestic_status": row.domestic_status or "",
                "therapeutic_areas": row.therapeutic_areas or "",
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

            # ── 3) 이벤트 → RegulatoryApproval + 적응증 추출 + source_url ──
            indication_parts = []
            source_urls: dict[str, str] = {}  # agency → source_url
            for ev in drug.events:
                approval = RegulatoryApproval(
                    agency=ev.agency.upper(),
                    status=(ApprovalStatus.APPROVED if ev.status == "approved"
                            else ApprovalStatus.PENDING),
                    approval_date=ev.approval_date,
                    brand_name=ev.brand_name or "",
                )
                # source_url: DB 값 우선, 없으면 raw_data에서 결정적 생성
                if ev.source_url:
                    source_urls[ev.agency] = ev.source_url
                elif ev.raw_data and isinstance(ev.raw_data, dict):
                    if ev.agency == "fda":
                        app_no = ev.raw_data.get("application_number", "")
                        if app_no:
                            source_urls["fda"] = f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={app_no.replace('BLA', '').replace('NDA', '')}"
                    elif ev.agency == "ema":
                        ema_name = ev.raw_data.get("name_of_medicine", "")
                        if ema_name:
                            source_urls["ema"] = f"https://www.ema.europa.eu/en/medicines/human/EPAR/{ema_name.lower().replace(' ', '-')}"
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

            # source_url을 impact에 전달
            impact._source_urls = source_urls

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

            # ── 4.5) CT.gov 임상 결과 조회 ──
            if ctgov_results_cache is not None and norm_inn in ctgov_results_cache:
                impact.clinical_results = ctgov_results_cache[norm_inn]["clinical_results"]
                impact.clinical_results_nct_id = ctgov_results_cache[norm_inn]["nct_id"]

            # ── 4.6) 한계점(Limitations) 자동 추출 → LLM에 전달 ──
            _limitations_parts: list[str] = []
            if impact.clinical_results:
                cr = impact.clinical_results
                auto_lims = cr.get("limitations", [])
                if auto_lims:
                    _limitations_parts.extend(auto_lims)
            if _limitations_parts:
                impact._limitations_text = " ".join(_limitations_parts)

            # ── 5) 경쟁약 주입 ──
            # EMA therapeutic_area가 있으면 이를 우선 사용 (더 구체적)
            # 없으면 DB therapeutic_areas 사용
            competitors = []
            seen = {drug.inn}

            # 5-a) EMA therapeutic_area 기반 (같은 EMA 분류 + 적응증 키워드 오버랩)
            if ema_ta:
                # 대상 약물의 적응증 키워드 집합 (소문자, 3자 이상 단어)
                _target_ind_words = set()
                if ema_indication:
                    _target_ind_words = {
                        w.lower() for w in re.split(r'[\s,;/()]+', ema_indication)
                        if len(w) >= 3 and w.isalpha()
                    }

                for other_inn, other_info in ema_index.items():
                    if other_info.get("therapeutic_area", "") == ema_ta:
                        # 적응증 키워드 오버랩 필터: 최소 2단어 공통
                        comp_indication = other_info.get("indication", "")
                        if _target_ind_words and comp_indication:
                            comp_words = {
                                w.lower() for w in re.split(r'[\s,;/()]+', comp_indication)
                                if len(w) >= 3 and w.isalpha()
                            }
                            overlap = _target_ind_words & comp_words
                            if len(overlap) < 2:
                                continue

                        # DB에서 해당 약물 score 조회
                        for area_list in area_index.values():
                            for comp in area_list:
                                if matcher.normalize(comp["inn"]) == other_inn:
                                    if comp["inn"] not in seen:
                                        seen.add(comp["inn"])
                                        comp_with_indication = dict(comp)
                                        if comp_indication:
                                            comp_with_indication["indication"] = comp_indication[:200]
                                        # mechanism_class 추가 (pharmacotherapeutic_group 기반)
                                        comp_ptg = other_info.get("pharmacotherapeutic_group", "")
                                        if comp_ptg:
                                            comp_with_indication["mechanism_class"] = comp_ptg
                                        competitors.append(comp_with_indication)

            # 5-b) DB therapeutic_area 폴백 (primary area 기반)
            target_primary = (
                status.therapeutic_areas[0].strip()
                if status.therapeutic_areas else ""
            )
            if len(competitors) < 3 and target_primary:
                for comp in area_index.get(target_primary, []):
                    if comp["inn"] in seen:
                        continue
                    # primary area가 동일한 약물만 매칭
                    comp_areas = comp.get("therapeutic_areas", "").split(",")
                    comp_primary = comp_areas[0].strip() if comp_areas else ""
                    if comp_primary != target_primary:
                        continue
                    seen.add(comp["inn"])
                    # EMA 인덱스에서 추가 맥락 보강
                    comp_enriched = dict(comp)
                    comp_norm = matcher.normalize(comp["inn"])
                    comp_ema = ema_index.get(comp_norm, {})
                    if not comp_ema and '-' in comp_norm:
                        comp_ema = ema_index.get(comp_norm.rsplit('-', 1)[0], {})
                    if comp_ema:
                        if comp_ema.get("indication") and "indication" not in comp_enriched:
                            comp_enriched["indication"] = comp_ema["indication"][:200]
                        if comp_ema.get("pharmacotherapeutic_group"):
                            comp_enriched["mechanism_class"] = comp_ema["pharmacotherapeutic_group"]
                    competitors.append(comp_enriched)

            # score 내림차순 정렬 후 상위 5개, INN Title Case 정규화
            competitors.sort(key=lambda x: x["score"], reverse=True)
            for comp in competitors:
                comp["inn"] = to_display_case(comp["inn"])
            impact._competitors = competitors[:5]

            # ── 6) 산정특례 카테고리 주입 ──
            impact._copay_exemption = _get_copay_exemption(impact)

            impacts.append(impact)

    return impacts


async def _run_render_only():
    """기존 JSON 파일에서 HTML만 재렌더링 (LLM·DB 호출 없음, ~2초)"""
    logger.info("=== HTML 재렌더 모드 (render-only) ===")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted(OUTPUT_DIR.glob("*.json"))
    # hot_issues_*.json, all_articles_*.json 등 비 브리핑 파일 제외
    json_files = [
        f for f in json_files
        if not f.name.startswith("hot_issues_") and not f.name.startswith("all_articles_")
    ]

    if not json_files:
        logger.error("재렌더할 JSON 파일 없음: %s", OUTPUT_DIR)
        return

    articles_meta = []
    rendered = 0

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("  JSON 파싱 실패 (%s): %s", jf.name, e)
            continue

        if not isinstance(data, dict):
            continue

        inn = data.get("inn", "")
        if not inn:
            continue

        # 저장된 메타데이터 복원 (없으면 기본값)
        score = data.get("_score", 0)
        source_urls = data.get("_source_urls") or {}
        nct_id = data.get("_nct_id", "")
        hot_issue_reasons = data.get("_hot_issue_reasons", [])
        therapeutic_areas = data.get("_therapeutic_areas", [])
        known_inns = data.get("_known_inns", [])

        # source_data 복원
        source_data = data.get("source_data") or {}
        source_data["analysis"] = {"hot_issue_reasons": hot_issue_reasons}
        source_data["therapeutic_areas"] = therapeutic_areas

        pipeline_version = data.get("_pipeline_version", "v3")

        if pipeline_version == "v4":
            v4_facts = data.get("_v4_facts", {})
            facts = {
                "inn": inn,
                "source_data": source_data,
                "d_day_text": v4_facts.get("d_day_text", ""),
                "approval_summary_table": v4_facts.get("approval_summary_table", ""),
                "cost_scenario_table": v4_facts.get("cost_scenario_table", ""),
            }
            insights = {
                "headline": data.get("headline", ""),
                "subtitle": data.get("subtitle", ""),
                "key_points": data.get("key_points", []),
                "global_insight_text": data.get("global_section", ""),
                "domestic_insight_text": data.get("domestic_section", ""),
                "medclaim_action_text": data.get("medclaim_section", ""),
            }
            html_content = generate_article_html_v4(
                facts, insights, score=score,
                source_urls=source_urls, nct_id=nct_id,
                known_inns=known_inns,
            )
        else:
            report_data = {
                "inn": inn,
                "headline": data.get("headline", ""),
                "subtitle": data.get("subtitle", ""),
                "key_points": data.get("key_points", []),
                "global_section": data.get("global_section", ""),
                "domestic_section": data.get("domestic_section", ""),
                "medclaim_section": data.get("medclaim_section", ""),
                "source_data": source_data,
            }
            html_content = generate_article_html(
                report_data, score=score,
                source_urls=source_urls, nct_id=nct_id,
                known_inns=known_inns,
            )
        html_path = OUTPUT_DIR / f"{_safe_filename(inn)}.html"
        html_path.write_text(html_content, encoding="utf-8")
        rendered += 1

        # 인덱스용 메타
        articles_meta.append({
            "inn": inn,
            "score": score,
            "headline": data.get("headline", ""),
            "key_points": data.get("key_points", []),
            "status_label": "",
            "source_data": source_data,
            "html_file": str(html_path.name),
        })

    # 인덱스 페이지 재생성
    articles_meta.sort(key=lambda x: x["score"], reverse=True)
    index_html = generate_index_html(articles_meta)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    logger.info("=== 재렌더 완료: %d건 HTML 생성 ===", rendered)
    print(f"\n  render-only 완료: {rendered}건 HTML 재생성")


async def run_publish(
    top_n: int = 20,
    min_score: int = 40,
    skip_llm: bool = False,
    render_only: bool = False,
    use_v4: bool = False,
):
    """기사 발행 메인 로직"""
    from regscan.report.llm_generator import LLMBriefingGenerator, BriefingReport
    from regscan.db.loader import DBLoader

    # ── render-only 모드: 기존 JSON → HTML 재렌더 (LLM·DB 없이) ──
    if render_only:
        return await _run_render_only()

    pipeline_ver = "V4 (팩트/인사이트 분리)" if use_v4 else "V3"
    logger.info("=== 기사 발행 시작 [%s] ===", pipeline_ver)
    logger.info("  대상: score >= %d, 최대 %d건", min_score, top_n)

    # ── HIRA 가격 스펙트럼 사전 구축 (변경 시에만 재계산) ──
    try:
        from regscan.report.price_stats import check_and_rebuild_if_needed
        rebuilt = check_and_rebuild_if_needed()
        if rebuilt:
            logger.info("  HIRA 가격 스펙트럼 재구축 완료")
    except Exception as e:
        logger.warning("  HIRA 가격 스펙트럼 구축 실패 (무시): %s", e)

    # CT.gov 임상 결과 사전 조회 (기사 품질 향상)
    logger.info("  CT.gov 임상 결과 사전 조회...")
    from regscan.db.database import init_db, get_async_session
    from regscan.db.models import DrugDB
    from sqlalchemy import select as _sel

    await init_db()
    async with get_async_session()() as _sess:
        _stmt = (
            _sel(DrugDB.inn)
            .where(DrugDB.global_score >= min_score)
            .order_by(DrugDB.global_score.desc())
            .limit(top_n)
        )
        _res = await _sess.execute(_stmt)
        _inns = [r[0] for r in _res.all()]

    ctgov_cache = await _fetch_ctgov_results_batch(_inns)

    impacts = await load_drugs_from_db(
        top_n=top_n, min_score=min_score,
        ctgov_results_cache=ctgov_cache,
    )
    if not impacts:
        logger.error("발행 대상 약물 없음")
        return

    logger.info("  DB 로드: %d건", len(impacts))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generator = LLMBriefingGenerator(provider="openai", model="gpt-5.2")
    loader = DBLoader()
    articles_meta = []
    generated = 0
    failed = 0
    skipped = 0

    # ── 1단계: LLM 브리핑 병렬 생성 ──
    sem = asyncio.Semaphore(10)
    results: list[tuple] = []

    async def _gen_one(idx: int, impact):
        safe_name = _safe_filename(impact.inn)
        json_path = OUTPUT_DIR / f"{safe_name}.json"

        if skip_llm and json_path.exists():
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
                logger.info("  [%d/%d] %s — 기존 JSON 로드", idx, len(impacts), impact.inn)
                return impact, report, "skipped"
            except Exception as e:
                logger.warning("  [%d/%d] %s — JSON 로드 실패: %s", idx, len(impacts), impact.inn, e)
                return impact, None, "failed"

        async with sem:
            try:
                logger.info("  [%d/%d] %s (score=%d) — LLM 브리핑 생성 중... [%s]",
                           idx, len(impacts), impact.inn, impact.global_score,
                           pipeline_ver)
                if use_v4:
                    report = await generator.generate_v4(impact)
                else:
                    report = await generator.generate(impact)
                try:
                    await loader.save_briefing(report)
                except Exception as e:
                    logger.debug("  DB 저장 건너뜀: %s", e)
                return impact, report, "generated"
            except Exception as e:
                logger.warning("  [%d/%d] %s — 브리핑 생성 실패: %s", idx, len(impacts), impact.inn, e)
                return impact, None, "failed"

    tasks = [_gen_one(i, imp) for i, imp in enumerate(impacts, 1)]
    batch_results = await asyncio.gather(*tasks)

    # ── 2단계: HTML/JSON 저장 (순차) ──
    for impact, report, status in batch_results:
        if status == "skipped":
            skipped += 1
        elif status == "generated":
            generated += 1
        else:
            failed += 1
            continue

        if report is None:
            continue

        safe_name = _safe_filename(impact.inn)
        json_path = OUTPUT_DIR / f"{safe_name}.json"
        html_path = OUTPUT_DIR / f"{safe_name}.html"

        # HTML 기사 생성
        report_data = report.to_dict()
        report_data["source_data"] = impact.to_dict()
        report_data["source_data"]["analysis"] = {
            "hot_issue_reasons": getattr(impact, 'hot_issue_reasons', []) or [],
        }
        report_data["source_data"]["therapeutic_areas"] = (
            getattr(impact, 'therapeutic_areas', []) or []
        )
        _urls = getattr(impact, '_source_urls', None) or {}
        _nct = getattr(impact, 'clinical_results_nct_id', '') or ''
        _comp_inns = [c["inn"] for c in getattr(impact, '_competitors', []) or []]

        if use_v4:
            # V4: 팩트/인사이트 분리 Jinja2 렌더링
            facts = {
                "inn": impact.inn,
                "source_data": report_data["source_data"],
                "d_day_text": generator._compute_d_day_text(impact),
                "approval_summary_table": generator._compute_approval_summary_table(impact),
                "cost_scenario_table": generator._compute_cost_scenario_table(impact),
            }
            insights = {
                "headline": report.headline,
                "subtitle": report.subtitle,
                "key_points": report.key_points,
                "global_insight_text": report.global_section,
                "domestic_insight_text": report.domestic_section,
                "medclaim_action_text": report.medclaim_section,
            }
            html_content = generate_article_html_v4(
                facts, insights, score=impact.global_score,
                source_urls=_urls, nct_id=_nct,
                known_inns=_comp_inns,
            )
        else:
            html_content = generate_article_html(
                report_data, score=impact.global_score,
                source_urls=_urls, nct_id=_nct,
                known_inns=_comp_inns,
            )
        html_path.write_text(html_content, encoding="utf-8")

        # JSON 메타데이터 보강
        _enriched = report.to_dict()
        _enriched["source_data"] = report_data["source_data"]
        _enriched["_source_urls"] = _urls
        _enriched["_nct_id"] = _nct
        _enriched["_score"] = impact.global_score
        _enriched["_hot_issue_reasons"] = getattr(impact, 'hot_issue_reasons', []) or []
        _enriched["_therapeutic_areas"] = getattr(impact, 'therapeutic_areas', []) or []
        _enriched["_known_inns"] = _comp_inns
        _enriched["_pipeline_version"] = "v4" if use_v4 else "v3"
        if use_v4:
            _enriched["_v4_facts"] = {
                "d_day_text": facts["d_day_text"],
                "approval_summary_table": facts["approval_summary_table"],
                "cost_scenario_table": facts["cost_scenario_table"],
            }
        json_path.write_text(
            json.dumps(_enriched, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

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
        md_lines.append(f"## [{art['score']}점] {to_display_case(art['inn'])}")
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

    # ── 자동 스냅샷 (결과 + 프롬프트 보관) ──
    try:
        from regscan.scripts.snapshot_articles import take_auto_snapshot
        ver_label = "v4" if use_v4 else "v3"
        snap_dest = take_auto_snapshot(pipeline_version=ver_label)
        logger.info("  스냅샷: %s", snap_dest.name)
    except Exception as e:
        logger.warning("  자동 스냅샷 실패 (무시): %s", e)

    print(f"\n{'='*60}")
    print(f"  RegScan 기사 발행 완료")
    print(f"{'='*60}")
    print(f"  LLM 생성: {generated}건 | 기존: {skipped}건 | 실패: {failed}건")
    print(f"  HTML 기사: {len(articles_meta)}건")
    print(f"  인덱스: {index_path}")
    print(f"\n  상위 5건:")
    for art in articles_meta[:5]:
        print(f"    [{art['score']}] {to_display_case(art['inn'])}")
        headline = art['headline'][:60].encode('ascii', 'replace').decode('ascii')
        print(f"         {headline}")
    print(f"{'='*60}")


def main():
    parser = ArgumentParser(description="RegScan 기사 발행")
    parser.add_argument("--top", type=int, default=20, help="상위 N개 약물 (기본 20)")
    parser.add_argument("--min-score", type=int, default=40, help="최소 점수 (기본 40)")
    parser.add_argument("--skip-llm", action="store_true", help="LLM 건너뜀 (기존 JSON만 HTML 변환)")
    parser.add_argument("--render-only", action="store_true", help="HTML만 재렌더 (LLM·DB 없이, ~2초)")
    parser.add_argument("--v4", action="store_true", help="V4 파이프라인 사용 (팩트/인사이트 분리 + Jinja2 + 툴콜링)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asyncio.run(run_publish(
        top_n=args.top, min_score=args.min_score,
        skip_llm=args.skip_llm, render_only=args.render_only,
        use_v4=args.v4,
    ))


if __name__ == "__main__":
    main()
