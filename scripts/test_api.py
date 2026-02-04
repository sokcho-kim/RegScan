"""API 테스트 (서버 없이)"""

import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from regscan.api.main import app

client = TestClient(app)


def test_root():
    print("=" * 60)
    print("[1] GET /")
    print("=" * 60)
    r = client.get("/")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")


def test_health():
    print("\n" + "=" * 60)
    print("[2] GET /health")
    print("=" * 60)
    r = client.get("/health")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")


def test_stats():
    print("\n" + "=" * 60)
    print("[3] GET /api/v1/stats")
    print("=" * 60)
    r = client.get("/api/v1/stats")
    print(f"Status: {r.status_code}")
    data = r.json()
    for k, v in data.items():
        print(f"  {k}: {v}")


def test_hot_issues():
    print("\n" + "=" * 60)
    print("[4] GET /api/v1/hot-issues")
    print("=" * 60)
    r = client.get("/api/v1/hot-issues?limit=10")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Count: {len(data)}")
    for item in data[:5]:
        print(f"  {item['inn']}: {item['global_score']}점 ({item['hot_issue_level']})")


def test_imminent():
    print("\n" + "=" * 60)
    print("[5] GET /api/v1/imminent")
    print("=" * 60)
    r = client.get("/api/v1/imminent?limit=10")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Count: {len(data)}")
    for item in data[:5]:
        hira = f"₩{item['hira_price']:,.0f}" if item.get('hira_price') else "없음"
        print(f"  {item['inn']}: CRIS {item['cris_trial_count']}건, HIRA {hira}")


def test_drug_detail():
    print("\n" + "=" * 60)
    print("[6] GET /api/v1/drugs/pembrolizumab")
    print("=" * 60)
    r = client.get("/api/v1/drugs/pembrolizumab")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"  INN: {data['inn']}")
    print(f"  FDA: {data['fda_approved']} ({data.get('fda_date')})")
    print(f"  EMA: {data['ema_approved']} ({data.get('ema_date')})")
    print(f"  MFDS: {data['mfds_approved']}")
    print(f"  HIRA: {data.get('hira_status')} (₩{data.get('hira_price', 0):,.0f})")
    print(f"  CRIS: {data['cris_trial_count']}건")
    print(f"  Score: {data['global_score']}점 ({data['hot_issue_level']})")
    print(f"  Summary: {data.get('summary', '')[:60]}...")


def test_medclaim():
    print("\n" + "=" * 60)
    print("[7] GET /api/v1/drugs/pembrolizumab/medclaim")
    print("=" * 60)
    r = client.get("/api/v1/drugs/pembrolizumab/medclaim")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"  INN: {data['inn']}")
    print(f"  HIRA Status: {data.get('hira_status')}")
    print(f"  Price: ₩{data.get('hira_price', 0):,.0f}")
    print(f"  Orphan: {data['is_orphan_drug']}")
    print(f"  High Cost: {data['is_high_cost']}")
    print(f"  Est. Burden: {data.get('estimated_burden')}")
    print(f"  Insights:")
    for insight in data.get('insights', []):
        print(f"    - {insight}")


def test_search():
    print("\n" + "=" * 60)
    print("[8] GET /api/v1/drugs/search?q=nivo")
    print("=" * 60)
    r = client.get("/api/v1/drugs/search?q=nivo")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Count: {len(data)}")
    for item in data[:5]:
        print(f"  {item['inn']}: {item['domestic_status']}")


if __name__ == "__main__":
    test_root()
    test_health()
    test_stats()
    test_hot_issues()
    test_imminent()
    test_drug_detail()
    test_medclaim()
    test_search()

    print("\n" + "=" * 60)
    print("API 테스트 완료!")
    print("=" * 60)
