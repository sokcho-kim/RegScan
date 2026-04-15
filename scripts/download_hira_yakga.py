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

        # [5] UI 자동 다운로드 시도
        log.info("[5] UI 네비게이션으로 다운로드 시도...")

        # 공지사항(마지막 보이는 항목) 클릭 후 ArrowDown으로 청구관련기준까지 스크롤
        await ib_page.evaluate("""() => {
            var els = document.querySelectorAll('[id*=controltreeTextBoxElement]');
            var last = els[els.length - 1];
            if (last) {
                var r = last.getBoundingClientRect();
                ['mousedown','mouseup','click'].forEach(function(evt) {
                    last.dispatchEvent(new MouseEvent(evt, {
                        bubbles:true, cancelable:true,
                        clientX:r.x+r.width/2, clientY:r.y+r.height/2, button:0
                    }));
                });
            }
        }""")
        await asyncio.sleep(1)

        # ArrowDown으로 청구관련기준까지
        for _ in range(5):
            await ib_page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)

        await asyncio.sleep(1)

        # 청구관련기준(마스터파일) 찾아서 클릭
        found = await ib_page.evaluate("""() => {
            var els = document.querySelectorAll('[id*=controltreeTextBoxElement]');
            for (var i = 0; i < els.length; i++) {
                if (els[i].textContent.includes('청구관련기준')) {
                    var r = els[i].getBoundingClientRect();
                    ['mousedown','mouseup','click'].forEach(function(evt) {
                        els[i].dispatchEvent(new MouseEvent(evt, {
                            bubbles:true, cancelable:true,
                            clientX:r.x+r.width/2, clientY:r.y+r.height/2, button:0
                        }));
                    });
                    return true;
                }
            }
            return false;
        }""")

        if found:
            log.info("  청구관련기준 클릭 완료!")
            await asyncio.sleep(5)

            # 우측에 게시글 목록 로드됨 — 적용약가 텍스트 찾기
            yakga_el = await ib_page.evaluate("""() => {
                var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while(w.nextNode()) {
                    if (w.currentNode.textContent.includes('적용약가')) {
                        var el = w.currentNode.parentElement;
                        var r = el.getBoundingClientRect();
                        if (r.x > 150 && r.width > 0) {
                            return {text: el.textContent.trim().substring(0,50), cx: r.x+r.width/2, cy: r.y+r.height/2};
                        }
                    }
                }
                return null;
            }""")

            if yakga_el:
                log.info("  적용약가 발견: %s", yakga_el["text"])

                # CDP 다운로드 설정
                from pathlib import Path as P
                dl_dir = P(__file__).resolve().parent.parent / "data" / "hira" / "downloads"
                dl_dir.mkdir(parents=True, exist_ok=True)

                cdp = await context.new_cdp_session(ib_page)
                await cdp.send("Browser.setDownloadBehavior", {
                    "behavior": "allowAndName",
                    "downloadPath": str(dl_dir),
                    "eventsEnabled": True,
                })

                dl_done = asyncio.Event()
                dl_guid = [None]

                def on_dl_progress(params):
                    if params.get("state") == "completed":
                        dl_guid[0] = params.get("guid")
                        dl_done.set()

                cdp.on("Browser.downloadProgress", on_dl_progress)

                # 적용약가 게시글 클릭 (제목 텍스트)
                await ib_page.mouse.click(yakga_el["cx"], yakga_el["cy"])
                await asyncio.sleep(5)

                # 첨부파일 다운로드 — 새 팝업 또는 페이지에서 Dext5 컴포넌트
                # 다운로드가 시작되면 CDP가 캡처
                try:
                    await asyncio.wait_for(dl_done.wait(), timeout=30)
                    log.info("  다운로드 완료: %s", dl_guid[0])

                    # 다운로드된 파일 찾기
                    for f in dl_dir.iterdir():
                        if f.stat().st_size > 100000:
                            log.info("  파일: %s (%dKB)", f.name, f.stat().st_size // 1024)
                except asyncio.TimeoutError:
                    log.info("  CDP 다운로드 타임아웃 — 첨부파일 아이콘 클릭 필요할 수 있음")

                    # 첨부파일 아이콘 찾기 (파일 이미지)
                    file_icon = await ib_page.evaluate("""() => {
                        var imgs = document.querySelectorAll('img[src*=ico_File], img[src*=file], [id*=imgNm]');
                        for (var img of imgs) {
                            var r = img.getBoundingClientRect();
                            if (r.width > 0 && r.x > 150) {
                                return {cx: r.x+r.width/2, cy: r.y+r.height/2, src: img.src};
                            }
                        }
                        return null;
                    }""")

                    if file_icon:
                        log.info("  첨부파일 아이콘 발견 — 클릭")

                        # ComFileDownPop 팝업 대기
                        popup_pages_before = len(context.pages)
                        await ib_page.mouse.click(file_icon["cx"], file_icon["cy"])
                        await asyncio.sleep(5)

                        # 새 팝업 확인
                        popup = None
                        for p in context.pages:
                            if not p.is_closed() and p != ib_page and p != main_page:
                                if "FileDown" in p.url or "popup" in p.url:
                                    popup = p
                                    break

                        # Nexacro 내부 팝업(ComFileDownPop)이 레이어로 열림
                        # Dext5 파일 리스트 → 체크박스 선택 → 다운로드 버튼
                        await asyncio.sleep(8)

                        # 1) 팝업 내 모든 요소 확인
                        popup_els = await ib_page.evaluate("""() => {
                            var results = [];
                            // Dext5 popup 영역 — FileDownPop ID 패턴
                            var els = document.querySelectorAll(
                                '[id*=FileDown] input[type=checkbox], ' +
                                '[id*=dext5] input[type=checkbox], ' +
                                'input[type=checkbox], ' +
                                '[id*=FileDown] button, ' +
                                '[id*=FileDown] [id*=btn], ' +
                                '[class*=check], [class*=download]'
                            );
                            for (var el of els) {
                                var r = el.getBoundingClientRect();
                                if (r.width > 0) {
                                    results.push({
                                        tag: el.tagName, type: el.type || '',
                                        id: el.id, cls: (el.className || '').substring(0,30),
                                        text: (el.textContent || el.value || '').trim().substring(0,30),
                                        cx: r.x+r.width/2, cy: r.y+r.height/2
                                    });
                                }
                            }
                            return results;
                        }""")
                        # Nexacro Dext5 파일 리스트 — 체크박스 + 다운로드 버튼
                        # 스크린샷에서 확인: 파일 행 체크박스, "다운로드" 버튼이 Nexacro DIV로 렌더링됨

                        # 1) 파일 행의 체크박스 찾기 — Dext5 체크박스 이미지
                        checkbox = await ib_page.evaluate("""() => {
                            // Dext5 체크박스 — 보통 img 또는 div로 렌더링
                            // 파일명 텍스트 근처의 체크박스 찾기
                            var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                            while(w.nextNode()) {
                                var text = w.currentNode.textContent.trim();
                                if (text.includes('적용약가') && text.includes('.xlsx')) {
                                    var el = w.currentNode.parentElement;
                                    var r = el.getBoundingClientRect();
                                    // 체크박스는 파일명 왼쪽 — x 좌표가 더 작은 클릭 가능 요소
                                    return {file_cx: r.x, file_cy: r.y + r.height/2,
                                            check_cx: r.x - 30, check_cy: r.y + r.height/2};
                                }
                            }
                            return null;
                        }""")

                        # 체크박스와 다운로드 버튼은 Nexacro DIV — dispatchEvent 필요
                        # 1) 체크박스: 파일명 행 왼쪽의 체크 이미지
                        chk_result = await ib_page.evaluate("""() => {
                            // Dext5 체크박스 — ID에 checkbox 또는 chk 패턴
                            var els = document.querySelectorAll('[id*=chk], [id*=check], [id*=Check]');
                            var results = [];
                            for (var el of els) {
                                var r = el.getBoundingClientRect();
                                if (r.width > 0 && r.y > 550) {
                                    results.push({id: el.id, cx: r.x+r.width/2, cy: r.y+r.height/2, w: r.width});
                                }
                            }
                            // 못 찾으면 파일 행 근처 img 태그
                            if (results.length === 0) {
                                var imgs = document.querySelectorAll('img');
                                for (var img of imgs) {
                                    var r = img.getBoundingClientRect();
                                    if (r.y > 580 && r.y < 660 && r.x < 280 && r.width < 30 && r.width > 5) {
                                        results.push({id: img.id || img.parentElement.id, cx: r.x+r.width/2, cy: r.y+r.height/2, w: r.width, src: (img.src||'').slice(-30)});
                                    }
                                }
                            }
                            return results;
                        }""")
                        log.info("  체크박스 후보: %s", chk_result)

                        if chk_result:
                            # 데이터 행 체크박스 선택 (head가 아닌 body row 0)
                            body_chk = [c for c in chk_result if "body_gridrow_0" in c.get("id", "")]
                            target_chk = body_chk[0] if body_chk else chk_result[-1]
                            log.info("  체크박스 dispatchEvent (%d, %d) id=%s", target_chk["cx"], target_chk["cy"], target_chk.get("id","")[-40:])
                            await ib_page.evaluate("""(pos) => {
                                var el = document.elementFromPoint(pos.cx, pos.cy);
                                if (el) {
                                    ['mousedown','mouseup','click'].forEach(function(evt) {
                                        el.dispatchEvent(new MouseEvent(evt, {
                                            bubbles:true, cancelable:true,
                                            clientX:pos.cx, clientY:pos.cy, button:0
                                        }));
                                    });
                                }
                            }""", target_chk)
                            await asyncio.sleep(2)

                        # 2) 다운로드 버튼 — dispatchEvent
                        dl_result = await ib_page.evaluate("""() => {
                            var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                            while(w.nextNode()) {
                                if (w.currentNode.textContent.trim() === '다운로드') {
                                    var el = w.currentNode.parentElement;
                                    var r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.x > 500) {
                                        return {cx: r.x+r.width/2, cy: r.y+r.height/2, id: el.id};
                                    }
                                }
                            }
                            return null;
                        }""")

                        if dl_result:
                            log.info("  다운로드 버튼 dispatchEvent (%d, %d)", dl_result["cx"], dl_result["cy"])
                            await ib_page.evaluate("""(pos) => {
                                var el = document.elementFromPoint(pos.cx, pos.cy);
                                if (el) {
                                    ['mousedown','mouseup','click'].forEach(function(evt) {
                                        el.dispatchEvent(new MouseEvent(evt, {
                                            bubbles:true, cancelable:true,
                                            clientX:pos.cx, clientY:pos.cy, button:0
                                        }));
                                    });
                                }
                            }""", dl_result)
                            await asyncio.sleep(5)

                        try:
                            await asyncio.wait_for(dl_done.wait(), timeout=60)
                            log.info("  다운로드 완료!")
                            for f in dl_dir.iterdir():
                                if f.stat().st_size > 100000:
                                    log.info("  파일: %s (%dKB)", f.name, f.stat().st_size // 1024)
                        except asyncio.TimeoutError:
                            log.info("  다운로드 타임아웃 — 스크린샷 저장")
                            await ib_page.screenshot(path=str(dl_dir / "debug_final.png"))
            else:
                log.info("  적용약가 게시글 UI에서 못 찾음")
        else:
            log.info("  청구관련기준 못 찾음")

        log.info("")
        log.info("  수동 다운로드 필요 시:")
        log.info("  biz.hira.or.kr → 심사기준 종합서비스 → 기타 → 청구관련기준(마스터파일)")
        log.info("  → '%s' → 다운로드 → data/hira/downloads/", latest["title"])
        log.info("=" * 60)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
