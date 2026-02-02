"""HIRA 파이프라인 테스트"""

import pytest
from datetime import datetime

from regscan.parse.hira_parser import HIRAParser
from regscan.ingest.hira import CrawlConfig, CATEGORY_MAP


# =============================================================================
# HIRA Parser 테스트
# =============================================================================

class TestHIRAParser:
    """HIRA 파서 테스트"""

    @pytest.fixture
    def parser(self):
        return HIRAParser()

    def test_parse_notice_basic(self, parser):
        """기본 고시 파싱 테스트"""
        raw = {
            "title": "약제 급여목록 및 급여상한금액표 고시 제2025-123호 일부개정",
            "content": "1. 개정 이유\n약제 급여기준 변경...\n2. 주요 내용\n...",
            "publication_date": "2025-01-20",
            "url": "https://www.hira.or.kr/popup?id=123",
            "category": "고시",
            "meta": {
                "게시일": "2025-01-20",
                "관련근거": "국민건강보험법 시행규칙",
            },
            "files": [
                {"filename": "고시문.hwp", "url": "https://example.com/file.hwp"}
            ],
            "collected_at": "2025-01-20T10:00:00",
        }

        result = parser.parse(raw)

        assert result["title"] == raw["title"]
        assert result["category"] == "고시"
        assert result["notification_number"] == "고시 제2025-123호"
        assert result["change_type"] == "REVISED"  # 일부개정
        assert result["domain"] == "DRUG"  # 약제 키워드
        assert result["has_attachment"] is True

    def test_parse_date_formats(self, parser):
        """다양한 날짜 포맷 테스트"""
        # YYYY-MM-DD
        raw1 = {"publication_date": "2025-01-20", "title": "테스트"}
        result1 = parser.parse(raw1)
        assert result1["publication_date"] == datetime(2025, 1, 20)

        # YYYY.MM.DD
        raw2 = {"publication_date": "2025.01.20", "title": "테스트"}
        result2 = parser.parse(raw2)
        assert result2["publication_date"] == datetime(2025, 1, 20)

        # YYYYMMDD
        raw3 = {"publication_date": "20250120", "title": "테스트"}
        result3 = parser.parse(raw3)
        assert result3["publication_date"] == datetime(2025, 1, 20)

    def test_infer_change_type_new(self, parser):
        """신규 변경 유형 추론"""
        raw = {
            "title": "신규 급여 항목 신설 고시",
            "content": "새로운 항목을 신설합니다.",
        }
        result = parser.parse(raw)
        assert result["change_type"] == "NEW"

    def test_infer_change_type_revised(self, parser):
        """개정 변경 유형 추론"""
        raw = {
            "title": "급여기준 일부개정",
            "content": "기존 기준을 개정합니다.",
        }
        result = parser.parse(raw)
        assert result["change_type"] == "REVISED"

    def test_infer_change_type_deleted(self, parser):
        """폐지 변경 유형 추론"""
        raw = {
            "title": "급여 항목 폐지 고시",
            "content": "해당 항목을 삭제합니다.",
        }
        result = parser.parse(raw)
        assert result["change_type"] == "DELETED"

    def test_infer_domain_drug(self, parser):
        """약제 도메인 추론"""
        raw = {"title": "약제 급여목록 변경", "content": ""}
        result = parser.parse(raw)
        assert result["domain"] == "DRUG"

    def test_infer_domain_procedure(self, parser):
        """행위 도메인 추론"""
        raw = {"title": "진료행위 수가 조정", "content": ""}
        result = parser.parse(raw)
        assert result["domain"] == "PROCEDURE"

    def test_infer_domain_material(self, parser):
        """재료 도메인 추론"""
        raw = {"title": "치료재료 급여기준", "content": ""}
        result = parser.parse(raw)
        assert result["domain"] == "MATERIAL"

    def test_extract_notification_number(self, parser):
        """고시번호 추출 테스트"""
        # 제목에서 추출
        raw1 = {"title": "고시 제2025-123호 개정", "content": ""}
        result1 = parser.parse(raw1)
        assert "2025-123" in result1["notification_number"]

        # 보건복지부 고시
        raw2 = {"title": "보건복지부 고시 제2025-45호", "content": ""}
        result2 = parser.parse(raw2)
        assert "2025-45" in result2["notification_number"]

        # 메타에서 추출
        raw3 = {"title": "테스트", "meta": {"고시번호": "제2025-100호"}}
        result3 = parser.parse(raw3)
        assert result3["notification_number"] == "제2025-100호"

    def test_parse_many(self, parser):
        """배치 파싱 테스트"""
        raw_list = [
            {"title": "테스트1", "content": "내용1"},
            {"title": "테스트2", "content": "내용2"},
            {"title": "테스트3", "content": "내용3"},
        ]

        results = parser.parse_many(raw_list)

        assert len(results) == 3
        assert results[0]["title"] == "테스트1"
        assert results[2]["title"] == "테스트3"


# =============================================================================
# CrawlConfig 테스트
# =============================================================================

class TestCrawlConfig:
    """크롤링 설정 테스트"""

    def test_default_config(self):
        """기본 설정"""
        config = CrawlConfig()

        assert config.headless is True
        assert config.timeout == 30000
        assert config.page_size == 30
        assert config.days_back == 7
        assert set(config.categories) == set(CATEGORY_MAP.keys())

    def test_custom_config(self):
        """커스텀 설정"""
        config = CrawlConfig(
            headless=False,
            days_back=14,
            categories=["01", "02"],
        )

        assert config.headless is False
        assert config.days_back == 14
        assert config.categories == ["01", "02"]


# =============================================================================
# 통합 테스트 (모의)
# =============================================================================

class TestHIRAIntegration:
    """HIRA 통합 테스트 (실제 크롤링 없이)"""

    @pytest.fixture
    def mock_crawled_data(self):
        """모의 크롤링 데이터"""
        return [
            {
                "title": "요양급여의 적용기준 및 방법에 관한 세부사항 일부개정",
                "content": "1. 개정 이유: 급여기준 합리화\n2. 주요 내용: ...",
                "publication_date": "2025-01-20",
                "url": "https://www.hira.or.kr/popup?id=1",
                "category": "고시",
                "meta": {"게시일": "2025-01-20"},
                "files": [{"filename": "test.hwp", "url": "https://example.com"}],
                "collected_at": "2025-01-20T10:00:00",
                "source_type": "HIRA_CRITERIA",
            },
            {
                "title": "2025년 상반기 약가 인하 안내",
                "content": "약가 인하 관련 안내드립니다.",
                "publication_date": "2025-01-19",
                "url": "https://www.hira.or.kr/popup?id=2",
                "category": "공지사항",
                "meta": {},
                "files": [],
                "collected_at": "2025-01-20T11:00:00",
                "source_type": "HIRA_NOTICE",
            },
        ]

    def test_parse_crawled_data(self, mock_crawled_data):
        """크롤링 데이터 파싱"""
        parser = HIRAParser()
        results = parser.parse_many(mock_crawled_data)

        assert len(results) == 2

        # 첫 번째 (고시)
        assert results[0]["category"] == "고시"
        assert results[0]["change_type"] == "REVISED"
        assert results[0]["has_attachment"] is True

        # 두 번째 (공지사항)
        assert results[1]["category"] == "공지사항"
        assert results[1]["has_attachment"] is False

    def test_category_mapping(self):
        """카테고리 코드 매핑"""
        assert CATEGORY_MAP["01"] == "고시"
        assert CATEGORY_MAP["02"] == "행정해석"
        assert CATEGORY_MAP["09"] == "심사지침"
        assert CATEGORY_MAP["10"] == "심의사례공개"
        assert CATEGORY_MAP["17"] == "심사사례지침"
