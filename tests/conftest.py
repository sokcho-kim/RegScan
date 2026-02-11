"""공통 pytest 설정 및 fixture

- e2e 마커 등록 (일반 테스트와 분리)
- 공통 샘플 데이터 fixture
"""

import os

import pytest


# ── 커스텀 마커 등록 ──

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring real API keys")


# ── 공통 fixture ──

@pytest.fixture
def sample_drug():
    """테스트용 약물 데이터 (PEMBROLIZUMAB)"""
    return {
        "inn": "PEMBROLIZUMAB",
        "fda_approved": True,
        "fda_date": "2025-06-15",
        "ema_approved": True,
        "ema_date": "2025-08-01",
        "mfds_approved": False,
        "mfds_date": None,
        "hira_status": "reimbursed",
        "hira_price": 1250000,
        "global_score": 85,
    }


@pytest.fixture
def sample_preprints():
    """테스트용 bioRxiv 프리프린트 목록"""
    return [
        {
            "doi": "10.1101/2026.01.15.000111",
            "title": "Pembrolizumab + Lenvatinib combination shows improved PFS in advanced endometrial cancer",
            "abstract": (
                "Background: Pembrolizumab combined with lenvatinib has shown promising activity "
                "in advanced endometrial cancer. We conducted a Phase III trial enrolling 827 patients "
                "across 150 sites globally. Results: Median PFS was 7.2 months vs 3.8 months (HR 0.56, "
                "p<0.001). Overall survival showed a trend toward improvement (HR 0.68, p=0.049). "
                "Grade 3-4 adverse events occurred in 88.9% vs 72.7% of patients. Conclusion: "
                "The combination significantly improved PFS with manageable safety profile."
            ),
            "server": "medrxiv",
            "category": "oncology",
            "published_date": "2026-01-15",
        },
        {
            "doi": "10.1101/2026.01.20.000222",
            "title": "Real-world outcomes of PD-1 inhibitors in Korean NSCLC patients",
            "abstract": (
                "We analyzed 1,234 Korean patients with non-small cell lung cancer treated with "
                "PD-1 inhibitors including pembrolizumab. The 2-year overall survival rate was 42.3% "
                "and the response rate was 38.7%. Korean patients showed comparable efficacy to "
                "global clinical trial data."
            ),
            "server": "medrxiv",
            "category": "oncology",
            "published_date": "2026-01-20",
        },
    ]


@pytest.fixture
def sample_market_reports():
    """테스트용 ASTI 시장 리포트 목록"""
    return [
        {
            "title": "글로벌 면역항암제 시장 분석 및 전망 2026-2030",
            "source": "ASTI",
            "publisher": "한국과학기술정보연구원",
            "market_size_krw": 5200.0,
            "growth_rate": 15.3,
            "summary": (
                "면역관문억제제 시장은 2026년 5,200억 원에서 2030년 약 9,400억 원으로 "
                "연평균 15.3% 성장 전망. PD-1/PD-L1 억제제가 전체 시장의 68% 차지."
            ),
            "published_date": "2026-01-10",
        },
        {
            "title": "국내 항암제 급여 현황 및 시장 동향",
            "source": "KISTI",
            "publisher": "한국과학기술정보연구원",
            "market_size_krw": 3800.0,
            "growth_rate": 12.1,
            "summary": "국내 항암제 시장 규모 약 3,800억 원. 면역항암제 비중 증가 추세.",
            "published_date": "2026-01-05",
        },
    ]


@pytest.fixture
def sample_expert_opinions():
    """테스트용 Health.kr 전문가 리뷰 목록"""
    return [
        {
            "source": "KPIC",
            "title": "PEMBROLIZUMAB 신규 적응증 확대에 따른 약료 전략",
            "author": "김약사",
            "summary": (
                "Pembrolizumab의 자궁내막암 적응증 추가로 국내 급여 범위 확대 가능성 높음. "
                "기존 NSCLC, 흑색종 외 새로운 영역으로 사용 증가 전망."
            ),
            "published_date": "2026-01-12",
        },
    ]
