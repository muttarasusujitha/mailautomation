"""Send email endpoints."""
import base64
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr
from pymongo.errors import DuplicateKeyError

from shared.database.service import get_db
from app.gmail_client import generate_message_id, is_send_quota_error, send_email_async, _normalize_trainer_reply_body

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_quota_retry_after(value: Any) -> Optional[datetime]:
    match = re.search(r"Retry after ([^\".]+(?:\.\d+)?Z)", str(value or ""))
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def _gmail_quota_cooldown(db: AsyncIOMotorDatabase) -> Optional[datetime]:
    doc = await db["mail_send_cooldowns"].find_one({"_id": "gmail_send_quota"}, {"_id": 0, "retry_after": 1})
    retry_after = (doc or {}).get("retry_after")
    if isinstance(retry_after, datetime) and retry_after > datetime.utcnow():
        return retry_after
    return None


async def _remember_gmail_quota_cooldown(db: AsyncIOMotorDatabase, error: Any) -> Optional[datetime]:
    retry_after = _parse_quota_retry_after(error)
    if not retry_after:
        return None
    await db["mail_send_cooldowns"].update_one(
        {"_id": "gmail_send_quota"},
        {
            "$set": {
                "retry_after": retry_after,
                "error_message": str(error or ""),
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )
    return retry_after


def _ics_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _parse_ics_datetime(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("calendar start/end is required")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=None)
    return parsed.astimezone().replace(tzinfo=None)


def _format_ics_datetime(value: str) -> str:
    return _parse_ics_datetime(value).strftime("%Y%m%dT%H%M%S")


def _fold_ics_line(line: str) -> str:
    if len(line) <= 74:
        return line
    chunks = [line[:74]]
    rest = line[74:]
    while rest:
        chunks.append(" " + rest[:73])
        rest = rest[73:]
    return "\r\n".join(chunks)


def _build_calendar_invite_ics(invite: "CalendarInvite", fallback_attendee_email: str) -> str:
    attendee_email = str(invite.attendee_email or fallback_attendee_email or "").strip()
    organizer_email = str(invite.organizer_email or "").strip()
    meeting_url = str(invite.meeting_url or "").strip()
    location = str(invite.location or ("Online Meeting" if meeting_url else "")).strip()
    description = str(invite.description or "").strip()
    if meeting_url and meeting_url not in description:
        description = f"{description}\n\nJoin meeting: {meeting_url}".strip()

    uid = f"{uuid.uuid4().hex}@trainersync.local"
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    timezone_name = invite.timezone or "Asia/Kolkata"
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Clahan Technologies//Trainer Interview//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART;TZID={timezone_name}:{_format_ics_datetime(invite.start)}",
        f"DTEND;TZID={timezone_name}:{_format_ics_datetime(invite.end)}",
        f"SUMMARY:{_ics_escape(invite.summary)}",
        f"LOCATION:{_ics_escape(location)}",
        f"DESCRIPTION:{_ics_escape(description)}",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
    ]
    if organizer_email:
        organizer_name = _ics_escape(invite.organizer_name or "Clahan Technologies")
        lines.append(f"ORGANIZER;CN={organizer_name}:mailto:{organizer_email}")
    if attendee_email:
        attendee_name = _ics_escape(invite.attendee_name or attendee_email)
        lines.append(
            f"ATTENDEE;CN={attendee_name};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{attendee_email}"
        )
    if meeting_url:
        lines.append(f"URL:{_ics_escape(meeting_url)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(_fold_ics_line(line) for line in lines) + "\r\n"


class EmailAttachment(BaseModel):
    filename: str
    content_base64: str
    subtype: Optional[str] = "pdf"


class CalendarInvite(BaseModel):
    summary: str
    start: str
    end: str
    timezone: Optional[str] = "Asia/Kolkata"
    location: Optional[str] = ""
    description: Optional[str] = ""
    organizer_name: Optional[str] = "Clahan Technologies"
    organizer_email: Optional[str] = ""
    attendee_name: Optional[str] = ""
    attendee_email: Optional[str] = ""
    meeting_url: Optional[str] = ""


class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    smtp_config: Optional[Dict[str, Any]] = None
    tracking_url: Optional[str] = ""
    customer_id: Optional[str] = None
    requirement_id: Optional[str] = None
    mail_type: Optional[str] = None
    trainer_id: Optional[str] = None
    trainer_name: Optional[str] = None
    idempotency_key: Optional[str] = None
    attachments: Optional[List[EmailAttachment]] = None
    calendar_invite: Optional[CalendarInvite] = None
    ai_generate: bool = False
    ai_context: Optional[Dict[str, Any]] = None


class BulkEmailRequest(BaseModel):
    payloads: List[SendEmailRequest]
    smtp_config: Optional[Dict[str, Any]] = None


@router.post("/send")
async def send_single_email(
    payload: SendEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    body = _normalize_trainer_reply_body(payload.body)
    generation_source = "template"
    # This opt-in is used only by controlled pipeline callers.  The supplied
    # body remains the authoritative fallback: the model may improve wording
    # but cannot change links, attachments, commercials, slots, or stage.
    if payload.ai_generate:
        setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
        if str(setting.get("value") or "").strip().lower() == "ai":
            try:
                from app.routes.inbox_actions import _ai_draft_reply

                generated = await _ai_draft_reply(
                    subject=payload.subject,
                    body=body,
                    hint=(
                        "Write this recipient-facing workflow email naturally and concisely. Preserve every verified fact in the "
                        "reference exactly, including links, dates, times, requested next action, and attachments. "
                        "Do not invent commercial, availability, trainer details, or completion status."
                    ),
                    workflow_context=payload.ai_context or {},
                    reference_reply={"body": body},
                    require_openai=True,
                )
                if str(generated or "").strip():
                    body = _normalize_trainer_reply_body(generated.strip())
                    generation_source = "ai"
                else:
                    generation_source = "template_fallback"
            except Exception:
                logger.exception("Client pipeline AI wording failed; using approved template")
                generation_source = "template_fallback"
    idempotency_key = str(payload.idempotency_key or "").strip()
    existing_log = None
    if idempotency_key:
        existing_log = await db.email_logs.find_one(
            {"idempotency_key": idempotency_key},
            {"_id": 0, "email_id": 1, "status": 1, "sent_at": 1, "error_message": 1},
        )
        existing_status = (existing_log or {}).get("status")
        existing_updated_at = (existing_log or {}).get("updated_at") or (existing_log or {}).get("created_at")
        stale_sending = False
        if existing_status == "sending":
            try:
                stale_sending = bool(existing_updated_at and existing_updated_at < datetime.utcnow() - timedelta(minutes=10))
            except TypeError:
                stale_sending = False
        if existing_log and (existing_status == "sent" or (existing_status == "sending" and not stale_sending)):
            return {
                "success": True,
                "email_id": existing_log.get("email_id"),
                "sent_at": existing_log.get("sent_at"),
                "already_sent": existing_log.get("status") == "sent",
                "already_in_progress": existing_log.get("status") == "sending",
            }

    quota_retry_after = await _gmail_quota_cooldown(db)
    if quota_retry_after:
        raise HTTPException(
            429,
            detail={
                "message": "Gmail sending quota cooldown is active",
                "retry_after": quota_retry_after.isoformat() + "Z",
                "error": "Previous Gmail send attempt hit quota. The system is holding new sends until the retry time.",
            },
        )

    attachments = []
    # Keep the exact client-facing lab-cost workbook in the delivery log.  This
    # lets the Lab Cost screen provide an auditable re-download of the file
    # that was actually sent, without retaining unrelated CV/profile files.
    lab_cost_workbooks: List[Dict[str, str]] = []
    if payload.attachments:
        for att in payload.attachments:
            try:
                attachments.append({
                    "filename": att.filename,
                    "content": base64.b64decode(att.content_base64),
                    "subtype": att.subtype or "pdf",
                })
                filename_lower = (att.filename or "").lower()
                if "lab" in filename_lower and "cost" in filename_lower and filename_lower.endswith((".xlsx", ".xls")):
                    lab_cost_workbooks.append({
                        "filename": att.filename,
                        "subtype": att.subtype or "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "content_base64": att.content_base64,
                    })
            except Exception as exc:
                raise HTTPException(400, detail={"message": "Invalid attachment encoding", "error": str(exc)})
    if payload.calendar_invite:
        try:
            invite = payload.calendar_invite
            ics = _build_calendar_invite_ics(invite, payload.to)
            attachments.append({
                "filename": "interview-invite.ics",
                "content": ics.encode("utf-8"),
                "subtype": "calendar",
                "content_type": "text/calendar",
            })
        except Exception as exc:
            raise HTTPException(400, detail={"message": "Invalid calendar invite", "error": str(exc)})
    # Log attachment filenames for debugging
    if attachments:
        try:
            # also print to stdout to ensure container logs capture this
            print(f"Received {len(attachments)} attachment(s) for {payload.to}: " + ", ".join(a.get('filename','<unknown>') for a in attachments))
            logger.info("Received %d attachment(s) for %s: %s", len(attachments), payload.to, 
                        ", ".join(a.get('filename','<unknown>') for a in attachments))
        except Exception:
            logger.exception("Failed to log attachment filenames")

    message_id_header = generate_message_id()
    now = datetime.utcnow()
    email_id = (existing_log or {}).get("email_id") or f"EML-{uuid.uuid4().hex[:10].upper()}"
    log = {
        "email_id": email_id,
        "direction": "outbound",
        "recipient": payload.to,
        "to_email": payload.to,
        "subject": payload.subject,
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": body,
        "body_snippet": body[:300],
        "status": "sending" if idempotency_key else "pending_send",
        "error_message": "",
        "customer_id": payload.customer_id,
        "requirement_id": payload.requirement_id,
        "mail_type": payload.mail_type,
        "generation_source": generation_source,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "attachment_names": [item.get("filename", "") for item in attachments if item.get("filename")],
        "lab_cost_workbooks": lab_cost_workbooks,
        "sent_at": None,
        "created_at": now,
        "updated_at": now,
    }
    if idempotency_key:
        log["idempotency_key"] = idempotency_key
    preinserted = False
    if idempotency_key:
        if existing_log:
            log_for_retry = dict(log)
            log_for_retry.pop("created_at", None)
            await db.email_logs.update_one({"idempotency_key": idempotency_key}, {"$set": log_for_retry})
            preinserted = True
        else:
            try:
                await db.email_logs.insert_one(dict(log))
                preinserted = True
            except DuplicateKeyError:
                existing_log = await db.email_logs.find_one(
                    {"idempotency_key": idempotency_key},
                    {"_id": 0, "email_id": 1, "status": 1, "sent_at": 1},
                ) or {}
                return {
                    "success": True,
                    "email_id": existing_log.get("email_id"),
                    "sent_at": existing_log.get("sent_at"),
                    "already_sent": existing_log.get("status") == "sent",
                    "already_in_progress": existing_log.get("status") != "sent",
                }

    success, error = await send_email_async(
        to=payload.to,
        subject=payload.subject,
        body=body,
        smtp_config=payload.smtp_config,
        tracking_url=payload.tracking_url or "",
        attachments=attachments,
        message_id_header=message_id_header,
    )
    now = datetime.utcnow()
    final_update = {
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "updated_at": now,
    }
    log.update(final_update)
    if preinserted:
        await db.email_logs.update_one({"email_id": email_id}, {"$set": final_update})
    else:
        await db.email_logs.insert_one(log)
    log.pop("_id", None)

    if not success:
        if is_send_quota_error(error):
            await _remember_gmail_quota_cooldown(db, error)
        raise HTTPException(502, detail={"message": "Email delivery failed", "error": error})
    return {"success": True, "email_id": log["email_id"], "sent_at": now}


@router.post("/send/bulk")
async def send_bulk_emails(
    payload: BulkEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    import asyncio
    quota_retry_after = await _gmail_quota_cooldown(db)
    if quota_retry_after:
        return {
            "total": len(payload.payloads),
            "sent": 0,
            "failed": len(payload.payloads),
            "quota_blocked": True,
            "retry_after": quota_retry_after.isoformat() + "Z",
            "results": [],
        }
    results = []
    for item in payload.payloads:
        cfg = item.smtp_config or payload.smtp_config
        body = _normalize_trainer_reply_body(item.body)
        attachments = []
        if item.attachments:
            for att in item.attachments:
                try:
                    attachments.append({
                        "filename": att.filename,
                        "content": base64.b64decode(att.content_base64),
                        "subtype": att.subtype or "pdf",
                    })
                except Exception as exc:
                    return HTTPException(400, detail={"message": "Invalid attachment encoding", "error": str(exc)})
        if item.calendar_invite:
            try:
                ics = _build_calendar_invite_ics(item.calendar_invite, item.to)
                attachments.append({
                    "filename": "interview-invite.ics",
                    "content": ics.encode("utf-8"),
                    "subtype": "calendar",
                    "content_type": "text/calendar",
                })
            except Exception as exc:
                return HTTPException(400, detail={"message": "Invalid calendar invite", "error": str(exc)})
        message_id_header = generate_message_id()
        success, error = await send_email_async(
            to=item.to,
            subject=item.subject,
            body=body,
            smtp_config=cfg,
            tracking_url=item.tracking_url or "",
            attachments=attachments,
            message_id_header=message_id_header,
        )
        now = datetime.utcnow()
        log = {
            "email_id": f"EML-{uuid.uuid4().hex[:10].upper()}",
            "direction": "outbound",
            "recipient": item.to,
            "to_email": item.to,
            "subject": item.subject,
            "gmail_message_id": message_id_header,
            "message_id_header": message_id_header,
            "body": body,
            "body_snippet": body[:300],
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "customer_id": item.customer_id,
            "requirement_id": item.requirement_id,
            "mail_type": item.mail_type,
            "trainer_id": item.trainer_id,
            "trainer_name": item.trainer_name,
            "sent_at": now if success else None,
            "created_at": now,
            "updated_at": now,
        }
        await db.email_logs.insert_one(log)
        log.pop("_id", None)
        quota_blocked = is_send_quota_error(error)
        results.append({
            "email_id": log["email_id"],
            "to": item.to,
            "success": success,
            "error": error,
            "quota_blocked": quota_blocked,
        })
        if quota_blocked:
            await _remember_gmail_quota_cooldown(db, error)
            break
        if success:
            await asyncio.sleep(1.5)

    sent = sum(1 for r in results if r["success"])
    return {"total": len(results), "sent": sent, "failed": len(results) - sent, "results": results}
