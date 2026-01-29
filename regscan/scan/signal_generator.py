"""Signal 생성기 - 원본 데이터를 FeedCard로 변환"""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from regscan.models import (
    ChangeType,
    Citation,
    Domain,
    FeedCard,
    ImpactLevel,
    Role,
    SourceType,
)
from .why_it_matters import WhyItMattersGenerator


class SignalGenerator:
    """원본 데이터 → FeedCard 변환"""

    def __init__(self, use_llm: bool = True):
        self.why_generator = WhyItMattersGenerator(use_llm=use_llm)
        self._why_it_matters_method: Optional[str] = None

    async def generate(
        self,
        parsed_data: dict[str, Any],
        source_type: SourceType,
    ) -> FeedCard:
        """
        파싱된 데이터를 FeedCard로 변환

        Args:
            parsed_data: 파서에서 변환된 중간 형식 데이터
            source_type: 데이터 소스 유형

        Returns:
            FeedCard 인스턴스
        """
        # why_it_matters 생성
        why_text, why_method = await self.why_generator.generate(parsed_data)
        self._why_it_matters_method = why_method

        return FeedCard(
            id=self._generate_id(source_type),
            source_type=source_type,
            title=self._build_title(parsed_data, source_type),
            summary=self._build_summary(parsed_data),
            why_it_matters=why_text,
            change_type=self._detect_change_type(parsed_data),
            domain=self._classify_domain(parsed_data),
            impact_level=self._assess_impact(parsed_data),
            published_at=self._parse_date(parsed_data),
            effective_at=None,
            collected_at=datetime.now(),
            citation=self._build_citation(parsed_data, source_type),
            tags=self._extract_tags(parsed_data),
            target_roles=self._identify_target_roles(parsed_data),
        )

    @property
    def last_why_method(self) -> Optional[str]:
        """마지막 why_it_matters 생성 방법"""
        return self._why_it_matters_method

    def _generate_id(self, source_type: SourceType) -> str:
        """고유 ID 생성"""
        today = datetime.now().strftime("%Y%m%d")
        prefix = source_type.value.lower().replace("_", "-")
        return f"card-{today}-{prefix}-{uuid4().hex[:8]}"

    def _build_title(self, data: dict[str, Any], source_type: SourceType) -> str:
        """제목 생성"""
        if source_type == SourceType.FDA_APPROVAL:
            brand = data.get("brand_name", "")
            generic = data.get("generic_name", "")
            submission_type = data.get("submission_type", "")

            if submission_type == "ORIG":
                action = "신규 승인"
            elif submission_type == "SUPPL":
                action = "적응증 추가"
            else:
                action = "승인"

            if brand and generic:
                title = f"FDA, {brand}({generic}) {action}"
            elif brand:
                title = f"FDA, {brand} {action}"
            else:
                title = f"FDA 의약품 {action}"

            return title[:50]

        # 기본
        return data.get("title", "정보 없음")[:50]

    def _build_summary(self, data: dict[str, Any]) -> str:
        """요약 생성"""
        parts = []

        sponsor = data.get("sponsor")
        if sponsor:
            parts.append(f"제약사: {sponsor}")

        dosage_form = data.get("dosage_form")
        if dosage_form:
            parts.append(f"제형: {dosage_form}")

        pharm_class = data.get("pharm_class", [])
        if pharm_class:
            parts.append(f"분류: {pharm_class[0]}")

        if parts:
            return ". ".join(parts)[:100]

        return data.get("summary", "")[:100]

    def _detect_change_type(self, data: dict[str, Any]) -> ChangeType:
        """변경 유형 감지"""
        submission_type = data.get("submission_type", "")

        mapping = {
            "ORIG": ChangeType.NEW,       # Original Application
            "SUPPL": ChangeType.REVISED,  # Supplement
            "ABBREV": ChangeType.NEW,     # Abbreviated (Generic)
            "NDA": ChangeType.NEW,
            "BLA": ChangeType.NEW,
        }

        return mapping.get(submission_type, ChangeType.INFO)

    def _classify_domain(self, data: dict[str, Any]) -> list[Domain]:
        """도메인 분류"""
        domains = [Domain.DRUG]  # FDA 승인은 기본적으로 DRUG

        pharm_class = " ".join(data.get("pharm_class", [])).lower()
        generic = data.get("generic_name", "").lower()
        search_text = pharm_class + " " + generic

        # 키워드 기반 추가 도메인
        if any(kw in search_text for kw in ["safety", "risk", "warning"]):
            domains.append(Domain.SAFETY)
        if any(kw in search_text for kw in ["efficacy", "effective", "clinical"]):
            domains.append(Domain.EFFICACY)

        return domains

    def _assess_impact(self, data: dict[str, Any]) -> ImpactLevel:
        """영향도 평가"""
        submission_type = data.get("submission_type", "")
        submission_class = data.get("submission_class_code", "")
        pharm_class = " ".join(data.get("pharm_class", [])).lower()

        # 높은 영향도
        if submission_type == "ORIG":  # 신약
            return ImpactLevel.HIGH
        if "orphan" in pharm_class or "rare" in pharm_class:  # 희귀의약품
            return ImpactLevel.HIGH
        if submission_class in ["1", "2"]:  # Priority Review
            return ImpactLevel.HIGH

        # 중간 영향도
        if submission_type == "SUPPL":  # 적응증 추가
            return ImpactLevel.MID
        if any(kw in pharm_class for kw in ["cancer", "oncolog", "antineoplastic"]):
            return ImpactLevel.MID

        # 기본값
        return ImpactLevel.LOW

    def _parse_date(self, data: dict[str, Any]) -> datetime:
        """날짜 파싱"""
        date_str = data.get("submission_status_date", "")

        if date_str:
            try:
                # FDA 날짜 형식: YYYYMMDD
                return datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                pass

        return datetime.now()

    def _build_citation(self, data: dict[str, Any], source_type: SourceType) -> Citation:
        """Citation 메타데이터 구성"""
        return Citation(
            source_id=data.get("application_number", data.get("source_id", "unknown")),
            source_url=data.get("source_url", ""),
            source_title=self._build_title(data, source_type),
            version=data.get("submission_type"),
            snapshot_date=datetime.now().strftime("%Y-%m-%d"),
        )

    def _extract_tags(self, data: dict[str, Any]) -> list[str]:
        """태그 추출"""
        tags = []

        # 제약사
        sponsor = data.get("sponsor")
        if sponsor:
            tags.append(sponsor)

        # 약리학적 분류
        pharm_class = data.get("pharm_class", [])
        tags.extend(pharm_class[:3])

        # 성분명
        generic = data.get("generic_name")
        if generic:
            tags.append(generic)

        return tags[:10]  # 최대 10개

    def _identify_target_roles(self, data: dict[str, Any]) -> list[Role]:
        """대상 역할 식별"""
        roles = [Role.PHYSICIAN, Role.PHARMACIST]  # FDA 승인은 기본

        pharm_class = " ".join(data.get("pharm_class", [])).lower()

        # 특수 분류에 따른 추가 역할
        if any(kw in pharm_class for kw in ["oncolog", "cancer"]):
            roles.append(Role.ADMIN)  # 고가 약제 = 경영진 관심

        return roles


async def generate_feed_cards(
    parsed_data_list: list[dict[str, Any]],
    source_type: SourceType,
    use_llm: bool = True,
) -> list[tuple[FeedCard, str]]:
    """
    여러 데이터를 FeedCard로 변환

    Returns:
        list of (FeedCard, why_method)
    """
    generator = SignalGenerator(use_llm=use_llm)
    results = []

    for data in parsed_data_list:
        card = await generator.generate(data, source_type)
        results.append((card, generator.last_why_method))

    return results
