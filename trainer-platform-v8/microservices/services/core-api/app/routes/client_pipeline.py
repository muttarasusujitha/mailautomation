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
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=200),
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

    effective_page_size = min(limit or page_size, 200)
    total = await db["requirements"].count_documents(query)
    skip = (page - 1) * effective_page_size
    requirements = await (
        db["requirements"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(effective_page_size)
        .to_list(effective_page_size)
    )

    # Enrich each requirement with its shortlist entry
    result: List[Dict[str, Any]] = []
    for req in requirements:
        req_id = req.get("requirement_id") or str(req.get("_id", ""))
        shortlist = await db["shortlists"].find_one(
            {"requirement_id": req_id}, {"_id": 0}
        ) or {}
        top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []
        selected_trainer_id = (
            shortlist.get("selected_trainer_id")
            or req.get("selected_trainer_id")
            or ""
        )
        selected_trainer = next(
            (trainer for trainer in top_trainers if trainer.get("trainer_id") == selected_trainer_id),
            None,
        )
        if not selected_trainer and selected_trainer_id:
            selected_trainer = await db["trainers"].find_one(
                {"trainer_id": selected_trainer_id}, {"_id": 0}
            )
        if not selected_trainer and shortlist.get("selected_trainer_name"):
            selected_trainer = {
                "trainer_id": selected_trainer_id,
                "name": shortlist.get("selected_trainer_name"),
            }

        client_po = await db["purchase_orders"].find_one(
            {"requirement_id": req_id}, {"_id": 0}, sort=[("created_at", -1)]
        ) or {}
        invoice = await db["invoices"].find_one(
            {"requirement_id": req_id}, {"_id": 0}, sort=[("created_at", -1)]
        ) or {}

        # Summarise pipeline stage counts
        stage_counts: Dict[str, int] = {}
        for t in top_trainers:
            stage = t.get("pipeline_status") or t.get("status") or "unknown"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        item = {
            **req,
            "client": {
                "name": req.get("client_name") or req.get("client_company") or "",
                "company": req.get("client_company") or req.get("client_name") or "",
                "email": req.get("client_email") or "",
            },
            "client_po": client_po,
            "invoice": invoice,
            "selected_trainer": selected_trainer or {},
            "shortlist": {
                "total_trainers": len(top_trainers),
                "stage_counts": stage_counts,
                "selected_trainer_id": selected_trainer_id,
                "selected_trainer_name": shortlist.get("selected_trainer_name") or (selected_trainer or {}).get("name"),
                "selection_status": shortlist.get("selection_status"),
            },
        }
        if q:
            haystack = " ".join(
                str(value or "")
                for value in (
                    req_id,
                    item.get("technology_needed"),
                    item.get("domain"),
                    item["client"].get("name"),
                    item["client"].get("company"),
                    item["client"].get("email"),
                    client_po.get("po_number"),
                    client_po.get("client_po_number"),
                    invoice.get("invoice_number"),
                    (selected_trainer or {}).get("name"),
                )
            ).lower()
            if q.lower() not in haystack:
                continue
        result.append(item)

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": effective_page_size,
        "pages": max(1, (total + effective_page_size - 1) // effective_page_size),
        "pipeline": result,
    }
