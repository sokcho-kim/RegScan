"""Seladelpar 관련 기사 스크래핑"""

import sys
import io
import json
import asyncio
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.async_api import async_playwright

URLS = [
    "https://www.dailypharm.com/user/news/334440?view_mode=pc",
    "https://hyperlab.hits.ai/blog/seladelpar",
    "http://www.bosa.co.kr/news/articleView.html?idxno=2189109",
]

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "articles"


async def scrape_dailypharm(page, url):
    """데일리팜 기사 스크래핑"""
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    title = await page.locator("h1.title, .article-title, h1").first.text_content()

    # 기사 본문
    content_selectors = [
        "div.article-body",
        "div.article-content",
        "div#article-body",
        "article",
        "div.news_content",
        "div.view_content",
    ]

    content = ""
    for selector in content_selectors:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                content = await el.text_content()
                if len(content) > 100:
                    break
        except:
            continue

    if not content:
        content = await page.locator("body").text_content()

    return {
        "url": url,
        "source": "데일리팜",
        "title": title.strip() if title else "",
        "content": content.strip() if content else "",
    }


async def scrape_hyperlab(page, url):
    """하이퍼랩 블로그 스크래핑"""
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    title = await page.locator("h1").first.text_content()

    # 블로그 본문
    content_selectors = [
        "article",
        "div.blog-content",
        "div.post-content",
        "main",
        "div.content",
    ]

    content = ""
    for selector in content_selectors:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                content = await el.text_content()
                if len(content) > 100:
                    break
        except:
            continue

    if not content:
        content = await page.locator("body").text_content()

    return {
        "url": url,
        "source": "하이퍼랩",
        "title": title.strip() if title else "",
        "content": content.strip() if content else "",
    }


async def scrape_bosa(page, url):
    """보사연보 기사 스크래핑"""
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    title = await page.locator("h1, .article-title, h3.heading").first.text_content()

    # 기사 본문
    content_selectors = [
        "div#article-view-content-div",
        "div.article-body",
        "article",
        "div#news_body_area",
        "div.view-content",
    ]

    content = ""
    for selector in content_selectors:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                content = await el.text_content()
                if len(content) > 100:
                    break
        except:
            continue

    if not content:
        content = await page.locator("body").text_content()

    return {
        "url": url,
        "source": "보사연보",
        "title": title.strip() if title else "",
        "content": content.strip() if content else "",
    }


async def scrape_all():
    """모든 기사 스크래핑"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    articles = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # 1. 데일리팜
        print("[1/3] 데일리팜 스크래핑...")
        try:
            article = await scrape_dailypharm(page, URLS[0])
            articles.append(article)
            print(f"    제목: {article['title'][:50]}...")
            print(f"    본문: {len(article['content'])}자")
        except Exception as e:
            print(f"    실패: {e}")

        # 2. 하이퍼랩
        print("[2/3] 하이퍼랩 스크래핑...")
        try:
            article = await scrape_hyperlab(page, URLS[1])
            articles.append(article)
            print(f"    제목: {article['title'][:50]}...")
            print(f"    본문: {len(article['content'])}자")
        except Exception as e:
            print(f"    실패: {e}")

        # 3. 보사연보
        print("[3/3] 보사연보 스크래핑...")
        try:
            article = await scrape_bosa(page, URLS[2])
            articles.append(article)
            print(f"    제목: {article['title'][:50]}...")
            print(f"    본문: {len(article['content'])}자")
        except Exception as e:
            print(f"    실패: {e}")

        await browser.close()

    # JSON 저장
    output_file = OUTPUT_DIR / f"seladelpar_articles_{datetime.now().strftime('%Y%m%d')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": datetime.now().isoformat(),
            "count": len(articles),
            "articles": articles
        }, f, ensure_ascii=False, indent=2)

    print(f"\n저장: {output_file}")

    # 개별 텍스트 파일 저장
    for i, article in enumerate(articles, 1):
        txt_file = OUTPUT_DIR / f"seladelpar_{i}_{article['source']}.txt"
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(f"제목: {article['title']}\n")
            f.write(f"출처: {article['source']}\n")
            f.write(f"URL: {article['url']}\n")
            f.write(f"{'='*60}\n\n")
            f.write(article['content'])
        print(f"저장: {txt_file}")

    return articles


if __name__ == "__main__":
    articles = asyncio.run(scrape_all())

    print("\n" + "="*60)
    print("스크래핑 완료!")
    print("="*60)

    for article in articles:
        print(f"\n[{article['source']}]")
        print(f"제목: {article['title']}")
        print(f"본문 길이: {len(article['content'])}자")
        print(f"본문 미리보기: {article['content'][:200]}...")
