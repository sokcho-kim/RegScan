"""FDA Advisory Committee 미팅 일정 — 시드 파일 기반

openFDA에 직접 API가 없으므로 시드 파일 방식으로 관리.
향후 FDA Meetings RSS 등으로 자동화 가능.

사용법:
    client = FDAAdComClient()
    upcoming = client.get_upcoming_meetings()
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from regscan.config import settings

logger = logging.getLogger(__name__)


class FDAAdComClient:
    """FDA Advisory Committee 시드 데이터 로더"""

    def __init__(self, seed_path: Path | None = None):
        """
        Args:
            seed_path: 시드 JSON 파일 경로. None이면 기본 경로.
        """
        self._seed_path = seed_path or (
            settings.DATA_DIR / "fda" / "adcom_meetings.json"
        )
        self._meetings: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """시드 파일 로드"""
        if not self._seed_path.exists():
            logger.debug("AdCom 시드 파일 없음: %s", self._seed_path)
            return

        try:
            with open(self._seed_path, "r", encoding="utf-8") as f:
                self._meetings = json.load(f)
            logger.debug("AdCom 시드 로드: %d건", len(self._meetings))
        except Exception as e:
            logger.warning("AdCom 시드 로드 실패: %s", e)

    def get_upcoming_meetings(
        self,
        days_ahead: int = 180,
    ) -> list[dict[str, Any]]:
        """향후 N일 이내의 미팅만 반환

        Args:
            days_ahead: 앞으로 N일 이내

        Returns:
            향후 미팅 목록
        """
        today = date.today()
        upcoming: list[dict[str, Any]] = []

        for meeting in self._meetings:
            meeting_date_str = meeting.get("meeting_date", "")
            if not meeting_date_str:
                continue

            try:
                meeting_date = datetime.strptime(meeting_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if today <= meeting_date <= today.replace(
                year=today.year + (1 if today.month > 6 else 0),
            ):
                days_until = (meeting_date - today).days
                if days_until <= days_ahead:
                    entry = dict(meeting)
                    entry["days_until"] = days_until
                    upcoming.append(entry)

        # 날짜순 정렬
        upcoming.sort(key=lambda x: x.get("meeting_date", ""))
        return upcoming

    def get_all_meetings(self) -> list[dict[str, Any]]:
        """모든 미팅 반환"""
        return list(self._meetings)
