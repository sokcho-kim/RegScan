"""기사 버전 비교 뷰어 생성기

두 스냅샷의 브리핑 JSON을 비교하는 자체 완결형 HTML을 생성한다.

사용법:
    python -m regscan.scripts.compare_articles --a "pre-fix" --b "post-v4"
    python -m regscan.scripts.compare_articles   # 대화형: 스냅샷 목록에서 선택
"""

import json
import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from regscan.config import settings
from regscan.scripts.snapshot_articles import (
    BRIEFINGS_DIR,
    SNAPSHOTS_DIR,
    list_snapshots,
    _is_article_json,
)

logger = logging.getLogger(__name__)

OUTPUT_HTML = BRIEFINGS_DIR / "compare.html"


# ── 데이터 로딩 ──────────────────────────────────────────

def _load_snapshot(name: str) -> dict[str, dict]:
    """스냅샷 디렉터리에서 INN → JSON dict 매핑 로드"""
    snap_dir = SNAPSHOTS_DIR / name
    if not snap_dir.exists():
        raise FileNotFoundError(f"스냅샷 '{name}'을 찾을 수 없습니다: {snap_dir}")

    articles: dict[str, dict] = {}
    for f in sorted(snap_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        inn = data.get("inn", f.stem)
        articles[inn] = data
    return articles


def _pick_interactive() -> tuple[str, str]:
    """대화형으로 스냅샷 2개 선택"""
    snapshots = list_snapshots()
    if len(snapshots) < 2:
        print("비교하려면 스냅샷이 2개 이상 필요합니다.")
        print("  python -m regscan.scripts.snapshot_articles --name <이름>")
        sys.exit(1)

    print("\n사용 가능한 스냅샷:")
    for i, s in enumerate(snapshots, 1):
        ts = (s.get("created_at") or "-")[:19]
        print(f"  [{i}] {s['name']:<20}  {ts}  ({s['file_count']}건)")

    def _ask(label: str) -> str:
        while True:
            raw = input(f"\n{label} 번호 또는 이름: ").strip()
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(snapshots):
                    return snapshots[idx]["name"]
            else:
                if any(s["name"] == raw for s in snapshots):
                    return raw
            print("  올바른 번호 또는 이름을 입력하세요.")

    a = _ask("Version A (기준)")
    b = _ask("Version B (비교)")
    return a, b


# ── HTML 생성 ─────────────────────────────────────────────

def generate_compare_html(name_a: str, name_b: str) -> str:
    """두 스냅샷을 비교하는 단일 HTML 문자열 생성"""
    articles_a = _load_snapshot(name_a)
    articles_b = _load_snapshot(name_b)

    # INN 기준 매칭
    all_inns = sorted(set(articles_a.keys()) | set(articles_b.keys()))

    # 비교 데이터 구조
    compare_data = []
    for inn in all_inns:
        compare_data.append({
            "inn": inn,
            "a": articles_a.get(inn),
            "b": articles_b.get(inn),
        })

    data_json = json.dumps(compare_data, ensure_ascii=False, default=str)

    return _HTML_TEMPLATE.replace("{{NAME_A}}", name_a).replace(
        "{{NAME_B}}", name_b
    ).replace("{{DATA_JSON}}", data_json)


# ── HTML 템플릿 ───────────────────────────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RegScan Article Comparison</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif; }
  .panel { min-height: 80px; }
  .metric-pass { color: #16a34a; }
  .metric-fail { color: #dc2626; }
  .section-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
                   letter-spacing: 0.05em; color: #6b7280; margin-bottom: 0.25rem; }
  .section-content { white-space: pre-wrap; line-height: 1.7; }
  .diff-highlight { background: #fef08a; padding: 0 2px; border-radius: 2px; }
  .absent-badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
                  background: #f3f4f6; color: #9ca3af; font-size: 0.8rem; }
  select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%236b7280' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
           background-repeat: no-repeat; background-position: right 0.75rem center; }
  .key-point { margin-bottom: 0.4rem; padding-left: 1rem; text-indent: -1rem; }
  .key-point::before { content: "• "; color: #6366f1; font-weight: 700; }
  table.fact-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  table.fact-table th, table.fact-table td { border: 1px solid #e5e7eb; padding: 4px 8px; text-align: left; }
  table.fact-table th { background: #f9fafb; font-weight: 600; }
</style>
</head>
<body class="bg-gray-50 text-gray-800">

<!-- ── 헤더 ────────────────────────────────── -->
<header class="bg-white border-b sticky top-0 z-10 shadow-sm">
  <div class="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-4 flex-wrap">
    <h1 class="text-lg font-bold text-indigo-700 whitespace-nowrap">RegScan A/B Compare</h1>
    <select id="drugSelect" class="border rounded-lg px-3 py-1.5 pr-8 text-sm bg-white focus:ring-2 focus:ring-indigo-300"></select>
    <span class="text-sm text-gray-500" id="drugCount"></span>
    <div class="ml-auto flex gap-3 text-sm">
      <span class="px-2 py-0.5 rounded bg-blue-100 text-blue-700 font-medium">A: {{NAME_A}}</span>
      <span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">B: {{NAME_B}}</span>
    </div>
  </div>
</header>

<!-- ── 메인 ────────────────────────────────── -->
<main class="max-w-screen-2xl mx-auto px-4 py-6" id="mainContent"></main>

<script>
// ── 데이터 ──
const DATA = {{DATA_JSON}};
const NAME_A = "{{NAME_A}}";
const NAME_B = "{{NAME_B}}";

// ── 품질 지표 체크 ──
const BANNED_PHRASES = [
  "혁명적", "획기적", "사실상 제도권 밖", "게임체인저", "판도를 바꿀",
  "꿈의 신약", "기적", "만병통치", "완치", "100%"
];
const REPETITIVE_PHRASES = [
  "판매권자 부재", "시장성 판단 보류", "보험 적용 가능성 열려",
  "급여 가능성이 열려", "전액 환자 부담", "제도권 처방 경로"
];

function checkQuality(article) {
  if (!article) return null;
  const allText = [
    article.headline || "",
    article.subtitle || "",
    ...(article.key_points || []),
    article.global_section || "",
    article.domestic_section || "",
    article.medclaim_section || "",
  ].join(" ");

  // 반복 문구
  let repetitionCount = 0;
  for (const phrase of REPETITIVE_PHRASES) {
    const re = new RegExp(phrase, "g");
    const matches = allText.match(re);
    if (matches) repetitionCount += matches.length;
  }

  // 금지 표현
  let bannedCount = 0;
  const bannedFound = [];
  for (const phrase of BANNED_PHRASES) {
    if (allText.includes(phrase)) {
      bannedCount++;
      bannedFound.push(phrase);
    }
  }

  // 숫자 훅 (headline 또는 global 첫 문장에 숫자)
  const hookTarget = (article.headline || "") + " " +
    (article.global_section || "").split(/[.!?\n]/)[0];
  const hasNumberHook = /\d/.test(hookTarget);

  // MOA 연쇄 (→ 패턴)
  const hasMoaChain = allText.includes("→") &&
    (allText.match(/→/g) || []).length >= 2;

  // 한계점 서술
  const limitKeywords = ["다만", "한계", "CI", "p-value", "p=", "유의성", "95%"];
  const hasLimitation = limitKeywords.some(kw => allText.includes(kw));

  // 섹션별 글자수
  const lengths = {
    headline: (article.headline || "").length,
    global: (article.global_section || "").length,
    domestic: (article.domestic_section || "").length,
    medclaim: (article.medclaim_section || "").length,
    total: allText.length,
  };

  return {
    repetitionCount,
    bannedCount,
    bannedFound,
    hasNumberHook,
    hasMoaChain,
    hasLimitation,
    lengths,
  };
}

// ── 마크다운 테이블 → HTML ──
function mdTableToHtml(md) {
  if (!md) return "";
  const lines = md.trim().split("\n").filter(l => l.trim());
  if (lines.length < 2) return md;
  const parseRow = line => line.split("|").map(c => c.trim()).filter(c => c);

  const headers = parseRow(lines[0]);
  // skip separator (line 1)
  const rows = lines.slice(2).map(parseRow);

  let html = '<table class="fact-table"><thead><tr>';
  for (const h of headers) html += `<th>${h}</th>`;
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    for (const cell of row) html += `<td>${cell}</td>`;
    html += "</tr>";
  }
  html += "</tbody></table>";
  return html;
}

// ── 렌더링 헬퍼 ──
function esc(s) {
  if (!s) return "";
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function renderMetric(label, pass, detail) {
  const icon = pass ? "✅" : "❌";
  const cls = pass ? "metric-pass" : "metric-fail";
  return `<div class="flex items-center gap-1.5 text-sm">
    <span>${icon}</span>
    <span class="${cls}">${label}</span>
    ${detail ? `<span class="text-gray-400 text-xs">${detail}</span>` : ""}
  </div>`;
}

function renderQualityCard(q, version) {
  if (!q) return `<div class="absent-badge">데이터 없음</div>`;
  return `
    <div class="bg-white rounded-lg border p-3 space-y-1">
      <div class="text-xs font-semibold text-gray-500 mb-2">★ Quality Metrics (${version})</div>
      ${renderMetric("반복 문구", q.repetitionCount === 0, q.repetitionCount + "회")}
      ${renderMetric("금지 표현", q.bannedCount === 0,
        q.bannedCount > 0 ? q.bannedFound.join(", ") : "0건")}
      ${renderMetric("숫자 훅", q.hasNumberHook, "")}
      ${renderMetric("MOA 연쇄", q.hasMoaChain, "")}
      ${renderMetric("한계점 서술", q.hasLimitation, "")}
      <div class="pt-1 border-t mt-1 text-xs text-gray-400">
        글자수: 전체 ${q.lengths.total.toLocaleString()} ·
        글로벌 ${q.lengths.global.toLocaleString()} ·
        국내 ${q.lengths.domestic.toLocaleString()} ·
        청구 ${q.lengths.medclaim.toLocaleString()}
      </div>
    </div>`;
}

function renderSection(label, emoji, textA, textB) {
  const a = textA ? esc(textA) : '<span class="absent-badge">없음</span>';
  const b = textB ? esc(textB) : '<span class="absent-badge">없음</span>';
  return `
    <div class="grid grid-cols-2 gap-4">
      <div class="panel">
        <div class="section-label">${emoji} ${label} (A)</div>
        <div class="section-content text-sm">${a}</div>
      </div>
      <div class="panel">
        <div class="section-label">${emoji} ${label} (B)</div>
        <div class="section-content text-sm">${b}</div>
      </div>
    </div>`;
}

function renderKeyPoints(kpA, kpB) {
  const renderList = (kps) => {
    if (!kps || kps.length === 0) return '<span class="absent-badge">없음</span>';
    return kps.map(p => `<div class="key-point">${esc(p)}</div>`).join("");
  };
  return `
    <div class="grid grid-cols-2 gap-4">
      <div class="panel">
        <div class="section-label">🔑 Key Points (A: ${kpA ? kpA.length : 0})</div>
        ${renderList(kpA)}
      </div>
      <div class="panel">
        <div class="section-label">🔑 Key Points (B: ${kpB ? kpB.length : 0})</div>
        ${renderList(kpB)}
      </div>
    </div>`;
}

function renderV4Facts(factsA, factsB) {
  if (!factsA && !factsB) return "";
  const render = (f, label) => {
    if (!f) return `<div class="absent-badge">V4 팩트 없음</div>`;
    return `
      <div class="space-y-2">
        <div class="text-sm"><strong>D-Day:</strong> ${esc(f.d_day_text || "")}</div>
        <div>
          <div class="text-xs font-medium text-gray-500 mb-1">승인 현황</div>
          ${mdTableToHtml(f.approval_summary_table || "")}
        </div>
        <div>
          <div class="text-xs font-medium text-gray-500 mb-1">비용 시나리오</div>
          ${mdTableToHtml(f.cost_scenario_table || "")}
        </div>
      </div>`;
  };
  return `
    <div class="grid grid-cols-2 gap-4">
      <div class="panel">
        <div class="section-label">📊 V4 Facts (A)</div>
        ${render(factsA, "A")}
      </div>
      <div class="panel">
        <div class="section-label">📊 V4 Facts (B)</div>
        ${render(factsB, "B")}
      </div>
    </div>`;
}

// ── 메인 렌더 ──
function renderDrug(entry) {
  const a = entry.a;
  const b = entry.b;
  const qA = checkQuality(a);
  const qB = checkQuality(b);

  const scoreA = a?._score ?? a?.source_data?.global_score ?? "-";
  const scoreB = b?._score ?? b?.source_data?.global_score ?? "-";
  const versionA = a?._pipeline_version || "?";
  const versionB = b?._pipeline_version || "?";

  return `
    <div class="space-y-4">
      <!-- 메타 배지 -->
      <div class="grid grid-cols-2 gap-4">
        <div class="flex gap-2 text-xs">
          <span class="px-2 py-0.5 rounded bg-gray-100">Score: ${scoreA}</span>
          <span class="px-2 py-0.5 rounded bg-gray-100">Pipeline: ${versionA}</span>
        </div>
        <div class="flex gap-2 text-xs">
          <span class="px-2 py-0.5 rounded bg-gray-100">Score: ${scoreB}</span>
          <span class="px-2 py-0.5 rounded bg-gray-100">Pipeline: ${versionB}</span>
        </div>
      </div>

      <!-- 품질 지표 -->
      <div class="grid grid-cols-2 gap-4">
        <div>${renderQualityCard(qA, NAME_A)}</div>
        <div>${renderQualityCard(qB, NAME_B)}</div>
      </div>

      <!-- Headline -->
      ${renderSection("Headline", "📰", a?.headline, b?.headline)}

      <!-- Subtitle -->
      ${renderSection("Subtitle", "📌", a?.subtitle, b?.subtitle)}

      <!-- Key Points -->
      ${renderKeyPoints(a?.key_points, b?.key_points)}

      <!-- V4 Facts -->
      ${renderV4Facts(a?._v4_facts, b?._v4_facts)}

      <!-- Global Section -->
      ${renderSection("Global Insight", "🌍", a?.global_section, b?.global_section)}

      <!-- Domestic Section -->
      ${renderSection("Domestic Insight", "🇰🇷", a?.domestic_section, b?.domestic_section)}

      <!-- MedClaim Section -->
      ${renderSection("MedClaim Action", "💊", a?.medclaim_section, b?.medclaim_section)}
    </div>`;
}

// ── 초기화 ──
function init() {
  const select = document.getElementById("drugSelect");
  const main = document.getElementById("mainContent");
  const countEl = document.getElementById("drugCount");

  // 드롭다운 채우기
  DATA.forEach((entry, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    const inA = entry.a ? "A" : "-";
    const inB = entry.b ? "B" : "-";
    opt.textContent = `${entry.inn}  [${inA}/${inB}]`;
    select.appendChild(opt);
  });

  countEl.textContent = `${DATA.length}개 약물`;

  function render() {
    const idx = parseInt(select.value);
    main.innerHTML = renderDrug(DATA[idx]);
  }

  select.addEventListener("change", render);
  if (DATA.length > 0) render();
}

document.addEventListener("DOMContentLoaded", init);
</script>

</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = ArgumentParser(description="기사 버전 비교 뷰어 생성")
    parser.add_argument("--a", dest="name_a", type=str, help="Version A 스냅샷 이름")
    parser.add_argument("--b", dest="name_b", type=str, help="Version B 스냅샷 이름")
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help=f"출력 HTML 경로 (기본: {OUTPUT_HTML})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 대화형 또는 인자
    if args.name_a and args.name_b:
        name_a, name_b = args.name_a, args.name_b
    else:
        name_a, name_b = _pick_interactive()

    logger.info("비교 생성: %s (A) vs %s (B)", name_a, name_b)

    html = generate_compare_html(name_a, name_b)

    out_path = Path(args.output) if args.output else OUTPUT_HTML
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    logger.info("비교 HTML 저장: %s", out_path)
    print(f"\n비교 페이지 생성 완료: {out_path}")
    print(f"  Version A: {name_a}")
    print(f"  Version B: {name_b}")
    print(f"  브라우저에서 열어 확인하세요.\n")


if __name__ == "__main__":
    main()
