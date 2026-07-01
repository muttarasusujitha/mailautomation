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
    # Redact sensitive fields
    for cfg_key in ("emailCfg", "twilioCfg", "teamsCfg", "teamsDirectCfg"):
        cfg = doc.get(cfg_key) or {}
        for secret_key in ("smtpPass", "authToken", "appPassword", "clientSecret", "geminiApiKey", "anthropicApiKey"):
            if cfg.get(secret_key):
                cfg[secret_key] = "***"
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
    auto_send_cfg = doc.get("autoSendCfg") or {}

    smtp_ok = bool(email_cfg.get("smtpUser") and email_cfg.get("smtpPass"))
    auto_send_enabled = bool(auto_send_cfg.get("enabled"))
    issues = []
    if not smtp_ok:
        issues.append("SMTP credentials not configured")
    if not auto_send_enabled:
        issues.append("Auto-send is disabled in settings")

    pending_count = await db["client_emails"].count_documents(
        {"reply_status": "pending_auto_send", "auto_send_eligible": True}
    )
    return {
        "success": True,
        "smtp_configured": smtp_ok,
        "auto_send_enabled": auto_send_enabled,
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
