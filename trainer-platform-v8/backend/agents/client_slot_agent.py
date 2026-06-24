from utils.time_utils import utc_now
import hashlib
import re
import uuid
from typing import Callable, Optional

from agents.email_agent import send_email_async
from agents.teams_agent import send_teams_stage_notification
from agents.whatsapp_agent import send_whatsapp_message


CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR = 5000


class ClientSlotError(Exception):
    pass


def strip_quoted_reply_text(text: str) -> str:
    value = str(text or "")
    value = re.split(r"\nOn .+wrote:\s*", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.split(r"\n-{2,}\s*Original Message\s*-{2,}", value, maxsplit=1, flags=re.IGNORECASE)[0]
    lines = [line for line in value.splitlines() if not line.strip().startswith(">")]
    return "\n".join(lines).strip()


def looks_like_trainer_slots(text: str) -> bool:
    value = re.sub(r"\s+", " ", strip_quoted_reply_text(text).lower()).strip()
    if not value:
        return False

    client_confirmation_phrases = [
        "works for our team",
        "client team",
        "please proceed with scheduling",
        "share the meeting details",
        "share meeting details",
        "schedule the discussion",
        "thank you for sharing the trainer",
    ]
    if any(phrase in value for phrase in client_confirmation_phrases):
        return False

    has_time = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", value))
    has_range = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:to|-|–|—)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", value))
    has_date_or_day = bool(re.search(
        r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?|"
        r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})\b",
        value,
    ))
    has_slot_language = bool(re.search(r"\b(?:slot|available|availability|timing|schedule|interview|discussion)\b", value))
    return (has_time or has_range) and (has_date_or_day or has_slot_language)


def _commercial_candidates_from_payload(payload: dict) -> list[str]:
    values = []
    for key in (
        "trainer_commercial",
        "trainer_commercials",
        "commercial",
        "commercials",
        "expected_commercial",
        "expected_commercials",
        "expected_charges_per_day",
    ):
        value = (payload or {}).get(key)
        if isinstance(value, dict):
            for nested_key in (
                "text",
                "commercial",
                "commercials",
                "expected_commercial",
                "expected_commercials",
                "expected_charges_per_day",
                "requested_trainer_commercial",
                "amount",
            ):
                nested = value.get(nested_key)
                if nested not in (None, ""):
                    values.append(str(nested))
        elif value not in (None, ""):
            values.append(str(value))
    return values


def _commercial_unit(text: str) -> str:
    value = str(text or "").lower()
    if re.search(r"\bper\s+hour\b|\b/hour\b|\bhr\b", value):
        return "hour"
    if re.search(r"\bhalf[-\s]?day\b", value):
        return "half day"
    if re.search(r"\bper\s+day\b|\b/day\b|\bday\b", value):
        return "day"
    if re.search(r"\bper\s+session\b|\b/session\b|\bsession\b", value):
        return "session"
    return ""


def _format_commercial_amount(amount_text: str, suffix: str = "") -> str:
    clean_amount = str(amount_text or "").replace(",", "").strip()
    multiplier = 1000 if str(suffix or "").lower() == "k" else 1
    try:
        amount = float(clean_amount) * multiplier
    except ValueError:
        return ""
    amount_display = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
    return f"INR {amount_display}"


def _format_commercial_value(amount: float, unit: str = "") -> str:
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        return ""
    if amount <= 0:
        return ""
    amount_display = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
    unit = str(unit or "").strip()
    return f"INR {amount_display} per {unit}" if unit else f"INR {amount_display}"


def _commercial_text(details: dict) -> str:
    if not details:
        return ""
    return _format_commercial_value(details.get("amount"), details.get("unit")) or str(details.get("text") or "").strip()


def _parse_commercial_from_text(text: str = "", *, require_keyword: bool = True) -> dict:
    value = strip_quoted_reply_text(text)
    if not value:
        return {}
    commercial_keywords = r"\b(?:commercials?|charges?|fees?|rate|budget|cost|commercial\s+expectation|expected\s+commercial|expected\s+charges?)\b"
    lines = [line.strip(" -*\t") for line in value.splitlines() if line.strip()]
    if not lines:
        lines = [value]

    for line in lines:
        has_keyword = bool(re.search(commercial_keywords, line, flags=re.IGNORECASE))
        if require_keyword and not has_keyword:
            continue
        money_match = re.search(
            r"(?:\b(?:inr|rs\.?|rupees?)\s*)?(?:\u20b9\s*)?([0-9][0-9,]*(?:\.\d{1,2})?)(\s*k)?\b",
            line,
            flags=re.IGNORECASE,
        )
        if not money_match:
            continue
        clean_amount = money_match.group(1).replace(",", "").strip()
        multiplier = 1000 if (money_match.group(2) or "").strip().lower() == "k" else 1
        try:
            amount = float(clean_amount) * multiplier
        except ValueError:
            continue
        unit = _commercial_unit(line)
        return {
            "amount": amount,
            "unit": unit,
            "text": _format_commercial_value(amount, unit),
            "source_line": line,
        }
    return {}


def _extract_commercial_from_text(text: str = "", *, require_keyword: bool = True) -> str:
    return _commercial_text(_parse_commercial_from_text(text, require_keyword=require_keyword))


def extract_trainer_commercial_details(slot_text: str = "", payload: Optional[dict] = None) -> dict:
    for candidate in _commercial_candidates_from_payload(payload or {}):
        commercial = _parse_commercial_from_text(candidate, require_keyword=False)
        if commercial:
            return commercial
    return _parse_commercial_from_text(slot_text, require_keyword=True)


def extract_trainer_commercial_text(slot_text: str = "", payload: Optional[dict] = None) -> str:
    return _commercial_text(extract_trainer_commercial_details(slot_text, payload))


def client_commercial_from_trainer_details(details: dict) -> str:
    if not details:
        return ""
    try:
        amount = float(details.get("amount") or 0)
    except (TypeError, ValueError):
        return ""
    return _format_commercial_value(amount + CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR, details.get("unit"))


def _number_value(*values) -> float:
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
        if match:
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:
                pass
    return 0.0


def _requirement_text(requirement: dict) -> str:
    values = []
    for value in (requirement or {}).values():
        if isinstance(value, (str, int, float)):
            values.append(str(value))
        elif isinstance(value, dict):
            values.extend(str(item) for item in value.values() if isinstance(item, (str, int, float)))
    return " ".join(values).lower()


def _client_budget_is_fixed(requirement: dict) -> bool:
    if any(bool((requirement or {}).get(key)) for key in ("budget_fixed", "fixed_budget", "client_budget_fixed", "is_budget_fixed")):
        return True
    text = _requirement_text(requirement)
    fixed_patterns = [
        r"\bfixed\s+budget\b",
        r"\bbudget\s+(?:is\s+)?fixed\b",
        r"\bfixed\s+commercial",
        r"\bcommercials?\s+(?:are\s+|is\s+)?fixed\b",
        r"\bnot\s+negotiable\b",
        r"\bnon[-\s]?negotiable\b",
        r"\bcannot\s+exceed\b",
        r"\bcan't\s+exceed\b",
        r"\bmax(?:imum)?\s+budget\b",
        r"\bbudget\s+cap\b",
        r"\bstrict\s+budget\b",
    ]
    return any(re.search(pattern, text) for pattern in fixed_patterns)


def client_budget_for_trainer_commercial(requirement: dict, trainer_details: dict) -> dict:
    unit = str((trainer_details or {}).get("unit") or "").strip().lower()
    if unit == "hour":
        amount = _number_value(
            (requirement or {}).get("budget_per_hour"),
            (requirement or {}).get("hourly_rate"),
            (requirement or {}).get("client_budget_per_hour"),
        )
    else:
        amount = _number_value(
            (requirement or {}).get("budget_per_day"),
            (requirement or {}).get("day_rate"),
            (requirement or {}).get("client_budget_per_day"),
        )
        if not amount:
            total = _number_value(
                (requirement or {}).get("budget_total"),
                (requirement or {}).get("total_budget"),
                ((requirement or {}).get("commercials") or {}).get("total_amount"),
            )
            days = _number_value((requirement or {}).get("duration_days"), (requirement or {}).get("duration"))
            if total and days and unit in {"day", "session", ""}:
                amount = total / days
            elif total and not unit:
                amount = total
    if not amount:
        return {}
    return {"amount": amount, "unit": unit or "day", "fixed": _client_budget_is_fixed(requirement)}


def client_commercial_budget_issue(requirement: dict, trainer_details: dict) -> dict:
    if not trainer_details:
        return {}
    client_budget = client_budget_for_trainer_commercial(requirement, trainer_details)
    if not client_budget:
        return {}
    try:
        trainer_amount = float(trainer_details.get("amount") or 0)
        budget_amount = float(client_budget.get("amount") or 0)
    except (TypeError, ValueError):
        return {}
    client_amount = trainer_amount + CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR
    if client_amount <= budget_amount:
        return {}

    unit = str(trainer_details.get("unit") or client_budget.get("unit") or "").strip()
    budget_label = "fixed client budget" if client_budget.get("fixed") else "client budget"
    trainer_target = max(0, budget_amount - CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR)
    target_text = _format_commercial_value(trainer_target, unit)
    client_text = _format_commercial_value(client_amount, unit)
    budget_text = _format_commercial_value(budget_amount, unit)
    trainer_text = _commercial_text(trainer_details)
    message = (
        f"The {budget_label} is {budget_text}. "
        f"Trainer quoted {trainer_text}; after adding Clahan's INR {CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR:,.0f} margin, "
        f"the client commercial becomes {client_text}, which exceeds the client budget. "
        f"Please negotiate the trainer commercial to {target_text} or get client approval for {client_text} before sending slots."
    )
    return {
        "message": message,
        "trainer_amount": trainer_amount,
        "trainer_text": trainer_text,
        "client_amount": client_amount,
        "client_text": client_text,
        "budget_amount": budget_amount,
        "budget_text": budget_text,
        "trainer_target": trainer_target,
        "target_text": target_text,
        "unit": unit,
        "fixed": bool(client_budget.get("fixed")),
    }


def client_commercial_budget_error(requirement: dict, trainer_details: dict) -> str:
    return client_commercial_budget_issue(requirement, trainer_details).get("message", "")


def _line_has_commercial_amount(line: str = "") -> bool:
    return bool(_extract_commercial_from_text(line, require_keyword=True))


def strip_trainer_commercial_lines(text: str = "") -> str:
    lines = []
    for line in str(text or "").splitlines():
        if _line_has_commercial_amount(line):
            continue
        lines.append(line)
    clean = "\n".join(lines).strip()
    return clean or str(text or "").strip()


async def get_admin_email_config(db):
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {k: v for k, v in email_cfg.items() if v not in (None, "")}


async def client_contact_for_requirement(db, requirement_id: str, payload: dict) -> tuple:
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


async def trainer_contact_for_slot(db, trainer_id: str, payload: dict) -> tuple[dict, str, str]:
    trainer = {}
    if trainer_id:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    name = (
        payload.get("trainer_name")
        or trainer.get("name")
        or trainer.get("trainer_name")
        or "Trainer"
    )
    email = (
        str(payload.get("trainer_email") or "").strip()
        or str(payload.get("to_email") or "").strip()
        or str(trainer.get("email") or "").strip()
        or str(trainer.get("trainer_email") or "").strip()
    )
    return trainer, name, email


def trainer_commercial_negotiation_body(trainer_name: str, technology: str, issue: dict) -> str:
    target_text = issue.get("target_text") or "the workable commercial"
    trainer_text = issue.get("trainer_text") or "your shared commercial"
    return (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"Thank you for sharing your availability and commercial details for the {technology} requirement.\n\n"
        f"Your shared commercial is {trainer_text}. For this requirement, the workable trainer-side commercial is {target_text}. "
        "Kindly confirm whether this is workable from your side so we can proceed with sharing your slot options with the client.\n\n"
        "Once you confirm, we will move ahead with the next coordination step.\n\n"
        "Best Regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )


async def send_trainer_commercial_negotiation_email(
    db,
    payload: dict,
    requirement: dict,
    issue: dict,
    *,
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "client_slot_budget_guard",
) -> dict:
    trainer_id = str(payload.get("trainer_id") or "").strip()
    requirement_id = str(payload.get("requirement_id") or "").strip()
    trainer, trainer_name, trainer_email = await trainer_contact_for_slot(db, trainer_id, payload)
    if not trainer_email:
        return {
            "success": False,
            "error": "Trainer email not found for commercial negotiation",
            "trainer_id": trainer_id,
        }

    existing = await db["email_logs"].find_one(
        {
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "mail_type": "trainer_commercial_negotiation",
            "status": "sent",
            "reply_received": {"$ne": True},
            "commercials.requested_trainer_commercial": issue.get("trainer_target"),
        },
        {"_id": 0},
        sort=[("sent_at", -1), ("created_at", -1)],
    )
    if existing:
        return {
            "success": True,
            "skipped": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to_email": existing.get("to_email"),
            "requested_trainer_commercial": issue.get("trainer_target"),
            "target_text": issue.get("target_text"),
        }

    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    subject = f"Commercial Revision Request - {technology} Training"
    body = trainer_commercial_negotiation_body(trainer_name, technology, issue)
    email_id = f"TRAINER-COMM-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = tracking_url_builder(email_id) if tracking_url_builder else ""
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(trainer_email, subject, body, smtp_config, tracking_url)
    now = utc_now()
    log_doc = {
        "email_id": email_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requirement_id": requirement_id,
        "to_email": trainer_email,
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
        "mail_type": "trainer_commercial_negotiation",
        "source": source,
        "commercials": {
            "trainer_quoted_commercial": issue.get("trainer_amount"),
            "trainer_quoted_text": issue.get("trainer_text"),
            "requested_trainer_commercial": issue.get("trainer_target"),
            "requested_trainer_text": issue.get("target_text"),
            "client_budget": issue.get("budget_amount"),
            "client_budget_text": issue.get("budget_text"),
            "client_commercial_with_markup": issue.get("client_amount"),
            "client_commercial_text": issue.get("client_text"),
            "clahan_markup": CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR,
            "unit": issue.get("unit") or "",
            "fixed_client_budget": bool(issue.get("fixed")),
        },
        "created_at": now,
    }
    await db["email_logs"].insert_one(log_doc)
    await db["conversations"].insert_one({
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": trainer_email,
        "requirement_id": requirement_id,
        "subject": subject,
        "body": body,
        "direction": "sent",
        "mail_type": "trainer_commercial_negotiation",
        "status": "sent" if success else "failed",
        "error": error if not success else "",
        "sent_at": now,
        "email_id": email_id,
        "opened": False,
        "open_count": 0,
    })
    if success:
        await db["trainers"].update_one(
            {"trainer_id": trainer_id},
            {"$set": {"status": "commercial_negotiation_requested"}},
        )
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.status": "commercial_negotiation_requested",
                "top_trainers.$.pipeline_status": "commercial_negotiation_requested",
                "top_trainers.$.commercial_negotiation_email_id": email_id,
                "top_trainers.$.commercial_negotiation_requested_at": now,
            }},
        )
    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "to_email": trainer_email,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "requested_trainer_commercial": issue.get("trainer_target"),
        "target_text": issue.get("target_text"),
    }


def requirement_locked_for_other_trainer(requirement: dict, trainer_id: str) -> tuple[bool, str, str]:
    selected_trainer_id = str((requirement or {}).get("selected_trainer_id") or "").strip()
    selection_status = str((requirement or {}).get("selection_status") or (requirement or {}).get("status") or "").strip().lower()
    locked_statuses = {
        "selected",
        "trainer_selected_auto_sent",
        "toc_requested",
        "training_confirmed",
        "closed",
        "fulfilled",
    }
    locked = bool(selected_trainer_id) or selection_status in locked_statuses
    if not locked:
        return False, "", ""
    if selected_trainer_id and str(trainer_id or "").strip() == selected_trainer_id:
        return False, selected_trainer_id, str((requirement or {}).get("selected_trainer_name") or "").strip()
    return True, selected_trainer_id, str((requirement or {}).get("selected_trainer_name") or "").strip()


async def send_client_slot_options_email(
    db,
    payload: dict,
    *,
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "manual",
    request_base_url: str = "",
) -> dict:
    trainer_id = payload.get("trainer_id", "")
    trainer_name = payload.get("trainer_name") or "the trainer"
    requirement_id = payload.get("requirement_id", "")
    force = bool(payload.get("force", False))

    if not requirement_id and not str(payload.get("client_email") or "").strip():
        raise ClientSlotError("requirement_id is required")

    requirement, client_email, client_name = await client_contact_for_requirement(db, requirement_id, payload)
    client_phone = (
        str(payload.get("client_phone") or "").strip()
        or str(payload.get("client_whatsapp") or "").strip()
        or str(requirement.get("client_phone") or "").strip()
        or str(requirement.get("client_whatsapp") or "").strip()
    )
    blocked, selected_trainer_id, selected_trainer_name = requirement_locked_for_other_trainer(requirement, trainer_id)
    if blocked:
        return {
            "success": True,
            "skipped": True,
            "already_sent": True,
            "status": "requirement_already_selected",
            "reason": f"{selected_trainer_name or selected_trainer_id or 'Another trainer'} is already selected for this requirement. Client slot mails to remaining trainers are stopped.",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "selected_trainer_id": selected_trainer_id,
            "selected_trainer_name": selected_trainer_name,
        }
    if not client_email:
        raise ClientSlotError("Client email not found for this requirement")

    technology = requirement.get("technology_needed") or payload.get("technology") or "training"
    slot_text = strip_quoted_reply_text(
        payload.get("slot_text") or payload.get("slots") or payload.get("trainer_reply") or ""
    )
    if not slot_text:
        if not force:
            raise ClientSlotError("Trainer slot availability not found for client scheduling")
        slot_text = "The trainer has confirmed availability. Please reply with a convenient slot or share alternate timings."
    elif not force and not looks_like_trainer_slots(slot_text):
        raise ClientSlotError("Trainer reply does not contain concrete interview slot availability")

    trainer_commercial_details = extract_trainer_commercial_details(slot_text, payload)
    
    # If no commercial found in slot reply, look up trainer's previous commercial from mail2 response
    if not trainer_commercial_details and trainer_id and requirement_id:
        try:
            mail2_reply = await db["email_logs"].find_one({
                "trainer_id": trainer_id,
                "requirement_id": requirement_id,
                "mail_type": {"$in": ["mail2", "mail2_followup"]},
                "direction": "received",
            }, sort=[("sent_at", -1)])
            if mail2_reply and mail2_reply.get("reply_text"):
                trainer_commercial_details = extract_trainer_commercial_details(
                    mail2_reply.get("reply_text", ""), 
                    {}
                )
        except Exception as e:
            pass  # Continue without previous commercial if lookup fails
    
    trainer_commercial = _commercial_text(trainer_commercial_details)
    budget_issue = client_commercial_budget_issue(requirement, trainer_commercial_details)
    if budget_issue:
        negotiation_result = await send_trainer_commercial_negotiation_email(
            db,
            payload,
            requirement,
            budget_issue,
            tracking_url_builder=tracking_url_builder,
            source=f"{source}_client_slot_budget_guard",
        )
        prefix = "Client slot email was not sent."
        if negotiation_result.get("success"):
            if negotiation_result.get("already_sent"):
                action_text = "Commercial negotiation mail was already sent to the trainer."
            else:
                action_text = (
                    "Commercial negotiation mail sent to the trainer "
                    f"for {budget_issue.get('target_text') or 'the workable trainer-side commercial'}."
                )
        else:
            action_text = (
                "Commercial negotiation mail could not be sent to the trainer: "
                f"{negotiation_result.get('error') or 'unknown error'}."
            )
        raise ClientSlotError(f"{prefix} {budget_issue.get('message')} {action_text}")
    client_commercial = client_commercial_from_trainer_details(trainer_commercial_details)
    client_slot_text = strip_trainer_commercial_lines(slot_text) if trainer_commercial else slot_text
    commercial_block = f"Commercial: {client_commercial}\n\n" if client_commercial else ""
    normalised_slots = re.sub(r"\s+", " ", slot_text.lower()).strip()
    slot_hash = hashlib.sha256(f"{requirement_id}|{trainer_id}|{normalised_slots}".encode("utf-8")).hexdigest()

    active_statuses = [
        "sent",
        "confirmed_scheduled",
        "calendar_failed",
        "trainer_email_failed",
        "client_email_failed",
        "needs_manual_review",
    ]

    if not force:
        existing = await db["client_slot_emails"].find_one({
            "requirement_id": requirement_id,
            "status": {"$in": active_statuses},
        }, {"_id": 0}, sort=[("created_at", -1)])
        if existing:
            return {
                "success": True,
                "already_sent": True,
                "email_id": existing.get("email_id"),
                "to_email": existing.get("to_email"),
                "slot_ref": existing.get("slot_ref"),
                "status": existing.get("status"),
                "trainer_commercial": existing.get("trainer_commercial") or "",
                "client_commercial": existing.get("client_commercial") or "",
                "blocked_by_requirement": True,
            }

    slot_ref = payload.get("slot_ref") or f"SLOT-{uuid.uuid4().hex[:8].upper()}"
    subject = payload.get("subject") or f"Interview Slot Options - {technology} | {requirement_id} | {slot_ref}"
    body = payload.get("body") or (
        f"Hi {client_name or 'Team'},\n\n"
        f"Our training coordination team has received availability for the {technology} discussion/interview.\n\n"
        f"Reference: {requirement_id} / {slot_ref}\n\n"
        f"Available slot(s):\n{client_slot_text}\n\n"
        f"{commercial_block}"
        "Please confirm which slot works for your team, or share alternate timings if these are not convenient.\n"
        "Once you confirm, Clahan Technologies will schedule the meeting and share the final link separately.\n\n"
        "Regards,\nRecruitment Team,\nClahan Technologies"
    )
    if payload.get("body") and client_commercial and "commercial" not in body.lower():
        body = f"{body.rstrip()}\n\nCommercial: {client_commercial}"
    if slot_ref not in subject:
        subject = f"{subject} | {slot_ref}"
    if slot_ref not in body:
        body = f"{body.rstrip()}\n\nReference: {requirement_id} / {slot_ref}"

    email_id = f"CLIENT-SLOT-{uuid.uuid4().hex[:8].upper()}"
    tracking_url = tracking_url_builder(email_id) if tracking_url_builder else ""
    smtp_config = await get_admin_email_config(db)
    success, error = await send_email_async(client_email, subject, body, smtp_config, tracking_url)
    whatsapp_result = {"status": "skipped", "error": "Client phone not found"}
    if success and client_phone:
        whatsapp_result = await send_whatsapp_message(
            db,
            client_phone,
            body,
            event_type="client_slot_options",
            recipient_type="client",
            request_base_url=request_base_url,
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_slot_options",
                "recipient_name": client_name,
                "client_name": client_name,
                "client_email": client_email,
                "trainer_name": trainer_name,
                "trainer_id": trainer_id,
                "requirement_id": requirement_id,
                "subject": subject,
            },
        )

    now = utc_now()
    doc = {
        "email_id": email_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "to_email": client_email,
        "client_phone": client_phone,
        "client_name": client_name,
        "subject": subject,
        "body": body,
        "slot_text": slot_text,
        "client_slot_text": client_slot_text,
        "trainer_commercial": trainer_commercial,
        "client_commercial": client_commercial,
        "clahan_commercial_markup": CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR if trainer_commercial else 0,
        "slot_ref": slot_ref,
        "slot_hash": slot_hash,
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "sent_at": now if success else None,
        "created_at": now,
        "force": force,
        "source": source,
        "source_email_id": payload.get("source_email_id") or "",
        "source_message_id": payload.get("source_message_id") or "",
        "whatsapp_summary": whatsapp_result,
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
        "trainer_commercial": trainer_commercial,
        "client_commercial": client_commercial,
        "clahan_commercial_markup": CLAHAN_CLIENT_COMMERCIAL_MARKUP_INR if trainer_commercial else 0,
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
        "source": source,
        "client_phone": client_phone,
        "whatsapp_summary": whatsapp_result,
    })

    teams_result = {"status": "not_sent", "error": "email_failed"}
    if success:
        teams_result = await send_teams_stage_notification(
            db,
            stage="client_message_sent",
            trainer_name=client_name,
            requirement=requirement or {"requirement_id": requirement_id, "technology_needed": technology},
            request_base_url=request_base_url,
            context={
                "source": source,
                "email_id": email_id,
                "mail_type": "client_slot_options",
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "recipient_type": "client",
                "client_email": client_email,
                "client_phone": client_phone,
                "subject": subject,
                "body": body,
                "email_status": "sent",
                "whatsapp_status": whatsapp_result.get("status", ""),
            },
        )
        await db["client_slot_emails"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )
        await db["email_logs"].update_one(
            {"email_id": email_id},
            {"$set": {"teams_summary": teams_result}},
        )

    return {
        "success": success,
        "error": error,
        "email_id": email_id,
        "to_email": client_email,
        "slot_ref": slot_ref,
        "already_sent": False,
        "trainer_commercial": trainer_commercial,
        "client_commercial": client_commercial,
        "whatsapp": whatsapp_result,
        "teams": teams_result,
    }


async def send_client_slots_for_email_log(
    db,
    email_id: str,
    *,
    force: bool = False,
    overrides: Optional[dict] = None,
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "email_log_manual",
    request_base_url: str = "",
) -> dict:
    log = await db["email_logs"].find_one({"email_id": email_id}, {"_id": 0})
    if not log:
        raise ClientSlotError("Email log not found")
    if log.get("mail_type") != "mail3":
        raise ClientSlotError("Client slot sending is available only for interview slot booking replies")

    slot_text = log.get("reply_text") or ""
    if not slot_text:
        latest_reply = await db["conversations"].find_one(
            {
                "trainer_id": log.get("trainer_id"),
                "requirement_id": log.get("requirement_id"),
                "direction": "received",
            },
            {"_id": 0},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        slot_text = (latest_reply or {}).get("body") or ""
    if not slot_text:
        raise ClientSlotError("Trainer slot reply not found for this email")

    overrides = overrides or {}
    client_email = str(overrides.get("client_email") or "").strip()
    client_name = str(overrides.get("client_name") or "").strip()
    if client_email and log.get("requirement_id"):
        update_fields = {"client_email": client_email}
        if client_name:
            update_fields["client_name"] = client_name
        await db["requirements"].update_one(
            {"requirement_id": log.get("requirement_id")},
            {"$set": update_fields},
        )

    result = await send_client_slot_options_email(
        db,
        {
            "trainer_id": log.get("trainer_id") or "",
            "trainer_name": log.get("trainer_name") or "the trainer",
            "requirement_id": log.get("requirement_id") or "",
            "slot_text": slot_text,
            "force": force,
            "client_email": client_email,
            "client_name": client_name,
            "source_email_id": email_id,
            "source_message_id": log.get("reply_message_id") or "",
        },
        tracking_url_builder=tracking_url_builder,
        source=source,
        request_base_url=request_base_url,
    )
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "client_slot_auto_result": result,
            "client_slot_auto_checked_at": utc_now(),
        }},
    )
    return result


async def send_pending_client_slot_replies(
    db,
    *,
    limit: int = 50,
    requirement_id: str = "",
    tracking_url_builder: Optional[Callable[[str], str]] = None,
    source: str = "pending_reply_scan",
    request_base_url: str = "",
) -> dict:
    return {
        "checked": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
        "manual_only": True,
        "reason": "Client slot mails are manual only",
    }
    query = {
        "mail_type": {"$in": ["mail3", "mail3_slot_followup"]},
        "status": "sent",
        "reply_received": True,
        "reply_text": {"$nin": [None, ""]},
        "$or": [
            {"client_slot_auto_result": {"$exists": False}},
            {"client_slot_auto_result.success": {"$ne": True}},
        ],
    }
    if requirement_id:
        query["requirement_id"] = requirement_id

    logs = await db["email_logs"].find(
        query,
        {"_id": 0},
    ).sort("replied_at", -1).limit(limit).to_list(limit)

    results = []
    sent = 0
    failed = 0
    for log in logs:
        try:
            result = await send_client_slots_for_email_log(
                db,
                log.get("email_id", ""),
                force=False,
                tracking_url_builder=tracking_url_builder,
                source=source,
                request_base_url=request_base_url,
            )
        except ClientSlotError as exc:
            result = {"success": False, "error": str(exc), "already_sent": False}
            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {
                    "client_slot_auto_result": result,
                    "client_slot_auto_checked_at": utc_now(),
                }},
            )
        except Exception as exc:
            result = {"success": False, "error": str(exc), "already_sent": False}
            await db["email_logs"].update_one(
                {"email_id": log.get("email_id")},
                {"$set": {
                    "client_slot_auto_result": result,
                    "client_slot_auto_checked_at": utc_now(),
                }},
            )
        results.append(result)
        if result.get("success"):
            sent += 1
        else:
            failed += 1

    return {"checked": len(logs), "sent": sent, "failed": failed, "results": results}
