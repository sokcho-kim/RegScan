"""Stream 2: 혁신지표 테스트

- FDA NME 필터 테스트
- EMA PRIME 필터 테스트
- 중복 제거 테스트
"""

import pytest
from unittest.mock import AsyncMock, patch

from regscan.stream.base import StreamResult
from regscan.stream.innovation import InnovationStream


# ── Fixtures ──

@pytest.fixture
def mock_fda_nme_response():
    """FDA NME (Type 1) mock 응답"""
    return {
        "meta": {"results": {"total": 2}},
        "results": [
            {
                "application_number": "NDA210000",
                "openfda": {
                    "generic_name": ["sotorasib"],
                    "brand_name": ["LUMAKRAS"],
                    "substance_name": ["SOTORASIB"],
                },
                "submissions": [{"submission_class_code": "1"}],
            },
            {
                "application_number": "NDA211000",
                "openfda": {
                    "generic_name": ["adagrasib"],
                    "brand_name": ["KRAZATI"],
                    "substance_name": ["ADAGRASIB"],
                },
                "submissions": [{"submission_class_code": "1"}],
            },
        ],
    }


@pytest.fixture
def mock_fda_bt_response():
    """FDA Breakthrough (code 5) mock 응답"""
    return {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "application_number": "NDA212000",
                "openfda": {
                    "generic_name": ["pirtobrutinib"],
                    "brand_name": ["JAYPIRCA"],
                    "substance_name": ["PIRTOBRUTINIB"],
                },
                "submissions": [{"submission_class_code": "5"}],
            },
        ],
    }


@pytest.fixture
def mock_ema_medicines_with_prime():
    """EMA medicines JSON with PRIME"""
    return [
        {
            "medicineName": "Zolgensma",
            "activeSubstance": "onasemnogene abeparvovec",
            "therapeuticArea": "Gene therapy",
            "primeMedicine": "Yes",
            "orphanMedicine": "Yes",
            "conditionalApproval": "No",
        },
        {
            "medicineName": "Keytruda",
            "activeSubstance": "pembrolizumab",
            "therapeuticArea": "Oncology",
            "primeMedicine": "No",
            "orphanMedicine": "No",
            "conditionalApproval": "No",
        },
    ]


@pytest.fixture
def mock_ema_orphan_designations():
    """EMA orphan designations mock"""
    return [
        {
            "activeSubstance": "nusinersen",
            "condition": "Spinal muscular atrophy",
            "inn": "nusinersen",
        },
        {
            "activeSubstance": "onasemnogene abeparvovec",
            "condition": "Spinal muscular atrophy",
            "inn": "onasemnogene abeparvovec",
        },
    ]


# ── Tests ──

class TestInnovationStream:
    def test_stream_name(self):
        stream = InnovationStream()
        assert stream.stream_name == "innovation"

    @pytest.mark.asyncio
    async def test_collect_nme(self, mock_fda_nme_response):
        """FDA NME 수집 테스트"""
        stream = InnovationStream()

        with patch("regscan.ingest.fda.FDAClient") as MockFDA:
            mock_client = AsyncMock()
            mock_client.search_by_submission_class.return_value = mock_fda_nme_response
            MockFDA.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockFDA.return_value.__aexit__ = AsyncMock(return_value=False)

            drugs = {}
            signals = []
            count = await stream._collect_fda_nme(drugs, signals)

        # NME 수집은 code "1" 와 "TYPE 1" 2회 검색 → 중복 INN은 drugs에서 제거되지만 signals에는 모두 포함
        assert count >= 2
        assert len(signals) >= 2
        assert all(s["type"] == "fda_nme" for s in signals)
        assert "sotorasib" in [s["inn"] for s in signals]

    @pytest.mark.asyncio
    async def test_collect_breakthrough(self, mock_fda_bt_response):
        """FDA Breakthrough 수집 테스트"""
        stream = InnovationStream()

        with patch("regscan.ingest.fda.FDAClient") as MockFDA:
            mock_client = AsyncMock()
            mock_client.search_by_submission_class.return_value = mock_fda_bt_response
            MockFDA.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockFDA.return_value.__aexit__ = AsyncMock(return_value=False)

            drugs = {}
            signals = []
            count = await stream._collect_fda_breakthrough(drugs, signals)

        assert count == 1
        assert signals[0]["type"] == "fda_breakthrough"
        assert signals[0]["inn"] == "pirtobrutinib"

    @pytest.mark.asyncio
    async def test_collect_ema_prime(self, mock_ema_medicines_with_prime):
        """EMA PRIME 필터 테스트"""
        stream = InnovationStream()

        with patch("regscan.ingest.ema.EMAClient") as MockEMA:
            mock_client = AsyncMock()
            mock_client.fetch_medicines.return_value = mock_ema_medicines_with_prime
            MockEMA.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockEMA.return_value.__aexit__ = AsyncMock(return_value=False)

            drugs = {}
            signals = []
            count = await stream._collect_ema_prime(drugs, signals)

        # Zolgensma만 PRIME
        assert count == 1
        assert signals[0]["type"] == "ema_prime"
        assert "onasemnogene" in signals[0]["inn"].lower()

    @pytest.mark.asyncio
    async def test_collect_ema_orphan(self, mock_ema_orphan_designations):
        """EMA Orphan 수집 테스트"""
        stream = InnovationStream()

        with patch("regscan.ingest.ema.EMAClient") as MockEMA:
            mock_client = AsyncMock()
            mock_client.fetch_orphan_designations.return_value = mock_ema_orphan_designations
            MockEMA.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockEMA.return_value.__aexit__ = AsyncMock(return_value=False)

            drugs = {}
            signals = []
            count = await stream._collect_ema_orphan(drugs, signals)

        assert count == 2
        assert all(s["type"] == "ema_orphan" for s in signals)

    def test_upsert_drug_new(self):
        """새 약물 추가"""
        stream = InnovationStream()
        drugs = {}
        stream._upsert_drug(drugs, "sotorasib", "sotorasib", None, designation="NME")

        assert "sotorasib" in drugs
        assert drugs["sotorasib"]["designations"] == ["NME"]

    def test_upsert_drug_existing_adds_designation(self):
        """기존 약물에 designation 추가"""
        stream = InnovationStream()
        drugs = {
            "sotorasib": {
                "inn": "sotorasib",
                "designations": ["NME"],
                "fda_data": None,
                "ema_data": None,
            }
        }
        stream._upsert_drug(drugs, "sotorasib", "sotorasib", None, designation="breakthrough")

        assert "breakthrough" in drugs["sotorasib"]["designations"]
        assert "NME" in drugs["sotorasib"]["designations"]

    def test_upsert_drug_no_duplicate_designation(self):
        """같은 designation 중복 방지"""
        stream = InnovationStream()
        drugs = {
            "sotorasib": {
                "inn": "sotorasib",
                "designations": ["NME"],
                "fda_data": None,
                "ema_data": None,
            }
        }
        stream._upsert_drug(drugs, "sotorasib", "sotorasib", None, designation="NME")

        assert drugs["sotorasib"]["designations"].count("NME") == 1
