from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import Optional

from app.database import get_db
from shared.models.schemas import Customer, CustomerCreate, CustomerUpdate, PaginatedResponse

router = APIRouter()


def _doc(doc: dict) -> Customer:
    doc["_id"] = str(doc["_id"])
    return Customer(**doc)


@router.get("", response_model=PaginatedResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: dict = {}
    if status:
        query["status"] = status
    if search:
        query["$or"] = [
            {"name":    {"$regex": search, "$options": "i"}},
            {"email":   {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
        ]
    total = await db.customers.count_documents(query)
    skip = (page - 1) * page_size
    cursor = db.customers.find(query).skip(skip).limit(page_size).sort("created_at", -1)
    items = [_doc(d) async for d in cursor]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("", response_model=Customer, status_code=201)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    doc = payload.model_dump()
    doc.update({"created_at": now, "updated_at": now})
    result = await db.customers.insert_one(doc)
    created = await db.customers.find_one({"_id": result.inserted_id})
    return _doc(created)


@router.get("/{customer_id}", response_model=Customer)
async def get_customer(
    customer_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        oid = ObjectId(customer_id)
    except Exception:
        raise HTTPException(400, "Invalid customer_id format")
    doc = await db.customers.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Customer not found")
    return _doc(doc)


@router.patch("/{customer_id}", response_model=Customer)
async def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "No fields to update")
    data["updated_at"] = datetime.utcnow()
    try:
        oid = ObjectId(customer_id)
    except Exception:
        raise HTTPException(400, "Invalid customer_id format")
    result = await db.customers.update_one({"_id": oid}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(404, "Customer not found")
    return _doc(await db.customers.find_one({"_id": oid}))


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    try:
        oid = ObjectId(customer_id)
    except Exception:
        raise HTTPException(400, "Invalid customer_id format")
    result = await db.customers.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Customer not found")
