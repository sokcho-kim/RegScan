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
            summary=self._build_summary(parsed_data, source_type),
            why_it_matters=why_text,
            change_type=self._detect_change_type(parsed_data, source_type),
            domain=self._classify_domain(parsed_data, source_type),
            impact_level=self._assess_impact(parsed_data, source_type),
            published_at=self._parse_date(parsed_data, source_type),
            effective_at=None,
            collected_at=datetime.now(),
            citation=self._build_citation(parsed_data, source_type),
            tags=self._extract_tags(parsed_data, source_type),
            target_roles=self._identify_target_roles(parsed_data, source_type),
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

        # EMA 의약품
        if source_type == SourceType.EMA_MEDICINE:
            name = data.get("name", "")
            inn = data.get("inn", "") or data.get("active_substance", "")
            status = data.get("medicine_status", "")

            if status.lower() == "authorised":
                action = "EU 승인"
            elif status.lower() == "withdrawn":
                action = "EU 철회"
            else:
                action = "EU 결정"

            if name and inn and name.lower() != inn.lower():
                title = f"EMA, {name}({inn}) {action}"
            elif name:
                title = f"EMA, {name} {action}"
            else:
                title = f"EMA 의약품 {action}"

            return title[:50]

        # EMA 희귀의약품
        if source_type == SourceType.EMA_ORPHAN:
            name = data.get("name", "")
            return f"EMA 희귀의약품 지정: {name}"[:50]

        # EMA 공급 부족
        if source_type == SourceType.EMA_SHORTAGE:
            medicine = data.get("medicine_affected", "")
            status = data.get("shortage_status", "")
            if "ongoing" in status.lower():
                return f"EMA 공급부족 지속: {medicine}"[:50]
            return f"EMA 공급부족: {medicine}"[:50]

        # EMA 안전성
        if source_type == SourceType.EMA_SAFETY:
            name = data.get("name", "")
            dhpc_type = data.get("dhpc_type", "")
            return f"EMA 안전성 통신: {name}"[:50]

        # 기본
        return data.get("title", "정보 없음")[:50]

    def _build_summary(self, data: dict[str, Any], source_type: SourceType = None) -> str:
        """요약 생성"""
        parts = []

        # EMA 의약품
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN):
            mah = data.get("mah") or data.get("sponsor")
            if mah:
                parts.append(f"MAH: {mah}")

            therapeutic_area = data.get("therapeutic_area", "")
            if therapeutic_area:
                # 세미콜론으로 구분된 경우 첫 번째만
                area = therapeutic_area.split(";")[0].strip()
                parts.append(f"적응증: {area}")

            atc = data.get("atc_code", "")
            if atc:
                parts.append(f"ATC: {atc}")

            # 특수 지정 표시
            flags = []
            if data.get("is_orphan"):
                flags.append("희귀의약품")
            if data.get("is_biosimilar"):
                flags.append("바이오시밀러")
            if data.get("is_conditional"):
                flags.append("조건부승인")
            if data.get("is_accelerated"):
                flags.append("신속심사")
            if flags:
                parts.append(f"[{', '.join(flags)}]")

            if parts:
                return ". ".join(parts)[:100]

        # EMA 공급 부족
        if source_type == SourceType.EMA_SHORTAGE:
            inn = data.get("inn", "")
            if inn:
                parts.append(f"성분: {inn}")
            alternatives = data.get("alternatives_available", "")
            if alternatives:
                parts.append(f"대체제: {alternatives[:30]}")
            expected = data.get("expected_resolution_date", "")
            if expected:
                parts.append(f"예상해결: {expected}")
            if parts:
                return ". ".join(parts)[:100]

        # EMA 안전성
        if source_type == SourceType.EMA_SAFETY:
            substances = data.get("active_substances", "")
            if substances:
                parts.append(f"성분: {substances}")
            outcome = data.get("regulatory_outcome", "")
            if outcome:
                parts.append(f"조치: {outcome[:30]}")
            if parts:
                return ". ".join(parts)[:100]

        # FDA/기본
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

    def _detect_change_type(self, data: dict[str, Any], source_type: SourceType = None) -> ChangeType:
        """변경 유형 감지"""
        # EMA
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN):
            status = data.get("medicine_status", "").lower()
            if status == "authorised":
                return ChangeType.NEW
            elif status == "withdrawn":
                return ChangeType.DELETED
            elif "conditional" in status:
                return ChangeType.NEW
            return ChangeType.INFO

        if source_type == SourceType.EMA_SHORTAGE:
            return ChangeType.INFO

        if source_type == SourceType.EMA_SAFETY:
            return ChangeType.REVISED  # 안전성 정보는 보통 개정

        # FDA
        submission_type = data.get("submission_type", "")

        mapping = {
            "ORIG": ChangeType.NEW,       # Original Application
            "SUPPL": ChangeType.REVISED,  # Supplement
            "ABBREV": ChangeType.NEW,     # Abbreviated (Generic)
            "NDA": ChangeType.NEW,
            "BLA": ChangeType.NEW,
        }

        return mapping.get(submission_type, ChangeType.INFO)

    def _classify_domain(self, data: dict[str, Any], source_type: SourceType = None) -> list[Domain]:
        """도메인 분류"""
        domains = [Domain.DRUG]  # 기본적으로 DRUG

        # EMA 안전성
        if source_type == SourceType.EMA_SAFETY:
            domains = [Domain.DRUG, Domain.SAFETY]
            return domains

        # EMA 공급 부족
        if source_type == SourceType.EMA_SHORTAGE:
            domains = [Domain.DRUG, Domain.REIMBURSEMENT]  # 공급 이슈는 급여에 영향
            return domains

        # EMA 의약품/희귀의약품
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN):
            therapeutic_area = data.get("therapeutic_area", "").lower()
            pharm_group = data.get("pharmacotherapeutic_group", "").lower()
            search_text = therapeutic_area + " " + pharm_group

            if any(kw in search_text for kw in ["safety", "risk"]):
                domains.append(Domain.SAFETY)
            if any(kw in search_text for kw in ["efficacy", "effective"]):
                domains.append(Domain.EFFICACY)
            return domains

        # FDA
        pharm_class = " ".join(data.get("pharm_class", [])).lower()
        generic = data.get("generic_name", "").lower()
        search_text = pharm_class + " " + generic

        # 키워드 기반 추가 도메인
        if any(kw in search_text for kw in ["safety", "risk", "warning"]):
            domains.append(Domain.SAFETY)
        if any(kw in search_text for kw in ["efficacy", "effective", "clinical"]):
            domains.append(Domain.EFFICACY)

        return domains

    def _assess_impact(self, data: dict[str, Any], source_type: SourceType = None) -> ImpactLevel:
        """영향도 평가"""
        # EMA 의약품
        if source_type == SourceType.EMA_MEDICINE:
            # 높은 영향도
            if data.get("is_orphan"):
                return ImpactLevel.HIGH
            if data.get("is_accelerated"):
                return ImpactLevel.HIGH
            if data.get("is_prime"):
                return ImpactLevel.HIGH
            if data.get("is_conditional"):
                return ImpactLevel.HIGH
            if data.get("is_advanced_therapy"):
                return ImpactLevel.HIGH

            # 중간 영향도
            therapeutic_area = data.get("therapeutic_area", "").lower()
            if any(kw in therapeutic_area for kw in ["cancer", "neoplasm", "oncolog"]):
                return ImpactLevel.MID
            if data.get("is_biosimilar"):
                return ImpactLevel.MID

            return ImpactLevel.LOW

        # EMA 희귀의약품
        if source_type == SourceType.EMA_ORPHAN:
            return ImpactLevel.HIGH  # 희귀의약품 지정은 항상 HIGH

        # EMA 공급 부족
        if source_type == SourceType.EMA_SHORTAGE:
            if data.get("is_ongoing"):
                return ImpactLevel.HIGH  # 진행 중인 부족은 HIGH
            return ImpactLevel.MID

        # EMA 안전성
        if source_type == SourceType.EMA_SAFETY:
            return ImpactLevel.HIGH  # 안전성 이슈는 항상 HIGH

        # FDA
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

    def _parse_date(self, data: dict[str, Any], source_type: SourceType = None) -> datetime:
        """날짜 파싱"""
        # EMA
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN,
                          SourceType.EMA_SHORTAGE, SourceType.EMA_SAFETY):
            # EMA 파서에서 이미 YYYY-MM-DD로 변환됨
            date_str = (data.get("approval_date") or
                       data.get("marketing_authorisation_date") or
                       data.get("designation_date") or
                       data.get("start_date") or
                       data.get("dissemination_date") or "")

            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    pass

            return datetime.now()

        # FDA
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

    def _extract_tags(self, data: dict[str, Any], source_type: SourceType = None) -> list[str]:
        """태그 추출"""
        tags = []

        # EMA
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN,
                          SourceType.EMA_SHORTAGE, SourceType.EMA_SAFETY):
            # MAH
            mah = data.get("mah") or data.get("sponsor")
            if mah:
                tags.append(mah)

            # ATC 코드
            atc = data.get("atc_code")
            if atc:
                tags.append(atc)

            # INN/성분명
            inn = data.get("inn") or data.get("active_substance") or data.get("generic_name")
            if inn:
                tags.append(inn)

            # 치료영역 (첫 번째만)
            therapeutic_area = data.get("therapeutic_area", "")
            if therapeutic_area:
                first_area = therapeutic_area.split(";")[0].strip()
                if first_area:
                    tags.append(first_area)

            # 특수 지정
            if data.get("is_orphan"):
                tags.append("Orphan")
            if data.get("is_biosimilar"):
                tags.append("Biosimilar")
            if data.get("is_accelerated"):
                tags.append("Accelerated")

            return tags[:10]

        # FDA/기본
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

    def _identify_target_roles(self, data: dict[str, Any], source_type: SourceType = None) -> list[Role]:
        """대상 역할 식별"""
        roles = [Role.PHYSICIAN, Role.PHARMACIST]  # 기본

        # EMA
        if source_type in (SourceType.EMA_MEDICINE, SourceType.EMA_ORPHAN):
            therapeutic_area = data.get("therapeutic_area", "").lower()

            # 고가 약제 = 경영진 관심
            if any(kw in therapeutic_area for kw in ["cancer", "neoplasm", "oncolog"]):
                roles.append(Role.ADMIN)
            if data.get("is_orphan"):
                roles.append(Role.ADMIN)  # 희귀의약품도 고가
            if data.get("is_advanced_therapy"):
                roles.append(Role.ADMIN)  # 첨단치료제도 고가

            return roles

        if source_type == SourceType.EMA_SHORTAGE:
            # 공급 부족은 원무팀도 관심
            roles.append(Role.ADMIN)
            return roles

        if source_type == SourceType.EMA_SAFETY:
            # 안전성 이슈는 심사간호사도 관심
            roles.append(Role.REVIEWER_NURSE)
            return roles

        # FDA
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
