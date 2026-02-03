"""
수집된 기사 분석 스크립트
- 키워드 추출
- 트렌드 분석
- 주요 기업/제품 언급 분석
"""

import json
from pathlib import Path
from collections import Counter
import re
from datetime import datetime


def load_articles(base_dir: str = "data/scraping") -> list[dict]:
    """모든 기사 로드"""
    articles = []
    for json_file in Path(base_dir).rglob('*.json'):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'source' not in data:
                data['source'] = json_file.parent.name
            articles.append(data)
    return articles


def extract_keywords(text: str, min_length: int = 2) -> list[str]:
    """텍스트에서 키워드 추출"""
    # 영문 단어 (2글자 이상)
    en_words = re.findall(r'\b[A-Za-z][A-Za-z0-9-]{1,}\b', text)
    # 한글 단어 (2글자 이상)
    kr_words = re.findall(r'[가-힣]{2,}', text)
    return en_words + kr_words


# 의료/제약 관련 주요 키워드
PHARMA_KEYWORDS = {
    # 치료 영역
    'obesity': '비만', 'diabetes': '당뇨', 'cancer': '암', 'oncology': '종양',
    'cardiovascular': '심혈관', 'neurology': '신경', 'immunology': '면역',
    'rare_disease': '희귀질환', 'mental_health': '정신건강',

    # 약물 유형
    'GLP-1': 'GLP-1', 'GIP': 'GIP', 'antibody': '항체', 'mRNA': 'mRNA',
    'gene_therapy': '유전자치료', 'cell_therapy': '세포치료',
    'biosimilar': '바이오시밀러', 'biologic': '바이오의약품',

    # 개발 단계
    'clinical_trial': '임상시험', 'Phase_1': '1상', 'Phase_2': '2상', 'Phase_3': '3상',
    'FDA': 'FDA', 'EMA': 'EMA', 'approval': '승인', 'IND': 'IND', 'NDA': 'NDA',

    # 기업 활동
    'M&A': 'M&A', 'partnership': '제휴', 'licensing': '라이선싱',
    'IPO': 'IPO', 'investment': '투자',
}

# 주요 제약사
PHARMA_COMPANIES = [
    'Pfizer', 'Novartis', 'Roche', 'Merck', 'AstraZeneca', 'GSK', 'Sanofi',
    'Johnson', 'AbbVie', 'Bristol-Myers', 'Eli Lilly', 'Novo Nordisk',
    'Gilead', 'Amgen', 'Biogen', 'Regeneron', 'Moderna', 'BioNTech',
    # 국내
    '삼성바이오', '셀트리온', '한미약품', 'SK바이오', '유한양행', '대웅제약',
    '녹십자', '종근당', '일동제약', '동아ST', '제넥신', '에이비엘바이오',
]

# 핫 토픽
HOT_TOPICS = [
    ('비만', 'obesity', 'weight', 'GLP-1', 'semaglutide', 'tirzepatide', 'Wegovy', 'Ozempic', 'Mounjaro'),
    ('AI', 'artificial intelligence', '인공지능', 'machine learning', '머신러닝'),
    ('세포치료', 'cell therapy', 'CAR-T', 'CAR-NK', 'stem cell', '줄기세포'),
    ('ADC', 'antibody-drug conjugate', '항체약물접합체'),
    ('mRNA', '메신저RNA'),
    ('유전자치료', 'gene therapy', 'CRISPR', '유전자편집'),
    ('바이오시밀러', 'biosimilar'),
    ('희귀질환', 'rare disease', 'orphan drug'),
]


def analyze_articles(articles: list[dict]) -> dict:
    """기사 분석"""
    results = {
        'total_articles': len(articles),
        'by_source': Counter(a['source'] for a in articles),
        'by_category': Counter(a.get('category', 'unknown') for a in articles if a.get('category')),
        'keywords': Counter(),
        'companies': Counter(),
        'hot_topics': Counter(),
        'recent_headlines': [],
    }

    all_text = ""
    for article in articles:
        title = article.get('title', '')
        content = article.get('content', '')
        text = f"{title} {content}"
        all_text += text + " "

        # 최신 헤드라인 (제목이 있는 경우만)
        if title and article.get('published_at'):
            results['recent_headlines'].append({
                'title': title,
                'source': article['source'],
                'date': article.get('published_at', ''),
                'category': article.get('category', ''),
            })

    # 키워드 빈도 분석
    words = extract_keywords(all_text)
    word_freq = Counter(w.lower() for w in words if len(w) >= 3)

    # 불용어 제거
    stopwords = {'the', 'and', 'for', 'that', 'with', 'are', 'this', 'from', 'was', 'were',
                 'has', 'have', 'been', 'will', 'can', 'its', 'their', 'said', 'which',
                 '있다', '있는', '하는', '대한', '위한', '통해', '따라', '이후', '것으로',
                 '있으며', '했다', '있을', '라며', '말했다', '등의', '에서', '으로'}

    results['keywords'] = Counter({k: v for k, v in word_freq.items()
                                    if k not in stopwords and v >= 3})

    # 기업 언급 분석
    text_lower = all_text.lower()
    for company in PHARMA_COMPANIES:
        count = text_lower.count(company.lower())
        if count > 0:
            results['companies'][company] = count

    # 핫 토픽 분석
    for topic_group in HOT_TOPICS:
        topic_name = topic_group[0]
        count = sum(text_lower.count(kw.lower()) for kw in topic_group)
        if count > 0:
            results['hot_topics'][topic_name] = count

    # 최신 헤드라인 정렬 (최신순)
    results['recent_headlines'] = sorted(
        results['recent_headlines'],
        key=lambda x: x['date'],
        reverse=True
    )[:20]

    return results


def print_analysis(results: dict):
    """분석 결과 출력"""
    print("=" * 60)
    print("       Medical/Pharma News Analysis Report")
    print("=" * 60)

    print(f"\n[Basic Stats]")
    print(f"  Total articles: {results['total_articles']}")
    print(f"\n  By source:")
    for src, cnt in results['by_source'].most_common():
        print(f"    - {src}: {cnt}")

    print(f"\n[Hot Topics TOP 10]")
    for topic, cnt in results['hot_topics'].most_common(10):
        bar = "#" * min(cnt // 5, 20)
        print(f"  {topic:15} {bar} ({cnt})")

    print(f"\n[Company Mentions]")
    for company, cnt in results['companies'].most_common(15):
        bar = "#" * min(cnt // 3, 20)
        print(f"  {company:15} {bar} ({cnt})")

    print(f"\n[Top Keywords]")
    for word, cnt in results['keywords'].most_common(20):
        print(f"  {word}: {cnt}")

    print(f"\n[Recent Headlines]")
    for i, h in enumerate(results['recent_headlines'][:10], 1):
        title_display = h['title'][:45] + '...' if len(h['title']) > 45 else h['title']
        # ASCII only for console
        title_ascii = title_display.encode('ascii', 'replace').decode('ascii')
        print(f"  {i}. [{h['source']}] {title_ascii}")


def save_analysis(results: dict, output_path: str = "data/scraping/analysis_report.json"):
    """분석 결과 저장"""
    # Counter를 dict로 변환
    output = {
        'generated_at': datetime.now().isoformat(),
        'total_articles': results['total_articles'],
        'by_source': dict(results['by_source']),
        'by_category': dict(results['by_category']),
        'hot_topics': dict(results['hot_topics'].most_common(20)),
        'companies': dict(results['companies'].most_common(20)),
        'keywords': dict(results['keywords'].most_common(50)),
        'recent_headlines': results['recent_headlines'],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n분석 결과 저장: {output_path}")


if __name__ == "__main__":
    articles = load_articles()
    results = analyze_articles(articles)
    print_analysis(results)
    save_analysis(results)
