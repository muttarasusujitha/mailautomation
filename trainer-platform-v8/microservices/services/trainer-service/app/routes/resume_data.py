"""Resume data — query extracted trainer profiles by email, domain, summary."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/by-email")
async def get_resume_by_email(
    email: str = Query(..., description="Trainer email address"),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["trainers"].find_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}},
        {"_id": 0, "resume": 0, "combined_text": 0},
    )
    if not doc:
        raise HTTPException(404, "No trainer found with that email")
    return {"success": True, "trainer": doc}


@router.get("/by-domain")
async def get_resumes_by_domain(
    domain: str = Query(..., description="Technology domain / category"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query = {
        "$or": [
            {"technology_category": {"$regex": domain, "$options": "i"}},
            {"secondary_categories": {"$regex": domain, "$options": "i"}},
            {"skills": {"$regex": domain, "$options": "i"}},
        ]
    }
    cursor = db["trainers"].find(query, {"_id": 0, "resume": 0, "combined_text": 0}).limit(limit)
    items = [d async for d in cursor]
    return {"success": True, "domain": domain, "count": len(items), "trainers": items}


@router.get("/domain-summary")
async def domain_summary(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Count trainers per primary technology category."""
    pipeline = [
        {"$group": {"_id": "$technology_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$match": {"_id": {"$ne": None}}},
    ]
    summary = {r["_id"]: r["count"] async for r in db["trainers"].aggregate(pipeline)}
    return {"success": True, "domains": summary}


@router.delete("/by-email")
async def delete_resume_by_email(
    email: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db["trainers"].delete_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "No trainer found with that email")
    return {"success": True, "deleted": email}


@router.delete("/by-domain")
async def delete_resumes_by_domain(
    domain: str = Query(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db["trainers"].delete_many(
        {"technology_category": {"$regex": f"^{domain}$", "$options": "i"}}
    )
    return {"success": True, "domain": domain, "deleted_count": result.deleted_count}
