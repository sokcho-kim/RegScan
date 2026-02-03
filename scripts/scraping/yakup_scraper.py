"""
약업신문(yakup.com) 스크래퍼
의료/제약 뉴스 수집
"""

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import time


@dataclass
class Article:
    """기사 데이터 모델"""
    nid: str
    title: str
    content: str
    author: str
    email: str
    category: str
    published_at: str
    url: str
    scraped_at: str = None

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "nid": self.nid,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "email": self.email,
            "category": self.category,
            "published_at": self.published_at,
            "url": self.url,
            "scraped_at": self.scraped_at
        }


class YakupScraper:
    """약업신문 스크래퍼"""

    BASE_URL = "https://www.yakup.com"
    CATEGORIES = {
        "12": "산업",
        "13": "정책",
        "14": "약국",
        "15": "학술",
        "16": "헬스",
    }

    def __init__(self, output_dir: str = "data/scraping/yakup"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def fetch_article(self, nid: str, cat: str = "12") -> Article | None:
        """단일 기사 수집"""
        url = f"{self.BASE_URL}/news/index.html?mode=view&cat={cat}&nid={nid}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # 제목 추출 (JavaScript 변수에서)
            title = ""
            title_match = re.search(r"var\s+title_this_page\s*=\s*['\"](.+?)['\"];", response.text)
            if title_match:
                title = title_match.group(1)
            else:
                # fallback: h1 또는 article_title
                title_elem = soup.select_one('h1') or soup.select_one('.article_title')
                title = title_elem.get_text(strip=True) if title_elem else ""

            # 본문 추출
            content_elem = soup.select_one('.text_article_con') or soup.select_one('.article_content')
            content = content_elem.get_text(strip=True) if content_elem else ""

            # 기자 정보 추출
            author = ""
            email = ""
            reporter_elem = soup.select_one('.reporter') or soup.find(string=re.compile(r'기자'))
            if reporter_elem:
                author_match = re.search(r'(\w+)\s*기자', str(reporter_elem))
                if author_match:
                    author = author_match.group(1) + " 기자"

            email_match = re.search(r'[\w.-]+@[\w.-]+', response.text)
            if email_match:
                email = email_match.group()

            # 날짜 추출
            published_at = ""
            date_match = re.search(r'입력\s*(\d{4}\.\d{2}\.\d{2}\s*\d{2}:\d{2})', response.text)
            if date_match:
                published_at = date_match.group(1)

            category = self.CATEGORIES.get(cat, "기타")

            return Article(
                nid=nid,
                title=title,
                content=content,
                author=author,
                email=email,
                category=category,
                published_at=published_at,
                url=url
            )

        except Exception as e:
            print(f"Error fetching article {nid}: {e}")
            return None

    def fetch_article_list(self, cat: str = "12", page: int = 1) -> list[str]:
        """기사 목록에서 nid 리스트 추출"""
        url = f"{self.BASE_URL}/news/index.html?cat={cat}&page={page}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            nids = []

            # 기사 링크에서 nid 추출
            for link in soup.select('a[href*="nid="]'):
                href = link.get('href', '')
                match = re.search(r'nid=(\d+)', href)
                if match:
                    nids.append(match.group(1))

            return list(set(nids))  # 중복 제거

        except Exception as e:
            print(f"Error fetching article list: {e}")
            return []

    def save_article(self, article: Article) -> Path:
        """기사 저장"""
        filename = f"{article.nid}.json"
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)

        return filepath

    def scrape_category(self, cat: str = "12", pages: int = 1, delay: float = 1.0) -> list[Article]:
        """카테고리별 기사 수집"""
        articles = []

        for page in range(1, pages + 1):
            print(f"Fetching page {page}...")
            nids = self.fetch_article_list(cat, page)

            for nid in nids:
                article = self.fetch_article(nid, cat)
                if article:
                    self.save_article(article)
                    articles.append(article)
                    print(f"  - nid={article.nid} saved")

                time.sleep(delay)  # 서버 부하 방지

        return articles


def main():
    """테스트 실행"""
    scraper = YakupScraper(output_dir="data/scraping/yakup")

    # 단일 기사 테스트
    article = scraper.fetch_article("322683", cat="12")

    if article:
        filepath = scraper.save_article(article)
        print(f"\n{'='*60}")
        print(f"제목: {article.title}")
        print(f"기자: {article.author} ({article.email})")
        print(f"날짜: {article.published_at}")
        print(f"카테고리: {article.category}")
        print(f"저장: {filepath}")
        print(f"{'='*60}")
        print(f"\n본문 미리보기:\n{article.content[:500]}...")
    else:
        print("기사를 가져오지 못했습니다.")


if __name__ == "__main__":
    main()
