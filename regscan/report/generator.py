"""MVP 리포트 생성기

일간/주간 규제 동향 리포트 생성
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any, Optional
from collections import Counter

from regscan.db import FeedCardRepository, GlobalStatusRepository
from regscan.models import FeedCard, ImpactLevel, SourceType
from regscan.map.global_status import GlobalRegulatoryStatus, HotIssueLevel


@dataclass
class ReportStats:
    """리포트 통계"""
    total_cards: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    by_impact: dict[str, int] = field(default_factory=dict)
    high_impact_count: int = 0


@dataclass
class DailyReport:
    """일간 리포트"""
    report_date: date
    generated_at: datetime
    stats: ReportStats
    highlights: list[FeedCard]
    hot_issues: list[GlobalRegulatoryStatus]
    all_cards: list[FeedCard]


@dataclass
class WeeklyReport:
    """주간 리포트"""
    start_date: date
    end_date: date
    generated_at: datetime
    stats: ReportStats
    top_highlights: list[FeedCard]
    hot_issues: list[GlobalRegulatoryStatus]
    daily_breakdown: dict[str, int]


class ReportGenerator:
    """리포트 생성기"""

    def __init__(self, db_url: str):
        self.feed_repo = FeedCardRepository(db_url)
        self.global_repo = GlobalStatusRepository(db_url)

    async def init(self):
        """저장소 초기화"""
        await self.feed_repo.init_db()
        await self.global_repo.init_db()

    async def generate_daily(self, target_date: Optional[date] = None) -> DailyReport:
        """
        일간 리포트 생성

        Args:
            target_date: 대상 날짜 (기본값: 오늘)

        Returns:
            DailyReport
        """
        target_date = target_date or date.today()

        # 날짜 범위 설정
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())

        # FeedCard 조회
        cards = await self.feed_repo.get_by_date_range(start_dt, end_dt)

        # 통계 계산
        stats = self._calculate_stats(cards)

        # 하이라이트 (HIGH 이상)
        highlights = [
            card for card in cards
            if card.impact_level in [ImpactLevel.HIGH, ImpactLevel.HIGH]
        ]
        highlights.sort(key=lambda c: c.impact_level.value, reverse=True)

        # 핫이슈
        hot_issues = await self.global_repo.get_hot_issues(min_score=50, limit=10)

        return DailyReport(
            report_date=target_date,
            generated_at=datetime.now(),
            stats=stats,
            highlights=highlights[:5],
            hot_issues=hot_issues[:5],
            all_cards=cards,
        )

    async def generate_weekly(
        self,
        end_date: Optional[date] = None,
    ) -> WeeklyReport:
        """
        주간 리포트 생성

        Args:
            end_date: 종료 날짜 (기본값: 오늘)

        Returns:
            WeeklyReport
        """
        end_date = end_date or date.today()
        start_date = end_date - timedelta(days=6)

        # 날짜 범위 설정
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        # FeedCard 조회
        cards = await self.feed_repo.get_by_date_range(start_dt, end_dt)

        # 통계 계산
        stats = self._calculate_stats(cards)

        # 일별 분포
        daily_breakdown = {}
        for card in cards:
            day = card.published_at.strftime("%Y-%m-%d")
            daily_breakdown[day] = daily_breakdown.get(day, 0) + 1

        # 상위 하이라이트
        top_highlights = [
            card for card in cards
            if card.impact_level in [ImpactLevel.HIGH, ImpactLevel.HIGH]
        ]
        top_highlights.sort(key=lambda c: c.impact_level.value, reverse=True)

        # 핫이슈
        hot_issues = await self.global_repo.get_hot_issues(min_score=40, limit=20)

        return WeeklyReport(
            start_date=start_date,
            end_date=end_date,
            generated_at=datetime.now(),
            stats=stats,
            top_highlights=top_highlights[:10],
            hot_issues=hot_issues[:10],
            daily_breakdown=daily_breakdown,
        )

    def _calculate_stats(self, cards: list[FeedCard]) -> ReportStats:
        """통계 계산"""
        by_source = Counter(card.source_type.value for card in cards)
        by_impact = Counter(card.impact_level.value for card in cards)

        high_impact_count = sum(
            1 for card in cards
            if card.impact_level in [ImpactLevel.HIGH, ImpactLevel.HIGH]
        )

        return ReportStats(
            total_cards=len(cards),
            by_source=dict(by_source),
            by_impact=dict(by_impact),
            high_impact_count=high_impact_count,
        )

    def format_daily_text(self, report: DailyReport) -> str:
        """일간 리포트 텍스트 형식"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"RegScan 일간 리포트 - {report.report_date.strftime('%Y-%m-%d')}")
        lines.append("=" * 60)
        lines.append(f"생성 시간: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # 요약
        lines.append("[요약]")
        lines.append(f"  - 전체 신호: {report.stats.total_cards}건")
        lines.append(f"  - 주요 신호 (HIGH+): {report.stats.high_impact_count}건")
        lines.append("")

        # 소스별 분포
        lines.append("[소스별 분포]")
        for source, count in sorted(report.stats.by_source.items()):
            lines.append(f"  - {source}: {count}건")
        lines.append("")

        # 하이라이트
        if report.highlights:
            lines.append("[오늘의 하이라이트]")
            for i, card in enumerate(report.highlights, 1):
                lines.append(f"  {i}. [{card.impact_level.value}] {card.title}")
                if card.why_it_matters:
                    lines.append(f"     → {card.why_it_matters}")
            lines.append("")

        # 핫이슈
        if report.hot_issues:
            lines.append("[핫이슈 모니터링]")
            for item in report.hot_issues:
                agencies = item.approved_agencies
                lines.append(f"  - {item.inn}: {item.global_score}점 ({item.hot_issue_level.value})")
                lines.append(f"    승인기관: {', '.join(agencies) if agencies else '없음'}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def format_weekly_text(self, report: WeeklyReport) -> str:
        """주간 리포트 텍스트 형식"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"RegScan 주간 리포트")
        lines.append(f"기간: {report.start_date.strftime('%Y-%m-%d')} ~ {report.end_date.strftime('%Y-%m-%d')}")
        lines.append("=" * 60)
        lines.append(f"생성 시간: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # 요약
        lines.append("[주간 요약]")
        lines.append(f"  - 전체 신호: {report.stats.total_cards}건")
        lines.append(f"  - 주요 신호 (HIGH+): {report.stats.high_impact_count}건")
        lines.append("")

        # 일별 분포
        lines.append("[일별 분포]")
        for day in sorted(report.daily_breakdown.keys()):
            count = report.daily_breakdown[day]
            bar = "█" * min(count, 20)
            lines.append(f"  {day}: {bar} {count}건")
        lines.append("")

        # Impact별 분포
        lines.append("[Impact별 분포]")
        for impact in ["HIGH", "MID", "LOW"]:
            count = report.stats.by_impact.get(impact, 0)
            lines.append(f"  - {impact}: {count}건")
        lines.append("")

        # 소스별 분포
        lines.append("[소스별 분포]")
        for source, count in sorted(report.stats.by_source.items(), key=lambda x: -x[1]):
            lines.append(f"  - {source}: {count}건")
        lines.append("")

        # 주간 하이라이트
        if report.top_highlights:
            lines.append("[주간 주요 하이라이트]")
            for i, card in enumerate(report.top_highlights[:5], 1):
                lines.append(f"  {i}. [{card.impact_level.value}] {card.title}")
                lines.append(f"     발행: {card.published_at.strftime('%Y-%m-%d')}")
            lines.append("")

        # 핫이슈 트래킹
        if report.hot_issues:
            lines.append("[핫이슈 트래킹]")
            for item in report.hot_issues[:5]:
                agencies = item.approved_agencies
                lines.append(f"  - {item.inn}: {item.global_score}점 ({item.hot_issue_level.value})")
                if agencies:
                    lines.append(f"    승인: {', '.join(agencies)}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def format_daily_markdown(self, report: DailyReport) -> str:
        """일간 리포트 마크다운 형식"""
        lines = []
        lines.append(f"# RegScan 일간 리포트")
        lines.append(f"**{report.report_date.strftime('%Y년 %m월 %d일')}**")
        lines.append("")
        lines.append(f"> 생성: {report.generated_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # 요약
        lines.append("## 요약")
        lines.append(f"- 전체 신호: **{report.stats.total_cards}건**")
        lines.append(f"- 주요 신호: **{report.stats.high_impact_count}건**")
        lines.append("")

        # 소스별
        lines.append("## 소스별 분포")
        lines.append("| 소스 | 건수 |")
        lines.append("|------|------|")
        for source, count in sorted(report.stats.by_source.items()):
            lines.append(f"| {source} | {count} |")
        lines.append("")

        # 하이라이트
        if report.highlights:
            lines.append("## 오늘의 하이라이트")
            for i, card in enumerate(report.highlights, 1):
                lines.append(f"### {i}. {card.title}")
                lines.append(f"- **Impact**: {card.impact_level.value}")
                if card.why_it_matters:
                    lines.append(f"- **중요성**: {card.why_it_matters}")
                lines.append("")

        # 핫이슈
        if report.hot_issues:
            lines.append("## 핫이슈 모니터링")
            lines.append("| INN | 점수 | 등급 | 승인기관 |")
            lines.append("|-----|------|------|----------|")
            for item in report.hot_issues:
                agencies = ", ".join(item.approved_agencies) or "-"
                lines.append(f"| {item.inn} | {item.global_score} | {item.hot_issue_level.value} | {agencies} |")
            lines.append("")

        return "\n".join(lines)

    def format_weekly_markdown(self, report: WeeklyReport) -> str:
        """주간 리포트 마크다운 형식"""
        lines = []
        lines.append(f"# RegScan 주간 리포트")
        lines.append(f"**{report.start_date.strftime('%Y.%m.%d')} ~ {report.end_date.strftime('%Y.%m.%d')}**")
        lines.append("")
        lines.append(f"> 생성: {report.generated_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # 요약
        lines.append("## 주간 요약")
        lines.append(f"- 전체 신호: **{report.stats.total_cards}건**")
        lines.append(f"- 주요 신호: **{report.stats.high_impact_count}건**")
        lines.append("")

        # 일별 차트 (텍스트)
        lines.append("## 일별 분포")
        lines.append("```")
        for day in sorted(report.daily_breakdown.keys()):
            count = report.daily_breakdown[day]
            bar = "█" * min(count, 30)
            lines.append(f"{day[-5:]}: {bar} {count}")
        lines.append("```")
        lines.append("")

        # Impact 분포
        lines.append("## Impact 분포")
        lines.append("| Impact | 건수 | 비율 |")
        lines.append("|--------|------|------|")
        total = report.stats.total_cards or 1
        for impact in ["HIGH", "MID", "LOW"]:
            count = report.stats.by_impact.get(impact, 0)
            pct = count / total * 100
            lines.append(f"| {impact} | {count} | {pct:.1f}% |")
        lines.append("")

        # 상위 하이라이트
        if report.top_highlights:
            lines.append("## 주간 주요 하이라이트")
            for i, card in enumerate(report.top_highlights[:5], 1):
                lines.append(f"### {i}. {card.title}")
                lines.append(f"- **날짜**: {card.published_at.strftime('%Y-%m-%d')}")
                lines.append(f"- **Impact**: {card.impact_level.value}")
                if card.why_it_matters:
                    lines.append(f"- **중요성**: {card.why_it_matters}")
                lines.append("")

        # 핫이슈
        if report.hot_issues:
            lines.append("## 핫이슈 트래킹")
            lines.append("| 순위 | INN | 점수 | 등급 | 승인기관 |")
            lines.append("|------|-----|------|------|----------|")
            for i, item in enumerate(report.hot_issues[:5], 1):
                agencies = ", ".join(item.approved_agencies) or "-"
                lines.append(f"| {i} | {item.inn} | {item.global_score} | {item.hot_issue_level.value} | {agencies} |")
            lines.append("")

        return "\n".join(lines)
