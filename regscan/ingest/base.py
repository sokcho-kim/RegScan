"""수집기 베이스 클래스"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx


class BaseIngestor(ABC):
    """데이터 수집기 베이스 클래스"""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Ingestor must be used as async context manager")
        return self._client

    @abstractmethod
    async def fetch(self) -> list[dict[str, Any]]:
        """원본 데이터 수집"""
        pass

    @abstractmethod
    def source_type(self) -> str:
        """소스 타입 반환"""
        pass

    def _now(self) -> datetime:
        return datetime.now()
