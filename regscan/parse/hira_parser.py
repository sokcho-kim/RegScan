"""HIRA 응답 파서"""

from datetime import datetime
from typing import Any


class HIRAParser:
    """HIRA 보험인정기준/공지사항 파서"""

    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        HIRA 크롤링 데이터를 중간 형식으로 변환

        Args:
            raw: 크롤러에서 수집한 단일 레코드

        Returns:
            정규화된 dict (SignalGenerator 입력용)
        """
        source_type = raw.get("source_type", "HIRA_NOTICE")
        category = raw.get("category", "")

        # 제목/본문
        title = raw.get("title", "").strip()
        content = raw.get("content", "").strip()

        # 날짜
        pub_date_str = raw.get("publication_date", "")
        publication_date = self._parse_date(pub_date_str)

        # 메타데이터
        meta = raw.get("meta", {})

        # 고시번호 추출
        notification_number = self._extract_notification_number(title, meta)

        # 관련 근거
        related_basis = meta.get("관련근거", "")

        # 첨부파일
        files = raw.get("files", [])

        # 변경 유형 추론
        change_type = self._infer_change_type(title, content)

        # 도메인 추론
        domain = self._infer_domain(title, content, category)

        return {
            # 식별
            "source_id": raw.get("url", ""),
            "source_type": source_type,

            # 기본 정보
            "title": title,
            "content": content,
            "category": category,

            # 날짜
            "publication_date": publication_date,
            "collected_at": raw.get("collected_at"),

            # 메타
            "notification_number": notification_number,
            "related_basis": related_basis,
            "meta": meta,

            # 첨부파일
            "files": files,
            "has_attachment": len(files) > 0,

            # 추론된 필드
            "change_type": change_type,
            "domain": domain,

            # URL
            "source_url": raw.get("url", ""),

            # 원본
            "raw": raw,
        }

    def _parse_date(self, date_str: str) -> datetime | None:
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        formats = [
            "%Y-%m-%d",
            "%Y.%m.%d",
            "%Y%m%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None

    def _extract_notification_number(
        self, title: str, meta: dict
    ) -> str:
        """고시번호 추출"""
        # 메타에서 먼저 찾기
        if "고시번호" in meta:
            return meta["고시번호"]

        # 제목에서 패턴 찾기
        import re

        patterns = [
            r"(고시\s*제?\d{4}-\d+호?)",
            r"(제?\d{4}-\d+호)",
            r"(보건복지부\s*고시\s*제?\d{4}-\d+호?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                return match.group(1)

        return ""

    def _infer_change_type(self, title: str, content: str) -> str:
        """변경 유형 추론"""
        text = f"{title} {content}".lower()

        if any(kw in text for kw in ["신설", "신규", "제정", "new"]):
            return "NEW"
        elif any(kw in text for kw in ["개정", "변경", "수정", "일부개정"]):
            return "REVISED"
        elif any(kw in text for kw in ["폐지", "삭제", "폐기"]):
            return "DELETED"
        else:
            return "INFO"

    def _infer_domain(self, title: str, content: str, category: str) -> str:
        """도메인 추론"""
        text = f"{title} {content}".lower()

        # 재료 (더 구체적인 키워드 먼저)
        if any(kw in text for kw in ["치료재료", "재료대", "의료기기"]):
            return "MATERIAL"

        # 행위/수가
        if any(kw in text for kw in ["행위", "수가", "진료비", "가산"]):
            return "PROCEDURE"

        # 약제
        if any(kw in text for kw in ["약제", "의약품", "약가"]):
            return "DRUG"

        # 안전
        if any(kw in text for kw in ["안전", "주의", "금기", "부작용"]):
            return "SAFETY"

        # 급여기준
        if any(kw in text for kw in ["급여기준", "인정기준", "보험인정"]):
            return "REIMBURSEMENT"

        # 카테고리 기반
        if category in ["고시", "행정해석"]:
            return "REIMBURSEMENT"
        elif category in ["심사지침", "심사사례지침"]:
            return "REIMBURSEMENT"
        elif category == "심의사례공개":
            return "REIMBURSEMENT"

        return "REIMBURSEMENT"  # HIRA 기본값

    def parse_many(self, raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """여러 결과 파싱"""
        return [self.parse(raw) for raw in raw_list]
