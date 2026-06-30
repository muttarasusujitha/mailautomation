"""Gmail OAuth2, sync, push-notification webhook routes."""
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

# ─── helpers ──────────────────────────────────────────────────────────────────

def _token_path() -> str:
    p = settings.GOOGLE_TOKEN_FILE or "config/token.json"
    if os.path.isabs(p):
        return p
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", p)


def _load_creds():
    tp = _token_path()
    if not os.path.exists(tp):
        return None, "token.json not found"
    try:
        from google.auth.transport.requests import Request as GReq
        from google.oauth2.credentials import Credentials
        scopes = ["https://www.googleapis.com/auth/gmail.modify",
                  "https://www.googleapis.com/auth/gmail.send",
                  "https://www.googleapis.com/auth/calendar"]
        creds = Credentials.from_authorized_user_file(tp, scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GReq())
            with open(tp, "w") as fh:
                fh.write(creds.to_json())
        return creds, ""
    except Exception as exc:
        return None, str(exc)


async def _gmail_service():
    try:
        from googleapiclient.discovery import build
        creds, err = _load_creds()
        if not creds:
            return None, err
        return build("gmail", "v1", credentials=creds), ""
    except Exception as exc:
        return None, str(exc)


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/auth-status")
async def gmail_auth_status(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Check whether Gmail OAuth token is present and valid."""
    creds, err = _load_creds()
    if not creds or not creds.valid:
        return {"connected": False, "error": err or "Token invalid or expired"}
    return {
        "connected": True,
        "email": getattr(creds, "_service_account_email", None) or settings.GMAIL_USER,
        "scopes": list(getattr(creds, "scopes", []) or []),
    }


@router.get("/oauth-url")
async def get_gmail_oauth_url(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Generate Gmail OAuth2 consent URL."""
    try:
        from google_auth_oauthlib.flow import Flow
        scopes = ["https://www.googleapis.com/auth/gmail.modify",
                  "https://www.googleapis.com/auth/gmail.send",
                  "https://www.googleapis.com/auth/calendar"]
        redirect_uri = str(request.base_url).rstrip("/") + "/api/v1/gmail/oauth-callback"
        flow = Flow.from_client_config(
            {"web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }},
            scopes=scopes,
        )
        flow.redirect_uri = redirect_uri
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        return {"url": auth_url}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/oauth-callback")
async def gmail_oauth_callback(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Exchange OAuth code for tokens and persist token.json."""
    body = await request.json()
    code = body.get("code") or request.query_params.get("code") or ""
    if not code:
        raise HTTPException(400, "code is required")
    try:
        from google_auth_oauthlib.flow import Flow
        scopes = ["https://www.googleapis.com/auth/gmail.modify",
                  "https://www.googleapis.com/auth/gmail.send",
                  "https://www.googleapis.com/auth/calendar"]
        redirect_uri = body.get("redirect_uri") or str(request.base_url).rstrip("/") + "/api/v1/gmail/oauth-callback"
        flow = Flow.from_client_config(
            {"web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }},
            scopes=scopes,
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        tp = _token_path()
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as fh:
            fh.write(flow.credentials.to_json())
        return {"success": True, "message": "Gmail connected successfully."}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/disconnect")
async def gmail_disconnect(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Remove stored OAuth token — disconnects Gmail."""
    tp = _token_path()
    if os.path.exists(tp):
        os.remove(tp)
    return {"success": True, "message": "Gmail disconnected."}


@router.post("/sync-now")
async def gmail_sync_now(background_tasks: BackgroundTasks, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Trigger an immediate inbox sync (delegates to inbox poll)."""
    from app.routes.inbox import _poll_and_store
    background_tasks.add_task(_poll_and_store, db, since_days=3, max_messages=100)
    return {"success": True, "message": "Gmail sync triggered in background."}


@router.post("/renew-watch")
async def renew_gmail_watch(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Re-register Gmail push-notification watch via Cloud Pub/Sub."""
    svc, err = await _gmail_service()
    if not svc:
        raise HTTPException(503, f"Gmail not connected: {err}")
    try:
        topic = os.getenv("GMAIL_PUBSUB_TOPIC", "")
        if not topic:
            return {"success": False, "message": "GMAIL_PUBSUB_TOPIC not configured"}
        resp = svc.users().watch(
            userId="me",
            body={"topicName": topic, "labelIds": ["INBOX"]},
        ).execute()
        await db["gmail_watch"].update_one(
            {"user": "default"},
            {"$set": {**resp, "renewed_at": datetime.utcnow()}},
            upsert=True,
        )
        return {"success": True, "watch": resp}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/webhook")
async def gmail_push_webhook(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Receive Gmail Pub/Sub push notification and trigger sync."""
    try:
        payload = await request.json()
        logger.info("Gmail push webhook received: %s", str(payload)[:200])
        # The message contains base64-encoded history data
        from app.routes.inbox import _poll_and_store
        import asyncio
        asyncio.create_task(_poll_and_store(db, since_days=1, max_messages=50))
    except Exception as exc:
        logger.warning("Gmail webhook parse error: %s", exc)
    return Response(status_code=204)
