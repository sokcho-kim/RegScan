"""Feed Card 데이터 모델"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """데이터 소스 유형"""

    # 국내
    HIRA_NOTICE = "HIRA_NOTICE"  # 심평원 공지
    HIRA_GUIDELINE = "HIRA_GUIDELINE"  # 심사지침
    MOHW_NOTICE = "MOHW_NOTICE"  # 복지부 고시
    MOHW_ADMIN_NOTICE = "MOHW_ADMIN_NOTICE"  # 행정예고

    # 글로벌 규제
    FDA_APPROVAL = "FDA_APPROVAL"  # FDA 승인
    FDA_GUIDANCE = "FDA_GUIDANCE"  # FDA 가이드라인
    EMA_MEDICINE = "EMA_MEDICINE"  # EMA 의약품 승인
    EMA_ORPHAN = "EMA_ORPHAN"  # EMA 희귀의약품 지정
    EMA_SHORTAGE = "EMA_SHORTAGE"  # EMA 공급 부족
    EMA_SAFETY = "EMA_SAFETY"  # EMA 안전성 통신 (DHPC)
    CMS_COVERAGE = "CMS_COVERAGE"  # CMS 급여 결정

    # 학술 (Phase 2)
    PUBMED_ABSTRACT = "PUBMED_ABSTRACT"
    PREPRINT = "PREPRINT"


class ChangeType(str, Enum):
    """변경 유형"""

    NEW = "NEW"  # 신규
    REVISED = "REVISED"  # 개정
    DELETED = "DELETED"  # 삭제/폐지
    INFO = "INFO"  # 단순 정보


class Domain(str, Enum):
    """도메인"""

    DRUG = "DRUG"  # 약제
    PROCEDURE = "PROCEDURE"  # 행위/시술
    MATERIAL = "MATERIAL"  # 재료
    CRITERIA = "CRITERIA"  # 심사기준
    REIMBURSEMENT = "REIMBURSEMENT"  # 급여/수가
    SAFETY = "SAFETY"  # 안전성
    EFFICACY = "EFFICACY"  # 유효성


class ImpactLevel(str, Enum):
    """영향도"""

    HIGH = "HIGH"  # 즉시 확인 필요
    MID = "MID"  # 참고 권장
    LOW = "LOW"  # 일반 정보


class Role(str, Enum):
    """대상 역할"""

    REVIEWER_NURSE = "REVIEWER_NURSE"  # 심사간호사
    PHYSICIAN = "PHYSICIAN"  # 의사
    ADMIN = "ADMIN"  # 원무/경영진
    PHARMACIST = "PHARMACIST"  # 약사


class Citation(BaseModel):
    """출처 메타데이터"""

    source_id: str = Field(..., description="원문 문서 ID (고시번호 등)")
    source_url: str = Field(..., description="원문 URL")
    source_title: str = Field(..., description="원문 제목")
    version: Optional[str] = Field(None, description="버전")
    section_ref: Optional[str] = Field(None, description="섹션/조항 참조")
    snapshot_date: str = Field(..., description="스냅샷 시점 (YYYY-MM-DD)")


class FeedCard(BaseModel):
    """메인화면 피드 카드"""

    # 식별
    id: str = Field(..., description="고유 ID")
    source_type: SourceType = Field(..., description="데이터 소스")

    # 콘텐츠
    title: str = Field(..., max_length=50, description="카드 제목")
    summary: str = Field(..., max_length=100, description="요약")
    why_it_matters: str = Field(..., max_length=80, description="왜 중요한가 (1문장)")

    # 분류
    change_type: ChangeType = Field(..., description="변경 유형")
    domain: list[Domain] = Field(..., description="도메인")
    impact_level: ImpactLevel = Field(..., description="영향도")

    # 시간
    published_at: datetime = Field(..., description="원문 발행일")
    effective_at: Optional[datetime] = Field(None, description="적용일")
    collected_at: datetime = Field(..., description="수집 시점")

    # 출처
    citation: Citation = Field(..., description="출처 메타데이터")

    # 개인화 태그 (Phase 2)
    tags: list[str] = Field(default_factory=list, description="태그")
    target_roles: list[Role] = Field(default_factory=list, description="대상 역할")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
