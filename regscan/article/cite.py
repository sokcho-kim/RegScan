"""기사 MD에 출처 블록을 붙이는 별도 후처리 스크립트

파이프라인과 분리된 단계. 생성된 기사 MD + 시그널 JSON을 받아서
기사별로 관련 출처를 매칭해 붙인다.

Usage:
    python -m regscan.article.cite output/articles/articles_2026-04-30-v16.md
    python -m regscan.article.cite output/articles/articles_2026-04-30-v16.md --signals output/signals/signals_2026-04-30_172154.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _find_latest_signals(signals_dir: Path) -> Path | None:
    """output/signals/ 에서 가장 최신 시그널 파일 찾기."""
    files = sorted(signals_dir.glob("signals_*.json"), reverse=True)
    return files[0] if files else None


def _collect_citations_for_body(body: str, signals: dict) -> list[str]:
    """기사 본문을 분석해서 관련 출처 URL을 수집."""
    citations: list[str] = []
    seen: set[str] = set()

    # 1) 기사 주제와 관련 높은 소스 타입 우선 정렬
    _SOURCE_PRIORITY_KEYWORDS = {
        "PMDA_REVIEW": ["PMDA", "의약품의료기기종합기구"],
        "PMDA_SAFETY": ["PMDA", "안전성"],
        "NICE_TA": ["NICE", "단일기술평가", "STA", "TA9"],
        "MFDS_PRESS": ["식약처", "식품의약품안전처"],
        "ASSEMBLY_BILL": ["개정안", "발의", "국회", "조문", "법률안"],
        "GNW_PRESS": ["GlobeNewsWire", "Teva", "Regeneron"],
        "KIPRIS_PATENT": ["특허", "KIPRIS"],
        "KHIDI_PHARMA_NEWS": ["KHIDI", "보건산업진흥원"],
    }
    def _source_relevance(src_type: str) -> int:
        kws = _SOURCE_PRIORITY_KEYWORDS.get(src_type, [])
        return sum(1 for kw in kws if kw in body)

    sorted_sources = sorted(signals.keys(), key=_source_relevance, reverse=True)

    for src_type in sorted_sources:
        sigs = signals[src_type]
        for sig in sigs:
            url = sig.get("url", "")
            if not url:
                continue
            sig_title = sig.get("title", "")

            # 본문에 시그널 키워드가 2개 이상 매칭되는지 확인
            if src_type == "ASSEMBLY_BILL":
                bill_short = re.sub(r"\s*(일부|전부)개정.*$", "", sig_title)
                proposer = sig.get("rst_proposer", sig.get("proposer", ""))[:10]
                if bill_short not in body and proposer not in body:
                    continue
            else:
                title_words = [w for w in re.findall(r"[가-힣]{3,}", sig_title)]
                if sum(1 for w in title_words[:6] if w in body) < 2:
                    continue

            if url not in seen:
                label = sig_title[:60]
                citations.append(f"- {label}: {url}" if label else f"- {url}")
                seen.add(url)
            if len(citations) >= 3:
                break
        if len(citations) >= 3:
            break

    # 2) 키워드 → 직접 링크 (기사 내용에 맞는 페이지)
    ta_ids = re.findall(r"\bTA(\d{3,4})\b", body)

    if "PMDA" in body or "의약품의료기기종합기구" in body:
        url = "https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0039.html"
        if url not in seen:
            citations.append(f"- PMDA 2025/26年度 승인 목록: {url}")
            seen.add(url)

    if ("NICE" in body or "단일기술평가" in body) and not ta_ids:
        url = "https://www.nice.org.uk/about/what-we-do/our-programmes/nice-guidance/nice-technology-appraisal-guidance"
        if url not in seen:
            citations.append(f"- NICE Technology Appraisal: {url}")
            seen.add(url)

    if any(kw in body for kw in ["WLA", "WHO Listed Authority", "우수규제기관", "참조국"]):
        url = "https://www.who.int/initiatives/who-listed-authority-reg-authorities/wla"
        if url not in seen:
            citations.append(f"- WHO Listed Authorities: {url}")
            seen.add(url)

    if any(kw in body for kw in ["KIPRIS", "특허정보"]):
        url = "http://www.kipris.or.kr/"
        if url not in seen:
            citations.append(f"- KIPRIS 특허정보검색: {url}")
            seen.add(url)

    # 3) TA 번호 → NICE 개별 페이지
    for ta_num in ta_ids:
        if len(citations) >= 6:
            break
        url = f"https://www.nice.org.uk/guidance/ta{ta_num}"
        if url not in seen:
            citations.append(f"- NICE TA{ta_num}: {url}")
            seen.add(url)

    return citations[:6]


def add_citations(md_text: str, signals: dict) -> str:
    """MD 텍스트의 각 기사에 출처 블록을 추가."""
    lines = md_text.split("\n")
    result: list[str] = []
    current_body_lines: list[str] = []
    in_article = False
    article_started = False

    for line in lines:
        # 기사 시작
        if re.match(r"^##\s+\d+\.\s+", line):
            # 이전 기사에 출처 붙이기
            if in_article and current_body_lines:
                body = "\n".join(current_body_lines)
                cites = _collect_citations_for_body(body, signals)
                if cites:
                    result.append("")
                    result.append("**출처**")
                    result.extend(cites)
                current_body_lines = []

            in_article = True
            article_started = True
            result.append(line)
            continue

        # 구분선 → 기사 끝
        if line.strip() == "---" and in_article:
            body = "\n".join(current_body_lines)
            cites = _collect_citations_for_body(body, signals)
            if cites:
                result.append("")
                result.append("**출처**")
                result.extend(cites)
            current_body_lines = []
            in_article = False
            result.append("")
            result.append(line)
            continue

        # guardrail 줄은 스킵 (출처 앞에 넣음)
        if line.strip().startswith("> guardrail:"):
            result.append(line)
            continue

        # 기존 출처 블록 제거 (재생성하니까)
        if line.strip() == "**출처**":
            # 다음 줄들 중 "- "로 시작하는 것들 스킵
            continue
        if in_article and line.startswith("- ") and re.search(r"https?://", line):
            continue

        if in_article:
            current_body_lines.append(line)

        result.append(line)

    # 마지막 기사 처리
    if in_article and current_body_lines:
        body = "\n".join(current_body_lines)
        cites = _collect_citations_for_body(body, signals)
        if cites:
            result.append("")
            result.append("**출처**")
            result.extend(cites)

    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(description="기사 MD에 출처 블록 추가")
    parser.add_argument("md_file", help="기사 MD 파일 경로")
    parser.add_argument("--signals", help="시그널 JSON 경로 (생략 시 최신 자동 탐색)")
    parser.add_argument("--output", "-o", help="출력 파일 (생략 시 원본 덮어쓰기)")
    args = parser.parse_args()

    md_path = Path(args.md_file)
    if not md_path.exists():
        print(f"파일 없음: {md_path}")
        sys.exit(1)

    # 시그널 로드
    if args.signals:
        sig_path = Path(args.signals)
    else:
        sig_dir = md_path.parent.parent / "signals"
        sig_path = _find_latest_signals(sig_dir)

    if not sig_path or not sig_path.exists():
        print(f"시그널 파일 없음. --signals 옵션으로 지정하세요.")
        sys.exit(1)

    signals = json.loads(sig_path.read_text(encoding="utf-8"))
    print(f"시그널: {sig_path.name} ({sum(len(v) for v in signals.values())}건)")

    # MD 읽기 + 출처 추가
    md_text = md_path.read_text(encoding="utf-8")
    cited = add_citations(md_text, signals)

    # 저장
    out_path = Path(args.output) if args.output else md_path
    out_path.write_text(cited, encoding="utf-8")
    print(f"출처 추가 완료: {out_path}")


if __name__ == "__main__":
    main()
