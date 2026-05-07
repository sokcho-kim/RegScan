"""MFDS 보도자료/공지사항/입법예고 수집기

mfds.go.kr 게시판 3개 통합 크롤링 (httpx+bs4, TLS 1.2+UA).
- 보도자료 (m_99): 신약 허가, 안전성, 정책
- 공지사항 (m_74): 규제 변경
- 입법예고 (m_209): 법령 제/개정

본문은 첨부 PDF에서 추출 (fetch_body=True).
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

MFDS_BASE = "https://www.mfds.go.kr"

BOARDS = {
    "press": {"id": "m_99", "label": "보도자료"},
    "notice": {"id": "m_74", "label": "공지사항"},
    "legislation": {"id": "m_209", "label": "입법예고"},
}


class MFDSPressIngestor(BaseIngestor):
    """MFDS 보도자료/공지/입법예고 수집기"""

    def __init__(
        self,
        timeout: float = 30.0,
        days_back: int = 14,
        max_pages: int = 3,
        boards: list[str] | None = None,
        fetch_body: bool = True,
    ):
        super().__init__(timeout=timeout)
        self.days_back = days_back
        self.max_pages = max_pages
        self.boards = boards or ["press", "notice"]
        self.fetch_body = fetch_body

    async def __aenter__(self):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            verify=ctx,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        return self

    def source_type(self) -> str:
        return "MFDS_PRESS"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = (self._now() - timedelta(days=self.days_back)).date()
        all_records: list[dict[str, Any]] = []

        for board_key in self.boards:
            board = BOARDS.get(board_key)
            if not board:
                continue
            records = await self._fetch_board(board, cutoff)
            all_records.extend(records)

        # 본문 추출
        if self.fetch_body:
            for record in all_records:
                await self._fetch_body(record)

        logger.info(
            "[MFDS Press] %d건 수집 (최근 %d일, body=%s)",
            len(all_records), self.days_back, self.fetch_body,
        )
        return all_records

    async def _fetch_board(self, board: dict, cutoff) -> list[dict]:
        board_id = board["id"]
        label = board["label"]
        records: list[dict] = []

        for page in range(1, self.max_pages + 1):
            try:
                response = await self._request_with_retry(
                    "GET",
                    f"{MFDS_BASE}/brd/{board_id}/list.do",
                    params={"page": page},
                    max_retries=3,
                )
            except Exception as e:
                logger.warning("[MFDS Press] %s p%d 실패: %s", label, page, e)
                break

            page_records, should_stop = self._parse_list(
                response.text, board_id, label, cutoff,
            )
            records.extend(page_records)
            if should_stop or not page_records:
                break

        return records

    def _parse_list(
        self, html: str, board_id: str, label: str, cutoff,
    ) -> tuple[list[dict], bool]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        should_stop = False

        for li in soup.select("div.bbs_list01 ul li"):
            a = li.select_one("a.title")
            if not a:
                continue

            title = a.get_text(strip=True)
            href = a.get("href", "")
            if "view.do" not in href:
                continue

            url = f"{MFDS_BASE}/brd/{board_id}/{href}" if not href.startswith("http") else href

            text = li.get_text()
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            date_str = date_match.group(1) if date_match else ""

            if date_str:
                try:
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if pub_date < cutoff:
                        should_stop = True
                        continue
                except ValueError:
                    pass

            # 담당부서 추출
            dept_match = re.search(r"담당부서\s*\|?\s*([^\n]+?)(?:\s+조회수|\s+\d{4}-|$)", text)
            department = dept_match.group(1).strip() if dept_match else ""

            records.append({
                "source": "MFDS",
                "source_type": "MFDS_PRESS",
                "board": label,
                "title": title,
                "department": department,
                "date": date_str,
                "url": url,
                "_fetched_at": self._now().strftime("%Y-%m-%d"),
            })

        return records, should_stop

    async def _fetch_body(self, record: dict) -> None:
        """상세 페이지 → 첨부 PDF 다운로드 → 텍스트 추출."""
        url = record.get("url", "")
        if not url:
            return

        # 1) 상세 페이지에서 첨부파일 URL 추출
        try:
            response = await self._request_with_retry(
                "GET", url, max_retries=2,
            )
        except Exception as e:
            logger.debug("[MFDS Press] 상세 페이지 실패: %s", e)
            return

        soup = BeautifulSoup(response.text, "html.parser")

        # 웹 본문이 있으면 먼저 시도 (일부 게시물은 웹에 본문 포함)
        content_div = soup.select_one("div.bbs-view-content")
        if content_div:
            web_body = content_div.get_text(separator="\n", strip=True)
            if len(web_body) > 100:
                record["body"] = web_body
                record["body_source"] = "html"
                return

        # 첨부파일에서 PDF 찾기
        pdf_url = self._extract_pdf_url(soup, base_url=url)
        if not pdf_url:
            return

        # 2) PDF 다운로드 + 텍스트 추출
        try:
            pdf_response = await self._request_with_retry(
                "GET", pdf_url, max_retries=2,
            )
            body = self._extract_text_from_pdf(pdf_response.content)
            if body:
                record["body"] = body
                record["body_source"] = "pdf"
        except Exception as e:
            logger.debug("[MFDS Press] PDF 추출 실패 (%s): %s", record["title"][:30], e)

    def _extract_pdf_url(self, soup: BeautifulSoup, base_url: str = "") -> str | None:
        """첨부파일 목록에서 PDF 다운로드 URL 추출.

        MFDS 첨부파일 구조:
          <ul class="bbs_file_view_list">
            <li>
              <strong>파일명.pdf</strong>
              <a class="bbs_icon_filedown" href="./down.do?brd_id=...&seq=...&file_seq=N">다운받기</a>
        """
        file_items = soup.select("ul.bbs_file_view_list li")

        # 1) PDF 파일 우선
        for li in file_items:
            filename_el = li.select_one("strong")
            if not filename_el:
                continue
            filename = filename_el.get_text(strip=True).lower()
            if ".pdf" not in filename:
                continue
            dl_link = li.select_one("a.bbs_icon_filedown, a[href*='down.do']")
            if dl_link:
                return self._resolve_download_url(dl_link.get("href", ""), base_url)

        # 2) fallback: hwpx/hwp 아무 첨부파일
        for li in file_items:
            dl_link = li.select_one("a.bbs_icon_filedown, a[href*='down.do']")
            if dl_link:
                return self._resolve_download_url(dl_link.get("href", ""), base_url)

        return None

    @staticmethod
    def _resolve_download_url(href: str, base_url: str) -> str:
        """상대 경로 → 절대 URL 변환."""
        if href.startswith("http"):
            return href
        if href.startswith("./"):
            # base_url: https://www.mfds.go.kr/brd/m_99/view.do?...
            # href: ./down.do?...
            # 결과: https://www.mfds.go.kr/brd/m_99/down.do?...
            base_path = base_url.split("?")[0].rsplit("/", 1)[0]
            return f"{base_path}/{href[2:]}"
        if href.startswith("/"):
            return f"{MFDS_BASE}{href}"
        return href

    @staticmethod
    def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
        """PDF 바이트 → 텍스트 추출 + 식약처 보도자료 양식 정제."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber 미설치 — pip install pdfplumber")
            return ""

        text_parts: list[str] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
        except Exception as e:
            logger.debug("[MFDS Press] PDF 파싱 오류: %s", e)
            return ""

        full_text = "\n".join(text_parts)
        return _clean_mfds_press_text(full_text)


def _clean_mfds_press_text(text: str) -> str:
    """식약처 보도자료 PDF 공통 양식 노이즈 제거.

    식약처 보도자료 PDF 구조:
      [헤더] 보도시점/배포일시
      [제목] 본문 제목 (중복 — 이미 title 필드에 있음)
      [부제] - 대시로 시작하는 요약
      [본문] 핵심 내용
      [붙임] 행사일정, 포스터, 신청서 등 부속 자료
      [담당자] 부서명 + 이름 + 전화번호
      [페이지번호] - 1 -, - 2 - 등
    """
    # ── 1. 붙임 이후 전체 제거 (본문과 부속자료 분리) ──
    # "<붙임>" 또는 "붙붙임임" (PDF 추출 시 중복 글자) 패턴
    text = re.split(
        r"\n\s*(?:<\s*붙임\s*>|붙\s*임|붙붙임임)\s*\d*\.?\s",
        text, maxsplit=1,
    )[0]

    # ── 2. 헤더 블록 제거 ──
    # "보도시점 배포 즉시 배포 2026. 5. 7.(목)" / "보도시점 2026. 5. 7.(목) 15:00 배포 ..."
    text = re.sub(
        r"보도시점\s.*?배포\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*\([월화수목금토일]\)\s*",
        "", text, count=1,
    )
    # "보도자료" / "보도참고자료" 라벨
    text = re.sub(
        r"(?:보\s*도\s*참?\s*고?\s*자\s*료)\s*", "", text, count=1,
    )
    # "배포 시 보도해 주시기 바랍니다"
    text = re.sub(r"배포\s*시\s*보도해\s*주시기\s*바랍니다[.\s]*", "", text)
    # "보도시점" 이 앞에 남아 있을 경우
    text = re.sub(r"^보도시점\s*", "", text)

    # ── 3. 담당자 블록 제거 ──
    # "화장품정책과 담당자 사무관 유미숙(043-719-2555)" 패턴
    text = re.sub(
        r"\n.*?담당자\s+(?:사무관|연구관|서기관|주무관)\s+\S+\s*\(\d[\d\-]+\).*",
        "", text,
    )
    # "책임자 과 장 김영주(043-719-1371)" 패턴
    text = re.sub(
        r"\n.*?책임자\s+과\s*장\s+\S+\s*\(\d[\d\-]+\).*",
        "", text,
    )
    # 단독 "담당자" 줄
    text = re.sub(r"\n\s*담당자\s+.*\(\d[\d\-]+\).*", "", text)
    # "담당 부서 ... 책임자 ..." 패턴
    text = re.sub(r"\n\s*담당\s*부서\s+.*$", "", text, flags=re.MULTILINE)

    # ── 4. 페이지 번호 제거 ──
    # "- 1 -", "- 2 -" 등
    text = re.sub(r"\n?\s*-\s*\d+\s*-\s*\n?", "\n", text)

    # ── 5. 식약처 서명/꼬리말 ──
    # "ü국내·외 최신 화장품 규제 동향..." 같은 홍보 문구
    text = re.sub(r"[üv✓►▸]\s*국내.*$", "", text, flags=re.MULTILINE)
    # "▸(누리집) https://..." 홍보 링크
    text = re.sub(r"[►▸]\s*\(누리집\).*$", "", text, flags=re.MULTILINE)

    # ── 6. PDF 추출 아티팩트 정리 ──
    # 연속 공백/빈줄
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 줄 끝 불필요 공백
    text = re.sub(r"[ \t]+\n", "\n", text)

    return text.strip()
