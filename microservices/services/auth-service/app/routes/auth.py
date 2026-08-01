"""Authentication routes — password reset."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr, HttpUrl

from app.config import get_settings
from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class LinkedInOAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: HttpUrl


class LinkedInProfileResponse(BaseModel):
    name: str
    email: EmailStr
    provider: str = 'linkedin'
    provider_id: Optional[str] = None



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

@router.post("/linkedin/oauth-callback", response_model=LinkedInProfileResponse)
async def linkedin_oauth_callback(payload: LinkedInOAuthCallbackRequest):
    settings = get_settings()
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_SECRET:
        raise HTTPException(503, "LinkedIn OAuth is not configured.")

    token_endpoint = "https://www.linkedin.com/oauth/v2/accessToken"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": payload.code,
                    "redirect_uri": str(payload.redirect_uri),
                    "client_id": settings.LINKEDIN_CLIENT_ID,
                    "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
    except httpx.HTTPError as exc:
        logger.exception("LinkedIn token exchange failed: %s", exc)
        raise HTTPException(502, "Could not exchange LinkedIn authorization code.")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(502, "LinkedIn did not return an access token.")

    profile_url = "https://api.linkedin.com/v2/me"
    email_url = "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            profile_resp = await client.get(profile_url, headers=headers)
            profile_resp.raise_for_status()
            profile_data = profile_resp.json()

            email_resp = await client.get(email_url, headers=headers)
            email_resp.raise_for_status()
            email_data = email_resp.json()
    except httpx.HTTPError as exc:
        logger.exception("LinkedIn profile fetch failed: %s", exc)
        raise HTTPException(502, "Could not fetch LinkedIn profile information.")

    email = None
    elements = email_data.get("elements") or []
    if elements:
        handle = elements[0].get("handle~") or {}
        email = handle.get("emailAddress")

    if not email:
        raise HTTPException(502, "LinkedIn did not return an email address.")

    given_name = profile_data.get("localizedFirstName") or ""
    family_name = profile_data.get("localizedLastName") or ""
    name = " ".join([given_name, family_name]).strip() or email.split("@")[0]

    return {
        "name": name,
        "email": email,
        "provider": "linkedin",
        "provider_id": profile_data.get("id"),
    }