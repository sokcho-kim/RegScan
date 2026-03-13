"""KHIDI (한국보건산업진흥원) 수집기 테스트"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from regscan.ingest.khidi import KHIDIIngestor, KHIDIBriefIngestor, KHIDI_BASE


SAMPLE_LIST_HTML = """
<html><body>
<table>
<tbody>
<tr>
    <td>571</td>
    <td><a href="/board/view?pageNum=1&rowCnt=10&no1=571&linkId=48941089&menuId=MENU01783">
        바이오헬스산업동향 제474호
    </a></td>
    <td>2026-03-06</td>
    <td>260</td>
</tr>
<tr>
    <td>570</td>
    <td><a href="/board/view?pageNum=1&rowCnt=10&no1=570&linkId=48941014&menuId=MENU01783">
        바이오헬스산업동향 제473호
    </a></td>
    <td>2026-02-27</td>
    <td>415</td>
</tr>
<tr>
    <td>569</td>
    <td><a href="/board/view?pageNum=1&rowCnt=10&no1=569&linkId=48941012&menuId=MENU01783">
        바이오헬스산업동향 제472호
    </a></td>
    <td>2025-12-01</td>
    <td>800</td>
</tr>
</tbody>
</table>
</body></html>
"""

SAMPLE_DETAIL_HTML = """
<html><body>
<div class="viewContent">
    <p>바이오헬스 산업의 주요 동향을 분석합니다.</p>
    <p>글로벌 의약품 시장은 2025년 1.5조 달러 규모.</p>
</div>
<div class="file_attach">
    <a href="/fileDownload?fileId=12345">제474호_보고서.pdf(3.98MB)</a>
</div>
</body></html>
"""


def test_khidi_fetch_list():
    """KHIDI 목록 수집 테스트"""
    ingestor = KHIDIIngestor(days_back=30, max_pages=1)

    mock_response = AsyncMock()
    mock_response.text = SAMPLE_LIST_HTML
    mock_response.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    ingestor._client = mock_client

    items = asyncio.run(ingestor.fetch())

    # days_back=30이므로 2025-12-01은 제외됨
    assert len(items) == 2
    assert items[0]["title"] == "바이오헬스산업동향 제474호"
    assert items[0]["no1"] == "571"
    assert items[0]["date"] == "2026-03-06"
    assert items[0]["source"] == "KHIDI"
    assert "board/view" in items[0]["url"]


def test_khidi_fetch_detail():
    """KHIDI 상세 페이지 추출 테스트"""
    ingestor = KHIDIIngestor()

    mock_response = AsyncMock()
    mock_response.text = SAMPLE_DETAIL_HTML
    mock_response.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    ingestor._client = mock_client

    item = {"url": f"{KHIDI_BASE}/board/view?no1=571"}
    result = asyncio.run(ingestor.fetch_detail(item))

    assert "바이오헬스 산업의 주요 동향" in result["content"]
    assert len(result["files"]) == 1
    assert "제474호_보고서.pdf" in result["files"][0]["filename"]


def test_khidi_brief_ingestor_inherits():
    """KHIDIBriefIngestor가 올바른 menu_id를 사용하는지"""
    ingestor = KHIDIBriefIngestor()
    assert ingestor.menu_id == "MENU01783"
    assert ingestor.source_type() == "KHIDI"


def test_extract_view_content():
    """viewContent 추출 테스트"""
    ingestor = KHIDIIngestor()
    content = ingestor._extract_view_content(SAMPLE_DETAIL_HTML)
    assert "바이오헬스 산업" in content
    assert "1.5조 달러" in content


def test_extract_files():
    """첨부파일 추출 테스트"""
    ingestor = KHIDIIngestor()
    files = ingestor._extract_files(SAMPLE_DETAIL_HTML)
    assert len(files) == 1
    assert "fileDownload" in files[0]["url"]
