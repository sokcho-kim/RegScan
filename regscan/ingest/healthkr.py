"""Health.kr 전문가 리뷰 수집기

Health.kr (건강정보포털)에서 약물별 전문가 리뷰를 수집합니다.
KPIC(약학정보원), 약사저널 등 섹션을 파싱합니다.

Playwright 기반 크롤링.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from regscan.config import settings
from .base import BaseIngestor

logger = logging.getLogger(__name__)

HEALTHKR_BASE_URL = "https://www.health.kr"
HEALTHKR_SEARCH_URL = f"{HEALTHKR_BASE_URL}/searchDrug/search.asp"


class HealthKRClient:
    """Health.kr 크롤링 클라이언트 (Playwright)"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._page = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()
        except ImportError:
            logger.warning("playwright 미설치 — pip install 'regscan[crawl]'")
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()

    async def search_drug(self, drug_name: str) -> list[dict[str, Any]]:
        """약물명으로 검색하여 drug_cd 목록 추출

        Args:
            drug_name: 약물명 (INN 또는 브랜드명)

        Returns:
            [{drug_cd, name, company, ...}, ...]
        """
        results = []
        try:
            url = f"{HEALTHKR_SEARCH_URL}?searchWord={drug_name}"
            await self._page.goto(url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(2000)

            rows = await self._page.query_selector_all(".search_result tr, .drug_list tr")
            for row in rows:
                try:
                    link = await row.query_selector("a[href*='drug_cd']")
                    if not link:
                        continue

                    name = (await link.inner_text()).strip()
                    href = await link.get_attribute("href") or ""

                    # drug_cd 추출
                    drug_cd = ""
                    if "drug_cd=" in href:
                        drug_cd = href.split("drug_cd=")[1].split("&")[0]

                    cols = await row.query_selector_all("td")
                    company = ""
                    if len(cols) >= 3:
                        company = (await cols[2].inner_text()).strip()

                    results.append({
                        "drug_cd": drug_cd,
                        "name": name,
                        "company": company,
                        "url": f"{HEALTHKR_BASE_URL}{href}" if href.startswith("/") else href,
                    })
                except Exception as e:
                    logger.debug("Health.kr 행 파싱 오류: %s", e)
                    continue

        except Exception as e:
            logger.warning("Health.kr 검색 실패 (%s): %s", drug_name, e)

        return results

    async def fetch_expert_reviews(self, drug_cd: str) -> list[dict[str, Any]]:
        """drug_cd 기반으로 전문가 리뷰(KPIC, 약사저널) 수집

        Args:
            drug_cd: Health.kr 약물 고유 코드

        Returns:
            [{title, source, author, summary, date, url}, ...]
        """
        reviews = []

        # KPIC 섹션
        try:
            kpic_url = f"{HEALTHKR_BASE_URL}/drug/drugBasicInfo.asp?drug_cd={drug_cd}"
            await self._page.goto(kpic_url, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(1500)

            # 전문가 의견 섹션 파싱
            sections = await self._page.query_selector_all(
                ".expert_opinion, .kpic_info, .drug_review"
            )
            for section in sections:
                try:
                    title_el = await section.query_selector("h3, h4, .title")
                    content_el = await section.query_selector(".content, p")

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    content = (await content_el.inner_text()).strip() if content_el else ""

                    if title or content:
                        reviews.append({
                            "title": title or f"KPIC 리뷰 - {drug_cd}",
                            "source": "KPIC",
                            "summary": content[:1000],
                            "source_url": kpic_url,
                            "drug_cd": drug_cd,
                        })
                except Exception as e:
                    logger.debug("KPIC 섹션 파싱 오류: %s", e)

        except Exception as e:
            logger.warning("KPIC 수집 실패 (drug_cd=%s): %s", drug_cd, e)

        return reviews


class HealthKRIngestor(BaseIngestor):
    """Health.kr 전문가 리뷰 수집기"""

    def __init__(self, drug_names: list[str] | None = None, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.drug_names = drug_names or []

    def source_type(self) -> str:
        return "HEALTHKR"

    async def fetch(self) -> list[dict[str, Any]]:
        """Health.kr 전문가 리뷰 수집

        Returns:
            리뷰 목록 (파싱 전 raw data)
        """
        all_reviews = []

        async with HealthKRClient() as client:
            for drug_name in self.drug_names:
                try:
                    drugs = await client.search_drug(drug_name)
                    for drug in drugs[:3]:  # 상위 3건만
                        if drug.get("drug_cd"):
                            reviews = await client.fetch_expert_reviews(drug["drug_cd"])
                            for r in reviews:
                                r["drug_name"] = drug_name
                                r["collected_at"] = self._now().isoformat()
                                all_reviews.append(r)
                except Exception as e:
                    logger.warning("Health.kr '%s' 수집 실패: %s", drug_name, e)

        logger.info("Health.kr 총 %d건 수집 완료", len(all_reviews))
        return all_reviews
