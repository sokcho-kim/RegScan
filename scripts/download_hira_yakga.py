"""HIRA biz.hira.or.kr에서 적용약가파일 자동 다운로드

Nexacro SSV API 직접 호출 방식.
1. 메인 → 심사기준 종합서비스(InfoBank) 팝업 열기
2. selectComBbsList.ndo → 적용약가 게시글 찾기
3. selectComBbsFileList.ndo → 첨부파일 목록 조회
4. 파일 다운로드

Usage: python scripts/download_hira_yakga.py
"""

import asyncio
import base64
import re
import sys
import io
import urllib.parse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RS = "\x1e"  # Record Separator
US = "\x1f"  # Unit Separator
ETX = "\x03"  # Empty value

SAVE_DIR = Path(__file__).parent.parent / "data" / "hira" / "downloads"


def build_ssv_header(cookies: dict) -> str:
    ssv = "SSV:utf-8" + RS
    ssv += f'JSESSIONID={cookies.get("JSESSIONID", "null")}' + RS
    ssv += f'BIZINTERSESSION={cookies.get("BIZINTERSESSION", "")}' + RS
    ssv += f'WMONID={cookies.get("WMONID", "")}' + RS
    ssv += "browserType=Chrome" + RS
    ssv += "osVersion=Windows 10" + RS
    ssv += "navigatorName=Chrome" + RS
    ssv += "navigatorVersion=147" + RS
    return ssv


async def fetch_ssv(page, url: str, body: str) -> str:
    return await page.evaluate(
        """async ([url, body]) => {
            const r = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'text/xml', 'Accept': 'application/xml, text/xml, */*', 'X-Requested-With': 'XMLHttpRequest'},
                body: body
            });
            return await r.text();
        }""",
        [url, body],
    )


async def fetch_binary(page, url: str) -> tuple[bytes, dict]:
    info = await page.evaluate(
        """async (url) => {
            const r = await fetch(url);
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let b = '';
            for (let i = 0; i < bytes.byteLength; i++) b += String.fromCharCode(bytes[i]);
            return {
                b64: btoa(b),
                status: r.status,
                ct: r.headers.get('content-type') || '',
                cd: r.headers.get('content-disposition') || '',
                size: bytes.byteLength
            };
        }""",
        url,
    )
    raw = base64.b64decode(info["b64"])
    return raw, info


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        ad_pages = []
        context.on("page", lambda p: ad_pages.append(p))

        page = await context.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        print("[1] biz.hira.or.kr 접속...")
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
            print("ERROR: 메인 페이지 없음")
            await browser.close()
            return

        # [2] 심사기준 종합서비스 클릭 → InfoBank
        print("[2] 심사기준 종합서비스 클릭...")
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
        print(f"  InfoBank: {ib_page.url[-50:]}")

        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        header = build_ssv_header(cookies)

        # [3] BBS 목록 → 적용약가 찾기
        print("[3] 적용약가파일 게시글 검색...")
        bbs_ssv = header
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
        bbs_ssv += "Dataset:dsParam" + RS
        bbs_ssv += US.join(cols) + RS
        vals = ["N", ETX, ETX, ETX, "1", "20", "0", ETX,
                "BBSMSTR_000000000676", "all", ETX, ETX, ETX, ETX, ETX, ETX]
        bbs_ssv += US.join(vals) + RS + RS
        bbs_ssv += "Dataset:gdsCurrentMenu" + RS
        bbs_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        bbs_result = await fetch_ssv(ib_page, "/qya/bbs/selectComBbsList.ndo", bbs_ssv)

        # 적용약가 행 추출
        rows = bbs_result.split(RS)
        yakga_ntt_id = None
        yakga_atch_id = None
        yakga_title = None

        for row in rows:
            if "적용약가" in row:
                fields = row.split(US)
                if len(fields) > 25:
                    yakga_ntt_id = fields[5]
                    yakga_atch_id = fields[25]
                    yakga_title = fields[11]
                    break

        if not yakga_atch_id:
            print("ERROR: 적용약가 게시글 못 찾음")
            await browser.close()
            return

        print(f"  제목: {yakga_title}")
        print(f"  nttId: {yakga_ntt_id}, atchFileId: {yakga_atch_id}")

        # [4] 첨부파일 목록 조회
        print("[4] 첨부파일 목록 조회...")
        file_ssv = header
        file_ssv += "Dataset:dsParam" + RS
        file_ssv += US.join([
            "_RowType_", "atchFileId:STRING(256)",
            "nttId:STRING(256)", "bbsId:STRING(256)",
        ]) + RS
        file_ssv += US.join([
            "N", yakga_atch_id, yakga_ntt_id, "BBSMSTR_000000000676",
        ]) + RS + RS
        file_ssv += "Dataset:gdsCurrentMenu" + RS
        file_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        file_result = await fetch_ssv(
            ib_page, "/qya/bbs/selectComBbsFileList.ndo", file_ssv,
        )

        # 파일 정보 파싱
        file_rows = file_result.split(RS)
        files_found = []
        for row in file_rows:
            if "/share/" in row and (".xlsx" in row.lower() or ".xls" in row.lower()):
                fields = row.split(US)
                files_found.append(fields)
                print(f"  파일: {[f[:60] for f in fields if f and f != ETX]}")

        if not files_found:
            print("ERROR: 첨부파일 없음")
            print(f"  응답: {file_result[:500]}")
            await browser.close()
            return

        # [5] 게시글 상세 조회 (세션 등록)
        print("[5] 게시글 상세 조회...")
        detail_ssv = header
        detail_ssv += "Dataset:dsParam" + RS
        detail_ssv += US.join([
            "_RowType_", "atchFileId:STRING(256)", "nttId:STRING(256)",
            "bbsId:STRING(256)", "totCnt:STRING(256)", "currentPage:STRING(256)",
            "recordCountPerPage:STRING(256)", "firstIndex:STRING(256)",
            "lastIndex:STRING(256)", "codeId:STRING(256)",
            "commentNo:STRING(256)", "commentCn:STRING(256)",
        ]) + RS
        detail_ssv += US.join([
            "N", yakga_atch_id, yakga_ntt_id, "BBSMSTR_000000000676",
            ETX, ETX, ETX, ETX, ETX, ETX, ETX, ETX,
        ]) + RS + RS
        detail_ssv += "Dataset:gdsCurrentMenu" + RS
        detail_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        await fetch_ssv(ib_page, "/qya/bbs/selectComBbsDetail.ndo", detail_ssv)
        print("  상세 조회 완료")

        # [6] Dext5 초기화 → gfs → 다운로드
        print("[6] Dext5 파일 다운로드...")
        SAVE_DIR.mkdir(parents=True, exist_ok=True)

        for file_fields in files_found:
            # apndFileStgPth + apndFileId 추출
            path_val = None
            file_id = None
            name_val = None
            for f in file_fields:
                if "/share/" in f:
                    path_val = f
                elif f.startswith("BBS_"):
                    file_id = f
                elif re.search(r"\.(xlsx?|csv)$", f, re.IGNORECASE):
                    name_val = f

            if not file_id:
                continue
            if not name_val:
                name_val = f"drug_prices_{file_id}.xlsx"

            full_path = (path_val or "") + file_id
            print(f"  파일: {name_val} ({file_id})")

            # Dext5 gfs (get file status) — 비암호화 모드
            gfs_body = f"dext5CMD=gfs&cd=1&urlAddress={urllib.parse.quote(full_path)}"
            gfs_result = await ib_page.evaluate(
                """async (body) => {
                    const r = await fetch('/com/dext5handler.ndo', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
                        body: body
                    });
                    return await r.text();
                }""",
                gfs_body,
            )
            print(f"  gfs: {gfs_result[:100]}")

            # 직접 파일 경로로 다운로드 시도 (NAS 파일)
            # Dext5 다운로드 = POST dext5handler.ndo with d00
            def make_encrypt(s: str) -> str:
                b1 = base64.b64encode(s.encode()).decode()
                return base64.b64encode(("R" + b1).encode()).decode()

            # d0 + fileSn + dsd + datasetIdx + fileId
            for pattern in [
                f"d01dsd0{file_id}",
                f"d0dsd0{file_id}",
                full_path,
                file_id,
            ]:
                d00 = make_encrypt(pattern)
                dl_body = f"d00={urllib.parse.quote(d00)}"

                info = await ib_page.evaluate(
                    """async (body) => {
                        const r = await fetch('/com/dext5handler.ndo', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
                            body: body
                        });
                        const ct = r.headers.get('content-type') || '';
                        const cd = r.headers.get('content-disposition') || '';
                        const buf = await r.arrayBuffer();
                        return {status: r.status, ct: ct, cd: cd, size: buf.byteLength};
                    }""",
                    dl_body,
                )

                if info["size"] > 100000:
                    raw, dl_info = await fetch_binary(
                        ib_page,
                        f"/com/dext5handler.ndo",
                    )
                    # POST로 다시 보내야 함 — evaluate로 처리
                    raw_b64 = await ib_page.evaluate(
                        """async (body) => {
                            const r = await fetch('/com/dext5handler.ndo', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
                                body: body
                            });
                            const buf = await r.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            let b = '';
                            for (let i = 0; i < bytes.byteLength; i++) b += String.fromCharCode(bytes[i]);
                            return btoa(b);
                        }""",
                        dl_body,
                    )
                    raw = base64.b64decode(raw_b64)
                    save_path = SAVE_DIR / name_val
                    with open(save_path, "wb") as f:
                        f.write(raw)
                    print(f"  다운로드 성공: {save_path} ({len(raw)/1024:.0f}KB)")
                    break
                else:
                    print(f"  d00 pattern '{pattern[:30]}...' → size={info['size']}")

        await browser.close()
        print("\n완료.")


if __name__ == "__main__":
    asyncio.run(main())
