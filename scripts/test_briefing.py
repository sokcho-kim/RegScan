"""LLM 브리핑 리포트 테스트"""

import sys
import io
import asyncio
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from regscan.api.main import app

client = TestClient(app)


def test_briefing_template():
    """템플릿 기반 브리핑 (LLM 미사용)"""
    print("=" * 60)
    print("[1] GET /api/v1/drugs/pembrolizumab/briefing?use_llm=false")
    print("    (템플릿 기반 - LLM 미사용)")
    print("=" * 60)

    r = client.get("/api/v1/drugs/pembrolizumab/briefing?use_llm=false")
    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"\nHeadline: {data['headline']}")
        print(f"Subtitle: {data['subtitle']}")
        print(f"\nKey Points:")
        for i, point in enumerate(data['key_points'], 1):
            print(f"  {i}. {point}")
        print(f"\nGlobal: {data['global_section']}")
        print(f"Domestic: {data['domestic_section']}")
        print(f"Medclaim: {data['medclaim_section']}")
    else:
        print(f"Error: {r.text}")


def test_briefing_llm():
    """LLM 기반 브리핑"""
    print("\n" + "=" * 60)
    print("[2] GET /api/v1/drugs/pembrolizumab/briefing?use_llm=true")
    print("    (LLM 기반 - Anthropic Claude)")
    print("=" * 60)

    r = client.get("/api/v1/drugs/pembrolizumab/briefing?use_llm=true")
    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"\nHeadline: {data['headline']}")
        print(f"Subtitle: {data['subtitle']}")
        print(f"\nKey Points:")
        for i, point in enumerate(data['key_points'], 1):
            print(f"  {i}. {point}")
        print(f"\n--- Markdown 출력 ---")
        print(data['markdown'][:1500] + "..." if len(data['markdown']) > 1500 else data['markdown'])
    elif r.status_code == 500:
        print("LLM API 오류 (API 키 확인 필요)")
        print(f"Error: {r.text[:200]}")
    else:
        print(f"Error: {r.text}")


def test_hot_issue_briefing():
    """핫이슈 약물 브리핑"""
    print("\n" + "=" * 60)
    print("[3] 핫이슈 약물 브리핑 (템플릿)")
    print("=" * 60)

    # 먼저 핫이슈 목록 조회
    r = client.get("/api/v1/hot-issues?limit=3")
    if r.status_code == 200:
        hot_issues = r.json()
        for item in hot_issues[:2]:
            inn = item['inn']
            print(f"\n--- {inn} (score: {item['global_score']}) ---")

            r2 = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm=false")
            if r2.status_code == 200:
                data = r2.json()
                print(f"Headline: {data['headline']}")
                print(f"Global: {data['global_section'][:100]}...")
            else:
                print(f"Error: {r2.status_code}")


if __name__ == "__main__":
    # 1. 템플릿 기반 테스트 (항상 성공)
    test_briefing_template()

    # 2. LLM 기반 테스트 (API 키 필요)
    test_briefing_llm()

    # 3. 핫이슈 약물 테스트
    test_hot_issue_briefing()

    print("\n" + "=" * 60)
    print("브리핑 리포트 테스트 완료!")
    print("=" * 60)
