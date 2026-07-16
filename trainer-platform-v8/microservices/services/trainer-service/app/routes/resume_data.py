"""Resume data — query extracted trainer profiles by email, domain, summary."""
import logging
import re
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _domain_query(domain: str) -> Dict[str, Any]:
    pattern = re.escape(domain.strip())
    return {
        "$or": [
            {"technology_category": {"$regex": pattern, "$options": "i"}},
            {"primary_category": {"$regex": pattern, "$options": "i"}},
            {"category": {"$regex": pattern, "$options": "i"}},
            {"domain": {"$regex": pattern, "$options": "i"}},
            {"secondary_categories": {"$regex": pattern, "$options": "i"}},
            {"skills": {"$regex": pattern, "$options": "i"}},
            {"technologies": {"$regex": pattern, "$options": "i"}},
        ]
    }


def _upload_domain_query(domain: str) -> Dict[str, Any]:
    pattern = re.escape(domain.strip())
    return {
        "$or": [
            {"extracted_data.technology_category": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.primary_category": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.category": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.domain": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.secondary_categories": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.skills": {"$regex": pattern, "$options": "i"}},
            {"extracted_data.technologies": {"$regex": pattern, "$options": "i"}},
        ]
    }


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
    query = _domain_query(domain)
    upload_query = _upload_domain_query(domain)
    cursor = db["trainers"].find(query, {"_id": 0, "resume": 0, "combined_text": 0}).limit(limit)
    items = [d async for d in cursor]
    uploads = [
        d async for d in db["resume_uploads"]
        .find(upload_query, {"_id": 0, "extracted_text": 0})
        .sort("created_at", -1)
        .limit(limit)
    ]
    trainer_ids = [item.get("trainer_id") for item in items if item.get("trainer_id")]
    shortlists_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": {"$in": trainer_ids}}) if trainer_ids else 0
    email_count = await db["email_logs"].count_documents({"trainer_id": {"$in": trainer_ids}}) if trainer_ids else 0
    return _json_safe({
        "success": True,
        "domain": domain,
        "count": len(items),
        "counts": {
            "trainers": len(items),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlists_count,
            "email_logs": email_count,
            "conversations": 0,
        },
        "trainers": items,
        "uploads": uploads,
    })


@router.get("/domain-summary")
async def domain_summary(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return domain-wise saved trainers and uploaded resume records."""
    trainer_pipeline = [
        {"$project": {
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "technology_category": 1,
            "domain": {"$ifNull": ["$technology_category", "$primary_category"]},
        }},
        {"$match": {"domain": {"$nin": [None, ""]}}},
        {"$sort": {"created_at": -1}},
    ]
    upload_pipeline = [
        {"$project": {
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "domain": {
                "$ifNull": [
                    "$extracted_data.technology_category",
                    "$extracted_data.primary_category",
                ]
            },
        }},
        {"$match": {"domain": {"$nin": [None, ""]}}},
        {"$sort": {"created_at": -1}},
    ]

    domains: Dict[str, Dict[str, Any]] = {}
    async for trainer in db["trainers"].aggregate(trainer_pipeline):
        key = str(trainer.get("domain") or "Uncategorised")
        bucket = domains.setdefault(key, {"domain": key, "trainers": [], "uploads": []})
        bucket["trainers"].append(_json_safe({
            "type": "trainer",
            "trainer_id": trainer.get("trainer_id"),
            "name": trainer.get("name"),
            "email": trainer.get("email"),
        }))

    async for upload in db["resume_uploads"].aggregate(upload_pipeline):
        key = str(upload.get("domain") or "Uncategorised")
        bucket = domains.setdefault(key, {"domain": key, "trainers": [], "uploads": []})
        bucket["uploads"].append(_json_safe({
            "type": "upload",
            "upload_id": upload.get("upload_id"),
            "trainer_id": upload.get("trainer_id"),
            "filename": upload.get("filename"),
            "processing_status": upload.get("processing_status"),
        }))

    domain_rows = []
    for bucket in domains.values():
        bucket["trainers_count"] = len(bucket["trainers"])
        bucket["uploads_count"] = len(bucket["uploads"])
        bucket["trainers"] = bucket["trainers"][:5]
        bucket["uploads"] = bucket["uploads"][:5]
        domain_rows.append(bucket)
    domain_rows.sort(key=lambda item: (item["trainers_count"] + item["uploads_count"], item["domain"]), reverse=True)

    return {
        "success": True,
        "domains": domain_rows,
        "total_domains": len(domain_rows),
        "total_trainers": sum(item["trainers_count"] for item in domain_rows),
        "total_uploads": sum(item["uploads_count"] for item in domain_rows),
    }


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
    include_logs: bool = Query(False),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    trainer_query = _domain_query(domain)
    upload_query = _upload_domain_query(domain)
    trainers = await db["trainers"].find(trainer_query, {"_id": 0, "trainer_id": 1, "email": 1}).to_list(1000)
    trainer_ids = [item.get("trainer_id") for item in trainers if item.get("trainer_id")]
    emails = [item.get("email") for item in trainers if item.get("email")]

    trainer_result = await db["trainers"].delete_many(trainer_query)
    upload_result = await db["resume_uploads"].delete_many(upload_query)
    email_deleted = 0
    if include_logs and (trainer_ids or emails):
        email_result = await db["email_logs"].delete_many({
            "$or": [
                {"trainer_id": {"$in": trainer_ids}},
                {"to_email": {"$in": emails}},
                {"trainer_email": {"$in": emails}},
            ]
        })
        email_deleted = email_result.deleted_count

    return {
        "success": True,
        "domain": domain,
        "deleted_count": trainer_result.deleted_count,
        "deleted": {
            "trainers": trainer_result.deleted_count,
            "resume_uploads": upload_result.deleted_count,
            "email_logs": email_deleted,
        },
    }
