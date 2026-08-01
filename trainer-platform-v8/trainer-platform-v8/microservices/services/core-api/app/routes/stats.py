from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timedelta

from app.database import get_db

router = APIRouter()


@router.get("/overview")
async def get_overview_stats(db: AsyncIOMotorDatabase = Depends(get_db)):
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    customers_total = await db.customers.count_documents({})
    customers_week = await db.customers.count_documents({"created_at": {"$gte": week_ago}})
    requirements_total = await db.requirements.count_documents({})
    requirements_active = await db.requirements.count_documents({"status": "active"})
    requirements_pending = await db.requirements.count_documents({"status": "pending"})
    journeys_total = await db.journeys.count_documents({})
    journeys_active = await db.journeys.count_documents({"status": "active"})
    automations_total = await db.automations.count_documents({})
    automations_active = await db.automations.count_documents({"is_active": True})

    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    req_by_status = {
        doc["_id"]: doc["count"]
        async for doc in db.requirements.aggregate(pipeline)
    }

    return {
        "customers": {
            "total": customers_total,
            "new_this_week": customers_week,
        },
        "requirements": {
            "total": requirements_total,
            "active": requirements_active,
            "pending": requirements_pending,
            "by_status": req_by_status,
        },
        "journeys": {
            "total": journeys_total,
            "active": journeys_active,
        },
        "automations": {
            "total": automations_total,
            "active": automations_active,
        },
        "generated_at": now.isoformat(),
    }


@router.get("/activity")
async def get_recent_activity(
    days: int = 7,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    customers = await db.customers.count_documents({"created_at": {"$gte": since}})
    requirements = await db.requirements.count_documents({"created_at": {"$gte": since}})
    journeys = await db.journeys.count_documents({"created_at": {"$gte": since}})
    return {
        "period_days": days,
        "new_customers": customers,
        "new_requirements": requirements,
        "new_journeys": journeys,
    }
