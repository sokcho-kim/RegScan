"""
의료/제약 뉴스 멀티 스크래퍼
국내: 메디게이트뉴스, 약업신문
글로벌: Endpoints News, FiercePharma (RSS 기반)
"""

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from datetime import datetime
import json
from pathlib import Path
import re
import time
from abc import ABC, abstractmethod
import xml.etree.ElementTree as ET
import hashlib


@dataclass
class Article:
    """기사 데이터 모델"""
    id: str
    title: str
    content: str
    author: str
    source: str
    category: str
    published_at: str
    url: str
    scraped_at: str = None

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


class BaseScraper(ABC):
    """기본 스크래퍼 인터페이스"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    @abstractmethod
    def fetch_latest(self, limit: int = 10) -> list[Article]:
        """최신 기사 수집"""
        pass

    def save_article(self, article: Article) -> Path:
        """기사 저장"""
        filename = f"{article.source}_{article.id}.json"
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)

        return filepath


class MedigateNewsScraper(BaseScraper):
    """메디게이트뉴스 스크래퍼"""

    BASE_URL = "https://www.medigatenews.com"
    SOURCE = "medigatenews"

    def __init__(self, output_dir: str = "data/scraping/medigatenews"):
        super().__init__(output_dir)

    def fetch_latest(self, limit: int = 10) -> list[Article]:
        """최신 기사 수집"""
        articles = []
        url = f"{self.BASE_URL}/news/articleList.html"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # 기사 링크 추출
            article_ids = []
            for link in soup.select('a[href*="/news/"]'):
                href = link.get('href', '')
                match = re.search(r'/news/(\d+)', href)
                if match and match.group(1) not in article_ids:
                    article_ids.append(match.group(1))
                    if len(article_ids) >= limit:
                        break

            # 각 기사 상세 수집
            for aid in article_ids:
                article = self._fetch_article(aid)
                if article:
                    self.save_article(article)
                    articles.append(article)
                    print(f"  [{self.SOURCE}] {aid} saved")
                time.sleep(0.5)

        except Exception as e:
            print(f"Error fetching {self.SOURCE}: {e}")

        return articles

    def _fetch_article(self, article_id: str) -> Article | None:
        """단일 기사 수집"""
        url = f"{self.BASE_URL}/news/{article_id}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # 제목
            title_elem = soup.select_one('h1.heading') or soup.select_one('h1')
            title = title_elem.get_text(strip=True) if title_elem else ""

            # 본문
            content_elem = soup.select_one('#article-view-content-div') or soup.select_one('.article-body')
            content = content_elem.get_text(strip=True) if content_elem else ""

            # 기자
            author = ""
            author_elem = soup.select_one('.byline') or soup.find(string=re.compile(r'기자'))
            if author_elem:
                author_text = author_elem.get_text() if hasattr(author_elem, 'get_text') else str(author_elem)
                author_match = re.search(r'(\w+)\s*기자', author_text)
                if author_match:
                    author = author_match.group(0)

            # 날짜
            published_at = ""
            date_elem = soup.select_one('.info-text time') or soup.select_one('time')
            if date_elem:
                published_at = date_elem.get_text(strip=True)

            # 카테고리
            category = ""
            cat_elem = soup.select_one('.category') or soup.select_one('.section-name')
            if cat_elem:
                category = cat_elem.get_text(strip=True)

            return Article(
                id=article_id,
                title=title,
                content=content[:5000],
                author=author,
                source=self.SOURCE,
                category=category,
                published_at=published_at,
                url=url
            )

        except Exception as e:
            print(f"Error fetching article {article_id}: {e}")
            return None


class RSSBasedScraper(BaseScraper):
    """RSS 기반 스크래퍼"""

    RSS_URL = ""
    SOURCE = ""
    NAMESPACES = {'dc': 'http://purl.org/dc/elements/1.1/'}

    def fetch_latest(self, limit: int = 10) -> list[Article]:
        """RSS 피드에서 최신 기사 수집"""
        articles = []

        try:
            response = self.session.get(self.RSS_URL, timeout=15)
            response.raise_for_status()

            # XML 파싱
            root = ET.fromstring(response.content)
            items = root.findall('.//item')[:limit]

            for item in items:
                article = self._parse_item(item)
                if article:
                    self.save_article(article)
                    articles.append(article)
                    print(f"  [{self.SOURCE}] {article.id[:30]}... saved")

        except Exception as e:
            print(f"Error fetching {self.SOURCE} RSS: {e}")

        return articles

    def _parse_item(self, item: ET.Element) -> Article | None:
        """RSS item 파싱"""
        try:
            title = item.findtext('title', '').strip()
            # HTML 태그 제거
            title = re.sub(r'<[^>]+>', '', title)

            link = item.findtext('link', '').strip()
            description = item.findtext('description', '').strip()
            # HTML 태그 제거
            description = re.sub(r'<[^>]+>', '', description)

            pub_date = item.findtext('pubDate', '').strip()

            # 저자 (dc:creator)
            author = item.findtext('dc:creator', '', self.NAMESPACES).strip()
            if not author:
                creator_elem = item.find('{http://purl.org/dc/elements/1.1/}creator')
                if creator_elem is not None:
                    author = creator_elem.text or ''

            # 카테고리
            categories = [cat.text for cat in item.findall('category') if cat.text]
            category = ', '.join(categories[:3]) if categories else ''

            # ID 생성 (URL 기반)
            article_id = link.rstrip('/').split('/')[-1]
            if not article_id or len(article_id) > 100:
                article_id = hashlib.md5(link.encode()).hexdigest()[:12]

            return Article(
                id=article_id,
                title=title,
                content=description,
                author=author,
                source=self.SOURCE,
                category=category,
                published_at=pub_date,
                url=link
            )

        except Exception as e:
            print(f"Error parsing RSS item: {e}")
            return None


class EndpointsNewsScraper(RSSBasedScraper):
    """Endpoints News 스크래퍼 (RSS)"""

    RSS_URL = "https://endpoints.news/feed/"
    SOURCE = "endpoints"

    def __init__(self, output_dir: str = "data/scraping/endpoints"):
        super().__init__(output_dir)


class FiercePharmasScraper(RSSBasedScraper):
    """FiercePharma 스크래퍼 (RSS)"""

    RSS_URL = "https://www.fiercepharma.com/rss/xml"
    SOURCE = "fiercepharma"

    def __init__(self, output_dir: str = "data/scraping/fiercepharma"):
        super().__init__(output_dir)


class YakupScraper(BaseScraper):
    """약업신문 스크래퍼 (기존 코드 통합)"""

    BASE_URL = "https://www.yakup.com"
    SOURCE = "yakup"

    def __init__(self, output_dir: str = "data/scraping/yakup"):
        super().__init__(output_dir)

    def fetch_latest(self, limit: int = 10) -> list[Article]:
        """최신 기사 수집"""
        articles = []
        url = f"{self.BASE_URL}/news/index.html?cat=12"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # 기사 nid 추출
            nids = []
            for link in soup.select('a[href*="nid="]'):
                href = link.get('href', '')
                match = re.search(r'nid=(\d+)', href)
                if match and match.group(1) not in nids:
                    nids.append(match.group(1))
                    if len(nids) >= limit:
                        break

            # 각 기사 수집
            for nid in nids:
                article = self._fetch_article(nid)
                if article:
                    self.save_article(article)
                    articles.append(article)
                    print(f"  [{self.SOURCE}] {nid} saved")
                time.sleep(0.5)

        except Exception as e:
            print(f"Error fetching {self.SOURCE}: {e}")

        return articles

    def _fetch_article(self, nid: str) -> Article | None:
        """단일 기사 수집"""
        url = f"{self.BASE_URL}/news/index.html?mode=view&cat=12&nid={nid}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            # 제목 (JavaScript 변수에서)
            title = ""
            title_match = re.search(r"var\s+title_this_page\s*=\s*['\"](.+?)['\"];", response.text)
            if title_match:
                title = title_match.group(1)

            soup = BeautifulSoup(response.text, 'html.parser')

            # 본문
            content_elem = soup.select_one('.text_article_con')
            content = content_elem.get_text(strip=True) if content_elem else ""

            # 기자
            author = ""
            author_match = re.search(r'(\w+)\s*기자', response.text)
            if author_match:
                author = author_match.group(0)

            # 날짜
            published_at = ""
            date_match = re.search(r'입력\s*(\d{4}\.\d{2}\.\d{2}\s*\d{2}:\d{2})', response.text)
            if date_match:
                published_at = date_match.group(1)

            return Article(
                id=nid,
                title=title,
                content=content[:5000],
                author=author,
                source=self.SOURCE,
                category="pharma",
                published_at=published_at,
                url=url
            )

        except Exception as e:
            print(f"Error fetching article {nid}: {e}")
            return None


def collect_all(limit_per_source: int = 5):
    """모든 소스에서 최신 기사 수집"""

    scrapers = [
        ("MedigateNews (KR)", MedigateNewsScraper()),
        ("Yakup (KR)", YakupScraper()),
        ("Endpoints (Global)", EndpointsNewsScraper()),
        ("FiercePharma (Global)", FiercePharmasScraper()),
    ]

    all_articles = []

    for name, scraper in scrapers:
        print(f"\n=== {name} ===")
        articles = scraper.fetch_latest(limit=limit_per_source)
        all_articles.extend(articles)
        print(f"Collected: {len(articles)} articles")

    print(f"\n{'='*50}")
    print(f"TOTAL: {len(all_articles)} articles from {len(scrapers)} sources")
    print(f"{'='*50}")

    return all_articles


if __name__ == "__main__":
    collect_all(limit_per_source=5)
