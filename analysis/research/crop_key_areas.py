"""풀페이지 캡처에서 핵심 영역만 크롭"""

from PIL import Image
from pathlib import Path

SRC = Path(__file__).parent / "screenshots"
OUT = Path(__file__).parent / "screenshots" / "cropped"
OUT.mkdir(exist_ok=True)


def crop(src_name, out_name, top, bottom, desc=""):
    """원본에서 (0, top) ~ (width, bottom) 영역을 크롭"""
    src = SRC / src_name
    if not src.exists():
        print(f"  SKIP (not found): {src_name}")
        return
    img = Image.open(src)
    w, h = img.size
    bottom = min(bottom, h)
    cropped = img.crop((0, top, w, bottom))
    out_path = OUT / out_name
    cropped.save(out_path, quality=90)
    print(f"  {out_name:50s} {cropped.size[0]}x{cropped.size[1]:5d}  ({desc})")


print("=== Perplexity ===")
# 허브: 상단 히어로 + 사용 사례 카드
crop("01d_perplexity_hub.png", "perplexity_hub_hero.png", 0, 1400,
     "시작하기 히어로 + 사용 사례 카드")

print("\n=== Glean ===")
# 확장: 히어로
crop("04_glean_extension.png", "glean_ext_hero.png", 0, 900,
     "브라우저 확장 히어로")
# 확장: Ask in context
crop("04_glean_extension.png", "glean_ext_ask.png", 1100, 2600,
     "Ask in context, get instant answers")
# 확장: Discover
crop("04_glean_extension.png", "glean_ext_discover.png", 2800, 4200,
     "Discover what matters")
# 확장: 새 탭
crop("04_glean_extension.png", "glean_ext_newtab.png", 5200, 6800,
     "Your new tab, optimized for productivity")
# 제품 개요: 히어로
crop("05_glean_product.png", "glean_product_hero.png", 0, 1200,
     "제품 개요 히어로")

print("\n=== Harvey AI ===")
# 메인: 히어로 + 제품 섹션
crop("06_harvey_home.png", "harvey_hero.png", 0, 1200,
     "Professional Class AI 히어로")
# 메인: 제품 카드들
crop("06_harvey_home.png", "harvey_products.png", 1200, 3800,
     "Assistant + Knowledge + Vault 제품 소개")
# Assistant: 쿼리 UI 목업
crop("07_harvey_assistant.png", "harvey_asst_query.png", 0, 1500,
     "Assistant 쿼리 + Source 문서 UI")
# Assistant: Just Ask Harvey 카드
crop("07_harvey_assistant.png", "harvey_asst_cards.png", 1500, 2800,
     "문서 업로드, Follow-up, 워크플로우, 협업")
# Assistant: Source Assured + Citation
crop("07_harvey_assistant.png", "harvey_asst_citation.png", 2800, 3900,
     "Source Assured 인용 하이라이트 + Multi Source")
# Assistant: Draft Mode + Word
crop("07_harvey_assistant.png", "harvey_asst_draft.png", 3900, 5200,
     "Draft Mode redline + Word 연동")

print("\n=== Shopify ===")
# Polaris: 이미 뷰포트 크기 (1440x962), 그대로 사용

print("\n=== Intercom ===")
# Inbox: 히어로
crop("11_intercom_inbox.png", "intercom_inbox_hero.png", 0, 1200,
     "AI Inbox 히어로")
# Inbox: 제품 화면
crop("11_intercom_inbox.png", "intercom_inbox_features.png", 1200, 3000,
     "Inbox 주요 기능 소개")
# Messenger: 핵심 디자인 결정
crop("10_intercom_messenger.png", "intercom_messenger_top.png", 0, 2000,
     "Messenger Home 설계 블로그 상단")

print("\n=== 컴플라이언스 ===")
# Softr: 히어로 + 대시보드 미리보기
crop("12_softr_compliance.png", "softr_hero.png", 0, 1500,
     "Compliance Tracker 히어로")
crop("12_softr_compliance.png", "softr_dashboard.png", 1500, 3500,
     "대시보드 미리보기")

print("\n=== 디자인 갤러리 ===")
# Healthcare UI: 상단 사례들
crop("13_healthcare_ui.png", "healthcare_ui_top.png", 0, 3000,
     "헬스케어 UI 상단 사례")
# Dribbble: 갤러리 뷰
crop("14_dribbble_health.png", "dribbble_health_gallery.png", 0, 1800,
     "Dribbble 헬스케어 SaaS 갤러리")
# Behance: 갤러리 뷰
crop("15_behance_dashboard.png", "behance_dashboard_gallery.png", 0, 2000,
     "Behance SaaS 대시보드 갤러리")

print("\n완료!")
