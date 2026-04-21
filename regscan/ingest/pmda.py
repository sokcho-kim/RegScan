"""PMDA (일본 의약품의료기기종합기구) 수집기

승인심사: rss_011.xml (Reviews) — 신약 승인, 심사 보고서
안전성: rss_013.xml (Safety) + 안전성 정보 HTML 테이블
전체: rss_008.xml (All) — 모든 카테고리 통합

RSS (RDF 1.0) + HTML 크롤링 + Excel 벌크 다운로드.
bs4 + lxml XML 파서, openpyxl Excel 파서 사용.
"""

from __future__ import annotations

import io
import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import BaseIngestor

logger = logging.getLogger(__name__)

PMDA_BASE = "https://www.pmda.go.jp"

# RSS 피드 URL
RSS_FEEDS = {
    "all": f"{PMDA_BASE}/rss_008.xml",
    "reviews": f"{PMDA_BASE}/rss_011.xml",
    "safety": f"{PMDA_BASE}/rss_013.xml",
    "international": f"{PMDA_BASE}/rss_009.xml",
}

# RSS 타이틀 카테고리 접두사 → 분류
CATEGORY_PREFIX = {
    "[SHINSA]": "review",       # 承認審査 (승인심사)
    "[ANZEN]": "safety",        # 安全対策 (안전대책)
    "[KOKUSAI]": "international",  # 国際 (국제)
    "[IBENTO]": "event",        # イベント (이벤트)
    "[SONOTA]": "other",        # その他 (기타)
    "[KISEI]": "regulation",    # 規制 (규제)
    "[SUKUHAI]": "relief",      # 救済 (구제)
}

# 안전성 정보 HTML 페이지
SAFETY_INFO_URL = (
    f"{PMDA_BASE}/english/safety/info-services"
    "/safety-information/0001.html"
)


def _make_tls12_context() -> ssl.SSLContext:
    """PMDA는 TLS 1.3 미지원 — TLS 1.2 강제"""
    ctx = ssl.create_default_context()
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _parse_rss_xml(xml_text: str) -> list[dict[str, str]]:
    """RDF 1.0 RSS XML을 파싱하여 항목 리스트 반환.

    feedparser 없이 bs4로 직접 파싱 (의존성 최소화).
    """
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item_el in soup.find_all("item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        date_el = item_el.find("dc:date") or item_el.find("date")

        title = title_el.get_text(strip=True) if title_el else ""
        link = link_el.get_text(strip=True) if link_el else ""
        date_str = date_el.get_text(strip=True) if date_el else ""

        if title:
            items.append({
                "title": title,
                "link": link,
                "date": date_str,
            })
    return items


def _classify_item(title: str) -> tuple[str, str]:
    """RSS 타이틀에서 카테고리 접두사 분리.

    Returns: (category, clean_title)
    """
    for prefix, category in CATEGORY_PREFIX.items():
        if title.startswith(prefix):
            clean = title[len(prefix):].strip()
            # 중복 접두사 제거 (예: [IBENTO][IBENTO])
            for p2 in CATEGORY_PREFIX:
                if clean.startswith(p2):
                    clean = clean[len(p2):].strip()
            return category, clean
    return "other", title


def _parse_iso_date(date_str: str) -> str:
    """ISO 8601 날짜를 YYYY-MM-DD로 변환."""
    if not date_str:
        return ""
    # 2026-04-14T12:00:00+09:00 → 2026-04-14
    match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
    return match.group(1) if match else ""


# ── PMDA RSS 수집기 ──────────────────────────────────────────


class PMDAReviewIngestor(BaseIngestor):
    """PMDA 승인심사 정보 수집기 (RSS)

    rss_011.xml — 신약 승인, 심사 보고서, 상담 정보 등
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_REVIEW"

    async def fetch(self) -> list[dict[str, Any]]:
        """승인심사 RSS 수집"""
        return await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["reviews"],
            source_type="PMDA_REVIEW",
            days_back=self.days_back,
        )


class PMDASafetyIngestor(BaseIngestor):
    """PMDA 안전성 정보 수집기 (RSS + HTML)

    rss_013.xml — 안전대책 관련 업데이트
    HTML 테이블 — Medical Safety Information (72+ 보고서)
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
        include_html_table: bool = True,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.include_html_table = include_html_table

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_SAFETY"

    async def fetch(self) -> list[dict[str, Any]]:
        """안전성 RSS + HTML 테이블 수집"""
        results = await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["safety"],
            source_type="PMDA_SAFETY",
            days_back=self.days_back,
        )

        if self.include_html_table:
            table_results = await self._fetch_safety_table()
            results.extend(table_results)

        logger.info(
            "[PMDA] 안전성 정보 총 %d건 수집", len(results),
        )
        return results

    async def _fetch_safety_table(self) -> list[dict[str, Any]]:
        """Medical Safety Information HTML 테이블 파싱"""
        try:
            response = await self.client.get(
                SAFETY_INFO_URL, follow_redirects=True,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error("[PMDA] 안전성 테이블 요청 실패: %s", e)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        records: list[dict[str, Any]] = []

        for row in soup.select("table tr"):
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            posted_in = cols[0].get_text(strip=True)
            number = cols[1].get_text(strip=True).replace("\n", " ")
            link = cols[2].find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            pdf_url = (
                f"{PMDA_BASE}{href}" if href.startswith("/") else href
            )

            records.append({
                "source": "PMDA",
                "source_type": "PMDA_SAFETY_REPORT",
                "title": title,
                "number": number,
                "posted_in": posted_in,
                "url": pdf_url,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        logger.info(
            "[PMDA] 안전성 보고서 테이블 %d건", len(records),
        )
        return records


class PMDAAllIngestor(BaseIngestor):
    """PMDA 전체 업데이트 수집기 (RSS)

    rss_008.xml — 모든 카테고리 통합 피드
    """

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 90,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
        )
        return self

    def source_type(self) -> str:
        return "PMDA_ALL"

    async def fetch(self) -> list[dict[str, Any]]:
        """전체 RSS 수집"""
        return await _fetch_rss(
            client=self.client,
            feed_url=RSS_FEEDS["all"],
            source_type="PMDA_ALL",
            days_back=self.days_back,
        )


# ── 공통 RSS 수집 로직 ──────────────────────────────────────


async def _fetch_rss(
    *,
    client: httpx.AsyncClient,
    feed_url: str,
    source_type: str,
    days_back: int,
) -> list[dict[str, Any]]:
    """RSS 피드를 가져와서 구조화된 레코드로 변환."""
    try:
        response = await client.get(feed_url, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        logger.error("[PMDA] RSS 요청 실패 (%s): %s", feed_url, e)
        return []

    items = _parse_rss_xml(response.text)
    cutoff = (datetime.now() - timedelta(days=days_back)).date()
    now_str = datetime.now().strftime("%Y-%m-%d")

    records: list[dict[str, Any]] = []
    for item in items:
        date_str = _parse_iso_date(item["date"])

        # 날짜 필터
        if date_str:
            try:
                pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if pub_date < cutoff:
                    continue
            except ValueError:
                pass

        category, clean_title = _classify_item(item["title"])

        records.append({
            "source": "PMDA",
            "source_type": source_type,
            "category": category,
            "title": clean_title,
            "title_original": item["title"],
            "date": date_str,
            "url": item["link"],
            "_fetched_at": now_str,
        })

    logger.info(
        "[PMDA] %s: %d건 수집 (최근 %d일)",
        source_type, len(records), days_back,
    )
    return records


# ── PMDA 신약 승인 목록 (Excel) ──────────────────────────────

# 연도별 승인 목록 페이지 (최근 → 과거순)
APPROVAL_LIST_INDEX = (
    f"{PMDA_BASE}/review-services/drug-reviews"
    "/review-information/p-drugs/0010.html"
)


class PMDAApprovalIngestor(BaseIngestor):
    """PMDA 신약 승인 목록 수집기 (Excel 벌크)

    pmda.go.jp 연도별 신약 승인 품목 일람 Excel을 다운로드하여 파싱.
    필드: 분야, 승인일, 판매명, 회사명, 성분명(INN), 효능·효과
    """

    def __init__(
        self,
        timeout: float = 30.0,
        years: int = 2,
    ):
        super().__init__(timeout=timeout)
        self.years = years

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self.timeout, verify=_make_tls12_context(),
            headers={"User-Agent": "RegScan/1.0"},
        )
        return self

    def source_type(self) -> str:
        return "PMDA_APPROVAL"

    async def fetch(self) -> list[dict[str, Any]]:
        """연도별 Excel에서 승인 품목 수집"""
        xlsx_urls = await self._find_xlsx_urls()

        all_records: list[dict[str, Any]] = []
        for url in xlsx_urls[:self.years]:
            records = await self._fetch_and_parse_xlsx(url)
            all_records.extend(records)

        logger.info(
            "[PMDA] 신약 승인 %d건 수집 (최근 %d년)",
            len(all_records), self.years,
        )
        return all_records

    async def _find_xlsx_urls(self) -> list[str]:
        """승인 목록 인덱스에서 연도별 페이지 URL을 찾고,
        각 페이지에서 xlsx 다운로드 URL을 추출."""
        try:
            r = await self.client.get(
                APPROVAL_LIST_INDEX, follow_redirects=True,
            )
            r.raise_for_status()
        except Exception as e:
            logger.error("[PMDA] 승인 목록 인덱스 요청 실패: %s", e)
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("#contents") or soup

        # 연도별 페이지 링크 (최근순)
        year_pages: list[str] = []
        for a in main.select("a[href*='p-drugs']"):
            text = a.get_text(strip=True)
            if re.match(r"20\d{2}年度", text):
                href = a["href"]
                full = f"{PMDA_BASE}{href}" if href.startswith("/") else href
                year_pages.append(full)

        # 각 연도 페이지에서 xlsx URL 추출
        xlsx_urls: list[str] = []
        for page_url in year_pages[:self.years]:
            try:
                r2 = await self.client.get(page_url, follow_redirects=True)
                r2.raise_for_status()
                soup2 = BeautifulSoup(r2.text, "html.parser")
                for a2 in soup2.select("a[href$='.xlsx']"):
                    href2 = a2["href"]
                    full2 = (
                        f"{PMDA_BASE}{href2}"
                        if href2.startswith("/") else href2
                    )
                    xlsx_urls.append(full2)
                    break  # 페이지당 1개
            except Exception as e:
                logger.warning(
                    "[PMDA] 연도 페이지 요청 실패 (%s): %s", page_url, e,
                )

        return xlsx_urls

    async def _fetch_and_parse_xlsx(
        self, url: str,
    ) -> list[dict[str, Any]]:
        """Excel 다운로드 + 파싱"""
        try:
            r = await self.client.get(url, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:
            logger.error("[PMDA] Excel 다운로드 실패 (%s): %s", url, e)
            return []

        return self._parse_xlsx(r.content)

    @staticmethod
    def _parse_xlsx(content: bytes) -> list[dict[str, Any]]:
        """PMDA 승인 목록 Excel 파싱"""
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        records: list[dict[str, Any]] = []
        now_str = datetime.now().strftime("%Y-%m-%d")

        for ws in wb.worksheets:
            header_row = None
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                # 헤더 행 찾기 (承認日 컬럼 포함)
                row_str = [str(c or "") for c in row]
                if any("承認日" in s for s in row_str):
                    header_row = i
                    continue

                if header_row is None:
                    continue

                # 데이터 행
                cells = list(row)
                if len(cells) < 6:
                    continue

                area = str(cells[0] or "").strip()
                date_raw = str(cells[1] or "").strip()
                number = str(cells[2] or "").strip()
                product_info = str(cells[3] or "").strip()
                approval_type = str(cells[4] or "").strip()
                ingredient = str(cells[5] or "").strip()
                indication = str(cells[6] or "").strip() if len(cells) > 6 else ""

                if not date_raw or not ingredient:
                    continue

                # 날짜 파싱 (2025.5.19 → 2025-05-19)
                date_match = re.match(
                    r"(\d{4})\.(\d{1,2})\.(\d{1,2})", date_raw,
                )
                if date_match:
                    y, m, d = date_match.groups()
                    date_str = f"{y}-{int(m):02d}-{int(d):02d}"
                else:
                    date_str = ""

                # 판매명/회사명 분리
                product_name = product_info.split("\n")[0].strip()
                company = ""
                if "\n" in product_info:
                    company_line = product_info.split("\n", 1)[1].strip()
                    company = re.sub(r"[（(].*?[）)]", "", company_line).strip()

                records.append({
                    "source": "PMDA",
                    "source_type": "PMDA_APPROVAL",
                    "area": area,
                    "date": date_str,
                    "number": number,
                    "product_name": product_name,
                    "company": company,
                    "approval_type": approval_type,
                    "ingredient": ingredient,
                    "indication": indication[:300],
                    "_fetched_at": now_str,
                })

        wb.close()
        return records
