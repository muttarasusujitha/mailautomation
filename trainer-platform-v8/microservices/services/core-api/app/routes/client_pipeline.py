"""Client pipeline — view all active requirements with their trainer pipeline."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def get_client_pipeline(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Aggregate view of requirements with their shortlist/trainer pipeline info.
    Mirrors the monolith's GET /client-pipeline endpoint.
    """
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    else:
        # Default: active requirements
        query["status"] = {"$nin": ["closed", "fulfilled", "cancelled"]}

    total = await db["requirements"].count_documents(query)
    skip = (page - 1) * page_size
    requirements = await (
        db["requirements"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
        .to_list(page_size)
    )

    # Enrich each requirement with its shortlist entry
    result: List[Dict[str, Any]] = []
    for req in requirements:
        req_id = req.get("requirement_id") or str(req.get("_id", ""))
        shortlist = await db["shortlists"].find_one(
            {"requirement_id": req_id}, {"_id": 0}
        ) or {}
        top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []

        # Summarise pipeline stage counts
        stage_counts: Dict[str, int] = {}
        for t in top_trainers:
            stage = t.get("pipeline_status") or t.get("status") or "unknown"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        result.append({
            **req,
            "shortlist": {
                "total_trainers": len(top_trainers),
                "stage_counts": stage_counts,
                "selected_trainer_id": shortlist.get("selected_trainer_id"),
                "selected_trainer_name": shortlist.get("selected_trainer_name"),
                "selection_status": shortlist.get("selection_status"),
            },
        })

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "pipeline": result,
    }
