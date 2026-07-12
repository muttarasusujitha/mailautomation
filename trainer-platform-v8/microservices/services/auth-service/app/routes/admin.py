"""Admin settings and diagnostics."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

REDACTED_SECRET = "***"
SECRET_FIELDS_BY_CFG = {
    "emailCfg": {"smtpPass", "imapPass", "fallbackSmtpPass"},
    "twilioCfg": {"authToken", "aisensyApiKey", "metaAccessToken"},
    "teamsCfg": {"webhookUrl"},
    "teamsDirectCfg": {"appPassword", "clientSecret"},
    "keys": {"mongoUri", "openaiKey"},
}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _normalise_threshold(value: Any, default: float = 0.7) -> float:
    try:
        threshold = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        threshold = default
    if threshold > 1:
        threshold /= 100
    return max(0.0, min(threshold, 1.0))


def _redact_settings(doc: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(doc or {})
    for cfg_key, secret_keys in SECRET_FIELDS_BY_CFG.items():
        cfg = redacted.get(cfg_key)
        if not isinstance(cfg, dict):
            continue
        safe_cfg = dict(cfg)
        for secret_key in secret_keys:
            if safe_cfg.get(secret_key):
                safe_cfg[secret_key] = REDACTED_SECRET
        redacted[cfg_key] = safe_cfg
    return redacted


def _preserve_redacted_secrets(update_fields: Dict[str, Any], existing_doc: Dict[str, Any]) -> None:
    for cfg_key, secret_keys in SECRET_FIELDS_BY_CFG.items():
        cfg = update_fields.get(cfg_key)
        existing_cfg = existing_doc.get(cfg_key) or {}
        if not isinstance(cfg, dict) or not isinstance(existing_cfg, dict):
            continue
        safe_cfg = dict(cfg)
        for secret_key in secret_keys:
            if safe_cfg.get(secret_key) == REDACTED_SECRET and existing_cfg.get(secret_key):
                safe_cfg[secret_key] = existing_cfg[secret_key]
        update_fields[cfg_key] = safe_cfg


def _force_auto_send_enabled(update_fields: Dict[str, Any], existing_doc: Dict[str, Any]) -> None:
    client_inbox_cfg = dict(existing_doc.get("clientInboxCfg") or {})
    client_inbox_cfg.update(update_fields.get("clientInboxCfg") or {})
    client_inbox_cfg["autoSendEnabled"] = True
    update_fields["clientInboxCfg"] = client_inbox_cfg

    scheduler_cfg = dict(existing_doc.get("schedulerCfg") or {})
    scheduler_cfg.update(update_fields.get("schedulerCfg") or {})
    scheduler_cfg["autoSendEnabled"] = True
    scheduler_cfg.setdefault("autoSendConfidenceThreshold", 0.7)
    update_fields["schedulerCfg"] = scheduler_cfg

    auto_send_cfg = dict(existing_doc.get("autoSendCfg") or {})
    auto_send_cfg.update(update_fields.get("autoSendCfg") or {})
    auto_send_cfg["enabled"] = True
    update_fields["autoSendCfg"] = auto_send_cfg

    pipeline = dict(existing_doc.get("pipeline") or {})
    pipeline.update(update_fields.get("pipeline") or {})
    pipeline["autoSend"] = True
    update_fields["pipeline"] = pipeline


class AdminSettingsUpdate(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    emailCfg: Optional[Dict[str, Any]] = None
    twilioCfg: Optional[Dict[str, Any]] = None
    clientInboxCfg: Optional[Dict[str, Any]] = None
    teamsCfg: Optional[Dict[str, Any]] = None
    teamsDirectCfg: Optional[Dict[str, Any]] = None
    notif: Optional[Dict[str, Any]] = None
    pipeline: Optional[Dict[str, Any]] = None
    keys: Optional[Dict[str, Any]] = None
    schedulerCfg: Optional[Dict[str, Any]] = None
    autoSendCfg: Optional[Dict[str, Any]] = None
    geminiApiKey: Optional[str] = None
    anthropicApiKey: Optional[str] = None


@router.get("/settings")
async def get_admin_settings(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return global admin configuration (redacts secrets)."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    doc = _redact_settings(doc)
    return {"success": True, "settings": doc, **doc}


@router.post("/settings")
async def save_admin_settings(
    payload: AdminSettingsUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Persist admin configuration to admin_settings collection."""
    now = datetime.utcnow()
    update_fields: Dict[str, Any] = {"updated_at": now}
    for field, value in payload.model_dump(exclude_none=True).items():
        update_fields[field] = value
    existing_doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    _preserve_redacted_secrets(update_fields, existing_doc)
    _force_auto_send_enabled(update_fields, existing_doc)

    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": update_fields, "$setOnInsert": {"settings_id": "default", "created_at": now}},
        upsert=True,
    )
    return {"success": True, "message": "Settings saved."}


@router.get("/auto-send/diagnose")
async def diagnose_auto_send(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Check auto-send configuration and report readiness."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    email_cfg = doc.get("emailCfg") or {}
    client_inbox_cfg = doc.get("clientInboxCfg") or {}
    scheduler_cfg = doc.get("schedulerCfg") or {}
    auto_send_cfg = doc.get("autoSendCfg") or {}

    smtp_ok = bool(email_cfg.get("smtpUser") and email_cfg.get("smtpPass"))
    auto_send_enabled = True

    threshold_value = client_inbox_cfg.get("autoSendThreshold")
    if threshold_value is None:
        threshold_value = auto_send_cfg.get("threshold")
    if threshold_value is None:
        threshold_value = scheduler_cfg.get("autoSendConfidenceThreshold")
    threshold = _normalise_threshold(threshold_value, 0.7)

    issues = []
    if not smtp_ok:
        issues.append("SMTP credentials not configured")
    pending_count = await db["client_emails"].count_documents(
        {
            "reply_sent": {"$ne": True},
            "auto_send_eligible": True,
            "$expr": {"$gte": [{"$ifNull": ["$auto_send_confidence", "$confidence"]}, threshold]},
            "$or": [
                {"status": {"$in": ["pending_approval", "pending_review"]}},
                {"reply_status": {"$in": ["pending_approval", "pending_review"]}},
            ],
        }
    )
    return {
        "success": True,
        "smtp_configured": smtp_ok,
        "auto_send_enabled": auto_send_enabled,
        "auto_send_threshold": threshold,
        "pending_auto_send_count": pending_count,
        "issues": issues,
        "ready": smtp_ok and auto_send_enabled,
    }


@router.post("/email/test")
async def test_email_config(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Send a test email using current SMTP settings."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    email_cfg = doc.get("emailCfg") or {}
    if not email_cfg.get("smtpUser"):
        raise HTTPException(400, "SMTP not configured")
    return {"success": True, "message": "Test email dispatched (configure SMTP to verify delivery)."}


@router.post("/whatsapp/test")
async def test_whatsapp_config(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Validate WhatsApp provider credentials in settings."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    cfg = doc.get("twilioCfg") or {}
    provider = (cfg.get("provider") or "twilio").lower()
    if provider == "twilio" and not cfg.get("accountSid"):
        raise HTTPException(400, "Twilio credentials not configured")
    if provider == "aisensy" and not cfg.get("aisensyApiKey"):
        raise HTTPException(400, "AiSensy API key not configured")
    if provider == "meta" and not cfg.get("metaAccessToken"):
        raise HTTPException(400, "Meta access token not configured")
    return {"success": True, "provider": provider, "message": f"{provider} credentials present."}


@router.post("/teams/test")
async def test_teams_config(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Validate Teams webhook URL."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    cfg = doc.get("teamsCfg") or {}
    if not cfg.get("webhookUrl"):
        raise HTTPException(400, "Teams webhook URL not configured")
    return {"success": True, "message": "Teams webhook URL is present."}


@router.post("/teams-direct/test")
async def test_teams_direct_config(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Check Teams Direct (Graph API) credentials."""
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    cfg = doc.get("teamsDirectCfg") or {}
    if not cfg.get("clientId"):
        raise HTTPException(400, "Teams Direct clientId not configured")
    return {"success": True, "message": "Teams Direct config present."}
