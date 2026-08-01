from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import Optional

from app.database import get_db
from shared.models.schemas import Automation, AutomationCreate, AutomationUpdate, PaginatedResponse

router = APIRouter()


def _doc(doc: dict) -> Automation:
    doc["_id"] = str(doc["_id"])
    return Automation(**doc)


@router.get("", response_model=PaginatedResponse)
async def list_automations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if is_active is not None:
        query["is_active"] = is_active
    total = await db.automations.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.automations.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_doc(d) async for d in cursor]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("", response_model=Automation, status_code=201)
async def create_automation(
    payload: AutomationCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({"created_at": now, "updated_at": now, "run_count": 0, "last_run": None})
    result = await db.automations.insert_one(doc)
    created = await db.automations.find_one({"_id": result.inserted_id})
    return _doc(created)


@router.get("/{automation_id}", response_model=Automation)
async def get_automation(
    automation_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.automations.find_one({"_id": ObjectId(automation_id)})
    if not doc:
        raise HTTPException(404, "Automation not found")
    return _doc(doc)


@router.patch("/{automation_id}", response_model=Automation)
async def update_automation(
    automation_id: str,
    payload: AutomationUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db.automations.update_one({"_id": ObjectId(automation_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Automation not found")
    return _doc(await db.automations.find_one({"_id": ObjectId(automation_id)}))


@router.delete("/{automation_id}", status_code=204)
async def delete_automation(
    automation_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db.automations.delete_one({"_id": ObjectId(automation_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Automation not found")


@router.post("/{automation_id}/trigger")
async def trigger_automation(
    automation_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.automations.find_one({"_id": ObjectId(automation_id)})
    if not doc:
        raise HTTPException(404, "Automation not found")
    if not doc.get("is_active"):
        raise HTTPException(400, "Automation is inactive")
    now = datetime.utcnow()
    await db.automations.update_one(
        {"_id": ObjectId(automation_id)},
        {"$set": {"last_run": now, "updated_at": now}, "$inc": {"run_count": 1}},
    )
    return {"message": "Automation triggered", "automation_id": automation_id, "triggered_at": now}
