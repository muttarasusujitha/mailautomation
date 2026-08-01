"""Client email conversations — paginated inbox view."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_client_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    requirement_id: Optional[str] = None,
    processed: Optional[bool] = None,
    reply_status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return client inbound emails with their AI-generated reply drafts."""
    query: Dict[str, Any] = {}
    if requirement_id:
        query["requirement_id"] = requirement_id
    if processed is not None:
        query["processed"] = processed
    if reply_status:
        query["reply_status"] = reply_status

    total = await db["client_emails"].count_documents(query)
    skip = (page - 1) * page_size
    cursor = (
        db["client_emails"]
        .find(query, {"_id": 0, "raw_body": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    items = [d async for d in cursor]
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "conversations": items,
    }
