"""HIRA biz.hira.or.kr 적용약가파일 다운로드 자동화

Nexacro SSV API로 최신 약가파일 메타 조회 + 수동 다운로드 가이드.
Dext5 파일 다운로드는 Nexacro 런타임 세션 종속이라 API 자동화 불가 →
수동 다운로드 후 data/hira/downloads/에 넣으면 자동 변환.

Usage:
    # 최신 약가파일 확인
    python scripts/download_hira_yakga.py

    # 수동 다운로드 후 변환
    python -m regscan.workers.drug_price_collector --convert-only data/hira/downloads/파일명.xlsx
"""

from __future__ import annotations

import asyncio
import logging
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

RS = "\x1e"
US = "\x1f"
ETX = "\x03"

BBS_ID = "BBSMSTR_000000000676"


def build_ssv_header(cookies: dict) -> str:
    ssv = "SSV:utf-8" + RS
    ssv += f'JSESSIONID={cookies.get("JSESSIONID", "null")}' + RS
    ssv += f'BIZINTERSESSION={cookies.get("BIZINTERSESSION", "")}' + RS
    ssv += f'WMONID={cookies.get("WMONID", "")}' + RS
    ssv += "browserType=Chrome" + RS + "osVersion=Windows 10" + RS
    ssv += "navigatorName=Chrome" + RS + "navigatorVersion=147" + RS
    return ssv


async def fetch_ssv(page, url: str, body: str) -> str:
    return await page.evaluate(
        """async ([url, body]) => {
            const r = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'text/xml', 'Accept': 'application/xml, text/xml, */*',
                           'X-Requested-With': 'XMLHttpRequest'},
                body: body
            });
            return await r.text();
        }""",
        [url, body],
    )


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        ad_pages = []
        context.on("page", lambda p: ad_pages.append(p))

        page = await context.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        log.info("[1] biz.hira.or.kr 접속...")
        try:
            await page.goto("https://biz.hira.or.kr", wait_until="load", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(5)

        # 광고 팝업 닫기
        for p in ad_pages:
            try:
                if not p.is_closed() and ("GuideP4" in p.url or "Popup.xfdl" in p.url):
                    await p.close()
            except Exception:
                pass

        main_page = None
        for p in context.pages:
            if not p.is_closed() and "index.do" in p.url:
                main_page = p
                break

        if not main_page:
            log.error("메인 페이지 없음")
            await browser.close()
            return

        # InfoBank 열기
        log.info("[2] InfoBank 열기...")
        rect = await main_page.evaluate("""() => {
            var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while(w.nextNode()) {
                if (w.currentNode.textContent.includes('심사기준 종합')) {
                    var r = w.currentNode.parentElement.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
        }""")

        async with context.expect_page(timeout=15000) as ib_info:
            await main_page.mouse.click(rect["x"], rect["y"])

        ib_page = await ib_info.value
        ib_page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        await asyncio.sleep(8)

        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        header = build_ssv_header(cookies)

        # BBS 목록 조회
        log.info("[3] 적용약가파일 검색...")
        bbs_ssv = header + "Dataset:dsParam" + RS
        cols = [
            "_RowType_", "brdTyBltNo:STRING(256)", "bltNo:STRING(256)",
            "totCnt:STRING(256)", "currentPage:STRING(256)",
            "recordCountPerPage:STRING(256)", "firstIndex:STRING(256)",
            "lastIndex:STRING(256)", "bbsId:STRING(256)",
            "cbSearchCnd:STRING(256)", "edSearchWrd:STRING(256)",
            "nttId:STRING(256)", "atchFileId:STRING(256)",
            "codeId:STRING(256)", "catType01Val:STRING(256)",
            "catType02Val:STRING(256)", "catType03Val:STRING(256)",
        ]
        bbs_ssv += US.join(cols) + RS
        vals = ["N", ETX, ETX, ETX, "1", "20", "0", ETX,
                BBS_ID, "all", ETX, ETX, ETX, ETX, ETX, ETX]
        bbs_ssv += US.join(vals) + RS + RS
        bbs_ssv += "Dataset:gdsCurrentMenu" + RS
        bbs_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        bbs_result = await fetch_ssv(ib_page, "/qya/bbs/selectComBbsList.ndo", bbs_ssv)

        # 적용약가 게시글 파싱
        yakga_posts = []
        for row in bbs_result.split(RS):
            if "적용약가" in row:
                fields = row.split(US)
                if len(fields) > 25:
                    yakga_posts.append({
                        "ntt_id": fields[5],
                        "atch_id": fields[25],
                        "title": fields[11],
                        "date": fields[17][:8] if len(fields[17]) >= 8 else "",
                        "dept": fields[32] if len(fields) > 32 else "",
                    })

        if not yakga_posts:
            log.error("적용약가 게시글 없음")
            await browser.close()
            return

        latest = yakga_posts[0]
        log.info("  최신: %s", latest["title"])
        log.info("  게시일: %s, 부서: %s", latest["date"], latest["dept"])
        log.info("  nttId=%s, atchFileId=%s", latest["ntt_id"], latest["atch_id"])

        # 파일 목록 조회
        log.info("[4] 첨부파일 목록...")
        file_ssv = header + "Dataset:dsParam" + RS
        file_ssv += US.join([
            "_RowType_", "atchFileId:STRING(256)",
            "nttId:STRING(256)", "bbsId:STRING(256)",
        ]) + RS
        file_ssv += US.join([
            "N", latest["atch_id"], latest["ntt_id"], BBS_ID,
        ]) + RS + RS
        file_ssv += "Dataset:gdsCurrentMenu" + RS
        file_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        file_result = await fetch_ssv(
            ib_page, "/qya/bbs/selectComBbsFileList.ndo", file_ssv,
        )

        files = []
        for frow in file_result.split(RS):
            if "BBS_" in frow:
                ffields = frow.split(US)
                file_info = {}
                for f in ffields:
                    if f.startswith("/share/"):
                        file_info["path"] = f
                    elif f.startswith("BBS_"):
                        file_info["file_id"] = f
                    elif f.endswith(".xlsx") or f.endswith(".xls"):
                        file_info["name"] = f
                    elif f.isdigit() and int(f) > 10000:
                        file_info["size"] = int(f)
                if file_info.get("name"):
                    files.append(file_info)

        log.info("")
        log.info("=" * 60)
        log.info("  적용약가파일 정보")
        log.info("=" * 60)
        log.info("  제목: %s", latest["title"])
        log.info("  게시일: %s", latest["date"])

        for i, f in enumerate(files):
            size_mb = f.get("size", 0) / 1024 / 1024
            log.info("  파일 %d: %s (%.1fMB)", i + 1, f.get("name", "?"), size_mb)

        # 기존 다운로드 파일과 비교
        dl_dir = Path(__file__).resolve().parent.parent / "data" / "hira"
        existing = sorted(dl_dir.glob("drug_prices_*.json"), reverse=True)
        if existing:
            log.info("")
            log.info("  현재 최신 JSON: %s", existing[0].name)

            import re
            date_match = re.search(r"(\d{8})", existing[0].name)
            if date_match:
                existing_date = date_match.group(1)
                new_date = latest["date"]
                if new_date > existing_date:
                    log.info("  *** 새 약가파일 있음! (%s → %s) ***", existing_date, new_date)
                else:
                    log.info("  최신 상태 (갱신 불필요)")

        log.info("")
        log.info("  수동 다운로드 방법:")
        log.info("  1) biz.hira.or.kr 접속")
        log.info("  2) 심사기준 종합서비스 → 기타 → 청구관련기준(마스터파일)")
        log.info("  3) '%s' 게시글 클릭 → 첨부파일 다운로드", latest["title"])
        log.info("  4) data/hira/downloads/ 에 저장")
        log.info("  5) python -m regscan.workers.drug_price_collector --convert-only <파일경로>")
        log.info("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
