"""수집기 베이스 클래스"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        **kwargs,
    ) -> httpx.Response:
        """HTTP 요청 + 재시도 (정부 사이트 TLS 불안정 대응).

        Args:
            method: "GET" or "POST"
            url: 요청 URL
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간 대기 (초)
            **kwargs: httpx 요청 파라미터
        """
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await self.client.request(
                    method, url, follow_redirects=True, **kwargs,
                )
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ReadError) as e:
                last_error = e
                if attempt < max_retries:
                    logger.debug(
                        "[%s] 연결 실패 (시도 %d/%d), %s초 후 재시도: %s",
                        self.source_type(), attempt, max_retries,
                        retry_delay, type(e).__name__,
                    )
                    await asyncio.sleep(retry_delay)
        raise last_error
