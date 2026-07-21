"""Dashboard analytics and stats endpoints."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
PENDING_CLIENT_STATUSES = ["pending_approval", "pending_review", "needs_manual_review"]

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


def _client_status_query(statuses: List[str]) -> Dict[str, Any]:
    return {
        "$or": [
            {"status": {"$in": statuses}},
            {"reply_status": {"$in": statuses}},
        ],
    }


# ─── /dashboard/stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def dashboard_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Quick KPI numbers for the top-of-page dashboard cards."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Requirements
    total_req = await db["requirements"].count_documents({})
    active_req = await db["requirements"].count_documents({"status": {"$in": ["active", "open", "pending"]}})
    closed_req = await db["requirements"].count_documents({"status": {"$in": ["closed", "fulfilled", "completed"]}})
    new_req_week = await db["requirements"].count_documents({"created_at": {"$gte": week_ago}})

    # Trainers
    # Resume uploads create rows in both `trainers` and `resume_uploads` in the
    # normal path, but older/imported data can exist only as upload records or
    # discovered trainer leads. Keep the headline inventory from dropping to 0
    # when profile data exists outside the confirmed trainers collection.
    confirmed_trainers = await db["trainers"].count_documents({})
    uploaded_resume_records = await db["resume_uploads"].count_documents({})
    trainer_leads = await db["trainer_profile_leads"].count_documents({})
    total_trainers = max(confirmed_trainers, uploaded_resume_records, trainer_leads)
    new_confirmed_trainers_week = await db["trainers"].count_documents({"created_at": {"$gte": week_ago}})
    new_uploaded_resumes_week = await db["resume_uploads"].count_documents({"created_at": {"$gte": week_ago}})
    new_trainer_leads_week = await db["trainer_profile_leads"].count_documents({"created_at": {"$gte": week_ago}})
    new_trainers_week = max(new_confirmed_trainers_week, new_uploaded_resumes_week, new_trainer_leads_week)

    # Emails
    # Some legacy send logs have no direction field, while inbound logs are
    # explicitly marked as inbound. Count all non-inbound sent rows.
    sent_email_query = _outbound_email_query({"status": "sent"})
    total_emails_sent = await db["email_logs"].count_documents(sent_email_query)
    emails_this_week = await db["email_logs"].count_documents(
        _outbound_email_query({"status": "sent", **_date_recent_query("sent_at", week_ago)})
    )
    failed_emails = await db["email_logs"].count_documents(
        _outbound_email_query({"status": "failed"})
    )
    total_replies = await db["email_logs"].count_documents(
        _outbound_email_query({"reply_received": True})
    )
    replies_this_week = await db["email_logs"].count_documents(
        _outbound_email_query({"reply_received": True, **_date_recent_query("reply_received_at", week_ago)})
    )

    # Client inbox
    total_client_requests = await db["client_emails"].count_documents({})
    client_requests_today = await db["client_emails"].count_documents({"created_at": {"$gte": today_start}})
    client_pending = await db["client_emails"].count_documents(_client_status_query(PENDING_CLIENT_STATUSES))
    client_requirements_created = await db["client_emails"].count_documents({
        "requirement_id": {"$exists": True, "$nin": ["", None]},
    })
    inbox_pending = await db["client_emails"].count_documents({"processed": {"$ne": True}})

    # Shortlists
    total_shortlists = await db["shortlists"].count_documents({})
    selected_count = await db["requirements"].count_documents({
        "selected_trainer_id": {"$exists": True, "$ne": ""},
    })

    # WhatsApp
    wa_success_statuses = ["queued", "sent", "delivered", "read"]
    wa_sent = await db["whatsapp_logs"].count_documents({"status": {"$in": wa_success_statuses}})
    wa_failed = await db["whatsapp_logs"].count_documents({"status": {"$in": ["failed", "undelivered"]}})
    wa_skipped = await db["whatsapp_logs"].count_documents({"status": "skipped"})
    wa_total = await db["whatsapp_logs"].count_documents({})
    wa_replies = await db["whatsapp_logs"].count_documents({
        "$or": [
            {"direction": "inbound"},
            {"status": "received"},
        ],
    })

    return {
        "success": True,
        "generated_at": now.isoformat(),
        # Compatibility fields for older dashboard bundles that predate the
        # nested KPI response shape below.
        "total_trainers": total_trainers,
        "total_requirements": total_req,
        "active_requirements": active_req,
        "closed_requirements": closed_req,
        "total_emails_sent": total_emails_sent,
        "total_emails_failed": failed_emails,
        "emails_sent_this_week": emails_this_week,
        "pending_review": 0,
        "interested_count": 0,
        "contacted_count": total_emails_sent,
        "confirmed_count": selected_count,
        "declined_count": 0,
        "requirements": {
            "total": total_req,
            "active": active_req,
            "closed": closed_req,
            "new_this_week": new_req_week,
            "selection_rate_pct": _safe_pct(selected_count, total_req),
        },
        "trainers": {
            "total": total_trainers,
            "confirmed": confirmed_trainers,
            "uploaded_resumes": uploaded_resume_records,
            "leads": trainer_leads,
            "new_this_week": new_trainers_week,
        },
        "emails": {
            "total_sent": total_emails_sent,
            "sent_this_week": emails_this_week,
            "failed": failed_emails,
            "total_replies": total_replies,
            "replies_this_week": replies_this_week,
            "inbox_pending": inbox_pending,
        },
        "total_replies": total_replies,
        "client_requests": {
            "total": total_client_requests,
            "today": client_requests_today,
            "pending_approval": client_pending,
            "requirements_created": client_requirements_created,
        },
        "shortlists": {
            "total": total_shortlists,
            "trainers_selected": selected_count,
        },
        "whatsapp": {
            "total_sent": wa_sent,
            "sent": wa_sent,
            "failed": wa_failed,
            "skipped": wa_skipped,
            "replies": wa_replies,
            "total_attempted": wa_total,
            "total": wa_total,
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
        {"$match": _outbound_email_query({"status": "sent", **_date_recent_query("sent_at", since)})},
        {"$addFields": {"bucket_date": {"$ifNull": ["$sent_at", "$created_at"]}}},
        {"$group": {
            "_id": {
                "year": {"$year": "$bucket_date"},
                "month": {"$month": "$bucket_date"},
                "day": {"$dayOfMonth": "$bucket_date"},
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
