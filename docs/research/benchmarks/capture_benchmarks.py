"""벤치마크 서비스 화면 캡처 스크립트"""

from playwright.sync_api import sync_playwright
from pathlib import Path
import time

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

TARGETS = [
    # Perplexity AI
    {"name": "01_perplexity_home", "url": "https://www.perplexity.ai/", "desc": "Perplexity 홈 - 검색창 + Discover 피드"},
    {"name": "02_perplexity_discover", "url": "https://www.perplexity.ai/discover", "desc": "Perplexity Discover 피드"},

    # Glean
    {"name": "03_glean_home", "url": "https://www.glean.com/", "desc": "Glean 메인 - 엔터프라이즈 AI 검색"},
    {"name": "04_glean_extension", "url": "https://www.glean.com/browser-extension", "desc": "Glean 브라우저 확장 - 새 탭 페이지"},
    {"name": "05_glean_product", "url": "https://www.glean.com/product/overview", "desc": "Glean 제품 개요"},

    # Harvey AI
    {"name": "06_harvey_home", "url": "https://www.harvey.ai/", "desc": "Harvey AI 메인 - 톤앤매너 참고"},
    {"name": "07_harvey_assistant", "url": "https://www.harvey.ai/platform/assistant", "desc": "Harvey Assistant - Citation UI"},
    {"name": "08_harvey_legal", "url": "https://www.harvey.ai/legal", "desc": "Harvey Legal 페이지"},

    # Shopify
    {"name": "09_shopify_polaris", "url": "https://polaris.shopify.com/", "desc": "Shopify Polaris 디자인 시스템"},

    # Intercom
    {"name": "10_intercom_messenger", "url": "https://www.intercom.com/blog/product-thinking-behind-messenger-home/", "desc": "Intercom Messenger Home 설계"},
    {"name": "11_intercom_inbox", "url": "https://www.intercom.com/customer-service-platform/inbox", "desc": "Intercom AI Inbox"},

    # 컴플라이언스/헬스케어 대시보드
    {"name": "12_softr_compliance", "url": "https://softr.io/create/compliance-tracker-dashboard", "desc": "Softr 컴플라이언스 트래커"},
    {"name": "13_healthcare_ui", "url": "https://www.koruux.com/50-examples-of-healthcare-UI/", "desc": "헬스케어 UI 50선"},
    {"name": "14_dribbble_health", "url": "https://dribbble.com/tags/health-saas", "desc": "Dribbble 헬스케어 SaaS 디자인"},
    {"name": "15_behance_dashboard", "url": "https://www.behance.net/search/projects/saas%20dashboard", "desc": "Behance SaaS 대시보드"},

    # 가이드 아티클
    {"name": "16_uxdesign_b2b", "url": "https://uxdesign.cc/design-thoughtful-dashboards-for-b2b-saas-ff484385960d", "desc": "B2B SaaS 대시보드 설계 가이드"},
    {"name": "17_perplexity_guide", "url": "https://www.byriwa.com/how-to-use-perplexity-ai/", "desc": "Perplexity 사용 가이드 (스크린샷 포함)"},
]


def capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
        )
        page = context.new_page()

        for i, target in enumerate(TARGETS):
            name = target["name"]
            url = target["url"]
            desc = target["desc"]
            out = SCREENSHOT_DIR / f"{name}.png"

            print(f"[{i+1}/{len(TARGETS)}] {desc}")
            print(f"  URL: {url}")

            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                time.sleep(2)  # 렌더링 대기

                # 쿠키/팝업 닫기 시도
                for sel in [
                    "button:has-text('Accept')",
                    "button:has-text('Got it')",
                    "button:has-text('Close')",
                    "button:has-text('Dismiss')",
                    "[aria-label='Close']",
                    "[data-testid='close-button']",
                ]:
                    try:
                        page.click(sel, timeout=1000)
                        time.sleep(0.5)
                    except:
                        pass

                # 풀페이지 캡처
                page.screenshot(path=str(out), full_page=True)
                print(f"  -> {out.name} OK")

            except Exception as e:
                print(f"  -> FAIL: {e}")

        browser.close()

    print(f"\n완료! {SCREENSHOT_DIR} 확인하세요.")


if __name__ == "__main__":
    capture_all()
