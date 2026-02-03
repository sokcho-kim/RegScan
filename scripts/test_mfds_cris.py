"""MFDS + CRIS API 연동 테스트"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.ingest.mfds import MFDSClient, MFDSPermitIngestor
from regscan.ingest.cris import CRISClient, CRISTrialIngestor
from regscan.parse.mfds_parser import MFDSPermitParser
from regscan.parse.cris_parser import CRISTrialParser
from regscan.config import settings


async def test_mfds():
    """MFDS API 테스트"""
    print("\n" + "=" * 60)
    print("MFDS (식약처) 의약품 허가정보 API 테스트")
    print("=" * 60)

    if not settings.DATA_GO_KR_API_KEY:
        print("[ERROR] DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        print("  → .env 파일에 DATA_GO_KR_API_KEY=... 추가하세요")
        print("  → 발급: https://www.data.go.kr/data/15095677/openapi.do")
        return None

    try:
        async with MFDSClient() as client:
            # 전체 건수 확인
            total = await client.get_total_count()
            print(f"\n[MFDS] 전체 데이터: {total:,}건")

            # 샘플 데이터 조회
            response = await client.search_permits(num_of_rows=5)
            items = response.get("body", {}).get("items", [])

            print(f"[MFDS] 샘플 조회: {len(items)}건")

            # 파서 테스트
            parser = MFDSPermitParser()

            for i, item in enumerate(items[:3], 1):
                parsed = parser.parse_permit(item)
                print(f"\n--- 샘플 {i} ---")
                print(f"  품목명: {parsed['item_name']}")
                print(f"  업체명: {parsed['entp_name']}")
                print(f"  허가일: {parsed['permit_date_str']}")
                print(f"  주성분: {parsed['main_ingredient']}")
                print(f"  전문/일반: {parsed['etc_otc_code']}")

            return items

    except Exception as e:
        print(f"[ERROR] MFDS API 오류: {e}")
        return None


async def test_cris():
    """CRIS API 테스트"""
    print("\n" + "=" * 60)
    print("CRIS (임상연구정보서비스) 임상시험 API 테스트")
    print("=" * 60)

    if not settings.DATA_GO_KR_API_KEY:
        print("[ERROR] DATA_GO_KR_API_KEY가 설정되지 않았습니다.")
        return None

    try:
        async with CRISClient() as client:
            # 전체 건수 확인
            total = await client.get_total_count()
            print(f"\n[CRIS] 전체 데이터: {total:,}건")

            # 샘플 데이터 조회
            response = await client.search_trials(num_of_rows=5)
            items = response.get("body", {}).get("items", [])

            print(f"[CRIS] 샘플 조회: {len(items)}건")

            # 파서 테스트
            parser = CRISTrialParser()

            for i, item in enumerate(items[:3], 1):
                parsed = parser.parse_trial(item)
                print(f"\n--- 샘플 {i} ---")
                print(f"  등록번호: {parsed['trial_id']}")
                print(f"  제목: {parsed['title'][:50]}...")
                print(f"  Phase: {parsed['phase']}")
                print(f"  상태: {parsed['status_raw']}")
                print(f"  의뢰자: {parsed['sponsor']}")
                if parsed['drug_names']:
                    print(f"  시험약: {', '.join(parsed['drug_names'][:3])}")

            return items

    except Exception as e:
        print(f"[ERROR] CRIS API 오류: {e}")
        return None


async def test_ingestor_sample():
    """수집기 샘플 테스트 (소량)"""
    print("\n" + "=" * 60)
    print("수집기 샘플 테스트")
    print("=" * 60)

    mfds_items = []
    cris_items = []

    # MFDS 100건
    try:
        print("\n[MFDS] 100건 샘플 수집 중...")
        mfds_ingestor = MFDSPermitIngestor(max_items=100)
        mfds_items = await mfds_ingestor.fetch()
        print(f"[MFDS] 수집 완료: {len(mfds_items)}건")
    except Exception as e:
        print(f"[MFDS] 수집 실패: {e}")

    # CRIS 100건
    try:
        print("\n[CRIS] 100건 샘플 수집 중...")
        cris_ingestor = CRISTrialIngestor(max_items=100)
        cris_items = await cris_ingestor.fetch()
        print(f"[CRIS] 수집 완료: {len(cris_items)}건")
    except Exception as e:
        print(f"[CRIS] 수집 실패: {e}")
        print("  → CRIS API는 별도 활용신청 필요: https://www.data.go.kr/data/3033869/openapi.do")

    # 저장
    output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")

    mfds_file = output_dir / "mfds" / f"permits_{today}_sample.json"
    mfds_file.parent.mkdir(exist_ok=True)
    with open(mfds_file, "w", encoding="utf-8") as f:
        json.dump(mfds_items, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[저장] {mfds_file}")

    cris_file = output_dir / "cris" / f"trials_{today}_sample.json"
    cris_file.parent.mkdir(exist_ok=True)
    with open(cris_file, "w", encoding="utf-8") as f:
        json.dump(cris_items, f, ensure_ascii=False, indent=2, default=str)
    print(f"[저장] {cris_file}")

    return mfds_items, cris_items


async def main():
    print("=" * 60)
    print(" MFDS + CRIS API 연동 테스트")
    print("=" * 60)
    print(f"API Key 설정: {'있음' if settings.DATA_GO_KR_API_KEY else '없음'}")

    # 1. API 기본 테스트
    await test_mfds()
    await test_cris()

    # 2. 수집기 테스트
    if settings.DATA_GO_KR_API_KEY:
        await test_ingestor_sample()

    print("\n" + "=" * 60)
    print(" 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
