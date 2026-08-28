"""Client inbox management — approve, reject, regenerate-reply."""
import html
import json
import logging
import re
import uuid
from datetime import datetime, time, timedelta
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db
from app.agents.email_classifier import classify_email
from app.agents.reply_templates import build_auto_reply
from app.gmail_client import generate_message_id, send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)

PENDING_STATUSES = ["pending_approval", "pending_review", "needs_manual_review"]
VISIBLE_DEFAULT_STATUSES = [
    "pending_approval",
    "pending_review",
    "needs_manual_review",
    "received",
    "processed",
    "reply_failed",
    "send_failed",
    "trainer_email_failed",
    "trainer_email_missing",
    "calendar_failed",
    "client_email_failed",
]
HIDDEN_DEFAULT_STATUSES = ["spam", "ignored", "deleted"]
HIDDEN_DEFAULT_SENDER_REGEX = (
    r"noreply|no-reply|donotreply|do-not-reply|postmaster|mailer-daemon|mail delivery subsystem|newsletter|updates-noreply|"
    r"recommendationnc|onlinecourses|@linkedin\.com$|@naukri\.com$|"
    r"@googlemail\.com$|@alison\.com$|@reliancedigital\.in$|@nptel\.iitm\.ac\.in$"
)
HIDDEN_DEFAULT_CATEGORIES = ["bounce", "system", "newsletter", "marketing", "job_alert"]
CLIENT_REQUEST_SIGNAL = {
    "$or": [
        {"extracted.is_training_request": True},
        {"extracted.direct_request_language": True},
        {"requirement_id": {"$exists": True, "$nin": ["", None]}},
    ]
}


def _status_filter(status: Optional[str], include_hidden: bool = False) -> Dict[str, Any]:
    if include_hidden and (not status or status == "all"):
        return {}
    if not status or status == "all":
        return {
            "$and": [
                {"deleted": {"$ne": True}},
                {"status": {"$nin": HIDDEN_DEFAULT_STATUSES}},
                {"reply_status": {"$nin": HIDDEN_DEFAULT_STATUSES}},
                {
                    "$or": [
                        {"status": {"$in": VISIBLE_DEFAULT_STATUSES}},
                        {"reply_status": {"$in": VISIBLE_DEFAULT_STATUSES}},
                        {"extracted.is_training_request": True},
                        {"requirement_id": {"$exists": True, "$nin": ["", None]}},
                    ],
                },
                CLIENT_REQUEST_SIGNAL,
                {
                    "$nor": [
                        {"from_email": {"$regex": HIDDEN_DEFAULT_SENDER_REGEX, "$options": "i"}},
                        {"from_name": {"$regex": HIDDEN_DEFAULT_SENDER_REGEX, "$options": "i"}},
                        {"office_mail_category": {"$in": HIDDEN_DEFAULT_CATEGORIES}},
                        {"email_classification.scenario": {"$in": HIDDEN_DEFAULT_CATEGORIES}},
                        {"email_classification.person_type": {"$in": ["bounce", "system"]}},
                        {"extracted.is_non_client_email": True},
                    ]
                },
            ],
        }
    statuses = PENDING_STATUSES if status == "pending_approval" else [status]
    return {
        "$and": [
            {"deleted": {"$ne": True}},
            {"status": {"$ne": "deleted"}},
            {
                "$or": [
                    {"status": {"$in": statuses}},
                    {"reply_status": {"$in": statuses}},
                ],
            },
            CLIENT_REQUEST_SIGNAL,
            {
                "$nor": [
                    {"from_email": {"$regex": HIDDEN_DEFAULT_SENDER_REGEX, "$options": "i"}},
                    {"from_name": {"$regex": HIDDEN_DEFAULT_SENDER_REGEX, "$options": "i"}},
                    {"office_mail_category": {"$in": HIDDEN_DEFAULT_CATEGORIES}},
                    {"email_classification.scenario": {"$in": HIDDEN_DEFAULT_CATEGORIES}},
                    {"email_classification.person_type": {"$in": ["bounce", "system"]}},
                    {"extracted.is_non_client_email": True},
                ]
            },
        ],
    }


def _count_status_query(statuses: List[str]) -> Dict[str, Any]:
    return {
        "$or": [
            {"status": {"$in": statuses}},
            {"reply_status": {"$in": statuses}},
        ],
    }


def _today_query() -> Dict[str, Any]:
    # The UI is used in IST while Mongo datetimes are stored in UTC.
    ist_offset = timedelta(hours=5, minutes=30)
    today_ist = datetime.utcnow() + ist_offset
    start_ist = datetime.combine(today_ist.date(), time.min)
    end_ist = start_ist + timedelta(days=1)
    start_utc = start_ist - ist_offset
    end_utc = end_ist - ist_offset
    return {
        "$or": [
            {"created_at": {"$gte": start_utc, "$lt": end_utc}},
            {"updated_at": {"$gte": start_utc, "$lt": end_utc}},
            {"received_at": {"$gte": start_ist.isoformat(), "$lt": end_ist.isoformat()}},
        ],
    }


def _normalise_item_status(doc: Dict[str, Any]) -> Dict[str, Any]:
    raw_status = doc.get("status") or ""
    effective = doc.get("reply_status") or raw_status or "pending_approval"
    if effective in ("pending_review", "needs_manual_review"):
        effective = "pending_approval"
    if raw_status and raw_status != effective:
        doc["raw_status"] = raw_status
    doc["status"] = effective
    for field in ("clean_body", "raw_body", "body", "ai_reply", "draft_reply"):
        if doc.get(field):
            doc[field] = _clean_incoming_email(doc[field])
    generated_reply = doc.get("generated_reply")
    if isinstance(generated_reply, dict) and generated_reply.get("body"):
        doc["generated_reply"] = {
            **generated_reply,
            "body": _clean_incoming_email(generated_reply["body"]),
        }
    return doc


def _email_address(value: Any) -> str:
    return (parseaddr(str(value or ""))[1] or str(value or "")).strip().lower()


def _current_inbound_message_id(doc: Dict[str, Any]) -> str:
    return str(doc.get("latest_gmail_message_id") or doc.get("gmail_message_id") or "").strip()


async def _smtp_config(db: AsyncIOMotorDatabase) -> Optional[Dict[str, Any]]:
    from app.routes.inbox import _load_admin_settings

    settings_doc = await _load_admin_settings(db)
    return settings_doc.get("emailCfg") or None


class ApproveRequest(BaseModel):
    send_now: bool = True
    override_body: Optional[str] = None
    body: Optional[str] = None
    subject: Optional[str] = None


class RegenerateRequest(BaseModel):
    hint: Optional[str] = ""
    instruction: Optional[str] = ""


class ProcessPendingRequest(BaseModel):
    limit: int = 100


@router.get("")
async def list_inbox_emails(
    status: Optional[str] = Query(None),
    include_hidden: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query = _status_filter(status, include_hidden)

    total = await db["client_emails"].count_documents(query)
    skip = (page - 1) * limit
    pipeline = [
        {"$match": query},
        {
            "$addFields": {
                "_sort_received_at": {
                    "$switch": {
                        "branches": [
                            {
                                "case": {"$eq": [{"$type": "$received_at"}, "date"]},
                                "then": "$received_at",
                            },
                            {
                                "case": {"$eq": [{"$type": "$received_at"}, "string"]},
                                "then": {
                                    "$dateFromString": {
                                        "dateString": "$received_at",
                                        "onError": "$created_at",
                                        "onNull": "$created_at",
                                    }
                                },
                            },
                        ],
                        "default": "$created_at",
                    }
                }
            }
        },
        {"$sort": {"_sort_received_at": -1, "created_at": -1, "updated_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "_sort_received_at": 0,
            }
        },
    ]
    cursor = db["client_emails"].aggregate(pipeline)
    items = [_normalise_item_status(d) async for d in cursor]
    status_count = db["client_emails"].count_documents
    visible_base_query = _status_filter(None, False)
    visible_pending_query = _status_filter("pending_approval", False)
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "emails": items,
        "stats": {
            "today": await status_count({"$and": [visible_base_query, _today_query()]}),
            "pending_approval": await status_count(visible_pending_query),
            "auto_sent": await status_count({"$and": [visible_base_query, _count_status_query(["auto_sent"])]}),
            "sent": await status_count({"$and": [visible_base_query, _count_status_query(["sent"])]}),
            "approved": await status_count({"$and": [visible_base_query, _count_status_query(["approved"])]}),
            "rejected": await status_count({"$and": [visible_base_query, _count_status_query(["rejected"])]}),
            "spam": await status_count(_count_status_query(["spam"])),
            "office_replies": await status_count(_count_status_query(["office_reply", "routed_to_trainer_reply"])),
            "requirements_created": await status_count({"$and": [visible_base_query, {"requirement_id": {"$exists": True, "$nin": ["", None]}}]}),
            "total": await status_count(visible_base_query),
        },
    }


@router.post("/process-pending")
async def process_pending_inbox_emails(
    payload: ProcessPendingRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-run requirement extraction and trainer automation for stored client emails."""
    from app.routes.inbox import _process_pending_client_emails

    return {"success": True, **await _process_pending_client_emails(db, payload.limit)}


@router.post("/{email_id}/create-requirement")
async def create_requirement_from_inbox_email(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a requirement and shortlist from a single inbox email."""
    from app.routes.inbox import _process_client_requirement_email

    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")
    return {"success": True, **await _process_client_requirement_email(db, doc, force_new_requirement=True)}


@router.delete("/{email_id}", status_code=204)
async def delete_inbox_email(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    result = await db["client_emails"].update_one(
        {"email_id": email_id},
        {
            "$set": {
                "status": "deleted",
                "reply_status": "deleted",
                "deleted": True,
                "deleted_at": now,
                "updated_at": now,
                "processed": True,
            }
        },
    )
    if result.matched_count == 0:
        existing_deleted = await db["client_emails"].find_one(
            {
                "email_id": email_id,
                "$or": [
                    {"deleted": True},
                    {"status": "deleted"},
                    {"reply_status": "deleted"},
                ],
            },
            {"_id": 1},
        )
        if not existing_deleted:
            return


@router.post("/{email_id}/approve")
async def approve_inbox_reply(
    email_id: str,
    payload: ApproveRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Approve a pending auto-generated client reply and optionally send it."""
    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")

    reply_body = payload.override_body or payload.body or doc.get("ai_reply") or doc.get("draft_reply") or ""
    if not reply_body:
        raise HTTPException(400, "No reply body available to approve")

    now = datetime.utcnow()
    update: Dict[str, Any] = {
        "approved": True,
        "approved_at": now,
        "reply_status": "approved",
        "status": "approved",
        "updated_at": now,
    }

    if payload.send_now:
        to = _email_address(doc.get("from_email", ""))
        if not to:
            raise HTTPException(400, "No recipient address available")
        subject = payload.subject or doc.get("subject", "Re: Training Requirement")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        source_gmail_message_id = _current_inbound_message_id(doc)
        duplicate_markers = [{"source_email_id": email_id}]
        if source_gmail_message_id:
            duplicate_markers.append({"source_gmail_message_id": source_gmail_message_id})
        existing_sent_log = await db["email_logs"].find_one(
            {
                "mail_type": "client_reply",
                "status": "sent",
                "$and": [
                    {"$or": [{"recipient": to}, {"to_email": to}]},
                    {"$or": duplicate_markers},
                ],
            },
            {"_id": 0, "sent_at": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        if existing_sent_log:
            success, error = True, ""
            sent_at = existing_sent_log.get("sent_at") or existing_sent_log.get("created_at") or now
            message_id_header = existing_sent_log.get("gmail_message_id") or existing_sent_log.get("message_id_header") or ""
        else:
            message_id_header = generate_message_id()
            success, error = await send_email_async(
                to=to,
                subject=subject,
                body=reply_body,
                smtp_config=await _smtp_config(db),
                message_id_header=message_id_header,
            )
            sent_at = now
        if success:
            update["reply_sent"] = True
            update["reply_sent_at"] = sent_at
            update["reply_sent_for_message_id"] = source_gmail_message_id
            update["reply_status"] = "sent"
            update["status"] = "sent"
            # Log outbound reply
            if not existing_sent_log:
                await db["email_logs"].insert_one({
                    "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
                    "direction": "outbound",
                    "recipient": to,
                    "to_email": to,
                    "subject": subject,
                    "gmail_message_id": message_id_header,
                    "message_id_header": message_id_header,
                    "body": reply_body,
                    "body_snippet": reply_body[:300],
                    "status": "sent",
                    "mail_type": "client_reply",
                    "requirement_id": doc.get("requirement_id"),
                    "source_email_id": email_id,
                    "source_gmail_message_id": source_gmail_message_id,
                    "sent_at": now,
                    "created_at": now,
                    "updated_at": now,
                })
            if doc.get("pending_trainer_automation") or doc.get("client_authorized_trainer_search"):
                try:
                    from app.routes.inbox import _start_trainer_search_after_client_reply

                    automation_update = await _start_trainer_search_after_client_reply(db, doc)
                    update.update(automation_update)
                except Exception as exc:
                    logger.exception("Trainer automation failed after client reply for %s", email_id)
                    update.update({
                        "status": "trainer_email_failed",
                        "trainer_automation_status": "failed",
                        "trainer_automation_error": str(exc),
                        "trainer_automation_failed_at": now,
                    })
        else:
            update["reply_status"] = "send_failed"
            update["status"] = "send_failed"
            update["reply_sent"] = False
            update["reply_error"] = error

    await db["client_emails"].update_one({"email_id": email_id}, {"$set": update})
    return {
        "success": True,
        "email_id": email_id,
        "status": update["status"],
        "reply_status": update["reply_status"],
        "trainer_automation_status": update.get("trainer_automation_status"),
        "mail_automation": update.get("mail_automation"),
    }


@router.post("/{email_id}/reject")
async def reject_inbox_reply(
    email_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Reject a pending auto-generated reply (marks it as discarded)."""
    result = await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {"status": "rejected", "reply_status": "rejected", "approved": False, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Inbox email not found")
    return {"success": True, "email_id": email_id, "reply_status": "rejected"}


@router.post("/{email_id}/regenerate-reply")
async def regenerate_reply(
    email_id: str,
    payload: RegenerateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Re-generate an AI reply for a client email using Anthropic/Gemini."""
    doc = await db["client_emails"].find_one({"email_id": email_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Inbox email not found")

    body = _clean_incoming_email(doc.get("clean_body") or doc.get("body") or doc.get("raw_body") or "")
    subject = doc.get("subject", "")
    hint = payload.hint or payload.instruction or ""

    classification = doc.get("email_classification") or classify_email(
        subject=subject,
        body=body,
        sender_email=doc.get("from_email") or doc.get("sender") or "",
        sender_name=doc.get("from_name") or "",
    )
    extracted = doc.get("extracted") if isinstance(doc.get("extracted"), dict) else {}
    reference_reply = build_auto_reply(
        classification=classification,
        extracted=extracted,
        subject=subject,
        sender_name=doc.get("from_name") or "",
    )
    workflow_context = await _load_reply_workflow_context(db, doc, classification, extracted, body)
    if workflow_context.get("lab_cost"):
        reference_reply = _build_lab_reference_reply(
            workflow_context["lab_cost"],
            extracted,
            doc.get("from_name") or "",
            subject,
        )

    new_reply = await _ai_draft_reply(
        subject=subject,
        body=body,
        hint=hint,
        workflow_context=workflow_context,
        reference_reply=reference_reply,
    )

    now = datetime.utcnow()
    generated_reply = {
        "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
        "body": new_reply,
    }
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$set": {
            "ai_reply": new_reply,
            "draft_reply": new_reply,
            "generated_reply": generated_reply,
            "status": "pending_approval",
            "reply_status": "pending_review",
            "regenerated_at": now,
            "updated_at": now,
        }},
    )
    return {"success": True, "email_id": email_id, "reply": new_reply, "generated_reply": generated_reply}


def _clean_incoming_email(value: Any) -> str:
    """Normalize common HTML and escape artifacts before drafting."""
    text = html.unescape(str(value or ""))
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(?:p|div|li)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pick(source: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {key: source[key] for key in keys if source.get(key) not in (None, "", [], {})}


def _lab_request_context(body: str, extracted: Dict[str, Any]) -> Dict[str, Any]:
    lower = body.lower()
    is_lab_request = bool(re.search(r"\blab(?:oratory)?\s+(?:access|cost|charges?|setup|environment)\b", lower))
    lab_only = is_lab_request and bool(re.search(r"\b(?:lab\s+access\s+only|only\s+lab|without\s+(?:a\s+)?trainer)\b", lower))
    if not is_lab_request:
        return {}
    known_inputs = _pick(extracted, [
        "technology", "technology_needed", "duration_days", "duration_hours", "participant_count",
    ])
    duration_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:working\s+)?days?\b", lower)
    hours_per_day_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per\s+day|daily|/\s*day)\b", lower)
    total_hours_match = re.search(
        r"\b(?:total(?:\s+lab)?(?:\s+usage)?\s*[:=-]?\s*)(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b"
        r"|\b(\d+(?:\.\d+)?)\s*(?:total\s+)(?:hours?|hrs?)\b",
        lower,
    )
    participants_match = re.search(r"\b(\d+)\s*(?:participants?|learners?|users?|employees?|students?)\b", lower)
    if duration_match and not known_inputs.get("duration_days"):
        known_inputs["duration_days"] = float(duration_match.group(1))
    if hours_per_day_match:
        known_inputs["hours_per_day"] = float(hours_per_day_match.group(1))
    if total_hours_match:
        known_inputs["total_hours"] = float(total_hours_match.group(1) or total_hours_match.group(2))
    if participants_match and not known_inputs.get("participant_count"):
        known_inputs["participant_count"] = int(participants_match.group(1))
    providers = []
    if re.search(r"\baws\b", lower):
        providers.append("AWS")
    if re.search(r"\bazure\b", lower):
        providers.append("Azure")
    if re.search(r"\b(?:gcp|google\s+cloud)\b", lower):
        providers.append("GCP")
    if providers:
        known_inputs["cloud_provider"] = " and ".join(providers)
    cluster_requested = bool(re.search(r"\bclusters?\b|\bkubernetes\b|\bk8s\b", lower))
    cluster_count_match = re.search(r"\b(\d+)\s+(?:kubernetes\s+|k8s\s+)?clusters?\b", lower)
    if cluster_count_match:
        known_inputs["cluster_count"] = int(cluster_count_match.group(1))
    required_inputs = ["cloud_provider", "participant_count", "hours_per_day", "duration_days"]
    if cluster_requested:
        required_inputs.append("cluster_count")
    return {
        "feature": "lab_cost",
        "request_type": "lab_access_only" if lab_only else "training_with_lab_support",
        "available": True,
        "known_inputs": known_inputs,
        "required_quote_inputs": required_inputs,
        "missing_quote_inputs": [key for key in required_inputs if not known_inputs.get(key)],
        "pricing_rule": (
            "Do not invent or estimate a total. Ask only for required quote inputs that are genuinely missing. "
            "If all inputs are present but no approved calculated total is in workflow context, state that the "
            "lab-cost workbook or quote will be generated and confirmed after review."
        ),
    }


def _build_lab_reference_reply(
    lab_context: Dict[str, Any],
    extracted: Dict[str, Any],
    sender_name: str,
    subject: str,
) -> Dict[str, Any]:
    known = lab_context.get("known_inputs") or {}
    missing = lab_context.get("missing_quote_inputs") or []
    client = str(extracted.get("client_name") or sender_name or "Client").strip().split()[0]
    request_type = lab_context.get("request_type")
    intro = "Thank you for sharing your lab-access requirement."
    noted = []
    def quantity(value: Any) -> str:
        try:
            number = float(value)
            return str(int(number)) if number.is_integer() else str(number)
        except (TypeError, ValueError):
            return str(value)

    technology = extracted.get("technology_needed") or extracted.get("technology")
    if technology:
        noted.append(f"technology: {technology}")
    if known.get("duration_days"):
        noted.append(f"duration: {quantity(known['duration_days'])} days")
    if known.get("hours_per_day"):
        noted.append(f"access: {quantity(known['hours_per_day'])} hours per day")
    if known.get("total_hours"):
        noted.append(f"total usage: {quantity(known['total_hours'])} hours")
    if known.get("cloud_provider"):
        noted.append(f"cloud provider: {str(known['cloud_provider']).upper()}")

    paragraphs = [f"Dear {client},", intro]
    if noted:
        paragraphs.append("We have noted " + ", ".join(noted) + ".")
    if missing:
        labels = {
            "cloud_provider": "preferred cloud provider (AWS, Azure, or GCP)",
            "participant_count": "number of participants/users requiring access",
            "hours_per_day": "required lab-access hours per day",
            "duration_days": "number of access days",
            "cluster_count": "number and required configuration of Kubernetes clusters",
        }
        requested = [labels[item] for item in missing if item in labels]
        paragraphs.append(
            "To prepare the exact total lab-cost quote, please confirm " + ", and ".join(requested) + "."
        )
    else:
        paragraphs.append(
            "We will generate and review the lab-cost calculation using these inputs and share the confirmed total quote, including applicable charges."
        )
    if request_type == "lab_access_only":
        paragraphs.append("We have treated this as a lab-access-only request and not as a trainer requirement.")
    paragraphs.append("Best Regards,\nRecruitment Team\nClahan Technologies")
    return {
        "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
        "body": "\n\n".join(paragraphs),
        "template_key": "client_lab_cost_grounded",
        "auto_send_safe": False,
    }


def _client_document_delivery_context(doc: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    requested = [str(item).strip() for item in (extracted.get("requested_details") or []) if str(item).strip()]
    attachment_names = list(doc.get("attachment_names") or extracted.get("attachment_names") or [])
    for item in doc.get("attachments") or extracted.get("source_attachments") or []:
        if isinstance(item, dict) and item.get("filename"):
            attachment_names.append(str(item["filename"]))
    combined = "\n".join([*requested, *attachment_names]).lower()
    if re.search(r"\b(?:xlsx|xls|excel|spreadsheet)\b", combined) or any(
        name.lower().endswith((".xlsx", ".xls")) for name in attachment_names
    ):
        toc_format = "xlsx"
    elif re.search(r"\b(?:pdf|docx|doc|word document)\b", combined) or any(
        name.lower().endswith((".pdf", ".docx", ".doc")) for name in attachment_names
    ):
        toc_format = "detailed_pdf"
    else:
        toc_format = "detailed_pdf"
    return {
        "client_reference_attachments": attachment_names,
        "toc_requested": bool(extracted.get("toc_requested")),
        "toc_action": extracted.get("toc_action") or "",
        "preferred_toc_output": toc_format,
        "format_rule": (
            "Preserve the client's supplied TOC structure and output family when a reference is present. "
            "Excel references use the compact Day/Module/Duration plus Module/Topics workbook. "
            "Word or PDF references use the detailed client-ready programme document."
        ),
        "single_email_rule": (
            "When the client requests several deliverables, one reply may list them together, but claim a file is "
            "attached only when the current send operation actually includes it. State unavailable or pending items separately."
        ),
        "lab_cost_rule": (
            "Lab cost is a separate reviewed deliverable. Never attach or quote a workbook generated from default, "
            "placeholder, inferred, or unapproved rates."
        ),
    }


async def _load_reply_workflow_context(
    db: AsyncIOMotorDatabase,
    doc: Dict[str, Any],
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    body: str,
) -> Dict[str, Any]:
    """Load bounded, non-secret workflow facts used to ground an email draft."""
    requirement_id = str(doc.get("requirement_id") or "").strip()
    requirement: Dict[str, Any] = {}
    shortlist: Dict[str, Any] = {}
    toc: Dict[str, Any] = {}
    purchase_order: Dict[str, Any] = {}
    invoice: Dict[str, Any] = {}
    recent_client_replies: List[str] = []
    if requirement_id:
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        toc = await db["toc_generations"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0},
            sort=[("created_at", -1)],
        ) or {}
        purchase_order = await db["purchase_orders"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0},
            sort=[("created_at", -1)],
        ) or {}
        invoice = await db["invoices"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0},
            sort=[("created_at", -1)],
        ) or {}

    # Give the writer a small amount of real conversation history. This prevents
    # the same client from receiving near-identical acknowledgements repeatedly.
    sender_email = _email_address(doc.get("from_email"))
    if sender_email:
        reply_cursor = db["client_emails"].find(
            {
                "from_email": {"$regex": re.escape(sender_email), "$options": "i"},
                "reply_sent": True,
                "email_id": {"$ne": doc.get("email_id")},
            },
            {
                "_id": 0,
                "sent_reply_body": 1,
                "ai_reply": 1,
                "draft_reply": 1,
                "generated_reply.body": 1,
            },
        ).sort("reply_sent_at", -1).limit(3)
        async for prior in reply_cursor:
            prior_reply = (
                prior.get("sent_reply_body")
                or prior.get("ai_reply")
                or prior.get("draft_reply")
                or (prior.get("generated_reply") or {}).get("body")
                or ""
            )
            if str(prior_reply).strip():
                recent_client_replies.append(str(prior_reply).strip()[:900])

    trainer_summaries = []
    for trainer in (shortlist.get("top_trainers") or [])[:10]:
        if isinstance(trainer, dict):
            trainer_summaries.append(_pick(trainer, [
                "trainer_id", "name", "status", "availability", "interview_status",
                "client_status", "commercial_status", "last_mail_type",
            ]))

    return {
        "classification": _pick(classification, [
            "person_type", "scenario", "urgency", "sentiment", "requires_human", "auto_reply_allowed",
        ]),
        "email_workflow": _pick(doc, [
            "status", "reply_status", "office_mail_category", "source_outbound_mail_type",
            "requirement_id", "trainer_id", "reply_template_key", "pending_trainer_automation",
            "client_authorized_trainer_search", "meeting_status", "interview_status",
        ]),
        "extracted_request": _pick(extracted, [
            "client_name", "company_name", "technology", "technology_needed", "duration_text",
            "duration_days", "duration_hours", "training_dates", "preferred_dates", "timing", "mode",
            "location", "participant_count", "audience_level", "budget_range", "budget_total",
            "budget_per_day", "currency", "requested_details", "clahan_managed_details",
            "needs_clarification", "latest_coordination_intent", "toc_requested", "toc_action",
            "scope_attached", "attachment_names", "source_attachments",
        ]),
        "requirement": _pick(requirement, [
            "requirement_id", "status", "technology", "technology_needed", "duration_days", "duration_hours",
            "training_dates", "preferred_dates", "timing", "mode", "location", "participant_count",
            "audience_level", "budget_range", "budget_total", "budget_per_day", "currency",
            "client_name", "company_name", "workflow_stage", "shortlist_status", "interview_status",
            "selected_trainer_id", "commercial_status", "payment_status", "toc_status", "lab_cost",
        ]),
        "shortlist": {
            **_pick(shortlist, ["status", "workflow_stage", "client_status", "selected_trainer_id"]),
            "trainer_count": len(shortlist.get("top_trainers") or []),
            "trainers": trainer_summaries,
        } if shortlist else {},
        "business_features": {
            "training_requirement": {
                "exists": bool(requirement),
                **_pick(requirement, ["status", "workflow_stage", "training_dates", "timing", "mode"]),
            },
            "trainer_profiles": {
                "available_count": len(shortlist.get("top_trainers") or []),
                "selected_trainer_id": shortlist.get("selected_trainer_id") or requirement.get("selected_trainer_id") or "",
                "rule": "Claim a profile/CV was shared or attached only when workflow state explicitly confirms it.",
            },
            "toc": {
                "exists": bool(toc),
                **_pick(toc, ["toc_id", "domain", "duration_days", "trainer_name", "created_at", "status", "sent_at"]),
                "rule": "A TOC-generation feature existing is not proof that a TOC PDF was attached or sent.",
            },
            "purchase_order": {
                "exists": bool(purchase_order),
                **_pick(purchase_order, ["po_id", "po_number", "status", "total_amount", "created_at", "sent_at"]),
            },
            "invoice": {
                "exists": bool(invoice),
                **_pick(invoice, [
                    "invoice_id", "invoice_number", "status", "invoice_date", "due_date",
                    "total_amount", "balance_due", "created_at", "sent_at",
                ]),
                "rule": "Claim an invoice PDF is available or sent only when this record and status support that claim.",
            },
            "documents_and_pdfs": {
                "generation_available": True,
                "rule": (
                    "The application can generate TOC, trainer-profile, PO, and invoice documents. Lab cost is available "
                    "only through its reviewed workflow. Feature availability alone never proves a particular file has "
                    "been generated, attached, or sent."
                ),
            },
        },
        "document_delivery": _client_document_delivery_context(doc, extracted),
        "lab_cost": _lab_request_context(body, extracted),
        "recent_replies_to_this_sender": recent_client_replies,
    }


def _client_auto_reply_template() -> str:
    return (
        "Dear Client,\n\n"
        "Thank you for sharing your training requirement.\n\n"
        "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
        "* Training duration\n"
        "* Preferred training dates\n"
        "* Daily training timings\n"
        "* Audience level (Beginner / Intermediate / Advanced)\n"
        "* Training mode (Online / Offline / Hybrid)\n"
        "* Budget or expected commercial charges per day/session\n\n"
        "Meanwhile, we will begin an initial trainer search based on the information currently available. "
        "Once we receive the above details, we will refine the shortlist and share the most relevant trainer profiles for your review.\n\n"
        "We look forward to your response.\n\n"
        "Best Regards,\n"
        "Recruitment Team\n"
        "Clahan Technologies"
    )


async def _ai_draft_reply(
    subject: str,
    body: str,
    hint: str = "",
    workflow_context: Optional[Dict[str, Any]] = None,
    reference_reply: Optional[Dict[str, Any]] = None,
    require_openai: bool = False,
) -> str:
    """Generate a client reply when LLM email drafting is enabled; otherwise use template."""
    from app.config import get_settings
    cfg = get_settings()

    template = _client_auto_reply_template()
    grounded_reference = (reference_reply or {}).get("body") or template
    if not bool(getattr(cfg, "USE_LLM_FOR_EMAILS", False)):
        return "" if require_openai else grounded_reference

    context_json = json.dumps(workflow_context or {}, ensure_ascii=False, default=str, separators=(",", ":"))
    prompt = (
        f"Workflow context (authoritative JSON):\n{context_json[:12000]}\n\n"
        f"Deterministic workflow reply (safe reference):\n{grounded_reference[:4000]}\n\n"
        f"Incoming email subject:\n{subject}\n\n"
        f"Incoming email body:\n{body[:6000]}"
        + (f"\n\nAdditional instruction:\n{hint}" if hint else "")
    )

    openai_key = cfg.OPENAI_API_KEY.strip()
    if bool(getattr(cfg, "USE_OPENAI_FOR_EMAILS", False)) and openai_key:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=openai_key)
            response = await client.responses.create(
                model=cfg.OPENAI_MODEL or "gpt-5.5",
                reasoning={"effort": "low"},
                text={"verbosity": "low"},
                instructions=(
                    f"You are a professional training coordinator at {cfg.FROM_NAME or 'Clahan Technologies'}. "
                    "Write in the same simple coordinator style used in Clahan/Hostinger sent replies: concise "
                    "acknowledgement, clear next step, ordinary business wording, and a direct close. Phrases such "
                    "as 'Thank you for sharing', 'To proceed further', 'kindly share', 'we will share it with you "
                    "once received', and 'for your review' are acceptable when they fit the scenario. Do not make "
                    "the mail sound like a chatbot, CRM note, or fixed template. Match the sender's level of "
                    "formality without copying their mistakes. Vary sentence openings and rhythm enough that "
                    "repeated client replies do not look cloned. Do not paraphrase or list back dates, times, durations, technologies, "
                    "or other details the sender has already supplied merely to prove that they were read. For a "
                    "new training requirement, acknowledge it in one sentence and lead with the concrete next step "
                    "(for example, reviewing suitable trainer options and reverting with the requested information). "
                    "Sound like an experienced account manager writing personally after reading the email, not an "
                    "automated workflow or ticketing system. Avoid phrases such as 'our system', 'the workflow', "
                    "'the proposed programme', or 'once validated'. Do not narrate internal processing. A strong client acknowledgement should "
                    "read like a brief personal note: thank them for a clear brief, explain what the next response "
                    "will contain, and close with confidence. "
                    "For a detailed corporate-training request, write a complete acknowledgement of roughly 180-300 "
                    "words when the sender has asked for several deliverables: state that trainer options are being "
                    "reviewed, group the deliverables the client will receive, and explain the next confirmation step. "
                    "Keep a simple question to "
                    "roughly 60-100 words. Use 140-250 words only when several facts, questions, or next steps must be "
                    "covered. Prefer short paragraphs; use bullets only when they make three or more items clearer. "
                    "Address the sender by their reliable name when available. For ordinary client and trainer "
                    "emails, prefer the natural greeting 'Hi <name>'; use 'Hi Team' when no reliable name is available. "
                    "Produce the most accurate client-facing reply for the current workflow stage. Treat the "
                    "workflow JSON and incoming email as authoritative facts. Use the deterministic workflow "
                    "reply only as a safety and business-rule reference; write a fresh, natural reply instead of "
                    "copying its wording or structure. Make the reply specific by acknowledging the relevant facts "
                    "the sender provided, while avoiding unnecessary repetition. Answer each legitimate question "
                    "that the context actually resolves. If recent_replies_to_this_sender is present, it contains "
                    "messages already sent to this client. Do not reuse their opening, sentence sequence, closing, "
                    "or distinctive phrases. Preserve the business meaning but choose a clearly different natural "
                    "voice and structure for this reply. "
                    "Never invent "
                    "prices, dates, availability, policies, names, attachments, actions, approvals, statuses, or "
                    "commitments. Never claim an action was completed merely because the application has a feature "
                    "for it. Check business_features before discussing training requirements, trainer profiles/CVs, "
                    "TOCs, proposals/PDFs, purchase orders, invoices, or other generated documents. If a feature "
                    "record exists, accurately state its verified status; if it does not exist, describe the next "
                    "review/generation step without claiming completion. If a requested value is missing, ask only "
                    "for the smallest necessary missing input or "
                    "state the exact item the team must confirm. Distinguish lab-access-only requests from training "
                    "or trainer requirements and obey any lab_cost pricing_rule in context. Do not use exaggerated "
                    "sales language, filler, emojis, or claims such as best-in-class. Do not ask again for "
                    "facts already present. For suspicious, system, legal, security, or human-review scenarios, "
                    "write only a cautious acknowledgement for manual review. End with 'Best Regards', followed by "
                    "'Recruitment Team' and 'Clahan Technologies'. Return only the email body with no subject line."
                ),
                input=prompt,
                max_output_tokens=600,
            )
            generated = response.output_text.strip()
            if generated:
                return generated
            logger.warning("OpenAI returned an empty mail draft; trying fallback provider")
        except Exception as exc:
            logger.warning("OpenAI mail generation failed: %s", exc)

    if require_openai:
        logger.warning("OpenAI generation required but no usable OpenAI output was produced")
        return ""

    key = cfg.ANTHROPIC_API_KEY.strip() if hasattr(cfg, "ANTHROPIC_API_KEY") else ""
    if key:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=key)
            anthropic_prompt = (
                f"You are a professional training coordinator at {cfg.FROM_NAME or 'TrainerSync'}. "
                "Draft a concise reply grounded only in the supplied workflow context and email. "
                "Do not invent prices, availability, actions, or policy. Use the deterministic reply as a safe baseline.\n\n"
                f"Workflow context:\n{context_json[:12000]}\n\n"
                f"Deterministic reply:\n{grounded_reference[:4000]}\n\n"
                f"Subject: {subject}\nBody: {body[:6000]}"
                + (f"\n\nHint: {hint}" if hint else "")
                + "\n\nReturn only the reply body, no subject line."
            )
            model_name = getattr(cfg, "ANTHROPIC_MODEL", "claude-haiku-4-20250514") or "claude-haiku-4-20250514"
            msg = await client.messages.create(
                model=model_name,
                max_tokens=600,
                temperature=0.4,
                messages=[{"role": "user", "content": anthropic_prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        except Exception as exc:
            logger.warning("AI reply generation failed: %s", exc)

    # Fallback template
    return grounded_reference
