"""Authentication routes — password reset."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Initiate a password-reset flow. Always returns 200 to avoid email enumeration."""
    user = await db["auth_users"].find_one({"email": payload.email}, {"_id": 0, "user_id": 1, "name": 1})
    if not user:
        # Return success regardless — avoids email enumeration
        return {"success": True, "message": "If that email exists you will receive a reset link."}

    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=2)
    await db["password_resets"].insert_one({
        "user_id": user.get("user_id"),
        "email": payload.email,
        "token": token,
        "expires_at": expires_at,
        "used": False,
        "created_at": datetime.utcnow(),
    })
    # In production: send email with the reset link
    logger.info("Password reset token created for %s (not emailed in dev mode)", payload.email)
    return {"success": True, "message": "If that email exists you will receive a reset link."}
