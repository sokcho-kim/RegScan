"""bioRxiv/medRxiv 프리프린트 파서"""

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BioRxivParser:
    """bioRxiv/medRxiv 프리프린트 파서

    API 응답을 정규화된 dict로 변환합니다.
    """

    def parse_preprint(self, raw: dict[str, Any]) -> dict[str, Any]:
        """프리프린트 파싱

        Args:
            raw: bioRxiv API 응답의 단일 항목

        Returns:
            {doi, title, authors, abstract, server, category,
             published_date, pdf_url}
        """
        doi = raw.get("doi", "")
        title = raw.get("title", "").strip()
        authors = raw.get("authors", "")
        abstract = raw.get("abstract", "").strip()
        server = raw.get("server", "biorxiv")
        category = raw.get("category", "")
        date_str = raw.get("date", "")
        version = raw.get("version", "1")

        published_date = self._parse_date(date_str)

        # PDF URL 구성
        pdf_url = ""
        if doi:
            pdf_url = f"https://www.{server}.org/content/{doi}v{version}.full.pdf"

        return {
            "doi": doi,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "server": server,
            "category": category,
            "published_date": published_date,
            "pdf_url": pdf_url,
        }

    def parse_many(self, raw_list: list[dict]) -> list[dict]:
        """복수 프리프린트 파싱"""
        results = []
        for raw in raw_list:
            try:
                parsed = self.parse_preprint(raw)
                if parsed["doi"]:
                    results.append(parsed)
            except Exception as e:
                logger.warning("bioRxiv 파싱 실패: %s — %s", raw.get("doi", "?"), e)
        return results

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱 (YYYY-MM-DD)"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
