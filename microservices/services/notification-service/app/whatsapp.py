"""WhatsApp messaging engine — supports Twilio, AiSensy, and Meta Cloud API."""
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
AISENSY_API_URL = "https://backend.aisensy.com/campaign/t1/api/v2"
META_GRAPH_API_BASE = "https://graph.facebook.com"

STAGE_LABELS = {
    "mail1": "Stage 1 - First outreach",
    "mail1_reminder": "Stage 1 - Follow-up reminder",
    "first": "Stage 1 - First outreach",
    "mail2": "Stage 2 - Details requested",
    "mail3": "Stage 3 - Interview slot booking",
    "mail4": "Stage 4 - Interview scheduled",
    "mail5_ok": "Stage 5 - Trainer selected",
    "mail5_no": "Stage 5 - Trainer rejected",
    "mail6_toc": "Stage 6 - ToC requested",
    "mail7_confirm": "Stage 7 - Training confirmed",
    "reply": "Trainer reply",
}


def stage_label(mail_type: str = "") -> str:
    return STAGE_LABELS.get(mail_type or "", mail_type or "Pipeline update")


def _plain_phone(number: Any, country_code: str = "+91") -> str:
    raw = str(number or "").strip().replace("whatsapp:", "")
    if raw.startswith("00"):
        raw = f"+{raw[2:]}"
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    country = re.sub(r"\D", "", country_code or "91") or "91"
    if country == "91":
        if len(digits) == 12 and digits.startswith(country):
            return f"+{digits}"
        if len(digits) == 10:
            return f"+{country}{digits}"
        if len(digits) > 10:
            return f"+{country}{digits[-10:]}"
    if raw.startswith("+"):
        return f"+{digits}"
    if digits.startswith(country):
        return f"+{digits}"
    return f"+{digits}"


def _wa_number(number: Any, country_code: str = "+91") -> str:
    plain = _plain_phone(number, country_code)
    return f"whatsapp:{plain}" if plain else ""


def _csv(value: Any) -> List[str]:
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


async def _get_config(db) -> Dict[str, Any]:
    doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0, "twilioCfg": 1}) or {}
    cfg = doc.get("twilioCfg") or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "provider": (cfg.get("provider") or settings.WHATSAPP_PROVIDER).strip().lower(),
        "accountSid": cfg.get("accountSid") or settings.TWILIO_ACCOUNT_SID,
        "authToken": cfg.get("authToken") or settings.TWILIO_AUTH_TOKEN,
        "fromWhatsAppNumber": cfg.get("fromWhatsAppNumber") or settings.TWILIO_WHATSAPP_FROM,
        "vendorWhatsAppNumber": cfg.get("vendorWhatsAppNumber") or settings.VENDOR_WHATSAPP_NUMBER,
        "defaultCountryCode": cfg.get("defaultCountryCode") or settings.DEFAULT_COUNTRY_CODE,
        "aisensyApiKey": cfg.get("aisensyApiKey") or settings.AISENSY_API_KEY,
        "aisensyCampaignName": cfg.get("aisensyCampaignName") or settings.AISENSY_CAMPAIGN_NAME,
        "aisensySource": cfg.get("aisensySource") or settings.AISENSY_SOURCE,
        "aisensyTemplateParamFields": cfg.get("aisensyTemplateParamFields") or settings.AISENSY_TEMPLATE_PARAM_FIELDS,
        "aisensyTags": cfg.get("aisensyTags") or settings.AISENSY_TAGS,
        "metaApiVersion": cfg.get("metaApiVersion") or settings.META_GRAPH_API_VERSION,
        "metaPhoneNumberId": cfg.get("metaPhoneNumberId") or settings.META_WHATSAPP_PHONE_NUMBER_ID,
        "metaAccessToken": cfg.get("metaAccessToken") or settings.META_WHATSAPP_ACCESS_TOKEN,
        "metaTemplateName": cfg.get("metaTemplateName") or settings.META_WHATSAPP_TEMPLATE_NAME,
        "metaLanguageCode": cfg.get("metaLanguageCode") or settings.META_WHATSAPP_LANGUAGE_CODE,
    }


async def _log_whatsapp(db, doc: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow()
    full = {"whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}", "created_at": now, "updated_at": now, **doc}
    await db["whatsapp_logs"].insert_one(full)
    return full


async def send_whatsapp(
    db,
    to_number: str,
    body: str,
    *,
    event_type: str,
    recipient_type: str,
    context: Optional[Dict[str, Any]] = None,
    media_url: str = "",
) -> Dict[str, Any]:
    config = await _get_config(db)
    context = context or {}
    provider = config.get("provider", "twilio")
    cc = config.get("defaultCountryCode", "+91")
    to_plain = _plain_phone(to_number, cc)
    to_wa = _wa_number(to_number, cc)
    from_wa = _wa_number(config.get("fromWhatsAppNumber", ""), cc)

    log = await _log_whatsapp(db, {
        "provider": provider,
        "direction": "outbound",
        "event_type": event_type,
        "recipient_type": recipient_type,
        "to_number": to_plain,
        "body": body,
        "status": "queued",
        "context": context,
    })

    # ── validation ────────────────────────────────────────────────────────────
    missing = []
    if not config.get("enabled"):
        missing.append("WhatsApp automation is disabled")
    if not to_plain:
        missing.append("recipient WhatsApp number")
    if provider == "aisensy":
        if not config.get("aisensyApiKey"):
            missing.append("AiSensy API key")
        if not config.get("aisensyCampaignName"):
            missing.append("AiSensy campaign name")
    elif provider == "meta":
        if not config.get("metaAccessToken"):
            missing.append("Meta access token")
        if not config.get("metaPhoneNumberId"):
            missing.append("Meta phone number ID")
    else:  # twilio
        if not config.get("accountSid"):
            missing.append("Twilio Account SID")
        if not config.get("authToken"):
            missing.append("Twilio Auth Token")
        if not from_wa:
            missing.append("Twilio sender number")

    if missing:
        err = ", ".join(missing)
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log["whatsapp_id"]},
            {"$set": {"status": "skipped", "error_message": err, "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "skipped", "error": err, "whatsapp_id": log["whatsapp_id"]}

    # ── AiSensy ───────────────────────────────────────────────────────────────
    if provider == "aisensy":
        fields = _csv(config.get("aisensyTemplateParamFields")) or ["message"]
        params = [body if f.lower() in {"message", "body", "text"} else context.get(f, "") for f in fields]
        payload = {
            "apiKey": config["aisensyApiKey"],
            "campaignName": config["aisensyCampaignName"],
            "destination": to_plain.lstrip("+"),
            "userName": context.get("trainer_name") or context.get("recipient_name") or "Trainer",
            "source": config.get("aisensySource") or "TrainerSync",
            "templateParams": params,
            "tags": _csv(config.get("aisensyTags")) or ["trainersync"],
            "paramsFallbackValue": {"FirstName": context.get("trainer_name") or "user"},
        }
        if media_url:
            payload["media"] = {"url": media_url}
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(AISENSY_API_URL, json=payload)
            rj = resp.json() if resp.content else {}
            if resp.status_code >= 400 or rj.get("success") is False:
                err = rj.get("message") or resp.text
                await db["whatsapp_logs"].update_one(
                    {"whatsapp_id": log["whatsapp_id"]},
                    {"$set": {"status": "failed", "error_message": err, "updated_at": datetime.utcnow()}},
                )
                return {"success": False, "status": "failed", "error": err, "whatsapp_id": log["whatsapp_id"], "provider": "aisensy"}
            mid = rj.get("messageId") or rj.get("id") or rj.get("requestId")
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log["whatsapp_id"]},
                {"$set": {"status": "sent", "aisensy_message_id": mid, "sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
            )
            return {"success": True, "status": "sent", "provider": "aisensy", "aisensy_message_id": mid, "whatsapp_id": log["whatsapp_id"]}
        except Exception as exc:
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log["whatsapp_id"]},
                {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
            )
            return {"success": False, "status": "failed", "error": str(exc), "whatsapp_id": log["whatsapp_id"], "provider": "aisensy"}

    # ── Meta Cloud API ────────────────────────────────────────────────────────
    if provider == "meta":
        ver = config.get("metaApiVersion") or "v23.0"
        url = f"{META_GRAPH_API_BASE}/{ver}/{config['metaPhoneNumberId']}/messages"
        tname = config.get("metaTemplateName")
        if tname:
            fields = _csv(config.get("metaTemplateParamFields", "message"))
            parameters = [{"type": "text", "text": (body if f.lower() in {"message", "body"} else context.get(f, ""))[:1024]} for f in fields]
            wa_payload: Dict[str, Any] = {
                "messaging_product": "whatsapp", "to": to_plain.lstrip("+"),
                "type": "template",
                "template": {"name": tname, "language": {"code": config.get("metaLanguageCode") or "en_US"},
                             "components": [{"type": "body", "parameters": parameters}] if parameters else []},
            }
        else:
            wa_payload = {"messaging_product": "whatsapp", "to": to_plain.lstrip("+"), "type": "text", "text": {"body": body[:4096]}}
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(url, json=wa_payload, headers={"Authorization": f"Bearer {config['metaAccessToken']}"})
            rj = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                err = (rj.get("error") or {}).get("message") or resp.text
                await db["whatsapp_logs"].update_one(
                    {"whatsapp_id": log["whatsapp_id"]},
                    {"$set": {"status": "failed", "error_message": err, "updated_at": datetime.utcnow()}},
                )
                return {"success": False, "status": "failed", "error": err, "whatsapp_id": log["whatsapp_id"], "provider": "meta"}
            msgs = rj.get("messages") or []
            mid = (msgs[0] or {}).get("id") if msgs else ""
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log["whatsapp_id"]},
                {"$set": {"status": "sent", "meta_message_id": mid, "sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
            )
            return {"success": True, "status": "sent", "provider": "meta", "meta_message_id": mid, "whatsapp_id": log["whatsapp_id"]}
        except Exception as exc:
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log["whatsapp_id"]},
                {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
            )
            return {"success": False, "status": "failed", "error": str(exc), "whatsapp_id": log["whatsapp_id"], "provider": "meta"}

    # ── Twilio ────────────────────────────────────────────────────────────────
    url = f"{TWILIO_API_BASE}/Accounts/{config['accountSid']}/Messages.json"
    data: Dict[str, Any] = {"From": from_wa, "To": to_wa, "Body": body}
    if media_url:
        data["MediaUrl"] = media_url
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(url, data=data, auth=(config["accountSid"], config["authToken"]))
        rj = resp.json()
        if resp.status_code >= 400:
            err = rj.get("message") or resp.text
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log["whatsapp_id"]},
                {"$set": {"status": "failed", "error_message": err, "updated_at": datetime.utcnow()}},
            )
            return {"success": False, "status": "failed", "error": err, "whatsapp_id": log["whatsapp_id"], "provider": "twilio"}
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log["whatsapp_id"]},
            {"$set": {"status": rj.get("status", "sent"), "twilio_sid": rj.get("sid"), "sent_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
        )
        return {"success": True, "status": rj.get("status", "sent"), "provider": "twilio", "twilio_sid": rj.get("sid"), "whatsapp_id": log["whatsapp_id"]}
    except Exception as exc:
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log["whatsapp_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": datetime.utcnow()}},
        )
        return {"success": False, "status": "failed", "error": str(exc), "whatsapp_id": log["whatsapp_id"], "provider": "twilio"}
