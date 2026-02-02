"""데이터 수집 모듈"""

from .base import BaseIngestor
from .hira import (
    CrawlConfig,
    HIRAInsuranceCriteriaIngestor,
    HIRANoticeIngestor,
    HIRAGuidelineIngestor,
    CATEGORY_MAP,
)
from .mohw import (
    MOHWPreAnnouncementIngestor,
    MOHWNoticeIngestor,
    MOHWAdminNoticeIngestor,
)

__all__ = [
    "BaseIngestor",
    "CrawlConfig",
    # HIRA
    "HIRAInsuranceCriteriaIngestor",
    "HIRANoticeIngestor",
    "HIRAGuidelineIngestor",
    "CATEGORY_MAP",
    # MOHW
    "MOHWPreAnnouncementIngestor",
    "MOHWNoticeIngestor",
    "MOHWAdminNoticeIngestor",
]
