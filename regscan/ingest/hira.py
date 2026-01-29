"""HIRA (심평원) 데이터 수집"""

from typing import Any

from .base import BaseIngestor


class HIRANoticeIngestor(BaseIngestor):
    """심평원 공지사항 수집"""

    BASE_URL = "https://www.hira.or.kr"

    def source_type(self) -> str:
        return "HIRA_NOTICE"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        심평원 공지사항 수집

        TODO: 실제 구현
        - 공지사항 목록 페이지 크롤링
        - 상세 페이지 파싱
        - 첨부파일 메타데이터 추출
        """
        # 구현 예정
        return []


class HIRAGuidelineIngestor(BaseIngestor):
    """심사지침 수집"""

    BASE_URL = "https://www.hira.or.kr"

    def source_type(self) -> str:
        return "HIRA_GUIDELINE"

    async def fetch(self) -> list[dict[str, Any]]:
        """
        심사지침 수집

        TODO: 실제 구현
        - 심사지침 목록 조회
        - 개정 이력 추적
        """
        return []
