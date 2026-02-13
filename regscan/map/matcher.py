"""성분명 매칭 로직

FDA ↔ MFDS ↔ HIRA 데이터 연결
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .timeline import DrugTimeline, TimelineBuilder, FDAInfo, MFDSInfo, HIRAInfo


class IngredientMatcher:
    """성분명 정규화 및 매칭"""

    # 제거할 접미사 패턴
    SUFFIX_PATTERNS = [
        r"\s*(mesylate|mesilate|maleate|hydrochloride|hcl|sulfate|sodium|potassium)\s*",
        r"\s*(micronized|anhydrous|hydrate|dihydrate)\s*",
        r"\s*\(.*\)\s*",  # 괄호 내용
        r"\s*,.*$",  # 콤마 이후
    ]

    # 알려진 유의어 (brand → INN 매핑 포함)
    SYNONYMS = {
        "pembrolizumab": ["keytruda", "펨브롤리주맙", "키트루다", "mk-3475"],
        "nivolumab": ["opdivo", "니볼루맙", "옵디보", "bms-936558"],
        "semaglutide": ["ozempic", "wegovy", "rybelsus", "세마글루티드", "오젬픽"],
        "belumosudil": ["rezurock", "벨루모수딜", "레주록"],
        "trastuzumab": ["herceptin", "트라스투주맙", "허셉틴"],
        "atezolizumab": ["tecentriq", "아테졸리주맙", "테센트릭"],
        "durvalumab": ["imfinzi", "더발루맙", "임핀지"],
        "avelumab": ["bavencio", "아벨루맙", "바벤시오"],
        "ipilimumab": ["yervoy", "이필리무맙", "여보이"],
        "lenvatinib": ["lenvima", "렌바티닙", "렌비마"],
        "sorafenib": ["nexavar", "소라페닙", "넥사바"],
        "osimertinib": ["tagrisso", "오시머티닙", "타그리소"],
        "adalimumab": ["humira", "아달리무맙", "휴미라"],
        "ustekinumab": ["stelara", "우스테키누맙", "스텔라라"],
        "secukinumab": ["cosentyx", "세쿠키누맙", "코센틱스"],
        "dupilumab": ["dupixent", "두필루맙", "듀피센트"],
        "tofacitinib": ["xeljanz", "토파시티닙", "젤잔즈"],
        "baricitinib": ["olumiant", "바리시티닙", "올루미언트"],
        "ruxolitinib": ["jakafi", "jakavi", "룩소리티닙", "자카피"],
        "empagliflozin": ["jardiance", "엠파글리플로진", "자디앙스"],
        "dapagliflozin": ["farxiga", "forxiga", "다파글리플로진", "포시가"],
        "tirzepatide": ["mounjaro", "zepbound", "티르제파티드", "마운자로"],
        "sacubitril/valsartan": ["entresto", "사쿠비트릴발사르탄", "엔트레스토"],
        "rivaroxaban": ["xarelto", "리바록사반", "자렐토"],
        "apixaban": ["eliquis", "아픽사반", "엘리퀴스"],
        "olaparib": ["lynparza", "올라파립", "린파자"],
        "rucaparib": ["rubraca", "루카파립", "루브라카"],
        "venetoclax": ["venclexta", "베네토클락스", "벤클렉스타"],
        "ibrutinib": ["imbruvica", "이브루티닙", "임브루비카"],
        "acalabrutinib": ["calquence", "아칼라브루티닙", "칼퀀스"],
        "zanubrutinib": ["brukinsa", "자누브루티닙", "브루킨사"],
        "elotuzumab": ["empliciti", "엘로투주맙", "엠플리시티"],
        "daratumumab": ["darzalex", "다라투무맙", "다잘렉스"],
        "enfortumab vedotin": ["padcev", "엔포르투맙 베도틴", "패드세브"],
        "tucatinib": ["tukysa", "투카티닙", "투키사"],
        "nusinersen": ["spinraza", "누시너센", "스핀라자"],
        "onasemnogene abeparvovec": ["zolgensma", "졸겐스마"],
        "risdiplam": ["evrysdi", "리스디플람", "에브리스디"],
        "voxelotor": ["oxbryta", "복셀로토르"],
    }

    def normalize(self, name: str) -> str:
        """
        성분명 정규화

        Args:
            name: 원본 성분명

        Returns:
            정규화된 성분명 (소문자, 접미사 제거)
        """
        if not name:
            return ""

        # 소문자 변환
        normalized = name.lower().strip()

        # 접미사 제거
        for pattern in self.SUFFIX_PATTERNS:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

        # 공백 정리
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def find_canonical(self, name: str) -> str:
        """
        표준 성분명 찾기 (유의어 → 표준명)

        Args:
            name: 성분명 (정규화된 또는 원본)

        Returns:
            표준 성분명
        """
        normalized = self.normalize(name)

        # 유의어 사전 검색
        for canonical, synonyms in self.SYNONYMS.items():
            if normalized == canonical:
                return canonical
            for syn in synonyms:
                if normalized == syn.lower():
                    return canonical

        return normalized

    def fuzzy_match(
        self,
        name: str,
        candidates: set[str] | list[str],
        threshold: float = 0.85,
    ) -> str | None:
        """
        퍼지 매칭으로 가장 유사한 후보 반환

        검색 순서: canonical lookup → prefix match → token overlap → SequenceMatcher

        Args:
            name: 매칭할 이름
            candidates: 후보 이름 목록 (정규화된)
            threshold: SequenceMatcher 최소 유사도 (0~1)

        Returns:
            매칭된 후보 또는 None
        """
        from difflib import SequenceMatcher

        if not name or not candidates:
            return None

        # 1) canonical lookup
        canonical = self.find_canonical(name)
        if canonical in candidates:
            return canonical

        normalized = self.normalize(name)
        if normalized in candidates:
            return normalized

        # 2) prefix match (처음 6자 이상 일치)
        if len(normalized) >= 6:
            prefix = normalized[:6]
            for c in candidates:
                if c.startswith(prefix):
                    return c

        # 3) token overlap (공백/하이픈 분리 후 겹치는 토큰 비율)
        name_tokens = set(re.split(r'[\s\-/]+', normalized))
        for c in candidates:
            c_tokens = set(re.split(r'[\s\-/]+', c))
            if name_tokens and c_tokens:
                overlap = len(name_tokens & c_tokens)
                max_len = max(len(name_tokens), len(c_tokens))
                if overlap / max_len >= 0.5 and overlap >= 1:
                    return c

        # 4) SequenceMatcher
        best_match = None
        best_ratio = 0.0
        for c in candidates:
            ratio = SequenceMatcher(None, normalized, c).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = c

        if best_ratio >= threshold:
            return best_match

        return None

    def match(self, name1: str, name2: str) -> bool:
        """
        두 성분명이 동일한지 확인

        Args:
            name1: 첫 번째 성분명
            name2: 두 번째 성분명

        Returns:
            매칭 여부
        """
        canonical1 = self.find_canonical(name1)
        canonical2 = self.find_canonical(name2)

        return canonical1 == canonical2


@dataclass
class MFDSProduct:
    """MFDS 제품 정보"""
    item_seq: str
    item_name: str
    ingredient_name: str
    permit_date: Optional[date]
    company: str
    cancel_status: str


@dataclass
class ATCMapping:
    """ATC 매핑 정보"""
    product_code: str
    product_name: str
    atc_code: str
    atc_name: str
    ingredient_code: str


@dataclass
class HIRANotification:
    """HIRA 고시 정보"""
    title: str
    publication_date: Optional[date]
    notification_number: str
    content_summary: str
    url: str


class DrugMatcher:
    """FDA ↔ MFDS ↔ HIRA 통합 매칭"""

    def __init__(
        self,
        mfds_data_path: Optional[str | Path] = None,
        atc_data_path: Optional[str | Path] = None,
        hira_data_path: Optional[str | Path] = None,
    ):
        self.ingredient_matcher = IngredientMatcher()
        self._mfds_data: list[dict] = []
        self._atc_data: Optional[pd.DataFrame] = None
        self._hira_data: list[dict] = []

        if mfds_data_path:
            self.load_mfds_data(mfds_data_path)
        if atc_data_path:
            self.load_atc_data(atc_data_path)
        if hira_data_path:
            self.load_hira_data(hira_data_path)

    def load_mfds_data(self, path: str | Path) -> None:
        """MFDS 데이터 로드"""
        path = Path(path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._mfds_data = json.load(f)

    def load_atc_data(self, path: str | Path) -> None:
        """ATC 매핑 데이터 로드"""
        path = Path(path)
        if path.exists():
            self._atc_data = pd.read_excel(path, skiprows=1)

    def load_hira_data(self, path: str | Path) -> None:
        """HIRA 고시 데이터 로드"""
        path = Path(path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._hira_data = json.load(f)

    def find_mfds_by_ingredient(self, ingredient: str) -> list[MFDSProduct]:
        """
        성분명으로 MFDS 제품 검색

        Args:
            ingredient: 성분명 (영문)

        Returns:
            매칭된 MFDS 제품 목록
        """
        results = []
        normalized = self.ingredient_matcher.normalize(ingredient)

        for item in self._mfds_data:
            item_ingr = item.get("ITEM_INGR_NAME") or ""
            item_name = item.get("ITEM_NAME") or ""
            eng_name = item.get("ITEM_ENG_NAME") or ""

            # 성분명 매칭
            if (
                normalized in self.ingredient_matcher.normalize(item_ingr)
                or normalized in self.ingredient_matcher.normalize(item_name)
                or normalized in self.ingredient_matcher.normalize(eng_name)
            ):
                permit_date = self._parse_date(item.get("ITEM_PERMIT_DATE"))
                results.append(
                    MFDSProduct(
                        item_seq=item.get("ITEM_SEQ", ""),
                        item_name=item.get("ITEM_NAME", ""),
                        ingredient_name=item_ingr,
                        permit_date=permit_date,
                        company=item.get("ENTP_NAME", ""),
                        cancel_status=item.get("CANCEL_NAME", "정상"),
                    )
                )

        return results

    def find_atc_by_ingredient(self, ingredient: str) -> list[ATCMapping]:
        """
        성분명으로 ATC 매핑 검색

        Args:
            ingredient: 성분명 (영문)

        Returns:
            매칭된 ATC 매핑 목록
        """
        if self._atc_data is None:
            return []

        results = []
        normalized = self.ingredient_matcher.normalize(ingredient)

        # ATC코드 명칭에서 검색
        for _, row in self._atc_data.iterrows():
            atc_name = str(row.get("ATC코드 명칭", ""))
            if normalized in self.ingredient_matcher.normalize(atc_name):
                results.append(
                    ATCMapping(
                        product_code=str(row.get("제품코드", "")),
                        product_name=str(row.get("제품명", "")),
                        atc_code=str(row.get("ATC코드", "")),
                        atc_name=atc_name,
                        ingredient_code=str(row.get("주성분코드", "")),
                    )
                )

        return results

    def find_hira_by_ingredient(self, ingredient: str) -> list[HIRANotification]:
        """
        성분명으로 HIRA 고시 검색 (신규 급여 약물)

        Args:
            ingredient: 성분명 (영문)

        Returns:
            매칭된 HIRA 고시 목록
        """
        results = []
        normalized = self.ingredient_matcher.normalize(ingredient)

        for item in self._hira_data:
            title = item.get("title", "")
            # 제목에서 성분명 검색
            if normalized in self.ingredient_matcher.normalize(title):
                pub_date = self._parse_date(item.get("publication_date"))

                # 고시번호 추출
                meta = item.get("meta", {})
                notification_num = meta.get("관련근거", "")

                # content 요약 (처음 200자)
                content = item.get("content", "")
                summary = content[:200] + "..." if len(content) > 200 else content

                results.append(
                    HIRANotification(
                        title=title,
                        publication_date=pub_date,
                        notification_number=notification_num,
                        content_summary=summary,
                        url=item.get("url", ""),
                    )
                )

        return results

    def build_timeline(
        self,
        fda_data: dict[str, Any],
        include_mfds: bool = True,
        include_hira: bool = True,
    ) -> DrugTimeline:
        """
        FDA 데이터로부터 Timeline 생성

        Args:
            fda_data: FDA 파서 출력 데이터
            include_mfds: MFDS 매칭 포함 여부
            include_hira: HIRA 매칭 포함 여부

        Returns:
            DrugTimeline 객체
        """
        # 성분명 추출
        substance_names = fda_data.get("substance_name", [])
        generic_name = fda_data.get("generic_name", "")
        ingredient = substance_names[0] if substance_names else generic_name

        normalized = self.ingredient_matcher.find_canonical(ingredient)

        builder = TimelineBuilder().with_ingredient(
            normalized=normalized,
            en=ingredient,
        )

        # FDA 정보
        builder.with_fda(
            approval_date=fda_data.get("submission_status_date"),
            application_number=fda_data.get("application_number", ""),
            brand_name=fda_data.get("brand_name", ""),
            generic_name=generic_name,
            submission_type=fda_data.get("submission_type", ""),
        )

        # MFDS 매칭
        if include_mfds and ingredient:
            mfds_products = self.find_mfds_by_ingredient(ingredient)
            if mfds_products:
                # 가장 최근 허가 제품 선택
                active = [p for p in mfds_products if p.cancel_status == "정상"]
                product = active[0] if active else mfds_products[0]
                builder.with_mfds(
                    permit_date=product.permit_date,
                    item_seq=product.item_seq,
                    item_name=product.item_name,
                    ingredient_name=product.ingredient_name,
                    company=product.company,
                )

        # HIRA/ATC 매칭
        if include_hira and ingredient:
            # 먼저 ATC 매핑에서 검색 (기존 급여)
            atc_mappings = self.find_atc_by_ingredient(ingredient)
            if atc_mappings:
                mapping = atc_mappings[0]
                builder.with_hira(
                    product_code=mapping.product_code,
                    product_name=mapping.product_name,
                    atc_code=mapping.atc_code,
                )
            else:
                # ATC 없으면 HIRA 고시에서 검색 (신규 급여)
                hira_notifications = self.find_hira_by_ingredient(ingredient)
                if hira_notifications:
                    notif = hira_notifications[0]
                    builder.with_hira(
                        coverage_date=notif.publication_date,
                        notification_number=notif.notification_number,
                        product_name=notif.title,
                        criteria_summary=notif.content_summary,
                    )

        return builder.build()

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None

        date_str = str(date_str)

        for fmt in ["%Y%m%d", "%Y-%m-%d", "%Y.%m.%d"]:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None
