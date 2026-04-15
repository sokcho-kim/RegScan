"""HIRA 적용약가파일 자동 수집 워커

biz.hira.or.kr에서 적용약가 Excel 파일을 자동 다운로드하고
JSON으로 변환하여 IngredientBridge가 사용하는 data/hira/ 경로에 저장한다.

데이터 소스: https://biz.hira.or.kr (청구관련기준 마스터 파일)
갱신 주기: 월간 비정기 (보통 15~20일경 공시)
자동화 전략: daily check → 신규 파일 감지 시 다운로드 + 변환

사용법:
    # 최신 약가파일 다운로드 + 변환
    python -m regscan.workers.drug_price_collector

    # 다운로드만 (변환 안 함)
    python -m regscan.workers.drug_price_collector --download-only

    # 기존 Excel 파일을 JSON으로 변환만
    python -m regscan.workers.drug_price_collector --convert-only data/hira/약가파일.xlsx
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 경로 설정
# ═══════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "hira"
DOWNLOAD_DIR = DATA_DIR / "downloads"

# HIRA 약제기준정��� 페이지 (biz.hira.or.kr은 Nexacro14 RIA라 크롤링 불가)
# 대안 1: HIRA 본사이트 약제기준 게시판 (파일 첨부 공지)
HIRA_NOTICE_URL = "https://www.hira.or.kr/bbsDummy.do?pgmid=HIRAA030056000000"
# 대안 2: biz.hira.or.kr — Nexacro14 RIA 기반, Playwright 일반 셀렉터 불가
HIRA_BIZ_URL = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"

# Excel → JSON 컬럼 매핑 (원본 한글 컬럼 → 내부 영문 키)
COLUMN_MAP = {
    "제품코드": "제품코드",
    "적용시작일자": "적용시작일자",
    "급여기준": "급여기준",
    "상한가": "price_ceiling",
    "가산금": "가산금",
    "투여경로": "투여경로",
    "제품명": "제품명",
    "규격": "spec",
    "단위": "unit",
    "업체명": "company",
    "분류번호": "class_no",
    "주성분코드": "ingredient_code",
    "전문/일반": "rx_otc",
    "퇴장방지": "퇴장방지",
    "의약품동등성": "의약품동등성",
    "저가대체가산여부": "저가대체가산여부",
    "예외의약품구분": "예외의약품구분",
    "임의조제불가항목": "임의조제불가항목",
    "고시일자": "notice_date",
    "대응코드": "대응코드",
    "희귀의약품구분": "희귀의약품구분",
    "판매예정일": "판매예정일",
    "동일 의약품": "동일 의약품",
    "청구규격": "claim_spec",
    "본인부담률D(30%)여부": "본인부담률D(30%)여부",
    "본인부담률A(50%)여부": "본인부담률A(50%)여부",
    "본인부담률B(80%)여부": "본인부담률B(80%)여부",
    "선별급여여부": "선별급여여부",
    "변경이전약품코드": "변경이전약품코드",
    "변경이후약품코드": "변경이후약품코드",
}


# ═══════════════════════════════════════════════════════
# 1. Playwright 다운로더
# ═══════════════════════════════════════════════════════

RS = "\x1e"  # Nexacro SSV Record Separator
US = "\x1f"  # Nexacro SSV Unit Separator
ETX = "\x03"  # Nexacro SSV Empty value
BBS_ID = "BBSMSTR_000000000676"  # 청구관련기준(마스터파일) 게시판


async def download_latest_drug_price(
    *,
    headless: bool = True,
    timeout: int = 60000,
) -> Path | None:
    """HIRA biz.hira.or.kr에서 최신 적용약가 Excel을 자동 다운로드한다.

    전략:
    1) data/hira/downloads/에 미변환 Excel이 있으면 사용 (수동 지원)
    2) biz.hira.or.kr Nexacro SSV API + UI 자동화로 다운로드

    파이프라인:
      메인 접속 → 광고 닫기 → 심사기준 종합서비스(InfoBank) 팝업
      → SSV API로 적용약가 게시글 탐지
      → 키보드 ArrowDown으로 청구관련기준 메뉴 접근
      → 적용약가 클릭 → 체크박스 dispatchEvent → 다운로드 dispatchEvent
      → page.route로 dext5handler.ndo XHR 응답 인터셉트 → xlsx 저장

    Returns
    -------
    다운로드된 Excel 파일 경로, 실패 시 None
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 전략 1: 수동 다운로드 파일
    manual = _find_new_manual_download()
    if manual:
        logger.info("[DrugPrice] 수동 다운로드 파일 감지: %s", manual.name)
        return manual

    # 전략 2: biz.hira.or.kr 자동 다운로드
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("[DrugPrice] playwright 미설치")
        return None

    logger.info("[DrugPrice] biz.hira.or.kr 접속 (headless=%s)", headless)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        ad_pages: list = []
        context.on("page", lambda p: ad_pages.append(p))

        page = await context.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

        try:
            await page.goto("https://biz.hira.or.kr", wait_until="load", timeout=timeout)
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
            logger.error("[DrugPrice] 메인 페이지 없음")
            await browser.close()
            return None

        # InfoBank 열기
        rect = await main_page.evaluate("""() => {
            var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while(w.nextNode()) {
                if (w.currentNode.textContent.includes('심사기준 종합')) {
                    var r = w.currentNode.parentElement.getBoundingClientRect();
                    return {x: r.x+r.width/2, y: r.y+r.height/2};
                }
            }
        }""")
        if not rect:
            logger.error("[DrugPrice] 심사기준 종합서비스 링크 없음")
            await browser.close()
            return None

        try:
            async with context.expect_page(timeout=15000) as ib_info:
                await main_page.mouse.click(rect["x"], rect["y"])
            ib_page = await ib_info.value
        except Exception as e:
            logger.error("[DrugPrice] InfoBank 팝업 실패: %s", e)
            await browser.close()
            return None

        ib_page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        await asyncio.sleep(10)
        logger.info("[DrugPrice] InfoBank 열림")

        cookies = {c["name"]: c["value"] for c in await context.cookies()}

        # SSV API로 적용약가 메타 조회
        yakga_info = await _find_yakga_via_ssv(ib_page, cookies)
        if not yakga_info:
            logger.warning("[DrugPrice] 적용약가 게시글 못 찾음")
            await browser.close()
            return None

        logger.info("[DrugPrice] 적용약가: %s", yakga_info["title"])

        # UI 네비게이션: 청구관련기준 → 적용약가 → 체크박스 → 다운로드
        xlsx_data = await _download_via_ui(ib_page, yakga_info)

        await browser.close()

        if xlsx_data and len(xlsx_data) > 10000:
            fname = yakga_info.get("file_name", "drug_prices.xlsx")
            save_path = DOWNLOAD_DIR / fname
            with open(save_path, "wb") as f:
                f.write(xlsx_data)
            logger.info("[DrugPrice] 저장: %s (%dKB)", save_path.name, len(xlsx_data) // 1024)
            return save_path

        logger.warning("[DrugPrice] 자동 다운로드 실패 — 수동 다운로드 필요")
        return None


def _build_ssv_header(cookies: dict) -> str:
    ssv = "SSV:utf-8" + RS
    ssv += f'JSESSIONID={cookies.get("JSESSIONID", "null")}' + RS
    ssv += f'BIZINTERSESSION={cookies.get("BIZINTERSESSION", "")}' + RS
    ssv += f'WMONID={cookies.get("WMONID", "")}' + RS
    ssv += "browserType=Chrome" + RS + "osVersion=Windows 10" + RS
    ssv += "navigatorName=Chrome" + RS + "navigatorVersion=147" + RS
    return ssv


async def _fetch_ssv(page, url: str, body: str) -> str:
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


async def _find_yakga_via_ssv(ib_page, cookies: dict) -> dict | None:
    """SSV API로 적용약가 게시글 + 파일 메타 조회."""
    header = _build_ssv_header(cookies)

    # 게시글 목록
    bbs_ssv = header + "Dataset:dsParam" + RS
    cols = ["_RowType_", "brdTyBltNo:STRING(256)", "bltNo:STRING(256)",
            "totCnt:STRING(256)", "currentPage:STRING(256)",
            "recordCountPerPage:STRING(256)", "firstIndex:STRING(256)",
            "lastIndex:STRING(256)", "bbsId:STRING(256)",
            "cbSearchCnd:STRING(256)", "edSearchWrd:STRING(256)",
            "nttId:STRING(256)", "atchFileId:STRING(256)",
            "codeId:STRING(256)", "catType01Val:STRING(256)",
            "catType02Val:STRING(256)", "catType03Val:STRING(256)"]
    bbs_ssv += US.join(cols) + RS
    vals = ["N", ETX, ETX, ETX, "1", "20", "0", ETX,
            BBS_ID, "all", ETX, ETX, ETX, ETX, ETX, ETX]
    bbs_ssv += US.join(vals) + RS + RS
    bbs_ssv += "Dataset:gdsCurrentMenu" + RS
    bbs_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

    result = await _fetch_ssv(ib_page, "/qya/bbs/selectComBbsList.ndo", bbs_ssv)

    for row in result.split(RS):
        if "적용약가" not in row:
            continue
        fields = row.split(US)
        if len(fields) <= 25:
            continue

        ntt_id = fields[5]
        atch_id = fields[25]
        title = fields[11]

        # 파일 목록
        file_ssv = header + "Dataset:dsParam" + RS
        file_ssv += US.join(["_RowType_", "atchFileId:STRING(256)",
                             "nttId:STRING(256)", "bbsId:STRING(256)"]) + RS
        file_ssv += US.join(["N", atch_id, ntt_id, BBS_ID]) + RS + RS
        file_ssv += "Dataset:gdsCurrentMenu" + RS
        file_ssv += US.join(["_RowType_", "menuId:STRING(256)"]) + RS

        file_result = await _fetch_ssv(ib_page, "/qya/bbs/selectComBbsFileList.ndo", file_ssv)

        file_name = "drug_prices.xlsx"
        for frow in file_result.split(RS):
            if ".xlsx" in frow.lower():
                for f in frow.split(US):
                    if f.endswith(".xlsx") or f.endswith(".xls"):
                        file_name = f
                        break

        return {"ntt_id": ntt_id, "atch_id": atch_id, "title": title, "file_name": file_name}

    return None


async def _download_via_ui(ib_page, yakga_info: dict) -> bytes | None:
    """InfoBank UI에서 적용약가 다운로드 — XHR 인터셉트."""

    # 1) 공지사항(마지막 보이는 행) 클릭 후 ArrowDown으로 청구관련기준까지 스크롤
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

    for _ in range(5):
        await ib_page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
    await asyncio.sleep(1)

    # 2) 청구관련기준 클릭
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

    if not found:
        logger.warning("[DrugPrice] 청구관련기준 메뉴 못 찾음")
        return None

    await asyncio.sleep(5)

    # 3) 적용약가 게시글 클릭
    yakga_el = await ib_page.evaluate("""() => {
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while(w.nextNode()) {
            if (w.currentNode.textContent.includes('적용약가')) {
                var el = w.currentNode.parentElement;
                var r = el.getBoundingClientRect();
                if (r.x > 150 && r.width > 0)
                    return {cx: r.x+r.width/2, cy: r.y+r.height/2};
            }
        }
        return null;
    }""")

    if not yakga_el:
        logger.warning("[DrugPrice] 적용약가 게시글 UI에서 못 찾음")
        return None

    await ib_page.mouse.click(yakga_el["cx"], yakga_el["cy"])
    await asyncio.sleep(5)

    # 4) 첨부파일 아이콘 클릭
    file_icon = await ib_page.evaluate("""() => {
        var imgs = document.querySelectorAll('img[src*=ico_File], img[src*=file], [id*=imgNm]');
        for (var img of imgs) {
            var r = img.getBoundingClientRect();
            if (r.width > 0 && r.x > 150)
                return {cx: r.x+r.width/2, cy: r.y+r.height/2};
        }
        return null;
    }""")

    if not file_icon:
        logger.warning("[DrugPrice] 첨부파일 아이콘 없음")
        return None

    await ib_page.mouse.click(file_icon["cx"], file_icon["cy"])
    await asyncio.sleep(8)

    # 5) 체크박스(body row 0) dispatchEvent
    chk_result = await ib_page.evaluate("""() => {
        var els = document.querySelectorAll('[id*=chk], [id*=check], [id*=Check]');
        for (var el of els) {
            if (el.id.includes('body_gridrow_0') && el.id.includes('controlcheckbox')) {
                var r = el.getBoundingClientRect();
                if (r.width > 0) return {cx: r.x+r.width/2, cy: r.y+r.height/2};
            }
        }
        return null;
    }""")

    if chk_result:
        await ib_page.evaluate("""(pos) => {
            var el = document.elementFromPoint(pos.cx, pos.cy);
            if (el) ['mousedown','mouseup','click'].forEach(function(evt) {
                el.dispatchEvent(new MouseEvent(evt, {
                    bubbles:true, cancelable:true,
                    clientX:pos.cx, clientY:pos.cy, button:0
                }));
            });
        }""", chk_result)
        await asyncio.sleep(2)

    # 6) dext5handler.ndo XHR 인터셉트 설정
    captured_data: list[bytes] = []

    async def intercept_dext5(route):
        resp = await route.fetch()
        body = await resp.body()
        if len(body) > 10000:
            captured_data.append(body)
            logger.info("[DrugPrice] dext5handler 응답 캡처: %dKB", len(body) // 1024)
        await route.fulfill(response=resp)

    await ib_page.route("**/dext5handler.ndo", intercept_dext5)

    # 7) 다운로드 버튼 dispatchEvent
    dl_btn = await ib_page.evaluate("""() => {
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while(w.nextNode()) {
            if (w.currentNode.textContent.trim() === '다운로드') {
                var el = w.currentNode.parentElement;
                var r = el.getBoundingClientRect();
                if (r.width > 0 && r.x > 500)
                    return {cx: r.x+r.width/2, cy: r.y+r.height/2};
            }
        }
        return null;
    }""")

    if dl_btn:
        await ib_page.evaluate("""(pos) => {
            var el = document.elementFromPoint(pos.cx, pos.cy);
            if (el) ['mousedown','mouseup','click'].forEach(function(evt) {
                el.dispatchEvent(new MouseEvent(evt, {
                    bubbles:true, cancelable:true,
                    clientX:pos.cx, clientY:pos.cy, button:0
                }));
            });
        }""", dl_btn)

    # 8) XHR 응답 대기
    for _ in range(60):
        if captured_data:
            break
        await asyncio.sleep(1)

    await ib_page.unroute("**/dext5handler.ndo")

    return captured_data[0] if captured_data else None


def _find_new_manual_download() -> Path | None:
    """data/hira/downloads/ 에서 ��직 변환되지 않은 최신 xlsx/xls 파일을 찾는다."""
    if not DOWNLOAD_DIR.exists():
        return None

    excel_files = sorted(
        [f for f in DOWNLOAD_DIR.iterdir() if f.suffix.lower() in (".xlsx", ".xls")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for excel in excel_files:
        date_str = _extract_date_from_filename(excel.name)
        if date_str:
            json_candidate = DATA_DIR / f"drug_prices_{date_str}.json"
            if json_candidate.exists():
                continue
        return excel

    return None


    # (레거시 _find_drug_price_link / _find_attachment_link 삭제됨
    #  → _find_yakga_via_ssv + _download_via_ui로 대체)


def _extract_date_from_filename(filename: str) -> str | None:
    """파일명에서 날짜 추출.

    예: '230401_260401_적용약가파일' → '20260401' (끝 날짜 = 최신)
        '260201 적용약가파일' → '20260201'
    """
    # YYYYMMDD 패턴 (우선)
    matches = re.findall(r"(20\d{6})", filename)
    if matches:
        return matches[-1]  # 마지막(최신) 날짜

    # YYMMDD 패턴 — 여러 개 있으면 마지막(적용 종료일 = 최신)
    matches = re.findall(r"(\d{6})", filename)
    if matches:
        yy = matches[-1][:2]
        century = "20" if int(yy) < 50 else "19"
        return f"{century}{matches[-1]}"

    return None


# ═══════════════════════════════════════════════════════
# 2. Excel → JSON 변환기
# ═══════════════════════════════════════════════════════

def convert_excel_to_json(
    excel_path: Path | str,
    output_path: Path | str | None = None,
) -> Path:
    """적용약가 Excel 파일을 JSON으로 변환한다.

    Parameters
    ----------
    excel_path : Excel 파일 경로
    output_path : 출력 JSON 경로. None이면 자동 생성.

    Returns
    -------
    생성된 JSON 파일 경로
    """
    import pandas as pd

    excel_path = Path(excel_path)
    logger.info("[DrugPrice] Excel 변환 시작: %s", excel_path.name)

    # Excel 읽기
    df = pd.read_excel(excel_path, engine="openpyxl")
    logger.info("[DrugPrice] Excel 로드: %d행 x %d열", len(df), len(df.columns))

    # 스키마 검증: 필수 컬럼 존재 확인
    REQUIRED_COLUMNS = {"\uc81c\ud488\ucf54\ub4dc", "\uc801\uc6a9\uc2dc\uc791\uc77c\uc790", "\uc0c1\ud55c\uac00", "\uc8fc\uc131\ubd84\ucf54\ub4dc", "\uc81c\ud488\uba85", "\uae09\uc5ec\uae30\uc900"}
    actual_columns = {str(c).strip() for c in df.columns}
    missing = REQUIRED_COLUMNS - actual_columns
    if missing:
        raise ValueError(
            f"[DrugPrice] Excel 필수 컬럼 누락: {missing}. "
            f"실제 컬럼: {sorted(actual_columns)[:10]}... "
            f"HIRA 약가파일 형식이 변경되었을 수 있습니다."
        )

    # 컬럼 매핑
    rename_map = {}
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in COLUMN_MAP:
            rename_map[col] = COLUMN_MAP[col_str]

    df = df.rename(columns=rename_map)

    # 날짜 컬럼 문자열 변환
    date_cols = ["적용시작일자", "notice_date", "판매예정일"]
    for col in date_cols:
        if col in df.columns:
            df[col] = df[col].apply(_format_date)

    # NaN → None 변환
    df = df.where(df.notna(), None)

    # price_ceiling 숫자 변환
    if "price_ceiling" in df.columns:
        df["price_ceiling"] = pd.to_numeric(df["price_ceiling"], errors="coerce")

    # JSON 변환
    records = df.to_dict(orient="records")

    # 출력 경로 결정
    if output_path is None:
        date_str = _extract_date_from_filename(excel_path.name)
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        output_path = DATA_DIR / f"drug_prices_{date_str}.json"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, default=str)

    file_size = output_path.stat().st_size / (1024 * 1024)
    logger.info(
        "[DrugPrice] JSON 변환 완료: %s (%d건, %.1fMB)",
        output_path.name, len(records), file_size,
    )
    return output_path


def _format_date(val: Any) -> str | None:
    """날짜 값을 YYYY-MM-DD 문자열로 변환."""
    if val is None or (isinstance(val, float) and val != val):  # NaN check
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s if s else None


# ═══════════════════════════════════════════════════════
# 3-A. DataFrame-level 데이터 해시 (빠른 변경 감지 게이트)
# ═══════════════════════════════════════════════════════

# 수치형 컬럼 (반올림 + 정수 정규화 대상)
NUMERIC_COLUMNS = ("price_ceiling", "가산금")

# 코드형 컬럼 (int/str 혼재 위험 → 문자열 강제 + 소수점/0 패딩 제거)
CODE_COLUMNS = ("제품코드", "ingredient_code", "class_no", "대응코드", "변경이전약품코드", "변경이후약품코드")

# 제품명 류 컬럼 (숫자+단위 사이 공백 제거 대상)
# 조사 결과: unit 컬럼은 upper()만으로 162→140 흡수 충분, 제품명만 내부 공백 변형 존재
NAME_COLUMNS = ("제품명",)

# 제품명 내 '숫자 + 공백 + 단위' 패턴 매칭용 (mg/ml/g/mcg/l/iu/kg 등)
_UNIT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s+(mg|ml|mcg|iu|kg|g|l)\b", re.IGNORECASE)


def _normalize_code(val: Any) -> str:
    """코드 컬럼 정규화: int 12345 / float 12345.0 / str '12345 ' → '12345'."""
    if val is None:
        return ""
    if isinstance(val, float):
        if val != val:  # NaN
            return ""
        if val.is_integer():
            return str(int(val))
        return str(val)
    return str(val).strip()


def _normalize_numeric(val: Any) -> str:
    """수치 컬럼 정규화: 반올림 후 정수면 int, 아니면 소수 4자리 고정.

    4자리 확장 이유: 고가 항암제 1mg당 단가 계산 시 2자리는 손실 발생.
    59,004건 조사 결과 현재는 모두 정수지만 미래 대비 여유.
    """
    if val is None:
        return ""
    try:
        import math
        f = float(val)
        if math.isnan(f):
            return ""
        rounded = round(f, 4)
        if rounded == int(rounded):
            return str(int(rounded))
        return f"{rounded:.4f}"
    except (ValueError, TypeError):
        return str(val).strip()


def _normalize_name(val: Any) -> str:
    """제품명 정규화: 숫자+단위 사이 공백 제거.

    '80 mg' → '80mg', '500 MG' → '500MG' (upper는 이후 단계에서 적용).
    조사 결과 HIRA 제품명에 mg/ml/g 앞뒤 공백 변형 실존.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    return _UNIT_PATTERN.sub(r"\1\2", s)


def compute_dataframe_hash(path: Path | str) -> str:
    """Excel 또는 JSON 파일을 DataFrame으로 로드 후 순수 데이터 해시를 계산.

    파일 포맷(메타데이터, 저장 시점, 소프트웨어 버전 등)에 무관하게
    동일한 데이터면 동일한 해시를 반환한다.

    로직:
      1. Excel/JSON → DataFrame 로드
      2. 메타데이터 행(전체 NaN 등) 제거
      3. ingredient_code 기준 정렬 → index 리셋
      4. pd.util.hash_pandas_object() 로 행별 해시 → 합산

    Returns
    -------
    16진수 해시 문자열 (deterministic)
    """
    import pandas as pd

    path = Path(path)

    # 파일 타입에 따라 로드
    if path.suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, engine="openpyxl")
        # 컬럼 매핑 적용 (Excel은 원본 한글 컬럼명)
        rename_map = {}
        for col in df.columns:
            col_str = str(col).strip()
            if col_str in COLUMN_MAP:
                rename_map[col] = COLUMN_MAP[col_str]
        df = df.rename(columns=rename_map)
    elif path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        df = pd.DataFrame(records)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {path.suffix}")

    # 메타데이터 행 제거 (전체 NaN 행)
    df = df.dropna(how="all")

    # None 컬럼 제거 (Excel 31번째 빈 컬럼 등)
    df = df.loc[:, df.columns.notna()]
    df = df.loc[:, df.columns.astype(str).str.strip() != ""]

    # ─── #1 Dtype Consistency: 코드 컬럼 강제 정규화 ───
    # int/float/str 혼재 리스크 제거 (12345 / 12345.0 / "12345 " → "12345")
    for col in CODE_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_normalize_code)

    # ─── #3 Float Precision: 수치형 컬럼 반올림 정수화 (4자리) ───
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_normalize_numeric)

    # ─── #2-α Name Unit Normalization: 제품명 내 '숫자 단위' → '숫자단위' ───
    # (조사 결과: HIRA 제품명에 '80 mg' vs '80mg' 변형 실존, unit 컬럼은 불필요)
    for col in NAME_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_normalize_name)

    # 정렬 키 결정: ingredient_code > 제품코드 (정규화 이후 수행)
    sort_key = "ingredient_code" if "ingredient_code" in df.columns else "제품코드"
    if sort_key in df.columns:
        df = df.sort_values(by=[sort_key, "적용시작일자"] if "적용시작일자" in df.columns else [sort_key])
    df = df.reset_index(drop=True)

    # NaN 정규화
    df = df.fillna("")

    # 모든 값을 문자열로 통일
    df = df.astype(str)

    # ─── #2 String Normalization: 공백 제거 + 대소문자 통일 ───
    # 한글은 upper 무영향, 영문 제품명/단위(MG/Mg/mg) 통일
    for col in df.columns:
        df[col] = df[col].str.strip().str.upper()

    # pandas 행별 해시 → 합산
    row_hashes = pd.util.hash_pandas_object(df, index=False)
    data_hash = hashlib.sha256(str(row_hashes.sum()).encode()).hexdigest()

    logger.info("[DrugPrice] DataFrame 해시: %s (%d행, %s)", data_hash[:16], len(df), path.name)
    return data_hash


def has_data_changed(old_path: Path | str | None, new_path: Path | str) -> bool:
    """두 파일의 순수 데이터가 변경되었는지 DataFrame 해시로 판별.

    빠른 게이트: True면 record diff 진행, False면 스킵.
    old_path가 None이면 항상 True (최초 수집).
    """
    if old_path is None or not Path(old_path).exists():
        return True

    old_hash = compute_dataframe_hash(old_path)
    new_hash = compute_dataframe_hash(new_path)

    changed = old_hash != new_hash
    if changed:
        logger.info("[DrugPrice] 데이터 변경 감지: %s → %s", old_hash[:16], new_hash[:16])
    else:
        logger.info("[DrugPrice] 데이터 동일 — 변경 없음")
    return changed


# ═══════════════════════════════════════════════════════
# 3-B. 레코드 단위 변경 감지 (상세 diff)
# ═══════════════════════════════════════════════════════

# 변경 감지의 기준 키: 제품코드 + 적용시작일자 (복합키로 유일한 레코드 식별)
RECORD_KEY = ("제품코드", "적용시작일자")

# 변경 추적 대상 필드 (이 필드가 바뀌면 "변경"으로 간주)
TRACKED_FIELDS = ("급여기준", "price_ceiling", "ingredient_code")


def get_current_drug_prices_path() -> Path | None:
    """현재 사용 중인 drug_prices JSON 파일 경로를 반환."""
    candidates = sorted(DATA_DIR.glob("drug_prices_*.json"), reverse=True)
    return candidates[0] if candidates else None


def _build_record_index(records: list[dict]) -> dict[tuple, dict]:
    """레코드 리스트를 (제품코드, 적용시작일자) → record dict로 인덱싱."""
    index: dict[tuple, dict] = {}
    for rec in records:
        key = tuple(str(rec.get(k, "")) for k in RECORD_KEY)
        index[key] = rec
    return index


def diff_drug_prices(
    old_path: Path | None,
    new_path: Path,
) -> dict[str, Any]:
    """두 drug_prices JSON을 레코드 단위로 비교하여 변경 내역을 반환.

    Returns
    -------
    {
        "has_changes": bool,
        "summary": { "added": int, "removed": int, "modified": int, "unchanged": int },
        "added": [{ "제품코드": ..., "제품명": ..., ... }],        # 신규 등재 약물
        "removed": [{ "제품코드": ..., "제품명": ..., ... }],      # 삭제된 약물
        "modified": [{                                              # 변경된 약물
            "key": ("제품코드", "적용시작일자"),
            "제품명": ...,
            "changes": { "price_ceiling": {"old": 470, "new": 469}, ... }
        }],
    }
    """
    # 신규 파일 로드
    with open(new_path, "r", encoding="utf-8") as f:
        new_records = json.load(f)
    new_index = _build_record_index(new_records)

    # 기존 파일이 없으면 전부 신규
    if old_path is None or not old_path.exists():
        return {
            "has_changes": True,
            "summary": {"added": len(new_records), "removed": 0, "modified": 0, "unchanged": 0},
            "added": new_records,
            "removed": [],
            "modified": [],
        }

    with open(old_path, "r", encoding="utf-8") as f:
        old_records = json.load(f)
    old_index = _build_record_index(old_records)

    old_keys = set(old_index.keys())
    new_keys = set(new_index.keys())

    # 신규 등재
    added_keys = new_keys - old_keys
    added = [new_index[k] for k in added_keys]

    # 삭제
    removed_keys = old_keys - new_keys
    removed = [old_index[k] for k in removed_keys]

    # 변경 (공통 키에서 추적 필드 비교)
    modified = []
    common_keys = old_keys & new_keys
    for key in common_keys:
        old_rec = old_index[key]
        new_rec = new_index[key]
        changes = {}
        for field in TRACKED_FIELDS:
            old_val = old_rec.get(field)
            new_val = new_rec.get(field)
            # NaN/None 정규화
            if _is_empty(old_val) and _is_empty(new_val):
                continue
            if old_val != new_val:
                changes[field] = {"old": old_val, "new": new_val}
        if changes:
            modified.append({
                "key": key,
                "제품명": new_rec.get("제품명", ""),
                "ingredient_code": new_rec.get("ingredient_code", ""),
                "changes": changes,
            })

    unchanged = len(common_keys) - len(modified)

    summary = {
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "unchanged": unchanged,
    }

    has_changes = summary["added"] > 0 or summary["removed"] > 0 or summary["modified"] > 0

    return {
        "has_changes": has_changes,
        "summary": summary,
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def _is_empty(val: Any) -> bool:
    """None, NaN, 빈 문자열 판별."""
    if val is None:
        return True
    if isinstance(val, float) and val != val:  # NaN
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def save_diff_report(diff: dict[str, Any], output_dir: Path | None = None) -> Path | None:
    """변경 내역을 JSON 리포트로 저장. 변경 없으면 None 반환."""
    if not diff["has_changes"]:
        return None

    if output_dir is None:
        output_dir = DATA_DIR / "changelog"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"drug_price_diff_{timestamp}.json"

    # 리포트 크기 제한: added/removed는 요약만 (제품코드+제품명)
    compact = {
        "timestamp": timestamp,
        "summary": diff["summary"],
        "added": [
            {"제품코드": r.get("제품코드"), "제품명": r.get("제품명"), "ingredient_code": r.get("ingredient_code")}
            for r in diff["added"][:200]  # 최대 200건
        ],
        "removed": [
            {"제품코드": r.get("제품코드"), "제품명": r.get("제품명"), "ingredient_code": r.get("ingredient_code")}
            for r in diff["removed"][:200]
        ],
        "modified": diff["modified"][:500],  # 최대 500건
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2, default=str)

    logger.info("[DrugPrice] 변경 리포트 저장: %s", report_path.name)
    return report_path


# ═══════════════════════════════════════════════════════
# 4. 통합 워커
# ═══════════════════════════════════════════════════════

class DrugPriceCollector:
    """적용약가파일 자동 수집 + 변환 워커."""

    async def run(
        self,
        *,
        headless: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """전체 파이프라인 실행: 다운로드 → 변환 → 변경감지.

        Parameters
        ----------
        headless : 브라우저 headless 모드
        force : True면 변경 여부와 무관하게 갱신

        Returns
        -------
        실행 결과 dict
        """
        start = datetime.now(timezone.utc)
        result: dict[str, Any] = {"status": "started"}

        # Step 1: 다운로드
        logger.info("[DrugPrice] === Step 1: 다운로드 ===")
        excel_path = await download_latest_drug_price(headless=headless)

        if excel_path is None:
            result["status"] = "download_failed"
            result["message"] = "약가파일 다운로드 실패 — 사이트 구조 확인 필요"
            return result

        result["excel_path"] = str(excel_path)
        result["excel_size_mb"] = round(excel_path.stat().st_size / (1024 * 1024), 1)

        # Step 2: 변환
        logger.info("[DrugPrice] === Step 2: Excel → JSON 변환 ===")
        json_path = convert_excel_to_json(excel_path)
        result["json_path"] = str(json_path)

        # Step 3: 변경 감지 (2단계: DataFrame 해시 게이트 → 레코드 diff)
        logger.info("[DrugPrice] === Step 3: 변경 감지 ===")
        current_path = get_current_drug_prices_path()
        # 새 파일이 기존 파일과 같은 경로면 비교 대상에서 제외
        old_path = None if (current_path and current_path.resolve() == json_path.resolve()) else current_path

        # 3-A: DataFrame 해시로 빠른 변경 여부 판별
        data_changed = has_data_changed(old_path, json_path)
        result["data_hash_changed"] = data_changed

        if not force and not data_changed:
            result["status"] = "no_change"
            result["message"] = "DataFrame 해시 비교 결과 데이터 동일 — 갱신 불필요"
            logger.info("[DrugPrice] DataFrame 해시 동일 — 스킵")
        else:
            # 3-B: 레코드 단위 상세 diff
            diff = diff_drug_prices(old_path, json_path)
            result["diff_summary"] = diff["summary"]

            if not force and not diff["has_changes"]:
                result["status"] = "no_change"
                result["message"] = "레코드 비교 결과 변경 없음 — 갱신 불필요"
                logger.info("[DrugPrice] 변경 없음 — 스킵")
            else:
                result["status"] = "updated"
                report_path = save_diff_report(diff)
                if report_path:
                    result["diff_report"] = str(report_path)
                logger.info(
                    "[DrugPrice] 변경 감지 — 신규 %d건, 삭제 %d건, 수정 %d건, 유지 %d건",
                    diff["summary"]["added"],
                    diff["summary"]["removed"],
                    diff["summary"]["modified"],
                    diff["summary"]["unchanged"],
                )

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        result["duration_sec"] = round(elapsed, 1)
        result["started_at"] = start.isoformat()

        return result


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

async def _main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="HIRA 적용약가파일 자동 수집")
    parser.add_argument("--download-only", action="store_true",
                        help="다운로드만 수행 (변환 안 함)")
    parser.add_argument("--convert-only", type=str, default=None,
                        help="기존 Excel 파일을 JSON으로 변환만")
    parser.add_argument("--no-headless", action="store_true",
                        help="브라우저 GUI 모드 (디버깅용)")
    parser.add_argument("--force", action="store_true",
                        help="변경 여부와 무관하게 갱신")
    args = parser.parse_args()

    if args.convert_only:
        path = Path(args.convert_only)
        if not path.exists():
            print(f"파일 없음: {path}")
            return
        json_path = convert_excel_to_json(path)
        print(f"변환 완료: {json_path}")
        return

    if args.download_only:
        excel_path = await download_latest_drug_price(headless=not args.no_headless)
        if excel_path:
            print(f"다운로드 완료: {excel_path}")
        else:
            print("다운로드 실패")
        return

    collector = DrugPriceCollector()
    result = await collector.run(
        headless=not args.no_headless,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
