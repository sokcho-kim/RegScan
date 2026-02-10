"""Health.kr 전문가 리뷰 파서"""

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HealthKRParser:
    """Health.kr 리뷰 파서

    raw 데이터를 정규화된 dict로 변환합니다.
    """

    def parse_review(self, raw: dict[str, Any]) -> dict[str, Any]:
        """리뷰 파싱

        Args:
            raw: HealthKRClient에서 수집한 raw dict

        Returns:
            {title, source, author, summary, published_date, source_url, raw_data}
        """
        return {
            "title": raw.get("title", ""),
            "source": raw.get("source", "KPIC"),
            "author": raw.get("author", ""),
            "summary": raw.get("summary", ""),
            "published_date": self._parse_date(raw.get("date_str", "")),
            "source_url": raw.get("source_url", ""),
            "raw_data": raw,
        }

    def parse_many(self, raw_list: list[dict]) -> list[dict]:
        """복수 리뷰 파싱"""
        results = []
        for raw in raw_list:
            try:
                results.append(self.parse_review(raw))
            except Exception as e:
                logger.warning("Health.kr 파싱 실패: %s — %s", raw.get("title", "?"), e)
        return results

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None
        date_str = date_str.strip()
        for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
