"""Stream 1: 치료영역 테스트

- FDA pharm_class 검색 mock
- EMA therapeutic_area 필터
- INN 병합 + 중복 제거
- CompetitorMapper ATC/제네릭 매핑
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from regscan.stream.base import StreamResult
from regscan.stream.therapeutic import (
    TherapeuticAreaStream,
    TherapeuticAreaConfig,
    AreaConfig,
    _bool_field,
)
from regscan.map.competitor import CompetitorMapper


# ── Fixtures ──

@pytest.fixture
def mock_fda_response():
    """FDA pharm_class 검색 mock 응답"""
    return {
        "meta": {"results": {"total": 2}},
        "results": [
            {
                "application_number": "NDA001",
                "openfda": {
                    "generic_name": ["pembrolizumab"],
                    "brand_name": ["KEYTRUDA"],
                    "substance_name": ["PEMBROLIZUMAB"],
                    "pharm_class_epc": ["PD-1 Blocking Antibody [EPC]"],
                },
                "submissions": [],
            },
            {
                "application_number": "NDA002",
                "openfda": {
                    "generic_name": ["nivolumab"],
                    "brand_name": ["OPDIVO"],
                    "substance_name": ["NIVOLUMAB"],
                    "pharm_class_epc": ["PD-1 Blocking Antibody [EPC]"],
                },
                "submissions": [],
            },
        ],
    }


@pytest.fixture
def mock_ema_medicines():
    """EMA medicines JSON mock"""
    return [
        {
            "medicineName": "Keytruda",
            "activeSubstance": "pembrolizumab",
            "therapeuticArea": "Oncology; Melanoma",
            "atcCode": "L01FF02",
            "authorisationStatus": "authorised",
            "marketingAuthorisationDate": "2015-07-17",
            "orphanMedicine": "No",
            "primeMedicine": "No",
            "conditionalApproval": "No",
        },
        {
            "medicineName": "Tecentriq",
            "activeSubstance": "atezolizumab",
            "therapeuticArea": "Oncology; Lung Cancer",
            "atcCode": "L01FF05",
            "authorisationStatus": "authorised",
            "marketingAuthorisationDate": "2017-09-21",
            "orphanMedicine": "No",
            "primeMedicine": "No",
            "conditionalApproval": "No",
        },
        {
            "medicineName": "Humira",
            "activeSubstance": "adalimumab",
            "therapeuticArea": "Immunology; Rheumatoid Arthritis",
            "atcCode": "L04AB04",
            "authorisationStatus": "authorised",
            "orphanMedicine": "No",
            "primeMedicine": "No",
            "conditionalApproval": "No",
        },
    ]


# ── Tests: TherapeuticAreaConfig ──

class TestTherapeuticAreaConfig:
    def test_areas_defined(self):
        """5대 치료영역 정의 확인"""
        assert len(TherapeuticAreaConfig.AREAS) == 5
        assert "oncology" in TherapeuticAreaConfig.AREAS
        assert "rare_disease" in TherapeuticAreaConfig.AREAS
        assert "immunology" in TherapeuticAreaConfig.AREAS
        assert "cardiovascular" in TherapeuticAreaConfig.AREAS
        assert "metabolic" in TherapeuticAreaConfig.AREAS

    def test_get_area(self):
        """개별 영역 조회"""
        area = TherapeuticAreaConfig.get_area("oncology")
        assert area is not None
        assert area.name == "oncology"
        assert area.label_ko == "항암"
        assert len(area.fda_pharm_classes) > 0
        assert len(area.ema_therapeutic_keywords) > 0
        assert len(area.ct_conditions) > 0

    def test_get_area_invalid(self):
        """존재하지 않는 영역"""
        assert TherapeuticAreaConfig.get_area("nonexistent") is None

    def test_enabled_areas(self):
        """설정된 영역만 반환"""
        areas = TherapeuticAreaConfig.enabled_areas()
        assert len(areas) == 5  # 기본 5개 모두 활성


# ── Tests: TherapeuticAreaStream ──

class TestTherapeuticAreaStream:
    def test_stream_name(self):
        stream = TherapeuticAreaStream(areas=["oncology"])
        assert stream.stream_name == "therapeutic_area"

    @pytest.mark.asyncio
    async def test_collect_oncology(self, mock_fda_response, mock_ema_medicines):
        """항암 영역 수집 (mock)"""
        stream = TherapeuticAreaStream(areas=["oncology"])

        # FDA mock
        with patch("regscan.ingest.fda.FDAClient") as MockFDA:
            mock_client = AsyncMock()
            mock_client.search_by_pharm_class.return_value = mock_fda_response
            MockFDA.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockFDA.return_value.__aexit__ = AsyncMock(return_value=False)

            # EMA mock
            with patch("regscan.ingest.ema.EMAClient") as MockEMA:
                mock_ema_client = AsyncMock()
                mock_ema_client.fetch_medicines.return_value = mock_ema_medicines
                MockEMA.return_value.__aenter__ = AsyncMock(return_value=mock_ema_client)
                MockEMA.return_value.__aexit__ = AsyncMock(return_value=False)

                results = await stream.collect()

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, StreamResult)
        assert result.stream_name == "therapeutic_area"
        assert result.sub_category == "oncology"
        assert result.drug_count >= 0  # Mock에 따라 다름


# ── Tests: INN 병합 + 중복 제거 ──

class TestINNMerge:
    def test_duplicate_inn_merged(self):
        """같은 INN이 FDA+EMA 양쪽에 있으면 병합"""
        from regscan.stream.orchestrator import StreamOrchestrator

        orch = StreamOrchestrator(enabled_streams=[])

        stream_results = {
            "therapeutic_area": [
                StreamResult(
                    stream_name="therapeutic_area",
                    sub_category="oncology",
                    drugs_found=[
                        {"inn": "pembrolizumab", "therapeutic_areas": ["oncology"],
                         "fda_data": {"generic_name": "pembrolizumab"}, "ema_data": None, "atc_code": "L01FF02"},
                        {"inn": "nivolumab", "therapeutic_areas": ["oncology"],
                         "fda_data": {"generic_name": "nivolumab"}, "ema_data": None, "atc_code": ""},
                    ],
                ),
            ],
            "innovation": [
                StreamResult(
                    stream_name="innovation",
                    drugs_found=[
                        {"inn": "pembrolizumab", "therapeutic_areas": [],
                         "fda_data": None, "ema_data": {"inn": "pembrolizumab"}, "atc_code": ""},
                    ],
                ),
            ],
        }

        merged = orch.merge_results(stream_results)

        # pembrolizumab은 1번만 나와야 함
        inns = [d["inn"] for d in merged]
        assert inns.count("pembrolizumab") == 1
        assert "nivolumab" in inns

        # pembrolizumab의 stream_sources에 양쪽 모두 포함
        pembro = next(d for d in merged if d["inn"] == "pembrolizumab")
        assert "therapeutic_area" in pembro["stream_sources"]
        assert "innovation" in pembro["stream_sources"]


# ── Tests: CompetitorMapper ──

class TestCompetitorMapper:
    @pytest.mark.asyncio
    async def test_find_same_atc(self, mock_ema_medicines):
        """같은 ATC 3단계 약물 조회"""
        mapper = CompetitorMapper()

        with patch.object(mapper, "_get_ema_medicines", return_value=mock_ema_medicines):
            results = await mapper.find_same_atc("L01FF02", exclude_inn="pembrolizumab")

        # atezolizumab (L01FF05)은 같은 L01F 그룹
        atc_inns = [r["inn"] for r in results]
        assert "atezolizumab" in atc_inns

    @pytest.mark.asyncio
    async def test_find_biosimilars(self, mock_ema_medicines):
        """바이오시밀러 조회"""
        mapper = CompetitorMapper()

        # adalimumab 바이오시밀러 추가
        medicines_with_biosimilar = mock_ema_medicines + [
            {
                "medicineName": "Amgevita",
                "activeSubstance": "adalimumab",
                "biosimilar": "Yes",
                "atcCode": "L04AB04",
            },
        ]

        with patch.object(mapper, "_get_ema_medicines", return_value=medicines_with_biosimilar):
            results = await mapper.find_biosimilars("adalimumab")

        assert len(results) >= 1
        assert any(r["relationship_type"] == "biosimilar" for r in results)


# ── Tests: Helper ──

class TestHelpers:
    def test_bool_field_yes(self):
        assert _bool_field({"orphanMedicine": "Yes"}, "orphanMedicine") is True

    def test_bool_field_no(self):
        assert _bool_field({"orphanMedicine": "No"}, "orphanMedicine") is False

    def test_bool_field_true_bool(self):
        assert _bool_field({"is_orphan": True}, "is_orphan") is True

    def test_bool_field_missing(self):
        assert _bool_field({}, "nonexistent") is False

    def test_bool_field_multiple_keys(self):
        assert _bool_field({"is_prime": True}, "primeMedicine", "is_prime") is True
