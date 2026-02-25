"""브리핑 기사 스냅샷 CLI

현재 output/briefings/ 의 개별 약물 JSON 파일을 버전 라벨로 복사해 보관한다.

사용법:
    python -m regscan.scripts.snapshot_articles --name "pre-fix"
    python -m regscan.scripts.snapshot_articles --name "post-v4"
    python -m regscan.scripts.snapshot_articles --list          # 기존 스냅샷 목록
"""

import json
import logging
import shutil
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from regscan.config import settings

logger = logging.getLogger(__name__)

BRIEFINGS_DIR = settings.BASE_DIR / "output" / "briefings"
SNAPSHOTS_DIR = BRIEFINGS_DIR / "snapshots"

# 스냅샷 대상에서 제외할 파일 접두어
EXCLUDE_PREFIXES = ("hot_issues_", "all_articles_", "compare")


def _is_article_json(path: Path) -> bool:
    """개별 약물 브리핑 JSON인지 판별"""
    if path.suffix != ".json":
        return False
    name = path.name
    if name.startswith("_"):
        return False
    for prefix in EXCLUDE_PREFIXES:
        if name.startswith(prefix):
            return False
    return True


def list_snapshots() -> list[dict]:
    """기존 스냅샷 목록 반환"""
    if not SNAPSHOTS_DIR.exists():
        return []
    results = []
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "_snapshot_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            results.append(meta)
        else:
            # 메타 없으면 디렉터리 이름만
            json_count = sum(1 for f in d.glob("*.json") if not f.name.startswith("_"))
            results.append({
                "name": d.name,
                "created_at": None,
                "file_count": json_count,
            })
    return results


def take_snapshot(name: str) -> Path:
    """현재 브리핑 JSON을 스냅샷으로 복사"""
    dest = SNAPSHOTS_DIR / name
    if dest.exists():
        raise FileExistsError(f"스냅샷 '{name}' 이미 존재합니다: {dest}")

    # 대상 파일 수집
    sources = [f for f in sorted(BRIEFINGS_DIR.glob("*.json")) if _is_article_json(f)]
    if not sources:
        raise FileNotFoundError(f"복사할 JSON 파일이 없습니다: {BRIEFINGS_DIR}")

    dest.mkdir(parents=True, exist_ok=True)

    for src in sources:
        shutil.copy2(src, dest / src.name)

    # 메타데이터 저장
    meta = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "file_count": len(sources),
    }
    (dest / "_snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return dest


def main():
    parser = ArgumentParser(description="브리핑 기사 스냅샷")
    parser.add_argument("--name", type=str, help="스냅샷 이름 (예: pre-fix, post-v4)")
    parser.add_argument("--list", action="store_true", help="기존 스냅샷 목록 출력")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.list:
        snapshots = list_snapshots()
        if not snapshots:
            print("저장된 스냅샷이 없습니다.")
            return
        print(f"\n{'이름':<20} {'생성일시':<22} {'파일수':>6}")
        print("-" * 52)
        for s in snapshots:
            ts = s.get("created_at") or "-"
            if ts and ts != "-":
                ts = ts[:19]
            print(f"{s['name']:<20} {ts:<22} {s['file_count']:>6}")
        print()
        return

    if not args.name:
        parser.error("--name 또는 --list 중 하나를 지정하세요.")

    dest = take_snapshot(args.name)
    meta_path = dest / "_snapshot_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    print(f"\n스냅샷 저장 완료:")
    print(f"  이름: {meta['name']}")
    print(f"  경로: {dest}")
    print(f"  파일: {meta['file_count']}건")
    print(f"  시간: {meta['created_at'][:19]}")
    print()


if __name__ == "__main__":
    main()
