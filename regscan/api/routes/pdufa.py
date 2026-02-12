"""PDUFA 일정 API

GET /api/v1/pdufa/upcoming  — D-Day 카운트다운 목록
POST /api/v1/pdufa          — 수동 등록
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


# ── Schemas ──

class PdufaItem(BaseModel):
    id: int
    inn: str
    brand_name: str = ""
    company: str = ""
    pdufa_date: date
    indication: str = ""
    application_type: str = ""
    status: str = "pending"
    days_until: int = 0
    notes: str = ""


class PdufaCreateRequest(BaseModel):
    inn: str
    brand_name: str = ""
    company: str = ""
    pdufa_date: date
    indication: str = ""
    application_type: str = ""  # NDA / BLA
    notes: str = ""


# ── Endpoints ──

@router.get("/upcoming", response_model=list[PdufaItem])
async def get_upcoming_pdufa():
    """다가오는 PDUFA 일정 (D-Day 카운트다운)"""
    from regscan.db.database import get_async_session
    from regscan.db.models import PdufaDateDB
    from sqlalchemy import select

    try:
        async with get_async_session()() as session:
            stmt = (
                select(PdufaDateDB)
                .where(PdufaDateDB.status == "pending")
                .where(PdufaDateDB.pdufa_date >= date.today())
                .order_by(PdufaDateDB.pdufa_date)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            items = []
            for row in rows:
                days_until = (row.pdufa_date - date.today()).days
                items.append(PdufaItem(
                    id=row.id,
                    inn=row.inn,
                    brand_name=row.brand_name or "",
                    company=row.company or "",
                    pdufa_date=row.pdufa_date,
                    indication=row.indication or "",
                    application_type=row.application_type or "",
                    status=row.status or "pending",
                    days_until=days_until,
                    notes=row.notes or "",
                ))
            return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDUFA 조회 실패: {e}")


@router.post("", response_model=PdufaItem)
async def create_pdufa(req: PdufaCreateRequest):
    """PDUFA 일정 수동 등록"""
    from regscan.db.database import get_async_session
    from regscan.db.models import PdufaDateDB

    try:
        async with get_async_session()() as session:
            row = PdufaDateDB(
                inn=req.inn,
                brand_name=req.brand_name,
                company=req.company,
                pdufa_date=req.pdufa_date,
                indication=req.indication,
                application_type=req.application_type,
                notes=req.notes,
                status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            days_until = (row.pdufa_date - date.today()).days
            return PdufaItem(
                id=row.id,
                inn=row.inn,
                brand_name=row.brand_name or "",
                company=row.company or "",
                pdufa_date=row.pdufa_date,
                indication=row.indication or "",
                application_type=row.application_type or "",
                status=row.status or "pending",
                days_until=days_until,
                notes=row.notes or "",
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDUFA 등록 실패: {e}")
