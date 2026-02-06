"""Google Cloud Storage 아카이브 유틸리티.

수집된 원본 JSON을 GCS에 보관한다.
GCS_BUCKET 환경변수가 비어 있으면 모든 메서드가 조용히 스킵되므로
로컬 개발 환경에서도 에러 없이 동작한다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GCSStorage:
    """GCS 원본 JSON 아카이브

    GCS_BUCKET이 비어있으면 모든 메서드가 조용히 스킵 (로컬 개발 호환).
    """

    def __init__(self, bucket_name: str = "", prefix: str = "raw/") -> None:
        self._bucket_name = bucket_name
        self._prefix = prefix

        if not bucket_name:
            self._enabled = False
            self._bucket = None
            logger.debug("GCSStorage disabled: bucket_name이 비어 있음")
            return

        # google.cloud.storage를 lazy import — 로컬에 라이브러리 없어도 안전
        try:
            from google.cloud import storage as _gcs  # noqa: WPS433

            client = _gcs.Client()
            self._bucket = client.bucket(bucket_name)
            self._enabled = True
            logger.info("GCSStorage enabled: bucket=%s, prefix=%s", bucket_name, prefix)
        except Exception:
            self._enabled = False
            self._bucket = None
            logger.warning(
                "GCSStorage disabled: google-cloud-storage 초기화 실패",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload_json(self, data: Any, path: str) -> str:
        """JSON 데이터를 GCS에 업로드.

        Returns:
            gs:// URI 문자열. disabled이면 빈 문자열.
        """
        if not self._enabled:
            return ""

        full_path = f"{self._prefix}{path}"
        blob = self._bucket.blob(full_path)  # type: ignore[union-attr]

        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        blob.upload_from_string(payload, content_type="application/json")

        uri = f"gs://{self._bucket_name}/{full_path}"
        logger.info("GCS upload 완료: %s (%d bytes)", uri, len(payload))
        return uri

    def download_json(self, path: str) -> Optional[dict]:
        """GCS에서 JSON 다운로드.

        Returns:
            파싱된 dict. disabled이거나 파일이 없으면 None.
        """
        if not self._enabled:
            return None

        full_path = f"{self._prefix}{path}"
        blob = self._bucket.blob(full_path)  # type: ignore[union-attr]

        try:
            raw = blob.download_as_bytes()
            data: dict = json.loads(raw.decode("utf-8"))
            logger.info("GCS download 완료: gs://%s/%s", self._bucket_name, full_path)
            return data
        except Exception:
            logger.warning(
                "GCS download 실패: gs://%s/%s",
                self._bucket_name,
                full_path,
                exc_info=True,
            )
            return None

    def archive_scan(self, scan_date: str, source: str, data: list) -> str:
        """수집 결과 아카이브.

        저장 경로: ``{prefix}{source}/{scan_date}.json``

        Args:
            scan_date: ISO 날짜 문자열 (예: ``2026-02-06``).
            source: 데이터 소스 이름 (예: ``fda``, ``ema``, ``mfds``).
            data: 수집된 레코드 리스트.

        Returns:
            gs:// URI 문자열. disabled이면 빈 문자열.
        """
        path = f"{source}/{scan_date}.json"
        return self.upload_json(data, path)


# ----------------------------------------------------------------------
# Module-level factory
# ----------------------------------------------------------------------


def get_gcs_storage() -> GCSStorage:
    """Settings에서 GCS_BUCKET / GCS_PREFIX를 읽어 GCSStorage 인스턴스 반환."""
    from regscan.config import settings

    return GCSStorage(
        bucket_name=settings.GCS_BUCKET,
        prefix=settings.GCS_PREFIX,
    )
