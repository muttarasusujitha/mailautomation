from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from typing import Optional

from app.database import get_db
from shared.models.schemas import EmailLog, PaginatedResponse

router = APIRouter()


def _doc(doc: dict) -> EmailLog:
    doc["_id"] = str(doc["_id"])
    return EmailLog(**doc)


@router.get("/email", response_model=PaginatedResponse)
async def list_email_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    customer_id: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if customer_id:
        query["customer_id"] = customer_id
    if direction:
        query["direction"] = direction
    if status:
        query["status"] = status
    total = await db.email_logs.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.email_logs.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_doc(d) async for d in cursor]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/email/{log_id}", response_model=EmailLog)
async def get_email_log(
    log_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    from fastapi import HTTPException
    doc = await db.email_logs.find_one({"_id": ObjectId(log_id)})
    if not doc:
        raise HTTPException(404, "Email log not found")
    return _doc(doc)


@router.get("/whatsapp")
async def list_whatsapp_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if status:
        query["status"] = status
    total = await db.whatsapp_logs.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.whatsapp_logs.find(query, {"_id": 0}).skip(skip).limit(page_size).sort("created_at", -1)
    items = [d async for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/teams")
async def list_teams_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if status:
        query["status"] = status
    total = await db.teams_logs.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.teams_logs.find(query, {"_id": 0}).skip(skip).limit(page_size).sort("created_at", -1)
    items = [d async for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
