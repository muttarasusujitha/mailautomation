from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response, BackgroundTasks
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import uuid
import re as _re
import json as _json
import base64 as _base64
import io
import zipfile
import os
import html as _html
import smtplib
import asyncio
import hashlib
from email.utils import parseaddr as _parseaddr
from email.header import decode_header as _decode_header, make_header as _make_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import fitz
from pymongo import ReturnDocument
from pymongo.errors import ExecutionTimeout

from database import get_db
from config import get_settings
from agents.pipeline import run_pipeline
from agents.document_agent import (
    build_purchase_order_doc,
    public_purchase_order,
    purchase_order_filename,
    purchase_order_pdf_bytes,
    render_purchase_order_html,
)
from agents.resume_agent import (
    process_resume,
    public_resume_result,
    save_trainer_from_resume,
)
from agents.categorisation_agent import (
    SOFTWARE_TECH_DOMAINS,
    bulk_categorise_all,
    categorise_trainer,
    category_update_fields,
    get_all_categories,
    is_software_domain,
)
from agents.email_agent import (
    check_email_replies,
    send_email_async, compose_retry_email, compose_interview_email,
    get_gmail_password,
)
from agents.teams_agent import send_teams_stage_notification
from agents.client_intelligence_agent import (
    check_if_duplicate,
    create_requirement_from_email,
    extract_client_slot_confirmation,
    fetch_gmail_email,
    generate_calhan_reply,
    get_calendar_service,
    get_gmail_auth_status,
    get_gmail_oauth_url,
    get_gmail_service,
    get_history_message_ids,
    is_likely_training_email,
    process_client_email,
    renew_gmail_watch,
    save_gmail_oauth_token,
    sender_domain,
    send_gmail_reply,
)
from agents.scheduler import get_config as get_scheduler_config, update_config as update_scheduler_config
from agents.interview_reminder_scheduler import (
    cancel_interview_reminder,
    schedule_interview_reminder,
)
from agents.whatsapp_agent import (
    get_twilio_config,
    interview_reminder_fields,
    send_interview_whatsapp,
    send_shortlist_whatsapp,
    send_vendor_reply_notification,
    send_whatsapp_message,
    update_whatsapp_status,
)
from models.schemas import RequirementCreate

router = APIRouter()
CATEGORISATION_JOBS = {}

TRACKING_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)

def _norm_subject(value: str = "") -> str:
    try:
        value = str(_make_header(_decode_header(str(value or ""))))
    except Exception:
        value = str(value or "")
    value = value.lower()
    value = _re.sub(r"=\?[^?]+\?[bq]\?[^?]+\?=", " ", value)
    value = value.replace("re:", "").replace("fw:", "").replace("fwd:", "")
    value = value.replace("[reminder 1]", "").replace("[reminder 2]", "").replace("[reminder 3]", "")
    value = _re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def build_tracking_url(request: Request, email_id: str) -> str:
    return str(request.url_for("track_email_open", email_id=email_id))


async def get_admin_email_config(db):
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {k: v for k, v in email_cfg.items() if v not in (None, "")}


def _request_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _normalise_chat_messages(messages: list) -> list:
    cleaned = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if not cleaned and role != "user":
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] = f"{cleaned[-1]['content']}\n\n{content}"
        else:
            cleaned.append({"role": role, "content": content})
    return cleaned[-12:]


async def _trainer_phone(db, trainer_id: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    if not trainer_id:
        return ""
    trainer = await db["trainers"].find_one(
        {"trainer_id": trainer_id},
        {"_id": 0, "phone": 1},
    )
    return (trainer or {}).get("phone", "")


def _strip_quoted_reply_text(text: str) -> str:
    value = str(text or "")
    value = _re.split(r"\nOn .+wrote:\s*", value, maxsplit=1, flags=_re.IGNORECASE)[0]
    value = _re.split(r"\n-{2,}\s*Original Message\s*-{2,}", value, maxsplit=1, flags=_re.IGNORECASE)[0]
    lines = [line for line in value.splitlines() if not line.strip().startswith(">")]
    return "\n".join(lines).strip()


async def _client_contact_for_requirement(db, requirement_id: str, payload: dict) -> tuple:
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}

    email = (payload.get("client_email") or requirement.get("client_email") or "").strip()
    name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )

    if not email:
        inbox_docs = await db["client_emails"].find(
            {"requirement_id": requirement_id},
            {"_id": 0},
        ).sort("created_at", -1).limit(1).to_list(1)
        inbox_doc = inbox_docs[0] if inbox_docs else {}
        extracted = inbox_doc.get("extracted") or {}
        email = (inbox_doc.get("from_email") or extracted.get("client_email") or "").strip()
        name = inbox_doc.get("from_name") or extracted.get("client_name") or name

    return requirement, email, name


@router.post("/assistant/chat")
async def assistant_chat(payload: dict):
    system_prompt = str(payload.get("system") or "").strip()
    messages = _normalise_chat_messages(payload.get("messages") or [])
    if not messages:
        raise HTTPException(400, "Send at least one user message")

    settings = get_settings()
    api_key = (os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")).strip()
    if not api_key:
        raise HTTPException(503, "GEMINI_API_KEY is not configured on the backend")

    try:
        import httpx as _httpx
        full_prompt = (system_prompt + "\n\n") if system_prompt else ""
        for m in messages:
            role = "User" if m["role"] == "user" else "Assistant"
            full_prompt += f"{role}: {m['content']}\n"
        full_prompt += "Assistant:"
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        async with _httpx.AsyncClient(timeout=30) as http_client:
            res = await http_client.post(gemini_url, json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1000},
            })
            res.raise_for_status()
            data = res.json()
        reply = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
        try:
            db = get_db()
            rates = await _dashboard_cost_rates(db)
            input_tokens = max(1, int(len(full_prompt) / 4))
            output_tokens = max(1, int(len(reply) / 4))
            cost_inr = (
                (input_tokens / 1000) * rates["gemini_input_1k_tokens"]
                + (output_tokens / 1000) * rates["gemini_output_1k_tokens"]
            )
            await db["ai_usage_logs"].insert_one({
                "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
                "provider": "gemini",
                "model": "gemini-1.5-flash",
                "feature": payload.get("feature") or "assistant_chat",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_inr": _money(cost_inr),
                "metadata": payload.get("metadata") or {},
                "created_at": datetime.utcnow(),
            })
        except Exception as log_exc:
            print(f"[AI usage log] failed: {log_exc}")
        return {"reply": reply or "I could not generate a response."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Assistant request failed: {exc}") from exc


def _parse_domain_csv(value: str) -> List[str]:
    return [item.strip().lower() for item in (value or "").split(",") if item.strip()]


async def _client_inbox_settings(db) -> dict:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "clientInboxCfg": 1, "twilioCfg": 1},
    )
    cfg = (settings_doc or {}).get("clientInboxCfg") or {}
    twilio = (settings_doc or {}).get("twilioCfg") or {}
    return {
        "autoSendEnabled": bool(cfg.get("autoSendEnabled", True)),
        "autoSendThreshold": float(cfg.get("autoSendThreshold", 70)),
        "clientDomainsWhitelist": cfg.get("clientDomainsWhitelist", ""),
        "replySignature": cfg.get("replySignature") or "Regards,\nRecruitment Team,\nCalhan Technologies",
        "vendorWhatsAppNumber": cfg.get("vendorWhatsAppNumber") or twilio.get("vendorWhatsAppNumber", ""),
    }


async def _known_client_domain(db, email_address: str) -> bool:
    domain = sender_domain(email_address)
    if not domain:
        return False
    existing = await db["requirements"].find_one(
        {"client_email_domain": domain},
        {"_id": 1},
    )
    if existing:
        return True
    existing = await db["client_emails"].find_one(
        {"from_email": {"$regex": f"@{_re.escape(domain)}$", "$options": "i"}},
        {"_id": 1},
    )
    return bool(existing)


def _decode_pubsub_payload(payload: dict) -> dict:
    data = ((payload.get("message") or {}).get("data") or "").strip()
    if not data:
        return {}
    padded = data + "=" * (-len(data) % 4)
    decoded = _base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    return _json.loads(decoded)


def _public_doc(doc: dict) -> dict:
    clean = {k: v for k, v in (doc or {}).items() if k != "_id"}
    return clean


def _gmail_metadata(gmail_service, message_id: str) -> dict:
    msg = gmail_service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Reply-To", "Subject", "Message-ID"],
    ).execute()
    headers = {h.get("name", "").lower(): h.get("value", "") for h in (msg.get("payload") or {}).get("headers", [])}
    from_name, from_email = _parseaddr(headers.get("reply-to") or headers.get("from", ""))
    received_at = None
    if msg.get("internalDate"):
        try:
            received_at = datetime.utcfromtimestamp(int(msg["internalDate"]) / 1000)
        except Exception:
            received_at = None
    return {
        "email_id": message_id,
        "thread_id": msg.get("threadId"),
        "received_at": received_at or datetime.utcnow(),
        "from_name": from_name,
        "from_email": from_email,
        "subject": headers.get("subject", ""),
        "message_id_header": headers.get("message-id", ""),
        "snippet": msg.get("snippet", ""),
    }


async def _notify_vendor_about_client_email(db, inbox_doc: dict, request: Optional[Request] = None) -> bool:
    cfg = await _client_inbox_settings(db)
    vendor_number = cfg.get("vendorWhatsAppNumber", "")
    if not vendor_number:
        return False
    extracted = inbox_doc.get("extracted") or {}
    reply = inbox_doc.get("generated_reply") or {}
    message = (
        "New client training inquiry\n"
        f"From: {inbox_doc.get('from_name') or inbox_doc.get('from_email')}\n"
        f"Technology: {extracted.get('technology_needed') or '-'}\n"
        f"Urgency: {extracted.get('urgency') or 'normal'}\n"
        f"Confidence: {round(float(extracted.get('confidence') or 0) * 100)}%\n"
        f"Summary: {extracted.get('email_summary') or inbox_doc.get('subject') or ''}\n\n"
        f"Draft: {reply.get('whatsapp_message') or ''}"
    )
    result = await send_whatsapp_message(
        db,
        vendor_number,
        message[:1500],
        event_type="client_requirement_inbox",
        recipient_type="vendor",
        request_base_url=_request_base_url(request) if request else "",
        context={
            "source": "client_inbox",
            "email_id": inbox_doc.get("email_id"),
            "requirement_id": inbox_doc.get("requirement_id"),
        },
    )
    return bool(result.get("success"))


async def _process_and_store_client_message(db, message_id: str, gmail_service, request: Optional[Request] = None) -> dict:
    settings = await _client_inbox_settings(db)
    processed = await process_client_email(message_id, gmail_service)
    extracted = processed.get("extracted") or {}
    extracted["sender_is_known_client"] = await _known_client_domain(db, processed.get("from_email", ""))

    domain = sender_domain(processed.get("from_email", ""))
    whitelist = set(_parse_domain_csv(settings.get("clientDomainsWhitelist", "")))
    domain_is_allowed = not whitelist or domain in whitelist

    if processed.get("is_auto_reply") or not extracted.get("is_training_request"):
        status = "spam"
        generated_reply = {}
        requirement_id = None
    else:
        generated_reply = await generate_calhan_reply(extracted, {
            "subject": processed.get("subject", ""),
            "reply_signature": settings.get("replySignature"),
        })
        duplicate = await check_if_duplicate(extracted, db)
        requirement_id = None if duplicate else await create_requirement_from_email(extracted, message_id, db)
        confidence = float(extracted.get("confidence") or 0)
        threshold = float(settings.get("autoSendThreshold") or 70) / 100
        auto_send_eligible = confidence >= threshold and domain_is_allowed
        status = "auto_sent" if auto_send_eligible and settings.get("autoSendEnabled") else "pending_approval"

    confidence = float(extracted.get("confidence") or 0)
    auto_send_eligible = confidence >= (float(settings.get("autoSendThreshold") or 70) / 100) and domain_is_allowed
    inbox_doc = {
        "email_id": processed.get("email_id"),
        "thread_id": processed.get("thread_id"),
        "received_at": processed.get("received_at"),
        "from_email": processed.get("from_email"),
        "from_name": processed.get("from_name"),
        "subject": processed.get("subject"),
        "raw_body": processed.get("raw_body"),
        "clean_body": processed.get("clean_body"),
        "extracted": extracted,
        "generated_reply": generated_reply,
        "requirement_id": requirement_id,
        "status": status,
        "confidence": confidence,
        "auto_send_eligible": auto_send_eligible,
        "sent_at": None,
        "sent_by": None,
        "whatsapp_notified": False,
        "message_id_header": processed.get("message_id_header", ""),
        "created_at": datetime.utcnow(),
    }

    existing = await db["client_emails"].find_one({"email_id": inbox_doc["email_id"]}, {"_id": 1, "status": 1})
    if existing:
        return {"status": "already_processed", "email_id": inbox_doc["email_id"]}

    inbox_doc["whatsapp_notified"] = await _notify_vendor_about_client_email(db, inbox_doc, request)

    if status == "auto_sent":
        send_result = send_gmail_reply(
            gmail_service,
            to_email=inbox_doc["from_email"],
            subject=generated_reply.get("subject", ""),
            body=generated_reply.get("body", ""),
            thread_id=inbox_doc.get("thread_id") or "",
            in_reply_to=inbox_doc.get("message_id_header") or "",
        )
        inbox_doc["gmail_send_result"] = send_result
        inbox_doc["sent_at"] = datetime.utcnow()
        inbox_doc["sent_by"] = "auto"

    await db["client_emails"].insert_one(inbox_doc)
    if requirement_id:
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        await send_teams_stage_notification(
            db,
            stage="new_requirement_created",
            trainer_name="Not assigned yet",
            requirement=requirement or {"requirement_id": requirement_id},
            request_base_url=_request_base_url(request) if request else "",
            context={"source": "client_inbox", "email_id": inbox_doc["email_id"]},
        )
    return {"status": inbox_doc["status"], "email_id": inbox_doc["email_id"], "requirement_id": requirement_id}


async def _auto_send_pending_client_reply(db, inbox_doc: dict, gmail_service, settings: dict) -> Optional[dict]:
    if not settings.get("autoSendEnabled"):
        return None
    if inbox_doc.get("status") != "pending_approval" or inbox_doc.get("sent_at"):
        return None

    extracted = inbox_doc.get("extracted") or {}
    domain = sender_domain(inbox_doc.get("from_email", ""))
    whitelist = set(_parse_domain_csv(settings.get("clientDomainsWhitelist", "")))
    domain_is_allowed = not whitelist or domain in whitelist
    confidence = float(inbox_doc.get("confidence") or extracted.get("confidence") or 0)
    threshold = float(settings.get("autoSendThreshold") or 70) / 100
    if not domain_is_allowed or confidence < threshold:
        return None

    generated_reply = inbox_doc.get("generated_reply") or {}
    if not inbox_doc.get("from_email") or not generated_reply.get("body"):
        return None

    send_result = send_gmail_reply(
        gmail_service,
        to_email=inbox_doc["from_email"],
        subject=generated_reply.get("subject") or f"Re: {inbox_doc.get('subject') or 'Training Requirement'}",
        body=generated_reply.get("body", ""),
        thread_id=inbox_doc.get("thread_id") or "",
        in_reply_to=inbox_doc.get("message_id_header") or "",
    )
    await db["client_emails"].update_one(
        {"email_id": inbox_doc["email_id"], "status": "pending_approval", "sent_at": None},
        {"$set": {
            "status": "auto_sent",
            "gmail_send_result": send_result,
            "sent_at": datetime.utcnow(),
            "sent_by": "auto",
        }},
    )
    return {
        "status": "auto_sent",
        "email_id": inbox_doc["email_id"],
        "requirement_id": inbox_doc.get("requirement_id"),
    }


def _parse_calendar_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _calendar_datetime_text(start_iso: str, end_iso: str = "") -> tuple[str, str]:
    start_dt = _parse_calendar_datetime(start_iso)
    end_dt = _parse_calendar_datetime(end_iso)
    if start_dt and not end_dt:
        end_dt = start_dt + timedelta(minutes=30)
    return (
        start_dt.isoformat() if start_dt else str(start_iso or "").strip(),
        end_dt.isoformat() if end_dt else str(end_iso or "").strip(),
    )


def _meet_link_from_event(event: dict) -> str:
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    conference = event.get("conferenceData") or {}
    for entry in conference.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return ""


def _slot_reference_from_text(*values: str) -> str:
    text = "\n".join(str(value or "") for value in values)
    match = _re.search(r"\bSLOT-[A-Z0-9]{8,12}\b", text, flags=_re.IGNORECASE)
    return match.group(0).upper() if match else ""


async def _create_google_meet_event(
    *,
    trainer_email: str,
    trainer_name: str,
    client_email: str,
    client_name: str,
    requirement: dict,
    start_iso: str,
    end_iso: str = "",
    timezone_name: str = "Asia/Kolkata",
    slot_reply: str = "",
) -> dict:
    start_text, end_text = _calendar_datetime_text(start_iso, end_iso)
    if not start_text:
        raise RuntimeError("Client confirmed a slot, but no start date/time could be extracted")
    if not end_text:
        raise RuntimeError("Client confirmed a slot, but no end date/time could be prepared")

    technology = requirement.get("technology_needed") or "Training"
    requirement_id = requirement.get("requirement_id") or ""
    attendees = []
    if trainer_email:
        attendees.append({"email": trainer_email, "displayName": trainer_name or "Trainer"})
    if client_email:
        attendees.append({"email": client_email, "displayName": client_name or "Client"})

    event_body = {
        "summary": f"{technology} Trainer Discussion - {trainer_name or 'Trainer'}",
        "description": (
            f"Calhan Technologies trainer discussion/interview.\n\n"
            f"Requirement ID: {requirement_id}\n"
            f"Technology: {technology}\n"
            f"Trainer: {trainer_name or '-'}\n"
            f"Client: {client_name or client_email or '-'}\n\n"
            f"Client confirmed slot from reply:\n{slot_reply[:2000]}"
        ),
        "start": {"dateTime": start_text, "timeZone": timezone_name},
        "end": {"dateTime": end_text, "timeZone": timezone_name},
        "attendees": attendees,
        "conferenceData": {
            "createRequest": {
                "requestId": f"calhan-{uuid.uuid4().hex[:24]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    def _insert_event():
        service = get_calendar_service()
        return service.events().insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

    event = await asyncio.to_thread(_insert_event)
    meet_link = _meet_link_from_event(event)
    return {
        "event_id": event.get("id"),
        "html_link": event.get("htmlLink"),
        "meet_link": meet_link,
        "start": start_text,
        "end": end_text,
        "timezone": timezone_name,
        "raw_event": event,
    }


async def _trainer_contact_for_interview(db, trainer_id: str, requirement_id: str, fallback_name: str = "") -> dict:
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    email = (trainer.get("email") or "").strip()
    if not email:
        latest_log = await db["email_logs"].find_one(
            {
                "trainer_id": trainer_id,
                "requirement_id": requirement_id,
                "to_email": {"$nin": [None, ""]},
            },
            {"_id": 0, "to_email": 1},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        email = (latest_log or {}).get("to_email", "")
    return {
        "trainer": trainer,
        "email": email,
        "name": trainer.get("name") or fallback_name or "Trainer",
        "phone": trainer.get("phone") or "",
    }


async def _send_trainer_interview_schedule(
    db,
    request: Optional[Request],
    *,
    trainer_id: str,
    trainer_name: str,
    to_email: str,
    trainer_phone: str,
    requirement_id: str,
    date_time: str,
    interview_link: str,
    platform: str = "Google Meet",
    source: str = "client_slot_confirmation",
    calendar_event: Optional[dict] = None,
) -> dict:
    if not to_email:
        return {"success": False, "error": "Trainer email not found"}

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    technology = req.get("technology_needed", "Training") if req else "Training"
    subject = f"Interview Schedule Confirmation - {technology}"
    body = (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"The client has confirmed the interview/discussion slot. Please find the final details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        f"Please join on time. Let us know if you need any assistance.\n\n"
        f"Regards,\nRecruitment Team,\nCalhan Technologies"
    )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)

    email_result, whatsapp_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            requirement_id=requirement_id,
            technology=technology,
            date_time=date_time,
            platform=platform,
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request) if request else "",
        ),
    )
    success, error = email_result
    now = datetime.utcnow()

    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": requirement_id,
        "subject": subject,
        "body": body,
        "mail_type": "mail4",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": now,
        "platform": platform,
        "interview_link": interview_link,
        "date_time": date_time,
        "source": source,
        "calendar_event": calendar_event or {},
    })

    email_log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "mail4",
        "interview_scheduled": success,
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": technology,
        "trainer_phone": trainer_phone,
        "calendar_event": calendar_event or {},
        **interview_reminder_fields(date_time),
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
        "created_at": now,
    }
    await db["email_logs"].insert_one(email_log_doc)

    if success:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {"status": "interview_scheduled"}},
        )
        reminder_schedule = await schedule_interview_reminder(
            db,
            email_log=email_log_doc,
            request_base_url=_request_base_url(request) if request else "",
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=trainer_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request) if request else "",
            context={"source": source, "email_id": email_id, "interview_date": date_time},
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "whatsapp": whatsapp_result,
        "teams": teams_result,
        "reminder_schedule": reminder_schedule,
    }


def _recent_enough(sent_at, received_at, days: int = 21) -> bool:
    if not sent_at or not received_at:
        return True
    try:
        if isinstance(sent_at, str):
            sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).replace(tzinfo=None)
        if isinstance(received_at, str):
            received_at = datetime.fromisoformat(received_at.replace("Z", "+00:00")).replace(tzinfo=None)
        return timedelta(0) <= (received_at - sent_at) <= timedelta(days=days)
    except Exception:
        return True


async def _matching_client_slot_email(db, meta: dict, clean_body: str = "") -> Optional[dict]:
    from_email = (meta.get("from_email") or "").strip()
    if not from_email:
        return None

    slot_ref = _slot_reference_from_text(meta.get("subject", ""), meta.get("snippet", ""), clean_body)
    if slot_ref:
        exact = await db["client_slot_emails"].find_one(
            {
                "slot_ref": slot_ref,
                "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
            },
            {"_id": 0},
        )
        if exact:
            return exact

    received_at = meta.get("received_at") or datetime.utcnow()
    candidates = await db["client_slot_emails"].find(
        {
            "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
            "status": {"$in": ["sent", "confirmed_scheduled", "calendar_failed", "trainer_email_failed"]},
            "$or": [{"sent_at": {"$lte": received_at}}, {"sent_at": None}],
        },
        {"_id": 0},
    ).sort("sent_at", -1).limit(25).to_list(25)
    if not candidates:
        return None

    subject_norm = _norm_subject(meta.get("subject", ""))
    body_norm = _re.sub(r"\s+", " ", (clean_body or meta.get("snippet") or "").lower())
    scored = []
    for item in candidates:
        if not _recent_enough(item.get("sent_at"), received_at):
            continue
        slot_subject = _norm_subject(item.get("subject", ""))
        trainer_name = str(item.get("trainer_name") or "").lower()
        requirement_id = str(item.get("requirement_id") or "").lower()
        score = 0
        if slot_subject and (slot_subject in subject_norm or subject_norm in slot_subject):
            score += 140
        if "slot" in subject_norm or "availability" in subject_norm:
            score += 60
        if requirement_id and (requirement_id in subject_norm or requirement_id in body_norm):
            score += 50
        if trainer_name and trainer_name in body_norm:
            score += 40
        if _re.search(r"\b(confirm|confirmed|works|okay|ok|fine|available|schedule|book)\b", body_norm):
            score += 35
        if _re.search(r"\b(\d{1,2}(:\d{2})?\s*(am|pm)?|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", body_norm):
            score += 35
        scored.append((score, item))

    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1] if scored[0][0] >= 100 else None


async def _process_client_slot_reply(
    db,
    message_id: str,
    gmail_service,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
    slot_doc: Optional[dict] = None,
) -> Optional[dict]:
    existing = await db["client_slot_confirmations"].find_one({"gmail_message_id": message_id}, {"_id": 0})
    if existing and existing.get("status") not in {"calendar_failed", "trainer_email_failed"}:
        return {
            "status": "already_processed_client_slot_reply",
            "email_id": message_id,
            "requirement_id": existing.get("requirement_id"),
            "trainer_id": existing.get("trainer_id"),
        }

    meta = fetch_gmail_email(message_id, gmail_service)
    if meta_hint:
        meta = {**meta_hint, **meta}
    clean_body = _strip_quoted_reply_text(meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or "")
    slot_doc = slot_doc or await _matching_client_slot_email(db, meta, clean_body)
    if not slot_doc:
        return None

    requirement_id = slot_doc.get("requirement_id", "")
    trainer_id = slot_doc.get("trainer_id", "")
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer_contact = await _trainer_contact_for_interview(
        db,
        trainer_id,
        requirement_id,
        slot_doc.get("trainer_name", ""),
    )
    client_name = slot_doc.get("client_name") or meta.get("from_name") or "Client"
    timezone_name = requirement.get("timezone") or "Asia/Kolkata"

    parsed = await extract_client_slot_confirmation(
        clean_body,
        slot_doc.get("slot_text", ""),
        {
            "timezone": timezone_name,
            "requirement_id": requirement_id,
            "technology": requirement.get("technology_needed") or "",
            "trainer_name": trainer_contact.get("name") or slot_doc.get("trainer_name", ""),
            "client_email": meta.get("from_email") or slot_doc.get("to_email"),
        },
    )

    now = datetime.utcnow()
    confirmation_id = existing.get("confirmation_id") if existing else f"CLIENT-CONF-{uuid.uuid4().hex[:8].upper()}"
    base_doc = {
        "confirmation_id": confirmation_id,
        "gmail_message_id": message_id,
        "thread_id": meta.get("thread_id"),
        "client_slot_email_id": slot_doc.get("email_id"),
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_contact.get("name") or slot_doc.get("trainer_name"),
        "trainer_email": trainer_contact.get("email"),
        "client_email": meta.get("from_email") or slot_doc.get("to_email"),
        "client_name": client_name,
        "subject": meta.get("subject"),
        "reply_text": clean_body,
        "parsed_slot": parsed,
        "updated_at": now,
    }
    if not existing:
        base_doc["created_at"] = now

    if not parsed.get("confirmed") or not parsed.get("start_iso") or float(parsed.get("confidence") or 0) < 0.5:
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "needs_manual_review", "error": parsed.get("reason") or ""}},
            upsert=True,
        )
        await db["client_slot_emails"].update_one(
            {"email_id": slot_doc.get("email_id")},
            {"$set": {
                "last_client_reply_at": now,
                "last_client_reply_text": clean_body,
                "last_client_reply_parse": parsed,
            }},
        )
        return {
            "status": "client_slot_needs_review",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "reason": parsed.get("reason"),
        }

    if not trainer_contact.get("email"):
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "trainer_email_missing", "error": "Trainer email not found"}},
            upsert=True,
        )
        return {
            "status": "trainer_email_missing",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        }

    try:
        calendar_event = await _create_google_meet_event(
            trainer_email=trainer_contact["email"],
            trainer_name=trainer_contact["name"],
            client_email=meta.get("from_email") or slot_doc.get("to_email") or "",
            client_name=client_name,
            requirement=requirement or {"requirement_id": requirement_id},
            start_iso=parsed.get("start_iso", ""),
            end_iso=parsed.get("end_iso", ""),
            timezone_name=parsed.get("timezone") or timezone_name,
            slot_reply=clean_body,
        )
    except Exception as exc:
        error = str(exc)
        await db["client_slot_confirmations"].update_one(
            {"confirmation_id": confirmation_id},
            {"$set": {**base_doc, "status": "calendar_failed", "error": error}},
            upsert=True,
        )
        await db["client_slot_emails"].update_one(
            {"email_id": slot_doc.get("email_id")},
            {"$set": {
                "status": "calendar_failed",
                "client_confirmed_at": now,
                "client_confirmed_slot": parsed,
                "calendar_error": error,
            }},
        )
        return {
            "status": "calendar_failed",
            "email_id": message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "error": error,
        }

    meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or ""
    date_time = parsed.get("start_iso") or calendar_event.get("start") or parsed.get("date_time_text")
    send_result = await _send_trainer_interview_schedule(
        db,
        request,
        trainer_id=trainer_id,
        trainer_name=trainer_contact["name"],
        to_email=trainer_contact["email"],
        trainer_phone=trainer_contact.get("phone", ""),
        requirement_id=requirement_id,
        date_time=date_time,
        interview_link=meet_link,
        platform="Google Meet",
        source="client_slot_confirmation",
        calendar_event=calendar_event,
    )
    final_status = "confirmed_scheduled" if send_result.get("success") else "trainer_email_failed"
    await db["client_slot_confirmations"].update_one(
        {"confirmation_id": confirmation_id},
        {"$set": {
            **base_doc,
            "status": final_status,
            "calendar_event": calendar_event,
            "trainer_schedule_email": send_result,
            "scheduled_at": now,
            "error": send_result.get("error") or "",
        }},
        upsert=True,
    )
    await db["client_slot_emails"].update_one(
        {"email_id": slot_doc.get("email_id")},
        {"$set": {
            "status": final_status,
            "client_confirmed_at": now,
            "client_confirmed_slot": parsed,
            "client_reply_message_id": message_id,
            "calendar_event": calendar_event,
            "trainer_schedule_email": send_result,
        }},
    )
    return {
        "status": final_status,
        "email_id": message_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_email_sent": bool(send_result.get("success")),
        "meet_link": meet_link,
        "calendar_event_id": calendar_event.get("event_id"),
    }


async def _sync_recent_client_inbox(db, request: Optional[Request] = None, max_results: int = 25) -> dict:
    service = get_gmail_service()
    settings = await _client_inbox_settings(db)
    whitelist = _parse_domain_csv(settings.get("clientDomainsWhitelist", ""))
    listed = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        q="newer_than:7d",
        maxResults=max(1, min(int(max_results or 25), 100)),
    ).execute()

    processed = []
    skipped = 0
    already_processed = 0
    auto_sent_existing = []
    errors = []

    for item in listed.get("messages", []) or []:
        message_id = item.get("id")
        if not message_id:
            continue
        existing = await db["client_emails"].find_one({"email_id": message_id}, {"_id": 0})
        if existing:
            auto_sent = await _auto_send_pending_client_reply(db, existing, service, settings)
            if auto_sent:
                auto_sent_existing.append(auto_sent)
            already_processed += 1
            continue
        try:
            meta = _gmail_metadata(service, message_id)
            slot_doc = await _matching_client_slot_email(db, meta)
            if slot_doc:
                slot_result = await _process_client_slot_reply(
                    db,
                    message_id,
                    service,
                    request,
                    meta_hint=meta,
                    slot_doc=slot_doc,
                )
                if slot_result:
                    processed.append(slot_result)
                    continue
            known_domain = await _known_client_domain(db, meta.get("from_email", ""))
            likely_training = known_domain or is_likely_training_email(
                meta.get("subject", ""),
                meta.get("from_email", ""),
                whitelist,
                meta.get("snippet", ""),
            )
            if not likely_training:
                skipped += 1
                continue
            processed.append(await _process_and_store_client_message(db, message_id, service, request))
        except Exception as exc:
            errors.append({"email_id": message_id, "error": str(exc)})

    await db["gmail_sync"].update_one(
        {"sync_id": "default"},
        {"$set": {
            "last_manual_sync_at": datetime.utcnow(),
            "last_manual_sync_processed": len(processed),
            "last_manual_sync_skipped": skipped,
            "last_manual_sync_auto_sent_existing": len(auto_sent_existing),
            "last_manual_sync_errors": errors[-5:],
        }},
        upsert=True,
    )
    return {
        "success": True,
        "processed": processed,
        "processed_count": len(processed),
        "auto_sent_existing": auto_sent_existing,
        "auto_sent_existing_count": len(auto_sent_existing),
        "skipped": skipped,
        "already_processed": already_processed,
        "errors": errors,
    }


TOC_SYSTEM_PROMPT = """You are an expert curriculum designer and corporate trainer with 15+ years of experience
designing professional training programs for IT companies, MNCs, and corporate clients.

Your task is to generate a detailed, professional Training Table of Contents (TOC) / Course Curriculum.

RULES:
1. Structure the curriculum day-by-day with clear session breakdowns
2. Each day has Morning Session (9:30 AM – 1:00 PM) and Afternoon Session (2:00 PM – 5:30 PM)
3. Each session has 3-5 topics with 10-20 minute time slots per topic
4. Include hands-on Lab Exercises at the end of each session (45-60 mins)
5. Include a Recap & Q&A (15 mins) at start of each day (except Day 1)
6. Day 1 starts with: Introduction & Expectations (30 mins) + Environment Setup (30 mins)
7. Last day ends with: Final Project / Capstone (2 hrs) + Assessment & Certification Guidance (30 mins) + Feedback & Closing (15 mins)
8. Topics must be technically accurate, industry-relevant, and progressive (basic to advanced)
9. Lab exercises must be practical, hands-on, and relevant to the day's topics
10. Adjust depth and complexity based on audience_level (beginner/intermediate/advanced)
11. For Online mode: include "Check-in Poll" at session start, "Breakout Room Activity" for labs
12. For Offline mode: include "Whiteboard Activity" and "Group Discussion" segments

OUTPUT FORMAT (respond ONLY with valid JSON, no markdown, no explanation):
{
  "title": "Complete [Technology] Training Program",
  "subtitle": "[Duration]-Day [Level] Training | [Mode] Mode",
  "overview": "2-3 sentence program overview",
  "prerequisites": ["prereq1", "prereq2"],
  "learning_outcomes": ["outcome1", "outcome2", "outcome3", "outcome4", "outcome5"],
  "days": [
    {
      "day": 1,
      "title": "Day 1: [Theme]",
      "morning_session": {
        "time": "9:30 AM – 1:00 PM",
        "title": "Session Title",
        "topics": [
          { "time": "9:30 – 10:00", "topic": "Introduction & Expectations", "type": "lecture" },
          { "time": "10:00 – 10:45", "topic": "Topic Name", "type": "lecture" },
          { "time": "10:45 – 11:00", "topic": "Break", "type": "break" },
          { "time": "11:00 – 12:00", "topic": "Topic Name", "type": "demo" },
          { "time": "12:00 – 1:00", "topic": "Lab: Lab Title", "type": "lab" }
        ]
      },
      "afternoon_session": {
        "time": "2:00 PM – 5:30 PM",
        "title": "Session Title",
        "topics": [
          { "time": "2:00 – 3:00", "topic": "Topic Name", "type": "lecture" },
          { "time": "3:00 – 3:15", "topic": "Break", "type": "break" },
          { "time": "3:15 – 4:15", "topic": "Topic Name", "type": "demo" },
          { "time": "4:15 – 5:15", "topic": "Lab: Lab Title", "type": "lab" },
          { "time": "5:15 – 5:30", "topic": "Day Summary & Q&A", "type": "qa" }
        ]
      }
    }
  ],
  "tools_software": ["tool1", "tool2"],
  "certification_guidance": "What certification this training prepares for",
  "trainer_notes": "Special instructions or tips for the trainer"
}
"""


def _toc_user_prompt(payload: dict) -> str:
    technology = payload.get("technology") or "Training"
    duration_days = int(payload.get("duration_days") or 1)
    audience_level = payload.get("audience_level") or "intermediate"
    mode = payload.get("mode") or "Online"
    custom_topics = (payload.get("custom_topics") or "").strip()
    if payload.get("toc_type") == "custom":
        return f"""Generate a structured Training Table of Contents for:
- Technology/Domain: {technology}
- Duration: {duration_days} days
- Audience Level: {audience_level}
- Training Mode: {mode}
- Client has specified these topics to cover: {custom_topics}

Structure these exact topics into a logical day-by-day curriculum with proper time slots and lab exercises.
Do not add extra topics beyond what's specified, but you can add sub-topics and labs for each.
"""
    return f"""Generate a complete Training Table of Contents for:
- Technology/Domain: {technology}
- Duration: {duration_days} days
- Audience Level: {audience_level}
- Training Mode: {mode}
- Generate comprehensive, industry-standard curriculum covering all major topics
"""


async def _generate_toc_with_claude(payload: dict) -> dict:
    import httpx as _httpx
    settings = get_settings()
    api_key = os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")
    full_prompt = TOC_SYSTEM_PROMPT + "\n\n" + _toc_user_prompt(payload)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    async with _httpx.AsyncClient(timeout=120) as client:
        res = await client.post(url, json={
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8000},
        })
        res.raise_for_status()
        data = res.json()
    raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
    raw = _re.sub(r"^```(?:json)?\s*", "", raw)
    raw = _re.sub(r"\s*```$", "", raw).strip()
    match = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if not match:
        raise ValueError(f"Gemini did not return valid JSON for TOC. Response: {raw[:300]}")
    return _json.loads(match.group())


def _clean_filename(value: str) -> str:
    cleaned = _re.sub(r"[^A-Za-z0-9._-]+", "_", value or "toc").strip("_")
    return cleaned[:80] or "toc"


def _toc_html(doc: dict) -> str:
    toc = doc.get("toc_data") or {}

    def esc(value):
        return _html.escape(str(value or ""))

    def li(items):
        return "".join(f"<li>{esc(item)}</li>" for item in (items or []))

    day_blocks = []
    for day in toc.get("days") or []:
        sessions = []
        for key, label in (("morning_session", "Morning Session"), ("afternoon_session", "Afternoon Session")):
            session = day.get(key) or {}
            rows = "".join(
                f"<tr><td>{esc(topic.get('time'))}</td><td>{esc(topic.get('topic'))}</td><td>{esc(topic.get('type'))}</td></tr>"
                for topic in (session.get("topics") or [])
            )
            sessions.append(f"""
              <div class="session">
                <h4>{label}: {esc(session.get('title'))}</h4>
                <p class="time">{esc(session.get('time'))}</p>
                <table>
                  <thead><tr><th>Time</th><th>Topic</th><th>Type</th></tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            """)
        day_blocks.append(f"""
          <section class="day">
            <h3>{esc(day.get('title') or f"Day {day.get('day', '')}")}</h3>
            {''.join(sessions)}
          </section>
        """)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{esc(toc.get('title'))}</title>
  <style>
    body {{ font-family: Arial, sans-serif; color:#1f2937; margin:0; background:#f8fafc; }}
    .page {{ width: 900px; margin: 0 auto; background:#fff; padding: 44px; }}
    .brand {{ color:#2563eb; font-weight:700; font-size:13px; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:8px 0 6px; font-size:30px; color:#0f172a; }}
    h2 {{ margin:0 0 18px; font-size:16px; color:#475569; font-weight:500; }}
    h3 {{ margin:26px 0 12px; padding:10px 12px; background:#eff6ff; color:#1d4ed8; border-radius:8px; }}
    h4 {{ margin:14px 0 4px; font-size:15px; color:#0f172a; }}
    .meta, .overview, .box {{ border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin:14px 0; }}
    .meta {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; font-size:13px; }}
    .time {{ margin:0 0 8px; color:#64748b; font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; margin:8px 0 14px; font-size:12px; }}
    th {{ text-align:left; background:#f1f5f9; color:#334155; }}
    th, td {{ border:1px solid #e2e8f0; padding:8px; vertical-align:top; }}
    ul {{ margin:8px 0 0 20px; padding:0; }}
    li {{ margin:5px 0; }}
    .footer {{ margin-top:28px; padding-top:14px; border-top:1px solid #e2e8f0; color:#64748b; font-size:12px; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="brand">Calhan Technologies · TrainerSync</div>
    <h1>{esc(toc.get('title'))}</h1>
    <h2>{esc(toc.get('subtitle'))}</h2>
    <div class="meta">
      <div><strong>Technology:</strong> {esc(doc.get('technology'))}</div>
      <div><strong>Trainer:</strong> {esc(doc.get('trainer_name'))}</div>
      <div><strong>Duration:</strong> {esc(doc.get('duration_days'))} day(s)</div>
      <div><strong>Mode:</strong> {esc(doc.get('mode'))}</div>
      <div><strong>Audience:</strong> {esc(doc.get('audience_level'))}</div>
      <div><strong>Reference:</strong> {esc(doc.get('toc_id'))}</div>
    </div>
    <div class="overview"><strong>Program Overview</strong><br>{esc(toc.get('overview'))}</div>
    <div class="box"><strong>Prerequisites</strong><ul>{li(toc.get('prerequisites'))}</ul></div>
    <div class="box"><strong>Learning Outcomes</strong><ul>{li(toc.get('learning_outcomes'))}</ul></div>
    {''.join(day_blocks)}
    <div class="box"><strong>Tools & Software</strong><ul>{li(toc.get('tools_software'))}</ul></div>
    <div class="box"><strong>Certification Guidance</strong><br>{esc(toc.get('certification_guidance'))}</div>
    <div class="box"><strong>Trainer Notes</strong><br>{esc(toc.get('trainer_notes'))}</div>
    <div class="footer">Generated by TrainerSync for Calhan Technologies.</div>
  </div>
</body>
</html>"""


def _toc_pdf_bytes(doc: dict) -> bytes:
    toc = doc.get("toc_data") or {}
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    margin = 42
    y = 42

    def new_page():
        nonlocal page, y
        page = pdf.new_page(width=595, height=842)
        y = 42

    def write(text: str, size: int = 10, color=(31 / 255, 41 / 255, 55 / 255), bold: bool = False, gap: int = 8):
        nonlocal y
        text = str(text or "")
        font = "helv"
        rect = fitz.Rect(margin, y, 553, 820)
        needed = max(18, (len(text) // 85 + 1) * (size + 4))
        if y + needed > 810:
            new_page()
            rect = fitz.Rect(margin, y, 553, 820)
        consumed = page.insert_textbox(rect, text, fontsize=size, fontname=font, color=color, align=0)
        y += max(needed, abs(consumed) if consumed < 0 else needed) + gap

    def bullet_list(title: str, items: list):
        write(title, size=13, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
        for item in items or []:
            write(f"- {item}", size=9, gap=2)
        y_gap(6)

    def y_gap(amount: int):
        nonlocal y
        y += amount

    write("Calhan Technologies | TrainerSync", size=9, bold=True, color=(37 / 255, 99 / 255, 235 / 255), gap=10)
    write(toc.get("title", "Training Table of Contents"), size=20, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
    write(toc.get("subtitle", ""), size=11, color=(71 / 255, 85 / 255, 105 / 255), gap=14)
    write(f"Technology: {doc.get('technology', '')} | Duration: {doc.get('duration_days', '')} day(s) | Mode: {doc.get('mode', '')} | Trainer: {doc.get('trainer_name', '')}", size=9, gap=12)
    write("Program Overview", size=13, bold=True, color=(15 / 255, 23 / 255, 42 / 255), gap=4)
    write(toc.get("overview", ""), size=10, gap=10)
    bullet_list("Prerequisites", toc.get("prerequisites", []))
    bullet_list("Learning Outcomes", toc.get("learning_outcomes", []))

    for day in toc.get("days") or []:
        write(day.get("title") or f"Day {day.get('day', '')}", size=14, bold=True, color=(29 / 255, 78 / 255, 216 / 255), gap=6)
        for key, label in (("morning_session", "Morning Session"), ("afternoon_session", "Afternoon Session")):
            session = day.get(key) or {}
            write(f"{label}: {session.get('title', '')} ({session.get('time', '')})", size=11, bold=True, gap=4)
            for topic in session.get("topics") or []:
                write(f"{topic.get('time', '')} - {topic.get('topic', '')} [{topic.get('type', '')}]", size=8, gap=1)
            y_gap(5)

    bullet_list("Tools & Software", toc.get("tools_software", []))
    write("Certification Guidance", size=13, bold=True, gap=4)
    write(toc.get("certification_guidance", ""), size=10, gap=8)
    write("Trainer Notes", size=13, bold=True, gap=4)
    write(toc.get("trainer_notes", ""), size=10, gap=8)

    out = pdf.tobytes()
    pdf.close()
    return out


def _send_toc_email_with_attachment(to_email: str, subject: str, body: str, filename: str, pdf_bytes: bytes, smtp_config: dict) -> tuple:
    settings = get_settings()
    gmail_user = smtp_config.get("smtpUser") or getattr(settings, "gmail_user", "")
    gmail_pass = (smtp_config.get("smtpPass") or get_gmail_password()).replace(" ", "")
    from_name = smtp_config.get("fromName") or getattr(settings, "from_name", "TrainerSync")
    from_email = smtp_config.get("fromEmail") or getattr(settings, "from_email", "") or gmail_user
    smtp_host = smtp_config.get("smtpHost") or "smtp.gmail.com"
    smtp_port = int(smtp_config.get("smtpPort") or 587)

    if not gmail_user or not gmail_pass:
        return False, "Gmail credentials not set in .env or Admin email settings"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Reply-To"] = from_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    try:
        try:
            ssl_port = 465 if smtp_port == 587 else smtp_port
            with smtplib.SMTP_SSL(smtp_host, ssl_port, timeout=20) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        except Exception:
            starttls_port = smtp_port if smtp_port != 465 else 587
            with smtplib.SMTP(smtp_host, starttls_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, [to_email], msg.as_string())
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _list_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {val}" for key, val in value.items())
    return str(value or "")


def _category_combined_text(trainer: dict, category_data: dict) -> str:
    parts = [
        trainer.get("name", ""),
        trainer.get("technologies", ""),
        _list_text(trainer.get("skills", [])),
        _list_text(trainer.get("certifications", [])),
        trainer.get("summary", ""),
        category_data.get("primary_category", ""),
        category_data.get("domain", ""),
        _list_text(category_data.get("secondary_categories", [])),
        _list_text(category_data.get("specialisation_tags", [])),
        _list_text(category_data.get("industry_focus", [])),
        _list_text(category_data.get("language_of_delivery", [])),
        _list_text(category_data.get("skill_level_map", {})),
        trainer.get("resume", "")[:50000],
    ]
    return " ".join(parts).lower()


async def _distinct_non_empty(db, field: str) -> List[str]:
    values = await db["trainers"].distinct(field, {field: {"$nin": [None, ""]}})
    cleaned = {str(value).strip() for value in values if str(value).strip()}
    return sorted(cleaned, key=lambda item: item.lower())


async def _software_domains(db) -> List[str]:
    existing = await _distinct_non_empty(db, "domain")
    software_existing = [domain for domain in existing if is_software_domain(domain)]
    return sorted(set(SOFTWARE_TECH_DOMAINS + software_existing), key=lambda item: item.lower())


async def _categorise_and_update_trainer(db, trainer: dict) -> dict:
    category_data = await categorise_trainer(trainer)
    update_fields = category_update_fields(category_data)
    update_fields["combined_text"] = _category_combined_text(trainer, category_data)
    await db["trainers"].update_one(
        {"trainer_id": trainer["trainer_id"]},
        {
            "$set": update_fields,
            "$unset": {"categorisation_error": "", "categorisation_failed_at": ""},
        },
    )
    updated = await db["trainers"].find_one({"trainer_id": trainer["trainer_id"]}, {"_id": 0})
    return {"category": category_data, "trainer": updated}


async def _categorise_trainer_by_id(db, trainer_id: str) -> dict:
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    return await _categorise_and_update_trainer(db, trainer)


async def _categorise_trainers_background(trainer_ids: List[str]):
    db = get_db()
    for trainer_id in dict.fromkeys(trainer_ids):
        try:
            await _categorise_trainer_by_id(db, trainer_id)
        except Exception as exc:
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {
                    "categorisation_error": str(exc),
                    "categorisation_failed_at": datetime.utcnow(),
                }},
            )


async def _run_categorisation_job(job_id: str):
    db = get_db()
    CATEGORISATION_JOBS[job_id].update({
        "status": "running",
        "started_at": datetime.utcnow(),
    })
    try:
        result = await bulk_categorise_all(db)
        CATEGORISATION_JOBS[job_id].update({
            **result,
            "status": "completed",
            "completed_at": datetime.utcnow(),
        })
    except Exception as exc:
        CATEGORISATION_JOBS[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": datetime.utcnow(),
        })


# --- Admin Settings ---------------------------------------------------------

@router.get("/admin/settings")
async def get_admin_settings():
    db = get_db()
    settings = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0},
    )
    return settings or {}


@router.post("/admin/settings")
async def save_admin_settings(payload: dict):
    db = get_db()
    payload = {
        **payload,
        "settings_id": "default",
        "updated_at": datetime.utcnow(),
    }
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": payload},
        upsert=True,
    )
    return {"message": "Admin settings saved"}


@router.post("/admin/whatsapp/test")
async def test_whatsapp_settings(request: Request):
    db = get_db()
    cfg = await get_twilio_config(db)
    result = await send_whatsapp_message(
        db,
        cfg.get("vendorWhatsAppNumber", ""),
        "TrainerSync WhatsApp test message. Your Twilio configuration is connected.",
        event_type="admin_test",
        recipient_type="vendor",
        request_base_url=_request_base_url(request),
        context={"source": "admin_settings"},
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "WhatsApp test failed")
    return {"message": "WhatsApp test sent", **result}


@router.post("/auth/forgot-password")
async def forgot_password(payload: dict):
    email = (payload.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Enter a valid email address")

    db = get_db()
    reset_link = "http://localhost:5173/login?reset=1"
    subject = "Reset your TrainerSync password"
    body = (
        "Hello,\n\n"
        "We received a request to reset your TrainerSync password.\n\n"
        f"Reset link: {reset_link}\n\n"
        "If you did not request this, you can ignore this email.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(email, subject, body, smtp_config)
    if not success:
        raise HTTPException(500, error or "Could not send reset email")

    await db["password_reset_logs"].insert_one({
        "email": email,
        "status": "sent",
        "sent_at": datetime.utcnow(),
    })
    return {"message": "Reset email sent"}


@router.get("/email-open/{email_id}", name="track_email_open")
async def track_email_open(email_id: str, request: Request):
    db = get_db()
    now = datetime.utcnow()
    user_agent = request.headers.get("user-agent", "")
    client_ip = request.client.host if request.client else ""
    existing = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0, "opened_at": 1, "open_count": 1})

    set_fields = {
        "opened": True,
        "last_opened_at": now,
        "last_open_user_agent": user_agent,
        "last_open_ip": client_ip,
    }
    if not existing or not existing.get("opened_at"):
        set_fields["opened_at"] = now
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {
            "$set": set_fields,
            "$inc": {"open_count": 1},
        },
    )
    log = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    if log:
        await db["conversations"].update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "opened": True,
                    "opened_at": log.get("opened_at") or now,
                    "last_opened_at": now,
                    "open_count": (existing or {}).get("open_count", 0) + 1,
                }
            },
        )

    return Response(
        content=TRACKING_PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.post("/whatsapp/status-callback")
async def whatsapp_status_callback(request: Request):
    db = get_db()
    form = await request.form()
    payload = dict(form)
    return await update_whatsapp_status(db, payload)


@router.post("/whatsapp/inbound-callback")
async def whatsapp_inbound_callback(request: Request):
    db = get_db()
    form = await request.form()
    payload = dict(form)
    from_number = payload.get("From", "")
    to_number = payload.get("To", "")
    body = payload.get("Body", "")
    message_sid = payload.get("MessageSid") or payload.get("SmsSid") or ""
    existing = await db["whatsapp_logs"].find_one({"twilio_sid": message_sid}, {"_id": 1}) if message_sid else None
    if not existing:
        await db["whatsapp_logs"].insert_one({
            "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "event_type": "whatsapp_reply",
            "recipient_type": "trainer",
            "to_number": to_number,
            "from_number": from_number,
            "body": body,
            "status": "received",
            "twilio_sid": message_sid,
            "twilio_response": payload,
            "context": {"source": "twilio_inbound"},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
    reply_text = "Thanks for your response. TrainerSync has received your WhatsApp message and will update the trainer pipeline shortly."
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{_html.escape(reply_text)}</Message></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


# --- AI Training TOC Generator ---------------------------------------------

@router.post("/toc/generate")
async def generate_training_toc(payload: dict):
    required = ["requirement_id", "trainer_id", "trainer_name", "trainer_email", "technology", "duration_days"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    try:
        duration_days = int(payload.get("duration_days"))
    except Exception:
        raise HTTPException(400, "duration_days must be a number")
    if duration_days < 1 or duration_days > 15:
        raise HTTPException(400, "duration_days must be between 1 and 15")
    if payload.get("toc_type") == "custom" and not (payload.get("custom_topics") or "").strip():
        raise HTTPException(400, "custom_topics is required for custom TOC mode")

    try:
        toc_data = await _generate_toc_with_claude({**payload, "duration_days": duration_days})
    except Exception as exc:
        raise HTTPException(500, f"TOC generation failed: {exc}")

    db = get_db()
    toc_id = f"TOC-{uuid.uuid4().hex[:8].upper()}"
    doc = {
        "toc_id": toc_id,
        "requirement_id": payload.get("requirement_id"),
        "trainer_id": payload.get("trainer_id"),
        "trainer_name": payload.get("trainer_name"),
        "trainer_email": payload.get("trainer_email"),
        "technology": payload.get("technology"),
        "duration_days": duration_days,
        "audience_level": payload.get("audience_level") or "intermediate",
        "mode": payload.get("mode") or "Online",
        "toc_type": payload.get("toc_type") or "standard",
        "custom_topics": payload.get("custom_topics") or "",
        "toc_data": toc_data,
        "status": "draft",
        "created_at": datetime.utcnow(),
    }
    await db["toc_documents"].insert_one(doc)
    return {"toc_id": toc_id, "toc_data": toc_data, "message": "TOC generated successfully"}


@router.post("/toc/generate-pdf")
async def generate_toc_pdf(payload: dict):
    toc_id = payload.get("toc_id")
    if not toc_id:
        raise HTTPException(400, "toc_id is required")
    db = get_db()
    doc = await db["toc_documents"].find_one({"toc_id": toc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "TOC document not found")

    html = _toc_html(doc)
    pdf_bytes = _toc_pdf_bytes(doc)
    await db["toc_documents"].update_one(
        {"toc_id": toc_id},
        {"$set": {"html": html, "pdf_generated_at": datetime.utcnow()}},
    )
    filename = f"{_clean_filename(doc.get('technology', 'training'))}_{toc_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/toc/send-email")
async def send_toc_email(payload: dict):
    toc_id = payload.get("toc_id")
    if not toc_id:
        raise HTTPException(400, "toc_id is required")
    db = get_db()
    doc = await db["toc_documents"].find_one({"toc_id": toc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "TOC document not found")

    toc = doc.get("toc_data") or {}
    subject = payload.get("subject") or f"Training TOC / Course Agenda - {doc.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {doc.get('trainer_name') or 'Trainer'},\n\n"
        f"Please find attached the AI-generated Training Table of Contents for "
        f"{doc.get('technology', 'the training requirement')}.\n\n"
        "Kindly review the curriculum and share any changes or additions required before we share it with the client.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    pdf_bytes = _toc_pdf_bytes(doc)
    filename = f"{_clean_filename(doc.get('technology', 'training'))}_{toc_id}.pdf"
    smtp_config = await get_admin_email_config(db)
    success, error = _send_toc_email_with_attachment(
        doc.get("trainer_email", ""),
        subject,
        body,
        filename,
        pdf_bytes,
        smtp_config,
    )

    sent_at = datetime.utcnow()
    await db["toc_documents"].update_one(
        {"toc_id": toc_id},
        {"$set": {
            "status": "sent" if success else "send_failed",
            "sent_at": sent_at if success else None,
            "send_error": error,
            "email_subject": subject,
            "email_body": body,
        }},
    )
    await db["conversations"].insert_one({
        "trainer_id": doc.get("trainer_id"),
        "trainer_name": doc.get("trainer_name"),
        "to_email": doc.get("trainer_email"),
        "requirement_id": doc.get("requirement_id"),
        "subject": subject,
        "body": body,
        "mail_type": "toc_generated",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "toc_id": toc_id,
        "toc_title": toc.get("title", ""),
    })
    if not success:
        raise HTTPException(500, error or "TOC email failed")
    return {"success": True, "message": "TOC sent to trainer successfully", "toc_id": toc_id}


# --- Document Agent: Purchase Orders ---------------------------------------

async def _next_purchase_order_number(db) -> str:
    year = datetime.utcnow().year
    doc = await db["counters"].find_one_and_update(
        {"_id": f"purchase_orders:{year}"},
        {
            "$inc": {"sequence": 1},
            "$setOnInsert": {"created_at": datetime.utcnow(), "type": "purchase_orders", "year": year},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"PO-{year}-{int(doc.get('sequence', 1)):04d}"


def _purchase_order_download_url(request: Request, po_id: str) -> str:
    return str(request.url_for("download_purchase_order", po_id=po_id))


def _purchase_order_pdf_from_doc(po_doc: dict) -> bytes:
    encoded = po_doc.get("pdf_base64")
    if encoded:
        return _base64.b64decode(encoded)
    html = po_doc.get("html") or render_purchase_order_html(po_doc)
    return purchase_order_pdf_bytes(po_doc, html)


@router.post("/purchase-orders/generate")
async def generate_purchase_order(payload: dict, request: Request):
    trainer_id = payload.get("trainer_id")
    requirement_id = payload.get("requirement_id")
    if not trainer_id or not requirement_id:
        raise HTTPException(400, "trainer_id and requirement_id are required")

    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    po_number = await _next_purchase_order_number(db)
    po_id = f"PO-DOC-{uuid.uuid4().hex[:8].upper()}"
    po_doc = build_purchase_order_doc(trainer, requirement, payload, po_number)
    if (po_doc.get("commercials") or {}).get("total_amount", 0) <= 0:
        raise HTTPException(400, "day_rate or total_amount is required to generate a purchase order")
    po_doc.update({
        "po_id": po_id,
        "download_url": _purchase_order_download_url(request, po_id),
        "source": "shortlist",
    })

    try:
        html = render_purchase_order_html(po_doc)
        pdf_bytes = purchase_order_pdf_bytes(po_doc, html)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF generation failed: {exc}")

    po_doc.update({
        "html": html,
        "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_content_type": "application/pdf",
        "pdf_filename": purchase_order_filename(po_doc),
        "pdf_generated_at": datetime.utcnow(),
    })
    await db["purchase_orders"].insert_one(po_doc)
    await send_teams_stage_notification(
        db,
        stage="po_generated",
        trainer=po_doc.get("trainer") or {},
        requirement=po_doc.get("requirement") or {},
        request_base_url=_request_base_url(request),
        context={"source": "purchase_order", "po_id": po_id, "po_number": po_doc.get("po_number")},
    )

    return {
        "success": True,
        "message": "Purchase order generated",
        "purchase_order": public_purchase_order(po_doc),
    }


@router.get("/purchase-orders/{po_id}/download", name="download_purchase_order")
async def download_purchase_order(po_id: str):
    db = get_db()
    doc = await db["purchase_orders"].find_one({"po_id": po_id})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    try:
        pdf_bytes = _purchase_order_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF download failed: {exc}")

    if not doc.get("pdf_base64"):
        await db["purchase_orders"].update_one(
            {"po_id": po_id},
            {"$set": {
                "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
                "pdf_generated_at": datetime.utcnow(),
            }},
        )

    filename = doc.get("pdf_filename") or purchase_order_filename(doc)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/purchase-orders/{po_id}/send")
async def send_purchase_order(po_id: str, payload: dict, request: Request):
    db = get_db()
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Purchase order not found")

    trainer = doc.get("trainer") or {}
    requirement = doc.get("requirement") or {}
    commercials = doc.get("commercials") or {}
    to_email = payload.get("to_email") or trainer.get("email")
    if not to_email:
        raise HTTPException(400, "Trainer email is required to send PO")

    try:
        pdf_bytes = _purchase_order_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Purchase order PDF generation failed: {exc}")

    filename = doc.get("pdf_filename") or purchase_order_filename(doc)
    subject = payload.get("subject") or f"Purchase Order {doc.get('po_number')} - {requirement.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {trainer.get('name') or 'Trainer'},\n\n"
        f"Please find attached Purchase Order {doc.get('po_number')} for the "
        f"{requirement.get('technology', 'training')} engagement.\n\n"
        f"Grand Total: {commercials.get('currency', 'INR')} {commercials.get('grand_total', 0):,.2f}\n"
        f"Payment Terms: {doc.get('payment_terms')}\n\n"
        "Kindly acknowledge receipt and share your invoice as per the agreed terms.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )

    smtp_config = await get_admin_email_config(db)
    email_success, email_error = _send_toc_email_with_attachment(
        to_email,
        subject,
        body,
        filename,
        pdf_bytes,
        smtp_config,
    )

    download_url = _purchase_order_download_url(request, po_id)
    whatsapp_body = (
        "TrainerSync purchase order\n"
        f"PO: {doc.get('po_number')}\n"
        f"Trainer: {trainer.get('name') or 'Trainer'}\n"
        f"Technology: {requirement.get('technology') or 'Training'}\n"
        f"Grand Total: {commercials.get('currency', 'INR')} {commercials.get('grand_total', 0):,.2f}\n"
        "Please review and acknowledge the attached PO."
    )
    whatsapp_result = await send_whatsapp_message(
        db,
        trainer.get("phone", ""),
        whatsapp_body,
        event_type="purchase_order_document",
        recipient_type="trainer",
        request_base_url=_request_base_url(request),
        media_url=download_url,
        context={
            "po_id": po_id,
            "po_number": doc.get("po_number"),
            "trainer_id": trainer.get("trainer_id"),
            "trainer_name": trainer.get("name"),
            "requirement_id": requirement.get("requirement_id"),
            "technology": requirement.get("technology"),
        },
    )

    status = "sent" if email_success or whatsapp_result.get("success") else "send_failed"
    sent_at = datetime.utcnow()
    await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {
            "status": status,
            "sent_at": sent_at if status == "sent" else None,
            "email_status": "sent" if email_success else "failed",
            "email_error": email_error,
            "whatsapp_summary": whatsapp_result,
            "download_url": download_url,
        }},
    )
    await db["conversations"].insert_one({
        "trainer_id": trainer.get("trainer_id"),
        "trainer_name": trainer.get("name"),
        "to_email": to_email,
        "requirement_id": requirement.get("requirement_id"),
        "subject": subject,
        "body": body,
        "mail_type": "purchase_order",
        "direction": "sent",
        "status": "sent" if status == "sent" else "failed",
        "error": "" if status == "sent" else email_error or whatsapp_result.get("error", ""),
        "sent_at": sent_at,
        "po_id": po_id,
        "po_number": doc.get("po_number"),
    })

    updated = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if status != "sent":
        raise HTTPException(500, {
            "message": "Purchase order send failed",
            "email_error": email_error,
            "whatsapp": whatsapp_result,
        })

    return {
        "success": True,
        "message": "Purchase order sent",
        "purchase_order": public_purchase_order(updated),
        "email": {"success": email_success, "error": email_error},
        "whatsapp": whatsapp_result,
    }


@router.post("/purchase-orders/{po_id}/acknowledge")
async def acknowledge_purchase_order(po_id: str):
    db = get_db()
    result = await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {"status": "acknowledged", "acknowledged_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Purchase order not found")
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    return {"success": True, "purchase_order": public_purchase_order(doc)}


# Resume upload helpers

def _zip_display_name(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1] or path


def _is_resume_file(path: str) -> bool:
    lower = path.lower()
    return lower.endswith((".pdf", ".docx"))


async def _collect_resume_files(uploaded_files: List[UploadFile]) -> List[dict]:
    collected = []
    for upload in uploaded_files:
        filename = upload.filename or "resume"
        content = await upload.read()
        if not content:
            collected.append({"filename": filename, "error": "Empty file uploaded"})
            continue

        lower = filename.lower()
        if lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    resume_names = [
                        name for name in archive.namelist()
                        if not name.endswith("/")
                        and not name.replace("\\", "/").split("/")[-1].startswith(".")
                        and not name.replace("\\", "/").startswith("__MACOSX/")
                        and _is_resume_file(name)
                    ]
                    unsupported_count = len([
                        name for name in archive.namelist()
                        if not name.endswith("/")
                        and not name.replace("\\", "/").split("/")[-1].startswith(".")
                        and not name.replace("\\", "/").startswith("__MACOSX/")
                        and not _is_resume_file(name)
                    ])
                    if not resume_names:
                        collected.append({
                            "filename": filename,
                            "error": "ZIP contains no PDF or DOCX resume files",
                            "source_archive": filename,
                            "archive_file_count": unsupported_count,
                        })
                    for resume_name in resume_names:
                        collected.append({
                            "filename": _zip_display_name(resume_name),
                            "bytes": archive.read(resume_name),
                            "source_archive": filename,
                            "archive_path": resume_name,
                            "archive_resume_count": len(resume_names),
                            "archive_unsupported_count": unsupported_count,
                        })
            except zipfile.BadZipFile:
                collected.append({"filename": filename, "error": "Invalid ZIP file"})
            continue

        if lower.endswith((".pdf", ".docx")):
            collected.append({"filename": filename, "bytes": content})
        else:
            collected.append({"filename": filename, "error": "Only PDF, DOCX, or ZIP files are accepted"})

    return collected


def _resume_processing_concurrency() -> int:
    try:
        return max(1, min(5, int(os.getenv("RESUME_UPLOAD_CONCURRENCY", "3"))))
    except ValueError:
        return 3


async def _cache_resume_preview(db, processed: dict, item: dict) -> str:
    now = datetime.utcnow()
    upload_id = processed.get("upload_id") or f"RES-{uuid.uuid4().hex[:12].upper()}"
    processed["upload_id"] = upload_id

    upload_doc = {
        "upload_id": upload_id,
        "trainer_id": processed.get("trainer_id"),
        "filename": processed.get("filename"),
        "file_size": len(processed.get("raw_text", "")),
        "processing_status": "previewed",
        "extracted_data": public_resume_result(processed),
        "extracted_text": processed.get("raw_text", "")[:50000],
        "confidence_score": processed.get("confidence_score", 0),
        "created_at": now,
        "processed_at": now,
        "previewed_at": now,
    }
    for key in ("source_archive", "archive_path", "archive_resume_count", "archive_unsupported_count"):
        if item.get(key) is not None:
            upload_doc[key] = item.get(key)

    await db["resume_uploads"].update_one(
        {"upload_id": upload_id},
        {"$set": upload_doc},
        upsert=True,
    )
    return upload_id


def _profile_from_resume_upload(upload: dict, corrections: Optional[dict] = None) -> dict:
    extracted = dict(upload.get("extracted_data") or {})
    if corrections:
        extracted.update(corrections)

    return {
        **extracted,
        "success": True,
        "upload_id": upload.get("upload_id"),
        "trainer_id": extracted.get("trainer_id") or upload.get("trainer_id"),
        "filename": extracted.get("filename") or upload.get("filename"),
        "raw_text": upload.get("extracted_text") or upload.get("raw_text") or "",
        "source_archive": upload.get("source_archive") or extracted.get("source_archive"),
        "archive_path": upload.get("archive_path") or extracted.get("archive_path"),
        "confidence_score": extracted.get("confidence_score") or upload.get("confidence_score") or 0,
    }


def _resume_upload_corrections(corrections: Optional[dict], upload_id: str) -> dict:
    if not isinstance(corrections, dict):
        return {}
    scoped = corrections.get(upload_id)
    if isinstance(scoped, dict):
        return scoped
    known_profile_fields = {
        "name", "email", "phone", "location", "linkedin", "experience_years",
        "experience_raw", "role_designation", "education", "skills", "technologies",
        "certifications", "past_clients", "training_count", "day_rate", "hourly_rate",
        "technology_category", "secondary_categories", "category", "summary",
    }
    if any(key in known_profile_fields for key in corrections):
        return corrections
    return {}


async def _handle_resume_upload_item(db, item: dict, confirm: bool) -> tuple[dict, Optional[str]]:
    if item.get("error"):
        return {
            "filename": item["filename"],
            "success": False,
            "error": item["error"],
            "saved": False,
        }, None

    try:
        processed = await process_resume(item["bytes"], item["filename"], db)
        for key in ("source_archive", "archive_path", "archive_resume_count", "archive_unsupported_count"):
            if item.get(key) is not None:
                processed[key] = item.get(key)

        save_result = {"saved": False}
        saved_trainer_id = None
        if processed.get("success"):
            if confirm:
                save_result = await save_trainer_from_resume(processed, db, use_ai_tags=False)
                saved_trainer_id = save_result.get("trainer_id") if save_result.get("saved") else None
            else:
                await _cache_resume_preview(db, processed, item)

        return {
            **public_resume_result(processed),
            **save_result,
        }, saved_trainer_id
    except Exception as exc:
        return {
            "filename": item.get("filename", "resume"),
            "success": False,
            "error": str(exc),
            "saved": False,
        }, None


@router.post("/trainers/upload-resume")
async def upload_resume(
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    confirm: bool = False,
):
    uploaded_files = []
    if files:
        uploaded_files.extend(files)
    if file:
        uploaded_files.append(file)
    if not uploaded_files:
        raise HTTPException(400, "Upload at least one PDF, DOCX, or ZIP file")

    db = get_db()
    collected = await _collect_resume_files(uploaded_files)
    semaphore = asyncio.Semaphore(_resume_processing_concurrency())

    async def run_item(item: dict):
        async with semaphore:
            return await _handle_resume_upload_item(db, item, confirm)

    item_results = await asyncio.gather(*(run_item(item) for item in collected))
    results = [result for result, _trainer_id in item_results]
    saved_trainer_ids = [trainer_id for _result, trainer_id in item_results if trainer_id]
    if confirm and saved_trainer_ids:
        background_tasks.add_task(_categorise_trainers_background, saved_trainer_ids)

    success_count = sum(1 for r in results if r.get("success"))
    error_count = sum(1 for r in results if not r.get("success"))
    saved_count = sum(1 for r in results if r.get("saved"))
    inserted = sum(1 for r in results if r.get("saved") and r.get("action") == "inserted")
    updated = sum(1 for r in results if r.get("saved") and r.get("action") == "updated")
    archive_resume_count = sum(1 for item in collected if item.get("source_archive") and item.get("bytes"))
    archive_names = sorted({item["source_archive"] for item in collected if item.get("source_archive")})
    return {
        "confirm": confirm,
        "total": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "archive_count": len(archive_names),
        "archive_resume_count": archive_resume_count,
        "archives": archive_names,
        "saved_count": saved_count,
        "inserted": inserted,
        "updated": updated,
        "results": results,
    }


# ─── Clear Database ───────────────────────────────────────────────────────────

@router.post("/trainers/confirm-resumes")
async def confirm_resume_previews(payload: dict, background_tasks: BackgroundTasks):
    upload_ids = payload.get("upload_ids") or payload.get("uploadIds") or []
    if isinstance(upload_ids, str):
        upload_ids = [upload_ids]
    upload_ids = [str(upload_id).strip() for upload_id in upload_ids if str(upload_id).strip()]
    if not upload_ids:
        raise HTTPException(400, "Provide at least one preview upload_id to confirm")

    db = get_db()
    corrections = payload.get("corrections") or {}
    results = []
    saved_trainer_ids = []

    for upload_id in upload_ids:
        try:
            upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
            if not upload:
                results.append({
                    "upload_id": upload_id,
                    "success": False,
                    "saved": False,
                    "error": "Resume preview not found. Please extract preview again.",
                })
                continue

            profile = _profile_from_resume_upload(
                upload,
                _resume_upload_corrections(corrections, upload_id),
            )
            save_result = await save_trainer_from_resume(profile, db, use_ai_tags=False)
            if save_result.get("saved") and save_result.get("trainer_id"):
                saved_trainer_ids.append(save_result["trainer_id"])

            results.append({
                "upload_id": upload_id,
                "filename": upload.get("filename"),
                "success": bool(save_result.get("saved")),
                **save_result,
            })
        except Exception as exc:
            results.append({
                "upload_id": upload_id,
                "success": False,
                "saved": False,
                "error": str(exc),
            })

    if saved_trainer_ids:
        background_tasks.add_task(_categorise_trainers_background, saved_trainer_ids)

    saved_count = sum(1 for r in results if r.get("saved"))
    return {
        "confirm": True,
        "total": len(results),
        "success_count": saved_count,
        "error_count": sum(1 for r in results if not r.get("saved")),
        "saved_count": saved_count,
        "inserted": sum(1 for r in results if r.get("saved") and r.get("action") == "inserted"),
        "updated": sum(1 for r in results if r.get("saved") and r.get("action") == "updated"),
        "background_categorisation": bool(saved_trainer_ids),
        "results": results,
    }


@router.delete("/database/clear")
async def clear_database():
    db = get_db()
    results = {}
    for col in ["trainers", "requirements", "shortlists", "email_logs"]:
        r = await db[col].delete_many({})
        results[col] = r.deleted_count
    return {"message": "✅ Database cleared", "deleted": results}


# ─── Get All Trainers ─────────────────────────────────────────────────────────

@router.get("/trainers")
async def get_trainers(
    status: Optional[str] = None,
    search: Optional[str] = None,
    category: Optional[str] = None,
    domain: Optional[str] = None,
    industry: Optional[str] = None,
    experience: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    db = get_db()
    clauses = []
    if status:
        clauses.append({"status": status})
    if category:
        clauses.append({"$or": [
            {"primary_category": category},
            {"secondary_categories": category},
            {"technology_category": category},
            {"category": category},
        ]})
    if domain:
        clauses.append({"domain": domain})
    if industry:
        clauses.append({"industry_focus": industry})
    if experience == "0-3":
        clauses.append({"experience_years": {"$gte": 0, "$lt": 3}})
    elif experience == "3-7":
        clauses.append({"experience_years": {"$gte": 3, "$lt": 7}})
    elif experience == "7+":
        clauses.append({"experience_years": {"$gte": 7}})
    if search:
        pattern = _re.escape(search.strip())
        clauses.append({"$or": [
            {"name": {"$regex": pattern, "$options": "i"}},
            {"technologies": {"$regex": pattern, "$options": "i"}},
            {"skills": {"$regex": pattern, "$options": "i"}},
            {"specialty_tags": {"$regex": pattern, "$options": "i"}},
            {"specialisation_tags": {"$regex": pattern, "$options": "i"}},
            {"primary_category": {"$regex": pattern, "$options": "i"}},
            {"secondary_categories": {"$regex": pattern, "$options": "i"}},
            {"technology_category": {"$regex": pattern, "$options": "i"}},
            {"domain": {"$regex": pattern, "$options": "i"}},
            {"industry_focus": {"$regex": pattern, "$options": "i"}},
            {"language_of_delivery": {"$regex": pattern, "$options": "i"}},
            {"location": {"$regex": pattern, "$options": "i"}},
            {"email": {"$regex": pattern, "$options": "i"}},
        ]})

    query = {"$and": clauses} if len(clauses) > 1 else (clauses[0] if clauses else {})
    total = await db["trainers"].count_documents(query)
    skip = (page - 1) * limit
    trainers = await db["trainers"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {
        "trainers": trainers,
        "total": total,
        "page": page,
        "pages": -(-total // limit),
        "categories": await get_all_categories(db),
        "domains": await _software_domains(db),
        "industries": await _distinct_non_empty(db, "industry_focus"),
    }


@router.get("/trainers/categories")
async def trainer_categories():
    db = get_db()
    return {"categories": await get_all_categories(db)}


@router.get("/trainers/domains")
async def trainer_domains():
    db = get_db()
    return {"domains": await _software_domains(db)}


@router.get("/trainers/industries")
async def trainer_industries():
    db = get_db()
    return {"industries": await _distinct_non_empty(db, "industry_focus")}


@router.post("/trainers/categorise-all")
async def categorise_all_trainers(background_tasks: BackgroundTasks):
    db = get_db()
    pending_query = {
        "$and": [
            {"$or": [
                {"primary_category": {"$exists": False}},
                {"primary_category": None},
                {"primary_category": ""},
            ]},
            {"categorisation_failed_at": {"$exists": False}},
        ]
    }
    total_pending = await db["trainers"].count_documents(pending_query)
    job_id = f"CAT-{uuid.uuid4().hex[:8].upper()}"
    CATEGORISATION_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total_pending": total_pending,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "created_at": datetime.utcnow(),
    }
    background_tasks.add_task(_run_categorisation_job, job_id)
    return {
        "message": "Categorisation job started",
        "job_id": job_id,
        "total_pending": total_pending,
    }


@router.get("/trainers/categorise-jobs/{job_id}")
async def get_categorisation_job(job_id: str):
    job = CATEGORISATION_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Categorisation job not found")
    return job


@router.post("/trainers/{trainer_id}/categorise")
async def categorise_single_trainer(trainer_id: str):
    db = get_db()
    result = await _categorise_trainer_by_id(db, trainer_id)
    return {
        "trainer_id": trainer_id,
        **result,
    }


# ─── Create Requirement & Run Pipeline ───────────────────────────────────────

@router.post("/requirements")
async def create_requirement(req: RequirementCreate, request: Request):
    db = get_db()
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    req_dict = req.dict()
    req_dict.update({"requirement_id": req_id, "status": "active", "created_at": datetime.utcnow()})

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    if not all_trainers:
        raise HTTPException(400, "No trainers in database. Upload trainer resumes first.")

    excluded_statuses = ["interested", "confirmed", "declined"]
    filtered_trainers = [t for t in all_trainers
                        if t.get("status") not in excluded_statuses]

    result = await run_pipeline(filtered_trainers, req_dict)
    top_trainers   = result.get("top_trainers", [])
    email_payloads = result.get("email_payloads", [])

    req_dict["total_matched"] = len(result.get("ranked_trainers", []))
    req_dict["top_count"] = len(top_trainers)
    await db["requirements"].insert_one(req_dict)

    await db["shortlists"].insert_one({
        "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": req.technology_needed,
        "top_trainers": [{k: v for k, v in t.items() if k != "_id"} for t in top_trainers],
        "total_matched": len(result.get("ranked_trainers", [])),
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
        "created_at": datetime.utcnow()
    })
    await send_teams_stage_notification(
        db,
        stage="new_requirement_created",
        trainer_name="Not assigned yet",
        requirement=req_dict,
        request_base_url=_request_base_url(request),
        context={"source": "requirements_api", "top_count": len(top_trainers)},
    )

    for t in top_trainers:
        await db["trainers"].update_one(
            {"trainer_id": t["trainer_id"]},
            {"$set": {"match_score": t["match_score"], "rank": t["rank"],
                      "status": "contacted" if req_dict.get("send_emails") else "pending_review"}}
        )

    send_emails = req_dict.get('send_emails', False)
    smtp_config = await get_admin_email_config(db)
    email_results = []
    if send_emails and email_payloads:
        for payload in email_payloads:
            email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
            tracking_url = build_tracking_url(request, email_id)
            success, error = await send_email_async(
                payload["to"],
                payload["subject"],
                payload["body"],
                smtp_config,
                tracking_url,
            )
            trainer_phone = await _trainer_phone(db, payload.get("trainer_id", ""))
            whatsapp_result = await send_shortlist_whatsapp(
                db,
                trainer_phone=trainer_phone,
                trainer_name=payload.get("trainer_name", ""),
                subject=payload.get("subject", ""),
                body=payload.get("body", ""),
                mail_type="mail1",
                requirement_id=req_id,
                email_id=email_id,
                request_base_url=_request_base_url(request),
            )
            email_results.append({
                **payload,
                "email_id": email_id,
                "status": "sent" if success else "failed",
                "error_message": error if not success else "",
                "sent_at": datetime.utcnow().isoformat() if success else None,
                "tracking_url": tracking_url,
                "whatsapp": whatsapp_result,
            })

    for er in email_results:
        await db["email_logs"].insert_one({
            "email_id":      er["email_id"],
            "trainer_id":    er["trainer_id"],
            "trainer_name":  er["trainer_name"],
            "requirement_id": req_id,
            "to_email":      er["to"],
            "subject":       er["subject"],
            "body":          er["body"],
            "status":        er["status"],
            "email_stage":   1,
            "error_message": er.get("error_message", ""),
            "sent_at":       datetime.fromisoformat(er["sent_at"]) if er.get("sent_at") else None,
            "reply_received": False,
            "opened":         False,
            "open_count":     0,
            "tracking_url":   er.get("tracking_url", ""),
            "whatsapp_summary": er.get("whatsapp", {}),
            "retry_count":   0,
            "created_at":    datetime.utcnow()
        })
        if er["status"] == "sent":
            await send_teams_stage_notification(
                db,
                stage="trainer_contacted",
                trainer_name=er["trainer_name"],
                requirement=req_dict,
                request_base_url=_request_base_url(request),
                context={"source": "requirements_api", "email_id": er["email_id"], "trainer_id": er["trainer_id"]},
            )

    return {
        "requirement_id": req_id,
        "total_trainers_scanned": len(all_trainers),
        "total_available": len(filtered_trainers),
        "total_matched": len(result.get("ranked_trainers", [])),
        "top_trainers": len(top_trainers),
        "emails_sent": sum(1 for e in email_results if e["status"] == "sent"),
        "emails_failed": sum(1 for e in email_results if e["status"] == "failed"),
        "top_trainers_list": top_trainers,
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
    }


# ─── Retry Single Failed Email ────────────────────────────────────────────────

@router.post("/emails/{email_id}/retry")
async def retry_email(email_id: str, request: Request):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")
    if log.get("retry_count", 0) >= 3:
        raise HTTPException(400, "Max retry attempts (3) reached")

    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""), log.get("trainer_phone", ""))
    email_result, whatsapp_result = await asyncio.gather(
        send_email_async(
            log["to_email"],
            log["subject"],
            log["body"],
            smtp_config,
            build_tracking_url(request, email_id),
        ),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            subject=log.get("subject", ""),
            body=log.get("body", ""),
            mail_type=log.get("mail_type", "mail1_reminder"),
            requirement_id=log.get("requirement_id", ""),
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
    )
    success, error = email_result
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": datetime.utcnow() if success else None,
            "whatsapp_summary": whatsapp_result,
        },
         "$inc": {"retry_count": 1}}
    )
    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result}


# ─── Schedule Interview ───────────────────────────────────────────────────────

@router.post("/emails/{email_id}/schedule-interview")
async def schedule_interview(email_id: str, request: Request, interview_date: str = "", interview_link: str = ""):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    req = await db["requirements"].find_one({"requirement_id": log["requirement_id"]})
    technology = req.get("technology_needed", "Training") if req else "Training"

    body = compose_interview_email(
        trainer_name=log["trainer_name"],
        technology=technology,
        req_id=log["requirement_id"],
        interview_date=interview_date,
        interview_link=interview_link,
    )
    subject = f"Interview Scheduled — {technology} | {log['requirement_id']}"
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(
        log["to_email"],
        subject,
        body,
        smtp_config,
        build_tracking_url(request, email_id),
    )

    reminder_fields = interview_reminder_fields(interview_date)
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "interview_scheduled": success,
            "interview_date": interview_date,
            "interview_link": interview_link,
            "platform": "Online",
            "trainer_phone": await _trainer_phone(db, log.get("trainer_id", "")),
            "interview_email_sent_at": datetime.utcnow() if success else None,
            "technology": technology,
            **reminder_fields,
            "interview_reminder_status": "not_scheduled",
            "whatsapp_reminder_status": "not_scheduled",
        }}
    )
    whatsapp_result = await send_interview_whatsapp(
        db,
        trainer_phone=await _trainer_phone(db, log.get("trainer_id", "")),
        trainer_name=log.get("trainer_name", ""),
        requirement_id=log.get("requirement_id", ""),
        technology=technology,
        date_time=interview_date,
        platform="Online",
        interview_link=interview_link,
        email_id=email_id,
        request_base_url=_request_base_url(request),
    )
    await db["trainers"].update_one(
        {"trainer_id": log["trainer_id"]},
        {"$set": {"status": "confirmed"}}
    )
    updated_log = {
        **log,
        "interview_scheduled": success,
        "interview_date": interview_date,
        "interview_link": interview_link,
        "platform": "Online",
        "trainer_phone": await _trainer_phone(db, log.get("trainer_id", "")),
        "technology": technology,
        **reminder_fields,
    }
    reminder_schedule = await schedule_interview_reminder(
        db,
        email_log=updated_log,
        request_base_url=_request_base_url(request),
    ) if success else {"scheduled": False, "status": "email_failed", "error": error}
    if success:
        await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=log.get("trainer_name", ""),
            requirement=req or {"requirement_id": log.get("requirement_id"), "technology_needed": technology},
            request_base_url=_request_base_url(request),
            context={"source": "email_schedule_interview", "email_id": email_id, "interview_date": interview_date},
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result, "reminder_schedule": reminder_schedule}


# ─── Send Interview Link ──────────────────────────────────────────────────────

@router.post("/shortlists/send-interview-link")
async def send_interview_link_auto(payload: dict, request: Request):
    db = get_db()
    trainer_id     = payload.get("trainer_id")
    trainer_name   = payload.get("trainer_name")
    to_email       = payload.get("to_email")
    trainer_phone  = payload.get("trainer_phone") or payload.get("phone") or ""
    requirement_id = payload.get("requirement_id")
    platform       = payload.get("platform", "Zoom")
    date_time      = payload.get("date_time", "")
    interview_link = payload.get("interview_link", "")

    if not to_email:
        raise HTTPException(400, "to_email is required")

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    technology = req.get("technology_needed", "Training") if req else "Training"

    subject = f"Interview Schedule Confirmation – {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        f"Your interview has been scheduled. Please find the details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        f"Please join on time. Let us know if you need any assistance.\n\n"
        f"Regards,\nTrainerSync Team"
    )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)

    email_result, whatsapp_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            requirement_id=requirement_id,
            technology=technology,
            date_time=date_time,
            platform=platform,
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
    )
    success, error = email_result

    await db["conversations"].insert_one({
        "trainer_id": trainer_id, "trainer_name": trainer_name,
        "to_email": to_email, "requirement_id": requirement_id,
        "subject": subject, "body": body, "mail_type": "mail4",
        "direction": "sent", "status": "sent" if success else "failed",
        "error": error if not success else "", "sent_at": datetime.utcnow(),
        "platform": platform, "interview_link": interview_link, "date_time": date_time,
    })

    email_log_doc = {
        "email_id": email_id, "trainer_id": trainer_id, "trainer_name": trainer_name,
        "requirement_id": requirement_id, "to_email": to_email,
        "subject": subject, "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": datetime.utcnow() if success else None,
        "reply_received": False, "opened": False, "open_count": 0,
        "tracking_url": tracking_url, "retry_count": 0, "mail_type": "mail4",
        "interview_scheduled": success, "interview_date": date_time,
        "interview_link": interview_link, "platform": platform,
        "technology": technology,
        "trainer_phone": trainer_phone,
        **interview_reminder_fields(date_time),
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
        "created_at": datetime.utcnow(),
    }
    await db["email_logs"].insert_one(email_log_doc)

    if success:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {"status": "interview_scheduled"}}
        )
        reminder_schedule = await schedule_interview_reminder(
            db,
            email_log=email_log_doc,
            request_base_url=_request_base_url(request),
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="interview_scheduled",
            trainer_name=trainer_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request),
            context={"source": "shortlist_interview_link", "email_id": email_id, "interview_date": date_time},
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result,
            "teams": teams_result,
            "reminder_schedule": reminder_schedule,
            "message": f"Interview link email {'sent' if success else 'failed'} to {trainer_name}"}


# ─── Get Requirements ─────────────────────────────────────────────────────────

# --- Celery Interview Reminder Admin ---------------------------------------

def _public_reminder_doc(doc: dict) -> dict:
    clean = {k: v for k, v in (doc or {}).items() if k != "_id"}
    for key, value in list(clean.items()):
        if isinstance(value, datetime):
            clean[key] = value.isoformat()
    return clean


@router.get("/interview-reminders")
async def list_interview_reminders(
    status: Optional[str] = None,
    requirement_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    if requirement_id:
        query["requirement_id"] = requirement_id
    skip = max(page - 1, 0) * limit
    total = await db["interview_reminders"].count_documents(query)
    docs = await db["interview_reminders"].find(query, {"_id": 0}).sort("reminder_at", -1).skip(skip).limit(limit).to_list(limit)
    return {
        "reminders": [_public_reminder_doc(doc) for doc in docs],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/interview-reminders/{reminder_id}/cancel")
async def cancel_interview_reminder_route(reminder_id: str, payload: dict = {}):
    db = get_db()
    result = await cancel_interview_reminder(
        db,
        reminder_id=reminder_id,
        reason=payload.get("reason") or "cancelled_by_user",
    )
    if not result.get("cancelled"):
        raise HTTPException(404, "Pending reminder not found")
    return result


@router.post("/admin/teams/test")
async def test_teams_settings(request: Request):
    db = get_db()
    result = await send_teams_stage_notification(
        db,
        stage="new_requirement_created",
        trainer_name="Test Trainer",
        requirement_id="REQ-TEAMS-TEST",
        technology="TrainerSync Teams Test",
        request_base_url=_request_base_url(request),
        context={"source": "admin_test"},
    )
    if not result.get("success"):
        raise HTTPException(400, result)
    return result


@router.post("/interview-reminders/{reminder_id}/reschedule")
async def reschedule_interview_reminder_route(reminder_id: str, payload: dict, request: Request):
    date_time = payload.get("date_time") or payload.get("interview_date")
    if not date_time:
        raise HTTPException(400, "date_time is required")

    db = get_db()
    reminder = await db["interview_reminders"].find_one({"reminder_id": reminder_id}, {"_id": 0})
    if not reminder:
        raise HTTPException(404, "Reminder not found")

    await cancel_interview_reminder(db, reminder_id=reminder_id, reason="rescheduled")

    email_log = await db["email_logs"].find_one({"email_id": reminder.get("email_id")}, {"_id": 0}) or {}
    platform = payload.get("platform") or reminder.get("platform") or email_log.get("platform") or "Online"
    interview_link = payload.get("interview_link") or reminder.get("interview_link") or email_log.get("interview_link") or ""
    reminder_fields = interview_reminder_fields(date_time)
    update_fields = {
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": reminder.get("technology") or email_log.get("technology", ""),
        **reminder_fields,
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
    }
    if email_log.get("email_id"):
        await db["email_logs"].update_one({"email_id": email_log["email_id"]}, {"$set": update_fields})
    email_log = {
        **email_log,
        "email_id": email_log.get("email_id") or reminder.get("email_id"),
        "trainer_id": reminder.get("trainer_id"),
        "trainer_name": reminder.get("trainer_name"),
        "to_email": reminder.get("trainer_email"),
        "trainer_phone": reminder.get("trainer_phone", ""),
        "requirement_id": reminder.get("requirement_id"),
        **update_fields,
    }
    schedule = await schedule_interview_reminder(
        db,
        email_log=email_log,
        request_base_url=_request_base_url(request),
        replace_existing=True,
    )
    return {"rescheduled": schedule.get("scheduled", False), "reminder_schedule": schedule}


@router.get("/requirements")
async def get_requirements():
    db = get_db()
    reqs = await db["requirements"].find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"requirements": reqs}


# ─── Send Shortlist Mail ──────────────────────────────────────────────────────

@router.post("/shortlists/send-mail")
async def send_shortlist_mail(payload: dict, request: Request):
    db = get_db()
    trainer_id     = payload.get("trainer_id")
    trainer_name   = payload.get("trainer_name")
    to_email       = payload.get("to_email")
    trainer_phone  = payload.get("trainer_phone") or payload.get("phone") or ""
    requirement_id = payload.get("requirement_id")
    subject        = payload.get("subject")
    body           = payload.get("body")
    mail_type      = payload.get("mail_type", "first")

    if not to_email or not body:
        raise HTTPException(400, "to_email and body are required")

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)

    email_result, whatsapp_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            subject=subject,
            body=body,
            mail_type=mail_type,
            requirement_id=requirement_id,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
    )
    success, error = email_result

    sent_at = datetime.utcnow()
    await db["conversations"].insert_one({
        "trainer_id": trainer_id, "trainer_name": trainer_name,
        "to_email": to_email, "requirement_id": requirement_id,
        "subject": subject, "body": body, "mail_type": mail_type,
        "direction": "sent", "status": "sent" if success else "failed",
        "error": error if not success else "", "sent_at": sent_at,
        "email_id": email_id, "opened": False, "open_count": 0,
    })

    await db["email_logs"].insert_one({
        "email_id": email_id, "trainer_id": trainer_id, "trainer_name": trainer_name,
        "requirement_id": requirement_id, "to_email": to_email,
        "subject": subject, "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False, "opened": False, "open_count": 0,
        "tracking_url": tracking_url, "retry_count": 0,
        "mail_type": mail_type, "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "created_at": datetime.utcnow(),
    })

    teams_result = {"status": "not_applicable"}
    if success:
        new_status = "contacted" if mail_type in {"first", "mail1"} else "pending_review"
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": new_status}})
        teams_stage = None
        if mail_type in {"first", "mail1"}:
            teams_stage = "trainer_contacted"
        elif mail_type == "mail5_ok":
            teams_stage = "trainer_selected"
        if teams_stage:
            requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
            teams_result = await send_teams_stage_notification(
                db,
                stage=teams_stage,
                trainer_name=trainer_name,
                requirement=requirement or {"requirement_id": requirement_id},
                request_base_url=_request_base_url(request),
                context={"source": "shortlist_send_mail", "email_id": email_id, "mail_type": mail_type, "trainer_id": trainer_id},
            )

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams": teams_result}


# ─── Get Conversation Thread ──────────────────────────────────────────────────

@router.post("/shortlists/send-client-slots")
async def send_client_slot_options(payload: dict, request: Request):
    db = get_db()
    trainer_id = payload.get("trainer_id", "")
    trainer_name = payload.get("trainer_name") or "the trainer"
    requirement_id = payload.get("requirement_id", "")
    force = bool(payload.get("force", False))

    if not requirement_id:
        raise HTTPException(400, "requirement_id is required")

    requirement, client_email, client_name = await _client_contact_for_requirement(db, requirement_id, payload)
    if not client_email:
        raise HTTPException(400, "Client email not found for this requirement")

    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    slot_text = _strip_quoted_reply_text(
        payload.get("slot_text") or payload.get("slots") or payload.get("trainer_reply") or ""
    )
    if not slot_text:
        slot_text = "The trainer has confirmed availability. Please reply with a convenient slot or share alternate timings."

    normalised_slots = _re.sub(r"\s+", " ", slot_text.lower()).strip()
    slot_hash = hashlib.sha256(f"{requirement_id}|{trainer_id}|{normalised_slots}".encode("utf-8")).hexdigest()

    if not force:
        existing = await db["client_slot_emails"].find_one({
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "slot_hash": slot_hash,
            "status": "sent",
        }, {"_id": 0})
        if existing:
            return {
                "success": True,
                "already_sent": True,
                "email_id": existing.get("email_id"),
                "to_email": existing.get("to_email"),
                "slot_ref": existing.get("slot_ref"),
            }

    slot_ref = payload.get("slot_ref") or f"SLOT-{uuid.uuid4().hex[:8].upper()}"
    subject = payload.get("subject") or f"Trainer Slot Availability - {technology} | {requirement_id} | {slot_ref}"
    body = payload.get("body") or (
        f"Hi {client_name or 'Team'},\n\n"
        f"The trainer {trainer_name} has shared availability for the {technology} discussion/interview.\n\n"
        f"Reference: {requirement_id} / {slot_ref}\n\n"
        f"Trainer available slot(s):\n{slot_text}\n\n"
        "Please confirm which slot works for your team, or share alternate timings if these are not convenient.\n"
        "Once you confirm, we will schedule the meeting and share the final link with everyone.\n\n"
        "Regards,\nRecruitment Team,\nCalhan Technologies"
    )
    if slot_ref not in subject:
        subject = f"{subject} | {slot_ref}"
    if slot_ref not in body:
        body = f"{body.rstrip()}\n\nReference: {requirement_id} / {slot_ref}"

    email_id = f"CLIENT-SLOT-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)

    now = datetime.utcnow()
    doc = {
        "email_id": email_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": client_email,
        "client_name": client_name,
        "subject": subject,
        "body": body,
        "slot_text": slot_text,
        "slot_ref": slot_ref,
        "slot_hash": slot_hash,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "created_at": now,
        "force": force,
    }
    await db["client_slot_emails"].insert_one(doc)

    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": client_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "client_slot_options",
        "created_at": now,
    })

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "to_email": client_email,
        "slot_ref": slot_ref,
        "already_sent": False,
    }


@router.get("/shortlists/thread")
async def get_conversation_thread(trainer_id: str, requirement_id: str):
    db = get_db()

    all_msgs = await db["conversations"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id},
        {"_id": 0}
    ).sort("sent_at", 1).to_list(200)

    email_replies = await db["email_logs"].find(
        {"trainer_id": trainer_id, "requirement_id": requirement_id, "reply_received": True},
        {
            "_id": 0, "trainer_id": 1, "trainer_name": 1, "requirement_id": 1,
            "subject": 1, "reply_text": 1, "replied_at": 1, "created_at": 1,
        }
    ).sort("replied_at", 1).to_list(100)

    messages = []
    for m in all_msgs:
        direction = m.get("direction") or "sent"
        messages.append({**m, "direction": direction})

    existing_bodies = {m.get("body", "") for m in messages if m.get("direction") == "received"}
    for r in email_replies:
        reply_body = r.get("reply_text", "")
        if reply_body and reply_body not in existing_bodies:
            messages.append({
                "trainer_id":     r.get("trainer_id"),
                "trainer_name":   r.get("trainer_name"),
                "requirement_id": r.get("requirement_id"),
                "subject":        f"Re: {r.get('subject', '')}",
                "body":           reply_body,
                "direction":      "received",
                "sent_at":        r.get("replied_at") or r.get("created_at"),
                "mail_type":      "reply",
            })

    def sort_key(x):
        val = x.get("sent_at")
        if val is None:
            return datetime.min
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return datetime.min
        if hasattr(val, "tzinfo") and val.tzinfo is not None:
            return val.replace(tzinfo=None)
        return val

    messages.sort(key=sort_key)
    return {"messages": messages, "total": len(messages)}


@router.get("/shortlists/thread-states")
async def get_shortlist_thread_states(requirement_id: str):
    db = get_db()

    conversation_docs = await db["conversations"].find(
        {"requirement_id": requirement_id},
        {"_id": 0, "trainer_id": 1, "direction": 1, "mail_type": 1, "sent_at": 1, "body": 1},
    ).sort("sent_at", 1).to_list(1000)

    reply_docs = await db["email_logs"].find(
        {"requirement_id": requirement_id, "reply_received": True},
        {
            "_id": 0, "trainer_id": 1, "mail_type": 1,
            "reply_text": 1, "replied_at": 1, "created_at": 1,
        },
    ).sort("replied_at", 1).to_list(500)

    threads = {}
    seen_replies = set()
    for msg in conversation_docs:
        trainer_id = msg.get("trainer_id")
        if not trainer_id:
            continue
        item = {
            "direction": msg.get("direction") or "sent",
            "mail_type": msg.get("mail_type"),
            "sent_at": msg.get("sent_at"),
            "body": msg.get("body", ""),
        }
        threads.setdefault(str(trainer_id), []).append(item)
        if item["direction"] == "received" and item["body"]:
            seen_replies.add((str(trainer_id), item["body"]))

    for reply in reply_docs:
        trainer_id = reply.get("trainer_id")
        body = reply.get("reply_text", "")
        if not trainer_id or not body:
            continue
        key = (str(trainer_id), body)
        if key in seen_replies:
            continue
        threads.setdefault(str(trainer_id), []).append({
            "direction": "received",
            "mail_type": "reply",
            "sent_at": reply.get("replied_at") or reply.get("created_at"),
            "body": body,
        })

    return {"threads": threads}


# ─── Get Shortlists ───────────────────────────────────────────────────────────

@router.get("/shortlists/{requirement_id}")
async def get_shortlist(requirement_id: str):
    db = get_db()
    s = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Shortlist not found")
    return s


# ─── Email Logs ───────────────────────────────────────────────────────────────

@router.get("/emails")
async def get_email_logs(requirement_id: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {"requirement_id": requirement_id} if requirement_id else {}
    total = await db["email_logs"].count_documents(query)
    skip = (page - 1) * limit
    logs = await db["email_logs"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"emails": logs, "total": total, "page": page}


@router.get("/whatsapp/logs")
async def get_whatsapp_logs(requirement_id: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {"context.requirement_id": requirement_id} if requirement_id else {}
    total = await db["whatsapp_logs"].count_documents(query)
    skip = (page - 1) * limit
    logs = await db["whatsapp_logs"].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"whatsapp_logs": logs, "total": total, "page": page}


# ─── Check Replies ────────────────────────────────────────────────────────────

@router.post("/emails/check-replies")
async def manual_reply_check(request: Request):
    db = get_db()
    sent_recipients = await db["email_logs"].distinct(
        "to_email",
        {"status": "sent", "reply_received": {"$ne": True}},
    )
    smtp_config = await get_admin_email_config(db)
    replies = check_email_replies(
        since_days=14,
        max_messages=50,
        from_emails=sent_recipients,
        gmail_user=smtp_config.get("smtpUser") or "",
        gmail_pass=smtp_config.get("smtpPass") or "",
    )
    processed = 0
    skipped_duplicates = 0
    skipped_unmatched = 0
    for reply in replies:
        from_raw = reply["from_email"]
        m = _re.search(r'<([^>]+)>', from_raw)
        from_email_clean = m.group(1) if m else from_raw.strip()
        message_id_header = reply.get("message_id_header", "")

        duplicate_or = [{"subject": reply["subject"], "body": reply["body"]}]
        if message_id_header:
            duplicate_or.insert(0, {"message_id_header": message_id_header})
        existing_reply = await db["conversations"].find_one(
            {
                "direction": "received",
                "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                "$or": duplicate_or,
            },
            {"_id": 1},
        )
        if existing_reply:
            skipped_duplicates += 1
            continue

        replied_at = datetime.utcnow()
        try:
            if reply.get("received_at"):
                replied_at = datetime.fromisoformat(str(reply["received_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            replied_at = datetime.utcnow()

        reply_subject_norm = _norm_subject(reply.get("subject", ""))
        candidate_logs = await db["email_logs"].find(
            {
                "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                "status": "sent",
                "sent_at": {"$lte": replied_at},
            },
            {"_id": 0},
        ).sort("sent_at", -1).limit(25).to_list(25)

        def candidate_score(item):
            subject_norm = _norm_subject(item.get("subject", ""))
            reply_body_norm = str(reply.get("body", "")).lower()
            trainer_name_norm = str(item.get("trainer_name", "")).strip().lower()
            score = 0
            if subject_norm and (subject_norm in reply_subject_norm or reply_subject_norm in subject_norm):
                score += 100
            if trainer_name_norm and trainer_name_norm in reply_body_norm:
                score += 200
            if item.get("mail_type") == "mail2" and "additional details required" in reply_subject_norm:
                score += 80
            if item.get("mail_type") == "mail2_followup" and "details required" in reply_subject_norm:
                score += 70
            if item.get("mail_type") == "mail3" and "interview slot booking" in reply_subject_norm:
                score += 150
            if item.get("mail_type") == "mail4" and "interview schedule" in reply_subject_norm:
                score += 120
            if item.get("mail_type") == "mail1_reminder" and "reminder" in reply_subject_norm:
                score += 30
            if item.get("reply_received"):
                score -= 40
            return score

        log = sorted(candidate_logs, key=candidate_score, reverse=True)[0] if candidate_logs else None
        if not log:
            log = await db["conversations"].find_one(
                {"to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"}, "direction": "sent", "sent_at": {"$lte": replied_at}},
                sort=[("sent_at", -1)]
            )
        if log:
            trainer_id_matched     = log.get("trainer_id")
            requirement_id_matched = log.get("requirement_id")
            status_map = {"mark_interested": "interested", "mark_declined": "declined", "requires_review": "pending_review"}

            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {"reply_received": True, "reply_sentiment": reply["sentiment"],
                           "reply_text": reply["body"], "replied_at": replied_at,
                           "reply_message_id": message_id_header}}
            )

            duplicate_query = {
                "to_email": from_email_clean,
                "requirement_id": requirement_id_matched,
                "direction": "received",
                "$or": [
                    {"message_id_header": message_id_header} if message_id_header else {"subject": reply["subject"], "body": reply["body"]},
                    {"subject": reply["subject"], "body": reply["body"]},
                ],
            }
            already_stored = await db["conversations"].find_one(duplicate_query)
            if not already_stored:
                await db["conversations"].insert_one({
                    "trainer_id": trainer_id_matched, "trainer_name": log.get("trainer_name"),
                    "to_email": from_email_clean, "requirement_id": requirement_id_matched,
                    "subject": reply["subject"], "body": reply["body"],
                    "direction": "received", "mail_type": "reply",
                    "status": "received", "sent_at": replied_at,
                    "message_id_header": message_id_header,
                    "in_reply_to": reply.get("in_reply_to", ""),
                    "references": reply.get("references", ""),
                })
                await send_vendor_reply_notification(
                    db,
                    trainer_name=log.get("trainer_name", ""),
                    trainer_id=trainer_id_matched,
                    requirement_id=requirement_id_matched,
                    mail_type=log.get("mail_type", ""),
                    reply_subject=reply.get("subject", ""),
                    reply_body=reply.get("body", ""),
                    sentiment=reply.get("sentiment", ""),
                    request_base_url="",
                )
                requirement = await db["requirements"].find_one({"requirement_id": requirement_id_matched}, {"_id": 0})
                await send_teams_stage_notification(
                    db,
                    stage="trainer_replied",
                    trainer_name=log.get("trainer_name", ""),
                    requirement=requirement or {"requirement_id": requirement_id_matched},
                    request_base_url=_request_base_url(request),
                    context={
                        "source": "manual_reply_check",
                        "trainer_id": trainer_id_matched,
                        "sentiment": reply.get("sentiment", ""),
                        "subject": reply.get("subject", ""),
                    },
                )

            await db["trainers"].update_one(
                {"trainer_id": trainer_id_matched},
                {"$set": {"status": status_map.get(reply["action"], "pending_review")}}
            )
            processed += 1
        else:
            skipped_unmatched += 1

    if processed > 0:
        from agents.email_agent import mark_emails_seen
        msg_ids = [r["msg_id"] for r in replies if r.get("msg_id")]
        if msg_ids:
            mark_emails_seen(msg_ids)

    return {
        "replies_found": len(replies),
        "processed": processed,
        "skipped_duplicates": skipped_duplicates,
        "skipped_unmatched": skipped_unmatched,
    }


# ─── Scheduler Config ─────────────────────────────────────────────────────────

@router.get("/scheduler/config")
async def get_scheduler_config_route():
    return get_scheduler_config()


@router.post("/scheduler/config")
async def update_scheduler_config_route(payload: dict):
    allowed = {"retry_interval_unit", "retry_interval_value", "reply_check_interval", "max_retries", "auto_retry_enabled"}
    clean = {k: v for k, v in payload.items() if k in allowed}
    if not clean:
        raise HTTPException(400, "No valid config keys provided")
    if "retry_interval_unit" in clean and clean["retry_interval_unit"] not in ("minutes", "hours", "days"):
        raise HTTPException(400, "retry_interval_unit must be 'minutes', 'hours', or 'days'")
    update_scheduler_config(clean)
    return {"message": "Scheduler config updated", "config": get_scheduler_config()}


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

@router.get("/dashboard/stats")
async def get_dashboard_stats():
    db = get_db()
    total_trainers     = await db["trainers"].count_documents({})
    total_requirements = await db["requirements"].count_documents({})
    total_emails       = await db["email_logs"].count_documents({"status": "sent"})
    total_failed       = await db["email_logs"].count_documents({"status": "failed"})
    total_opened       = await db["email_logs"].count_documents({"opened": True})
    total_replies_logs = await db["email_logs"].count_documents({"reply_received": True})
    total_replies      = total_replies_logs
    interested         = await db["trainers"].count_documents({"status": "interested"})
    declined           = await db["trainers"].count_documents({"status": "declined"})
    pending_review     = await db["trainers"].count_documents({"status": "pending_review"})
    contacted          = await db["trainers"].count_documents({"status": "contacted"})
    confirmed          = await db["trainers"].count_documents({"status": "confirmed"})

    reply_rate    = round((total_replies / total_emails * 100) if total_emails > 0 else 0, 1)
    open_rate     = round((total_opened / total_emails * 100) if total_emails > 0 else 0, 1)
    interest_rate = round((interested / total_replies * 100) if total_replies > 0 else 0, 1)

    recent_emails = await db["email_logs"].find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    recent_whatsapp = await db["whatsapp_logs"].find({}, {"_id": 0}).sort("created_at", -1).limit(8).to_list(8)
    whatsapp_total = await db["whatsapp_logs"].count_documents({})
    whatsapp_sent = await db["whatsapp_logs"].count_documents({"status": {"$in": ["queued", "sent", "delivered", "read"]}})
    whatsapp_delivered = await db["whatsapp_logs"].count_documents({"status": {"$in": ["delivered", "read"]}})
    whatsapp_failed = await db["whatsapp_logs"].count_documents({"status": {"$in": ["failed", "undelivered", "skipped"]}})
    whatsapp_replies = await db["whatsapp_logs"].count_documents({"direction": "inbound"})

    today = datetime.utcnow().date()
    activity = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        activity.append({
            "day": day.strftime("%a"),
            "date": day.isoformat(),
            "emails": await db["email_logs"].count_documents({
                "status": "sent",
                "sent_at": {"$gte": start, "$lt": end},
            }),
            "opens": await db["email_logs"].count_documents({
                "opened": True,
                "opened_at": {"$gte": start, "$lt": end},
            }),
            "replies": await db["email_logs"].count_documents({
                "reply_received": True,
                "replied_at": {"$gte": start, "$lt": end},
            }),
        })

    try:
        score_dist = await db["trainers"].aggregate([
            {"$match": {"match_score": {"$ne": None}}},
            {"$bucket": {"groupBy": "$match_score", "boundaries": [0, 20, 40, 60, 80, 101],
                          "default": "Other", "output": {"count": {"$sum": 1}}}}
        ]).to_list(10)
    except:
        score_dist = []

    return {
        "total_trainers": total_trainers, "total_requirements": total_requirements,
        "total_emails_sent": total_emails, "total_emails_failed": total_failed,
        "total_emails_opened": total_opened, "open_rate": open_rate,
        "total_replies": total_replies, "interested_count": interested,
        "declined_count": declined, "pending_review": pending_review,
        "contacted_count": contacted, "confirmed_count": confirmed,
        "reply_rate": reply_rate, "interest_rate": interest_rate,
        "recent_emails": recent_emails, "score_distribution": score_dist,
        "email_activity": activity,
        "whatsapp": {
            "total": whatsapp_total,
            "sent": whatsapp_sent,
            "delivered": whatsapp_delivered,
            "failed": whatsapp_failed,
            "replies": whatsapp_replies,
            "delivery_rate": round((whatsapp_delivered / whatsapp_total * 100) if whatsapp_total else 0, 1),
        },
        "recent_whatsapp": recent_whatsapp,
    }


# ─── Delete Single Trainer ────────────────────────────────────────────────────

def _parse_dashboard_date(value: Optional[str], fallback: datetime, *, end_of_day: bool = False) -> datetime:
    if not value:
        return fallback
    try:
        text = value.strip()
        if len(text) == 10:
            parsed = datetime.fromisoformat(text)
            return parsed + timedelta(days=1) if end_of_day else parsed
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return fallback


def _dashboard_date_range(
    preset: str = "month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime, str]:
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())
    preset = (preset or "month").lower()
    if preset == "today":
        start = today_start
        end = start + timedelta(days=1)
    elif preset == "week":
        start = today_start - timedelta(days=today_start.weekday())
        end = start + timedelta(days=7)
    elif preset == "custom":
        start = _parse_dashboard_date(start_date, today_start - timedelta(days=30))
        end = _parse_dashboard_date(end_date, today_start + timedelta(days=1), end_of_day=True)
        if end <= start:
            end = start + timedelta(days=1)
    else:
        start = today_start.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        preset = "month"
    return start, end, preset


def _range_match(field: str, start: datetime, end: datetime) -> dict:
    return {field: {"$gte": start, "$lt": end}}


def _week_key(year: int, week: int) -> str:
    return f"{int(year)}-W{int(week):02d}"


def _week_start(dt: datetime) -> datetime:
    start = datetime.combine(dt.date(), datetime.min.time())
    return start - timedelta(days=start.weekday())


def _week_axis(start: datetime, end: datetime) -> list[dict]:
    current = _week_start(start)
    last = _week_start(end - timedelta(seconds=1))
    weeks = []
    guard = 0
    while current <= last and guard < 80:
        iso = current.isocalendar()
        weeks.append({
            "key": _week_key(iso.year, iso.week),
            "week": current.strftime("%d %b"),
            "opened": 0,
            "closed": 0,
        })
        current += timedelta(days=7)
        guard += 1
    return weeks


def _category_label(value: str) -> str:
    raw = (value or "").strip()
    low = raw.lower()
    if not raw:
        return "Uncategorised"
    mappings = [
        ("DevOps", ["devops", "docker", "kubernetes", "terraform", "jenkins", "ci/cd", "cicd"]),
        ("Gen AI", ["gen ai", "genai", "generative ai", "llm", "rag", "prompt"]),
        ("Python", ["python", "django", "flask", "pandas"]),
        ("Cloud", ["aws", "azure", "gcp", "cloud"]),
        ("Full Stack", ["react", "angular", "vue", "node", "full stack", "javascript", "typescript"]),
        ("Data Engineering", ["data engineering", "spark", "hadoop", "etl", "data pipeline"]),
        ("Cybersecurity", ["cyber", "security", "soc", "siem"]),
        ("MLOps", ["mlops", "machine learning operations"]),
        ("SRE", ["sre", "site reliability"]),
    ]
    for label, needles in mappings:
        if any(item in low for item in needles):
            return label
    if raw in {"Agentic AI", "AIOps", "LLMOps", "Multi-Skillset"}:
        return raw
    return raw[:32]


async def _distinct_count(db, collection: str, field: str, match: dict) -> int:
    docs = await db[collection].aggregate([
        {"$match": match},
        {"$group": {"_id": f"${field}"}},
        {"$match": {"_id": {"$nin": [None, ""]}}},
        {"$count": "count"},
    ]).to_list(1)
    return int(docs[0]["count"]) if docs else 0


async def _distinct_values(db, collection: str, field: str, match: dict) -> set:
    docs = await db[collection].aggregate([
        {"$match": match},
        {"$group": {"_id": f"${field}"}},
        {"$match": {"_id": {"$nin": [None, ""]}}},
    ]).to_list(10000)
    return {doc["_id"] for doc in docs if doc.get("_id")}


DEFAULT_COST_RATES_INR = {
    # These are estimator defaults. Override by saving admin_settings.costCfg.
    "whatsapp_outbound_message": 0.75,
    "whatsapp_inbound_message": 0.0,
    "teams_notification": 0.0,
    "gemini_input_1k_tokens": 0.0063,
    "gemini_output_1k_tokens": 0.0252,
    "gemini_input_tokens_per_call": 1800,
    "gemini_output_tokens_per_call": 700,
    "client_inbox_storage_gb_month": 20.0,
}


def _money(value: float) -> float:
    return round(float(value or 0), 2)


def _cost_number(value, default: float) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


async def _dashboard_cost_rates(db) -> dict:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "costCfg": 1},
    )
    cfg = (settings_doc or {}).get("costCfg") or {}
    return {
        key: _cost_number(cfg.get(key), default)
        for key, default in DEFAULT_COST_RATES_INR.items()
    }


async def _estimated_collection_bytes(db, collection: str, match: dict, limit: int = 5000) -> tuple[int, int]:
    total_bytes = 0
    count = 0
    async for doc in db[collection].find(match, {"_id": 0}).limit(limit):
        count += 1
        try:
            total_bytes += len(_json.dumps(doc, default=str).encode("utf-8"))
        except Exception:
            total_bytes += len(str(doc).encode("utf-8"))
    return total_bytes, count


async def _estimate_dashboard_expenses(db, start: datetime, end: datetime, weeks: list[dict]) -> dict:
    rates = await _dashboard_cost_rates(db)
    period_days = max((end - start).total_seconds() / 86400, 1)
    period_months = period_days / 30.44

    whatsapp_match = _range_match("created_at", start, end)
    whatsapp_outbound = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "direction": "outbound",
        "status": {"$in": ["queued", "sent", "delivered", "read"]},
    })
    whatsapp_inbound = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "direction": "inbound",
    })
    whatsapp_failed = await db["whatsapp_logs"].count_documents({
        **whatsapp_match,
        "status": {"$in": ["failed", "undelivered", "skipped"]},
    })

    teams_sent = await db["teams_logs"].count_documents({
        **_range_match("created_at", start, end),
        "status": "sent",
    })
    teams_failed = await db["teams_logs"].count_documents({
        **_range_match("created_at", start, end),
        "status": "failed",
    })

    client_processed = await db["client_emails"].count_documents(_range_match("received_at", start, end))
    client_auto_sent = await db["client_emails"].count_documents({
        **_range_match("received_at", start, end),
        "status": "auto_sent",
    })
    resume_gemini = await db["trainers"].count_documents({
        **_range_match("created_at", start, end),
        "extraction_source": "gemini",
    })

    usage_docs = await db["ai_usage_logs"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": None,
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
            "cost_inr": {"$sum": {"$ifNull": ["$cost_inr", 0]}},
        }},
    ]).to_list(1)
    actual_ai = usage_docs[0] if usage_docs else {}
    estimated_gemini_calls = (client_processed * 2) + resume_gemini
    estimated_input_tokens = estimated_gemini_calls * rates["gemini_input_tokens_per_call"]
    estimated_output_tokens = estimated_gemini_calls * rates["gemini_output_tokens_per_call"]
    logged_input_tokens = int(actual_ai.get("input_tokens") or 0)
    logged_output_tokens = int(actual_ai.get("output_tokens") or 0)
    logged_cost = float(actual_ai.get("cost_inr") or 0)
    if not logged_cost and (logged_input_tokens or logged_output_tokens):
        logged_cost = (
            (logged_input_tokens / 1000) * rates["gemini_input_1k_tokens"]
            + (logged_output_tokens / 1000) * rates["gemini_output_1k_tokens"]
        )
    estimated_unlogged_cost = (
        (estimated_input_tokens / 1000) * rates["gemini_input_1k_tokens"]
        + (estimated_output_tokens / 1000) * rates["gemini_output_1k_tokens"]
    )
    gemini_cost = logged_cost + estimated_unlogged_cost

    client_storage_bytes, client_storage_docs = await _estimated_collection_bytes(
        db,
        "client_emails",
        _range_match("received_at", start, end),
    )
    storage_gb = client_storage_bytes / (1024 ** 3)
    storage_cost = storage_gb * rates["client_inbox_storage_gb_month"] * period_months

    whatsapp_cost = (
        whatsapp_outbound * rates["whatsapp_outbound_message"]
        + whatsapp_inbound * rates["whatsapp_inbound_message"]
    )
    teams_cost = teams_sent * rates["teams_notification"]
    communication_total = whatsapp_cost + teams_cost
    ai_total = gemini_cost
    storage_total = storage_cost
    total = communication_total + ai_total + storage_total

    weekly_expenses = []
    current = _week_start(start)
    guard = 0
    week_lookup = {item["key"]: item for item in weeks}
    while current < end and guard < 80:
        week_end = min(current + timedelta(days=7), end)
        if week_end > start:
            w_start = max(current, start)
            iso = current.isocalendar()
            key = _week_key(iso.year, iso.week)

            w_whatsapp_outbound = await db["whatsapp_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "direction": "outbound",
                "status": {"$in": ["queued", "sent", "delivered", "read"]},
            })
            w_whatsapp_inbound = await db["whatsapp_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "direction": "inbound",
            })
            w_teams_sent = await db["teams_logs"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "status": "sent",
            })
            w_client_processed = await db["client_emails"].count_documents(_range_match("received_at", w_start, week_end))
            w_resume_gemini = await db["trainers"].count_documents({
                **_range_match("created_at", w_start, week_end),
                "extraction_source": "gemini",
            })
            w_gemini_calls = (w_client_processed * 2) + w_resume_gemini
            w_gemini = (
                (w_gemini_calls * rates["gemini_input_tokens_per_call"] / 1000) * rates["gemini_input_1k_tokens"]
                + (w_gemini_calls * rates["gemini_output_tokens_per_call"] / 1000) * rates["gemini_output_1k_tokens"]
            )
            w_bytes, _ = await _estimated_collection_bytes(db, "client_emails", _range_match("received_at", w_start, week_end))
            w_months = max((week_end - w_start).total_seconds() / 86400, 1) / 30.44
            w_storage = (w_bytes / (1024 ** 3)) * rates["client_inbox_storage_gb_month"] * w_months
            w_whatsapp = (
                w_whatsapp_outbound * rates["whatsapp_outbound_message"]
                + w_whatsapp_inbound * rates["whatsapp_inbound_message"]
            )
            w_teams = w_teams_sent * rates["teams_notification"]
            weekly_expenses.append({
                "key": key,
                "week": (week_lookup.get(key) or {}).get("week") or current.strftime("%d %b"),
                "whatsapp": _money(w_whatsapp),
                "teams": _money(w_teams),
                "gemini": _money(w_gemini),
                "storage": _money(w_storage),
                "total": _money(w_whatsapp + w_teams + w_gemini + w_storage),
            })
        current += timedelta(days=7)
        guard += 1

    return {
        "currency": "INR",
        "estimated": True,
        "total": _money(total),
        "communication_total": _money(communication_total),
        "ai_total": _money(ai_total),
        "storage_total": _money(storage_total),
        "items": [
            {
                "key": "whatsapp",
                "label": "WhatsApp Communication",
                "cost": _money(whatsapp_cost),
                "count": whatsapp_outbound + whatsapp_inbound,
                "unit": "messages",
                "note": f"{whatsapp_outbound} billable outbound, {whatsapp_inbound} inbound, {whatsapp_failed} failed/skipped",
            },
            {
                "key": "teams",
                "label": "Teams Communication",
                "cost": _money(teams_cost),
                "count": teams_sent,
                "unit": "notifications",
                "note": f"{teams_failed} failed webhook posts. Default Teams webhook cost is 0 unless you set a rate.",
            },
            {
                "key": "gemini",
                "label": "Gemini Text Generation",
                "cost": _money(gemini_cost),
                "count": int(actual_ai.get("calls") or 0) + estimated_gemini_calls,
                "unit": "AI calls",
                "note": f"{int(actual_ai.get('calls') or 0)} logged calls, {client_processed} client emails, {client_auto_sent} auto-sent replies, {resume_gemini} resume AI parses",
            },
            {
                "key": "client_storage",
                "label": "Client Inbox Cloud Storage",
                "cost": _money(storage_cost),
                "count": client_storage_docs,
                "unit": "stored emails",
                "note": f"{round(client_storage_bytes / 1024, 1)} KB stored in selected range",
            },
        ],
        "usage": {
            "whatsapp_outbound": whatsapp_outbound,
            "whatsapp_inbound": whatsapp_inbound,
            "whatsapp_failed": whatsapp_failed,
            "teams_sent": teams_sent,
            "teams_failed": teams_failed,
            "client_processed": client_processed,
            "client_auto_sent": client_auto_sent,
            "estimated_gemini_calls": estimated_gemini_calls,
            "logged_gemini_calls": int(actual_ai.get("calls") or 0),
            "logged_input_tokens": logged_input_tokens,
            "logged_output_tokens": logged_output_tokens,
            "estimated_input_tokens": int(estimated_input_tokens),
            "estimated_output_tokens": int(estimated_output_tokens),
            "client_storage_bytes": client_storage_bytes,
        },
        "rates": rates,
        "weekly": weekly_expenses,
    }


@router.get("/dashboard/analytics")
async def get_dashboard_analytics(
    preset: str = "month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    db = get_db()
    start, end, preset = _dashboard_date_range(preset, start_date, end_date)
    closed_statuses = ["closed", "completed", "fulfilled", "inactive", "cancelled", "archived"]
    req_range = _range_match("created_at", start, end)

    total_requirements = await db["requirements"].count_documents(req_range)
    po_req_ids_all = await _distinct_values(db, "purchase_orders", "requirement.requirement_id", {})
    closed_req_ids_all = await _distinct_values(db, "requirements", "requirement_id", {"status": {"$in": closed_statuses}})
    closed_ids_all = po_req_ids_all | closed_req_ids_all

    open_requirements = await db["requirements"].count_documents({
        **req_range,
        "status": {"$nin": closed_statuses},
        "requirement_id": {"$nin": list(closed_ids_all)},
    })
    closed_requirements = await db["requirements"].count_documents({
        **req_range,
        "$or": [
            {"status": {"$in": closed_statuses}},
            {"requirement_id": {"$in": list(po_req_ids_all)}},
        ],
    })

    shortlisted_ids = await _distinct_values(db, "shortlists", "requirement_id", {})
    emailed_ids = await _distinct_values(db, "email_logs", "requirement_id", {})
    in_pipeline_ids = (shortlisted_ids | emailed_ids) - closed_ids_all
    in_pipeline_requirements = await db["requirements"].count_documents({
        **req_range,
        "requirement_id": {"$in": list(in_pipeline_ids)},
    })

    avg_close_docs = await db["purchase_orders"].aggregate([
        {"$addFields": {"close_date": {"$ifNull": ["$acknowledged_at", {"$ifNull": ["$sent_at", "$created_at"]}]}}},
        {"$match": {"close_date": {"$gte": start, "$lt": end}}},
        {"$lookup": {
            "from": "requirements",
            "localField": "requirement.requirement_id",
            "foreignField": "requirement_id",
            "as": "req",
        }},
        {"$unwind": "$req"},
        {"$project": {"days": {"$divide": [{"$subtract": ["$close_date", "$req.created_at"]}, 86400000]}}},
        {"$group": {"_id": None, "avg": {"$avg": "$days"}}},
    ]).to_list(1)
    avg_days_to_close = round(float(avg_close_docs[0]["avg"]), 1) if avg_close_docs else 0

    weeks = _week_axis(start, end)
    week_index = {item["key"]: item for item in weeks}
    opened_docs = await db["requirements"].aggregate([
        {"$match": req_range},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$created_at"}, "week": {"$isoWeek": "$created_at"}},
            "count": {"$sum": 1},
        }},
    ]).to_list(100)
    for doc in opened_docs:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        if key in week_index:
            week_index[key]["opened"] = doc["count"]

    closed_week_docs = await db["purchase_orders"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$created_at"}, "week": {"$isoWeek": "$created_at"}},
            "ids": {"$addToSet": "$requirement.requirement_id"},
        }},
    ]).to_list(100)
    status_closed_week_docs = await db["requirements"].aggregate([
        {"$addFields": {"close_date": {"$ifNull": ["$closed_at", {"$ifNull": ["$updated_at", "$created_at"]}]}}},
        {"$match": {"status": {"$in": closed_statuses}, "close_date": {"$gte": start, "$lt": end}}},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$close_date"}, "week": {"$isoWeek": "$close_date"}},
            "ids": {"$addToSet": "$requirement_id"},
        }},
    ]).to_list(100)
    closed_by_week = {}
    for doc in [*closed_week_docs, *status_closed_week_docs]:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        closed_by_week.setdefault(key, set()).update(i for i in doc.get("ids", []) if i)
    for key, ids in closed_by_week.items():
        if key in week_index:
            week_index[key]["closed"] = len(ids)

    now = datetime.utcnow()
    month_start = datetime.combine(now.date(), datetime.min.time()).replace(day=1)
    month_end = month_start.replace(year=month_start.year + 1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month + 1)
    po_value_docs = await db["purchase_orders"].aggregate([
        {"$match": _range_match("created_at", month_start, month_end)},
        {"$group": {
            "_id": None,
            "value": {"$sum": {"$ifNull": ["$commercials.grand_total", 0]}},
            "count": {"$sum": 1},
        }},
    ]).to_list(1)
    po_month_value = round(float(po_value_docs[0]["value"]), 2) if po_value_docs else 0
    po_month_count = int(po_value_docs[0]["count"]) if po_value_docs else 0

    funnel = [
        {"stage": "New", "value": total_requirements},
        {"stage": "Shortlisted", "value": await _distinct_count(db, "shortlists", "requirement_id", _range_match("created_at", start, end))},
        {"stage": "Contacted", "value": await _distinct_count(db, "email_logs", "requirement_id", {"status": "sent", "sent_at": {"$gte": start, "$lt": end}})},
        {"stage": "Replied", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "reply_received": True,
            "$or": [{"replied_at": {"$gte": start, "$lt": end}}, {"created_at": {"$gte": start, "$lt": end}}],
        })},
        {"stage": "Interview", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "interview_scheduled": True,
            "$or": [{"interview_email_sent_at": {"$gte": start, "$lt": end}}, {"sent_at": {"$gte": start, "$lt": end}}],
        })},
        {"stage": "Selected", "value": await _distinct_count(db, "email_logs", "requirement_id", {
            "mail_type": "mail5_ok",
            "status": "sent",
            "sent_at": {"$gte": start, "$lt": end},
        })},
        {"stage": "PO", "value": await _distinct_count(db, "purchase_orders", "requirement.requirement_id", _range_match("created_at", start, end))},
    ]

    raw_categories = await db["requirements"].aggregate([
        {"$match": req_range},
        {"$project": {"category": {"$ifNull": ["$technology_category", "$technology_needed"]}}},
        {"$group": {"_id": "$category", "value": {"$sum": 1}}},
        {"$sort": {"value": -1}},
    ]).to_list(100)
    category_totals = {}
    for item in raw_categories:
        label = _category_label(item.get("_id", ""))
        category_totals[label] = category_totals.get(label, 0) + int(item.get("value", 0))
    if not category_totals:
        trainer_categories = await db["trainers"].aggregate([
            {"$project": {"category": {"$ifNull": ["$primary_category", {"$ifNull": ["$technology_category", "$category"]}]}}},
            {"$group": {"_id": "$category", "value": {"$sum": 1}}},
            {"$sort": {"value": -1}},
            {"$limit": 8},
        ]).to_list(20)
        for item in trainer_categories:
            label = _category_label(item.get("_id", ""))
            category_totals[label] = category_totals.get(label, 0) + int(item.get("value", 0))
    category_breakdown = [
        {"name": name, "value": value}
        for name, value in sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    trend_start = _week_start(now - timedelta(weeks=3))
    trend_weeks = _week_axis(trend_start, now + timedelta(days=1))[-4:]
    trend_index = {item["key"]: {**item, "sent": 0, "replies": 0, "reply_rate": 0} for item in trend_weeks}
    reply_trend_docs = await db["email_logs"].aggregate([
        {"$match": {"sent_at": {"$gte": trend_start, "$lt": now + timedelta(days=1)}, "status": "sent"}},
        {"$group": {
            "_id": {"year": {"$isoWeekYear": "$sent_at"}, "week": {"$isoWeek": "$sent_at"}},
            "sent": {"$sum": 1},
            "replies": {"$sum": {"$cond": ["$reply_received", 1, 0]}},
        }},
    ]).to_list(20)
    for doc in reply_trend_docs:
        key = _week_key(doc["_id"]["year"], doc["_id"]["week"])
        if key in trend_index:
            sent = int(doc.get("sent", 0))
            replies = int(doc.get("replies", 0))
            trend_index[key].update({
                "sent": sent,
                "replies": replies,
                "reply_rate": round((replies / sent * 100) if sent else 0, 1),
            })
    reply_rate_trend = list(trend_index.values())

    whatsapp_docs = await db["whatsapp_logs"].aggregate([
        {"$match": _range_match("created_at", start, end)},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "delivered": {"$sum": {"$cond": [{"$in": ["$status", ["delivered", "read"]]}, 1, 0]}},
            "sent": {"$sum": {"$cond": [{"$in": ["$status", ["sent", "queued", "delivered", "read"]]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "undelivered"]]}, 1, 0]}},
        }},
    ]).to_list(1)
    whatsapp = whatsapp_docs[0] if whatsapp_docs else {"total": 0, "delivered": 0, "sent": 0, "failed": 0}
    whatsapp_total = int(whatsapp.get("total", 0))
    whatsapp_delivered = int(whatsapp.get("delivered", 0))
    whatsapp_delivery_rate = round((whatsapp_delivered / whatsapp_total * 100) if whatsapp_total else 0, 1)
    expenses = await _estimate_dashboard_expenses(db, start, end, weeks)

    return {
        "range": {"preset": preset, "start": start.isoformat(), "end": end.isoformat()},
        "status_cards": {
            "total_open": open_requirements,
            "total_closed": closed_requirements,
            "total_in_pipeline": in_pipeline_requirements,
            "average_days_to_close": avg_days_to_close,
        },
        "requirements_weekly": weeks,
        "pipeline_funnel": funnel,
        "category_breakdown": category_breakdown,
        "po_month": {"value": po_month_value, "count": po_month_count, "currency": "INR"},
        "reply_rate_trend": reply_rate_trend,
        "whatsapp": {
            "total": whatsapp_total,
            "sent": int(whatsapp.get("sent", 0)),
            "delivered": whatsapp_delivered,
            "failed": int(whatsapp.get("failed", 0)),
            "delivery_rate": whatsapp_delivery_rate,
        },
        "expenses": expenses,
    }


@router.delete("/trainers/{trainer_id}")
async def delete_trainer(trainer_id: str):
    db = get_db()
    result = await db["trainers"].delete_one({"trainer_id": trainer_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Trainer not found")
    return {"message": f"Trainer {trainer_id} deleted", "deleted": True}


# ─── Send Email to Single Shortlisted Trainer ────────────────────────────────

@router.post("/emails/{email_id}/send-one")
async def send_email_to_one(email_id: str, request: Request, body: dict = {}):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    email_body = log["body"]
    custom_msg = body.get("message", "")
    if custom_msg:
        email_body = f"{custom_msg}\n\n---\n{email_body}"

    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""), log.get("trainer_phone", ""))
    email_result, whatsapp_result = await asyncio.gather(
        send_email_async(
            log["to_email"],
            log["subject"],
            email_body,
            smtp_config,
            build_tracking_url(request, email_id),
        ),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            subject=log.get("subject", ""),
            body=email_body,
            mail_type=log.get("mail_type", ""),
            requirement_id=log.get("requirement_id", ""),
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
    )
    success, error = email_result
    if success:
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"status": "sent", "sent_at": datetime.utcnow(), "error_message": ""},
             "$inc": {"retry_count": 1}}
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result}


# ─── Delete Requirement ───────────────────────────────────────────────────────

@router.delete("/requirements/{requirement_id}")
async def delete_requirement(requirement_id: str):
    db = get_db()
    r = await db["requirements"].delete_one({"requirement_id": requirement_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Requirement not found")
    await db["shortlists"].delete_many({"requirement_id": requirement_id})
    return {"message": f"Requirement {requirement_id} deleted", "deleted": True}


# ─── AI Reply Intent Analyzer ─────────────────────────────────────────────────
#
# Uses Gemini gemini-1.5-flash to accurately classify trainer reply intent.
# CRITICAL: negative phrases are matched FIRST before positive to avoid
# "not interested" being classified as positive due to "interested" substring.
#
def _keyword_intent(body: str) -> dict:
    t = body.lower().strip()
    # Negative checked FIRST — whole phrases only
    neg_phrases = [
        "not interested", "not available", "not able", "not in a position",
        "i am not", "i'm not", "i will not", "i wont", "i won't",
        "cannot", "cant", "can not", "unable", "no thanks", "no thank you",
        "decline", "declining", "unfortunately", "regret to",
        "busy", "unavailable", "withdraw", "not suitable",
        "not convenient", "pass on this", "not looking",
        "not considering", "no longer", "sorry, i",
    ]
    for phrase in neg_phrases:
        if phrase in t:
            return {"intent": "negative", "reason": f'Matched negative phrase: "{phrase}"',
                    "confidence": 0.92, "ai_used": False}

    # Positive only if no negative found
    pos_phrases = [
        "i am interested", "i'm interested", "i am available", "i'm available",
        "happy to", "glad to", "looking forward", "sounds good",
        "absolutely", "definitely", "please share", "will do",
        "let us proceed", "i can ", "yes, ", "sure, ",
        "confirm", "proceed", "accept", "agree to", "great opportunity",
    ]
    for phrase in pos_phrases:
        if phrase in t:
            return {"intent": "positive", "reason": f'Matched positive phrase: "{phrase}"',
                    "confidence": 0.85, "ai_used": False}

    return {"intent": "neutral", "reason": "No clear signal found", "confidence": 0.5, "ai_used": False}


@router.post("/ai/analyze-reply")
async def analyze_reply_intent(payload: dict):
    """
    Uses Claude AI to analyze trainer reply intent accurately.
    Returns: { intent, reason, confidence, ai_used }
    """
    reply_body   = (payload.get("reply_body") or "").strip()
    trainer_name = payload.get("trainer_name", "the trainer")
    stage        = payload.get("stage", "")
    requirement  = payload.get("requirement", "")

    if not reply_body:
        return {"intent": "neutral", "reason": "Empty reply body", "confidence": 0.5, "ai_used": False}

    # Strip quoted lines (lines starting with ">") — only analyze the trainer's own words
    clean_lines = [l for l in reply_body.splitlines() if not l.strip().startswith(">")]
    clean_body  = "\n".join(clean_lines).strip() or reply_body

    # Try Gemini AI first
    try:
        import httpx as _httpx
        from config import get_settings as _get_settings
        _settings = _get_settings()
        _api_key = os.getenv("GEMINI_API_KEY", "") or getattr(_settings, "gemini_api_key", "")
        if not _api_key:
            raise ValueError("GEMINI_API_KEY not set")
        prompt = f"""You are an expert email intent classifier for a trainer recruitment platform.

Trainer "{trainer_name}" replied to our email at pipeline stage: "{stage}".
Training requirement: "{requirement}".

Their reply:
---
{clean_body[:1500]}
---

Classify intent as exactly one of:
- "positive"  : interested, available, agreeable, willing to proceed, sharing details
- "negative"  : NOT interested, NOT available, declining, withdrawing, saying no
- "neutral"   : unclear, asking question without committing, out-of-office auto-reply

CRITICAL RULES:
1. "I am not interested" = NEGATIVE always.
2. "Not available" = NEGATIVE always.
3. Polite thank-you + decline = NEGATIVE.
4. Sharing experience/details/CV = POSITIVE.
5. Confirming slot/meeting = POSITIVE.
6. Question without declining = NEUTRAL.
7. Out-of-office / auto-reply = NEUTRAL.

Respond ONLY as valid JSON:
{{"intent": "positive or negative or neutral", "reason": "one sentence", "confidence": 0.0}}"""
        _url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={_api_key}"
        import asyncio as _asyncio
        async def _call():
            async with _httpx.AsyncClient(timeout=20) as _c:
                _r = await _c.post(_url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 150}})
                return _r.json()
        data = _asyncio.get_event_loop().run_until_complete(_call())
        raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if json_match:
            result = _json.loads(json_match.group())
            intent = result.get("intent", "neutral").lower()
            if intent not in ("positive", "negative", "neutral"):
                intent = "neutral"
            return {
                "intent":     intent,
                "reason":     result.get("reason", ""),
                "confidence": float(result.get("confidence", 0.85)),
                "ai_used":    True,
            }
    except Exception as e:
        print(f"[AI analyze-reply] Gemini API error: {e} — falling back to keyword matching")

    # Fallback — deterministic keyword classifier
    return _keyword_intent(clean_body)


@router.post("/ai/log-usage")
async def log_ai_usage(payload: dict):
    db = get_db()
    rates = await _dashboard_cost_rates(db)

    input_tokens = int(_cost_number(payload.get("input_tokens"), 0))
    output_tokens = int(_cost_number(payload.get("output_tokens"), 0))
    if not input_tokens:
        input_tokens = max(1, int(len(str(payload.get("prompt") or "")) / 4))
    if not output_tokens:
        output_tokens = max(1, int(len(str(payload.get("output") or "")) / 4))

    cost_inr = (
        (input_tokens / 1000) * rates["gemini_input_1k_tokens"]
        + (output_tokens / 1000) * rates["gemini_output_1k_tokens"]
    )
    doc = {
        "usage_id": f"AI-{uuid.uuid4().hex[:10].upper()}",
        "provider": payload.get("provider") or "gemini",
        "model": payload.get("model") or get_settings().gemini_model or "gemini-1.5-flash",
        "feature": payload.get("feature") or "text_generation",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_inr": _money(cost_inr),
        "metadata": payload.get("metadata") or {},
        "created_at": datetime.utcnow(),
    }
    await db["ai_usage_logs"].insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/trainers/resume-status/{upload_id}")
async def get_resume_status(upload_id: str):
    """Get the status of a resume upload."""
    db = get_db()
    upload = await db["resume_uploads"].find_one(
        {"upload_id": upload_id},
        {"_id": 0}
    )

    if not upload:
        raise HTTPException(404, "Resume upload not found")

    # Convert datetime objects to ISO strings for JSON serialization
    if isinstance(upload.get("created_at"), datetime):
        upload["created_at"] = upload["created_at"].isoformat()
    if isinstance(upload.get("processed_at"), datetime):
        upload["processed_at"] = upload["processed_at"].isoformat()

    return upload


@router.get("/trainers/by-upload/{upload_id}")
async def get_trainer_by_upload(upload_id: str):
    """Get the trainer record created from a resume upload."""
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    trainer = await db["trainers"].find_one(
        {"trainer_id": upload["trainer_id"]},
        {"_id": 0}
    )

    if not trainer:
        raise HTTPException(404, "Trainer not found")

    return {
        "upload_id": upload_id,
        "trainer": trainer,
        "extraction_status": upload.get("processing_status"),
    }


@router.post("/trainers/confirm-resume/{upload_id}")
async def confirm_resume_data(upload_id: str, background_tasks: BackgroundTasks, corrections: dict = {}):
    """
    Confirm extracted resume data and optionally apply corrections.
    Updates trainer record with confirmed data.
    """
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    profile = _profile_from_resume_upload(upload, corrections)
    save_result = await save_trainer_from_resume(profile, db, use_ai_tags=False)
    trainer_id = save_result.get("trainer_id")
    if trainer_id:
        background_tasks.add_task(_categorise_trainers_background, [trainer_id])

    return {
        "message": "Resume data confirmed and trainer updated",
        "upload_id": upload_id,
        "trainer_id": trainer_id,
        "extracted_data": profile,
        "background_categorisation": bool(trainer_id),
        **save_result,
    }

    return {
        "message": "✅ Resume data confirmed and trainer updated",
        "upload_id": upload_id,
        "trainer_id": trainer_id,
        "extracted_data": extracted_data,
        "categorisation": categorisation,
        "categorisation_error": categorisation_error,
    }


@router.get("/resume-uploads")
async def list_resume_uploads(status: Optional[str] = None, page: int = 1, limit: int = 20):
    """List all resume uploads with pagination."""
    db = get_db()
    query = {}
    if status:
        query["processing_status"] = status

    total = await db["resume_uploads"].count_documents(query)
    skip = (page - 1) * limit

    uploads = await db["resume_uploads"].find(query, {"_id": 0, "extracted_text": 0}).sort(
        "created_at", -1
    ).skip(skip).limit(limit).to_list(limit)

    # Convert datetime objects for JSON serialization
    for upload in uploads:
        if isinstance(upload.get("created_at"), datetime):
            upload["created_at"] = upload["created_at"].isoformat()
        if isinstance(upload.get("processed_at"), datetime):
            upload["processed_at"] = upload["processed_at"].isoformat()

    return {
        "uploads": uploads,
        "total": total,
        "page": page,
        "pages": -(-total // limit),
    }


@router.delete("/resume-uploads/{upload_id}")
async def delete_resume_upload(upload_id: str):
    """Delete a resume upload and its associated trainer record if it was only created from resume."""
    db = get_db()
    upload = await db["resume_uploads"].find_one({"upload_id": upload_id})
    if not upload:
        raise HTTPException(404, "Resume upload not found")

    trainer_id = upload["trainer_id"]

    # Delete upload
    await db["resume_uploads"].delete_one({"upload_id": upload_id})

    # Delete trainer if it was only created from this resume upload
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id})
    if trainer and trainer.get("source_sheet") == "resume_upload":
        await db["trainers"].delete_one({"trainer_id": trainer_id})

    return {
        "message": f"✅ Resume upload {upload_id} deleted",
        "trainer_deleted": trainer and trainer.get("source_sheet") == "resume_upload",
    }


# --- Client Inbox / Gmail Automation ---------------------------------------

@router.post("/gmail/webhook")
async def gmail_webhook(request: Request):
    db = get_db()
    try:
        payload = await request.json()
        decoded = _decode_pubsub_payload(payload)
        email_address = decoded.get("emailAddress")
        incoming_history_id = decoded.get("historyId")
        now = datetime.utcnow()

        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_webhook_received_at": now,
                "last_pubsub_payload": decoded,
                "gmail_user": email_address,
            }},
            upsert=True,
        )

        if not incoming_history_id:
            return {"status": "ok", "message": "No historyId in Pub/Sub payload"}

        service = get_gmail_service()
        sync = await db["gmail_sync"].find_one({"sync_id": "default"}, {"_id": 0})
        last_history_id = (sync or {}).get("last_history_id")
        if not last_history_id:
            await db["gmail_sync"].update_one(
                {"sync_id": "default"},
                {"$set": {"last_history_id": incoming_history_id}},
                upsert=True,
            )
            return {"status": "ok", "message": "Initialized Gmail history cursor"}

        try:
            message_ids, latest_history_id = get_history_message_ids(service, last_history_id)
        except Exception as exc:
            await db["gmail_sync"].update_one(
                {"sync_id": "default"},
                {"$set": {"last_history_id": incoming_history_id, "last_error": str(exc)}},
                upsert=True,
            )
            return {"status": "ok", "message": "History cursor reset", "error": str(exc)}

        settings = await _client_inbox_settings(db)
        whitelist = _parse_domain_csv(settings.get("clientDomainsWhitelist", ""))
        processed = []
        skipped = 0

        for message_id in message_ids:
            try:
                meta = _gmail_metadata(service, message_id)
                slot_doc = await _matching_client_slot_email(db, meta)
                if slot_doc:
                    slot_result = await _process_client_slot_reply(
                        db,
                        message_id,
                        service,
                        request,
                        meta_hint=meta,
                        slot_doc=slot_doc,
                    )
                    if slot_result:
                        processed.append(slot_result)
                        continue
                known_domain = await _known_client_domain(db, meta.get("from_email", ""))
                likely_training = known_domain or is_likely_training_email(
                    meta.get("subject", ""),
                    meta.get("from_email", ""),
                    whitelist,
                    meta.get("snippet", ""),
                )
                if not likely_training:
                    await db["client_emails"].update_one(
                        {"email_id": message_id},
                        {"$setOnInsert": {
                            **meta,
                            "received_at": now,
                            "raw_body": "",
                            "clean_body": "",
                            "extracted": {"is_training_request": False, "confidence": 0},
                            "generated_reply": {},
                            "requirement_id": None,
                            "status": "spam",
                            "confidence": 0,
                            "auto_send_eligible": False,
                            "sent_at": None,
                            "sent_by": None,
                            "whatsapp_notified": False,
                            "created_at": now,
                        }},
                        upsert=True,
                    )
                    skipped += 1
                    continue
                processed.append(await _process_and_store_client_message(db, message_id, service, request))
            except Exception as exc:
                await db["webhook_logs"].insert_one({
                    "webhook_type": "gmail_client_inbox",
                    "gmail_message_id": message_id,
                    "status": "error",
                    "error": str(exc),
                    "created_at": datetime.utcnow(),
                })

        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_history_id": latest_history_id or incoming_history_id,
                "last_processed_at": datetime.utcnow(),
                "last_processed_count": len(processed),
            }},
            upsert=True,
        )
        return {"status": "ok", "processed": processed, "skipped": skipped}
    except Exception as exc:
        print(f"Gmail webhook error: {exc}")
        return {"status": "ok", "error": str(exc)}


@router.post("/gmail/sync-now")
async def gmail_sync_now(request: Request, limit: int = 25):
    db = get_db()
    try:
        return await _sync_recent_client_inbox(db, request, limit)
    except Exception as exc:
        raise HTTPException(500, f"Gmail sync failed: {exc}") from exc


@router.get("/inbox")
async def get_client_inbox(status: Optional[str] = None, page: int = 1, limit: int = 20):
    db = get_db()
    query = {}
    if status and status != "all":
        query["status"] = status
    total = await db["client_emails"].count_documents(query)
    skip = (max(page, 1) - 1) * limit
    docs = await db["client_emails"].find(query, {"_id": 0}).sort("received_at", -1).skip(skip).limit(limit).to_list(limit)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {
        "today": await db["client_emails"].count_documents({"received_at": {"$gte": today}}),
        "pending_approval": await db["client_emails"].count_documents({"status": "pending_approval"}),
        "auto_sent": await db["client_emails"].count_documents({"status": "auto_sent"}),
        "requirements_created": await db["client_emails"].count_documents({"requirement_id": {"$nin": [None, ""]}}),
    }
    whatsapp_logs = await db["whatsapp_logs"].find(
        {"event_type": "client_requirement_inbox"},
        {"_id": 0},
    ).sort("created_at", -1).limit(5).to_list(5)
    return {
        "emails": [_public_doc(doc) for doc in docs],
        "total": total,
        "page": page,
        "pages": -(-total // limit) if limit else 1,
        "stats": stats,
        "whatsapp_logs": whatsapp_logs,
    }


@router.get("/client-updates")
async def get_client_updates(requirement_id: Optional[str] = None, limit: int = 30):
    db = get_db()
    query = {}
    if requirement_id:
        query["requirement_id"] = requirement_id

    limit = max(1, min(int(limit or 30), 100))
    try:
        docs = await db["client_slot_emails"].find(query, {"_id": 0}).sort(
            "_id", -1
        ).limit(limit).max_time_ms(3000).to_list(limit)
    except ExecutionTimeout:
        return {
            "updates": [],
            "total": 0,
            "warning": "Client updates are still loading. Please try again.",
        }

    requirement_ids = sorted({doc.get("requirement_id") for doc in docs if doc.get("requirement_id")})
    requirements = {}
    if requirement_ids:
        req_docs = await db["requirements"].find(
            {"requirement_id": {"$in": requirement_ids}},
            {"_id": 0, "requirement_id": 1, "technology_needed": 1, "client_company": 1, "client_name": 1},
        ).to_list(len(requirement_ids))
        requirements = {doc.get("requirement_id"): doc for doc in req_docs}

    email_ids = sorted({doc.get("email_id") for doc in docs if doc.get("email_id")})
    confirmations = {}
    if email_ids:
        try:
            conf_docs = await db["client_slot_confirmations"].find(
                {"client_slot_email_id": {"$in": email_ids}},
                {"_id": 0},
            ).sort("_id", -1).max_time_ms(3000).to_list(len(email_ids) * 2)
            for confirmation in conf_docs:
                confirmations.setdefault(confirmation.get("client_slot_email_id"), confirmation)
        except ExecutionTimeout:
            confirmations = {}

    updates = []
    for doc in docs:
        req = requirements.get(doc.get("requirement_id")) or {}
        confirmation = confirmations.get(doc.get("email_id")) or {}
        parsed_slot = doc.get("client_confirmed_slot") or confirmation.get("parsed_slot") or {}
        calendar_event = doc.get("calendar_event") or confirmation.get("calendar_event") or {}
        trainer_schedule_email = doc.get("trainer_schedule_email") or confirmation.get("trainer_schedule_email") or {}
        updates.append({
            **doc,
            "technology": req.get("technology_needed") or doc.get("technology") or "Training",
            "client_company": req.get("client_company") or doc.get("client_name") or req.get("client_name"),
            "confirmation_status": confirmation.get("status") or doc.get("status"),
            "confirmed_slot": parsed_slot,
            "meet_link": calendar_event.get("meet_link") or calendar_event.get("html_link") or "",
            "calendar_event_id": calendar_event.get("event_id"),
            "trainer_email_sent": bool(trainer_schedule_email.get("success")),
            "last_error": doc.get("calendar_error") or confirmation.get("error") or trainer_schedule_email.get("error") or doc.get("error_message") or "",
        })

    return {"updates": [_public_doc(update) for update in updates], "total": len(updates)}


@router.post("/inbox/{email_id}/approve")
async def approve_client_email(email_id: str, payload: dict = {}):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")

    reply = doc.get("generated_reply") or {}
    body = payload.get("body") or reply.get("body")
    subject = payload.get("subject") or reply.get("subject") or f"Re: {doc.get('subject', 'Training Requirement')}"
    if not body:
        raise HTTPException(400, "Reply body is required")

    service = get_gmail_service()
    send_result = send_gmail_reply(
        service,
        to_email=doc.get("from_email", ""),
        subject=subject,
        body=body,
        thread_id=doc.get("thread_id", ""),
        in_reply_to=doc.get("message_id_header", ""),
    )
    now = datetime.utcnow()
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "generated_reply.subject": subject,
            "generated_reply.body": body,
            "status": "approved",
            "sent_at": now,
            "sent_by": payload.get("sent_by") or "recruiter",
            "gmail_send_result": send_result,
        }},
    )
    if doc.get("requirement_id"):
        await db["requirements"].update_one(
            {"requirement_id": doc["requirement_id"]},
            {"$set": {"status": "active", "client_reply_sent_at": now}},
        )
    return {"success": True, "gmail": send_result}


@router.post("/inbox/{email_id}/reject")
async def reject_client_email(email_id: str):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")
    if doc.get("requirement_id"):
        await db["requirements"].delete_one({
            "requirement_id": doc["requirement_id"],
            "source": "email_auto",
        })
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"status": "rejected", "rejected_at": datetime.utcnow()}},
    )
    return {"success": True}


@router.post("/inbox/{email_id}/regenerate-reply")
async def regenerate_client_reply(email_id: str, payload: dict = {}):
    db = get_db()
    doc = await db["client_emails"].find_one({"email_id": email_id})
    if not doc:
        raise HTTPException(404, "Client email not found")
    settings = await _client_inbox_settings(db)
    context = {
        "subject": doc.get("subject", ""),
        "reply_signature": settings.get("replySignature"),
        "instruction": payload.get("instruction", ""),
    }
    extracted = doc.get("extracted") or {}
    if payload.get("instruction"):
        extracted = {
            **extracted,
            "needs_clarification": [
                *(extracted.get("needs_clarification") or []),
                f"Recruiter instruction: {payload.get('instruction')}",
            ],
        }
    reply = await generate_calhan_reply(extracted, context)
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"generated_reply": reply, "reply_regenerated_at": datetime.utcnow()}},
    )
    return {"success": True, "generated_reply": reply}


@router.get("/gmail/auth-status")
async def gmail_auth_status():
    db = get_db()
    return await get_gmail_auth_status(db)


@router.get("/gmail/oauth-url")
async def gmail_oauth_url(redirect_uri: Optional[str] = None):
    try:
        return get_gmail_oauth_url(redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            400,
            f"{exc}. Download OAuth credentials from Google Cloud and save them as backend/config/credentials.json.",
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/gmail/oauth-callback")
async def gmail_oauth_callback(payload: dict):
    try:
        return save_gmail_oauth_token(
            code=payload.get("code", ""),
            redirect_uri=payload.get("redirect_uri"),
        )
    except Exception as exc:
        raise HTTPException(400, f"Gmail OAuth failed: {exc}")


@router.post("/gmail/renew-watch")
async def gmail_renew_watch():
    db = get_db()
    try:
        return await renew_gmail_watch(db)
    except FileNotFoundError as exc:
        raise HTTPException(
            400,
            (
                f"{exc}. Put your Google OAuth Desktop credentials at "
                "backend/config/credentials.json, then run "
                "python scripts/gmail_auth.py from the backend folder to create token.json."
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Gmail watch renewal failed: {exc}")


@router.post("/gmail/disconnect")
async def gmail_disconnect():
    try:
        from agents.client_intelligence_agent import TOKEN_PATH
        if os.path.exists(TOKEN_PATH):
            os.remove(TOKEN_PATH)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    db = get_db()
    await db["gmail_sync"].update_one(
        {"sync_id": "default"},
        {"$set": {"disconnected_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"success": True, "connected": False}
