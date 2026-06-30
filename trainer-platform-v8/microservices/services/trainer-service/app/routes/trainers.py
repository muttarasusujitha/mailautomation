"""CRUD endpoints for trainers."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()


class TrainerCreate(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    linkedin: Optional[str] = ""
    skills: List[str] = []
    technology_category: Optional[str] = "Multi-Skillset"
    secondary_categories: List[str] = []
    experience_years: Optional[float] = 0
    location: Optional[str] = ""
    day_rate: Optional[float] = None
    bio: Optional[str] = ""
    metadata: Dict[str, Any] = {}


class TrainerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    skills: Optional[List[str]] = None
    technology_category: Optional[str] = None
    secondary_categories: Optional[List[str]] = None
    experience_years: Optional[float] = None
    location: Optional[str] = None
    day_rate: Optional[float] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _oid(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("")
async def list_trainers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if status:
        query["status"] = status
    if category:
        query["technology_category"] = {"$regex": category, "$options": "i"}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"skills": {"$regex": search, "$options": "i"}},
            {"technology_category": {"$regex": search, "$options": "i"}},
        ]
    total = await db.trainers.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.trainers.find(query, {"resume": 0, "combined_text": 0}).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_oid(d) async for d in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


@router.post("", status_code=201)
async def create_trainer(
    payload: TrainerCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    import uuid
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({
        "trainer_id": f"TR-{uuid.uuid4().hex[:8].upper()}",
        "status": "new",
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    })
    result = await db.trainers.insert_one(doc)
    created = await db.trainers.find_one({"_id": result.inserted_id}, {"resume": 0, "combined_text": 0})
    return _oid(created)


@router.get("/{trainer_id}")
async def get_trainer(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db.trainers.find_one(
        {"$or": [{"trainer_id": trainer_id}, {"_id": ObjectId(trainer_id)} if len(trainer_id) == 24 else {"trainer_id": trainer_id}]},
        {"resume": 0, "combined_text": 0},
    )
    if not doc:
        raise HTTPException(404, "Trainer not found")
    return _oid(doc)


@router.patch("/{trainer_id}")
async def update_trainer(
    trainer_id: str,
    payload: TrainerUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    result = await db.trainers.update_one({"trainer_id": trainer_id}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Trainer not found")
    doc = await db.trainers.find_one({"trainer_id": trainer_id}, {"resume": 0, "combined_text": 0})
    return _oid(doc)


@router.delete("/{trainer_id}", status_code=204)
async def delete_trainer(trainer_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db.trainers.delete_one({"trainer_id": trainer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer not found")
