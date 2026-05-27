"""MFDS 전체 허가정보 덤프 갱신 잡.

공공데이터포털 API는 날짜 필터를 지원하지 않고 약 4.3만건을 무작위 순서로
반환한다. 따라서 신규 허가를 탐지하려면 증분 수집이 불가능하며, 전체를
주기적으로 재수집해 캐시 파일을 통째로 갈아끼워야 한다.

이 스크립트는 전체 허가정보를 data/mfds/permits_full_YYYYMMDD.json 으로 저장하고,
오래된 덤프는 최근 N개만 남기고 정리한다. 일일스캔(daily_scanner._scan_mfds)이
이 파일을 읽으므로, 일일스캔 직전(또는 매일 1회)에 실행해야 한다.

사용법:
    python scripts/refresh_mfds_dump.py            # 전체 덤프 갱신
    python scripts/refresh_mfds_dump.py --keep 3   # 최근 3개 덤프만 유지
"""

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from regscan.config import settings
from regscan.ingest.mfds import MFDSPermitIngestor

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "mfds"


async def refresh(keep: int = 3) -> Path:
    """MFDS 전체 허가정보를 재수집해 캐시 파일로 저장하고 오래된 덤프를 정리."""
    if not settings.DATA_GO_KR_API_KEY:
        raise SystemExit("[ERROR] DATA_GO_KR_API_KEY 미설정")

    print(f"[MFDS] 전체 덤프 수집 시작... ({datetime.now():%Y-%m-%d %H:%M:%S})")
    ingestor = MFDSPermitIngestor()  # max_items=None → 전체 수집
    items = await ingestor.fetch()

    if not items:
        # 0건이면 기존 파일을 덮어쓰지 않는다 (멀쩡한 캐시 보호)
        raise SystemExit("[ERROR] 수집 0건 - API 응답/키 확인 필요. 기존 캐시 유지")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    out_file = OUTPUT_DIR / f"permits_full_{today}.json"
    out_file.write_text(
        json.dumps(items, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"[MFDS] 덤프 저장: {out_file.name} ({len(items):,}건)")

    # 오래된 덤프 정리 (최근 keep개만 유지) — 디스크 누적 방지
    dumps = sorted(OUTPUT_DIR.glob("permits_full_*.json"))
    for old in dumps[:-keep] if keep > 0 else []:
        old.unlink()
        print(f"[MFDS] 오래된 덤프 삭제: {old.name}")

    return out_file


def main() -> None:
    # 콘솔 한글 깨짐 방지 (스크립트 직접 실행 시에만)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    parser = argparse.ArgumentParser(description="MFDS 전체 허가정보 덤프 갱신")
    parser.add_argument(
        "--keep", type=int, default=3, help="유지할 최근 덤프 개수 (기본 3)"
    )
    args = parser.parse_args()
    asyncio.run(refresh(keep=args.keep))


if __name__ == "__main__":
    main()
