"""Database maintenance — development-only destructive operations."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

CLEARABLE_COLLECTIONS = [
    "email_logs",
    "shortlists",
    "trainer_slot_responses",
    "slots",
    "toc_generations",
    "whatsapp_logs",
    "teams_logs",
    "resume_uploads",
    "linkedin_leads",
    "email_analysis",
    "client_emails",
    "client_leads",
    "trainer_profile_leads",
    "purchase_orders",
    "invoices",
]


@router.delete("/clear")
async def clear_database(
    collection: str = "all",
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    ⚠️  DEVELOPMENT ONLY — clears one or all non-critical collections.
    Refuses to run in production (DEBUG must be True in settings).
    """
    if not settings.DEBUG:
        raise HTTPException(
            403,
            detail="Database clear is only allowed when DEBUG=True. Refusing in production.",
        )

    if collection == "all":
        targets = CLEARABLE_COLLECTIONS
    elif collection in CLEARABLE_COLLECTIONS:
        targets = [collection]
    else:
        raise HTTPException(
            400,
            detail=f"Unknown collection '{collection}'. Allowed: {', '.join(CLEARABLE_COLLECTIONS)}",
        )

    results = {}
    for col in targets:
        try:
            res = await db[col].delete_many({})
            results[col] = res.deleted_count
        except Exception as exc:
            results[col] = f"error: {exc}"
            logger.error("Failed to clear collection %s: %s", col, exc)

    logger.warning("Database clear executed: %s", results)
    return {"success": True, "deleted": results}
