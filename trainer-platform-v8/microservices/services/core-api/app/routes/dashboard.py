"""Dashboard analytics and stats endpoints."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

# ─── helpers ──────────────────────────────────────────────────────────────────

def _safe_pct(a: int, b: int) -> float:
    return round(a * 100 / b, 1) if b else 0.0


def _outbound_email_query(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"direction": {"$ne": "inbound"}, **(extra or {})}


def _date_recent_query(field: str, since: datetime) -> Dict[str, Any]:
    return {
        "$or": [
            {field: {"$gte": since}},
            {field: {"$exists": False}, "created_at": {"$gte": since}},
            {field: None, "created_at": {"$gte": since}},
        ],
    }


# ─── /dashboard/stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def dashboard_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Quick KPI numbers for the top-of-page dashboard cards."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Requirements
    total_req = await db["requirements"].count_documents({})
    active_req = await db["requirements"].count_documents({"status": {"$in": ["active", "open", "pending"]}})
    closed_req = await db["requirements"].count_documents({"status": {"$in": ["closed", "fulfilled", "completed"]}})
    new_req_week = await db["requirements"].count_documents({"created_at": {"$gte": week_ago}})

    # Trainers
    total_trainers = await db["trainers"].count_documents({})
    new_trainers_week = await db["trainers"].count_documents({"created_at": {"$gte": week_ago}})

    # Emails
    total_emails_sent = await db["email_logs"].count_documents({"direction": "outbound", "status": "sent"})
    emails_this_week = await db["email_logs"].count_documents({
        "direction": "outbound",
        "status": "sent",
        "sent_at": {"$gte": week_ago},
    })
    inbox_pending = await db["client_emails"].count_documents({"processed": {"$ne": True}})

    # Shortlists
    total_shortlists = await db["shortlists"].count_documents({})
    selected_count = await db["requirements"].count_documents({
        "selected_trainer_id": {"$exists": True, "$ne": ""},
    })

    # WhatsApp
    wa_sent = await db["whatsapp_logs"].count_documents({"status": "sent"})

    return {
        "success": True,
        "generated_at": now.isoformat(),
        "requirements": {
            "total": total_req,
            "active": active_req,
            "closed": closed_req,
            "new_this_week": new_req_week,
            "selection_rate_pct": _safe_pct(selected_count, total_req),
        },
        "trainers": {
            "total": total_trainers,
            "new_this_week": new_trainers_week,
        },
        "emails": {
            "total_sent": total_emails_sent,
            "sent_this_week": emails_this_week,
            "inbox_pending": inbox_pending,
        },
        "shortlists": {
            "total": total_shortlists,
            "trainers_selected": selected_count,
        },
        "whatsapp": {
            "total_sent": wa_sent,
        },
    }


@router.get("/analytics")
async def dashboard_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Time-series analytics for the dashboard charts."""
    now = datetime.utcnow()
    since = now - timedelta(days=days)

    # Requirements over time — daily bucket
    pipeline_req: List[Dict[str, Any]] = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": {
                "year": {"$year": "$created_at"},
                "month": {"$month": "$created_at"},
                "day": {"$dayOfMonth": "$created_at"},
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1}},
    ]
    req_series = [
        {
            "date": f"{r['_id']['year']}-{r['_id']['month']:02d}-{r['_id']['day']:02d}",
            "requirements": r["count"],
        }
        async for r in db["requirements"].aggregate(pipeline_req)
    ]

    # Emails sent over time
    pipeline_email: List[Dict[str, Any]] = [
        {"$match": {"direction": "outbound", "status": "sent", "sent_at": {"$gte": since}}},
        {"$group": {
            "_id": {
                "year": {"$year": "$sent_at"},
                "month": {"$month": "$sent_at"},
                "day": {"$dayOfMonth": "$sent_at"},
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1}},
    ]
    email_series = [
        {
            "date": f"{r['_id']['year']}-{r['_id']['month']:02d}-{r['_id']['day']:02d}",
            "emails_sent": r["count"],
        }
        async for r in db["email_logs"].aggregate(pipeline_email)
    ]

    # Requirements by status
    status_pipeline: List[Dict[str, Any]] = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    req_by_status = {
        r["_id"]: r["count"]
        async for r in db["requirements"].aggregate(status_pipeline)
    }

    # Trainer pipeline stages
    pipeline_stages: List[Dict[str, Any]] = [
        {"$unwind": "$top_trainers"},
        {"$group": {"_id": "$top_trainers.pipeline_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    trainer_stages = {
        r["_id"]: r["count"]
        async for r in db["shortlists"].aggregate(pipeline_stages)
        if r["_id"]
    }

    return {
        "success": True,
        "period_days": days,
        "since": since.isoformat(),
        "requirements_over_time": req_series,
        "emails_over_time": email_series,
        "requirements_by_status": req_by_status,
        "trainer_pipeline_stages": trainer_stages,
    }
