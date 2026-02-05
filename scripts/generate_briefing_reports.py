"""핫이슈 약물 브리핑 리포트 일괄 생성"""

import sys
import io
import json
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from regscan.api.main import app

client = TestClient(app)
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "briefings"


def generate_hot_issue_reports(use_llm: bool = True, limit: int = 10):
    """핫이슈 약물 브리핑 리포트 생성"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 핫이슈 목록 조회
    print(f"[1] 핫이슈 약물 조회 (limit={limit})...")
    r = client.get(f"/api/v1/hot-issues?limit={limit}")
    if r.status_code != 200:
        print(f"Error: {r.text}")
        return

    hot_issues = r.json()
    print(f"    → {len(hot_issues)}건 조회됨\n")

    reports = []

    for i, item in enumerate(hot_issues, 1):
        inn = item['inn']
        score = item['global_score']
        print(f"[{i}/{len(hot_issues)}] {inn} (score: {score})...", end=" ")

        # 브리핑 생성
        r = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm={str(use_llm).lower()}")
        if r.status_code == 200:
            data = r.json()
            reports.append({
                "inn": inn,
                "score": score,
                "data": data
            })
            print("OK")

            # 개별 마크다운 파일 저장
            md_file = OUTPUT_DIR / f"{inn.lower().replace(' ', '_')}.md"
            md_file.write_text(data['markdown'], encoding='utf-8')
        else:
            print(f"FAILED ({r.status_code})")

    # 통합 리포트 생성
    today = datetime.now().strftime("%Y-%m-%d")
    combined_md = f"""# RegScan 핫이슈 브리핑 리포트

**생성일:** {today}
**대상:** 글로벌 승인 + 국내 미허가/미급여 약물 (Hot Issue Score >= 60)
**건수:** {len(reports)}건

---

## 목차

"""
    for i, r in enumerate(reports, 1):
        combined_md += f"{i}. [{r['inn']}](#{r['inn'].lower().replace(' ', '-')}) (Score: {r['score']})\n"

    combined_md += "\n---\n\n"

    for r in reports:
        combined_md += f"## {r['inn']}\n\n"
        combined_md += f"**Hot Issue Score:** {r['score']}\n\n"
        # 마크다운에서 제목 부분 제외하고 내용만
        md_content = r['data']['markdown']
        # 첫 번째 # 제목 라인 제거
        lines = md_content.split('\n')
        if lines[0].startswith('# '):
            lines = lines[1:]
        combined_md += '\n'.join(lines)
        combined_md += "\n\n---\n\n"

    # 통합 파일 저장
    combined_file = OUTPUT_DIR / f"hot_issues_{today}.md"
    combined_file.write_text(combined_md, encoding='utf-8')
    print(f"\n통합 리포트 저장: {combined_file}")

    # JSON 저장
    json_file = OUTPUT_DIR / f"hot_issues_{today}.json"
    json_data = {
        "generated_at": datetime.now().isoformat(),
        "use_llm": use_llm,
        "count": len(reports),
        "reports": [
            {
                "inn": r['inn'],
                "score": r['score'],
                "headline": r['data']['headline'],
                "subtitle": r['data']['subtitle'],
                "key_points": r['data']['key_points'],
            }
            for r in reports
        ]
    }
    json_file.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"JSON 저장: {json_file}")

    return reports


def generate_single_report(inn: str, use_llm: bool = True):
    """단일 약물 브리핑 생성"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"브리핑 생성: {inn}...")
    r = client.get(f"/api/v1/drugs/{inn}/briefing?use_llm={str(use_llm).lower()}")

    if r.status_code == 200:
        data = r.json()
        md_file = OUTPUT_DIR / f"{inn.lower().replace(' ', '_')}.md"
        md_file.write_text(data['markdown'], encoding='utf-8')
        print(f"저장: {md_file}")
        print("\n" + data['markdown'])
        return data
    else:
        print(f"Error: {r.status_code} - {r.text}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="브리핑 리포트 생성")
    parser.add_argument("--inn", type=str, help="단일 약물 INN")
    parser.add_argument("--limit", type=int, default=10, help="핫이슈 개수")
    parser.add_argument("--no-llm", action="store_true", help="템플릿 기반 (LLM 미사용)")

    args = parser.parse_args()
    use_llm = not args.no_llm

    if args.inn:
        generate_single_report(args.inn, use_llm=use_llm)
    else:
        generate_hot_issue_reports(use_llm=use_llm, limit=args.limit)
