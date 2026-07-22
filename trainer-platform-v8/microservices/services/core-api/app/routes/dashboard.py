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
OPEN_REQUIREMENT_STATUSES = ["active", "open", "pending", "in_progress"]
CLOSED_REQUIREMENT_STATUSES = ["closed", "fulfilled", "completed", "cancelled"]
PIPELINE_TRAINER_STAGES = [
    "shortlisted",
    "mail1_sent",
    "waiting_reply1",
    "waiting_reply2",
    "interested",
    "selected",
    "toc_requested",
    "training_confirmed",
    "po_requested",
    "client_po_received",
    "invoice_generated",
    "invoice_sent",
]

# ─── helpers ──────────────────────────────────────────────────────────────────

def _safe_pct(a: int, b: int) -> float:
    return round(a * 100 / b, 1) if b else 0.0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Optional[str], fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return fallback


def _range_from_params(preset: str, start_date: Optional[str], end_date: Optional[str]) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    key = (preset or "month").lower()
    if key == "today":
        start = today
    elif key == "week":
        start = today - timedelta(days=today.weekday())
    elif key == "custom":
        start = _parse_date(start_date, today.replace(day=1))
    else:
        start = today.replace(day=1)

    if key == "custom":
        end = _parse_date(end_date, now).replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        end = now
    if end < start:
        start, end = (
            end.replace(hour=0, minute=0, second=0, microsecond=0),
            start.replace(hour=23, minute=59, second=59, microsecond=999999),
        )
    return start, end


def _date_range_query(field: str, start: datetime, end: datetime) -> Dict[str, Any]:
    return {field: {"$gte": start, "$lte": end}}


def _event_date_query(field: str, start: datetime, end: datetime) -> Dict[str, Any]:
    return {
        "$or": [
            {field: {"$gte": start, "$lte": end}},
            {field: {"$exists": False}, "created_at": {"$gte": start, "$lte": end}},
            {field: None, "created_at": {"$gte": start, "$lte": end}},
        ],
    }


def _date_bucket(date_value: datetime, start: datetime, end: datetime) -> str:
    if (end - start).days <= 1:
        return date_value.strftime("%d %b")
    monday = date_value - timedelta(days=date_value.weekday())
    return monday.strftime("%d %b")


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
    preset: str = Query("month"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Time-series analytics for the dashboard charts."""
    now = datetime.utcnow()
    start, end = _range_from_params(preset, start_date, end_date)
    since = start

    # Requirements over time — daily bucket
    pipeline_req: List[Dict[str, Any]] = [
        {"$match": {"created_at": {"$gte": start, "$lte": end}}},
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
        {"$match": _outbound_email_query({"status": "sent", **_event_date_query("sent_at", start, end)})},
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

    open_query = {
        "$or": [
            {"status": {"$in": OPEN_REQUIREMENT_STATUSES}},
            {"status": {"$exists": False}},
            {"status": None},
            {"status": ""},
        ]
    }
    closed_query = {
        "$or": [
            {"status": {"$in": CLOSED_REQUIREMENT_STATUSES}},
            {"client_po_status": {"$in": ["received", "invoice_generated", "invoice_sent"]}},
            {"invoice_status": {"$in": ["generated", "sent"]}},
            {"client_po_requested": True},
        ]
    }
    total_open = await db["requirements"].count_documents(open_query)
    total_closed = await db["requirements"].count_documents(closed_query)
    total_in_pipeline = await db["shortlists"].count_documents({
        "top_trainers.pipeline_status": {"$in": PIPELINE_TRAINER_STAGES}
    })

    po_docs = await db["purchase_orders"].find(
        {},
        {"_id": 0, "requirement_id": 1, "created_at": 1, "updated_at": 1, "total_amount": 1},
    ).to_list(10000)
    po_req_ids = [doc.get("requirement_id") for doc in po_docs if doc.get("requirement_id")]
    req_by_id = {
        doc.get("requirement_id"): doc
        for doc in await db["requirements"].find(
            {"requirement_id": {"$in": po_req_ids}},
            {"_id": 0, "requirement_id": 1, "created_at": 1},
        ).to_list(10000)
    }
    close_days = []
    for po in po_docs:
        po_date = po.get("created_at") or po.get("updated_at")
        req_date = req_by_id.get(po.get("requirement_id"), {}).get("created_at")
        if isinstance(po_date, datetime) and isinstance(req_date, datetime) and po_date >= req_date:
            close_days.append((po_date - req_date).total_seconds() / 86400)
    average_days_to_close = round(sum(close_days) / len(close_days), 1) if close_days else 0.0

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    po_month_docs = await db["purchase_orders"].find(
        _date_range_query("created_at", month_start, now),
        {"_id": 0, "total_amount": 1},
    ).to_list(10000)
    po_month = {
        "count": len(po_month_docs),
        "value": round(sum(_safe_float(doc.get("total_amount")) for doc in po_month_docs), 2),
        "currency": "INR",
    }

    requirement_docs = await db["requirements"].find(
        {"$or": [_date_range_query("created_at", start, end), _date_range_query("updated_at", start, end)]},
        {"_id": 0, "created_at": 1, "updated_at": 1, "status": 1, "technology_needed": 1, "domain": 1, "title": 1},
    ).to_list(10000)
    weekly_map: Dict[str, Dict[str, Any]] = {}
    categories: Dict[str, int] = {}
    for doc in requirement_docs:
        created_at = doc.get("created_at")
        if isinstance(created_at, datetime) and start <= created_at <= end:
            bucket = _date_bucket(created_at, start, end)
            weekly_map.setdefault(bucket, {"week": bucket, "opened": 0, "closed": 0})["opened"] += 1
        updated_at = doc.get("updated_at")
        status = (doc.get("status") or "").lower()
        if status in CLOSED_REQUIREMENT_STATUSES and isinstance(updated_at, datetime) and start <= updated_at <= end:
            bucket = _date_bucket(updated_at, start, end)
            weekly_map.setdefault(bucket, {"week": bucket, "opened": 0, "closed": 0})["closed"] += 1
        category = doc.get("technology_needed") or doc.get("domain") or doc.get("title") or "Uncategorised"
        categories[category] = categories.get(category, 0) + 1
    requirements_weekly = list(weekly_map.values())
    category_breakdown = [
        {"name": key, "value": value}
        for key, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)[:8]
    ]
    pipeline_funnel = [
        {"stage": key.replace("_", " ").title(), "value": value}
        for key, value in trainer_stages.items()
    ]

    wa_query = _event_date_query("sent_at", start, end)
    wa_total = await db["whatsapp_logs"].count_documents(wa_query)
    wa_delivered = await db["whatsapp_logs"].count_documents({"$and": [wa_query, {"status": {"$in": ["delivered", "read"]}}]})
    wa_sent = await db["whatsapp_logs"].count_documents({"$and": [wa_query, {"status": {"$in": ["queued", "sent"]}}]})
    wa_failed = await db["whatsapp_logs"].count_documents({"$and": [wa_query, {"status": {"$in": ["failed", "undelivered"]}}]})
    whatsapp = {
        "total": wa_total,
        "sent": wa_sent,
        "delivered": wa_delivered,
        "failed": wa_failed,
        "delivery_rate": _safe_pct(wa_delivered, wa_total),
    }

    reply_rate_trend = []
    for offset in range(3, -1, -1):
        wk_end = end - timedelta(days=offset * 7)
        wk_start = wk_end - timedelta(days=6)
        sent_q = _outbound_email_query({"status": "sent", **_event_date_query("sent_at", wk_start, wk_end)})
        reply_q = _outbound_email_query({"reply_received": True, **_event_date_query("reply_received_at", wk_start, wk_end)})
        sent = await db["email_logs"].count_documents(sent_q)
        replies = await db["email_logs"].count_documents(reply_q)
        reply_rate_trend.append({"week": wk_start.strftime("%d %b"), "sent": sent, "reply_rate": _safe_pct(replies, sent)})

    expense_logs = await db["expense_logs"].find(_date_range_query("created_at", start, end), {"_id": 0}).to_list(10000)
    ai_logs = await db["ai_usage_logs"].find(_date_range_query("created_at", start, end), {"_id": 0}).to_list(10000)
    buckets = {"whatsapp": 0.0, "teams": 0.0, "gemini": 0.0, "storage": 0.0}
    counts = {"whatsapp": wa_total, "teams": 0, "gemini": len(ai_logs), "storage": 0}
    weekly_expenses: Dict[str, Dict[str, Any]] = {}
    for doc in expense_logs:
        key = str(doc.get("category") or doc.get("service") or "").lower()
        amount = _safe_float(doc.get("cost_inr") or doc.get("amount_inr") or doc.get("cost") or doc.get("amount"))
        if "whatsapp" in key:
            bucket_key = "whatsapp"
        elif "team" in key:
            bucket_key = "teams"
        elif "gemini" in key or "ai" in key:
            bucket_key = "gemini"
        else:
            bucket_key = "storage"
        buckets[bucket_key] += amount
        counts[bucket_key] += 1
        created_at = doc.get("created_at")
        if isinstance(created_at, datetime):
            week = _date_bucket(created_at, start, end)
            row = weekly_expenses.setdefault(week, {"week": week, "whatsapp": 0, "teams": 0, "gemini": 0, "storage": 0})
            row[bucket_key] += amount
    for doc in ai_logs:
        amount = _safe_float(doc.get("cost_inr") or doc.get("amount_inr"))
        buckets["gemini"] += amount
        created_at = doc.get("created_at")
        if amount and isinstance(created_at, datetime):
            week = _date_bucket(created_at, start, end)
            row = weekly_expenses.setdefault(week, {"week": week, "whatsapp": 0, "teams": 0, "gemini": 0, "storage": 0})
            row["gemini"] += amount

    expenses = {
        "currency": "INR",
        "estimated": False,
        "total": round(sum(buckets.values()), 2),
        "communication_total": round(buckets["whatsapp"] + buckets["teams"], 2),
        "ai_total": round(buckets["gemini"], 2),
        "storage_total": round(buckets["storage"], 2),
        "items": [
            {"key": "whatsapp", "label": "WhatsApp", "cost": round(buckets["whatsapp"], 2), "count": counts["whatsapp"], "unit": "logs", "note": "Only explicit WhatsApp cost logs are summed."},
            {"key": "teams", "label": "Teams", "cost": round(buckets["teams"], 2), "count": counts["teams"], "unit": "logs", "note": "Only explicit Teams cost logs are summed."},
            {"key": "gemini", "label": "Gemini AI", "cost": round(buckets["gemini"], 2), "count": counts["gemini"], "unit": "logs", "note": "Only logged INR AI cost fields are summed."},
            {"key": "client_storage", "label": "Client Inbox Storage", "cost": round(buckets["storage"], 2), "count": counts["storage"], "unit": "logs", "note": "Only explicit storage cost logs are summed."},
        ],
        "weekly": list(weekly_expenses.values()),
    }

    return {
        "success": True,
        "period_days": days,
        "since": since.isoformat(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "status_cards": {
            "total_open": total_open,
            "total_closed": total_closed,
            "total_in_pipeline": total_in_pipeline,
            "average_days_to_close": average_days_to_close,
        },
        "requirements_weekly": requirements_weekly,
        "pipeline_funnel": pipeline_funnel,
        "category_breakdown": category_breakdown,
        "reply_rate_trend": reply_rate_trend,
        "whatsapp": whatsapp,
        "po_month": po_month,
        "expenses": expenses,
        "requirements_over_time": req_series,
        "emails_over_time": email_series,
        "requirements_by_status": req_by_status,
        "trainer_pipeline_stages": trainer_stages,
    }
