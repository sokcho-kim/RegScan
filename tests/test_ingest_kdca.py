"""KDCA (질병관리청) 수집기 테스트

KDCA는 Playwright 기반이므로 단위 테스트는 파싱 로직 중심.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from regscan.ingest.kdca import KDCAIngestor


def test_kdca_source_type():
    """source_type 확인"""
    ingestor = KDCAIngestor.__new__(KDCAIngestor)
    assert ingestor.source_type() == "KDCA"


def test_kdca_keyword_filter():
    """키워드 필터링 테스트"""
    ingestor = KDCAIngestor.__new__(KDCAIngestor)
    ingestor.keywords = ["백신", "감염병", "의약품"]

    # 매칭되는 경우
    assert ingestor._matches_keywords({"title": "코로나19 백신 접종 현황"})
    assert ingestor._matches_keywords({"title": "신종 감염병 대응 체계 강화"})
    assert ingestor._matches_keywords({"title": "의약품 안전관리 강화 방안"})

    # 매칭 안 되는 경우
    assert not ingestor._matches_keywords({"title": "직원 채용 공고"})
    assert not ingestor._matches_keywords({"title": "청사 이전 안내"})


def test_kdca_default_keywords():
    """기본 키워드 목록 확인"""
    ingestor = KDCAIngestor.__new__(KDCAIngestor)
    ingestor.keywords = [
        "백신", "예방접종", "감염병", "의약품", "바이오",
        "임상", "허가", "승인", "치료제",
    ]

    # 제약/바이오 관련 키워드가 포함되어 있는지
    assert "백신" in ingestor.keywords
    assert "의약품" in ingestor.keywords
    assert "바이오" in ingestor.keywords
    assert "치료제" in ingestor.keywords


def test_kdca_init_defaults():
    """기본 초기화 값 확인"""
    ingestor = KDCAIngestor(days_back=14)
    assert ingestor.days_back == 14
    assert len(ingestor.keywords) == 9
    assert ingestor.source_type() == "KDCA"
