"""보건복지부 데이터 수집"""

from typing import Any

from .base import BaseIngestor


class MOHWNoticeIngestor(BaseIngestor):
    """복지부 고시 수집"""

    BASE_URL = "https://www.mohw.go.kr"

    def source_type(self) -> str:
        return "MOHW_NOTICE"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        복지부 고시 수집

        TODO: 실제 구현
        - 법령정보센터 연동
        - 건강보험 관련 고시 필터링
        """
        return []


class MOHWAdminNoticeIngestor(BaseIngestor):
    """행정예고 수집"""

    # 행정예고 통합 시스템
    BASE_URL = "https://www.lawmaking.go.kr"

    def source_type(self) -> str:
        return "MOHW_ADMIN_NOTICE"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        행정예고 수집

        TODO: 실제 구현
        - 입법예고 시스템 API 또는 크롤링
        - 보건복지부 필터
        - 의견제출 기한 추출
        """
        return []
