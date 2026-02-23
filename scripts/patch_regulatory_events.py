"""regulatory_events 테이블 8건 데이터 오류 수동 패치.

팩트체크에서 발견된 오류:
  - SEMAGLUTIDE FDA/EMA 날짜·URL 오류 (Last-Write-Wins)
  - CABOZANTINIB FDA 날짜 오류 (최신 submission 추출 버그)
  - zanidatamab / setmelanotide / polatuzumab vedotin FDA 누락 (7일 윈도우)
  - polatuzumab vedotin EMA 날짜 오류

사용법: python scripts/patch_regulatory_events.py
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "regscan.db"

# ── 패치 정의 ──────────────────────────────────
# (inn, agency, field_updates_or_insert)
PATCHES: list[dict] = [
    # 1. SEMAGLUTIDE — FDA approval_date
    {
        "inn": "semaglutide",
        "agency": "fda",
        "action": "update",
        "fields": {"approval_date": "2021-06-04"},
    },
    # 2. SEMAGLUTIDE — EMA approval_date + source_url
    {
        "inn": "semaglutide",
        "agency": "ema",
        "action": "update",
        "fields": {
            "approval_date": "2022-01-06",
            "source_url": "https://www.ema.europa.eu/en/medicines/human/EPAR/wegovy",
        },
    },
    # 3. CABOZANTINIB — FDA approval_date
    {
        "inn": "cabozantinib",
        "agency": "fda",
        "action": "upsert",
        "fields": {"status": "approved", "approval_date": "2012-11-29"},
    },
    # 4. zanidatamab — FDA INSERT
    {
        "inn": "zanidatamab",
        "agency": "fda",
        "action": "upsert",
        "fields": {
            "status": "approved",
            "approval_date": "2024-11-20",
        },
    },
    # 5. setmelanotide — FDA INSERT
    {
        "inn": "setmelanotide",
        "agency": "fda",
        "action": "upsert",
        "fields": {
            "status": "approved",
            "approval_date": "2020-11-25",
        },
    },
    # 6. polatuzumab vedotin — FDA INSERT
    {
        "inn": "polatuzumab vedotin",
        "agency": "fda",
        "action": "upsert",
        "fields": {
            "status": "approved",
            "approval_date": "2019-06-10",
        },
    },
    # 7. polatuzumab vedotin — EMA approval_date
    {
        "inn": "polatuzumab vedotin",
        "agency": "ema",
        "action": "update",
        "fields": {"approval_date": "2020-01-16"},
    },
]


def get_drug_id(cur: sqlite3.Cursor, inn: str) -> int | None:
    """drugs 테이블에서 INN(대소문자 무시)으로 drug_id 조회."""
    cur.execute(
        "SELECT id FROM drugs WHERE LOWER(inn) = LOWER(?) OR LOWER(normalized_name) = LOWER(?)",
        (inn, inn),
    )
    row = cur.fetchone()
    return row[0] if row else None


def apply_patch(cur: sqlite3.Cursor, patch: dict) -> str:
    """단일 패치 적용. 결과 메시지 반환."""
    inn = patch["inn"]
    agency = patch["agency"]
    action = patch["action"]
    fields = patch["fields"]

    drug_id = get_drug_id(cur, inn)
    if drug_id is None:
        return f"  SKIP  {inn} : drugs not found"

    # 기존 이벤트 확인
    cur.execute(
        "SELECT id FROM regulatory_events WHERE drug_id = ? AND agency = ?",
        (drug_id, agency),
    )
    existing = cur.fetchone()

    if action == "update":
        if not existing:
            return f"  SKIP  {inn}/{agency} : no existing event row"
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [drug_id, agency]
        cur.execute(
            f"UPDATE regulatory_events SET {set_clause} WHERE drug_id = ? AND agency = ?",
            values,
        )
        return f"  UPDATE {inn}/{agency} -> {fields}"

    elif action == "upsert":
        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [drug_id, agency]
            cur.execute(
                f"UPDATE regulatory_events SET {set_clause} WHERE drug_id = ? AND agency = ?",
                values,
            )
            return f"  UPDATE {inn}/{agency} -> {fields}"
        else:
            cols = ["drug_id", "agency"] + list(fields.keys())
            placeholders = ", ".join(["?"] * len(cols))
            values = [drug_id, agency] + list(fields.values())
            cur.execute(
                f"INSERT INTO regulatory_events ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            return f"  INSERT {inn}/{agency} -> {fields}"

    return f"  UNKNOWN action: {action}"


def main():
    if not DB_PATH.exists():
        print(f"DB 파일 없음: {DB_PATH}")
        sys.exit(1)

    print(f"DB: {DB_PATH}")
    print(f"패치 {len(PATCHES)}건 적용 시작\n")

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    results = []
    for patch in PATCHES:
        msg = apply_patch(cur, patch)
        results.append(msg)
        print(msg)

    conn.commit()
    conn.close()

    print(f"\n완료: {len(results)}건 처리")


if __name__ == "__main__":
    main()
