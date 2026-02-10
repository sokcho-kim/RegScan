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
from .ema import (
    EMAClient,
    EMAEndpoint,
    EMAMedicineIngestor,
    EMAOrphanIngestor,
    EMAShortageIngestor,
    EMASafetyIngestor,
    fetch_ema_medicines,
    fetch_ema_all,
)
from .mfds import (
    MFDSClient,
    MFDSPermitIngestor,
    MFDSNewDrugIngestor,
)
from .cris import (
    CRISClient,
    CRISTrialIngestor,
    CRISActiveTrialIngestor,
    CRISDrugTrialIngestor,
)
from .asti import ASTIClient, ASTIIngestor
from .healthkr import HealthKRClient, HealthKRIngestor
from .biorxiv import BioRxivClient, BioRxivIngestor

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
    # EMA
    "EMAClient",
    "EMAEndpoint",
    "EMAMedicineIngestor",
    "EMAOrphanIngestor",
    "EMAShortageIngestor",
    "EMASafetyIngestor",
    "fetch_ema_medicines",
    "fetch_ema_all",
    # MFDS
    "MFDSClient",
    "MFDSPermitIngestor",
    "MFDSNewDrugIngestor",
    # CRIS
    "CRISClient",
    "CRISTrialIngestor",
    "CRISActiveTrialIngestor",
    "CRISDrugTrialIngestor",
    # v2: ASTI
    "ASTIClient",
    "ASTIIngestor",
    # v2: Health.kr
    "HealthKRClient",
    "HealthKRIngestor",
    # v2: bioRxiv
    "BioRxivClient",
    "BioRxivIngestor",
]
