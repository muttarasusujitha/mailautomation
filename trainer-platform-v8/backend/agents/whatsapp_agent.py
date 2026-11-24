import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from utils.time_utils import utc_now
from typing import Any, Dict, Optional

import httpx

from config import get_settings
from database import get_db


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

META_PIPELINE_TEMPLATES = {
    "first": ("trainer_first_contact", ["trainer_name", "technology", "technology"]),
    "mail1": ("trainer_first_contact", ["trainer_name", "technology", "technology"]),
    "mail1_reminder": ("trainer_first_contact", ["trainer_name", "technology", "technology"]),
    "mail2": ("trainer_details_request", ["trainer_name"]),
    "mail2_followup": ("trainer_details_request", ["trainer_name"]),
    "mail3": ("trainer_slot_booking", ["trainer_name", "technology", "slot1", "slot2", "slot3"]),
    "mail4": ("trainer_interview_schedule", ["trainer_name", "technology", "date_time", "platform", "interview_link"]),
    "mail5_ok": ("trainer_selection", ["trainer_name", "technology"]),
    "mail5_no": ("trainer_rejection", ["trainer_name", "technology"]),
    "mail6_toc": ("trainer_toc_request", ["trainer_name", "technology"]),
    "mail7_confirm": (
        "trainer_training_confirmation",
        ["trainer_name", "technology", "training_date", "venue", "contact_name", "contact_phone", "contact_email"],
    ),
}


def _default_country_code(value: Any = "+91") -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    # A valid country calling code is 1–3 digits (ITU-T E.164).
    # If the digit string is empty or longer than 3, the caller passed a full
    # phone number (e.g. "+919876543210") instead of just a code (e.g. "+91").
    # In either case fall back to India (+91).
    if not digits or len(digits) > 3:
        digits = "91"
    return f"+{digits}"


def _is_placeholder_value(value: Any) -> bool:
    clean = str(value or "").strip().lower()
    compact = clean.replace("-", "_").replace(" ", "_")
    return (
        not clean
        or compact.startswith("your_")
        or compact.startswith("your.")
        or compact.startswith("your-")
        or compact.startswith("enter_")
        or "xxxxxxxx" in compact
        or compact in {"placeholder", "changeme", "change_me", "your_api_key"}
    )


def _config_value(value: Any, fallback: Any = "", default: str = "") -> str:
    for candidate in (value, fallback):
        clean = str(candidate or "").strip()
        if clean and not _is_placeholder_value(clean):
            return clean
    return default


def _settings_env(env_name: str, default: str = "") -> str:
    return str(getattr(get_settings(), env_name.lower(), "") or os.getenv(env_name, default) or "").strip()


async def get_twilio_config(db) -> Dict[str, Any]:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "twilioCfg": 1},
    )
    cfg = (settings_doc or {}).get("twilioCfg") or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "provider": (cfg.get("provider") or _settings_env("WHATSAPP_PROVIDER", "twilio")).strip().lower(),
        "accountSid": _config_value(cfg.get("accountSid"), _settings_env("TWILIO_ACCOUNT_SID")),
        "authToken": _config_value(cfg.get("authToken"), _settings_env("TWILIO_AUTH_TOKEN")),
        "fromWhatsAppNumber": _config_value(cfg.get("fromWhatsAppNumber"), _settings_env("TWILIO_WHATSAPP_FROM")),
        "vendorWhatsAppNumber": _config_value(cfg.get("vendorWhatsAppNumber"), _settings_env("VENDOR_WHATSAPP_NUMBER")),
        "defaultCountryCode": _default_country_code(cfg.get("defaultCountryCode") or "+91"),
        "statusCallbackUrl": _config_value(cfg.get("statusCallbackUrl")),
        "aisensyApiUrl": _config_value(cfg.get("aisensyApiUrl"), _settings_env("AISENSY_API_URL", AISENSY_API_URL), AISENSY_API_URL),
        "aisensyApiKey": _config_value(cfg.get("aisensyApiKey"), _settings_env("AISENSY_API_KEY")),
        "aisensyCampaignName": _config_value(cfg.get("aisensyCampaignName"), _settings_env("AISENSY_CAMPAIGN_NAME")),
        "aisensySource": _config_value(cfg.get("aisensySource"), _settings_env("AISENSY_SOURCE", "TrainerSync"), "TrainerSync"),
        "aisensyTemplateParamFields": _config_value(cfg.get("aisensyTemplateParamFields"), _settings_env("AISENSY_TEMPLATE_PARAM_FIELDS", "message"), "message"),
        "aisensyTags": _config_value(cfg.get("aisensyTags"), _settings_env("AISENSY_TAGS", "trainersync"), "trainersync"),
        "metaApiVersion": _config_value(cfg.get("metaApiVersion"), _settings_env("META_GRAPH_API_VERSION", "v23.0"), "v23.0"),
        "metaPhoneNumberId": _config_value(cfg.get("metaPhoneNumberId"), _settings_env("META_WHATSAPP_PHONE_NUMBER_ID")),
        "metaAccessToken": _config_value(cfg.get("metaAccessToken"), _settings_env("META_WHATSAPP_ACCESS_TOKEN")),
        "metaTemplateName": _config_value(cfg.get("metaTemplateName"), _settings_env("META_WHATSAPP_TEMPLATE_NAME")),
        "metaLanguageCode": _config_value(cfg.get("metaLanguageCode"), _settings_env("META_WHATSAPP_LANGUAGE_CODE", "en_US"), "en_US"),
        "metaTemplateParamFields": _config_value(cfg.get("metaTemplateParamFields"), _settings_env("META_WHATSAPP_TEMPLATE_PARAM_FIELDS", "message"), "message"),
    }


def stage_label(mail_type: str = "") -> str:
    return STAGE_LABELS.get(mail_type or "", mail_type or "Pipeline update")


def _clip(text: Any, limit: int = 900) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned if len(cleaned) <= limit else f"{cleaned[:limit - 3]}..."


def _line_value(text: str, label: str, fallback: str = "") -> str:
    pattern = rf"{re.escape(label)}\s*:?\s*(.+)"
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return fallback
    value = match.group(1).strip()
    return value or fallback


def _contact_details_from_body(body: str = "") -> Dict[str, str]:
    details = {"name": "", "phone": "", "email": ""}
    lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
    try:
        start = next(
            i for i, line in enumerate(lines)
            if "please contact" in line.lower() or "for any questions" in line.lower()
        )
        candidates = lines[start + 1:start + 8]
    except StopIteration:
        candidates = lines

    for line in candidates:
        cleaned = re.sub(r"^[^\w+@]+", "", line).strip()
        if not details["email"] and "@" in cleaned:
            details["email"] = cleaned
        elif not details["phone"] and re.search(r"\d{6,}", re.sub(r"\D", "", cleaned)):
            details["phone"] = cleaned
        elif not details["name"] and not any(token in cleaned.lower() for token in ["phone", "email", "training date", "venue"]):
            details["name"] = cleaned
    return details


def _domain_from_text(subject: str = "", body: str = "", fallback: str = "Training") -> str:
    subject_text = str(subject or "")
    body_text = str(body or "")
    subject_patterns = [
        r"Training Requirement\s*[-\u2013]\s*([^|]+)",
        r"Interview Slot Booking\s*[-\u2013]\s*([^|]+)",
        r"Interview Schedule Confirmation\s*[-\u2013]\s*([^|]+)",
        r"Selected\s*[-\u2013]\s*([^|]+)",
        r"Update on Training Requirement\s*[-\u2013]\s*([^|]+)",
        r"ToC\s*/\s*Course Agenda\s*[-\u2013]\s*([^|]+)",
        r"Training Schedule Confirmed\s*[-\u2013]\s*([^|]+)",
    ]
    for pattern in subject_patterns:
        match = re.search(pattern, subject_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

    for pattern in [
        r"Domain/Technology\s*:\s*([^\n\r]+)",
        r"requirement for\s+(.+?)\s+and are looking",
        r"selected for the\s+(.+?)\s+training",
        r"engagement for the\s+(.+?)\s+training",
        r"interest in the\s+(.+?)\s+training requirement",
    ]:
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return fallback or "Training"


def _reminder_number(subject: str = "", body: str = "") -> str:
    match = re.search(r"Reminder\s+(\d+)", f"{subject or ''}\n{body or ''}", flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _slot_lines(body: str = "") -> str:
    text = str(body or "")
    lower = text.lower()
    start = lower.find("following slots:")
    end = lower.find("kindly confirm", start)
    if start < 0 or end <= start:
        return "* [Slot 1]\n* [Slot 2]\n* [Slot 3]"
    slot_text = text[start + len("following slots:"):end]
    lines = []
    for raw in slot_text.splitlines():
        cleaned = raw.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^[*\-\u2022]\s*", "", cleaned).strip()
        if cleaned:
            lines.append(f"* {cleaned}")
    return "\n".join(lines) or "* [Slot 1]\n* [Slot 2]\n* [Slot 3]"


def _slot_values(body: str = "") -> list:
    values = []
    for raw in _slot_lines(body).splitlines():
        cleaned = raw.strip()
        cleaned = re.sub(r"^[*\-\u2022]+\s*", "", cleaned).strip()
        cleaned = cleaned.replace("â€¢", "").strip()
        if cleaned:
            values.append(cleaned)
    while len(values) < 3:
        values.append(f"[Slot {len(values) + 1}]")
    return values[:3]


def _whatsapp_stage_message(
    *,
    trainer_name: str,
    subject: str = "",
    body: str = "",
    mail_type: str = "",
    technology: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> str:
    context = context or {}
    name = (trainer_name or context.get("trainer_name") or "Trainer").strip() or "Trainer"
    domain = (technology or context.get("technology") or context.get("domain") or "").strip()
    domain = _domain_from_text(subject, body, domain or "Training")
    greeting = f"Dear {name},"

    if mail_type in {"first", "mail1"}:
        return (
            f"{greeting}\n\n"
            f"We have received a training requirement for {domain} and are looking for a trainer with relevant experience.\n\n"
            "Training Details:\n"
            f"Domain/Technology: {domain}\n\n"
            "Please let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail1_reminder":
        number = _reminder_number(subject, body)
        reminder_text = f" (Reminder {number})" if number else ""
        return (
            f"{greeting}\n\n"
            f"This is a gentle follow-up{reminder_text} to our earlier message regarding the {domain} training requirement.\n\n"
            "We haven't received your response yet. Kindly let us know your interest and availability at the earliest.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail2":
        return (
            f"{greeting}\n\n"
            "Thank you for your response.\n\n"
            "To proceed further, kindly share the below details:\n\n"
            "* Total years of experience\n"
            "* Number of trainings conducted previously\n"
            "* Relevant certifications\n"
            "* Preferred training mode: Online / Offline\n"
            "* Availability for Full-Day or Half-Day sessions\n"
            "* Expected commercial charges per day/session\n"
            "* Current location\n"
            "* Availability for the mentioned dates\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail2_followup":
        return (
            f"{greeting}\n\n"
            "Thank you for confirming your interest.\n\n"
            "To proceed further, kindly share the above requested details:\n\n"
            "* Total years of experience\n"
            "* Number of trainings conducted previously\n"
            "* Relevant certifications\n"
            "* Preferred training mode: Online / Offline\n"
            "* Availability for Full-Day or Half-Day sessions\n"
            "* Expected commercial charges per day/session\n"
            "* Current location\n"
            "* Availability for the mentioned dates\n\n"
            "Once we receive these details, we can move ahead with the next step.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail3":
        return (
            f"{greeting}\n\n"
            "Thank you for sharing your details.\n\n"
            "We would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n"
            f"{_slot_lines(body)}\n\n"
            "Kindly confirm your preferred slot at the earliest.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail4":
        date_time = context.get("date_time") or _line_value(body, "Date & Time", "[Date & Time]")
        platform = context.get("platform") or _line_value(body, "Platform", "Zoom")
        interview_link = context.get("interview_link") or _line_value(body, "Meeting Link", "[Meeting Link]")
        return (
            f"{greeting}\n\n"
            "Your interview has been scheduled. Please find the details below:\n\n"
            f"Date & Time: {date_time}\n"
            f"Platform: {platform}\n"
            f"Meeting Link: {interview_link}\n\n"
            "Please join on time. Let us know if you need any assistance.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail5_ok":
        return (
            f"{greeting}\n\n"
            f"Congratulations! You have been selected for the {domain} training requirement.\n\n"
            "Clahan Technologies will coordinate the next steps and documentation with you shortly.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail5_no":
        return (
            f"{greeting}\n\n"
            f"Thank you for your time and interest in the {domain} training requirement.\n\n"
            "After careful consideration, we have decided to proceed with another trainer at this time.\n\n"
            "We will keep your profile on record and reach out for future opportunities.\n\n"
            "Thank you once again for your cooperation.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail6_toc":
        if "ai-generated" in body.lower() or "attached" in body.lower():
            return (
                f"{greeting}\n\n"
                f"The AI-generated ToC / Course Agenda for the {domain} training has been emailed to you for review.\n\n"
                "Kindly check the attached document in your email and share any required changes or additions before we share it with the client.\n\n"
                "Regards,\nTrainerSync Team"
            )
        return (
            f"{greeting}\n\n"
            f"Congratulations again on being selected for the {domain} training.\n\n"
            "To initiate the onboarding process, kindly share the following at the earliest:\n\n"
            "* Detailed Table of Contents / Course Agenda\n"
            "* Day-wise session breakdown\n"
            "* Tools, software, or prerequisites required by participants\n"
            "* Estimated preparation time needed\n\n"
            "Please revert at the earliest so we can coordinate with the client on schedule.\n\n"
            "Regards,\nTrainerSync Team"
        )

    if mail_type == "mail7_confirm":
        contact_details = _contact_details_from_body(body)
        training_date = context.get("training_date") or _line_value(body, "Training Date", "[Training Date]")
        venue = context.get("venue") or _line_value(body, "Venue / Platform", "[Venue or Platform]")
        contact_name = (
            context.get("contact_name")
            or _line_value(body, "Contact Name")
            or contact_details["name"]
            or "[Contact Name]"
        )
        contact_phone = (
            context.get("contact_phone")
            or _line_value(body, "Phone")
            or contact_details["phone"]
            or "[Phone Number]"
        )
        contact_email = (
            context.get("contact_email")
            or _line_value(body, "Email")
            or contact_details["email"]
            or "[Email]"
        )
        return (
            f"{greeting}\n\n"
            f"We are pleased to confirm your engagement for the {domain} training. Please find the final details below:\n\n"
            f"Training Date: {training_date}\n"
            f"Venue / Platform: {venue}\n\n"
            "Action Items Before Training:\n"
            "* Ensure all materials and slides are ready\n"
            "* Share soft copies of training content with us 2 days prior\n"
            "* Confirm your availability 24 hours before the training\n\n"
            "For any questions or additional information, please contact:\n\n"
            f"Contact Name: {contact_name}\n"
            f"Phone: {contact_phone}\n"
            f"Email: {contact_email}\n\n"
            "We look forward to a successful training session.\n\n"
            "Regards,\nTrainerSync Team"
        )

    return str(body or "").strip()


def _format_whatsapp_number(number: Any, default_country_code: str = "+91") -> str:
    plain = _plain_phone_number(number, default_country_code)
    if not plain:
        return ""
    return f"whatsapp:{plain}"


def _plain_phone_number(number: Any, default_country_code: str = "+91") -> str:
    raw = str(number or "").strip()
    if not raw:
        return ""

    raw = raw.replace("whatsapp:", "")
    if raw.startswith("00"):
        raw = f"+{raw[2:]}"
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    country = re.sub(r"\D", "", default_country_code or "+91") or "91"

    # Imported resumes sometimes contain two numbers in one field. AiSensy rejects
    # the combined value, so keep one valid 10-digit Indian mobile number.
    if country == "91":
        if len(digits) == 12 and digits.startswith(country):
            return f"+{digits}"
        if len(digits) == 10:
            return f"+{country}{digits}"
        if len(digits) > 10:
            candidate = digits[-10:]
            return f"+{country}{candidate}"

    if raw.startswith("+"):
        return f"+{digits}"
    if digits.startswith(country):
        return f"+{digits}"
    return f"+{digits}"


def _csv_values(value: Any) -> list:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _aisensy_value(field: str, body: str, context: Dict[str, Any], to_number: str) -> str:
    raw_field = str(field or "").strip()
    if raw_field.startswith("$"):
        return raw_field

    key = raw_field.lower()
    slots = _slot_values(body)
    contact_details = _contact_details_from_body(body)
    domain = (
        context.get("technology")
        or context.get("domain")
        or _domain_from_text(context.get("subject") or "", body, "Training")
    )
    mapping = {
        "message": body,
        "body": body,
        "text": body,
        "trainer_name": context.get("trainer_name") or context.get("recipient_name") or "Trainer",
        "recipient_name": context.get("trainer_name") or context.get("recipient_name") or "Trainer",
        "user_name": context.get("trainer_name") or context.get("recipient_name") or "Trainer",
        "technology": domain,
        "domain": domain,
        "requirement_id": context.get("requirement_id") or "-",
        "stage": context.get("stage") or stage_label(context.get("mail_type", "")),
        "subject": context.get("subject") or "",
        "mail_type": context.get("mail_type") or "",
        "event_type": context.get("event_type") or "",
        "date_time": context.get("date_time") or "",
        "platform": context.get("platform") or "",
        "interview_link": context.get("interview_link") or "",
        "slot1": slots[0],
        "slot2": slots[1],
        "slot3": slots[2],
        "training_date": context.get("training_date") or _line_value(body, "Training Date", "[Training Date]"),
        "venue": context.get("venue") or _line_value(body, "Venue / Platform", "[Venue / Platform]"),
        "contact_name": context.get("contact_name") or _line_value(body, "Contact Name") or contact_details["name"],
        "contact_phone": context.get("contact_phone") or _line_value(body, "Phone") or contact_details["phone"],
        "contact_email": context.get("contact_email") or _line_value(body, "Email") or contact_details["email"],
        "phone": to_number,
    }
    return str(mapping.get(key, context.get(key, "")) or "")


def _aisensy_template_params(config: Dict[str, Any], body: str, context: Dict[str, Any], to_number: str) -> list:
    raw_fields = str(config.get("aisensyTemplateParamFields") or "").strip().lower()
    if raw_fields in {"none", "no_params", "no params", "0", "[]"}:
        return []
    fields = _csv_values(config.get("aisensyTemplateParamFields")) or ["message"]
    return [_aisensy_value(field, body, context, to_number) for field in fields]


def _meta_template_parameters(
    config: Dict[str, Any],
    body: str,
    context: Dict[str, Any],
    to_number: str,
    fields: Optional[list] = None,
) -> list:
    fields = fields or _csv_values(config.get("metaTemplateParamFields"))
    return [
        {"type": "text", "text": _aisensy_value(field, body, context, to_number)[:1024]}
        for field in fields
    ]


def _meta_template_for_context(config: Dict[str, Any], context: Dict[str, Any]) -> tuple:
    mail_type = str(context.get("mail_type") or "").strip()
    if context.get("template_source") == "pipeline_whatsapp" and mail_type in META_PIPELINE_TEMPLATES:
        return META_PIPELINE_TEMPLATES[mail_type]
    configured_name = config.get("metaTemplateName", "")
    configured_fields = _csv_values(config.get("metaTemplateParamFields"))
    return configured_name, configured_fields


def _callback_url(config: Dict[str, Any], request_base_url: str = "") -> str:
    if config.get("statusCallbackUrl"):
        configured = str(config["statusCallbackUrl"]).strip()
        if configured.startswith("https://") and "localhost" not in configured and "127.0.0.1" not in configured:
            return configured
        return ""
    if request_base_url:
        base = request_base_url.rstrip("/")
        if base.startswith("https://") and "localhost" not in base and "127.0.0.1" not in base:
            return f"{base}/api/whatsapp/status-callback"
    return ""


async def _insert_whatsapp_log(db, log_doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = {
        "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        **log_doc,
    }
    await db["whatsapp_logs"].insert_one(doc)
    return doc


async def send_whatsapp_message(
    db,
    to_number: str,
    body: str,
    *,
    event_type: str,
    recipient_type: str,
    context: Optional[Dict[str, Any]] = None,
    request_base_url: str = "",
    media_url: str = "",
) -> Dict[str, Any]:
    config = await get_twilio_config(db)
    context = context or {}
    provider = (config.get("provider") or "twilio").strip().lower()
    if provider not in {"twilio", "aisensy", "meta"}:
        provider = "twilio"
    to_whatsapp = _format_whatsapp_number(to_number, config.get("defaultCountryCode", "+91"))
    from_whatsapp = _format_whatsapp_number(config.get("fromWhatsAppNumber"), config.get("defaultCountryCode", "+91"))
    to_plain = _plain_phone_number(to_number, config.get("defaultCountryCode", "+91"))

    log_doc = await _insert_whatsapp_log(db, {
        "provider": provider,
        "direction": "outbound",
        "event_type": event_type,
        "recipient_type": recipient_type,
        "to_number": to_whatsapp if provider == "twilio" else to_plain,
        "from_number": (
            from_whatsapp
            if provider == "twilio"
            else config.get("aisensySource", "TrainerSync")
            if provider == "aisensy"
            else config.get("metaPhoneNumberId", "")
        ),
        "body": body,
        "media_url": media_url,
        "status": "queued",
        "context": context,
    })

    missing = []
    if not config.get("enabled"):
        missing.append("WhatsApp automation is disabled")
    if provider == "aisensy":
        if not config.get("aisensyApiKey"):
            missing.append("AiSensy API key")
        if not config.get("aisensyCampaignName"):
            missing.append("AiSensy campaign name")
        if not to_plain:
            missing.append("recipient WhatsApp number")
    elif provider == "meta":
        if not config.get("metaAccessToken"):
            missing.append("Meta WhatsApp access token")
        if not config.get("metaPhoneNumberId"):
            missing.append("Meta WhatsApp Phone Number ID")
        if not to_plain:
            missing.append("recipient WhatsApp number")
    else:
        if not config.get("accountSid"):
            missing.append("Twilio Account SID")
        if not config.get("authToken"):
            missing.append("Twilio Auth Token")
        if not from_whatsapp:
            missing.append("Twilio WhatsApp sender number")
        if not to_whatsapp:
            missing.append("recipient WhatsApp number")

    if missing:
        error = ", ".join(missing)
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {"status": "skipped", "error_message": error, "updated_at": utc_now()}},
        )
        return {
            "success": False,
            "status": "skipped",
            "error": error,
            "whatsapp_id": log_doc["whatsapp_id"],
            "to_number": log_doc.get("to_number", ""),
            "from_number": log_doc.get("from_number", ""),
            "provider": provider,
        }

    if provider == "aisensy":
        api_url = config.get("aisensyApiUrl") or AISENSY_API_URL
        aisensy_destination = to_plain.lstrip("+")
        template_context = {
            **context,
            "event_type": event_type,
            "recipient_type": recipient_type,
        }
        recipient_name = (
            context.get("trainer_name")
            or context.get("recipient_name")
            or context.get("client_name")
            or "Trainer"
        )
        attributes = {
            "event_type": event_type,
            "recipient_type": recipient_type,
            "requirement_id": context.get("requirement_id") or "",
            "stage": context.get("stage") or stage_label(context.get("mail_type", "")),
        }
        payload = {
            "apiKey": config["aisensyApiKey"],
            "campaignName": config["aisensyCampaignName"],
            "destination": aisensy_destination,
            "userName": str(recipient_name),
            "source": config.get("aisensySource") or "TrainerSync",
            "templateParams": _aisensy_template_params(config, body, template_context, to_plain),
            "tags": _csv_values(config.get("aisensyTags")) or ["trainersync"],
            "paramsFallbackValue": {
                "FirstName": str(recipient_name or "user"),
            },
            "attributes": {k: str(v) for k, v in attributes.items() if v is not None},
        }
        if media_url:
            payload["media"] = {"url": media_url}

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(api_url, json=payload)
            try:
                payload_response = response.json()
            except Exception:
                payload_response = {"raw": response.text}

            is_failure = response.status_code >= 400 or payload_response.get("success") is False
            if is_failure:
                error = (
                    payload_response.get("message")
                    or payload_response.get("error")
                    or payload_response.get("raw")
                    or response.text
                )
                await db["whatsapp_logs"].update_one(
                    {"whatsapp_id": log_doc["whatsapp_id"]},
                    {"$set": {
                        "status": "failed",
                        "error_message": error,
                        "aisensy_response": payload_response,
                        "updated_at": utc_now(),
                    }},
                )
                return {
                    "success": False,
                    "status": "failed",
                    "error": error,
                    "whatsapp_id": log_doc["whatsapp_id"],
                    "to_number": log_doc.get("to_number", ""),
                    "from_number": log_doc.get("from_number", ""),
                    "provider": "aisensy",
                }

            message_id = (
                payload_response.get("messageId")
                or payload_response.get("submitted_message_id")
                or payload_response.get("submittedMessageId")
                or payload_response.get("message_id")
                or payload_response.get("id")
                or payload_response.get("requestId")
                or payload_response.get("campaignId")
            )
            status = payload_response.get("status") or payload_response.get("statusName") or "sent"
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {
                    "status": status,
                    "aisensy_message_id": message_id,
                    "aisensy_response": payload_response,
                    "sent_at": utc_now(),
                    "updated_at": utc_now(),
                }},
            )
            return {
                "success": True,
                "status": status,
                "provider": "aisensy",
                "aisensy_message_id": message_id,
                "whatsapp_id": log_doc["whatsapp_id"],
                "to_number": log_doc.get("to_number", ""),
                "from_number": log_doc.get("from_number", ""),
            }
        except Exception as exc:
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {"status": "failed", "error_message": str(exc), "updated_at": utc_now()}},
            )
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "whatsapp_id": log_doc["whatsapp_id"],
                "to_number": log_doc.get("to_number", ""),
                "from_number": log_doc.get("from_number", ""),
                "provider": "aisensy",
            }

    if provider == "meta":
        api_version = config.get("metaApiVersion") or "v23.0"
        api_version = api_version if api_version.startswith("v") else f"v{api_version}"
        url = f"{META_GRAPH_API_BASE}/{api_version}/{config['metaPhoneNumberId']}/messages"
        template_context = {
            **context,
            "event_type": event_type,
            "recipient_type": recipient_type,
        }
        meta_to = to_plain.lstrip("+")
        template_name, template_fields = _meta_template_for_context(config, template_context)
        if template_name:
            parameters = _meta_template_parameters(config, body, template_context, to_plain, template_fields)
            template = {
                "name": template_name,
                "language": {"code": config.get("metaLanguageCode") or "en_US"},
            }
            if parameters:
                template["components"] = [{"type": "body", "parameters": parameters}]
            payload = {
                "messaging_product": "whatsapp",
                "to": meta_to,
                "type": "template",
                "template": template,
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": meta_to,
                "type": "text",
                "text": {"preview_url": False, "body": body[:4096]},
            }

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {config['metaAccessToken']}"},
                )
            try:
                payload_response = response.json()
            except Exception:
                payload_response = {"raw": response.text}

            if response.status_code >= 400:
                error_obj = payload_response.get("error") if isinstance(payload_response, dict) else {}
                error = (
                    (error_obj or {}).get("message")
                    or payload_response.get("message")
                    or payload_response.get("raw")
                    or response.text
                )
                await db["whatsapp_logs"].update_one(
                    {"whatsapp_id": log_doc["whatsapp_id"]},
                    {"$set": {
                        "status": "failed",
                        "error_message": error,
                        "meta_response": payload_response,
                        "updated_at": utc_now(),
                    }},
                )
                return {
                    "success": False,
                    "status": "failed",
                    "error": error,
                    "whatsapp_id": log_doc["whatsapp_id"],
                    "to_number": log_doc.get("to_number", ""),
                    "from_number": log_doc.get("from_number", ""),
                    "provider": "meta",
                }

            messages = payload_response.get("messages") or []
            contacts = payload_response.get("contacts") or []
            message_id = (messages[0] or {}).get("id") if messages else ""
            status = (messages[0] or {}).get("message_status") or "sent"
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {
                    "status": status,
                    "meta_message_id": message_id,
                    "meta_wa_id": (contacts[0] or {}).get("wa_id") if contacts else "",
                    "meta_response": payload_response,
                    "sent_at": utc_now(),
                    "updated_at": utc_now(),
                }},
            )
            return {
                "success": True,
                "status": status,
                "provider": "meta",
                "meta_message_id": message_id,
                "whatsapp_id": log_doc["whatsapp_id"],
                "to_number": log_doc.get("to_number", ""),
                "from_number": log_doc.get("from_number", ""),
            }
        except Exception as exc:
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {"status": "failed", "error_message": str(exc), "updated_at": utc_now()}},
            )
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "whatsapp_id": log_doc["whatsapp_id"],
                "to_number": log_doc.get("to_number", ""),
                "from_number": log_doc.get("from_number", ""),
                "provider": "meta",
            }

    url = f"{TWILIO_API_BASE}/Accounts/{config['accountSid']}/Messages.json"
    data = {
        "From": from_whatsapp,
        "To": to_whatsapp,
        "Body": body,
    }
    if media_url:
        data["MediaUrl"] = media_url
    callback = _callback_url(config, request_base_url)
    if callback:
        data["StatusCallback"] = callback

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                url,
                data=data,
                auth=(config["accountSid"], config["authToken"]),
            )
        payload = response.json()
        if response.status_code >= 400:
            error = payload.get("message") or response.text
            await db["whatsapp_logs"].update_one(
                {"whatsapp_id": log_doc["whatsapp_id"]},
                {"$set": {
                    "status": "failed",
                    "error_message": error,
                    "twilio_response": payload,
                    "updated_at": utc_now(),
                }},
            )
            return {
                "success": False,
                "status": "failed",
                "error": error,
                "whatsapp_id": log_doc["whatsapp_id"],
                "to_number": log_doc.get("to_number", ""),
                "from_number": log_doc.get("from_number", ""),
                "provider": "twilio",
            }

        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {
                "status": payload.get("status", "sent"),
                "twilio_sid": payload.get("sid"),
                "twilio_response": payload,
                "sent_at": utc_now(),
                "updated_at": utc_now(),
            }},
        )
        return {
            "success": True,
            "status": payload.get("status", "sent"),
            "provider": "twilio",
            "twilio_sid": payload.get("sid"),
            "whatsapp_id": log_doc["whatsapp_id"],
            "to_number": log_doc.get("to_number", ""),
            "from_number": log_doc.get("from_number", ""),
        }
    except Exception as exc:
        await db["whatsapp_logs"].update_one(
            {"whatsapp_id": log_doc["whatsapp_id"]},
            {"$set": {"status": "failed", "error_message": str(exc), "updated_at": utc_now()}},
        )
        return {
            "success": False,
            "status": "failed",
            "error": str(exc),
            "whatsapp_id": log_doc["whatsapp_id"],
            "to_number": log_doc.get("to_number", ""),
            "from_number": log_doc.get("from_number", ""),
            "provider": "twilio",
        }


async def send_shortlist_whatsapp(
    db,
    *,
    trainer_phone: str,
    trainer_name: str,
    subject: str,
    body: str,
    mail_type: str,
    requirement_id: str,
    email_id: str,
    request_base_url: str = "",
) -> Dict[str, Any]:
    requirement = {}
    if requirement_id:
        requirement = await db["requirements"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0, "technology_needed": 1},
        ) or {}

    technology = requirement.get("technology_needed", "")
    message = _whatsapp_stage_message(
        trainer_name=trainer_name,
        subject=subject,
        body=body,
        mail_type=mail_type,
        technology=technology,
    )
    return await send_whatsapp_message(
        db,
        trainer_phone,
        message,
        event_type="trainer_pipeline_message",
        recipient_type="trainer",
        request_base_url=request_base_url,
        context={
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "email_id": email_id,
            "mail_type": mail_type,
            "stage": stage_label(mail_type),
            "subject": subject,
            "technology": technology,
            "template_source": "pipeline_whatsapp",
        },
    )


async def send_vendor_reply_notification(
    db,
    *,
    trainer_name: str,
    trainer_id: str,
    requirement_id: str,
    mail_type: str,
    reply_subject: str,
    reply_body: str,
    sentiment: str = "",
    request_base_url: str = "",
) -> Dict[str, Any]:
    config = await get_twilio_config(db)
    message = (
        "TrainerSync reply alert\n"
        f"Trainer: {trainer_name or trainer_id or 'Trainer'}\n"
        f"Requirement: {requirement_id or '-'}\n"
        f"Stage: {stage_label(mail_type)}\n"
        f"Sentiment: {sentiment or 'pending review'}\n"
        f"Subject: {_clip(reply_subject, 160)}\n\n"
        f"Reply: {_clip(reply_body, 700)}"
    )
    return await send_whatsapp_message(
        db,
        config.get("vendorWhatsAppNumber", ""),
        message,
        event_type="trainer_email_reply",
        recipient_type="vendor",
        request_base_url=request_base_url,
        context={
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "mail_type": mail_type,
            "stage": stage_label(mail_type),
            "sentiment": sentiment,
        },
    )


async def send_interview_whatsapp(
    db,
    *,
    trainer_phone: str,
    trainer_name: str,
    requirement_id: str,
    technology: str,
    date_time: str,
    platform: str,
    interview_link: str,
    email_id: str,
    request_base_url: str = "",
    reminder: bool = False,
) -> Dict[str, Any]:
    if reminder:
        message = (
            f"Dear {trainer_name or 'Trainer'},\n\n"
            f"This is a reminder for your {technology or 'Training'} interview.\n\n"
            f"Date & Time: {date_time or '[Date & Time]'}\n"
            f"Platform: {platform or 'Online'}\n"
            f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
            "Please join on time. Let us know if you need any assistance.\n\n"
            "Regards,\nTrainerSync Team"
        )
    else:
        message = _whatsapp_stage_message(
            trainer_name=trainer_name,
            mail_type="mail4",
            technology=technology,
            context={
                "date_time": date_time,
                "platform": platform,
                "interview_link": interview_link,
            },
        )
    return await send_whatsapp_message(
        db,
        trainer_phone,
        message,
        event_type="interview_reminder" if reminder else "interview_scheduled",
        recipient_type="trainer",
        request_base_url=request_base_url,
        context={
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "email_id": email_id,
            "mail_type": "mail4",
            "stage": stage_label("mail4"),
            "date_time": date_time,
            "platform": platform,
            "interview_link": interview_link,
        },
    )


def parse_interview_datetime(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            parsed = None
    if not parsed:
        for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if not parsed:
        return None

    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def interview_reminder_fields(date_time: str) -> Dict[str, Any]:
    interview_at = parse_interview_datetime(date_time)
    if not interview_at:
        return {}
    return {
        "interview_at": interview_at,
        "whatsapp_reminder_due_at": interview_at - timedelta(hours=1),
        "whatsapp_reminder_status": "pending",
    }


async def send_due_interview_reminders():
    db = get_db()
    now = utc_now()
    logs = await db["email_logs"].find({
        "interview_scheduled": True,
        "whatsapp_reminder_due_at": {"$lte": now},
        "whatsapp_reminder_status": "pending",
    }).to_list(100)

    for log in logs:
        trainer = await db["trainers"].find_one(
            {"trainer_id": log.get("trainer_id")},
            {"_id": 0, "phone": 1, "name": 1},
        ) or {}
        req = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id")},
            {"_id": 0, "technology_needed": 1},
        ) or {}

        result = await send_interview_whatsapp(
            db,
            trainer_phone=log.get("trainer_phone") or trainer.get("phone", ""),
            trainer_name=log.get("trainer_name") or trainer.get("name", ""),
            requirement_id=log.get("requirement_id", ""),
            technology=req.get("technology_needed", "Training"),
            date_time=log.get("interview_date", ""),
            platform=log.get("platform", "Online"),
            interview_link=log.get("interview_link", ""),
            email_id=log.get("email_id", ""),
            reminder=True,
        )
        await db["email_logs"].update_one(
            {"email_id": log.get("email_id")},
            {"$set": {
                "whatsapp_reminder_status": "sent" if result.get("success") else result.get("status", "failed"),
                "whatsapp_reminder_sent_at": utc_now() if result.get("success") else None,
                "whatsapp_reminder_error": result.get("error", ""),
            }},
        )


def _first_present(candidates: list, keys: list) -> Any:
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
    return None


def _status_candidates(payload: Dict[str, Any]) -> list:
    candidates = [payload]
    stack = [payload]
    seen = set()
    nested_keys = (
        "data", "message", "status", "statusData", "delivery", "eventData",
        "payload", "update", "key", "value", "changes", "statuses",
    )
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, dict):
            candidates.append(current)
            for key in nested_keys:
                value = current.get(key)
                if isinstance(value, dict):
                    stack.append(value)
                elif isinstance(value, list):
                    stack.extend(item for item in value if isinstance(item, dict))
        elif isinstance(current, list):
            stack.extend(item for item in current if isinstance(item, dict))
    return candidates


def _normalize_delivery_status(status: Any) -> str:
    if status is None:
        return ""
    numeric = {
        0: "failed",
        1: "queued",
        2: "sent",
        3: "delivered",
        4: "read",
        5: "read",
    }
    if isinstance(status, (int, float)):
        return numeric.get(int(status), str(status))
    raw = str(status).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "submitted": "sent",
        "success": "sent",
        "processed": "sent",
        "message_sent": "sent",
        "message_delivered": "delivered",
        "message_read": "read",
        "delivery_failed": "failed",
        "failed_to_deliver": "undelivered",
        "undeliverable": "undelivered",
        "error": "failed",
    }
    return aliases.get(raw, raw)


async def update_whatsapp_status(db, payload: Dict[str, Any]) -> Dict[str, Any]:
    candidates = _status_candidates(payload or {})
    sid = _first_present(candidates, ["MessageSid", "SmsSid", "SmsMessageSid", "sid"])
    provider_message_id = _first_present(candidates, [
        "messageId", "message_id", "submitted_message_id", "submittedMessageId",
        "id", "requestId", "campaignId", "wamid", "messageUuid", "message_uuid",
    ])
    status = _normalize_delivery_status(_first_present(candidates, [
        "MessageStatus", "SmsStatus", "status", "statusName", "delivery_status",
        "deliveryStatus", "event", "eventType",
    ]))
    raw_to_number = _first_present(candidates, [
        "To", "to", "destination", "phone", "phoneNumber", "recipient",
        "recipientPhone", "wa_id", "remoteJid",
    ])
    to_number = _plain_phone_number(raw_to_number) if raw_to_number else ""
    if not sid and not provider_message_id and not to_number:
        return {"updated": False, "reason": "Missing provider message id"}

    set_fields = {
        "status": status or "status_callback",
        "status_callback": payload,
        "updated_at": utc_now(),
    }
    if status in {"delivered", "read"}:
        set_fields["delivered_at"] = utc_now()
    error_code = _first_present(candidates, ["ErrorCode", "errorCode", "error_code", "code"])
    error_message = _first_present(candidates, ["ErrorMessage", "errorMessage", "error_message", "reason", "failure_reason"])
    if error_code:
        set_fields["error_code"] = error_code
    if error_message and status in {"failed", "undelivered", "rejected", "error"}:
        set_fields["error_message"] = error_message

    if sid:
        query = {"twilio_sid": sid}
    elif provider_message_id:
        query = {
            "$or": [
                {"aisensy_message_id": provider_message_id},
                {"aisensy_response.submitted_message_id": provider_message_id},
                {"aisensy_response.messageId": provider_message_id},
                {"meta_message_id": provider_message_id},
                {"twilio_response.sid": provider_message_id},
            ]
        }
    else:
        query = {
            "to_number": to_number,
            "direction": "outbound",
            "status": {"$in": ["queued", "sent", "submitted", "processed"]},
        }

    if provider_message_id or sid:
        result = await db["whatsapp_logs"].update_one(query, {"$set": set_fields})
    else:
        doc = await db["whatsapp_logs"].find_one(query, {"_id": 0, "whatsapp_id": 1}, sort=[("created_at", -1)])
        if not doc:
            return {"updated": False, "reason": "No matching WhatsApp log", "status": status, "to_number": to_number}
        result = await db["whatsapp_logs"].update_one(
            {"whatsapp_id": doc["whatsapp_id"]},
            {"$set": set_fields},
        )
    return {
        "updated": result.modified_count > 0,
        "twilio_sid": sid,
        "provider_message_id": provider_message_id,
        "to_number": to_number,
        "status": status,
    }
