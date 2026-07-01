"""Email open tracking pixel."""
from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime

from app.database import get_db

router = APIRouter()

_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


@router.get("/{email_id}", name="track_email_open")
async def track_email_open(
    email_id: str = Path(...),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return 1×1 GIF pixel and record open event."""
    now = datetime.utcnow()
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {"opened": True, "opened_at": now, "status": "opened", "updated_at": now}},
    )
    return Response(content=_PIXEL, media_type="image/gif",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
