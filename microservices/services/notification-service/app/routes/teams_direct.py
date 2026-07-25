"""Microsoft Teams Direct — Graph API OAuth + message sending."""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
TEAMS_AUTH_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
TEAMS_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
SCOPES = "https://graph.microsoft.com/Chat.Create https://graph.microsoft.com/ChatMessage.Send offline_access"


async def _get_teams_cfg(db) -> Dict[str, Any]:
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0, "teamsDirectCfg": 1}) or {}
    cfg = doc.get("teamsDirectCfg") or {}
    return {
        "client_id": cfg.get("clientId") or "",
        "client_secret": cfg.get("clientSecret") or "",
        "tenant_id": cfg.get("tenantId") or "common",
        "access_token": cfg.get("accessToken") or "",
        "refresh_token": cfg.get("refreshToken") or "",
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def teams_direct_status(db: AsyncIOMotorDatabase = Depends(get_db)):
    cfg = await _get_teams_cfg(db)
    connected = bool(cfg.get("access_token") and cfg.get("client_id"))
    return {
        "connected": connected,
        "tenant_id": cfg.get("tenant_id"),
        "has_refresh_token": bool(cfg.get("refresh_token")),
    }


# ── OAuth URL ─────────────────────────────────────────────────────────────────

@router.get("/oauth-url")
async def teams_direct_oauth_url(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    cfg = await _get_teams_cfg(db)
    client_id = cfg.get("client_id")
    if not client_id:
        raise HTTPException(400, "teamsDirectCfg.clientId not configured in admin settings")

    tenant = cfg.get("tenant_id", "common")
    redirect = str(request.base_url).rstrip("/") + "/api/v1/teams-direct/oauth-callback"
    url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect}"
        f"&scope={SCOPES.replace(' ', '%20')}"
        f"&response_mode=query"
    )
    return {"url": url}


# ── OAuth Callback ────────────────────────────────────────────────────────────

@router.get("/oauth-callback")
async def teams_direct_oauth_callback(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(400, "Missing OAuth code")

    cfg = await _get_teams_cfg(db)
    tenant = cfg.get("tenant_id", "common")
    redirect = str(request.base_url).rstrip("/") + "/api/v1/teams-direct/oauth-callback"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "authorization_code",
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": redirect,
                "scope": SCOPES,
            },
        )

    if resp.status_code >= 400:
        raise HTTPException(502, f"Token exchange failed: {resp.text[:300]}")

    tokens = resp.json()
    now = datetime.utcnow()
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": {
            "teamsDirectCfg.accessToken": tokens.get("access_token", ""),
            "teamsDirectCfg.refreshToken": tokens.get("refresh_token", ""),
            "teamsDirectCfg.tokenUpdatedAt": now,
            "updated_at": now,
        }},
        upsert=True,
    )
    return {"success": True, "message": "Teams Direct connected successfully."}


# ── Send Direct Message ───────────────────────────────────────────────────────

class TeamsSendDirectRequest(BaseModel):
    trainer_name: str = ""
    trainer_email: str = ""
    message: str
    requirement_id: Optional[str] = ""
    technology: Optional[str] = ""


@router.post("/send")
async def send_teams_direct(
    payload: TeamsSendDirectRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cfg = await _get_teams_cfg(db)
    access_token = cfg.get("access_token", "")
    if not access_token:
        raise HTTPException(503, "Teams Direct not configured. Connect via /oauth-url first.")

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    # 1. Resolve trainer's MS user ID from their email
    trainer_email = payload.trainer_email
    if not trainer_email:
        raise HTTPException(400, "trainer_email is required")

    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # Create or get 1:1 chat
        chat_resp = await client.post(
            f"{GRAPH_API_BASE}/chats",
            json={
                "chatType": "oneOnOne",
                "members": [
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{trainer_email}",
                    }
                ],
            },
        )
        if chat_resp.status_code >= 400:
            raise HTTPException(502, f"Chat creation failed: {chat_resp.text[:200]}")

        chat_id = chat_resp.json().get("id", "")
        if not chat_id:
            raise HTTPException(502, "Could not obtain Teams chat ID")

        # Send message
        msg_resp = await client.post(
            f"{GRAPH_API_BASE}/chats/{chat_id}/messages",
            json={"body": {"contentType": "text", "content": payload.message}},
        )
        if msg_resp.status_code >= 400:
            raise HTTPException(502, f"Message send failed: {msg_resp.text[:200]}")

        msg_id = msg_resp.json().get("id", "")

    now = datetime.utcnow()
    log_id = f"TDM-{uuid.uuid4().hex[:10].upper()}"
    await db["teams_logs"].insert_one({
        "teams_id": log_id,
        "event_type": "direct_message",
        "provider": "teams_direct",
        "trainer_email": trainer_email,
        "trainer_name": payload.trainer_name,
        "requirement_id": payload.requirement_id,
        "technology": payload.technology,
        "message": payload.message,
        "chat_id": chat_id,
        "ms_message_id": msg_id,
        "status": "sent",
        "sent_at": now,
        "created_at": now,
        "updated_at": now,
    })
    return {"success": True, "teams_id": log_id, "chat_id": chat_id, "message_id": msg_id}
