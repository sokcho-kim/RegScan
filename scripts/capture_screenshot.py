"""HTML 페이지 전체 스크롤 캡쳐"""

from playwright.sync_api import sync_playwright
from pathlib import Path

HTML_FILE = Path(__file__).parent.parent / "output/daily_scan/daily_briefing_2026-02-05_newspaper.html"
OUTPUT_FILE = Path(__file__).parent.parent / "output/daily_scan/screenshot_newspaper.png"

def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 800})

        # 로컬 HTML 파일 열기
        page.goto(f"file:///{HTML_FILE.absolute()}")
        page.wait_for_timeout(1000)  # 폰트 로딩 대기

        # 전체 페이지 스크린샷
        page.screenshot(path=str(OUTPUT_FILE), full_page=True)

        browser.close()
        print(f"스크린샷 저장: {OUTPUT_FILE}")

if __name__ == "__main__":
    capture()
