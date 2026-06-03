from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Response, BackgroundTasks
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from utils.time_utils import utc_from_timestamp, utc_now
import uuid
import re as _re
import json as _json
import base64 as _base64
import io
import zipfile
import os
import logging
import html as _html
import smtplib
import asyncio
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
    compose_shortlist_first_email,
    get_gmail_password,
)
from agents.client_slot_agent import (
    ClientSlotError,
    looks_like_trainer_slots,
    send_client_slot_options_email,
    send_client_slots_for_email_log,
    send_pending_client_slot_replies,
)
from agents.teams_agent import send_teams_stage_notification
from agents.teams_direct_agent import (
    exchange_microsoft_code,
    get_teams_direct_config,
    microsoft_oauth_url,
    send_trainer_teams_direct_message,
)
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
logger = logging.getLogger(__name__)
CATEGORISATION_JOBS = {}

SELECTION_LOCK_STATUSES = {
    "selected",
    "trainer_selected_auto_sent",
    "toc_requested",
    "training_confirmed",
    "closed",
    "fulfilled",
}

TRACKING_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


def _id_text(value) -> str:
    return str(value or "").strip()


def _requirement_selection_lock(requirement: Optional[dict]) -> dict:
    requirement = requirement or {}
    selected_trainer_id = _id_text(requirement.get("selected_trainer_id"))
    selection_status = _id_text(requirement.get("selection_status") or requirement.get("status")).lower()
    return {
        "locked": bool(selected_trainer_id) or selection_status in SELECTION_LOCK_STATUSES,
        "selected_trainer_id": selected_trainer_id,
        "selected_trainer_name": _id_text(requirement.get("selected_trainer_name")),
        "selection_status": selection_status,
    }


async def _requirement_trainer_send_guard(db, requirement_id: str, trainer_id: str) -> tuple[bool, dict, dict]:
    if not requirement_id:
        return True, {}, {}

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    lock = _requirement_selection_lock(requirement)
    selected_trainer_id = lock["selected_trainer_id"]
    if not lock["locked"] or (selected_trainer_id and _id_text(trainer_id) == selected_trainer_id):
        return True, {}, requirement

    selected_label = lock["selected_trainer_name"] or selected_trainer_id or "another trainer"
    return False, {
        "success": True,
        "skipped": True,
        "status": "requirement_already_selected",
        "reason": f"{selected_label} is already selected for this requirement. Further trainer mails are stopped.",
        "requirement_id": requirement_id,
        "selected_trainer_id": selected_trainer_id,
        "selected_trainer_name": lock["selected_trainer_name"],
    }, requirement


async def _mark_requirement_selected_and_stop_others(
    db,
    *,
    requirement_id: str,
    trainer_id: str,
    trainer_name: str,
    selected_at: datetime,
) -> None:
    if not requirement_id or not trainer_id:
        return

    stop_reason = f"{trainer_name or 'Selected trainer'} selected for this requirement"
    selected_fields = {
        "selected_trainer_id": trainer_id,
        "selected_trainer_name": trainer_name,
        "selection_status": "selected",
        "selected_at": selected_at,
        "remaining_trainers_stopped": True,
        "remaining_trainers_stopped_at": selected_at,
    }
    await db["requirements"].update_one(
        {"requirement_id": requirement_id},
        {"$set": selected_fields},
    )
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id},
        {"$set": selected_fields},
    )

    try:
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "top_trainers.$[selected].pipeline_status": "selected",
                "top_trainers.$[selected].status": "selected",
            }},
            array_filters=[{"selected.trainer_id": trainer_id}],
        )
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "top_trainers.$[other].pipeline_status": "stopped_selected",
                "top_trainers.$[other].status": "stopped_selected",
                "top_trainers.$[other].stopped_reason": stop_reason,
                "top_trainers.$[other].stopped_at": selected_at,
            }},
            array_filters=[{"other.trainer_id": {"$ne": trainer_id}}],
        )
    except Exception:
        pass

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


def _reply_sentiment_and_action(body: str) -> dict:
    text = str(body or "").lower()
    negative = [
        "not interested", "not available", "not able", "unable", "cannot",
        "can't", "decline", "declining", "busy", "not convenient", "withdraw",
    ]
    positive = [
        "available", "interested", "confirm", "confirmed", "accept", "accepted",
        "happy to", "sure", "okay", " ok ", "yes", "schedule", "agree", "proceed",
    ]
    if any(item in text for item in negative):
        return {"sentiment": "negative", "action": "mark_declined"}
    if any(item in text for item in positive):
        return {"sentiment": "positive", "action": "mark_interested"}
    return {"sentiment": "neutral", "action": "requires_review"}


def _email_key(value: str = "") -> str:
    _, addr = _parseaddr(str(value or ""))
    return (addr or value or "").strip().lower()


def _check_gmail_replies_fast(
    *,
    since_days: int = 14,
    max_messages: int = 50,
    from_emails: Optional[List[str]] = None,
) -> tuple[bool, List[dict], str]:
    try:
        service = get_gmail_service()
        target_emails = sorted({
            _email_key(item)
            for item in (from_emails or [])
            if _email_key(item) and "@" in _email_key(item)
        })
        queries = []
        if target_emails:
            chunk_size = 12
            for i in range(0, min(len(target_emails), 96), chunk_size):
                chunk = target_emails[i:i + chunk_size]
                from_terms = " ".join(f"from:{addr}" for addr in chunk)
                queries.append(f"in:inbox newer_than:{int(since_days)}d {{{from_terms}}} -from:me")
        else:
            queries.append(f"in:inbox newer_than:{int(since_days)}d -from:me")

        message_ids = []
        seen = set()
        per_query_limit = max(10, min(50, max_messages))
        for query in queries:
            response = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=per_query_limit,
            ).execute()
            for item in response.get("messages", []) or []:
                message_id = item.get("id")
                if message_id and message_id not in seen:
                    seen.add(message_id)
                    message_ids.append(message_id)
                if len(message_ids) >= max_messages:
                    break
            if len(message_ids) >= max_messages:
                break

        replies: List[dict] = []
        target_set = set(target_emails)
        for message_id in message_ids:
            meta = fetch_gmail_email(message_id, service)
            from_email = _email_key(meta.get("from_email", ""))
            if target_set and from_email not in target_set:
                continue
            body = (meta.get("clean_body") or meta.get("raw_body") or "")[:2000]
            verdict = _reply_sentiment_and_action(body)
            headers = meta.get("headers") or {}
            received_at = meta.get("received_at") or utc_now()
            replies.append({
                "msg_id": message_id,
                "message_id_header": headers.get("message-id", "") or meta.get("message_id_header", ""),
                "in_reply_to": headers.get("in-reply-to", ""),
                "references": headers.get("references", ""),
                "from_email": from_email,
                "from_raw": meta.get("from_email", ""),
                "subject": meta.get("subject", ""),
                "body": body,
                "sentiment": verdict["sentiment"],
                "action": verdict["action"],
                "received_at": received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at),
            })
        return True, replies, ""
    except Exception as exc:
        return False, [], str(exc)


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
    if trainer_id:
        trainer = await db["trainers"].find_one(
            {"trainer_id": trainer_id},
            {"_id": 0, "phone": 1},
        )
        if (trainer or {}).get("phone"):
            return trainer["phone"]
    return fallback or ""


async def _trainer_for_direct_teams(db, trainer_id: str, fallback: Optional[dict] = None) -> dict:
    fallback = fallback or {}
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    merged = {**fallback, **trainer}
    if trainer_id and not merged.get("trainer_id"):
        merged["trainer_id"] = trainer_id
    return merged


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


def _trainer_greeting(name: str = "") -> str:
    clean = str(name or "").strip()
    return f"Dear {clean or 'Trainer'},"


def _client_note_excerpt(text: str, max_chars: int = 900) -> str:
    clean = _strip_quoted_reply_text(text)
    clean = "\n".join(line.rstrip() for line in clean.splitlines()).strip()
    while "\n\n\n" in clean:
        clean = clean.replace("\n\n\n", "\n\n")
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rsplit(" ", 1)[0].strip() + "..."


def _detect_client_interview_decision(subject: str = "", body: str = "") -> dict:
    text = _re.sub(r"\s+", " ", f"{subject or ''} {body or ''}".lower()).strip()
    if not text:
        return {"decision": "", "confidence": 0, "reason": "empty"}
    subject_text = str(subject or "").lower().strip()
    if (
        _re.match(r"^(accepted|declined|tentatively accepted|updated invitation|canceled|cancelled):", subject_text)
        or "has accepted this invitation" in text
        or "has declined this invitation" in text
        or "has tentatively accepted this invitation" in text
    ):
        return {"decision": "", "confidence": 0, "reason": "calendar rsvp"}

    rejection_patterns = [
        r"\bnot\s+selected\b",
        r"\bnot\s+shortlisted\b",
        r"\bnot\s+select(?:ing|ed)?\b",
        r"\breject(?:ed|ing)?\b",
        r"\bdeclin(?:ed|ing)e?\b",
        r"\bnot\s+proceed(?:ing)?\b",
        r"\bwill\s+not\s+proceed\b",
        r"\bmove\s+to\s+next\s+trainer\b",
        r"\bgo\s+with\s+another\s+trainer\b",
        r"\bnot\s+fit\b",
        r"\bnot\s+suitable\b",
    ]
    selection_patterns = [
        r"\bselected\b",
        r"\bshortlisted\b",
        r"\bapproved\b",
        r"\bconfirm(?:ed)?\s+(?:the\s+)?trainer\b",
        r"\bproceed\s+with\b",
        r"\bgo\s+ahead\s+with\b",
        r"\bfinali[sz]ed\b",
        r"\bwe\s+can\s+proceed\b",
        r"\btrainer\s+is\s+confirmed\b",
        r"\bhe\s+is\s+selected\b",
        r"\bshe\s+is\s+selected\b",
    ]

    for pattern in rejection_patterns:
        if _re.search(pattern, text):
            return {"decision": "rejected", "confidence": 0.9, "reason": pattern}
    for pattern in selection_patterns:
        if _re.search(pattern, text):
            return {"decision": "selected", "confidence": 0.86, "reason": pattern}
    return {"decision": "", "confidence": 0, "reason": "no decision phrase"}


def _decision_mail_templates(trainer: dict, requirement: dict, decision: str, client_note: str = "") -> list:
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or ""
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "the training requirement"
    greeting = _trainer_greeting(trainer_name)
    note_block = f"\n\nClient note:\n{client_note}" if client_note else ""

    if decision == "selected":
        return [
            {
                "mail_type": "mail5_ok",
                "subject": f"Congratulations! You have been Selected - {technology}",
                "body": (
                    f"{greeting}\n\n"
                    f"Congratulations! The client has selected you for the {technology} training requirement."
                    f"{note_block}\n\n"
                    "We will coordinate the next steps and documentation with you shortly.\n\n"
                    "Regards,\nTrainerSync Team"
                ),
            },
        ]

    return [
        {
            "mail_type": "mail5_no",
            "subject": f"Update on Training Requirement - {technology}",
            "body": (
                f"{greeting}\n\n"
                f"Thank you for your time and interest in the {technology} training requirement.\n\n"
                "After the client discussion, we regret to inform you that the client has decided not to proceed with your profile for this requirement."
                f"{note_block}\n\n"
                "We will keep your profile on record and reach out for suitable future opportunities.\n\n"
                "Thank you once again for your cooperation.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }
    ]


def _duration_days_for_toc(requirement: dict) -> int:
    for key in ("duration_days", "duration"):
        value = requirement.get(key)
        if value:
            match = _re.search(r"\d+", str(value))
            if match:
                return max(1, min(int(match.group(0)), 15))
    hours = requirement.get("duration_hours")
    if hours:
        try:
            return max(1, min(int((float(hours) + 7) // 8), 15))
        except Exception:
            pass
    text = " ".join(str(requirement.get(key) or "") for key in ("preferred_dates", "timeline_start", "timeline_end", "description"))
    match = _re.search(r"\b(\d{1,2})\s*(?:day|days)\b", text, flags=_re.IGNORECASE)
    if match:
        return max(1, min(int(match.group(1)), 15))
    return 3


def _fallback_toc_data(payload: dict, reason: str = "") -> dict:
    technology = payload.get("technology") or "Training"
    duration_days = max(1, min(int(payload.get("duration_days") or 3), 15))
    audience_level = payload.get("audience_level") or "intermediate"
    mode = payload.get("mode") or "Online"
    themes = [
        ("Foundations and Environment Setup", [
            "Program introduction and learning outcomes",
            f"{technology} fundamentals and architecture",
            "Environment setup and tool walkthrough",
            "Core concepts with guided examples",
            "Hands-on lab: build the first working exercise",
        ]),
        ("Core Implementation and Practical Workflows", [
            "Key features and implementation patterns",
            "Common business use cases",
            "Configuration and troubleshooting practices",
            "Hands-on lab: implement a real-world workflow",
            "Review, Q&A, and improvement discussion",
        ]),
        ("Advanced Topics and Capstone", [
            "Advanced concepts and optimization",
            "Security, governance, and best practices",
            "Case study and scenario-based exercises",
            "Capstone project implementation",
            "Assessment, feedback, and next-step guidance",
        ]),
    ]

    days = []
    for index in range(duration_days):
        title, topics = themes[min(index, len(themes) - 1)]
        if index >= len(themes):
            title = f"Applied Practice and Capstone Extension {index + 1}"
            topics = [
                f"Recap and advanced {technology} scenario",
                "Design discussion and implementation planning",
                "Hands-on lab: extended business case",
                "Troubleshooting, optimization, and review",
                "Q&A and action plan",
            ]
        days.append({
            "day": index + 1,
            "title": f"Day {index + 1}: {title}",
            "morning_session": {
                "time": "9:30 AM - 1:00 PM",
                "title": f"{title} - Concepts",
                "topics": [
                    {"time": "9:30 - 10:00", "topic": "Recap / Introduction and objectives", "type": "lecture"},
                    {"time": "10:00 - 10:45", "topic": topics[0], "type": "lecture"},
                    {"time": "10:45 - 11:00", "topic": "Break", "type": "break"},
                    {"time": "11:00 - 12:00", "topic": topics[1], "type": "demo"},
                    {"time": "12:00 - 1:00", "topic": topics[2], "type": "lab"},
                ],
            },
            "afternoon_session": {
                "time": "2:00 PM - 5:30 PM",
                "title": f"{title} - Hands-on",
                "topics": [
                    {"time": "2:00 - 2:45", "topic": topics[3], "type": "lab"},
                    {"time": "2:45 - 3:30", "topic": topics[4], "type": "lab"},
                    {"time": "3:30 - 3:45", "topic": "Break", "type": "break"},
                    {"time": "3:45 - 4:45", "topic": "Practice exercise and trainer review", "type": "lab"},
                    {"time": "4:45 - 5:30", "topic": "Q&A, recap, and assignments", "type": "qa"},
                ],
            },
        })

    note = "Generated with deterministic fallback because AI generation was temporarily unavailable."
    if reason:
        note += f" Reason: {reason[:180]}"
    return {
        "title": f"Complete {technology} Training Program",
        "subtitle": f"{duration_days}-Day {audience_level.title()} Training | {mode} Mode",
        "overview": (
            f"This program provides a practical, structured path for learning {technology}. "
            "It combines concepts, demonstrations, hands-on labs, and a final capstone-style review."
        ),
        "prerequisites": [
            "Basic understanding of IT systems and business workflows",
            "Laptop with required software access",
            f"Interest or prior exposure to {technology}",
        ],
        "learning_outcomes": [
            f"Understand core {technology} concepts and terminology",
            "Configure and use key tools in practical scenarios",
            "Apply best practices for real-world implementation",
            "Troubleshoot common issues and validate outcomes",
            "Complete hands-on exercises aligned with business use cases",
        ],
        "days": days,
        "tools_software": [technology, "Browser", "Code editor / relevant platform tools", "Collaboration tools"],
        "certification_guidance": f"Trainer may align examples with relevant {technology} certification objectives where applicable.",
        "trainer_notes": note,
    }


async def _auto_generate_and_send_toc(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    source: str = "automation",
) -> dict:
    trainer_id = trainer.get("trainer_id") or ""
    requirement_id = requirement.get("requirement_id") or ""
    trainer_email = trainer.get("email") or trainer.get("trainer_email") or ""
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"

    if not trainer_id or not requirement_id or not trainer_email:
        return {"success": False, "error": "Trainer email or requirement id missing", "mail_type": "mail6_toc"}

    existing = await db["toc_documents"].find_one(
        {
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
            "status": {"$in": ["sent", "draft"]},
            "source": {"$in": ["client_post_interview_decision", "auto_selection_toc", source]},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if existing and existing.get("status") == "sent":
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "mail_type": "mail6_toc",
            "toc_id": existing.get("toc_id"),
        }

    duration_days = _duration_days_for_toc(requirement)
    mode = requirement.get("mode") or requirement.get("training_mode") or "Online"
    audience_level = requirement.get("audience_level") or requirement.get("level") or "intermediate"
    payload = {
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "trainer_email": trainer_email,
        "technology": technology,
        "duration_days": duration_days,
        "audience_level": audience_level,
        "mode": mode,
        "toc_type": "standard",
        "custom_topics": "",
    }

    try:
        toc_data = existing.get("toc_data") if existing else None
        generation_error = existing.get("generation_error", "") if existing else ""
        if not toc_data:
            try:
                toc_data = await _generate_toc_with_gemini(payload)
            except Exception as exc:
                generation_error = str(exc)
                toc_data = _fallback_toc_data(payload, generation_error)
        toc_id = existing.get("toc_id") if existing else f"TOC-{uuid.uuid4().hex[:8].upper()}"
        doc = {
            "toc_id": toc_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "trainer_email": trainer_email,
            "technology": technology,
            "duration_days": duration_days,
            "audience_level": audience_level,
            "mode": mode,
            "toc_type": "standard",
            "custom_topics": "",
            "toc_data": toc_data,
            "generation_error": generation_error,
            "status": "draft",
            "source": source,
            "created_at": existing.get("created_at") if existing else utc_now(),
            "updated_at": utc_now(),
        }
        await db["toc_documents"].update_one(
            {"toc_id": toc_id},
            {"$set": doc},
            upsert=True,
        )

        subject = f"AI Generated ToC / Course Agenda - {technology}"
        body = (
            f"Dear {trainer_name},\n\n"
            f"Congratulations again on being selected for the {technology} training.\n\n"
            "Please find attached the AI-generated Training Table of Contents / Course Agenda for your review.\n"
            "Kindly check the curriculum and share any required changes or additions before we share it with the client.\n\n"
            "Regards,\nTrainerSync Team"
        )
        pdf_bytes = _toc_pdf_bytes({**doc, "toc_data": toc_data})
        filename = f"{_clean_filename(technology)}_{toc_id}.pdf"
        smtp_config = await get_admin_email_config(db)
        success, error = _send_toc_email_with_attachment(
            trainer_email,
            subject,
            body,
            filename,
            pdf_bytes,
            smtp_config,
        )
        email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
        trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
        trainer_for_teams = await _trainer_for_direct_teams(db, trainer_id, trainer)
        whatsapp_result, teams_direct_result = await asyncio.gather(
            send_shortlist_whatsapp(
                db,
                trainer_phone=trainer_phone,
                trainer_name=trainer_name,
                subject=subject,
                body=body,
                mail_type="mail6_toc",
                requirement_id=requirement_id,
                email_id=email_id,
                request_base_url=_request_base_url(request) if request else "",
            ),
            send_trainer_teams_direct_message(
                db,
                trainer=trainer_for_teams,
                subject=subject,
                body=body,
                requirement_id=requirement_id,
                mail_type="mail6_toc",
                email_id=email_id,
            ),
        )
        sent_at = utc_now()
        await db["toc_documents"].update_one(
            {"toc_id": toc_id},
            {"$set": {
                "status": "sent" if success else "send_failed",
                "sent_at": sent_at if success else None,
                "send_error": error,
                "email_subject": subject,
                "email_body": body,
                "pdf_generated_at": sent_at,
                "whatsapp_summary": whatsapp_result,
                "teams_direct_summary": teams_direct_result,
            }},
        )
        await db["conversations"].insert_one({
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "to_email": trainer_email,
            "requirement_id": requirement_id,
            "subject": subject,
            "body": body,
            "mail_type": "mail6_toc",
            "direction": "sent",
            "status": "sent" if success else "failed",
            "error": error if not success else "",
            "sent_at": sent_at,
            "toc_id": toc_id,
            "toc_title": toc_data.get("title", ""),
            "source": source,
        })
        await db["email_logs"].insert_one({
            "email_id": email_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "to_email": trainer_email,
            "subject": subject,
            "body": body,
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": sent_at if success else None,
            "reply_received": False,
            "opened": False,
            "open_count": 0,
            "tracking_url": build_tracking_url(request, email_id) if request else "",
            "retry_count": 0,
            "mail_type": "mail6_toc",
            "toc_id": toc_id,
            "toc_title": toc_data.get("title", ""),
            "trainer_phone": trainer_phone,
            "whatsapp_summary": whatsapp_result,
            "teams_direct_summary": teams_direct_result,
            "source": source,
            "created_at": sent_at,
        })
        if success:
            await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": "toc_requested"}})
        return {
            "success": success,
            "error": error,
            "mail_type": "mail6_toc",
            "email_id": email_id,
            "toc_id": toc_id,
            "whatsapp": whatsapp_result,
            "teams_direct": teams_direct_result,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "mail_type": "mail6_toc"}


def _training_date_for_confirmation(requirement: dict) -> str:
    for key in ("training_dates", "preferred_dates", "timeline_start", "start_date"):
        value = str(requirement.get(key) or "").strip()
        if value:
            end = str(requirement.get("timeline_end") or "").strip()
            if key == "timeline_start" and end and end != value:
                return f"{value} to {end}"
            return value
    return "As per the client-approved schedule coordinated by Calhan Technologies"


def _venue_for_confirmation(requirement: dict) -> str:
    mode = str(requirement.get("mode") or requirement.get("training_mode") or "Online").strip()
    location = str(requirement.get("location") or requirement.get("preferred_location") or "").strip()
    if location and mode and mode.lower() not in location.lower():
        return f"{mode} - {location}"
    return location or mode or "Online / Client-approved platform"


async def _send_auto_training_confirmation(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    source: str = "automation",
) -> dict:
    smtp_config = await get_admin_email_config(db)
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "clientInboxCfg": 1, "twilioCfg": 1},
    ) or {}
    client_inbox_cfg = settings_doc.get("clientInboxCfg") or {}
    twilio_cfg = settings_doc.get("twilioCfg") or {}
    contact_email = (
        smtp_config.get("fromEmail")
        or smtp_config.get("smtpUser")
        or getattr(get_settings(), "from_email", "")
        or getattr(get_settings(), "gmail_user", "")
        or "recruitment@calhantech.com"
    )
    contact_phone = (
        client_inbox_cfg.get("vendorWhatsAppNumber")
        or twilio_cfg.get("vendorWhatsAppNumber")
        or "Calhan Technologies coordination team"
    )
    if str(contact_phone).startswith("whatsapp:"):
        contact_phone = str(contact_phone).replace("whatsapp:", "", 1)

    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"
    training_date = _training_date_for_confirmation(requirement)
    venue = _venue_for_confirmation(requirement)
    subject = f"Training Schedule Confirmed - {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        f"We are pleased to confirm your engagement for the {technology} training. Please find the final details below:\n\n"
        f"Training Date: {training_date}\n"
        f"Venue / Platform: {venue}\n\n"
        "Action Items Before Training:\n"
        "* Ensure all materials and slides are ready\n"
        "* Review the generated ToC / Course Agenda shared by Calhan Technologies\n"
        "* Share soft copies of training content with us 2 days prior\n"
        "* Confirm your availability 24 hours before the training\n\n"
        "For any questions or additional information, please contact:\n\n"
        "Contact Name: Calhan Technologies Team\n"
        f"Phone: {contact_phone}\n"
        f"Email: {contact_email}\n\n"
        "We look forward to a successful training session.\n\n"
        "Regards,\nTrainerSync Team"
    )
    return await _send_trainer_pipeline_email(
        db,
        request,
        trainer=trainer,
        requirement=requirement,
        subject=subject,
        body=body,
        mail_type="mail7_confirm",
        source=source,
    )


async def _send_trainer_pipeline_email(
    db,
    request: Optional[Request],
    *,
    trainer: dict,
    requirement: dict,
    subject: str,
    body: str,
    mail_type: str,
    source: str = "automation",
) -> dict:
    trainer_id = trainer.get("trainer_id") or ""
    requirement_id = requirement.get("requirement_id") or ""
    to_email = trainer.get("email") or trainer.get("trainer_email") or ""
    trainer_name = trainer.get("name") or trainer.get("trainer_name") or "Trainer"
    if not trainer_id or not requirement_id or not to_email:
        return {"success": False, "error": "Trainer email or requirement id missing", "mail_type": mail_type}

    allowed, blocked_response, latest_requirement = await _requirement_trainer_send_guard(
        db,
        requirement_id,
        trainer_id,
    )
    if not allowed:
        blocked_response["mail_type"] = mail_type
        return blocked_response
    requirement = latest_requirement or requirement

    existing = await db["email_logs"].find_one(
        {
            "trainer_id": trainer_id,
            "requirement_id": requirement_id,
            "mail_type": mail_type,
            "status": "sent",
        },
        {"_id": 0, "email_id": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if existing:
        return {
            "success": True,
            "skipped": True,
            "status": "already_sent",
            "mail_type": mail_type,
            "email_id": existing.get("email_id"),
        }

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
    trainer_for_teams = await _trainer_for_direct_teams(db, trainer_id, trainer)
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
            request_base_url=_request_base_url(request) if request else "",
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result
    now = utc_now()
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": requirement_id,
        "subject": subject,
        "body": body,
        "mail_type": mail_type,
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": now,
        "email_id": email_id,
        "source": source,
    })
    await db["email_logs"].insert_one({
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
        "mail_type": mail_type,
        "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "teams_direct_summary": teams_direct_result,
        "source": source,
        "created_at": now,
    })

    if success:
        status_by_type = {
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        trainer_status = status_by_type.get(mail_type)
        if trainer_status:
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {"status": trainer_status}},
            )
        if mail_type == "mail5_ok":
            await _mark_requirement_selected_and_stop_others(
                db,
                requirement_id=requirement_id,
                trainer_id=trainer_id,
                trainer_name=trainer_name,
                selected_at=now,
            )
            await send_teams_stage_notification(
                db,
                stage="trainer_selected",
                trainer_name=trainer_name,
                requirement=requirement,
                request_base_url=_request_base_url(request) if request else "",
                context={"source": source, "email_id": email_id, "trainer_id": trainer_id},
            )
    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "mail_type": mail_type,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
    }


async def _match_client_decision_candidate(db, meta: dict, clean_body: str) -> tuple[Optional[dict], Optional[dict], dict]:
    from_email = (meta.get("from_email") or "").strip()
    text = _re.sub(r"\s+", " ", f"{meta.get('subject') or ''} {clean_body or meta.get('snippet') or ''}".lower())
    domain = sender_domain(from_email)

    requirement_query = {"$or": []}
    if from_email:
        requirement_query["$or"].append({"client_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}})
    if domain:
        requirement_query["$or"].append({"client_email_domain": domain})
    requirements = []
    if requirement_query["$or"]:
        requirements = await db["requirements"].find(requirement_query, {"_id": 0}).sort("created_at", -1).limit(25).to_list(25)

    requirement_by_id = {req.get("requirement_id"): req for req in requirements if req.get("requirement_id")}
    requirement_ids = list(requirement_by_id.keys())
    if not requirement_ids and from_email:
        slot_docs = await db["client_slot_emails"].find(
            {"to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"}},
            {"_id": 0, "requirement_id": 1},
        ).sort("sent_at", -1).limit(25).to_list(25)
        requirement_ids = sorted({item.get("requirement_id") for item in slot_docs if item.get("requirement_id")})
        if requirement_ids:
            requirements = await db["requirements"].find(
                {"requirement_id": {"$in": requirement_ids}},
                {"_id": 0},
            ).to_list(25)
            requirement_by_id = {req.get("requirement_id"): req for req in requirements if req.get("requirement_id")}

    if not requirement_ids:
        return None, None, {"reason": "no requirement matched client email"}

    logs = await db["email_logs"].find(
        {
            "requirement_id": {"$in": requirement_ids},
            "mail_type": "mail4",
            "status": "sent",
            "interview_scheduled": True,
        },
        {"_id": 0},
    ).sort("sent_at", -1).limit(50).to_list(50)
    if not logs:
        return None, None, {"reason": "no scheduled interview mail found", "requirement_ids": requirement_ids}

    trainer_ids = [log.get("trainer_id") for log in logs if log.get("trainer_id")]
    trainers = await db["trainers"].find(
        {"trainer_id": {"$in": trainer_ids}},
        {"_id": 0},
    ).to_list(len(trainer_ids) or 1)
    trainer_by_id = {trainer.get("trainer_id"): trainer for trainer in trainers}

    scored = []
    for log in logs:
        requirement = requirement_by_id.get(log.get("requirement_id")) or {}
        trainer = trainer_by_id.get(log.get("trainer_id")) or {
            "trainer_id": log.get("trainer_id"),
            "name": log.get("trainer_name"),
            "email": log.get("to_email"),
            "phone": log.get("trainer_phone", ""),
        }
        trainer_name = str(trainer.get("name") or log.get("trainer_name") or "").strip().lower()
        trainer_parts = [part for part in _re.split(r"\s+", trainer_name) if len(part) > 2]
        requirement_id = str(log.get("requirement_id") or "").lower()
        technology = str(requirement.get("technology_needed") or log.get("technology") or "").lower()
        score = 0
        if trainer_name and trainer_name in text:
            score += 260
        elif trainer_parts and any(part in text for part in trainer_parts):
            score += 90
        if requirement_id and requirement_id in text:
            score += 120
        if technology and technology in text:
            score += 45
        if _re.search(r"\b(trainer|candidate|profile|interview|discussion)\b", text):
            score += 30
        sent_at = log.get("sent_at")
        if _recent_enough(sent_at, meta.get("received_at") or utc_now(), days=30):
            score += 35
        scored.append((score, log, trainer, requirement))

    if not scored:
        return None, None, {"reason": "no scored candidates"}
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_log, best_trainer, best_requirement = scored[0]
    viable_pairs = {
        (item[1].get("trainer_id"), item[1].get("requirement_id"))
        for item in scored
        if item[0] >= 50 and item[1].get("trainer_id") and item[1].get("requirement_id")
    }
    if len(viable_pairs) == 1 and best_score >= 50:
        if not best_trainer.get("email"):
            best_trainer["email"] = best_log.get("to_email")
        if not best_trainer.get("phone"):
            best_trainer["phone"] = best_log.get("trainer_phone", "")
        return best_trainer, best_requirement, {
            "score": best_score,
            "matched_email_id": best_log.get("email_id"),
            "single_candidate_group": True,
        }
    if best_score < 100 and len(logs) != 1:
        return None, None, {"reason": "ambiguous trainer decision", "score": best_score}
    if best_score < 70 and len(logs) == 1:
        return None, None, {"reason": "low confidence trainer decision", "score": best_score}
    if not best_trainer.get("email"):
        best_trainer["email"] = best_log.get("to_email")
    if not best_trainer.get("phone"):
        best_trainer["phone"] = best_log.get("trainer_phone", "")
    return best_trainer, best_requirement, {"score": best_score, "matched_email_id": best_log.get("email_id")}


async def _process_client_interview_decision(db, meta: dict, request: Optional[Request] = None) -> Optional[dict]:
    message_id = meta.get("email_id") or meta.get("gmail_message_id")
    if not message_id:
        return None
    existing = await db["post_interview_decisions"].find_one({"gmail_message_id": message_id}, {"_id": 0})
    if existing and existing.get("status") not in {"needs_manual_review", "trainer_decision_email_failed"}:
        return {"status": "already_processed_client_decision", **existing}

    clean_body = _strip_quoted_reply_text(meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or "")
    decision = _detect_client_interview_decision(meta.get("subject", ""), clean_body)
    if not decision.get("decision"):
        return None

    trainer, requirement, match = await _match_client_decision_candidate(db, meta, clean_body)
    now = utc_now()
    decision_id = existing.get("decision_id") if existing else f"DECISION-{uuid.uuid4().hex[:8].upper()}"
    if not trainer or not requirement:
        doc = {
            "decision_id": decision_id,
            "gmail_message_id": message_id,
            "status": "needs_manual_review",
            "decision": decision,
            "match": match,
            "client_email": meta.get("from_email"),
            "subject": meta.get("subject"),
            "reply_text": clean_body,
            "updated_at": now,
        }
        await db["post_interview_decisions"].update_one(
            {"gmail_message_id": message_id},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {k: v for k, v in doc.items() if k != "_id"}

    client_note = _client_note_excerpt(clean_body)
    sent_results = []
    for template in _decision_mail_templates(trainer, requirement, decision["decision"], client_note):
        sent = await _send_trainer_pipeline_email(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            subject=template["subject"],
            body=template["body"],
            mail_type=template["mail_type"],
            source="client_post_interview_decision",
        )
        sent_results.append(sent)
        if decision["decision"] != "selected":
            break
    if decision["decision"] == "selected" and sent_results and sent_results[0].get("success"):
        toc_result = await _auto_generate_and_send_toc(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            source="client_post_interview_decision",
        )
        sent_results.append(toc_result)
        if toc_result.get("success"):
            confirmation_result = await _send_auto_training_confirmation(
                db,
                request,
                trainer=trainer,
                requirement=requirement,
                source="client_post_interview_decision",
            )
            sent_results.append(confirmation_result)

    final_status = "trainer_selected_auto_sent" if decision["decision"] == "selected" else "trainer_rejected_auto_sent"
    if not all(item.get("success") for item in sent_results):
        final_status = "trainer_decision_email_failed"
    doc = {
        "decision_id": decision_id,
        "gmail_message_id": message_id,
        "status": final_status,
        "decision": decision,
        "match": match,
        "requirement_id": requirement.get("requirement_id"),
        "trainer_id": trainer.get("trainer_id"),
        "trainer_name": trainer.get("name") or trainer.get("trainer_name"),
        "trainer_email": trainer.get("email") or trainer.get("trainer_email"),
        "client_email": meta.get("from_email"),
        "client_name": meta.get("from_name"),
        "subject": meta.get("subject"),
        "reply_text": clean_body,
        "sent_results": sent_results,
        "updated_at": now,
    }
    await db["post_interview_decisions"].update_one(
        {"gmail_message_id": message_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {k: v for k, v in doc.items() if k != "_id"}


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
    model = (os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash").strip()

    try:
        import httpx as _httpx
        full_prompt = (system_prompt + "\n\n") if system_prompt else ""
        for m in messages:
            role = "User" if m["role"] == "user" else "Assistant"
            full_prompt += f"{role}: {m['content']}\n"
        full_prompt += "Assistant:"
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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
                "model": model,
                "feature": payload.get("feature") or "assistant_chat",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_inr": _money(cost_inr),
                "metadata": payload.get("metadata") or {},
                "created_at": utc_now(),
            })
        except Exception as log_exc:
            logger.warning("AI usage log failed: %s", log_exc)
        return {"reply": reply or "I could not generate a response.", "provider": "gemini", "model": model}
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


def _thread_datetime(value):
    if not value:
        return datetime.min
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except Exception:
            return datetime.min
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _message_sort_key(message: dict) -> tuple:
    return (
        _thread_datetime(message.get("sort_at") or message.get("sent_at")),
        int(message.get("sort_order") or 50),
        str(message.get("message_id") or ""),
    )


def _client_conversation_key(doc: dict, requirement: dict = None) -> str:
    requirement = requirement or {}
    requirement_id = doc.get("requirement_id") or requirement.get("requirement_id") or ""
    if requirement_id:
        return f"req:{requirement_id}"
    thread_id = doc.get("thread_id") or ""
    if thread_id:
        return f"thread:{thread_id}"
    extracted = doc.get("extracted") or {}
    technology = extracted.get("technology_needed") or requirement.get("technology_needed") or "general"
    email = (doc.get("from_email") or doc.get("to_email") or extracted.get("client_email") or "client").lower()
    return f"client:{email}|domain:{str(technology).strip().lower() or 'general'}"


def _client_conversation_meta(doc: dict, requirement: dict = None) -> dict:
    requirement = requirement or {}
    extracted = doc.get("extracted") or {}
    client_email = doc.get("from_email") or doc.get("to_email") or requirement.get("client_email") or extracted.get("client_email") or ""
    client_name = (
        doc.get("from_name")
        or doc.get("client_name")
        or requirement.get("client_name")
        or extracted.get("client_name")
        or requirement.get("client_company")
        or extracted.get("client_company")
        or client_email
        or "Client"
    )
    company = requirement.get("client_company") or extracted.get("client_company") or sender_domain(client_email)
    technology = requirement.get("technology_needed") or extracted.get("technology_needed") or doc.get("technology") or "Training"
    return {
        "client_name": client_name,
        "client_email": client_email,
        "client_company": company,
        "domain": technology,
        "requirement_id": doc.get("requirement_id") or requirement.get("requirement_id") or "",
        "thread_id": doc.get("thread_id") or "",
        "status": doc.get("status") or requirement.get("status") or "",
    }


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
            received_at = utc_from_timestamp(int(msg["internalDate"]) / 1000)
        except Exception:
            received_at = None
    return {
        "email_id": message_id,
        "thread_id": msg.get("threadId"),
        "received_at": received_at or utc_now(),
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


async def _save_post_interview_decision_email(db, meta: dict, decision_result: dict) -> None:
    now = utc_now()
    decision = decision_result.get("decision") or {}
    await db["client_emails"].update_one(
        {"email_id": meta.get("email_id")},
        {
            "$set": {
                "requirement_id": decision_result.get("requirement_id"),
                "status": decision_result.get("status") or "post_interview_decision",
                "confidence": decision.get("confidence", 0),
                "auto_send_eligible": False,
                "sent_at": now if "auto_sent" in str(decision_result.get("status") or "") else None,
                "sent_by": "auto" if "auto_sent" in str(decision_result.get("status") or "") else None,
                "post_interview_decision": decision_result,
                "extracted.is_training_request": False,
                "extracted.post_interview_decision": True,
                "extracted.decision": decision,
                "updated_at": now,
            },
            "$setOnInsert": {
                "email_id": meta.get("email_id"),
                "thread_id": meta.get("thread_id"),
                "received_at": meta.get("received_at"),
                "from_email": meta.get("from_email"),
                "from_name": meta.get("from_name"),
                "subject": meta.get("subject"),
                "raw_body": meta.get("raw_body"),
                "clean_body": meta.get("clean_body"),
                "generated_reply": {},
                "whatsapp_notified": False,
                "message_id_header": meta.get("message_id_header", ""),
                "created_at": now,
            },
        },
        upsert=True,
    )


async def _process_and_store_client_decision_message(
    db,
    message_id: str,
    gmail_service,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
) -> Optional[dict]:
    full_meta = fetch_gmail_email(message_id, gmail_service)
    if meta_hint:
        full_meta = {**meta_hint, **full_meta}
    decision_result = await _process_client_interview_decision(db, full_meta, request)
    if not decision_result:
        return None
    await _save_post_interview_decision_email(db, full_meta, decision_result)
    return decision_result


async def _process_and_store_client_message(db, message_id: str, gmail_service, request: Optional[Request] = None) -> dict:
    settings = await _client_inbox_settings(db)
    processed = await process_client_email(message_id, gmail_service)
    existing = await db["client_emails"].find_one({"email_id": processed.get("email_id")}, {"_id": 1, "status": 1})
    if existing:
        return {"status": "already_processed", "email_id": processed.get("email_id")}

    decision_result = await _process_client_interview_decision(db, processed, request)
    if decision_result:
        await _save_post_interview_decision_email(db, processed, decision_result)
        return decision_result

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
        "created_at": utc_now(),
    }

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
        inbox_doc["sent_at"] = utc_now()
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
            "sent_at": utc_now(),
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

    event_body = {
        "summary": f"{technology} Discussion - {requirement_id}".strip(),
        "description": (
            f"Calhan Technologies discussion/interview.\n\n"
            f"Requirement ID: {requirement_id}\n"
            f"Technology: {technology}\n"
            "Participants will be notified separately by Calhan Technologies.\n\n"
            f"Confirmed slot reply:\n{slot_reply[:2000]}"
        ),
        "start": {"dateTime": start_text, "timeZone": timezone_name},
        "end": {"dateTime": end_text, "timeZone": timezone_name},
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
            sendUpdates="none",
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
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    success, error = email_result
    now = utc_now()

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
        "teams_direct_summary": teams_direct_result,
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
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": date_time,
            },
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
        "teams": teams_result,
        "reminder_schedule": reminder_schedule,
    }


async def _send_client_interview_schedule(
    db,
    request: Optional[Request],
    *,
    client_email: str,
    client_name: str,
    requirement_id: str,
    date_time: str,
    interview_link: str,
    platform: str = "Google Meet",
    source: str = "client_slot_confirmation",
    calendar_event: Optional[dict] = None,
    client_slot_email_id: str = "",
) -> dict:
    if not client_email:
        return {"success": False, "error": "Client email not found"}

    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    technology = req.get("technology_needed", "Training") if req else "Training"
    client_phone = str((req or {}).get("client_phone") or (req or {}).get("client_whatsapp") or "").strip()
    subject = f"Discussion Schedule Confirmation - {technology}"
    body = (
        f"Hi {client_name or 'Client'},\n\n"
        f"The {technology} discussion/interview has been scheduled. Please find the final details below:\n\n"
        f"Date & Time : {date_time or '[Date & Time]'}\n"
        f"Platform    : {platform}\n"
        f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
        "Calhan Technologies will coordinate the discussion. Please join on time and let us know if you need any assistance.\n\n"
        "Regards,\nRecruitment Team,\nCalhan Technologies"
    )

    email_id = f"CLIENT-SCHEDULE-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id) if request else ""
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    whatsapp_result = {"status": "skipped", "error": "Client phone not found"}
    if success and client_phone:
        whatsapp_result = await send_whatsapp_message(
            db,
            client_phone,
            body,
            event_type="client_interview_schedule",
            recipient_type="client",
            request_base_url=_request_base_url(request) if request else "",
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_interview_schedule",
                "recipient_name": client_name,
                "client_name": client_name,
                "client_email": client_email,
                "requirement_id": requirement_id,
                "subject": subject,
                "date_time": date_time,
                "platform": platform,
                "interview_link": interview_link,
            },
        )
    now = utc_now()

    log_doc = {
        "email_id": email_id,
        "trainer_id": "",
        "trainer_name": "",
        "requirement_id": requirement_id,
        "to_email": client_email,
        "client_phone": client_phone,
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
        "mail_type": "client_interview_schedule",
        "interview_scheduled": success,
        "interview_date": date_time,
        "interview_link": interview_link,
        "platform": platform,
        "technology": technology,
        "calendar_event": calendar_event or {},
        "client_slot_email_id": client_slot_email_id,
        "whatsapp_summary": whatsapp_result,
        "source": source,
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)

    await db["client_messages"].insert_one({
        **log_doc,
        "direction": "sent",
        "client_email": client_email,
        "client_name": client_name,
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        teams_result = await send_teams_stage_notification(
            db,
            stage="client_message_sent",
            trainer_name=client_name,
            requirement=req or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=_request_base_url(request) if request else "",
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_interview_schedule",
                "recipient_type": "client",
                "client_email": client_email,
                "client_phone": client_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "interview_date": date_time,
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )
        await db["client_messages"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams": teams_result}


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

    received_at = meta.get("received_at") or utc_now()
    candidates = await db["client_slot_emails"].find(
        {
            "to_email": {"$regex": f"^{_re.escape(from_email)}$", "$options": "i"},
            "status": {"$in": ["sent", "confirmed_scheduled", "calendar_failed", "trainer_email_failed", "client_email_failed"]},
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


async def _process_client_slot_reply_from_meta(
    db,
    message_id: str,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
    slot_doc: Optional[dict] = None,
) -> Optional[dict]:
    existing = await db["client_slot_confirmations"].find_one({"gmail_message_id": message_id}, {"_id": 0})
    if existing and existing.get("status") not in {"calendar_failed", "trainer_email_failed", "needs_manual_review"}:
        return {
            "status": "already_processed_client_slot_reply",
            "email_id": message_id,
            "requirement_id": existing.get("requirement_id"),
            "trainer_id": existing.get("trainer_id"),
        }

    meta = meta_hint or {}
    clean_body = _strip_quoted_reply_text(meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or "")
    slot_doc = slot_doc or await _matching_client_slot_email(db, meta, clean_body)
    if not slot_doc:
        return None
    if slot_doc.get("status") == "confirmed_scheduled":
        return {
            "status": "already_processed_client_slot_reply",
            "email_id": message_id,
            "requirement_id": slot_doc.get("requirement_id"),
            "trainer_id": slot_doc.get("trainer_id"),
        }

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

    now = utc_now()
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
    date_time = parsed.get("date_time_text") or parsed.get("start_iso") or calendar_event.get("start")
    client_email = meta.get("from_email") or slot_doc.get("to_email") or ""
    send_result, client_send_result = await asyncio.gather(
        _send_trainer_interview_schedule(
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
        ),
        _send_client_interview_schedule(
            db,
            request,
            client_email=client_email,
            client_name=client_name,
            requirement_id=requirement_id,
            date_time=date_time,
            interview_link=meet_link,
            platform="Google Meet",
            source="client_slot_confirmation",
            calendar_event=calendar_event,
            client_slot_email_id=slot_doc.get("email_id", ""),
        ),
    )
    if send_result.get("success") and client_send_result.get("success"):
        final_status = "confirmed_scheduled"
    elif not send_result.get("success"):
        final_status = "trainer_email_failed"
    else:
        final_status = "client_email_failed"
    await db["client_slot_confirmations"].update_one(
        {"confirmation_id": confirmation_id},
        {"$set": {
            **base_doc,
            "status": final_status,
            "calendar_event": calendar_event,
            "trainer_schedule_email": send_result,
            "client_schedule_email": client_send_result,
            "scheduled_at": now,
            "error": send_result.get("error") or client_send_result.get("error") or "",
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
            "client_schedule_email": client_send_result,
        }},
    )
    return {
        "status": final_status,
        "email_id": message_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_email_sent": bool(send_result.get("success")),
        "client_email_sent": bool(client_send_result.get("success")),
        "meet_link": meet_link,
        "calendar_event_id": calendar_event.get("event_id"),
    }


async def _process_client_slot_reply(
    db,
    message_id: str,
    gmail_service,
    request: Optional[Request] = None,
    meta_hint: Optional[dict] = None,
    slot_doc: Optional[dict] = None,
) -> Optional[dict]:
    meta = fetch_gmail_email(message_id, gmail_service)
    if meta_hint:
        meta = {**meta_hint, **meta}
    return await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )


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
            has_decision = bool(
                existing.get("post_interview_decision")
                or (existing.get("extracted") or {}).get("post_interview_decision")
            )
            if (
                has_decision
                or existing.get("status") in {"spam", "needs_manual_review", "trainer_decision_email_failed"}
            ):
                decision_retry = await _process_and_store_client_decision_message(db, message_id, service, request)
                if decision_retry:
                    processed.append(decision_retry)
                    continue
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
            decision_result = await _process_and_store_client_decision_message(
                db,
                message_id,
                service,
                request,
                meta_hint=meta,
            )
            if decision_result:
                processed.append(decision_result)
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
            "last_manual_sync_at": utc_now(),
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


async def _generate_toc_with_gemini(payload: dict) -> dict:
    import httpx as _httpx
    settings = get_settings()
    api_key = os.getenv("GEMINI_API_KEY", "") or getattr(settings, "gemini_api_key", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")
    model = os.getenv("GEMINI_MODEL", "") or getattr(settings, "gemini_model", "") or "gemini-2.0-flash"
    full_prompt = TOC_SYSTEM_PROMPT + "\n\n" + _toc_user_prompt(payload)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with _httpx.AsyncClient(timeout=120) as client:
        res = await client.post(url, json={
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8000},
        })
        res.raise_for_status()
        data = res.json()
    raw = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Gemini did not return valid JSON for TOC. Response: {raw[:300]}")
    return _json.loads(raw[start:end + 1])


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
                    "categorisation_failed_at": utc_now(),
                }},
            )


async def _run_categorisation_job(job_id: str):
    db = get_db()
    CATEGORISATION_JOBS[job_id].update({
        "status": "running",
        "started_at": utc_now(),
    })
    try:
        result = await bulk_categorise_all(db)
        CATEGORISATION_JOBS[job_id].update({
            **result,
            "status": "completed",
            "completed_at": utc_now(),
        })
    except Exception as exc:
        CATEGORISATION_JOBS[job_id].update({
            "status": "failed",
            "error": str(exc),
            "completed_at": utc_now(),
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
    existing = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1, "teamsDirectCfg": 1},
    ) or {}
    incoming_email = payload.get("emailCfg")
    if isinstance(incoming_email, dict):
        existing_email = existing.get("emailCfg") or {}
        if not incoming_email.get("smtpPass") and existing_email.get("smtpPass"):
            incoming_email["smtpPass"] = existing_email.get("smtpPass")

    incoming_teams_direct = payload.get("teamsDirectCfg")
    if isinstance(incoming_teams_direct, dict):
        existing_teams_direct = existing.get("teamsDirectCfg") or {}
        for token_key in ("accessToken", "refreshToken", "expiresAt"):
            if not incoming_teams_direct.get(token_key) and existing_teams_direct.get(token_key):
                incoming_teams_direct[token_key] = existing_teams_direct.get(token_key)

    payload = {
        **payload,
        "settings_id": "default",
        "updated_at": utc_now(),
    }
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": payload},
        upsert=True,
    )
    return {"message": "Admin settings saved"}


@router.post("/admin/email/test")
async def test_email_settings(payload: dict = {}):
    db = get_db()
    cfg = await get_admin_email_config(db)
    to_email = str(
        payload.get("to_email")
        or cfg.get("fromEmail")
        or cfg.get("smtpUser")
        or getattr(get_settings(), "from_email", "")
        or getattr(get_settings(), "gmail_user", "")
    ).strip()
    if not to_email:
        raise HTTPException(400, "Enter SMTP username or From Email before testing email")

    subject = "TrainerSync SMTP Test"
    body = (
        "Hello,\n\n"
        "This is a TrainerSync SMTP test email. Your email sending configuration is connected.\n\n"
        "Regards,\nTrainerSync Team"
    )
    success, error = await send_email_async(to_email, subject, body, cfg)
    if not success:
        raise HTTPException(400, error or "Email test failed")
    return {"message": "Test email sent", "to_email": to_email}


@router.post("/admin/whatsapp/test")
async def test_whatsapp_settings(request: Request):
    db = get_db()
    cfg = await get_twilio_config(db)
    provider_name = (
        "AiSensy" if cfg.get("provider") == "aisensy"
        else "Meta Cloud API" if cfg.get("provider") == "meta"
        else "Twilio"
    )
    campaign_note = ""
    if cfg.get("provider") == "aisensy":
        campaign_note = f"\nCampaign: {cfg.get('aisensyCampaignName') or '-'}\nTemplate Params: {cfg.get('aisensyTemplateParamFields') or 'message'}"
    elif cfg.get("provider") == "meta":
        campaign_note = f"\nTemplate: {cfg.get('metaTemplateName') or 'text message'}\nLanguage: {cfg.get('metaLanguageCode') or 'en_US'}"
    result = await send_whatsapp_message(
        db,
        cfg.get("vendorWhatsAppNumber", ""),
        (
            "Dear Admin,\n\n"
            f"TrainerSync WhatsApp test message. Your {provider_name} configuration is connected."
            f"{campaign_note}\n\n"
            "Regards,\nTrainerSync Team"
        ),
        event_type="admin_test",
        recipient_type="vendor",
        request_base_url=_request_base_url(request),
        context={"source": "admin_settings", "provider": cfg.get("provider")},
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "WhatsApp test failed")
    return {"message": "WhatsApp test sent", **result}


@router.get("/teams-direct/oauth-url")
async def teams_direct_oauth_url():
    db = get_db()
    cfg = await get_teams_direct_config(db)
    missing = [name for name in ("clientId", "redirectUri") if not cfg.get(name)]
    if missing:
        raise HTTPException(400, f"Missing Microsoft Graph settings: {', '.join(missing)}")
    return {
        "auth_url": microsoft_oauth_url(cfg),
        "redirect_uri": cfg.get("redirectUri"),
    }


@router.get("/teams-direct/status")
async def teams_direct_status():
    db = get_db()
    cfg = await get_teams_direct_config(db)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    token_valid = bool(cfg.get("accessToken")) and int(cfg.get("expiresAt") or 0) > now_ts + 60
    has_refresh_token = bool(cfg.get("refreshToken"))
    return {
        "enabled": bool(cfg.get("enabled")),
        "connected": bool(cfg.get("enabled")) and (token_valid or has_refresh_token),
        "token_valid": token_valid,
        "has_refresh_token": has_refresh_token,
        "sender_user": cfg.get("senderUser", ""),
        "redirect_uri": cfg.get("redirectUri", ""),
    }


@router.get("/teams-direct/oauth-callback")
async def teams_direct_oauth_callback(code: str = "", error: str = "", error_description: str = ""):
    db = get_db()
    if error:
        message = error_description or error
        return Response(
            content=f"<h2>Teams authorization failed</h2><p>{_html.escape(message)}</p>",
            media_type="text/html",
            status_code=400,
        )
    if not code:
        return Response(
            content="<h2>Teams authorization failed</h2><p>Missing authorization code.</p>",
            media_type="text/html",
            status_code=400,
        )
    result = await exchange_microsoft_code(db, code)
    if not result.get("success"):
        return Response(
            content=f"<h2>Teams authorization failed</h2><p>{_html.escape(result.get('error', 'Unknown error'))}</p>",
            media_type="text/html",
            status_code=400,
        )
    return Response(
        content=(
            "<h2>Teams direct chat connected</h2>"
            "<p>You can close this tab and return to TrainerSync.</p>"
        ),
        media_type="text/html",
    )


@router.post("/admin/teams-direct/test")
async def test_teams_direct_settings(payload: dict):
    db = get_db()
    teams_email = str(payload.get("teams_email") or "").strip()
    if not teams_email:
        raise HTTPException(400, "Enter a trainer Teams email for the direct chat test")
    result = await send_trainer_teams_direct_message(
        db,
        trainer={
            "trainer_id": "TEAMS-DIRECT-TEST",
            "name": payload.get("trainer_name") or "Teams Direct Test",
            "teams_email": teams_email,
        },
        subject="TrainerSync Teams Direct Chat Test",
        body=(
            "Dear Trainer,\n\n"
            "This is a TrainerSync direct Microsoft Teams test message.\n\n"
            "Regards,\nTrainerSync Team"
        ),
        requirement_id="ADMIN-TEST",
        mail_type="admin_test",
        email_id=f"EMAIL-{uuid.uuid4().hex[:8].upper()}",
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "Teams direct chat test failed")
    return {"message": "Teams direct chat test sent", **result}


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
        "sent_at": utc_now(),
    })
    return {"message": "Reset email sent"}


@router.get("/email-open/{email_id}", name="track_email_open")
async def track_email_open(email_id: str, request: Request):
    db = get_db()
    now = utc_now()
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
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
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
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })
    reply_text = "Thanks for your response. TrainerSync has received your WhatsApp message and will update the trainer pipeline shortly."
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{_html.escape(reply_text)}</Message></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


async def _meta_whatsapp_verify_token(db) -> str:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "twilioCfg.metaVerifyToken": 1},
    )
    cfg = (settings_doc or {}).get("twilioCfg") or {}
    return (
        str(cfg.get("metaVerifyToken") or "").strip()
        or os.getenv("META_WHATSAPP_VERIFY_TOKEN", "").strip()
        or "trainersync_whatsapp_verify_2026"
    )


def _meta_message_text(message: dict) -> str:
    msg_type = str(message.get("type") or "").strip().lower()
    if msg_type == "text":
        return str((message.get("text") or {}).get("body") or "").strip()
    if msg_type == "button":
        return str((message.get("button") or {}).get("text") or "").strip()
    if msg_type == "interactive":
        interactive = message.get("interactive") or {}
        button_reply = interactive.get("button_reply") or {}
        list_reply = interactive.get("list_reply") or {}
        return str(button_reply.get("title") or list_reply.get("title") or "").strip()
    return str(message.get(msg_type) or "").strip()


@router.get("/whatsapp/meta/webhook")
async def whatsapp_meta_webhook_verify(request: Request):
    db = get_db()
    params = request.query_params
    mode = params.get("hub.mode") or params.get("hub_mode")
    token = params.get("hub.verify_token") or params.get("hub_verify_token")
    challenge = params.get("hub.challenge") or params.get("hub_challenge")
    expected_token = await _meta_whatsapp_verify_token(db)

    if mode == "subscribe" and token == expected_token and challenge:
        return Response(content=str(challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@router.post("/whatsapp/meta/webhook")
async def whatsapp_meta_webhook(request: Request):
    db = get_db()
    payload = await request.json()
    processed = {"statuses": 0, "messages": 0}

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            display_phone = metadata.get("display_phone_number") or ""
            phone_number_id = metadata.get("phone_number_id") or ""

            for status_item in value.get("statuses", []) or []:
                errors = status_item.get("errors") or []
                status_payload = {
                    **status_item,
                    "messageId": status_item.get("id") or "",
                    "status": status_item.get("status") or "",
                    "recipient": status_item.get("recipient_id") or "",
                    "phone_number_id": phone_number_id,
                    "display_phone_number": display_phone,
                }
                if errors:
                    status_payload["error_message"] = (
                        errors[0].get("message")
                        or errors[0].get("title")
                        or errors[0].get("details")
                        or ""
                    )
                    status_payload["error_code"] = errors[0].get("code") or ""
                await update_whatsapp_status(db, status_payload)
                processed["statuses"] += 1

            contacts_by_wa_id = {
                str(contact.get("wa_id") or ""): contact
                for contact in value.get("contacts", []) or []
            }
            for message in value.get("messages", []) or []:
                from_number = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not message_id:
                    continue
                existing = await db["whatsapp_logs"].find_one(
                    {"meta_message_id": message_id, "direction": "inbound"},
                    {"_id": 1},
                )
                if existing:
                    continue
                contact = contacts_by_wa_id.get(from_number) or {}
                await db["whatsapp_logs"].insert_one({
                    "whatsapp_id": f"WA-{uuid.uuid4().hex[:10].upper()}",
                    "provider": "meta",
                    "direction": "inbound",
                    "event_type": "whatsapp_reply",
                    "recipient_type": "trainer",
                    "from_number": from_number,
                    "to_number": display_phone,
                    "body": _meta_message_text(message),
                    "status": "received",
                    "meta_message_id": message_id,
                    "meta_phone_number_id": phone_number_id,
                    "meta_contact": contact,
                    "meta_payload": message,
                    "context": {"source": "meta_webhook"},
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                })
                processed["messages"] += 1

    return {"received": True, **processed}


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
        toc_data = await _generate_toc_with_gemini({**payload, "duration_days": duration_days})
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
        "created_at": utc_now(),
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
        {"$set": {"html": html, "pdf_generated_at": utc_now()}},
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

    sent_at = utc_now()
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


@router.post("/toc/auto-generate")
async def auto_generate_toc(payload: dict, request: Request):
    db = get_db()
    requirement_id = payload.get("requirement_id") or ""
    trainer_id = payload.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        raise HTTPException(400, "requirement_id and trainer_id are required")

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        latest_log = await db["email_logs"].find_one(
            {"requirement_id": requirement_id, "trainer_id": trainer_id, "to_email": {"$nin": [None, ""]}},
            {"_id": 0},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        trainer = {
            "trainer_id": trainer_id,
            "name": (latest_log or {}).get("trainer_name") or "Trainer",
            "email": (latest_log or {}).get("to_email") or "",
            "phone": (latest_log or {}).get("trainer_phone") or "",
        }
    result = await _auto_generate_and_send_toc(
        db,
        request,
        trainer=trainer,
        requirement=requirement,
        source=payload.get("source") or "auto_selection_toc",
    )
    if not result.get("success"):
        raise HTTPException(500, result.get("error") or "Auto TOC generation failed")
    if payload.get("send_confirmation", True):
        result["training_confirmation"] = await _send_auto_training_confirmation(
            db,
            request,
            trainer=trainer,
            requirement=requirement,
            source=payload.get("source") or "auto_selection_toc",
        )
    return result


# --- Document Agent: Purchase Orders ---------------------------------------

async def _next_purchase_order_number(db) -> str:
    year = utc_now().year
    doc = await db["counters"].find_one_and_update(
        {"_id": f"purchase_orders:{year}"},
        {
            "$inc": {"sequence": 1},
            "$setOnInsert": {"created_at": utc_now(), "type": "purchase_orders", "year": year},
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


async def _next_invoice_number(db) -> str:
    year = utc_now().year
    doc = await db["counters"].find_one_and_update(
        {"_id": f"invoices:{year}"},
        {
            "$inc": {"sequence": 1},
            "$setOnInsert": {"created_at": utc_now(), "type": "invoices", "year": year},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"INV-{year}-{int(doc.get('sequence', 1)):04d}"


def _invoice_download_url(request: Request, invoice_id: str) -> str:
    return str(request.url_for("download_invoice", invoice_id=invoice_id))


def _invoice_filename(invoice_doc: dict) -> str:
    number = _re.sub(r"[^A-Za-z0-9._-]+", "_", str(invoice_doc.get("invoice_number") or "invoice")).strip("_")
    client = _re.sub(r"[^A-Za-z0-9._-]+", "_", str((invoice_doc.get("client") or {}).get("name") or "client")).strip("_")
    return f"{number}_{client}.pdf"


def _public_invoice(invoice_doc: dict) -> dict:
    public = {k: v for k, v in invoice_doc.items() if k not in {"_id", "html", "pdf_base64"}}
    for key in ("issue_date", "created_at", "pdf_generated_at", "sent_at"):
        if isinstance(public.get(key), datetime):
            public[key] = public[key].isoformat()
    return public


def _money_text(value) -> str:
    try:
        return f"INR {float(value or 0):,.2f}"
    except Exception:
        return "INR 0.00"


def _render_invoice_html(invoice_doc: dict) -> str:
    esc = _html.escape
    company = invoice_doc.get("company") or {}
    trainer = invoice_doc.get("trainer") or {}
    client = invoice_doc.get("client") or {}
    requirement = invoice_doc.get("requirement") or {}
    commercials = invoice_doc.get("commercials") or {}
    item_rows = "".join([
        f"<tr><td>Training</td><td>{esc(requirement.get('technology') or 'Training')}</td><td>{esc(requirement.get('duration') or '-')}</td><td>{_money_text(commercials.get('total_amount'))}</td></tr>",
        f"<tr><td>GST</td><td>GST on training services</td><td>18%</td><td>{_money_text(commercials.get('gst_amount'))}</td></tr>",
    ])
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(invoice_doc.get('invoice_number') or 'Invoice')}</title>
<style>
@page {{ size:A4; margin:22mm 18mm; }}
body {{ font-family:Arial,sans-serif; color:#1f2937; font-size:12px; line-height:1.45; }}
.header {{ display:flex; justify-content:space-between; gap:24px; border-bottom:3px solid #059669; padding-bottom:18px; margin-bottom:20px; }}
h1,h2,h3 {{ margin:0; color:#0f172a; }}
.muted {{ color:#64748b; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
.box {{ border:1px solid #e2e8f0; border-radius:10px; padding:12px; }}
.title {{ color:#047857; font-weight:700; text-transform:uppercase; font-size:12px; margin-bottom:8px; }}
table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
th {{ background:#ecfdf5; color:#047857; text-align:left; }}
th,td {{ border:1px solid #d1fae5; padding:9px; vertical-align:top; }}
.totals {{ margin-left:auto; width:280px; margin-top:16px; }}
.totals td {{ border-color:#e2e8f0; }}
.total {{ font-weight:700; color:#047857; font-size:14px; }}
.footer {{ margin-top:28px; color:#64748b; font-size:11px; border-top:1px solid #e2e8f0; padding-top:12px; }}
</style></head><body>
<div class="header">
  <div><h1>{esc(company.get('name') or 'Calhan Technologies')}</h1>
  <p class="muted">{esc(company.get('tagline') or 'Corporate Training and Technology Consulting')}</p>
  <p class="muted">{esc(company.get('address') or '')}</p>
  <p class="muted">{esc(company.get('email') or '')} {esc(company.get('phone') or '')}</p></div>
  <div style="text-align:right"><h2>INVOICE</h2>
  <p><strong>{esc(invoice_doc.get('invoice_number') or '')}</strong></p>
  <p class="muted">Date: {esc(invoice_doc.get('issue_date_display') or '')}</p>
  <p class="muted">PO: {esc(invoice_doc.get('po_number') or '')}</p></div>
</div>
<div class="grid">
  <div class="box"><div class="title">Bill To</div><p><strong>{esc(client.get('name') or 'Client')}</strong></p><p>{esc(client.get('email') or '')}</p></div>
  <div class="box"><div class="title">Training Details</div><p><strong>{esc(requirement.get('technology') or 'Training')}</strong></p><p>Trainer: {esc(trainer.get('name') or 'Trainer')}</p><p>Dates: {esc(requirement.get('training_dates') or 'To be confirmed')}</p><p>Mode: {esc(requirement.get('mode') or 'Online')}</p></div>
</div>
<table><thead><tr><th>Item</th><th>Description</th><th>Qty/Rate</th><th>Amount</th></tr></thead><tbody>{item_rows}</tbody></table>
<table class="totals"><tr><td>Subtotal</td><td>{_money_text(commercials.get('total_amount'))}</td></tr><tr><td>GST 18%</td><td>{_money_text(commercials.get('gst_amount'))}</td></tr><tr class="total"><td>Grand Total</td><td>{_money_text(commercials.get('grand_total'))}</td></tr></table>
<div class="box" style="margin-top:18px"><div class="title">Payment Terms</div><p>{esc(invoice_doc.get('payment_terms') or '')}</p></div>
<div class="footer">Linked to PO {esc(invoice_doc.get('po_number') or '')}, requirement {esc(requirement.get('requirement_id') or '')}, trainer {esc(trainer.get('trainer_id') or '')}. Generated by TrainerSync.</div>
</body></html>"""


def _invoice_pdf_from_doc(invoice_doc: dict) -> bytes:
    encoded = invoice_doc.get("pdf_base64")
    if encoded:
        return _base64.b64decode(encoded)
    return purchase_order_pdf_bytes({}, invoice_doc.get("html") or _render_invoice_html(invoice_doc))


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
        "pdf_generated_at": utc_now(),
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


@router.post("/requirements/{requirement_id}/request-client-po")
async def request_client_purchase_order(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        raise HTTPException(404, "Requirement not found")

    trainer_id = str(payload.get("trainer_id") or requirement.get("selected_trainer_id") or "").strip()
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    trainer_name = (
        payload.get("trainer_name")
        or trainer.get("name")
        or requirement.get("selected_trainer_name")
        or "the trainer"
    )
    client_email = str(
        payload.get("client_email")
        or requirement.get("client_email")
        or ""
    ).strip()
    if not client_email:
        raise HTTPException(400, "Client email is required to request PO")

    client_name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or requirement.get("client_company")
        or "Client"
    )
    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    training_dates = (
        payload.get("training_dates")
        or requirement.get("training_dates")
        or requirement.get("timeline_start")
        or ""
    )
    subject = payload.get("subject") or f"Purchase Order Request - {technology} | {requirement_id}"
    body = payload.get("body") or (
        f"Hi {client_name},\n\n"
        f"The {technology} training engagement has been confirmed with {trainer_name}.\n\n"
        "To proceed with invoice generation and commercial closure, kindly share the Purchase Order (PO) "
        "with the applicable PO number, billing details, amount, payment terms, and tax details.\n\n"
        f"Requirement ID: {requirement_id}\n"
        f"Trainer: {trainer_name}\n"
        f"Training Dates: {training_dates or 'As confirmed'}\n\n"
        "Once we receive the PO, Calhan Technologies will generate the invoice and share it back for processing.\n\n"
        "Regards,\nRecruitment Team,\nCalhan Technologies"
    )

    email_id = f"CLIENT-PO-REQ-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    now = utc_now()

    log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": client_email,
        "client_name": client_name,
        "client_email": client_email,
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
        "mail_type": "client_po_request",
        "source": "client_po_request",
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["conversations"].insert_one({
        **log_doc,
        "direction": "client_sent",
        "error": error if not success else "",
    })
    if success:
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {
                "po_request_status": "requested",
                "po_requested_at": now,
                "po_requested_email_id": email_id,
                "selection_status": requirement.get("selection_status") or "training_confirmed",
            }},
        )

    if not success:
        raise HTTPException(500, error or "Could not send PO request to client")
    return {
        "success": True,
        "message": "PO request sent to client",
        "email_id": email_id,
        "to_email": client_email,
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
                "pdf_generated_at": utc_now(),
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
    sent_at = utc_now()
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
        {"$set": {"status": "acknowledged", "acknowledged_at": utc_now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Purchase order not found")
    doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    return {"success": True, "purchase_order": public_purchase_order(doc)}


@router.post("/purchase-orders/{po_id}/generate-invoice")
async def generate_invoice_from_purchase_order(po_id: str, payload: dict, request: Request):
    db = get_db()
    po_doc = await db["purchase_orders"].find_one({"po_id": po_id}, {"_id": 0})
    if not po_doc:
        raise HTTPException(404, "Purchase order not found")

    trainer = po_doc.get("trainer") or {}
    requirement = po_doc.get("requirement") or {}
    requirement_id = requirement.get("requirement_id") or ""
    full_requirement = {}
    if requirement_id:
        full_requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}

    client_email = str(
        requirement.get("client_email")
        or full_requirement.get("client_email")
        or payload.get("client_email")
        or ""
    ).strip()
    requested_client_email = str(payload.get("client_email") or "").strip()
    saved_client_email = str(full_requirement.get("client_email") or requirement.get("client_email") or "").strip()
    if saved_client_email and requested_client_email and saved_client_email.lower() != requested_client_email.lower():
        raise HTTPException(400, "Client email mismatch. Invoice can only be sent to the client saved on this requirement.")
    if not client_email:
        raise HTTPException(400, "Client email is required before generating invoice")

    client_name = (
        payload.get("client_name")
        or requirement.get("client_name")
        or full_requirement.get("client_company")
        or full_requirement.get("client_name")
        or client_email
    )
    invoice_number = await _next_invoice_number(db)
    invoice_id = f"INV-DOC-{uuid.uuid4().hex[:8].upper()}"
    now = utc_now()
    invoice_doc = {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "po_id": po_id,
        "po_number": po_doc.get("po_number"),
        "status": "generated",
        "issue_date": now,
        "issue_date_display": now.strftime("%d %b %Y"),
        "company": po_doc.get("company") or {},
        "trainer": trainer,
        "client": {
            "name": client_name,
            "email": client_email,
        },
        "requirement": {
            **requirement,
            "requirement_id": requirement_id,
            "client_email": client_email,
            "client_name": client_name,
        },
        "commercials": po_doc.get("commercials") or {},
        "payment_terms": payload.get("payment_terms") or po_doc.get("payment_terms") or DEFAULT_PAYMENT_TERMS if "DEFAULT_PAYMENT_TERMS" in globals() else po_doc.get("payment_terms", ""),
        "source": "purchase_order",
        "created_at": now,
        "download_url": _invoice_download_url(request, invoice_id),
    }

    try:
        html = _render_invoice_html(invoice_doc)
        pdf_bytes = purchase_order_pdf_bytes({}, html)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF generation failed: {exc}")

    invoice_doc.update({
        "html": html,
        "pdf_base64": _base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_content_type": "application/pdf",
        "pdf_filename": _invoice_filename(invoice_doc),
        "pdf_generated_at": utc_now(),
    })
    await db["invoices"].insert_one(invoice_doc)
    await db["purchase_orders"].update_one(
        {"po_id": po_id},
        {"$set": {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "invoice_status": "generated",
            "invoice_generated_at": utc_now(),
        }},
    )
    return {
        "success": True,
        "message": "Invoice generated",
        "invoice": _public_invoice(invoice_doc),
    }


@router.get("/invoices/{invoice_id}/download", name="download_invoice")
async def download_invoice(invoice_id: str):
    db = get_db()
    doc = await db["invoices"].find_one({"invoice_id": invoice_id})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    try:
        pdf_bytes = _invoice_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF download failed: {exc}")
    filename = doc.get("pdf_filename") or _invoice_filename(doc)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, payload: dict, request: Request):
    db = get_db()
    doc = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")

    client = doc.get("client") or {}
    trainer = doc.get("trainer") or {}
    requirement = doc.get("requirement") or {}
    to_email = str(client.get("email") or "").strip()
    requested_to = str(payload.get("to_email") or "").strip()
    if requested_to and requested_to.lower() != to_email.lower():
        raise HTTPException(400, "Client email mismatch. Invoice can only be sent to the saved invoice client.")
    if not to_email:
        raise HTTPException(400, "Client email is required to send invoice")

    try:
        pdf_bytes = _invoice_pdf_from_doc(doc)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Invoice PDF generation failed: {exc}")

    filename = doc.get("pdf_filename") or _invoice_filename(doc)
    subject = payload.get("subject") or f"Invoice {doc.get('invoice_number')} for PO {doc.get('po_number')} - {requirement.get('technology', 'Training')}"
    body = payload.get("body") or (
        f"Dear {client.get('name') or 'Client'},\n\n"
        f"Please find attached invoice {doc.get('invoice_number')} for the {requirement.get('technology', 'training')} engagement.\n\n"
        f"PO Reference: {doc.get('po_number')}\n"
        f"Trainer: {trainer.get('name') or 'Trainer'}\n"
        f"Grand Total: {_money_text((doc.get('commercials') or {}).get('grand_total'))}\n\n"
        "Kindly process as per the agreed terms.\n\n"
        "Regards,\nTrainerSync Team"
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

    sent_at = utc_now()
    status = "sent" if email_success else "send_failed"
    await db["invoices"].update_one(
        {"invoice_id": invoice_id},
        {"$set": {
            "status": status,
            "sent_at": sent_at if email_success else None,
            "email_status": "sent" if email_success else "failed",
            "email_error": email_error,
        }},
    )
    await db["purchase_orders"].update_one(
        {"po_id": doc.get("po_id")},
        {"$set": {
            "invoice_status": status,
            "invoice_sent_at": sent_at if email_success else None,
        }},
    )
    await db["client_messages"].insert_one({
        "message_id": f"CLIENT-MSG-{uuid.uuid4().hex[:8].upper()}",
        "client_email": to_email,
        "client_name": client.get("name") or "",
        "requirement_id": requirement.get("requirement_id") or "",
        "trainer_id": trainer.get("trainer_id") or "",
        "trainer_name": trainer.get("name") or "",
        "subject": subject,
        "body": body,
        "mail_type": "invoice",
        "direction": "sent",
        "status": "sent" if email_success else "failed",
        "error": "" if email_success else email_error,
        "sent_at": sent_at,
        "invoice_id": invoice_id,
        "invoice_number": doc.get("invoice_number"),
        "po_id": doc.get("po_id"),
        "po_number": doc.get("po_number"),
        "source": "invoice",
    })
    updated = await db["invoices"].find_one({"invoice_id": invoice_id}, {"_id": 0})
    if not email_success:
        raise HTTPException(500, email_error or "Invoice send failed")
    return {
        "success": True,
        "message": "Invoice sent to client",
        "invoice": _public_invoice(updated),
    }


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
    now = utc_now()
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
        "teams_email", "microsoft_teams_email", "teams_upn",
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
            {"teams_email": {"$regex": pattern, "$options": "i"}},
            {"microsoft_teams_email": {"$regex": pattern, "$options": "i"}},
            {"teams_upn": {"$regex": pattern, "$options": "i"}},
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
        "created_at": utc_now(),
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


def _wanted_resume_email_body(trainer_name: str, domain: str) -> str:
    domain_label = domain or "the relevant"
    return (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"We are currently looking for trainer profiles for {domain_label} training requirements.\n\n"
        "Kindly share your latest resume / trainer profile along with your updated experience, key skills, "
        "training expertise, availability, and commercial expectations.\n\n"
        "This will help us consider your profile for suitable upcoming opportunities.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )


def _single_trainer_mail_context(trainer: dict, payload: dict) -> dict:
    domain = str(
        payload.get("domain")
        or payload.get("technology")
        or trainer.get("primary_category")
        or trainer.get("technology_category")
        or trainer.get("domain")
        or trainer.get("technologies")
        or "Training"
    ).strip()
    return {
        "domain": domain,
        "duration": str(payload.get("duration") or payload.get("duration_days") or "").strip(),
        "mode": str(payload.get("mode") or "Online").strip(),
        "participants": str(payload.get("participants") or payload.get("participant_count") or "").strip(),
        "client_name": str(payload.get("client_name") or payload.get("client_company") or "").strip(),
        "client_email": str(payload.get("client_email") or "").strip(),
        "requirement_id": str(payload.get("requirement_id") or "").strip(),
    }


def _single_trainer_greeting(trainer_name: str) -> str:
    return f"Dear {trainer_name or 'Trainer'},"


def _has_proper_interview_slots(text: str = "") -> bool:
    clean = _strip_quoted_reply_text(text or "").lower()
    if not clean:
        return False
    date_hits = 0
    for pattern in [
        r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b",
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b",
    ]:
        date_hits += len(_re.findall(pattern, clean, flags=_re.IGNORECASE))
    time_hits = 0
    for pattern in [
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b\d{1,2}(?::\d{2})?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    ]:
        time_hits += len(_re.findall(pattern, clean, flags=_re.IGNORECASE))
    slot_hints = len(_re.findall(r"\b(?:slot|option|available|availability)\b", clean, flags=_re.IGNORECASE))
    return (date_hits >= 3 and time_hits >= 3) or (date_hits >= 3 and time_hits >= 2 and slot_hints >= 1)


def _single_trainer_pipeline_template(trainer_name: str, payload: dict, context: dict) -> dict:
    mail_type = str(payload.get("mail_type") or payload.get("template") or "mail1").strip()
    allowed = {
        "mail1",
        "mail2",
        "mail2_followup",
        "mail3",
        "mail4",
        "mail5_ok",
        "mail5_no",
        "mail6_toc",
        "mail7_confirm",
        "mail3_slot_followup",
    }
    if mail_type not in allowed:
        mail_type = "mail1"

    domain = context.get("domain") or "Training"
    greeting = _single_trainer_greeting(trainer_name)
    duration = context.get("duration") or "[Hours/Days]"
    mode = context.get("mode") or "[Online/Offline]"
    participants = context.get("participants") or "[Number]"
    slots = str(payload.get("slots") or payload.get("trainer_dates") or "").strip()
    interview_link = str(payload.get("interview_link") or "").strip()
    platform = str(payload.get("platform") or "Google Meet / Zoom").strip()
    date_time = str(payload.get("date_time") or payload.get("interview_date") or "").strip()
    training_date = str(payload.get("training_date") or "").strip()
    venue = str(payload.get("venue") or mode or "").strip()
    contact_name = str(payload.get("contact_name") or "Calhan Technologies Team").strip()
    contact_phone = str(payload.get("contact_phone") or "").strip()
    contact_email = str(payload.get("contact_email") or getattr(get_settings(), "from_email", "") or "").strip()

    if mail_type == "mail2":
        return {
            "mail_type": mail_type,
            "subject": f"Training Requirement - {domain} | Additional Details Required",
            "body": (
                f"{greeting}\n\n"
                "Thank you for your response.\n\n"
                "To proceed further, kindly share the below details:\n\n"
                "* Total years of experience\n"
                "* Number of trainings conducted previously\n"
                "* Relevant certifications\n"
                "* Preferred training mode (Online / Offline)\n"
                "* Availability for Full-Day or Half-Day sessions\n"
                "* Expected commercial charges per day/session\n"
                "* Current location\n"
                "* Availability for the mentioned dates\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail2_followup":
        return {
            "mail_type": mail_type,
            "subject": f"Re: Training Requirement - {domain} | Details Required",
            "body": (
                f"{greeting}\n\n"
                "Thank you for confirming your interest.\n\n"
                "To proceed further, kindly share the above requested details:\n\n"
                "* Total years of experience\n"
                "* Number of trainings conducted previously\n"
                "* Relevant certifications\n"
                "* Preferred training mode (Online / Offline)\n"
                "* Availability for Full-Day or Half-Day sessions\n"
                "* Expected commercial charges per day/session\n"
                "* Current location\n"
                "* Availability for the mentioned dates\n\n"
                "Once we receive these details, we can move ahead with the next step.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail3":
        slot_lines = slots or "* [Slot 1]\n* [Slot 2]\n* [Slot 3]"
        return {
            "mail_type": mail_type,
            "subject": f"Interview Slot Booking - {domain}",
            "body": (
                f"{greeting}\n\n"
                "Thank you for sharing your details.\n\n"
                "We would like to book an interview slot with you. Based on your availability, "
                "please confirm one of the following slots:\n\n"
                f"{slot_lines}\n\n"
                "Kindly confirm your preferred slot at the earliest.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail4":
        return {
            "mail_type": mail_type,
            "subject": f"Interview Schedule Confirmation - {domain}",
            "body": (
                f"{greeting}\n\n"
                "Your interview has been scheduled. Please find the details below:\n\n"
                f"Date & Time: {date_time or '[Date & Time]'}\n"
                f"Platform: {platform or '[Platform]'}\n"
                f"Meeting Link: {interview_link or '[Meeting Link]'}\n\n"
                "Please join on time. Let us know if you need any assistance.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail3_slot_followup":
        return {
            "mail_type": mail_type,
            "subject": "Interview Slot Details Required",
            "body": (
                f"Hi {trainer_name or 'Trainer'},\n\n"
                "Thank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\n"
                "Also, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\n"
                "Thanks."
            ),
        }

    if mail_type == "mail5_ok":
        return {
            "mail_type": mail_type,
            "subject": f"Congratulations! You have been Selected - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Congratulations! We are pleased to inform you that you have been selected for the {domain} training requirement.\n\n"
                "To proceed further, kindly share the following:\n\n"
                "* Table of Contents (ToC) / Course Agenda for the training\n"
                "* Any prerequisite materials or tools required\n\n"
                "We look forward to working with you!\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail5_no":
        return {
            "mail_type": mail_type,
            "subject": f"Update on Training Requirement - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Thank you for your time and interest in the {domain} training requirement.\n\n"
                "After careful consideration, we regret to inform you that we have decided to proceed with another trainer at this time.\n\n"
                "We will keep your profile on record and reach out for future opportunities.\n\n"
                "Thank you once again for your cooperation.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail6_toc":
        return {
            "mail_type": mail_type,
            "subject": f"Action Required: ToC / Course Agenda - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"Congratulations again on being selected for the {domain} training!\n\n"
                "To initiate the onboarding process, kindly share the following at the earliest:\n\n"
                "* Detailed Table of Contents (ToC) / Course Agenda\n"
                "* Day-wise session breakdown\n"
                "* Tools, software, or prerequisites required by participants\n"
                "* Estimated preparation time needed\n\n"
                "Please revert at the earliest so we can coordinate with the client on schedule.\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    if mail_type == "mail7_confirm":
        return {
            "mail_type": mail_type,
            "subject": f"Training Schedule Confirmed - {domain}",
            "body": (
                f"{greeting}\n\n"
                f"We are pleased to confirm your engagement for the {domain} training. Please find the final details below:\n\n"
                f"Training Date: {training_date or '[Training Date]'}\n"
                f"Venue / Platform: {venue or '[Venue / Platform]'}\n\n"
                "Action Items Before Training:\n"
                "* Ensure all materials and slides are ready\n"
                "* Share soft copies of training content with us 2 days prior\n"
                "* Confirm your availability 24 hours before the training\n\n"
                "For any questions or additional information, please contact:\n\n"
                f"Contact Name: {contact_name or '[Contact Name]'}\n"
                f"Phone: {contact_phone or '[Phone Number]'}\n"
                f"Email: {contact_email or '[Email]'}\n\n"
                "We look forward to a successful training session!\n\n"
                "Regards,\nTrainerSync Team"
            ),
        }

    return {
        "mail_type": "mail1",
        "subject": f"Training Requirement - {domain}",
        "body": compose_shortlist_first_email(
            trainer_name,
            domain,
            context.get("duration") or "",
            context.get("mode") or "",
            context.get("participants") or "",
        ),
    }


@router.post("/trainers/{trainer_id}/request-resume")
async def request_trainer_resume(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    trainer_name = str(payload.get("trainer_name") or trainer.get("name") or "Trainer").strip()
    to_email = str(payload.get("to_email") or trainer.get("email") or trainer.get("trainer_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Trainer email is required to request a resume")

    domain = str(
        payload.get("domain")
        or payload.get("technology")
        or trainer.get("primary_category")
        or trainer.get("technology_category")
        or trainer.get("domain")
        or trainer.get("technologies")
        or "Training"
    ).strip()
    subject = str(payload.get("subject") or f"Updated Trainer Profile / Resume Request - {domain}").strip()
    body = str(payload.get("body") or _wanted_resume_email_body(trainer_name, domain)).strip()

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(to_email, subject, body, smtp_config, tracking_url)

    sent_at = utc_now()
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": payload.get("requirement_id") or "",
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": "wanted_resume",
        "created_at": sent_at,
    })
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": payload.get("requirement_id") or "",
        "subject": subject,
        "body": body,
        "mail_type": "wanted_resume",
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "email_id": email_id,
    })

    if not success:
        raise HTTPException(500, error or "Resume request email failed")

    await db["trainers"].update_one(
        {"trainer_id": trainer_id},
        {"$set": {
            "status": "contacted",
            "resume_requested_at": sent_at,
            "resume_requested_domain": domain,
            "updated_at": sent_at,
        }},
    )
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or trainer
    return {
        "success": True,
        "message": "Resume request mail sent",
        "email_id": email_id,
        "trainer": trainer,
    }


# ─── Create Requirement & Run Pipeline ───────────────────────────────────────

@router.post("/trainers/{trainer_id}/send-automation-mail")
async def send_single_trainer_automation_mail(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    trainer_name = str(payload.get("trainer_name") or trainer.get("name") or "Trainer").strip()
    to_email = str(payload.get("to_email") or trainer.get("email") or trainer.get("trainer_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Trainer email is required to send automation mail")

    context = _single_trainer_mail_context(trainer, payload)
    template = _single_trainer_pipeline_template(trainer_name, payload, context)
    mail_type = template["mail_type"]
    subject = str(payload.get("subject") or template["subject"]).strip()
    body = str(payload.get("body") or template["body"]).strip()
    custom_note = str(payload.get("message") or payload.get("custom_message") or "").strip()
    if custom_note:
        body = f"{custom_note}\n\n---\n{body}"

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer.get("phone") or "")
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {
            "trainer_id": trainer_id,
            "name": trainer_name,
            "email": to_email,
            "phone": trainer_phone,
        },
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
        send_email_async(to_email, subject, body, smtp_config, tracking_url),
        send_shortlist_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=trainer_name,
            subject=subject,
            body=body,
            mail_type=mail_type,
            requirement_id=context["requirement_id"],
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=context["requirement_id"],
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result
    sent_at = utc_now()
    email_stage = {
        "mail1": 1,
        "mail2": 2,
        "mail2_followup": 2,
        "mail3": 3,
        "mail3_slot_followup": 3,
        "mail4": 4,
        "mail5_ok": 5,
        "mail5_no": 5,
        "mail6_toc": 6,
        "mail7_confirm": 7,
    }.get(mail_type, 1)

    await db["email_logs"].insert_one({
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": context["requirement_id"],
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "status": "sent" if success else "failed",
        "email_stage": email_stage,
        "error_message": error if not success else "",
        "sent_at": sent_at if success else None,
        "reply_received": False,
        "opened": False,
        "open_count": 0,
        "tracking_url": tracking_url,
        "retry_count": 0,
        "mail_type": mail_type,
        "source": "single_resume_automation",
        "technology": context["domain"],
        "client_name": context["client_name"],
        "client_email": context["client_email"],
        "trainer_phone": trainer_phone,
        "whatsapp_summary": whatsapp_result,
        "teams_direct_summary": teams_direct_result,
        "created_at": sent_at,
    })
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": to_email,
        "requirement_id": context["requirement_id"],
        "subject": subject,
        "body": body,
        "mail_type": mail_type,
        "direction": "sent",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": sent_at,
        "email_id": email_id,
        "source": "single_resume_automation",
        "client_name": context["client_name"],
        "client_email": context["client_email"],
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        status_by_type = {
            "mail1": "contacted",
            "mail2": "pending_review",
            "mail2_followup": "pending_review",
            "mail3": "pending_review",
            "mail3_slot_followup": "pending_review",
            "mail4": "interview_scheduled",
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {
                "status": status_by_type.get(mail_type, "contacted"),
                "last_automation_mail_at": sent_at,
                "last_automation_mail_domain": context["domain"],
                "last_automation_mail_type": mail_type,
                "last_automation_client_name": context["client_name"],
                "last_automation_client_email": context["client_email"],
                "updated_at": sent_at,
            }},
        )
        teams_stage_by_type = {
            "mail1": "trainer_contacted",
            "mail4": "interview_scheduled",
            "mail5_ok": "trainer_selected",
        }
        teams_stage = teams_stage_by_type.get(mail_type, "pipeline_message_sent")
        teams_result = await send_teams_stage_notification(
            db,
            stage=teams_stage,
            trainer_name=trainer_name,
            requirement={
                "requirement_id": context["requirement_id"],
                "technology_needed": context["domain"],
                "mode": context["mode"],
                "duration": context["duration"],
                "participant_count": context["participants"],
                "client_name": context["client_name"],
                "client_email": context["client_email"],
            },
            request_base_url=_request_base_url(request),
            context={
                "source": "single_resume_automation",
                "email_id": email_id,
                "mail_type": mail_type,
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "client_name": context["client_name"],
                "client_email": context["client_email"],
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    updated_trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or trainer
    if not success:
        raise HTTPException(500, error or "Automation mail failed")
    return {
        "success": True,
        "message": "Automation mail sent",
        "email_id": email_id,
        "trainer": updated_trainer,
        "whatsapp": whatsapp_result,
        "teams_direct": teams_direct_result,
        "teams": teams_result,
    }


@router.get("/trainers/{trainer_id}/automation-status")
async def get_single_trainer_automation_status(trainer_id: str):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    logs = await db["email_logs"].find(
        {"trainer_id": trainer_id, "source": "single_resume_automation"},
        {"_id": 0},
    ).sort("created_at", -1).limit(20).to_list(20)
    latest = logs[0] if logs else {}
    return {
        "trainer_id": trainer_id,
        "trainer": trainer,
        "logs": logs,
        "latest_mail_type": latest.get("mail_type", ""),
        "latest_status": latest.get("status", ""),
        "latest_reply_received": bool(latest.get("reply_received")),
    }


@router.post("/trainers/{trainer_id}/automation-pipeline/tick")
async def tick_single_trainer_automation_pipeline(trainer_id: str, payload: dict, request: Request):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    await manual_reply_check(request)
    logs = await db["email_logs"].find(
        {"trainer_id": trainer_id, "source": "single_resume_automation"},
        {"_id": 0},
    ).sort("created_at", -1).limit(30).to_list(30)

    def sent_logs(mail_types: set[str]) -> list[dict]:
        return [
            item for item in logs
            if item.get("status") == "sent" and item.get("mail_type") in mail_types
        ]

    def latest_sent(mail_types: set[str]) -> dict:
        items = sent_logs(mail_types)
        return items[0] if items else {}

    def log_time(item: dict, *fields: str) -> datetime:
        for field in fields:
            value = item.get(field)
            if isinstance(value, datetime):
                return value
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    continue
        return datetime.min

    next_mail_type = ""
    reason = "waiting"
    if not sent_logs({"mail1"}):
        next_mail_type = "mail1"
        reason = "start_pipeline"
    else:
        mail1 = latest_sent({"mail1"})
        mail2 = latest_sent({"mail2", "mail2_followup"})
        mail3 = latest_sent({"mail3"})
        slot_mail = latest_sent({"mail3", "mail3_slot_followup"})
        if mail1.get("reply_received") and not mail2:
            next_mail_type = "mail2"
            reason = "mail1_replied"
        elif mail2.get("reply_received") and not mail3:
            next_mail_type = "mail3"
            reason = "mail2_replied"
        elif slot_mail.get("reply_received"):
            slot_reply = slot_mail.get("reply_text") or ""
            if _has_proper_interview_slots(slot_reply):
                reason = "mail3_replied_manual_interview_step"
            else:
                reply_time = log_time(slot_mail, "replied_at", "created_at", "sent_at")
                followup_after_reply = any(
                    item.get("status") == "sent"
                    and item.get("mail_type") == "mail3_slot_followup"
                    and log_time(item, "created_at", "sent_at") > reply_time
                    for item in logs
                )
                if followup_after_reply:
                    reason = "waiting_clear_slot_reply"
                else:
                    next_mail_type = "mail3_slot_followup"
                    reason = "mail3_replied_without_proper_slots"
        elif latest_sent({"mail3_slot_followup"}):
            reason = "waiting_clear_slot_reply"
        elif mail2:
            reason = "waiting_mail2_reply"
        else:
            reason = "waiting_mail1_reply"

    if not next_mail_type:
        return {
            "success": True,
            "sent_next": False,
            "reason": reason,
            "trainer": trainer,
            "logs": logs,
        }

    send_payload = {
        **payload,
        "mail_type": next_mail_type,
        "domain": payload.get("domain") or trainer.get("last_automation_mail_domain") or trainer.get("primary_category") or trainer.get("domain") or "Training",
        "client_name": payload.get("client_name") or trainer.get("last_automation_client_name") or "",
        "client_email": payload.get("client_email") or trainer.get("last_automation_client_email") or "",
    }
    result = await send_single_trainer_automation_mail(trainer_id, send_payload, request)
    return {
        **result,
        "sent_next": True,
        "next_mail_type": next_mail_type,
        "reason": reason,
    }


@router.post("/requirements")
async def create_requirement(req: RequirementCreate, request: Request):
    db = get_db()
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    req_dict = req.dict()
    req_dict["client_name"] = str(req_dict.get("client_name") or "").strip()
    req_dict["client_company"] = str(req_dict.get("client_company") or "").strip()
    req_dict["client_email"] = str(req_dict.get("client_email") or "").strip()
    req_dict["client_phone"] = str(req_dict.get("client_phone") or "").strip()
    req_dict["client_whatsapp"] = str(req_dict.get("client_whatsapp") or "").strip()
    if req_dict["client_email"]:
        req_dict["client_email_domain"] = sender_domain(req_dict["client_email"])
    req_dict.update({"requirement_id": req_id, "status": "active", "created_at": utc_now()})

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
        "created_at": utc_now()
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
            trainer_phone = await _trainer_phone(db, payload.get("trainer_id", ""))
            trainer_for_teams = await _trainer_for_direct_teams(
                db,
                payload.get("trainer_id", ""),
                {
                    "trainer_id": payload.get("trainer_id", ""),
                    "name": payload.get("trainer_name", ""),
                    "email": payload.get("to", ""),
                    "phone": trainer_phone,
                },
            )
            email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
                send_email_async(
                    payload["to"],
                    payload["subject"],
                    payload["body"],
                    smtp_config,
                    tracking_url,
                ),
                send_shortlist_whatsapp(
                    db,
                    trainer_phone=trainer_phone,
                    trainer_name=payload.get("trainer_name", ""),
                    subject=payload.get("subject", ""),
                    body=payload.get("body", ""),
                    mail_type="mail1",
                    requirement_id=req_id,
                    email_id=email_id,
                    request_base_url=_request_base_url(request),
                ),
                send_trainer_teams_direct_message(
                    db,
                    trainer=trainer_for_teams,
                    subject=payload.get("subject", ""),
                    body=payload.get("body", ""),
                    requirement_id=req_id,
                    mail_type="mail1",
                    email_id=email_id,
                ),
            )
            success, error = email_result
            email_results.append({
                **payload,
                "email_id": email_id,
                "status": "sent" if success else "failed",
                "error_message": error if not success else "",
                "sent_at": utc_now().isoformat() if success else None,
                "tracking_url": tracking_url,
                "whatsapp": whatsapp_result,
                "teams_direct": teams_direct_result,
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
            "teams_direct_summary": er.get("teams_direct", {}),
            "retry_count":   0,
            "created_at":    utc_now()
        })
        if er["status"] == "sent":
            await send_teams_stage_notification(
                db,
                stage="trainer_contacted",
                trainer_name=er["trainer_name"],
                requirement=req_dict,
                request_base_url=_request_base_url(request),
                context={
                    "source": "requirements_api",
                    "email_id": er["email_id"],
                    "trainer_id": er["trainer_id"],
                    "recipient_type": "trainer",
                    "to_email": er.get("to", ""),
                    "to_phone": (er.get("whatsapp") or {}).get("to_number", ""),
                    "subject": er.get("subject", ""),
                    "body": er.get("body", ""),
                    "mail_type": "mail1",
                    "email_status": "sent",
                    "whatsapp_status": (er.get("whatsapp") or {}).get("status", ""),
                    "teams_direct_status": (er.get("teams_direct") or {}).get("status", ""),
                },
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

    allowed, blocked_response, _ = await _requirement_trainer_send_guard(
        db,
        log.get("requirement_id", ""),
        log.get("trainer_id", ""),
    )
    if not allowed:
        blocked_response["email_id"] = email_id
        blocked_response["mail_type"] = log.get("mail_type", "")
        return blocked_response

    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""), log.get("trainer_phone", ""))
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=log.get("subject", ""),
            body=log.get("body", ""),
            requirement_id=log.get("requirement_id", ""),
            mail_type=log.get("mail_type", "mail1_reminder"),
            email_id=email_id,
        ),
    )
    success, error = email_result
    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        requirement = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id", "")},
            {"_id": 0},
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="pipeline_message_sent",
            trainer_name=log.get("trainer_name", ""),
            requirement=requirement or {"requirement_id": log.get("requirement_id", "")},
            request_base_url=_request_base_url(request),
            context={
                "source": "email_retry",
                "email_id": email_id,
                "mail_type": log.get("mail_type", "mail1_reminder"),
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": log.get("subject", ""),
                "body": log.get("body", ""),
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": utc_now() if success else None,
            "whatsapp_summary": whatsapp_result,
            "teams_direct_summary": teams_direct_result,
            "teams_summary": teams_result,
        },
         "$inc": {"retry_count": 1}}
    )
    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


# ─── Schedule Interview ───────────────────────────────────────────────────────

@router.post("/emails/{email_id}/schedule-interview")
async def schedule_interview(email_id: str, request: Request, interview_date: str = "", interview_link: str = ""):
    db = get_db()
    log = await db["email_logs"].find_one({"email_id": email_id})
    if not log:
        raise HTTPException(404, "Email log not found")

    req = await db["requirements"].find_one({"requirement_id": log["requirement_id"]})
    allowed, blocked_response, req_for_guard = await _requirement_trainer_send_guard(
        db,
        log.get("requirement_id", ""),
        log.get("trainer_id", ""),
    )
    if not allowed:
        blocked_response["email_id"] = email_id
        blocked_response["mail_type"] = "mail4"
        return blocked_response
    req = req_for_guard or req
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
            "interview_email_sent_at": utc_now() if success else None,
            "technology": technology,
            **reminder_fields,
            "interview_reminder_status": "not_scheduled",
            "whatsapp_reminder_status": "not_scheduled",
        }}
    )
    trainer_phone = await _trainer_phone(db, log.get("trainer_id", ""))
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    whatsapp_result, teams_direct_result = await asyncio.gather(
        send_interview_whatsapp(
            db,
            trainer_phone=trainer_phone,
            trainer_name=log.get("trainer_name", ""),
            requirement_id=log.get("requirement_id", ""),
            technology=technology,
            date_time=interview_date,
            platform="Online",
            interview_link=interview_link,
            email_id=email_id,
            request_base_url=_request_base_url(request),
        ),
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=log.get("requirement_id", ""),
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {"whatsapp_summary": whatsapp_result, "teams_direct_summary": teams_direct_result}},
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
            context={
                "source": "email_schedule_interview",
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": interview_date,
            },
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "reminder_schedule": reminder_schedule}


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
    allowed, blocked_response, req_for_guard = await _requirement_trainer_send_guard(
        db,
        requirement_id,
        trainer_id,
    )
    if not allowed:
        blocked_response["mail_type"] = "mail4"
        return blocked_response
    req = req_for_guard or req
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
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type="mail4",
            email_id=email_id,
        ),
    )
    success, error = email_result

    await db["conversations"].insert_one({
        "trainer_id": trainer_id, "trainer_name": trainer_name,
        "to_email": to_email, "requirement_id": requirement_id,
        "subject": subject, "body": body, "mail_type": "mail4",
        "direction": "sent", "status": "sent" if success else "failed",
        "error": error if not success else "", "sent_at": utc_now(),
        "platform": platform, "interview_link": interview_link, "date_time": date_time,
    })

    email_log_doc = {
        "email_id": email_id, "trainer_id": trainer_id, "trainer_name": trainer_name,
        "requirement_id": requirement_id, "to_email": to_email,
        "subject": subject, "body": body,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": utc_now() if success else None,
        "reply_received": False, "opened": False, "open_count": 0,
        "tracking_url": tracking_url, "retry_count": 0, "mail_type": "mail4",
        "interview_scheduled": success, "interview_date": date_time,
        "interview_link": interview_link, "platform": platform,
        "technology": technology,
        "trainer_phone": trainer_phone,
        "teams_direct_summary": teams_direct_result,
        **interview_reminder_fields(date_time),
        "interview_reminder_status": "not_scheduled",
        "whatsapp_reminder_status": "not_scheduled",
        "created_at": utc_now(),
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
            context={
                "source": "shortlist_interview_link",
                "email_id": email_id,
                "mail_type": "mail4",
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
                "interview_date": date_time,
            },
        )
    else:
        reminder_schedule = {"scheduled": False, "status": "email_failed", "error": error}
        teams_result = {"status": "not_sent", "error": "email_failed"}

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result,
            "teams_direct": teams_direct_result,
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

@router.patch("/requirements/{requirement_id}")
async def update_requirement(requirement_id: str, payload: dict, request: Request):
    db = get_db()
    existing = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Requirement not found")

    allowed = {"client_name", "client_company", "client_email", "client_phone", "client_whatsapp"}
    update_fields = {}
    for key in allowed:
        if key in payload:
            update_fields[key] = str(payload.get(key) or "").strip()
    if "client_email" in update_fields:
        update_fields["client_email_domain"] = sender_domain(update_fields["client_email"])

    if update_fields:
        update_fields["updated_at"] = utc_now()
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": update_fields},
        )

    updated = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    pending = await send_pending_client_slot_replies(
        db,
        limit=50,
        requirement_id=requirement_id,
        tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
        source="requirement_client_contact_saved",
        request_base_url=_request_base_url(request),
    )
    return {"success": True, "requirement": updated, "client_slot_pending": pending}


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
    client_email   = str(payload.get("client_email") or "").strip()
    client_name    = str(payload.get("client_name") or "").strip()
    client_company = str(payload.get("client_company") or "").strip()
    client_phone   = str(payload.get("client_phone") or payload.get("client_whatsapp") or "").strip()

    if not to_email or not body:
        raise HTTPException(400, "to_email and body are required")

    requirement_for_guard = {}
    if requirement_id:
        allowed, blocked_response, requirement_for_guard = await _requirement_trainer_send_guard(
            db,
            requirement_id,
            trainer_id,
        )
        if not allowed:
            blocked_response["mail_type"] = mail_type
            return blocked_response

    if mail_type == "mail3" and requirement_id:
        requirement = requirement_for_guard or await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        saved_client_email = str(requirement.get("client_email") or "").strip()
        if not (client_email or saved_client_email):
            raise HTTPException(
                400,
                "Client email is required before sending Slot Booking Mail. Add the client email to this requirement so trainer slots can be sent automatically.",
            )

        update_fields = {}
        if client_email:
            update_fields["client_email"] = client_email
            update_fields["client_email_domain"] = sender_domain(client_email)
        if client_name:
            update_fields["client_name"] = client_name
        if client_company:
            update_fields["client_company"] = client_company
        if client_phone:
            update_fields["client_phone"] = client_phone
        if update_fields:
            update_fields["updated_at"] = utc_now()
            await db["requirements"].update_one(
                {"requirement_id": requirement_id},
                {"$set": update_fields},
            )

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = build_tracking_url(request, email_id)
    smtp_config = await get_admin_email_config(db)
    trainer_phone = await _trainer_phone(db, trainer_id, trainer_phone)
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        trainer_id,
        {"trainer_id": trainer_id, "name": trainer_name, "email": to_email, "phone": trainer_phone},
    )

    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=subject,
            body=body,
            requirement_id=requirement_id,
            mail_type=mail_type,
            email_id=email_id,
        ),
    )
    success, error = email_result

    sent_at = utc_now()
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
        "teams_direct_summary": teams_direct_result,
        "created_at": utc_now(),
    })

    teams_result = {"status": "not_applicable"}
    if success:
        status_by_type = {
            "first": "contacted",
            "mail1": "contacted",
            "mail5_ok": "selected",
            "mail5_no": "rejected",
            "mail6_toc": "toc_requested",
            "mail7_confirm": "training_confirmed",
        }
        new_status = status_by_type.get(mail_type, "pending_review")
        await db["trainers"].update_one({"trainer_id": trainer_id}, {"$set": {"status": new_status}})
        teams_stage_by_type = {
            "first": "trainer_contacted",
            "mail1": "trainer_contacted",
            "mail4": "interview_scheduled",
            "mail5_ok": "trainer_selected",
        }
        teams_stage = teams_stage_by_type.get(mail_type, "pipeline_message_sent")
        if mail_type == "mail5_ok":
            await _mark_requirement_selected_and_stop_others(
                db,
                requirement_id=requirement_id,
                trainer_id=trainer_id,
                trainer_name=trainer_name,
                selected_at=sent_at,
            )
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        teams_result = await send_teams_stage_notification(
            db,
            stage=teams_stage,
            trainer_name=trainer_name,
            requirement=requirement or {"requirement_id": requirement_id},
            request_base_url=_request_base_url(request),
            context={
                "source": "shortlist_send_mail",
                "email_id": email_id,
                "mail_type": mail_type,
                "trainer_id": trainer_id,
                "recipient_type": "trainer",
                "to_email": to_email,
                "to_phone": trainer_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {"success": success, "error": error, "email_id": email_id, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


# ─── Get Conversation Thread ──────────────────────────────────────────────────

@router.post("/shortlists/send-client-slots")
async def send_client_slot_options(payload: dict, request: Request):
    db = get_db()
    try:
        return await send_client_slot_options_email(
            db,
            payload,
            tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
            source=payload.get("source") or "manual",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/emails/{email_id}/send-client-slots")
async def send_email_log_client_slots(email_id: str, payload: dict, request: Request):
    db = get_db()
    try:
        return await send_client_slots_for_email_log(
            db,
            email_id,
            force=bool(payload.get("force", True)),
            overrides=payload,
            tracking_url_builder=lambda new_email_id: build_tracking_url(request, new_email_id),
            source=payload.get("source") or "email_log_button",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        raise HTTPException(400, str(exc)) from exc


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


@router.get("/trainers/{trainer_id}/conversation-thread")
async def get_trainer_conversation_thread(trainer_id: str, limit: int = 250):
    db = get_db()
    trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0})
    if not trainer:
        raise HTTPException(404, "Trainer not found")

    conversations = await db["conversations"].find(
        {"trainer_id": trainer_id},
        {"_id": 0},
    ).sort("sent_at", 1).limit(limit).to_list(limit)

    email_replies = await db["email_logs"].find(
        {"trainer_id": trainer_id, "reply_received": True},
        {
            "_id": 0,
            "email_id": 1,
            "trainer_id": 1,
            "trainer_name": 1,
            "requirement_id": 1,
            "to_email": 1,
            "subject": 1,
            "reply_text": 1,
            "replied_at": 1,
            "created_at": 1,
            "mail_type": 1,
            "source": 1,
            "client_name": 1,
            "client_email": 1,
        },
    ).sort("replied_at", 1).limit(limit).to_list(limit)

    client_slots = await db["client_slot_emails"].find(
        {"trainer_id": trainer_id},
        {"_id": 0},
    ).sort("created_at", 1).limit(limit).to_list(limit)

    client_slot_ids = [doc.get("email_id") for doc in client_slots if doc.get("email_id")]
    confirmations = []
    if client_slot_ids:
        confirmations = await db["client_slot_confirmations"].find(
            {"client_slot_email_id": {"$in": client_slot_ids}},
            {"_id": 0},
        ).sort("updated_at", 1).limit(limit).to_list(limit)

    messages = []
    seen = set()

    def add_message(item: dict):
        body = str(item.get("body") or "")
        key = (
            item.get("direction") or "",
            item.get("mail_type") or "",
            item.get("sent_at") or "",
            item.get("subject") or "",
            body[:500],
        )
        if key in seen:
            return
        seen.add(key)
        messages.append(item)

    for msg in conversations:
        add_message({
            **msg,
            "direction": msg.get("direction") or "sent",
            "channel": "trainer",
        })

    for reply in email_replies:
        body = reply.get("reply_text") or ""
        if not body:
            continue
        add_message({
            "email_id": reply.get("email_id"),
            "trainer_id": reply.get("trainer_id"),
            "trainer_name": reply.get("trainer_name"),
            "requirement_id": reply.get("requirement_id"),
            "to_email": reply.get("to_email"),
            "subject": f"Re: {reply.get('subject', '')}",
            "body": body,
            "direction": "received",
            "sent_at": reply.get("replied_at") or reply.get("created_at"),
            "mail_type": reply.get("mail_type") or "reply",
            "source": reply.get("source") or "email_reply",
            "client_name": reply.get("client_name"),
            "client_email": reply.get("client_email"),
            "channel": "trainer",
        })

    for slot in client_slots:
        add_message({
            "email_id": slot.get("email_id"),
            "trainer_id": trainer_id,
            "trainer_name": slot.get("trainer_name"),
            "requirement_id": slot.get("requirement_id"),
            "to_email": slot.get("to_email"),
            "subject": slot.get("subject") or "Client slot options",
            "body": slot.get("body") or slot.get("slot_text") or "",
            "direction": "client_sent",
            "sent_at": slot.get("sent_at") or slot.get("created_at"),
            "mail_type": "client_slot_options",
            "status": slot.get("status"),
            "client_name": slot.get("client_name"),
            "client_email": slot.get("to_email"),
            "slot_ref": slot.get("slot_ref"),
            "channel": "client",
        })
        if slot.get("last_client_reply_text"):
            add_message({
                "email_id": slot.get("client_reply_message_id") or slot.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": slot.get("trainer_name"),
                "requirement_id": slot.get("requirement_id"),
                "to_email": slot.get("to_email"),
                "subject": f"Re: {slot.get('subject', '')}",
                "body": slot.get("last_client_reply_text"),
                "direction": "client_received",
                "sent_at": slot.get("client_confirmed_at") or slot.get("updated_at") or slot.get("created_at"),
                "mail_type": "client_slot_reply",
                "status": slot.get("status"),
                "client_name": slot.get("client_name"),
                "client_email": slot.get("to_email"),
                "slot_ref": slot.get("slot_ref"),
                "channel": "client",
            })

    for confirmation in confirmations:
        trainer_email = confirmation.get("trainer_schedule_email") or {}
        client_email = confirmation.get("client_schedule_email") or {}
        calendar_event = confirmation.get("calendar_event") or {}
        if trainer_email.get("email_id"):
            add_message({
                "email_id": trainer_email.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": confirmation.get("trainer_name"),
                "requirement_id": confirmation.get("requirement_id"),
                "to_email": confirmation.get("trainer_email"),
                "subject": "Interview Schedule Confirmation",
                "body": (
                    f"Selected slot: {(confirmation.get('parsed_slot') or {}).get('date_time_text') or ''}\n"
                    f"Meet link: {calendar_event.get('meet_link') or calendar_event.get('html_link') or ''}"
                ).strip(),
                "direction": "sent",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "mail_type": "mail4",
                "status": "sent" if trainer_email.get("success") else "failed",
                "client_name": confirmation.get("client_name"),
                "client_email": confirmation.get("client_email"),
                "channel": "trainer",
            })
        if client_email.get("email_id"):
            add_message({
                "email_id": client_email.get("email_id"),
                "trainer_id": trainer_id,
                "trainer_name": confirmation.get("trainer_name"),
                "requirement_id": confirmation.get("requirement_id"),
                "to_email": confirmation.get("client_email"),
                "subject": "Client Schedule Confirmation",
                "body": (
                    f"Selected slot: {(confirmation.get('parsed_slot') or {}).get('date_time_text') or ''}\n"
                    f"Meet link: {calendar_event.get('meet_link') or calendar_event.get('html_link') or ''}"
                ).strip(),
                "direction": "client_sent",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "mail_type": "client_interview_schedule",
                "status": "sent" if client_email.get("success") else "failed",
                "client_name": confirmation.get("client_name"),
                "client_email": confirmation.get("client_email"),
                "channel": "client",
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
    return {"trainer": trainer, "messages": messages[-limit:], "total": len(messages)}


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

async def _build_shortlist_for_existing_requirement(db, requirement: dict) -> dict:
    req_id = requirement.get("requirement_id")
    if not req_id:
        raise HTTPException(400, "Requirement id missing")

    all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
    if not all_trainers:
        shortlist_doc = {
            "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
            "requirement_id": req_id,
            "technology_needed": requirement.get("technology_needed", ""),
            "top_trainers": [],
            "total_matched": 0,
            "category_filter_applied": False,
            "no_category_match": True,
            "category_match_count": 0,
            "created_at": utc_now(),
            "auto_created": True,
        }
        await db["shortlists"].update_one(
            {"requirement_id": req_id},
            {"$setOnInsert": shortlist_doc},
            upsert=True,
        )
        return await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0}) or shortlist_doc

    excluded_statuses = ["interested", "confirmed", "declined"]
    filtered_trainers = [
        trainer for trainer in all_trainers
        if trainer.get("status") not in excluded_statuses
    ]
    result = await run_pipeline(filtered_trainers, requirement)
    top_trainers = [
        {k: v for k, v in trainer.items() if k != "_id"}
        for trainer in result.get("top_trainers", [])
    ]
    total_matched = len(result.get("ranked_trainers", []))
    shortlist_doc = {
        "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
        "requirement_id": req_id,
        "technology_needed": requirement.get("technology_needed", ""),
        "top_trainers": top_trainers,
        "total_matched": total_matched,
        "category_filter_applied": result.get("category_filter_applied", False),
        "no_category_match": result.get("no_category_match", False),
        "category_match_count": result.get("category_match_count", 0),
        "created_at": utc_now(),
        "auto_created": True,
    }
    await db["shortlists"].update_one(
        {"requirement_id": req_id},
        {"$setOnInsert": shortlist_doc},
        upsert=True,
    )
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": {"total_matched": total_matched, "top_count": len(top_trainers)}},
    )
    for trainer in top_trainers:
        trainer_id = trainer.get("trainer_id")
        if not trainer_id:
            continue
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {
                "match_score": trainer.get("match_score"),
                "rank": trainer.get("rank"),
                "status": "pending_review",
            }},
        )
    return await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0}) or shortlist_doc


@router.get("/shortlists/{requirement_id}")
async def get_shortlist(requirement_id: str):
    db = get_db()
    s = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not s:
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        if not requirement:
            raise HTTPException(404, "Requirement not found")
        s = await _build_shortlist_for_existing_requirement(db, requirement)
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

async def _auto_send_client_slots_from_trainer_reply(db, request: Request, log: dict, reply: dict) -> dict:
    if (log or {}).get("mail_type") not in {"mail3", "mail3_slot_followup"}:
        return {"skipped": True, "reason": "Not an interview slot booking reply"}
    if not looks_like_trainer_slots(reply.get("body") or ""):
        return {"skipped": True, "reason": "Trainer reply does not contain concrete interview slots"}
    previous_result = (log or {}).get("client_slot_auto_result") or {}
    if previous_result.get("success"):
        return {
            "skipped": True,
            "reason": "Client slot options already sent",
            "already_sent": True,
            "email_id": previous_result.get("email_id"),
        }

    payload = {
        "trainer_id": log.get("trainer_id") or "",
        "trainer_name": log.get("trainer_name") or "the trainer",
        "requirement_id": log.get("requirement_id") or "",
        "slot_text": reply.get("body") or "",
        "force": False,
        "client_email": log.get("client_email") or "",
        "client_name": log.get("client_name") or "",
        "source_email_id": log.get("email_id") or "",
        "source_message_id": reply.get("message_id_header") or "",
    }
    try:
        result = await send_client_slot_options_email(
            db,
            payload,
            tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
            source="trainer_reply_auto",
            request_base_url=_request_base_url(request),
        )
    except ClientSlotError as exc:
        result = {"success": False, "error": str(exc), "already_sent": False}
    except Exception as exc:
        result = {"success": False, "error": str(exc), "already_sent": False}

    await db["email_logs"].update_one(
        {"email_id": log.get("email_id")},
        {"$set": {
            "client_slot_auto_result": result,
            "client_slot_auto_checked_at": utc_now(),
        }},
    )
    return result


async def _handle_client_slot_confirmation_reply(
    db,
    request: Request,
    *,
    log: dict,
    reply: dict,
    from_email: str,
    replied_at: datetime,
) -> dict:
    if (log or {}).get("mail_type") != "client_slot_options":
        return {"skipped": True, "reason": "Not a client slot options reply"}

    message_id = (
        reply.get("message_id_header")
        or f"imap:{reply.get('msg_id') or log.get('email_id') or uuid.uuid4().hex}"
    )
    slot_doc = await db["client_slot_emails"].find_one({"email_id": log.get("email_id")}, {"_id": 0})
    if not slot_doc:
        return {"success": False, "status": "slot_doc_missing", "error": "Client slot email record not found"}

    from_name, parsed_from_email = _parseaddr(reply.get("from_raw") or reply.get("from_email") or "")
    clean_body = _strip_quoted_reply_text(reply.get("body") or "")
    meta = {
        "email_id": message_id,
        "thread_id": "",
        "received_at": replied_at,
        "from_email": parsed_from_email or from_email,
        "from_name": from_name,
        "subject": reply.get("subject") or f"Re: {log.get('subject', '')}",
        "headers": {},
        "message_id_header": reply.get("message_id_header") or "",
        "raw_body": reply.get("body") or "",
        "clean_body": clean_body,
        "snippet": clean_body[:300],
    }
    result = await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )
    if result:
        return result
    return {"success": False, "status": "client_slot_not_matched", "error": "Could not match client slot reply"}


async def _process_pending_client_slot_confirmations_from_logs(
    db,
    request: Request,
    *,
    limit: int = 25,
) -> dict:
    logs = await db["email_logs"].find(
        {
            "mail_type": "client_slot_options",
            "status": "sent",
            "reply_received": True,
            "reply_text": {"$nin": [None, ""]},
        },
        {"_id": 0},
    ).sort("replied_at", -1).limit(limit).to_list(limit)

    processed = []
    skipped = 0
    failed = 0
    for log in logs:
        already = await db["client_slot_confirmations"].find_one(
            {"client_slot_email_id": log.get("email_id")},
            {"_id": 0, "status": 1},
        )
        if already and already.get("status") not in {"calendar_failed", "trainer_email_failed", "needs_manual_review"}:
            skipped += 1
            continue
        replied_at = log.get("replied_at") or utc_now()
        if isinstance(replied_at, str):
            try:
                replied_at = datetime.fromisoformat(replied_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                replied_at = utc_now()
        reply = {
            "msg_id": log.get("reply_message_id") or log.get("email_id"),
            "message_id_header": log.get("reply_message_id") or "",
            "from_email": log.get("to_email") or "",
            "from_raw": log.get("to_email") or "",
            "subject": f"Re: {log.get('subject', '')}",
            "body": log.get("reply_text") or "",
        }
        result = await _handle_client_slot_confirmation_reply(
            db,
            request,
            log=log,
            reply=reply,
            from_email=log.get("to_email") or "",
            replied_at=replied_at,
        )
        processed.append(result)
        if result and result.get("status") in {"confirmed_scheduled", "already_processed_client_slot_reply"}:
            continue
        if result and result.get("success") is False:
            failed += 1

    return {"checked": len(logs), "processed": processed, "skipped": skipped, "failed": failed}


@router.post("/emails/check-replies")
async def manual_reply_check(request: Request):
    db = get_db()
    sent_recipients = await db["email_logs"].distinct(
        "to_email",
        {
            "status": "sent",
            "$or": [
                {"reply_received": {"$ne": True}},
                {"mail_type": "mail3", "client_slot_auto_result": {"$exists": False}},
            ],
        },
    )
    smtp_config = await get_admin_email_config(db)
    gmail_ok, replies, gmail_error = await asyncio.to_thread(
        _check_gmail_replies_fast,
        since_days=14,
        max_messages=50,
        from_emails=sent_recipients,
    )
    reply_source = "gmail_api" if gmail_ok else "imap"
    if not gmail_ok:
        replies = await asyncio.to_thread(
            check_email_replies,
            since_days=14,
            max_messages=50,
            from_emails=sent_recipients,
            gmail_user=smtp_config.get("smtpUser") or "",
            gmail_pass=smtp_config.get("smtpPass") or "",
        )
    processed = 0
    skipped_duplicates = 0
    skipped_unmatched = 0
    client_slot_auto_sent = 0
    client_slot_auto_failed = 0
    client_slot_auto_results = []
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
            {"_id": 0, "trainer_id": 1, "trainer_name": 1, "requirement_id": 1, "sent_at": 1},
        )
        if existing_reply:
            if existing_reply.get("trainer_id") and existing_reply.get("requirement_id"):
                slot_log = await db["email_logs"].find_one(
                    {
                        "trainer_id": existing_reply.get("trainer_id"),
                        "requirement_id": existing_reply.get("requirement_id"),
                        "to_email": {"$regex": f"^{_re.escape(from_email_clean)}$", "$options": "i"},
                        "mail_type": "mail3",
                        "status": "sent",
                    },
                    {"_id": 0},
                    sort=[("sent_at", -1), ("created_at", -1)],
                )
                if slot_log:
                    slot_result = await _auto_send_client_slots_from_trainer_reply(db, request, slot_log, reply)
                    if slot_result and not slot_result.get("skipped"):
                        client_slot_auto_results.append(slot_result)
                        if slot_result.get("success"):
                            client_slot_auto_sent += 1
                        else:
                            client_slot_auto_failed += 1
            skipped_duplicates += 1
            continue

        replied_at = utc_now()
        try:
            if reply.get("received_at"):
                replied_at = datetime.fromisoformat(str(reply["received_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            replied_at = utc_now()

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

            if log.get("mail_type") == "client_slot_options":
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
                        "trainer_id": trainer_id_matched,
                        "trainer_name": log.get("trainer_name"),
                        "to_email": from_email_clean,
                        "requirement_id": requirement_id_matched,
                        "subject": reply["subject"],
                        "body": reply["body"],
                        "direction": "received",
                        "mail_type": "client_slot_confirmation",
                        "status": "received",
                        "sent_at": replied_at,
                        "message_id_header": message_id_header,
                        "in_reply_to": reply.get("in_reply_to", ""),
                        "references": reply.get("references", ""),
                    })
                confirmation_result = await _handle_client_slot_confirmation_reply(
                    db,
                    request,
                    log=log,
                    reply=reply,
                    from_email=from_email_clean,
                    replied_at=replied_at,
                )
                client_slot_auto_results.append(confirmation_result)
                processed += 1
                continue

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
            slot_result = await _auto_send_client_slots_from_trainer_reply(db, request, log, reply)
            if slot_result and not slot_result.get("skipped"):
                client_slot_auto_results.append(slot_result)
                if slot_result.get("success"):
                    client_slot_auto_sent += 1
                else:
                    client_slot_auto_failed += 1
            processed += 1
        else:
            skipped_unmatched += 1

    pending_slot_scan = await send_pending_client_slot_replies(
        db,
        tracking_url_builder=lambda email_id: build_tracking_url(request, email_id),
        source="reply_check_pending_scan",
        request_base_url=_request_base_url(request),
    )
    client_slot_auto_sent += pending_slot_scan.get("sent", 0)
    client_slot_auto_failed += pending_slot_scan.get("failed", 0)
    client_slot_auto_results.extend(pending_slot_scan.get("results") or [])
    client_confirmation_scan = await _process_pending_client_slot_confirmations_from_logs(
        db,
        request,
        limit=25,
    )
    client_slot_auto_results.extend(client_confirmation_scan.get("processed") or [])

    if processed > 0 and reply_source == "imap":
        from agents.email_agent import mark_emails_seen
        msg_ids = [r["msg_id"] for r in replies if r.get("msg_id")]
        if msg_ids:
            await asyncio.to_thread(mark_emails_seen, msg_ids)

    return {
        "reply_source": reply_source,
        "gmail_fast_error": "" if gmail_ok else gmail_error,
        "replies_found": len(replies),
        "processed": processed,
        "skipped_duplicates": skipped_duplicates,
        "skipped_unmatched": skipped_unmatched,
        "client_slot_auto_sent": client_slot_auto_sent,
        "client_slot_auto_failed": client_slot_auto_failed,
        "client_slot_pending_checked": pending_slot_scan.get("checked", 0),
        "client_slot_confirmations_checked": client_confirmation_scan.get("checked", 0),
        "client_slot_confirmations_failed": client_confirmation_scan.get("failed", 0),
        "client_slot_auto_results": client_slot_auto_results,
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

    today = utc_now().date()
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
    now = utc_now()
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

    now = utc_now()
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


@router.patch("/trainers/{trainer_id}")
async def update_trainer(trainer_id: str, payload: dict):
    db = get_db()
    allowed_fields = {
        "teams_email",
        "microsoft_teams_email",
        "teams_upn",
        "email",
        "phone",
        "location",
        "linkedin",
    }
    updates = {
        key: (str(value).strip() if value is not None else "")
        for key, value in payload.items()
        if key in allowed_fields
    }
    if not updates:
        raise HTTPException(400, "No supported trainer fields provided")
    updates["updated_at"] = utc_now()
    result = await db["trainers"].find_one_and_update(
        {"trainer_id": trainer_id},
        {"$set": updates},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(404, "Trainer not found")
    return {"success": True, "trainer": result}


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
    trainer_for_teams = await _trainer_for_direct_teams(
        db,
        log.get("trainer_id", ""),
        {
            "trainer_id": log.get("trainer_id", ""),
            "name": log.get("trainer_name", ""),
            "email": log.get("to_email", ""),
            "phone": trainer_phone,
        },
    )
    email_result, whatsapp_result, teams_direct_result = await asyncio.gather(
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
        send_trainer_teams_direct_message(
            db,
            trainer=trainer_for_teams,
            subject=log.get("subject", ""),
            body=email_body,
            requirement_id=log.get("requirement_id", ""),
            mail_type=log.get("mail_type", ""),
            email_id=email_id,
        ),
    )
    success, error = email_result
    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"status": "sent", "sent_at": utc_now(), "error_message": ""},
             "$inc": {"retry_count": 1}}
        )
        requirement = await db["requirements"].find_one(
            {"requirement_id": log.get("requirement_id", "")},
            {"_id": 0},
        )
        teams_result = await send_teams_stage_notification(
            db,
            stage="pipeline_message_sent",
            trainer_name=log.get("trainer_name", ""),
            requirement=requirement or {"requirement_id": log.get("requirement_id", "")},
            request_base_url=_request_base_url(request),
            context={
                "source": "email_send_one",
                "email_id": email_id,
                "mail_type": log.get("mail_type", ""),
                "trainer_id": log.get("trainer_id", ""),
                "recipient_type": "trainer",
                "to_email": log.get("to_email", ""),
                "to_phone": trainer_phone,
                "subject": log.get("subject", ""),
                "body": email_body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
                "teams_direct_status": teams_direct_result.get("status", ""),
            },
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"whatsapp_summary": whatsapp_result, "teams_direct_summary": teams_direct_result, "teams_summary": teams_result}},
        )
    return {"success": success, "error": error, "whatsapp": whatsapp_result, "teams_direct": teams_direct_result, "teams": teams_result}


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
    Uses Gemini AI to analyze trainer reply intent accurately.
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
    except Exception as exc:
        logger.warning("AI analyze-reply Gemini API error; falling back to keyword matching: %s", exc)

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
        "created_at": utc_now(),
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


def _exact_email_query(email: str) -> dict:
    clean = _email_key(email)
    if not clean or "@" not in clean:
        raise HTTPException(400, "Enter a valid email address")
    return {"$regex": f"^{_re.escape(clean)}$", "$options": "i"}


async def _resume_email_matches(db, email: str) -> dict:
    email_query = _exact_email_query(email)
    trainers = await db["trainers"].find(
        {"email": email_query},
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "domain": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(50)
    trainer_ids = [item.get("trainer_id") for item in trainers if item.get("trainer_id")]
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    upload_query = {
        "$or": [
            {"extracted_data.email": email_query},
            {"extracted_data.trainer_id": trainer_id_query},
            {"trainer_id": trainer_id_query},
        ]
    }
    uploads = await db["resume_uploads"].find(
        upload_query,
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data.email": 1,
            "extracted_data.name": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(100)

    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({
        "$or": [
            {"trainer_id": trainer_id_query},
            {"to_email": email_query},
        ]
    })
    conversation_count = await db["conversations"].count_documents({
        "$or": [
            {"trainer_id": trainer_id_query},
            {"to_email": email_query},
        ]
    })
    return {
        "email": _email_key(email),
        "trainers": trainers,
        "uploads": uploads,
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
    }


@router.get("/resume-data/by-email")
async def preview_resume_data_by_email(email: str):
    db = get_db()
    return await _resume_email_matches(db, email)


@router.delete("/resume-data/by-email")
async def delete_resume_data_by_email(email: str, include_logs: bool = False):
    db = get_db()
    matches = await _resume_email_matches(db, email)
    trainer_ids = matches.get("trainer_ids") or []
    email_query = _exact_email_query(email)
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}
    upload_ids = [item.get("upload_id") for item in matches.get("uploads", []) if item.get("upload_id")]

    deleted = {
        "trainers": 0,
        "resume_uploads": 0,
        "shortlist_entries_removed": 0,
        "email_logs": 0,
        "conversations": 0,
    }
    if trainer_ids:
        deleted["trainers"] = (await db["trainers"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        pull_result = await db["shortlists"].update_many(
            {"top_trainers.trainer_id": trainer_id_query},
            {"$pull": {"top_trainers": {"trainer_id": trainer_id_query}}},
        )
        deleted["shortlist_entries_removed"] = pull_result.modified_count
    if upload_ids:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"upload_id": {"$in": upload_ids}})).deleted_count
    else:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"extracted_data.email": email_query})).deleted_count

    if include_logs:
        log_query = {
            "$or": [
                {"trainer_id": trainer_id_query},
                {"to_email": email_query},
            ]
        }
        deleted["email_logs"] = (await db["email_logs"].delete_many(log_query)).deleted_count
        deleted["conversations"] = (await db["conversations"].delete_many(log_query)).deleted_count

    return {
        "success": True,
        "email": matches["email"],
        "deleted": deleted,
        "matched": matches["counts"],
    }


def _domain_search_regex(domain: str) -> dict:
    clean = str(domain or "").strip()
    compact = _re.sub(r"[^A-Za-z0-9]+", "", clean)
    if len(compact) < 2:
        raise HTTPException(400, "Enter a domain or technology, for example Data Science or Python")
    if len(compact) <= 40:
        pattern = r"[\s_\-./]*".join(_re.escape(char) for char in compact)
    else:
        pattern = _re.escape(clean)
    return {"$regex": pattern, "$options": "i"}


def _domain_search_terms(domain: str) -> list:
    clean = str(domain or "").strip()
    compact = _re.sub(r"[^A-Za-z0-9]+", "", clean).lower()
    aliases = {
        "datascience": [
            "Data Science",
            "DataScience",
            "Machine Learning",
            "ML",
            "Deep Learning",
            "Python",
            "Pandas",
            "NumPy",
            "Scikit",
            "Statistics",
            "Predictive Analytics",
        ],
        "dataanalytics": ["Data Analytics", "Data Analyst", "Python", "SQL", "Power BI", "Tableau", "Excel"],
        "ai": ["AI", "Artificial Intelligence", "Machine Learning", "Deep Learning"],
        "genai": ["Gen AI", "Generative AI", "LLM", "RAG", "LangChain", "OpenAI"],
        "aws": ["AWS", "Amazon Web Services"],
        "azure": ["Azure", "Microsoft Azure"],
        "devops": ["DevOps", "Docker", "Kubernetes", "Jenkins", "Terraform", "CI/CD"],
    }
    terms = [clean]
    if compact and compact.lower() != clean.lower():
        terms.append(compact)
    terms.extend(aliases.get(compact, []))
    seen = set()
    return [term for term in terms if term and not (term.lower() in seen or seen.add(term.lower()))]


def _domain_search_regexes(domain: str) -> list:
    return [_domain_search_regex(term) for term in _domain_search_terms(domain)]


def _field_regex_clauses(fields: list, regexes: list) -> list:
    return [{field: regex} for field in fields for regex in regexes]


def _resume_domain_trainer_query(domain: str) -> dict:
    regexes = _domain_search_regexes(domain)
    searchable_fields = [
        "technology_category",
        "primary_category",
        "category",
        "domain",
        "technologies",
        "summary",
        "role_designation",
        "resume",
        "combined_text",
        "skills",
        "secondary_categories",
        "specialty_tags",
        "specialisation_tags",
    ]
    return {"$or": _field_regex_clauses(searchable_fields, regexes)}


def _resume_domain_upload_query(domain: str) -> dict:
    regexes = _domain_search_regexes(domain)
    searchable_fields = [
        "filename",
        "source_archive",
        "archive_path",
        "extracted_text",
        "raw_text",
        "extracted_data.technology_category",
        "extracted_data.primary_category",
        "extracted_data.category",
        "extracted_data.domain",
        "extracted_data.technologies",
        "extracted_data.summary",
        "extracted_data.role_designation",
        "extracted_data.resume",
        "extracted_data.combined_text",
        "extracted_data.skills",
        "extracted_data.secondary_categories",
        "extracted_data.specialty_tags",
        "extracted_data.specialisation_tags",
    ]
    return {"$or": _field_regex_clauses(searchable_fields, regexes)}


async def _resume_domain_matches(db, domain: str) -> dict:
    search = str(domain or "").strip()
    _domain_search_regex(search)
    exact_matches = await _resume_domain_exact_matches(db, search)
    exact_counts = exact_matches.get("counts") or {}
    if (exact_counts.get("trainers") or 0) + (exact_counts.get("resume_uploads") or 0):
        return exact_matches

    initial_uploads = await db["resume_uploads"].find(
        _resume_domain_upload_query(search),
        {"_id": 0, "upload_id": 1, "trainer_id": 1, "extracted_data.trainer_id": 1},
    ).limit(200).to_list(200)
    upload_trainer_ids = sorted({
        item.get("trainer_id") or ((item.get("extracted_data") or {}).get("trainer_id"))
        for item in initial_uploads
        if item.get("trainer_id") or ((item.get("extracted_data") or {}).get("trainer_id"))
    })

    trainer_query = {
        "$or": [
            _resume_domain_trainer_query(search),
            {"trainer_id": {"$in": upload_trainer_ids or ["__none__"]}},
        ]
    }
    trainers = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(200)
    trainer_ids = sorted({item.get("trainer_id") for item in trainers if item.get("trainer_id")})
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    uploads = await db["resume_uploads"].find(
        {
            "$or": [
                _resume_domain_upload_query(search),
                {"trainer_id": trainer_id_query},
                {"extracted_data.trainer_id": trainer_id_query},
            ]
        },
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data.email": 1,
            "extracted_data.name": 1,
            "extracted_data.technology_category": 1,
            "extracted_data.skills": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(300)

    upload_ids = sorted({item.get("upload_id") for item in uploads if item.get("upload_id")})
    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({"trainer_id": trainer_id_query})
    conversation_count = await db["conversations"].count_documents({"trainer_id": trainer_id_query})

    return {
        "domain": search,
        "trainers": trainers,
        "uploads": uploads,
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
        "upload_ids": upload_ids,
    }


@router.get("/resume-data/by-domain")
async def preview_resume_data_by_domain(domain: str):
    db = get_db()
    return await _resume_domain_matches(db, domain)


@router.delete("/resume-data/by-domain")
async def delete_resume_data_by_domain(domain: str, include_logs: bool = False):
    db = get_db()
    matches = await _resume_domain_matches(db, domain)
    trainer_ids = matches.get("trainer_ids") or []
    upload_ids = matches.get("upload_ids") or []
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}

    deleted = {
        "trainers": 0,
        "resume_uploads": 0,
        "shortlist_entries_removed": 0,
        "email_logs": 0,
        "conversations": 0,
    }
    if trainer_ids:
        deleted["trainers"] = (await db["trainers"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        pull_result = await db["shortlists"].update_many(
            {"top_trainers.trainer_id": trainer_id_query},
            {"$pull": {"top_trainers": {"trainer_id": trainer_id_query}}},
        )
        deleted["shortlist_entries_removed"] = pull_result.modified_count
    if upload_ids:
        deleted["resume_uploads"] = (await db["resume_uploads"].delete_many({"upload_id": {"$in": upload_ids}})).deleted_count

    if include_logs and trainer_ids:
        deleted["email_logs"] = (await db["email_logs"].delete_many({"trainer_id": trainer_id_query})).deleted_count
        deleted["conversations"] = (await db["conversations"].delete_many({"trainer_id": trainer_id_query})).deleted_count

    return {
        "success": True,
        "domain": matches["domain"],
        "deleted": deleted,
        "matched": matches["counts"],
    }


def _clean_resume_domain_label(value: str) -> str:
    clean = str(value or "").strip()
    clean = _re.sub(r"^[^\w+#.]+", "", clean).strip()
    clean = _re.sub(r"\s+", " ", clean)
    return clean


def _normalise_resume_domain_label(value: str) -> str:
    clean = _clean_resume_domain_label(value)
    compact = _re.sub(r"[^a-z0-9+#.]+", "", clean.lower())
    data_science_terms = {
        "datascience",
        "machinelearning",
        "ml",
        "deeplearning",
        "python",
        "pandas",
        "numpy",
        "scikit",
        "scikitlearn",
        "sklearn",
        "statistics",
        "statisticalmodeling",
        "pytorch",
        "tensorflow",
        "r",
        "sql",
        "tableau",
        "powerbi",
    }
    if compact in data_science_terms:
        return "Data Science"
    gen_ai_terms = {"genai", "generativeai", "llm", "llmops", "rag", "langchain", "openai"}
    if compact in gen_ai_terms:
        return "Gen AI"
    return clean or "Uncategorised"


def _resume_domain_label(doc: dict) -> str:
    source = doc or {}
    for key in ("technology_category", "primary_category", "category", "domain"):
        value = _normalise_resume_domain_label(source.get(key))
        if value and value.lower() not in {"multi-skillset", "multiskillset", "uncategorised", "uncategorized", "unknown"}:
            return value
    technologies = str(source.get("technologies") or "").strip()
    if technologies:
        first = technologies.split(",")[0].strip()
        if first:
            return _normalise_resume_domain_label(first)
    skills = source.get("skills") or []
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",")]
    if isinstance(skills, list):
        for skill in skills:
            clean = _normalise_resume_domain_label(skill)
            if clean:
                return clean
    return "Uncategorised"


def _public_resume_domain_item(doc: dict, item_type: str) -> dict:
    extracted = doc.get("extracted_data") or {}
    def text(value) -> str:
        return "" if value is None else str(value)

    skills = doc.get("skills") or extracted.get("skills") or []
    if not isinstance(skills, list):
        skills = []

    return {
        "type": item_type,
        "trainer_id": text(doc.get("trainer_id") or extracted.get("trainer_id")),
        "upload_id": text(doc.get("upload_id")),
        "name": text(doc.get("name") or extracted.get("name")),
        "email": text(doc.get("email") or extracted.get("email")),
        "phone": text(doc.get("phone") or extracted.get("phone")),
        "filename": text(doc.get("filename")),
        "domain": _resume_domain_label(extracted or doc),
        "skills": [text(skill) for skill in skills[:6]],
        "status": text(doc.get("processing_status") or doc.get("status")),
    }


async def _resume_domain_exact_matches(db, domain: str) -> dict:
    target = _normalise_resume_domain_label(domain).lower()
    upload_docs = await db["resume_uploads"].find(
        {},
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data": 1,
            "created_at": 1,
            "processed_at": 1,
        },
    ).sort("created_at", -1).to_list(5000)
    uploads = [
        upload for upload in upload_docs
        if _resume_domain_label(upload.get("extracted_data") or {}).lower() == target
    ]
    upload_trainer_ids = {
        str(upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id")))
        for upload in uploads
        if upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
    }
    trainer_query = {
        "$or": [
            {"source_sheet": "resume_upload"},
            {"source": "resume_upload"},
            {"trainer_id": {"$in": list(upload_trainer_ids) or ["__none__"]}},
        ]
    }
    trainer_docs = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "primary_category": 1,
            "category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "status": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(5000)
    trainers = [trainer for trainer in trainer_docs if _resume_domain_label(trainer).lower() == target]
    trainer_ids = sorted({str(item.get("trainer_id")) for item in trainers if item.get("trainer_id")})
    upload_ids = sorted({str(item.get("upload_id")) for item in uploads if item.get("upload_id")})
    trainer_id_query = {"$in": trainer_ids or ["__none__"]}
    shortlist_count = await db["shortlists"].count_documents({"top_trainers.trainer_id": trainer_id_query})
    email_log_count = await db["email_logs"].count_documents({"trainer_id": trainer_id_query})
    conversation_count = await db["conversations"].count_documents({"trainer_id": trainer_id_query})

    return {
        "domain": _normalise_resume_domain_label(domain),
        "trainers": [_public_resume_domain_item(trainer, "trainer") for trainer in trainers[:200]],
        "uploads": [_public_resume_domain_item(upload, "upload") for upload in uploads[:300]],
        "counts": {
            "trainers": len(trainers),
            "resume_uploads": len(uploads),
            "shortlists_with_trainer": shortlist_count,
            "email_logs": email_log_count,
            "conversations": conversation_count,
        },
        "trainer_ids": trainer_ids,
        "upload_ids": upload_ids,
    }


@router.get("/resume-data/domain-summary")
async def resume_data_domain_summary(limit_per_domain: int = 8):
    db = get_db()
    limit_per_domain = max(1, min(20, int(limit_per_domain or 8)))
    groups = {}

    def group_for(label: str) -> dict:
        key = label or "Uncategorised"
        if key not in groups:
            groups[key] = {
                "domain": key,
                "trainers_count": 0,
                "uploads_count": 0,
                "trainer_ids": set(),
                "upload_ids": set(),
                "trainers": [],
                "uploads": [],
            }
        return groups[key]

    upload_docs = await db["resume_uploads"].find(
        {},
        {
            "_id": 0,
            "upload_id": 1,
            "trainer_id": 1,
            "filename": 1,
            "processing_status": 1,
            "extracted_data": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(1000)
    for upload in upload_docs:
        extracted = upload.get("extracted_data") or {}
        group = group_for(_resume_domain_label(extracted))
        upload_id = upload.get("upload_id")
        if upload_id and upload_id not in group["upload_ids"]:
            group["upload_ids"].add(upload_id)
            group["uploads_count"] += 1
            if len(group["uploads"]) < limit_per_domain:
                group["uploads"].append(_public_resume_domain_item(upload, "upload"))

    trainer_ids_from_uploads = {
        upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
        for upload in upload_docs
        if upload.get("trainer_id") or ((upload.get("extracted_data") or {}).get("trainer_id"))
    }
    trainer_query = {
        "$or": [
            {"source_sheet": "resume_upload"},
            {"source": "resume_upload"},
            {"trainer_id": {"$in": list(trainer_ids_from_uploads) or ["__none__"]}},
        ]
    }
    trainer_docs = await db["trainers"].find(
        trainer_query,
        {
            "_id": 0,
            "trainer_id": 1,
            "name": 1,
            "email": 1,
            "phone": 1,
            "technology_category": 1,
            "primary_category": 1,
            "category": 1,
            "domain": 1,
            "technologies": 1,
            "skills": 1,
            "status": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).to_list(1000)
    for trainer in trainer_docs:
        group = group_for(_resume_domain_label(trainer))
        trainer_id = trainer.get("trainer_id")
        if trainer_id and trainer_id not in group["trainer_ids"]:
            group["trainer_ids"].add(trainer_id)
            group["trainers_count"] += 1
            if len(group["trainers"]) < limit_per_domain:
                group["trainers"].append(_public_resume_domain_item(trainer, "trainer"))

    domains = []
    for group in groups.values():
        group["trainer_ids"] = sorted(group["trainer_ids"])
        group["upload_ids"] = sorted(group["upload_ids"])
        group["total"] = group["trainers_count"] + group["uploads_count"]
        domains.append(group)
    domains.sort(key=lambda item: (-item["total"], item["domain"].lower()))

    return {
        "domains": domains,
        "total_domains": len(domains),
        "total_trainers": sum(item["trainers_count"] for item in domains),
        "total_uploads": sum(item["uploads_count"] for item in domains),
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
        now = utc_now()

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
                decision_result = await _process_and_store_client_decision_message(
                    db,
                    message_id,
                    service,
                    request,
                    meta_hint=meta,
                )
                if decision_result:
                    processed.append(decision_result)
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
                    "created_at": utc_now(),
                })

        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_history_id": latest_history_id or incoming_history_id,
                "last_processed_at": utc_now(),
                "last_processed_count": len(processed),
            }},
            upsert=True,
        )
        return {"status": "ok", "processed": processed, "skipped": skipped}
    except Exception as exc:
        logger.warning("Gmail webhook error: %s", exc)
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
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
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


@router.get("/client-conversations")
async def get_client_conversations(
    q: Optional[str] = None,
    client: Optional[str] = None,
    domain: Optional[str] = None,
    requirement_id: Optional[str] = None,
    limit: int = 60,
):
    db = get_db()
    limit = max(10, min(int(limit or 60), 150))
    filters = []

    if requirement_id:
        filters.append({"requirement_id": requirement_id})

    if client:
        pattern = {"$regex": _re.escape(client.strip()), "$options": "i"}
        filters.append({"$or": [
            {"from_email": pattern},
            {"from_name": pattern},
            {"extracted.client_email": pattern},
            {"extracted.client_name": pattern},
            {"extracted.client_company": pattern},
        ]})

    domain_requirement_ids = []
    if domain:
        domain_pattern = {"$regex": _re.escape(domain.strip()), "$options": "i"}
        domain_requirements = await db["requirements"].find(
            {"$or": [
                {"technology_needed": domain_pattern},
                {"job_title": domain_pattern},
                {"job_description": domain_pattern},
            ]},
            {"_id": 0, "requirement_id": 1},
        ).limit(200).to_list(200)
        domain_requirement_ids = [doc.get("requirement_id") for doc in domain_requirements if doc.get("requirement_id")]
        domain_or = [
            {"extracted.technology_needed": domain_pattern},
            {"subject": domain_pattern},
            {"clean_body": domain_pattern},
            {"raw_body": domain_pattern},
        ]
        if domain_requirement_ids:
            domain_or.append({"requirement_id": {"$in": domain_requirement_ids}})
        filters.append({"$or": domain_or})

    if q:
        search_pattern = {"$regex": _re.escape(q.strip()), "$options": "i"}
        filters.append({"$or": [
            {"from_email": search_pattern},
            {"from_name": search_pattern},
            {"subject": search_pattern},
            {"clean_body": search_pattern},
            {"raw_body": search_pattern},
            {"extracted.client_company": search_pattern},
            {"extracted.technology_needed": search_pattern},
        ]})

    query = {"$and": filters} if filters else {}
    client_docs = await db["client_emails"].find(query, {"_id": 0}).sort(
        "received_at", -1
    ).limit(600).to_list(600)

    requirement_ids = {
        doc.get("requirement_id")
        for doc in client_docs
        if doc.get("requirement_id")
    }
    requirement_ids.update(domain_requirement_ids)

    requirements = {}
    if requirement_ids:
        req_docs = await db["requirements"].find(
            {"requirement_id": {"$in": list(requirement_ids)}},
            {"_id": 0},
        ).to_list(len(requirement_ids))
        requirements = {doc.get("requirement_id"): doc for doc in req_docs}

    client_emails = sorted({
        (doc.get("from_email") or (doc.get("extracted") or {}).get("client_email") or "").lower()
        for doc in client_docs
        if doc.get("from_email") or (doc.get("extracted") or {}).get("client_email")
    })

    scoped_to_requirement_or_domain = bool(requirement_id or domain)
    slot_filters = []
    if requirement_id:
        slot_filters.append({"requirement_id": requirement_id})
    elif requirement_ids:
        slot_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
    if client_emails and not scoped_to_requirement_or_domain:
        slot_filters.append({"to_email": {"$in": client_emails}})
    slot_docs = []
    if slot_filters:
        slot_docs = await db["client_slot_emails"].find(
            {"$or": slot_filters},
            {"_id": 0},
        ).sort("created_at", -1).limit(400).to_list(400)

    slot_ids = [doc.get("email_id") for doc in slot_docs if doc.get("email_id")]
    confirmations = []
    if slot_ids or requirement_ids:
        confirmation_filters = []
        if slot_ids:
            confirmation_filters.append({"client_slot_email_id": {"$in": slot_ids}})
        if requirement_id:
            confirmation_filters.append({"requirement_id": requirement_id})
        elif requirement_ids:
            confirmation_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
        confirmations = await db["client_slot_confirmations"].find(
            {"$or": confirmation_filters},
            {"_id": 0},
        ).sort("updated_at", -1).limit(400).to_list(400)

    client_message_filters = []
    if requirement_id:
        client_message_filters.append({"requirement_id": requirement_id})
    elif requirement_ids:
        client_message_filters.append({"requirement_id": {"$in": list(requirement_ids)}})
    if slot_ids:
        client_message_filters.append({"client_slot_email_id": {"$in": slot_ids}})
    if client_emails and not scoped_to_requirement_or_domain:
        client_message_filters.append({"client_email": {"$in": client_emails}})
        client_message_filters.append({"to_email": {"$in": client_emails}})
    client_messages = []
    if client_message_filters:
        client_messages = await db["client_messages"].find(
            {"$or": client_message_filters},
            {"_id": 0},
        ).sort("created_at", -1).limit(400).to_list(400)

    threads = {}

    def ensure_group(seed_doc: dict, requirement: dict = None) -> dict:
        requirement = requirement or {}
        key = _client_conversation_key(seed_doc, requirement)
        if key not in threads:
            meta = _client_conversation_meta(seed_doc, requirement)
            threads[key] = {
                "thread_key": key,
                **meta,
                "messages": [],
                "message_count": 0,
                "latest_at": None,
                "last_subject": "",
                "last_preview": "",
                "_seen": set(),
            }
        else:
            meta = _client_conversation_meta(seed_doc, requirement)
            for field in ["client_name", "client_email", "client_company", "domain", "requirement_id", "thread_id", "status"]:
                if meta.get(field) and not threads[key].get(field):
                    threads[key][field] = meta[field]
        return threads[key]

    def add_message(group: dict, item: dict):
        body = str(item.get("body") or "").strip()
        subject = str(item.get("subject") or "").strip()
        if not body and not subject:
            return
        direction = item.get("direction") or "received"
        source = item.get("source") or ""
        normal_body = _re.sub(r"\s+", " ", body.lower()).strip()
        normal_subject = _re.sub(r"\s+", " ", subject.lower()).strip()
        if direction == "received":
            identity = f"{direction}|{normal_subject}|{normal_body[:260]}"
        else:
            identity = f"{source}|{item.get('message_id')}|{direction}|{normal_subject}|{normal_body[:160]}"
        if identity in group["_seen"]:
            return
        group["_seen"].add(identity)
        message = {
            "message_id": item.get("message_id") or "",
            "direction": direction,
            "source": source,
            "subject": subject,
            "body": body,
            "sent_at": item.get("sent_at"),
            "sort_at": item.get("sort_at") or item.get("sent_at"),
            "sort_order": item.get("sort_order", 50),
            "status": item.get("status") or "",
            "from_label": item.get("from_label") or "",
            "to_label": item.get("to_label") or "",
            "meta": item.get("meta") or {},
        }
        group["messages"].append(message)
        when = _thread_datetime(message.get("sent_at"))
        latest = _thread_datetime(group.get("latest_at"))
        if when >= latest:
            group["latest_at"] = message.get("sent_at")
            group["last_subject"] = subject
            group["last_preview"] = body[:180]

    for doc in client_docs:
        req = requirements.get(doc.get("requirement_id")) or {}
        group = ensure_group(doc, req)
        client_label = doc.get("from_name") or doc.get("from_email") or "Client"
        add_message(group, {
            "message_id": doc.get("email_id"),
            "direction": "received",
            "source": "client_inbox",
            "subject": doc.get("subject"),
            "body": doc.get("clean_body") or doc.get("raw_body") or doc.get("snippet"),
            "sent_at": doc.get("received_at") or doc.get("created_at"),
            "sort_order": 10,
            "status": doc.get("status"),
            "from_label": client_label,
            "to_label": "Calhan Technologies",
            "meta": {
                "requirement_id": doc.get("requirement_id"),
                "confidence": doc.get("confidence"),
                "thread_id": doc.get("thread_id"),
            },
        })
        reply = doc.get("generated_reply") or {}
        if reply.get("body"):
            sent_at = doc.get("sent_at")
            add_message(group, {
                "message_id": f"reply:{doc.get('email_id')}",
                "direction": "sent" if sent_at else "draft",
                "source": "calhan_reply",
                "subject": reply.get("subject") or f"Re: {doc.get('subject', '')}",
                "body": reply.get("body"),
                "sent_at": sent_at or doc.get("created_at") or doc.get("received_at"),
                "sort_order": 20,
                "status": doc.get("status"),
                "from_label": "Calhan Technologies",
                "to_label": client_label,
                "meta": {"sent_by": doc.get("sent_by") or ("draft" if not sent_at else "")},
            })

    for slot in slot_docs:
        req = requirements.get(slot.get("requirement_id")) or {}
        group = ensure_group(slot, req)
        client_label = slot.get("client_name") or slot.get("to_email") or "Client"
        add_message(group, {
            "message_id": slot.get("email_id"),
            "direction": "sent",
            "source": "client_slot_options",
            "subject": slot.get("subject"),
            "body": slot.get("body"),
            "sent_at": slot.get("sent_at") or slot.get("created_at"),
            "sort_order": 30,
            "status": slot.get("status"),
            "from_label": "Calhan Technologies",
            "to_label": client_label,
            "meta": {
                "trainer_name": slot.get("trainer_name"),
                "slot_ref": slot.get("slot_ref"),
                "slot_text": slot.get("slot_text"),
            },
        })
        if slot.get("last_client_reply_text"):
            add_message(group, {
                "message_id": f"slot-reply:{slot.get('email_id')}",
                "direction": "received",
                "source": "client_slot_reply",
                "subject": f"Re: {slot.get('subject', '')}",
                "body": slot.get("last_client_reply_text"),
                "sent_at": slot.get("last_client_reply_at") or slot.get("client_confirmed_at"),
                "sort_order": 40,
                "status": slot.get("status"),
                "from_label": client_label,
                "to_label": "Calhan Technologies",
                "meta": {"slot_ref": slot.get("slot_ref")},
            })

    for confirmation in confirmations:
        req = requirements.get(confirmation.get("requirement_id")) or {}
        group = ensure_group(confirmation, req)
        client_label = confirmation.get("client_name") or confirmation.get("client_email") or "Client"
        add_message(group, {
            "message_id": confirmation.get("gmail_message_id") or confirmation.get("confirmation_id"),
            "direction": "received",
            "source": "client_slot_confirmation",
            "subject": confirmation.get("subject"),
            "body": confirmation.get("reply_text"),
            "sent_at": confirmation.get("created_at") or confirmation.get("updated_at"),
            "sort_order": 40,
            "status": confirmation.get("status"),
            "from_label": client_label,
            "to_label": "Calhan Technologies",
            "meta": {
                "trainer_name": confirmation.get("trainer_name"),
                "parsed_slot": confirmation.get("parsed_slot"),
            },
        })
        calendar_event = confirmation.get("calendar_event") or {}
        meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or ""
        if meet_link:
            add_message(group, {
                "message_id": f"meet:{confirmation.get('confirmation_id')}",
                "direction": "system",
                "source": "google_calendar",
                "subject": "Google Meet scheduled",
                "body": f"Meeting link created and trainer notified.\n\nMeet link: {meet_link}",
                "sent_at": confirmation.get("scheduled_at") or confirmation.get("updated_at"),
                "sort_order": 50,
                "status": confirmation.get("status"),
                "from_label": "TrainerSync",
                "to_label": "Client + Trainer",
                "meta": {"meet_link": meet_link},
            })

    for client_message in client_messages:
        req = requirements.get(client_message.get("requirement_id")) or {}
        group = ensure_group(client_message, req)
        client_label = (
            client_message.get("client_name")
            or client_message.get("client_email")
            or client_message.get("to_email")
            or "Client"
        )
        calendar_event = client_message.get("calendar_event") or {}
        meet_link = calendar_event.get("meet_link") or calendar_event.get("html_link") or client_message.get("interview_link") or ""
        add_message(group, {
            "message_id": client_message.get("email_id"),
            "direction": client_message.get("direction") or "sent",
            "source": client_message.get("mail_type") or "client_message",
            "subject": client_message.get("subject"),
            "body": client_message.get("body"),
            "sent_at": client_message.get("sent_at") or client_message.get("created_at"),
            "sort_order": 45,
            "status": client_message.get("status"),
            "from_label": "Calhan Technologies",
            "to_label": client_label,
            "meta": {
                "client_slot_email_id": client_message.get("client_slot_email_id"),
                "meet_link": meet_link,
                "platform": client_message.get("platform"),
                "interview_date": client_message.get("interview_date"),
            },
        })

    result_threads = []
    for group in threads.values():
        group["messages"].sort(key=_message_sort_key)
        group["message_count"] = len(group["messages"])
        if not group.get("latest_at") and group["messages"]:
            group["latest_at"] = group["messages"][-1].get("sent_at")
        group.pop("_seen", None)
        result_threads.append(group)

    search_text = (q or "").strip().lower()
    if search_text:
        result_threads = [
            thread for thread in result_threads
            if search_text in " ".join([
                str(thread.get("client_name") or ""),
                str(thread.get("client_email") or ""),
                str(thread.get("client_company") or ""),
                str(thread.get("domain") or ""),
                str(thread.get("requirement_id") or ""),
                " ".join(str(msg.get("subject") or "") + " " + str(msg.get("body") or "") for msg in thread.get("messages", [])),
            ]).lower()
        ]

    result_threads.sort(key=lambda thread: _thread_datetime(thread.get("latest_at")), reverse=True)

    facet_docs = await db["client_emails"].find({}, {
        "_id": 0,
        "from_email": 1,
        "from_name": 1,
        "extracted.client_company": 1,
        "extracted.technology_needed": 1,
    }).sort("received_at", -1).limit(300).to_list(300)
    clients = []
    domains = set()
    seen_clients = set()
    for doc in facet_docs:
        extracted = doc.get("extracted") or {}
        email = (doc.get("from_email") or "").lower()
        name = doc.get("from_name") or extracted.get("client_company") or email
        key = email or name.lower()
        if key and key not in seen_clients:
            seen_clients.add(key)
            clients.append({
                "name": name or "Client",
                "email": email,
                "company": extracted.get("client_company") or sender_domain(email),
            })
        if extracted.get("technology_needed"):
            domains.add(str(extracted["technology_needed"]))

    return {
        "threads": [_public_doc(thread) for thread in result_threads[:limit]],
        "total": len(result_threads),
        "clients": clients[:100],
        "domains": sorted(domains),
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
        client_schedule_email = doc.get("client_schedule_email") or confirmation.get("client_schedule_email") or {}
        updates.append({
            **doc,
            "technology": req.get("technology_needed") or doc.get("technology") or "Training",
            "client_company": req.get("client_company") or doc.get("client_name") or req.get("client_name"),
            "confirmation_status": confirmation.get("status") or doc.get("status"),
            "confirmed_slot": parsed_slot,
            "meet_link": calendar_event.get("meet_link") or calendar_event.get("html_link") or "",
            "calendar_event_id": calendar_event.get("event_id"),
            "trainer_email_sent": bool(trainer_schedule_email.get("success")),
            "client_email_sent": bool(client_schedule_email.get("success")),
            "last_error": (
                doc.get("calendar_error")
                or confirmation.get("error")
                or trainer_schedule_email.get("error")
                or client_schedule_email.get("error")
                or doc.get("error_message")
                or ""
            ),
        })

    return {"updates": [_public_doc(update) for update in updates], "total": len(updates)}


@router.post("/client-updates/{email_id}/retry-schedule")
async def retry_client_slot_schedule(email_id: str, request: Request):
    db = get_db()
    slot_doc = await db["client_slot_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not slot_doc:
        raise HTTPException(404, "Client slot update not found")

    confirmation = await db["client_slot_confirmations"].find_one(
        {"client_slot_email_id": email_id},
        {"_id": 0},
        sort=[("updated_at", -1), ("created_at", -1)],
    ) or {}
    reply_text = (
        slot_doc.get("last_client_reply_text")
        or confirmation.get("reply_text")
        or ""
    )
    if not reply_text:
        raise HTTPException(400, "Client confirmation reply is missing. Ask the client to confirm a slot first.")

    message_id = (
        confirmation.get("gmail_message_id")
        or slot_doc.get("client_reply_message_id")
        or f"retry:{email_id}"
    )
    meta = {
        "email_id": message_id,
        "thread_id": confirmation.get("thread_id") or "",
        "received_at": slot_doc.get("client_confirmed_at") or confirmation.get("created_at") or utc_now(),
        "from_email": confirmation.get("client_email") or slot_doc.get("to_email") or "",
        "from_name": confirmation.get("client_name") or slot_doc.get("client_name") or "Client",
        "subject": confirmation.get("subject") or f"Re: {slot_doc.get('subject', '')}",
        "headers": {},
        "message_id_header": message_id,
        "raw_body": reply_text,
        "clean_body": reply_text,
        "snippet": reply_text[:300],
    }
    result = await _process_client_slot_reply_from_meta(
        db,
        message_id,
        request=request,
        meta_hint=meta,
        slot_doc=slot_doc,
    )
    if not result:
        raise HTTPException(400, "Could not retry this client slot confirmation")
    return result


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
    now = utc_now()
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
        {"$set": {"status": "rejected", "rejected_at": utc_now()}},
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
        {"$set": {"generated_reply": reply, "reply_regenerated_at": utc_now()}},
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
        {"$set": {"disconnected_at": utc_now()}},
        upsert=True,
    )
    return {"success": True, "connected": False}
