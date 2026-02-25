"""브리핑 기사 스냅샷 CLI

현재 output/briefings/ 의 개별 약물 JSON 파일을 버전 라벨로 복사해 보관한다.

사용법:
    python -m regscan.scripts.snapshot_articles --name "pre-fix"
    python -m regscan.scripts.snapshot_articles --name "post-v4"
    python -m regscan.scripts.snapshot_articles --from-commit fded439 --name "pre-v4"
    python -m regscan.scripts.snapshot_articles --list          # 기존 스냅샷 목록
"""

import json
import logging
import shutil
import subprocess
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


def take_auto_snapshot(pipeline_version: str = "unknown") -> Path:
    """publish_articles 완료 후 자동 호출 — 날짜 기반 스냅샷 + 프롬프트 저장"""
    today = datetime.now().strftime("%Y-%m-%d")
    base_name = f"{today}_{pipeline_version}"

    # 동일 날짜+버전이면 _2, _3 접미 추가
    dest = SNAPSHOTS_DIR / base_name
    seq = 1
    while dest.exists():
        seq += 1
        dest = SNAPSHOTS_DIR / f"{base_name}_{seq}"
    name = dest.name

    # 대상 파일 수집
    sources = [f for f in sorted(BRIEFINGS_DIR.glob("*.json")) if _is_article_json(f)]
    if not sources:
        logger.warning("자동 스냅샷: 복사할 JSON 없음")
        return dest

    dest.mkdir(parents=True, exist_ok=True)

    for src in sources:
        shutil.copy2(src, dest / src.name)

    # 프롬프트 저장
    prompt_text = _dump_current_prompts(pipeline_version)
    if prompt_text:
        (dest / "_prompts.txt").write_text(prompt_text, encoding="utf-8")

    # 메타데이터
    meta = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "file_count": len(sources),
        "pipeline_version": pipeline_version,
        "auto": True,
    }
    (dest / "_snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("자동 스냅샷 저장: %s (%d건)", name, len(sources))
    return dest


def _dump_current_prompts(pipeline_version: str) -> str:
    """현재 prompts.py의 시스템/유저 프롬프트를 텍스트로 덤프"""
    try:
        from regscan.report.prompts import (
            SYSTEM_PROMPT_V4, BRIEFING_REPORT_PROMPT_V4,
            SYSTEM_PROMPT_V3, BRIEFING_REPORT_PROMPT_V3,
        )
    except ImportError:
        return ""

    lines = [
        f"# RegScan Prompt Snapshot — {pipeline_version}",
        f"# Generated: {datetime.now().isoformat()}\n",
    ]

    if pipeline_version.startswith("v4") or pipeline_version.startswith("V4"):
        lines += [
            "=" * 60,
            "SYSTEM_PROMPT_V4",
            "=" * 60,
            SYSTEM_PROMPT_V4,
            "\n" + "=" * 60,
            "BRIEFING_REPORT_PROMPT_V4",
            "=" * 60,
            BRIEFING_REPORT_PROMPT_V4,
        ]
    else:
        lines += [
            "=" * 60,
            "SYSTEM_PROMPT_V3",
            "=" * 60,
            SYSTEM_PROMPT_V3,
            "\n" + "=" * 60,
            "BRIEFING_REPORT_PROMPT_V3",
            "=" * 60,
            BRIEFING_REPORT_PROMPT_V3,
        ]

    return "\n".join(lines)


def take_snapshot_from_commit(name: str, commit: str) -> Path:
    """git 커밋에서 브리핑 JSON을 추출해 스냅샷으로 저장"""
    dest = SNAPSHOTS_DIR / name
    if dest.exists():
        raise FileExistsError(f"스냅샷 '{name}' 이미 존재합니다: {dest}")

    repo_root = settings.BASE_DIR
    briefings_rel = "output/briefings"

    # git ls-tree 로 해당 커밋의 briefings 파일 목록 가져오기
    result = subprocess.run(
        ["git", "ls-tree", "--name-only", commit, f"{briefings_rel}/"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise ValueError(f"커밋 '{commit}'에서 파일 목록을 가져올 수 없습니다: {result.stderr.strip()}")

    all_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # JSON만, 제외 패턴 적용
    json_files = []
    for fpath in all_files:
        fname = fpath.rsplit("/", 1)[-1]
        if not fname.endswith(".json"):
            continue
        if fname.startswith("_"):
            continue
        skip = False
        for prefix in EXCLUDE_PREFIXES:
            if fname.startswith(prefix):
                skip = True
                break
        if not skip:
            json_files.append((fpath, fname))

    if not json_files:
        raise FileNotFoundError(f"커밋 '{commit}'에 브리핑 JSON이 없습니다.")

    dest.mkdir(parents=True, exist_ok=True)

    # 커밋 정보 (날짜)
    commit_info = subprocess.run(
        ["git", "log", "-1", "--format=%H %ai %s", commit],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8",
    )
    commit_desc = commit_info.stdout.strip() if commit_info.returncode == 0 else commit

    # 각 파일을 git show로 추출
    count = 0
    for git_path, fname in json_files:
        show = subprocess.run(
            ["git", "show", f"{commit}:{git_path}"],
            cwd=repo_root, capture_output=True, text=True, encoding="utf-8",
        )
        if show.returncode != 0:
            logger.warning("  건너뜀: %s (%s)", fname, show.stderr.strip())
            continue
        (dest / fname).write_text(show.stdout, encoding="utf-8")
        count += 1

    # 메타데이터
    meta = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "file_count": count,
        "from_commit": commit_desc,
    }
    (dest / "_snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return dest


def main():
    parser = ArgumentParser(description="브리핑 기사 스냅샷")
    parser.add_argument("--name", type=str, help="스냅샷 이름 (예: pre-fix, post-v4)")
    parser.add_argument("--from-commit", type=str, dest="from_commit",
                        help="git 커밋 해시에서 추출 (예: fded439)")
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

    if args.from_commit:
        dest = take_snapshot_from_commit(args.name, args.from_commit)
    else:
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
