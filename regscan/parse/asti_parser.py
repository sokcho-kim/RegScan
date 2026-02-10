"""ASTI 시장 리포트 파서"""

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ASTIReportParser:
    """ASTI/KISTI 리포트 파서

    raw 데이터를 정규화된 dict로 변환합니다.
    """

    def parse_report(self, raw: dict[str, Any]) -> dict[str, Any]:
        """리포트 파싱

        Args:
            raw: ASTIClient에서 수집한 raw dict

        Returns:
            {title, source, publisher, published_date,
             market_size_krw, growth_rate, summary, source_url, raw_data}
        """
        title = raw.get("title", "")
        publisher = raw.get("publisher", "")
        date_str = raw.get("date_str", "")
        source_url = raw.get("source_url", "")
        content = raw.get("content", "")

        published_date = self._parse_date(date_str)
        market_size = self._extract_market_size(title + " " + content)
        growth_rate = self._extract_growth_rate(title + " " + content)

        summary = content[:500] if content else title

        return {
            "title": title,
            "source": raw.get("source", "ASTI"),
            "publisher": publisher,
            "published_date": published_date,
            "market_size_krw": market_size,
            "growth_rate": growth_rate,
            "summary": summary,
            "source_url": source_url,
            "raw_data": raw,
        }

    def parse_many(self, raw_list: list[dict]) -> list[dict]:
        """복수 리포트 파싱"""
        results = []
        for raw in raw_list:
            try:
                results.append(self.parse_report(raw))
            except Exception as e:
                logger.warning("ASTI 파싱 실패: %s — %s", raw.get("title", "?"), e)
        return results

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱 (YYYY.MM.DD / YYYY-MM-DD 등)"""
        if not date_str:
            return None
        date_str = date_str.strip()
        for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y년 %m월 %d일"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_market_size(text: str) -> Optional[float]:
        """텍스트에서 시장 규모(억 원) 추출"""
        patterns = [
            r"(\d[\d,.]+)\s*억\s*원",
            r"시장\s*규모\s*(\d[\d,.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_growth_rate(text: str) -> Optional[float]:
        """텍스트에서 성장률(%) 추출"""
        patterns = [
            r"성장률?\s*(\d+\.?\d*)\s*%",
            r"(\d+\.?\d*)\s*%\s*성장",
            r"CAGR\s*(\d+\.?\d*)\s*%",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None
