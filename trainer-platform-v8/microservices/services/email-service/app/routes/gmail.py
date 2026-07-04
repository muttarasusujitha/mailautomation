"""Gmail OAuth2, sync, push-notification webhook routes."""
import logging
import os
from datetime import datetime, timedelta
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

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]
OAUTH_STATE_TTL_MINUTES = 20


def _default_oauth_redirect(request: Request) -> str:
    configured_redirect = settings.GOOGLE_REDIRECT_URI.strip()
    if configured_redirect:
        return configured_redirect

    frontend_url = settings.FRONTEND_URL.strip().rstrip("/")
    if frontend_url:
        return f"{frontend_url}/auth/callback"

    return str(request.base_url).rstrip("/") + "/api/v1/gmail/oauth-callback"


def _oauth_client_config(redirect_uri: str) -> Dict[str, Any]:
    return {"web": {
        "client_id": settings.GOOGLE_CLIENT_ID.strip(),
        "client_secret": settings.GOOGLE_CLIENT_SECRET.strip(),
        "redirect_uris": [redirect_uri],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}


def _ensure_oauth_configured() -> None:
    missing = []
    if not settings.GOOGLE_CLIENT_ID.strip():
        missing.append("GOOGLE_CLIENT_ID")
    if not settings.GOOGLE_CLIENT_SECRET.strip():
        missing.append("GOOGLE_CLIENT_SECRET")
    if missing:
        raise HTTPException(
            400,
            f"Google OAuth is missing {', '.join(missing)} in microservices/.env",
        )

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
        creds = Credentials.from_authorized_user_file(tp, GMAIL_SCOPES)
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
        return {
            "connected": False,
            "valid": False,
            "token_valid": False,
            "calendar_connected": False,
            "error": err or "Token invalid or expired",
        }
    scopes = list(getattr(creds, "scopes", []) or [])
    email = getattr(creds, "_service_account_email", None) or settings.GMAIL_USER
    calendar_connected = any("/auth/calendar" in str(scope) for scope in scopes)
    return {
        "connected": True,
        "valid": True,
        "token_valid": True,
        "email": email,
        "gmail_user": email,
        "configured_user": email,
        "calendar_connected": calendar_connected,
        "calendar_ready": calendar_connected,
        "scopes": scopes,
    }


@router.get("/oauth-url")
async def get_gmail_oauth_url(
    request: Request,
    redirect_uri: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Generate Gmail OAuth2 consent URL."""
    try:
        from google_auth_oauthlib.flow import Flow
        _ensure_oauth_configured()
        redirect_uri = redirect_uri or request.query_params.get("redirect_uri") or _default_oauth_redirect(request)
        flow = Flow.from_client_config(
            _oauth_client_config(redirect_uri),
            scopes=GMAIL_SCOPES,
            autogenerate_code_verifier=True,
        )
        flow.redirect_uri = redirect_uri
        auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
        code_verifier = getattr(flow, "code_verifier", None)
        if not code_verifier:
            raise HTTPException(500, "Google OAuth PKCE verifier could not be generated")

        now = datetime.utcnow()
        await db["gmail_oauth_states"].update_one(
            {"state": state},
            {"$set": {
                "state": state,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "created_at": now,
                "expires_at": now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
            }},
            upsert=True,
        )
        return {
            "url": auth_url,
            "auth_url": auth_url,
            "state": state,
            "code_verifier": code_verifier,
            "expires_in": OAUTH_STATE_TTL_MINUTES * 60,
        }
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, str(exc)) from exc


@router.post("/oauth-callback")
async def gmail_oauth_callback(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Exchange OAuth code for tokens and persist token.json."""
    body = await request.json()
    code = body.get("code") or request.query_params.get("code") or ""
    state = body.get("state") or request.query_params.get("state") or ""
    fallback_code_verifier = body.get("code_verifier") or body.get("codeVerifier") or ""
    if not code:
        raise HTTPException(400, "code is required")
    try:
        from google_auth_oauthlib.flow import Flow
        _ensure_oauth_configured()
        redirect_uri = body.get("redirect_uri") or _default_oauth_redirect(request)
        oauth_state = None
        if state:
            oauth_state = await db["gmail_oauth_states"].find_one({"state": state}, {"_id": 0})
            if oauth_state and oauth_state.get("redirect_uri"):
                redirect_uri = oauth_state["redirect_uri"]
        code_verifier = (oauth_state or {}).get("code_verifier") or fallback_code_verifier
        if not code_verifier:
            raise HTTPException(
                400,
                "Google OAuth session expired or is missing its code verifier. Start Gmail connection again.",
            )
        flow = Flow.from_client_config(
            _oauth_client_config(redirect_uri),
            scopes=GMAIL_SCOPES,
            state=state or None,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        if state:
            await db["gmail_oauth_states"].delete_one({"state": state})
        tp = _token_path()
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as fh:
            fh.write(flow.credentials.to_json())
        return {"success": True, "message": "Gmail connected successfully."}
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, str(exc)) from exc


@router.post("/disconnect")
async def gmail_disconnect(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Remove stored OAuth token — disconnects Gmail."""
    tp = _token_path()
    if os.path.exists(tp):
        os.remove(tp)
    return {"success": True, "message": "Gmail disconnected."}


@router.post("/sync-now")
async def gmail_sync_now(
    limit: int = Query(100, ge=1, le=500),
    since_days: int = Query(3, ge=1, le=30),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Run an immediate inbox sync and return real processing counts."""
    from app.routes.inbox import _poll_and_store, _process_pending_client_emails

    stored = await _poll_and_store(db, since_days=since_days, max_messages=limit)
    pending = await _process_pending_client_emails(db, limit=limit)
    return {
        "success": True,
        "message": "Gmail sync completed.",
        "processed_count": stored,
        "stored": stored,
        **pending,
    }


@router.post("/renew-watch")
async def renew_gmail_watch(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Re-register Gmail push-notification watch via Cloud Pub/Sub."""
    svc, err = await _gmail_service()
    if not svc:
        raise HTTPException(503, f"Gmail not connected: {err}")
    try:
        topic = settings.GMAIL_PUBSUB_TOPIC.strip()
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
