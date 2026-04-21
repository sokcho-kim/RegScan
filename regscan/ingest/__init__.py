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
from .khidi import KHIDIIngestor, KHIDIBriefIngestor, KHIDIReportIngestor
from .kdca import KDCAIngestor
from .orange_book import (
    OrangeBookClient,
    FDAOrangeBookIngestor,
    FDAPatentExpiryIngestor,
)
from .purple_book import (
    PurpleBookClient,
    FDAPurpleBookIngestor,
    FDABiologicExpiryIngestor,
)
from .mfds_safety import (
    MFDSSafetyClient,
    MFDSSafetyLetterIngestor,
    MFDSRecallIngestor,
)
from .nice import (
    NICEClient,
    NICETAIngestor,
    NICERecentTAIngestor,
)
from .pmda import (
    PMDAReviewIngestor,
    PMDASafetyIngestor,
    PMDAAllIngestor,
)
from .mohw_insurance import MOHWHealthInsuranceIngestor

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
    # KHIDI
    "KHIDIIngestor",
    "KHIDIBriefIngestor",
    "KHIDIReportIngestor",
    # KDCA
    "KDCAIngestor",
    # FDA Orange Book
    "OrangeBookClient",
    "FDAOrangeBookIngestor",
    "FDAPatentExpiryIngestor",
    # FDA Purple Book
    "PurpleBookClient",
    "FDAPurpleBookIngestor",
    "FDABiologicExpiryIngestor",
    # MFDS Safety
    "MFDSSafetyClient",
    "MFDSSafetyLetterIngestor",
    "MFDSRecallIngestor",
    # NICE HTA
    "NICEClient",
    "NICETAIngestor",
    "NICERecentTAIngestor",
    # PMDA (Japan)
    "PMDAReviewIngestor",
    "PMDASafetyIngestor",
    "PMDAAllIngestor",
    # MOHW Health Insurance
    "MOHWHealthInsuranceIngestor",
]
