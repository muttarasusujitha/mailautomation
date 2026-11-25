import html
import os
import time
import uuid
from typing import Any, Dict
from urllib.parse import quote

import httpx

from config import get_settings
from utils.time_utils import utc_now


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _is_placeholder_value(value: Any) -> bool:
    clean = _clean(value).lower()
    return (
        not clean
        or clean.startswith("your_")
        or clean.startswith("your.")
        or clean.startswith("your-")
        or clean.startswith("enter_")
        or clean in {"placeholder", "changeme", "change_me", "your-client-id", "your-client-secret"}
    )


def _config_value(cfg: Dict[str, Any], key: str, env_name: str = "", default: str = "") -> str:
    cfg_value = _clean(cfg.get(key))
    if cfg_value and not _is_placeholder_value(cfg_value):
        return cfg_value
    env_value = ""
    if env_name:
        env_value = _clean(getattr(get_settings(), env_name.lower(), "") or os.getenv(env_name, ""))
    if env_value and not _is_placeholder_value(env_value):
        return env_value
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _trainer_teams_identity(trainer: Dict[str, Any], fallback: str = "") -> str:
    return (
        _clean(trainer.get("teams_email"))
        or _clean(trainer.get("microsoft_teams_email"))
        or _clean(trainer.get("teams_upn"))
        or _clean(trainer.get("email"))
        or _clean(trainer.get("trainer_email"))
        or _clean(fallback)
    )


def _same_identity(left: str, right: str) -> bool:
    return _clean(left).lower() == _clean(right).lower()


def _graph_user_bind_url(user_identity: str) -> str:
    encoded_identity = quote(_clean(user_identity), safe="")
    return f"{GRAPH_BASE}/users/{encoded_identity}"


async def get_teams_direct_config(db) -> Dict[str, Any]:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "teamsDirectCfg": 1},
    )
    cfg = (settings_doc or {}).get("teamsDirectCfg") or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "tenantId": _config_value(cfg, "tenantId", "MICROSOFT_TENANT_ID", "common"),
        "clientId": _config_value(cfg, "clientId", "MICROSOFT_CLIENT_ID"),
        "clientSecret": _config_value(cfg, "clientSecret", "MICROSOFT_CLIENT_SECRET"),
        "refreshToken": _config_value(cfg, "refreshToken", "MICROSOFT_REFRESH_TOKEN"),
        "accessToken": _config_value(cfg, "accessToken", "MICROSOFT_ACCESS_TOKEN"),
        "expiresAt": _safe_int(cfg.get("expiresAt")),
        "senderUser": _config_value(cfg, "senderUser", "MICROSOFT_SENDER_USER"),
        "redirectUri": _config_value(
            cfg,
            "redirectUri",
            "MICROSOFT_REDIRECT_URI",
            "http://localhost:8000/api/teams-direct/oauth-callback",
        ),
    }


def microsoft_oauth_url(config: Dict[str, Any]) -> str:
    tenant_id = config.get("tenantId") or "common"
    scopes = "offline_access User.Read Chat.Create ChatMessage.Send"
    from urllib.parse import urlencode

    return (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?"
        + urlencode({
            "client_id": config.get("clientId", ""),
            "response_type": "code",
            "redirect_uri": config.get("redirectUri", ""),
            "response_mode": "query",
            "scope": scopes,
            "prompt": "consent",
        })
    )


async def exchange_microsoft_code(db, code: str) -> Dict[str, Any]:
    cfg = await get_teams_direct_config(db)
    missing = [
        name for name in ("tenantId", "clientId", "clientSecret", "redirectUri")
        if not cfg.get(name)
    ]
    if missing:
        return {"success": False, "error": f"Missing Microsoft Graph settings: {', '.join(missing)}"}

    data = {
        "client_id": cfg["clientId"],
        "client_secret": cfg["clientSecret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirectUri"],
        "scope": "offline_access User.Read Chat.Create ChatMessage.Send",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL_TEMPLATE.format(tenant_id=cfg["tenantId"]), data=data)
    payload = response.json()
    if response.status_code >= 400:
        return {"success": False, "error": payload.get("error_description") or payload.get("error") or response.text, "payload": payload}

    access_token = payload.get("access_token", "")
    if not access_token:
        pretty_payload = payload if isinstance(payload, dict) else {"raw": str(payload)}
        return {
            "success": False,
            "error": "Microsoft did not return an access token.",
            "payload": pretty_payload,
        }

    expires_at = int(time.time()) + int(payload.get("expires_in") or 3600) - 120
    token_fields = {
        "teamsDirectCfg.accessToken": access_token,
        "teamsDirectCfg.refreshToken": payload.get("refresh_token") or cfg.get("refreshToken", ""),
        "teamsDirectCfg.expiresAt": expires_at,
        "teamsDirectCfg.enabled": True,
        "updated_at": utc_now(),
    }
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": token_fields},
        upsert=True,
    )
    return {"success": True, "expires_at": expires_at}


async def _refresh_access_token(db, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not cfg.get("refreshToken"):
        return {"success": False, "error": "Microsoft refresh token not connected"}
    missing = [name for name in ("tenantId", "clientId", "clientSecret") if not cfg.get(name)]
    if missing:
        return {"success": False, "error": f"Missing Microsoft Graph settings: {', '.join(missing)}"}

    data = {
        "client_id": cfg["clientId"],
        "client_secret": cfg["clientSecret"],
        "grant_type": "refresh_token",
        "refresh_token": cfg["refreshToken"],
        "scope": "offline_access User.Read Chat.Create ChatMessage.Send",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL_TEMPLATE.format(tenant_id=cfg["tenantId"]), data=data)
    payload = response.json()
    if response.status_code >= 400:
        return {"success": False, "error": payload.get("error_description") or payload.get("error") or response.text, "payload": payload}

    access_token = payload.get("access_token", "")
    if not access_token:
        pretty_payload = payload if isinstance(payload, dict) else {"raw": str(payload)}
        return {
            "success": False,
            "error": "Microsoft refresh returned no access token.",
            "payload": pretty_payload,
        }

    expires_at = int(time.time()) + int(payload.get("expires_in") or 3600) - 120
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": {
            "teamsDirectCfg.accessToken": access_token,
            "teamsDirectCfg.refreshToken": payload.get("refresh_token") or cfg.get("refreshToken", ""),
            "teamsDirectCfg.expiresAt": expires_at,
            "updated_at": utc_now(),
        }},
        upsert=True,
    )
    return {"success": True, "access_token": access_token, "expires_at": expires_at}


async def _access_token(db) -> Dict[str, Any]:
    cfg = await get_teams_direct_config(db)
    if not cfg.get("enabled"):
        return {"success": False, "status": "skipped", "error": "Teams direct chat is disabled"}
    expires_at = _safe_int(cfg.get("expiresAt"))
    has_access_token = bool(cfg.get("accessToken"))
    has_refresh_token = bool(cfg.get("refreshToken"))
    if has_access_token and expires_at > int(time.time()) + 60:
        return {"success": True, "access_token": cfg["accessToken"], "config": cfg}
    if not has_refresh_token:
        if has_access_token:
            error = "Teams Direct access token expired and no refresh token is connected. Reconnect Microsoft Teams Direct Chat."
        else:
            error = "Teams Direct is not connected. Click Connect Direct Chat to create a Microsoft Graph access token."
        return {"success": False, "status": "skipped", "error": error, "config": cfg}
    refreshed = await _refresh_access_token(db, cfg)
    if not refreshed.get("success"):
        # Retry once for transient network/auth errors
        retried = await _refresh_access_token(db, cfg)
        if retried.get("success"):
            refreshed = retried
        else:
            # Include the payload/error for easier debugging in logs/UI
            error_payload = retried.get("payload") or retried.get("error") or refreshed.get("payload")
            return {**retried, "status": "skipped", "config": cfg, "debug_payload": error_payload}
    if not refreshed.get("access_token"):
        return {"success": False, "status": "skipped", "error": "Missing access token after refresh.", "config": cfg, "debug_payload": refreshed.get("payload")}
    return {"success": True, "access_token": refreshed["access_token"], "config": cfg}


async def _graph_get_me(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{GRAPH_BASE}/me?$select=id,userPrincipalName,mail,displayName",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(payload.get("error", {}).get("message") or response.text)
    return payload


async def _find_existing_one_on_one_chat(access_token: str, sender_upn: str, recipient_upn: str) -> str:
    """Return the chat-id of the existing 1-on-1 chat between sender and recipient.

    The Graph API returns HTTP 201 with an existing chat-id when you POST
    /chats with the same pair of members — effectively an upsert — so a
    separate lookup is only needed as a belt-and-suspenders optimisation to
    avoid the write round-trip on repeat messages.

    Strategy:
      1. GET /me/chats?$filter=chatType eq 'oneOnOne'&$expand=members
         and scan for a chat whose members contain recipient_upn.
      2. If found, return it.  If not (new conversation or API paging
         hasn't surfaced it), fall through — the caller will POST /chats
         which safely returns the existing chat-id via Graph's upsert
         behaviour.
    """
    recipient_lower = _clean(recipient_upn).lower()
    url = (
        f"{GRAPH_BASE}/me/chats"
        "?$filter=chatType eq 'oneOnOne'"
        "&$expand=members($select=userId,email)"
        "&$top=50"
        "&$select=id,chatType"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            # Non-fatal: fall through to create path.
            return ""
        data = response.json()
        for chat in data.get("value") or []:
            for member in chat.get("members") or []:
                member_email = _clean(member.get("email", "")).lower()
                member_user_id = _clean(member.get("userId", "")).lower()
                if member_email == recipient_lower or member_user_id == recipient_lower:
                    return chat.get("id") or ""
    except Exception:
        pass  # Non-fatal: fall through to create path.
    return ""


async def _get_or_create_one_on_one_chat(access_token: str, sender_upn: str, recipient_upn: str) -> str:
    """Return an existing 1-on-1 chat-id or create a new one.

    Always tries to find an existing chat first so that the same trainer
    is not scattered across multiple separate chats when contacted repeatedly.
    """
    existing = await _find_existing_one_on_one_chat(access_token, sender_upn, recipient_upn)
    if existing:
        return existing
    # Either no existing chat was found or the lookup failed gracefully.
    # POST /chats — Graph API performs an upsert: if the pair already has
    # a chat it returns the existing chat-id (HTTP 200) rather than
    # creating a duplicate (HTTP 201).
    return await _create_one_on_one_chat(access_token, sender_upn, recipient_upn)


async def _create_one_on_one_chat(access_token: str, sender_upn: str, recipient_upn: str) -> str:
    members = [
        {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": ["owner"],
            "user@odata.bind": _graph_user_bind_url(sender_upn),
        },
        {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": ["owner"],
            "user@odata.bind": _graph_user_bind_url(recipient_upn),
        },
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{GRAPH_BASE}/chats",
            json={"chatType": "oneOnOne", "members": members},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
    payload = response.json()
    if response.status_code not in {200, 201, 202}:
        raise RuntimeError(payload.get("error", {}).get("message") or response.text)
    return payload.get("id") or payload.get("chatId") or ""


async def _send_chat_message(access_token: str, chat_id: str, body: str) -> Dict[str, Any]:
    content = html.escape(body).replace("\n", "<br>")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{GRAPH_BASE}/chats/{chat_id}/messages",
            json={"body": {"contentType": "html", "content": content}},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(payload.get("error", {}).get("message") or response.text)
    return payload


async def send_trainer_teams_direct_message(
    db,
    *,
    trainer: Dict[str, Any],
    subject: str,
    body: str,
    requirement_id: str = "",
    mail_type: str = "",
    email_id: str = "",
) -> Dict[str, Any]:
    teams_email = _trainer_teams_identity(trainer)
    if not teams_email:
        return {"success": False, "status": "skipped", "error": "Trainer Teams email not found"}

    log_doc = {
        "teams_direct_id": f"TD-{uuid.uuid4().hex[:10].upper()}",
        "provider": "microsoft_graph",
        "direction": "outbound",
        "status": "queued",
        "trainer_id": trainer.get("trainer_id", ""),
        "trainer_name": trainer.get("name") or trainer.get("trainer_name") or "",
        "teams_email": teams_email,
        "requirement_id": requirement_id,
        "mail_type": mail_type,
        "email_id": email_id,
        "subject": subject,
        "body": body,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await db["teams_direct_logs"].insert_one(log_doc)

    token_result = await _access_token(db)
    if not token_result.get("success") or not token_result.get("access_token"):
        error_message = token_result.get("error") or "Missing Microsoft Graph access token"
        await db["teams_direct_logs"].update_one(
            {"teams_direct_id": log_doc["teams_direct_id"]},
            {"$set": {
                "status": token_result.get("status", "failed"),
                "error_message": error_message,
                "updated_at": utc_now(),
            }},
        )
        return {
            "success": False,
            "status": token_result.get("status", "skipped"),
            "error": error_message,
            "teams_direct_id": log_doc["teams_direct_id"],
            "teams_email": teams_email,
        }

    access_token = token_result["access_token"]
    try:
        me = await _graph_get_me(access_token)
        sender_upn = token_result.get("config", {}).get("senderUser") or me.get("userPrincipalName") or me.get("mail")
        if not sender_upn:
            raise RuntimeError("Microsoft sender user not found")
        if (
            _same_identity(sender_upn, teams_email)
            or _same_identity(me.get("userPrincipalName"), teams_email)
            or _same_identity(me.get("mail"), teams_email)
        ):
            raise RuntimeError(
                "Teams Direct Chat recipient cannot be the same as the sender. "
                "Test with another Teams user or guest account."
            )
        chat_id = await _get_or_create_one_on_one_chat(access_token, sender_upn, teams_email)
        message_body = f"Subject: {subject}\n\n{body}" if subject else body
        message = await _send_chat_message(access_token, chat_id, message_body)
        await db["teams_direct_logs"].update_one(
            {"teams_direct_id": log_doc["teams_direct_id"]},
            {"$set": {
                "status": "sent",
                "chat_id": chat_id,
                "message_id": message.get("id", ""),
                "sent_at": utc_now(),
                "updated_at": utc_now(),
            }},
        )
        return {
            "success": True,
            "status": "sent",
            "teams_direct_id": log_doc["teams_direct_id"],
            "teams_email": teams_email,
            "chat_id": chat_id,
            "message_id": message.get("id", ""),
        }
    except Exception as exc:
        await db["teams_direct_logs"].update_one(
            {"teams_direct_id": log_doc["teams_direct_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": utc_now()}},
        )
        return {
            "success": False,
            "status": "failed",
            "error": str(exc),
            "teams_direct_id": log_doc["teams_direct_id"],
            "teams_email": teams_email,
        }
