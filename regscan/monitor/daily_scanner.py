"""일간 규제 동향 스캐너

FDA/EMA/MFDS 신규 승인을 매일 체크하고 핫이슈를 판별합니다.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Any
from enum import Enum

import httpx

from regscan.config import settings

logger = logging.getLogger(__name__)


class ApprovalSource(str, Enum):
    FDA = "fda"
    EMA = "ema"
    MFDS = "mfds"


class HotIssueType(str, Enum):
    """핫이슈 유형"""
    GLOBAL_CONCURRENT = "global_concurrent"      # FDA+EMA 동시/근접 승인
    DOMESTIC_ARRIVAL = "domestic_arrival"        # 글로벌 승인 → 국내 허가
    BREAKTHROUGH = "breakthrough"                 # FDA Breakthrough Therapy
    PRIME = "prime"                              # EMA PRIME
    ORPHAN = "orphan"                            # 희귀의약품
    ACCELERATED = "accelerated"                  # 가속 승인
    HIGH_INTEREST = "high_interest"              # 고관심 적응증
    NONE = "none"                                # 일반


@dataclass
class NewApproval:
    """신규 승인 건"""
    source: ApprovalSource
    drug_name: str
    generic_name: str                            # INN
    approval_date: date
    application_number: str = ""
    indication: str = ""
    sponsor: str = ""

    # 특별 지정
    is_breakthrough: bool = False
    is_accelerated: bool = False
    is_priority: bool = False
    is_fast_track: bool = False
    is_orphan: bool = False
    is_prime: bool = False
    is_conditional: bool = False

    # 핫이슈 판정
    hot_issue_type: HotIssueType = HotIssueType.NONE
    hot_issue_score: int = 0
    hot_issue_reasons: list[str] = field(default_factory=list)

    # 기존 데이터 매칭
    matched_existing: bool = False
    existing_approvals: list[str] = field(default_factory=list)  # ["fda", "ema"] 등

    # 원본 데이터
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "drug_name": self.drug_name,
            "generic_name": self.generic_name,
            "approval_date": self.approval_date.isoformat(),
            "application_number": self.application_number,
            "indication": self.indication,
            "sponsor": self.sponsor,
            "is_breakthrough": self.is_breakthrough,
            "is_accelerated": self.is_accelerated,
            "is_orphan": self.is_orphan,
            "is_prime": self.is_prime,
            "hot_issue_type": self.hot_issue_type.value,
            "hot_issue_score": self.hot_issue_score,
            "hot_issue_reasons": self.hot_issue_reasons,
            "matched_existing": self.matched_existing,
            "existing_approvals": self.existing_approvals,
        }


@dataclass
class ScanResult:
    """일간 스캔 결과"""
    scan_date: date
    scan_time: datetime

    # 신규 승인 건
    fda_new: list[NewApproval] = field(default_factory=list)
    ema_new: list[NewApproval] = field(default_factory=list)
    mfds_new: list[NewApproval] = field(default_factory=list)

    # 핫이슈
    hot_issues: list[NewApproval] = field(default_factory=list)

    # 에러
    errors: list[str] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return len(self.fda_new) + len(self.ema_new) + len(self.mfds_new)

    @property
    def has_hot_issues(self) -> bool:
        return len(self.hot_issues) > 0

    def to_dict(self) -> dict:
        return {
            "scan_date": self.scan_date.isoformat(),
            "scan_time": self.scan_time.isoformat(),
            "summary": {
                "fda_new": len(self.fda_new),
                "ema_new": len(self.ema_new),
                "mfds_new": len(self.mfds_new),
                "total_new": self.total_new,
                "hot_issues": len(self.hot_issues),
            },
            "fda_new": [a.to_dict() for a in self.fda_new],
            "ema_new": [a.to_dict() for a in self.ema_new],
            "mfds_new": [a.to_dict() for a in self.mfds_new],
            "hot_issues": [a.to_dict() for a in self.hot_issues],
            "errors": self.errors,
        }


class DailyScanner:
    """일간 규제 동향 스캐너

    사용법:
        scanner = DailyScanner()
        scanner.load_existing_data()  # 기존 데이터 로드
        result = await scanner.scan()  # 스캔 실행

        if result.has_hot_issues:
            for issue in result.hot_issues:
                print(f"HOT: {issue.generic_name} - {issue.hot_issue_reasons}")
    """

    # 고관심 적응증 키워드
    HIGH_INTEREST_KEYWORDS = [
        "cancer", "oncology", "tumor", "carcinoma", "lymphoma", "leukemia",
        "alzheimer", "dementia", "parkinson",
        "obesity", "weight", "diabetes",
        "rare disease", "orphan",
        "gene therapy", "cell therapy", "car-t",
        "covid", "coronavirus",
    ]

    # 핫이슈 스코어 가중치
    SCORE_WEIGHTS = {
        "breakthrough": 20,
        "prime": 20,
        "accelerated": 15,
        "orphan": 15,
        "priority": 10,
        "fast_track": 10,
        "conditional": 10,
        "global_concurrent": 25,      # FDA+EMA 동시 승인
        "domestic_arrival": 30,       # 글로벌 → 국내 허가
        "high_interest_indication": 10,
    }

    HOT_ISSUE_THRESHOLD = 20  # 이 점수 이상이면 핫이슈

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(__file__).parent.parent.parent / "data"
        self._existing_drugs: dict[str, dict] = {}  # normalized_name -> data
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def load_existing_data(self) -> int:
        """기존 수집 데이터 로드 (FDA/EMA/MFDS)"""
        self._existing_drugs.clear()
        count = 0

        # FDA 데이터
        fda_files = list(self.data_dir.glob("fda/approvals_*.json"))
        if fda_files:
            fda_file = sorted(fda_files)[-1]  # 가장 최근 파일
            with open(fda_file, encoding="utf-8") as f:
                fda_data = json.load(f)
            # 리스트 또는 dict 형태 모두 지원
            fda_items = fda_data if isinstance(fda_data, list) else fda_data.get("results", [])
            for item in fda_items:
                name = self._normalize_name(
                    item.get("openfda", {}).get("generic_name", [""])[0] or
                    item.get("openfda", {}).get("brand_name", [""])[0]
                )
                if name:
                    if name not in self._existing_drugs:
                        self._existing_drugs[name] = {"approvals": [], "data": {}}
                    self._existing_drugs[name]["approvals"].append("fda")
                    self._existing_drugs[name]["data"]["fda"] = item
                    count += 1

        # EMA 데이터
        ema_files = list(self.data_dir.glob("ema/medicines_*.json"))
        if ema_files:
            ema_file = sorted(ema_files)[-1]
            with open(ema_file, encoding="utf-8") as f:
                ema_data = json.load(f)
            for item in ema_data if isinstance(ema_data, list) else ema_data.get("results", []):
                # 다양한 필드명 지원
                name = self._normalize_name(
                    item.get("international_non_proprietary_name_common_name") or
                    item.get("active_substance") or
                    item.get("inn") or
                    item.get("activeSubstance") or
                    item.get("name_of_medicine", "")
                )
                if name:
                    if name not in self._existing_drugs:
                        self._existing_drugs[name] = {"approvals": [], "data": {}}
                    if "ema" not in self._existing_drugs[name]["approvals"]:
                        self._existing_drugs[name]["approvals"].append("ema")
                        self._existing_drugs[name]["data"]["ema"] = item
                        count += 1

        # MFDS 데이터 (full 파일 우선)
        mfds_files = list(self.data_dir.glob("mfds/permits_full_*.json"))
        if not mfds_files:
            mfds_files = list(self.data_dir.glob("mfds/permits_*.json"))
        if mfds_files:
            mfds_file = sorted(mfds_files)[-1]
            with open(mfds_file, encoding="utf-8") as f:
                mfds_data = json.load(f)
            for item in mfds_data if isinstance(mfds_data, list) else mfds_data.get("results", []):
                name = self._normalize_name(item.get("ITEM_INGR_NAME", ""))
                if name:
                    if name not in self._existing_drugs:
                        self._existing_drugs[name] = {"approvals": [], "data": {}}
                    if "mfds" not in self._existing_drugs[name]["approvals"]:
                        self._existing_drugs[name]["approvals"].append("mfds")
                        self._existing_drugs[name]["data"]["mfds"] = item
                        count += 1

        logger.info(f"기존 데이터 로드 완료: {len(self._existing_drugs)}개 약물, {count}건 승인")
        return len(self._existing_drugs)

    def _normalize_name(self, name: str) -> str:
        """약물명 정규화"""
        if not name:
            return ""
        # 소문자, 공백 제거, 특수문자 제거
        normalized = name.lower().strip()
        normalized = "".join(c for c in normalized if c.isalnum())

        # 수화물 제거 (dihydrate, trihydrate 등)
        for suffix in ["dihydrate", "trihydrate", "monohydrate", "tetrahydrate", "hydrate"]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
                break

        return normalized

    async def scan(self, days_back: int = 1) -> ScanResult:
        """
        일간 스캔 실행

        Args:
            days_back: 며칠 전까지 스캔할지 (기본 1일)

        Returns:
            ScanResult
        """
        result = ScanResult(
            scan_date=date.today(),
            scan_time=datetime.now(),
        )

        # FDA 스캔
        try:
            result.fda_new = await self._scan_fda(days_back)
            logger.info(f"FDA 신규 승인: {len(result.fda_new)}건")
        except Exception as e:
            error_msg = f"FDA 스캔 실패: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        # EMA 스캔
        try:
            result.ema_new = await self._scan_ema(days_back)
            logger.info(f"EMA 신규 승인: {len(result.ema_new)}건")
        except Exception as e:
            error_msg = f"EMA 스캔 실패: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        # MFDS 스캔
        try:
            result.mfds_new = await self._scan_mfds(days_back)
            logger.info(f"MFDS 신규 허가: {len(result.mfds_new)}건")
        except Exception as e:
            error_msg = f"MFDS 스캔 실패: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        # 기존 데이터 매칭 & 핫이슈 판정
        all_new = result.fda_new + result.ema_new + result.mfds_new
        for approval in all_new:
            self._match_existing(approval)
            self._calculate_hot_issue_score(approval)

            if approval.hot_issue_score >= self.HOT_ISSUE_THRESHOLD:
                result.hot_issues.append(approval)

        # 핫이슈 스코어순 정렬
        result.hot_issues.sort(key=lambda x: -x.hot_issue_score)

        logger.info(f"스캔 완료: 총 {result.total_new}건, 핫이슈 {len(result.hot_issues)}건")
        return result

    async def _scan_fda(self, days_back: int) -> list[NewApproval]:
        """FDA 신규 승인 스캔"""
        if not self._client:
            raise RuntimeError("Scanner must be used as async context manager")

        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        to_date = datetime.now().strftime("%Y%m%d")

        url = "https://api.fda.gov/drug/drugsfda.json"
        params = {
            "search": f"submissions.submission_status_date:[{from_date}+TO+{to_date}]",
            "limit": 100,
        }
        if settings.FDA_API_KEY:
            params["api_key"] = settings.FDA_API_KEY

        # URL 직접 구성 (+ 인코딩 문제 방지)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query}"

        response = await self._client.get(full_url)

        if response.status_code == 404:
            # 결과 없음
            return []

        response.raise_for_status()
        data = response.json()

        approvals = []
        for item in data.get("results", []):
            # 신규 승인 건 파싱
            approval = self._parse_fda_approval(item)
            if approval:
                approvals.append(approval)

        return approvals

    def _parse_fda_approval(self, item: dict) -> Optional[NewApproval]:
        """FDA 응답 파싱"""
        openfda = item.get("openfda", {})

        generic_name = (openfda.get("generic_name") or [""])[0]
        brand_name = (openfda.get("brand_name") or [""])[0]

        if not generic_name and not brand_name:
            return None

        # 최근 승인 submission 찾기
        submissions = item.get("submissions", [])
        recent_approval = None
        for sub in submissions:
            if sub.get("submission_type") == "ORIG" and sub.get("submission_status") == "AP":
                recent_approval = sub
                break

        if not recent_approval:
            # ORIG가 없으면 가장 최근 AP
            for sub in submissions:
                if sub.get("submission_status") == "AP":
                    recent_approval = sub
                    break

        if not recent_approval:
            return None

        # 날짜 파싱
        date_str = recent_approval.get("submission_status_date", "")
        try:
            approval_date = datetime.strptime(date_str, "%Y%m%d").date()
        except:
            approval_date = date.today()

        # 특별 지정 확인
        applications = item.get("applications", [])
        is_orphan = any("orphan" in str(app).lower() for app in applications)

        # submission_class_code로 특별 지정 확인
        class_code = recent_approval.get("submission_class_code", "")
        is_priority = class_code == "P"  # Priority Review

        # application_docs에서 추가 정보
        docs = recent_approval.get("application_docs", [])
        is_breakthrough = any("breakthrough" in str(doc).lower() for doc in docs)
        is_accelerated = any("accelerated" in str(doc).lower() for doc in docs)
        is_fast_track = any("fast track" in str(doc).lower() for doc in docs)

        return NewApproval(
            source=ApprovalSource.FDA,
            drug_name=brand_name,
            generic_name=generic_name,
            approval_date=approval_date,
            application_number=item.get("application_number", ""),
            indication=", ".join(openfda.get("pharm_class_epc", [])),
            sponsor=item.get("sponsor_name", ""),
            is_breakthrough=is_breakthrough,
            is_accelerated=is_accelerated,
            is_priority=is_priority,
            is_fast_track=is_fast_track,
            is_orphan=is_orphan,
            raw_data=item,
        )

    @staticmethod
    def _parse_ema_date(date_str: str) -> Optional[date]:
        """EMA 날짜 파싱 (DD/MM/YYYY 형식)"""
        if not date_str or not date_str.strip():
            return None
        try:
            return datetime.strptime(date_str.strip(), "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None

    async def _scan_ema(self, days_back: int) -> list[NewApproval]:
        """EMA 신규 승인 스캔 (JSON Report 방식)"""
        if not self._client:
            raise RuntimeError("Scanner must be used as async context manager")

        # EMA JSON report - 전체 의약품 목록 (ingestor와 동일한 엔드포인트)
        url = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"
        from_dt = (datetime.now() - timedelta(days=days_back)).date()

        try:
            response = await self._client.get(url, follow_redirects=True, timeout=60.0)

            if response.status_code != 200:
                logger.warning(f"EMA API 응답: {response.status_code}")
                return []

            data = response.json()
            # EMA JSON report: {"meta": {...}, "data": [...]} 또는 raw list
            if isinstance(data, dict):
                items = data.get("data", data.get("results", []))
            elif isinstance(data, list):
                items = data
            else:
                items = []

            approvals = []
            for item in items:
                approval = self._parse_ema_approval(item, from_dt)
                if approval:
                    approvals.append(approval)

            return approvals

        except Exception as e:
            logger.warning(f"EMA 스캔 에러: {e}")
            return []

    def _parse_ema_approval(self, item: dict, from_date: date) -> Optional[NewApproval]:
        """EMA 응답 파싱 (JSON Report 형식)

        EMA JSON Report 필드명: marketing_authorisation_date, last_updated_date 등
        날짜 형식: DD/MM/YYYY
        Boolean 필드: "Yes"/"No" 문자열
        """
        # 날짜 파싱 - EC 결정일 > 최종업데이트일 > 승인일 순으로 우선
        ec_date = self._parse_ema_date(item.get("european_commission_decision_date", ""))
        updated_date = self._parse_ema_date(item.get("last_updated_date", ""))
        auth_date = self._parse_ema_date(item.get("marketing_authorisation_date", ""))

        # 최근 활동 날짜 결정
        activity_date = ec_date or updated_date or auth_date
        if not activity_date:
            return None

        # 최근 항목만 필터
        if activity_date < from_date:
            return None

        # 실제 승인일 (표시용)
        approval_date = auth_date or ec_date or activity_date

        generic_name = (
            item.get("international_non_proprietary_name_common_name") or
            item.get("active_substance") or ""
        )
        brand_name = item.get("name_of_medicine", "")

        if not generic_name:
            return None

        # Boolean 필드 ("Yes"/"No" 문자열)
        is_prime = str(item.get("prime_priority_medicine", "")).lower() == "yes"
        is_orphan = str(item.get("orphan_medicine", "")).lower() == "yes"
        is_conditional = str(item.get("conditional_approval", "")).lower() == "yes"
        is_accelerated = str(item.get("accelerated_assessment", "")).lower() == "yes"

        return NewApproval(
            source=ApprovalSource.EMA,
            drug_name=brand_name,
            generic_name=generic_name,
            approval_date=approval_date,
            indication=item.get("therapeutic_area_mesh", ""),
            sponsor=item.get("marketing_authorisation_developer_applicant_holder", ""),
            is_prime=is_prime,
            is_orphan=is_orphan,
            is_conditional=is_conditional,
            is_accelerated=is_accelerated,
            raw_data=item,
        )

    async def _scan_mfds(self, days_back: int) -> list[NewApproval]:
        """MFDS 신규 허가 스캔

        공공데이터포털 API는 날짜 필터를 미지원하고 44K건을 임의 순서로 반환.
        따라서 캐시된 전체 데이터 파일(permits_full_*.json)에서
        최근 허가 품목을 필터링합니다.
        """
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        # 캐시된 전체 데이터 파일 우선 사용
        mfds_dir = self.data_dir / "mfds"
        full_files = sorted(mfds_dir.glob("permits_full_*.json")) if mfds_dir.exists() else []
        if not full_files:
            # full 파일 없으면 일반 permits 파일 사용
            full_files = sorted(mfds_dir.glob("permits_*.json")) if mfds_dir.exists() else []

        if not full_files:
            logger.warning("MFDS 캐시 데이터 없음 - 먼저 collect_all을 실행하세요")
            return []

        try:
            mfds_file = full_files[-1]  # 가장 최근 파일
            with open(mfds_file, encoding="utf-8") as f:
                mfds_data = json.load(f)

            items = mfds_data if isinstance(mfds_data, list) else mfds_data.get("results", [])
            logger.info(f"MFDS 캐시 로드: {mfds_file.name} ({len(items):,}건)")

            approvals = []
            for item in items:
                approval = self._parse_mfds_approval(item, from_date)
                if approval:
                    approvals.append(approval)

            return approvals

        except Exception as e:
            logger.warning(f"MFDS 스캔 에러: {e}")
            return []

    def _parse_mfds_approval(self, item: dict, from_date: str) -> Optional[NewApproval]:
        """MFDS 응답 파싱"""
        # 허가일 확인
        permit_date_str = item.get("ITEM_PERMIT_DATE", "")
        if not permit_date_str:
            return None

        try:
            approval_date = datetime.strptime(permit_date_str[:8], "%Y%m%d").date()
        except:
            return None

        # 최근 허가만 필터
        from_dt = datetime.strptime(from_date, "%Y%m%d").date()
        if approval_date < from_dt:
            return None

        generic_name = item.get("ITEM_INGR_NAME", "")
        brand_name = item.get("ITEM_NAME", "")

        if not generic_name:
            return None

        return NewApproval(
            source=ApprovalSource.MFDS,
            drug_name=brand_name,
            generic_name=generic_name,
            approval_date=approval_date,
            application_number=item.get("ITEM_SEQ", ""),
            indication=item.get("EE_DOC_DATA", "")[:200] if item.get("EE_DOC_DATA") else "",
            sponsor=item.get("ENTP_NAME", ""),
            raw_data=item,
        )

    def _match_existing(self, approval: NewApproval) -> None:
        """기존 데이터와 매칭"""
        normalized = self._normalize_name(approval.generic_name)

        if normalized in self._existing_drugs:
            existing = self._existing_drugs[normalized]
            approval.matched_existing = True
            approval.existing_approvals = existing["approvals"].copy()

    def _calculate_hot_issue_score(self, approval: NewApproval) -> None:
        """핫이슈 스코어 계산"""
        score = 0
        reasons = []
        hot_type = HotIssueType.NONE

        # 1. 글로벌 동시 승인 (FDA+EMA)
        if approval.matched_existing:
            if approval.source == ApprovalSource.FDA and "ema" in approval.existing_approvals:
                score += self.SCORE_WEIGHTS["global_concurrent"]
                reasons.append("FDA+EMA 동시 승인")
                hot_type = HotIssueType.GLOBAL_CONCURRENT
            elif approval.source == ApprovalSource.EMA and "fda" in approval.existing_approvals:
                score += self.SCORE_WEIGHTS["global_concurrent"]
                reasons.append("EMA+FDA 동시 승인")
                hot_type = HotIssueType.GLOBAL_CONCURRENT

        # 2. 국내 도입 (글로벌 → MFDS)
        if approval.source == ApprovalSource.MFDS and approval.matched_existing:
            if "fda" in approval.existing_approvals or "ema" in approval.existing_approvals:
                score += self.SCORE_WEIGHTS["domestic_arrival"]
                reasons.append("글로벌 승인 약물 국내 허가")
                hot_type = HotIssueType.DOMESTIC_ARRIVAL

        # 3. 특별 지정
        if approval.is_breakthrough:
            score += self.SCORE_WEIGHTS["breakthrough"]
            reasons.append("FDA Breakthrough Therapy")
            if hot_type == HotIssueType.NONE:
                hot_type = HotIssueType.BREAKTHROUGH

        if approval.is_prime:
            score += self.SCORE_WEIGHTS["prime"]
            reasons.append("EMA PRIME")
            if hot_type == HotIssueType.NONE:
                hot_type = HotIssueType.PRIME

        if approval.is_accelerated:
            score += self.SCORE_WEIGHTS["accelerated"]
            reasons.append("가속 승인")
            if hot_type == HotIssueType.NONE:
                hot_type = HotIssueType.ACCELERATED

        if approval.is_orphan:
            score += self.SCORE_WEIGHTS["orphan"]
            reasons.append("희귀의약품")
            if hot_type == HotIssueType.NONE:
                hot_type = HotIssueType.ORPHAN

        if approval.is_priority:
            score += self.SCORE_WEIGHTS["priority"]
            reasons.append("FDA Priority Review")

        if approval.is_fast_track:
            score += self.SCORE_WEIGHTS["fast_track"]
            reasons.append("FDA Fast Track")

        if approval.is_conditional:
            score += self.SCORE_WEIGHTS["conditional"]
            reasons.append("EMA Conditional Approval")

        # 4. 고관심 적응증
        indication_lower = approval.indication.lower()
        for keyword in self.HIGH_INTEREST_KEYWORDS:
            if keyword in indication_lower:
                score += self.SCORE_WEIGHTS["high_interest_indication"]
                reasons.append(f"고관심 적응증 ({keyword})")
                if hot_type == HotIssueType.NONE:
                    hot_type = HotIssueType.HIGH_INTEREST
                break

        approval.hot_issue_score = score
        approval.hot_issue_reasons = reasons
        approval.hot_issue_type = hot_type


# 편의 함수
async def run_daily_scan(days_back: int = 1, data_dir: Optional[Path] = None) -> ScanResult:
    """일간 스캔 실행 편의 함수"""
    scanner = DailyScanner(data_dir=data_dir)
    scanner.load_existing_data()

    async with scanner:
        return await scanner.scan(days_back=days_back)
