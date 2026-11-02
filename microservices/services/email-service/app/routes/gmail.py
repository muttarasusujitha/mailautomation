"""Gmail OAuth2, sync, push-notification webhook routes."""
import logging
import os
import uuid
import json
import base64
import hashlib
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]
USER_GMAIL_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.send",
]
OAUTH_STATE_TTL_MINUTES = 20
GMAIL_SYNC_IN_PROGRESS = False
GMAIL_SYNC_LAST_RESULT: Dict[str, Any] = {}


def _default_oauth_redirect(request: Request) -> str:
    origin = request.headers.get("origin", "").strip()
    origin_host = urlsplit(origin).hostname.lower() if origin else ""
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    host = (origin_host or forwarded_host or request.headers.get("host", "")).split(":", 1)[0].lower()
    if origin_host in {"localhost", "127.0.0.1", "::1"} or host in {"localhost", "127.0.0.1", "::1"}:
        local_redirect = settings.GOOGLE_REDIRECT_URI_LOCAL.strip()
        if local_redirect:
            return local_redirect

    configured_redirect = settings.GOOGLE_REDIRECT_URI.strip()
    if configured_redirect:
        return configured_redirect

    frontend_url = settings.FRONTEND_URL.strip().rstrip("/")
    if frontend_url:
        return f"{frontend_url}/auth/callback"

    return str(request.base_url).rstrip("/") + "/api/v1/gmail/oauth-callback"


def _configured_oauth_redirects() -> set[str]:
    return {
        value
        for value in (
            settings.GOOGLE_REDIRECT_URI.strip(),
            settings.GOOGLE_REDIRECT_URI_LOCAL.strip(),
        )
        if value
    }


def _frontend_redirect_url(request: Request) -> str:
    configured_url = settings.FRONTEND_URL.strip().rstrip("/")
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and configured_url.startswith(
        ("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1")
    ):
        forwarded_proto = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0].strip()
        return f"{forwarded_proto}://{host}"
    return configured_url or "http://localhost:5174"


def _oauth_client_config(redirect_uri: str) -> Dict[str, Any]:
    client_id = settings.GOOGLE_CLIENT_ID.strip()
    client_secret = settings.GOOGLE_CLIENT_SECRET.strip()

    return {"web": {
        "client_id": client_id,
        "client_secret": client_secret,
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


def _authenticated_user_id(request: Request) -> str:
    user_id = str(request.headers.get("x-authenticated-user-id") or "").strip()
    if not user_id:
        raise HTTPException(401, "Sign in again to manage your Gmail connection")
    return user_id


def _user_token_path(user_id: str) -> str:
    # Never place raw user identifiers in paths; the directory is isolated from
    # the shared company mailbox token and lives on the existing OAuth volume.
    safe_id = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return os.path.join(os.path.dirname(_token_path()), "users", f"{safe_id}.json")


def _save_credentials(token_path: str, credentials) -> None:
    directory = os.path.dirname(token_path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass


def _load_user_creds(user_id: str, refresh_expired: bool = True):
    token_path = _user_token_path(user_id)
    if not os.path.exists(token_path):
        return None, "Gmail is not connected for this account"
    try:
        from google.auth.transport.requests import Request as GReq
        from google.oauth2.credentials import Credentials
        with open(token_path, "r", encoding="utf-8") as token_file:
            token_info = json.load(token_file)
        credentials = Credentials.from_authorized_user_info(
            token_info,
            scopes=token_info.get("scopes"),
        )
        if refresh_expired and credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(GReq())
            _save_credentials(token_path, credentials)
        return credentials, ""
    except Exception as exc:
        return None, str(exc)


async def _user_google_email(credentials) -> str:
    if not credentials or not credentials.token:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
        if response.status_code != 200:
            return ""
        return str(response.json().get("email") or "").strip()
    except Exception:
        return ""


def _user_token_status(user_id: str) -> Dict[str, Any]:
    token_path = _user_token_path(user_id)
    if not os.path.exists(token_path):
        return {"exists": False, "valid": False, "connected": False, "error": "Gmail not connected"}
    try:
        with open(token_path, "r", encoding="utf-8") as token_file:
            token = json.load(token_file)
        expiry_raw = str(token.get("expiry") or "").strip()
        expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00")) if expiry_raw else None
        expired = expiry <= datetime.now(timezone.utc) if expiry else True
        has_refresh_token = bool(token.get("refresh_token"))
        return {
            "exists": True,
            "valid": not expired,
            "connected": (not expired) or has_refresh_token,
            "expired": expired,
            "has_refresh_token": has_refresh_token,
            "scopes": list(token.get("scopes") or []),
        }
    except Exception as exc:
        return {"exists": True, "valid": False, "connected": False, "error": str(exc)}


def _load_creds(refresh_expired: bool = True):
    tp = _token_path()
    if not os.path.exists(tp):
        return None, "token.json not found"
    try:
        from google.auth.transport.requests import Request as GReq
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(tp)
        if refresh_expired and creds and creds.expired and creds.refresh_token:
            refresh_request = GReq()
            creds.refresh(lambda *args, **kwargs: refresh_request(*args, timeout=10, **kwargs))
            with open(tp, "w") as fh:
                fh.write(creds.to_json())
        return creds, ""
    except Exception as exc:
        return None, str(exc)


def _read_token_status() -> Dict[str, Any]:
    tp = _token_path()
    if not os.path.exists(tp):
        return {"exists": False, "valid": False, "error": "token.json not found"}
    try:
        with open(tp, "r", encoding="utf-8") as fh:
            token = json.load(fh)
        expiry_raw = str(token.get("expiry") or "").strip()
        expired = True
        if expiry_raw:
            expiry = datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
            expired = expiry <= datetime.now(timezone.utc)
        scopes = list(token.get("scopes") or [])
        has_refresh_token = bool(token.get("refresh_token"))
        return {
            "exists": True,
            "valid": not expired,
            "connected": (not expired) or has_refresh_token,
            "expired": expired,
            "expiry": expiry_raw,
            "has_refresh_token": has_refresh_token,
            "scopes": scopes,
        }
    except Exception as exc:
        return {"exists": True, "valid": False, "error": str(exc)}


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
    token_status = _read_token_status()
    connected = bool(token_status.get("connected"))
    if connected and token_status.get("expired"):
        creds, refresh_error = _load_creds()
        if not creds:
            return {
                "connected": False,
                "valid": False,
                "token_valid": False,
                "calendar_connected": False,
                "error": "Gmail authorization expired or was revoked. Reconnect the client Gmail account.",
                "expired": True,
                "expiry": token_status.get("expiry", ""),
            }
        token_status = _read_token_status()
        connected = bool(token_status.get("connected"))
    if not connected:
        return {
            "connected": False,
            "valid": False,
            "token_valid": False,
            "calendar_connected": False,
            "error": token_status.get("error") or "Token invalid or expired",
            "expired": bool(token_status.get("expired")),
            "expiry": token_status.get("expiry", ""),
        }
    scopes = list(token_status.get("scopes") or [])
    email = settings.GMAIL_USER
    calendar_connected = any("/auth/calendar" in str(scope) for scope in scopes)
    return {
        "connected": True,
        "valid": bool(token_status.get("valid")),
        "token_valid": bool(token_status.get("valid")),
        "expired": bool(token_status.get("expired")),
        "expiry": token_status.get("expiry", ""),
        "email": email,
        "gmail_user": email,
        "configured_user": email,
        "calendar_connected": calendar_connected,
        "calendar_ready": calendar_connected,
        "scopes": scopes,
    }


@router.get("/me/auth-status")
async def my_gmail_auth_status(request: Request):
    """Return only the signed-in user's personal Gmail connection status."""
    user_id = _authenticated_user_id(request)
    token_status = _user_token_status(user_id)
    if not token_status.get("connected"):
        return {
            "connected": False,
            "valid": False,
            "token_valid": False,
            "email": "",
            "error": token_status.get("error") or "Gmail is not connected for this account",
        }
    credentials, error = _load_user_creds(user_id)
    if not credentials:
        return {"connected": False, "valid": False, "token_valid": False, "email": "", "error": error}
    email = await _user_google_email(credentials)
    if not email:
        return {
            "connected": False,
            "valid": False,
            "token_valid": False,
            "email": "",
            "error": "Google account identity could not be verified. Reconnect Gmail.",
        }
    return {
        "connected": True,
        "valid": bool(token_status.get("valid")),
        "token_valid": bool(token_status.get("valid")),
        "email": email,
        "gmail_user": email,
        "scopes": list(token_status.get("scopes") or []),
        "connection_type": "personal",
    }


@router.get("/me/oauth-url")
async def my_gmail_oauth_url(
    request: Request,
    redirect_uri: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Start a least-privilege, user-owned Gmail connection."""
    try:
        user_id = _authenticated_user_id(request)
        from google_auth_oauthlib.flow import Flow
        _ensure_oauth_configured()
        requested_redirect = (redirect_uri or "").strip()
        if requested_redirect:
            if requested_redirect not in _configured_oauth_redirects():
                raise HTTPException(400, "The requested Google OAuth redirect URI is not configured")
            callback_uri = requested_redirect
        else:
            callback_uri = _default_oauth_redirect(request)
        flow = Flow.from_client_config(
            _oauth_client_config(callback_uri),
            scopes=USER_GMAIL_SCOPES,
            autogenerate_code_verifier=True,
        )
        flow.redirect_uri = callback_uri
        auth_url, state = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="false",
        )
        code_verifier = getattr(flow, "code_verifier", None)
        if not code_verifier:
            raise HTTPException(500, "Google OAuth PKCE verifier could not be generated")
        now = datetime.utcnow()
        await db["gmail_oauth_states"].update_one(
            {"state": state},
            {"$set": {
                "state": state,
                "code_verifier": code_verifier,
                "redirect_uri": callback_uri,
                "user_id": user_id,
                "account_scope": "personal",
                "created_at": now,
                "expires_at": now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
            }},
            upsert=True,
        )
        return {
            "success": True,
            "url": auth_url,
            "auth_url": auth_url,
            "state": state,
            "code_verifier": code_verifier,
            "redirect_uri": callback_uri,
            "account_scope": "personal",
            "expires_in": OAUTH_STATE_TTL_MINUTES * 60,
        }
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, str(exc)) from exc


@router.post("/me/oauth-callback")
async def my_gmail_oauth_callback(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Complete the PKCE flow only for the user who started it."""
    user_id = _authenticated_user_id(request)
    body = await request.json()
    state = str(body.get("state") or "")
    oauth_state = await db["gmail_oauth_states"].find_one({"state": state}, {"_id": 0})
    if not oauth_state or oauth_state.get("account_scope") != "personal" or oauth_state.get("user_id") != user_id:
        raise HTTPException(403, "This Google authorization belongs to a different or expired session")
    return await _exchange_gmail_oauth_code(request, db, body)


@router.post("/me/disconnect")
async def my_gmail_disconnect(request: Request):
    """Disconnect only the signed-in user's Gmail token."""
    token_path = _user_token_path(_authenticated_user_id(request))
    if os.path.exists(token_path):
        os.remove(token_path)
    return {"success": True, "message": "Your Gmail connection was removed."}


@router.post("/me/test-send")
async def my_gmail_test_send(request: Request):
    """Send a fixed test message from the user's own Gmail address back to itself."""
    user_id = _authenticated_user_id(request)
    credentials, error = _load_user_creds(user_id)
    if not credentials:
        raise HTTPException(409, error or "Connect Gmail before sending a test message")
    email = await _user_google_email(credentials)
    if not email:
        raise HTTPException(409, "Reconnect Gmail so the connected account can be verified")
    try:
        from googleapiclient.discovery import build
        message = EmailMessage()
        message["To"] = email
        message["From"] = email
        message["Subject"] = "TrainerSync Gmail connection test"
        message.set_content(
            "This test message confirms that your personal Gmail connection can send mail from TrainerSync."
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "sent_to": email, "message_id": result.get("id", "")}
    except Exception as exc:
        logger.exception("Personal Gmail test-send failed")
        raise HTTPException(502, "Google could not send the test message. Reconnect and try again.") from exc


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
        # Select the callback from the browser environment. This lets one
        # Google OAuth client serve both the deployed app and local Vite.
        # The value is persisted with the OAuth state and reused by the
        # callback exchange, so both sides use the exact same URI.
        requested_redirect = (redirect_uri or "").strip()
        if requested_redirect:
            allowed_redirects = _configured_oauth_redirects()
            if requested_redirect not in allowed_redirects:
                raise HTTPException(400, "The requested Google OAuth redirect URI is not configured")
            redirect_uri = requested_redirect
        else:
            redirect_uri = _default_oauth_redirect(request)
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
            "redirect_uri": redirect_uri,
            "expires_in": OAUTH_STATE_TTL_MINUTES * 60,
        }
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, str(exc)) from exc


async def _exchange_gmail_oauth_code(
    request: Request,
    db: AsyncIOMotorDatabase,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Exchange OAuth code for tokens and persist token.json."""
    body = body or {}
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
            if not oauth_state:
                raise HTTPException(400, "Google authorization expired. Start the Gmail connection again.")
            expires_at = oauth_state.get("expires_at")
            if not expires_at or expires_at.replace(tzinfo=None) <= datetime.utcnow():
                await db["gmail_oauth_states"].delete_one({"state": state})
                raise HTTPException(400, "Google authorization expired. Start the Gmail connection again.")
            if oauth_state.get("redirect_uri"):
                redirect_uri = oauth_state["redirect_uri"]
        else:
            raise HTTPException(400, "Google authorization state is missing. Start the Gmail connection again.")
        personal_account = bool(oauth_state and oauth_state.get("account_scope") == "personal")
        if personal_account and not oauth_state.get("user_id"):
            raise HTTPException(403, "Google authorization is missing its account owner")
        if personal_account and not oauth_state.get("code_verifier"):
            raise HTTPException(400, "Google authorization expired. Start the Gmail connection again.")
        code_verifier = (oauth_state or {}).get("code_verifier") or fallback_code_verifier
        if not code_verifier:
            raise HTTPException(
                400,
                "Google OAuth session expired or is missing its code verifier. Start Gmail connection again.",
            )
        flow = Flow.from_client_config(
            _oauth_client_config(redirect_uri),
            scopes=USER_GMAIL_SCOPES if personal_account else GMAIL_SCOPES,
            state=state or None,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = redirect_uri
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            # Log full exception and surface a clearer HTTP error for diagnostics.
            logger.exception("Google token fetch failed during OAuth code exchange")
            # Avoid logging secrets; include the exception text for debugging.
            err_text = str(exc)
            raise HTTPException(502, f"Google token exchange failed: {err_text}") from exc
        if state:
            await db["gmail_oauth_states"].delete_one({"state": state})
        if personal_account:
            _save_credentials(_user_token_path(oauth_state["user_id"]), flow.credentials)
            return {"success": True, "message": "Your Gmail account connected successfully.", "account_scope": "personal"}
        tp = _token_path()
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w", encoding="utf-8") as fh:
            fh.write(flow.credentials.to_json())
        return {"success": True, "message": "Gmail connected successfully.", "account_scope": "company"}
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, str(exc)) from exc


@router.post("/oauth-callback")
async def gmail_oauth_callback(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    body = await request.json()
    return await _exchange_gmail_oauth_code(request, db, body)


@router.get("/oauth-callback")
async def gmail_oauth_callback_get(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    error = request.query_params.get("error")
    state = request.query_params.get("state", "")
    oauth_state = await db["gmail_oauth_states"].find_one({"state": state}, {"_id": 0}) if state else None
    callback_path = "/profile?gmail_connected=1" if oauth_state and oauth_state.get("account_scope") == "personal" else "/admin?gmail_connected=1"
    if error:
        frontend_url = _frontend_redirect_url(request)
        error_path = "/profile" if oauth_state and oauth_state.get("account_scope") == "personal" else "/admin"
        return RedirectResponse(f"{frontend_url}{error_path}?gmail_error={error}")
    code = request.query_params.get("code", "")
    if code and state:
        if not (oauth_state or {}).get("code_verifier"):
            # The browser still has the PKCE verifier from the start of this
            # same OAuth flow. Let the frontend submit it if the DB state was
            # lost (for example, after a service/database restart).
            callback_url = f"{_frontend_redirect_url(request)}/auth/callback?{urlencode({'code': code, 'state': state})}"
            return RedirectResponse(callback_url)
    await _exchange_gmail_oauth_code(request, db, {})
    frontend_url = _frontend_redirect_url(request)
    return RedirectResponse(f"{frontend_url}{callback_path}")


@router.post("/disconnect")
async def gmail_disconnect(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Remove stored OAuth token — disconnects Gmail."""
    tp = _token_path()
    if os.path.exists(tp):
        os.remove(tp)
    return {"success": True, "message": "Gmail disconnected."}


@router.post("/sync-now")
async def gmail_sync_now(
    background_tasks: BackgroundTasks,
    limit: int = Query(100, ge=1, le=500),
    since_days: int = Query(3, ge=1, le=30),
    search_query: str = Query(""),
    process: bool = Query(True),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Queue an immediate inbox sync; process=false stores requests for review without sending."""
    from app.routes.inbox import _poll_and_store, _process_pending_client_emails

    global GMAIL_SYNC_IN_PROGRESS, GMAIL_SYNC_LAST_RESULT

    gmail_service, gmail_error = await _gmail_service()
    if gmail_service is None:
        raise HTTPException(503, f"Client Gmail is not connected. Reconnect Gmail and retry. ({gmail_error})")

    if GMAIL_SYNC_IN_PROGRESS:
        return {
            "success": True,
            "queued": True,
            "running": True,
            "message": "Gmail sync is already running. The inbox will update shortly.",
            **GMAIL_SYNC_LAST_RESULT,
        }

    sync_id = f"GS-{uuid.uuid4().hex[:10].upper()}"
    GMAIL_SYNC_IN_PROGRESS = True
    GMAIL_SYNC_LAST_RESULT = {
        "sync_id": sync_id,
        "processed_count": 0,
        "stored": 0,
        "checked": 0,
        "requirements_created": 0,
        "auto_sent": 0,
        "failed": 0,
        "skipped": 0,
    }

    async def _run_sync() -> None:
        global GMAIL_SYNC_IN_PROGRESS, GMAIL_SYNC_LAST_RESULT
        try:
            stored = await _poll_and_store(
                db,
                since_days=since_days,
                max_messages=limit,
                search_query=search_query,
                process_client_requests=process,
            )
            pending = await _process_pending_client_emails(db, limit=limit) if process else {
                "checked": stored,
                "requirements_created": 0,
                "auto_sent": 0,
                "failed": 0,
                "skipped": 0,
            }
            GMAIL_SYNC_LAST_RESULT = {
                "sync_id": sync_id,
                "processed_count": stored,
                "stored": stored,
                **pending,
                "completed_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.exception("Gmail background sync failed")
            GMAIL_SYNC_LAST_RESULT = {
                "sync_id": sync_id,
                "processed_count": 0,
                "stored": 0,
                "checked": 0,
                "requirements_created": 0,
                "auto_sent": 0,
                "failed": 1,
                "skipped": 0,
                "error": str(exc),
                "completed_at": datetime.utcnow().isoformat(),
            }
        finally:
            GMAIL_SYNC_IN_PROGRESS = False

    background_tasks.add_task(_run_sync)
    return {
        "success": True,
        "queued": True,
        "running": True,
        "sync_id": sync_id,
        "message": "Gmail sync started. The inbox will update shortly.",
        "processed_count": 0,
        "stored": 0,
        "checked": 0,
        "requirements_created": 0,
        "auto_sent": 0,
        "failed": 0,
        "skipped": 0,
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
