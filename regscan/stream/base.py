"""Stream 기본 클래스 및 결과 모델"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StreamResult:
    """단일 스트림 실행 결과"""

    stream_name: str
    sub_category: str = ""  # e.g. "oncology" for therapeutic stream
    drugs_found: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    collected_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def drug_count(self) -> int:
        return len(self.drugs_found)

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def inn_list(self) -> list[str]:
        return [d.get("inn", "") for d in self.drugs_found if d.get("inn")]


class BaseStream(ABC):
    """스트림 추상 클래스 — 모든 스트림이 구현해야 함"""

    @property
    @abstractmethod
    def stream_name(self) -> str:
        """스트림 식별자 (e.g. 'therapeutic_area', 'innovation', 'external')"""
        ...

    @abstractmethod
    async def collect(self) -> list[StreamResult]:
        """데이터 수집 실행 → StreamResult 리스트 반환

        치료영역 스트림은 영역별로 여러 StreamResult를 반환할 수 있음.
        """
        ...
