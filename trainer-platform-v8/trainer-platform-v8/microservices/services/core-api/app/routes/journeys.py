from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import Optional

from app.database import get_db
from shared.models.schemas import Journey, JourneyCreate, JourneyUpdate, PaginatedResponse

router = APIRouter()


def _doc(doc: dict) -> Journey:
    doc["_id"] = str(doc["_id"])
    return Journey(**doc)


@router.get("", response_model=PaginatedResponse)
async def list_journeys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    total = await db.journeys.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.journeys.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_doc(d) async for d in cursor]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("", response_model=Journey, status_code=201)
async def create_journey(
    payload: JourneyCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({"created_at": now, "updated_at": now})
    result = await db.journeys.insert_one(doc)
    created = await db.journeys.find_one({"_id": result.inserted_id})
    return _doc(created)


@router.get("/{journey_id}", response_model=Journey)
async def get_journey(
    journey_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db.journeys.find_one({"_id": ObjectId(journey_id)})
    if not doc:
        raise HTTPException(404, "Journey not found")
    return _doc(doc)


@router.patch("/{journey_id}", response_model=Journey)
async def update_journey(
    journey_id: str,
    payload: JourneyUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db.journeys.update_one({"_id": ObjectId(journey_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Journey not found")
    return _doc(await db.journeys.find_one({"_id": ObjectId(journey_id)}))


@router.delete("/{journey_id}", status_code=204)
async def delete_journey(
    journey_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db.journeys.delete_one({"_id": ObjectId(journey_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Journey not found")
