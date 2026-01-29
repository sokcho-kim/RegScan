"""모델 테스트"""

from datetime import datetime

from regscan.models import (
    ChangeType,
    Citation,
    Domain,
    FeedCard,
    ImpactLevel,
    Role,
    SourceType,
)


def test_feed_card_creation():
    """FeedCard 생성 테스트"""
    citation = Citation(
        source_id="복지부고시 제2026-12호",
        source_url="https://www.mohw.go.kr/example",
        source_title="건강보험 행위 급여 목록표 일부개정",
        snapshot_date="2026-01-29",
    )

    card = FeedCard(
        id="card-20260129-001",
        source_type=SourceType.MOHW_NOTICE,
        title="무릎관절 인공관절 재료대 급여기준 개정",
        summary="인공관절 재료대 급여 상한금액 조정",
        why_it_matters="정형외과 인공관절 수술 청구에 직접 영향",
        change_type=ChangeType.REVISED,
        domain=[Domain.MATERIAL, Domain.REIMBURSEMENT],
        impact_level=ImpactLevel.HIGH,
        published_at=datetime(2026, 1, 28, 9, 0, 0),
        collected_at=datetime.now(),
        citation=citation,
        tags=["정형외과", "인공관절"],
        target_roles=[Role.REVIEWER_NURSE, Role.ADMIN],
    )

    assert card.id == "card-20260129-001"
    assert card.source_type == SourceType.MOHW_NOTICE
    assert card.impact_level == ImpactLevel.HIGH
    assert len(card.domain) == 2
    assert Domain.MATERIAL in card.domain


def test_feed_card_json():
    """FeedCard JSON 변환 테스트"""
    citation = Citation(
        source_id="test-001",
        source_url="https://example.com",
        source_title="테스트 문서",
        snapshot_date="2026-01-29",
    )

    card = FeedCard(
        id="card-test-001",
        source_type=SourceType.HIRA_NOTICE,
        title="테스트 카드",
        summary="테스트 요약",
        why_it_matters="테스트 중요도",
        change_type=ChangeType.NEW,
        domain=[Domain.DRUG],
        impact_level=ImpactLevel.LOW,
        published_at=datetime(2026, 1, 29),
        collected_at=datetime(2026, 1, 29),
        citation=citation,
    )

    json_data = card.model_dump_json()
    assert "card-test-001" in json_data
    assert "HIRA_NOTICE" in json_data
