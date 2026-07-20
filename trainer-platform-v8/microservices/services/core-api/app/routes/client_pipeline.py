"""Client pipeline — view all active requirements with their trainer pipeline."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


CLIENT_MESSAGE_LABELS = {
    "client_request": "Client Request",
    "calhan_reply": "Clahan Reply",
    "client_slots": "Client Slots Sent",
    "client_slot_reply": "Client Slot Reply",
    "client_confirmation": "Client Confirmation",
    "client_interview_schedule": "Interview Schedule",
    "client_toc_details_request": "TOC Details Request",
    "client_toc": "TOC Sent",
    "client_budget_revision_request": "Budget Revision",
    "client_po_request": "PO Request",
    "client_po": "Client PO",
    "invoice": "Invoice",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _message_time(doc: Dict[str, Any]) -> Any:
    return (
        doc.get("sent_at")
        or doc.get("received_at")
        or doc.get("created_at")
        or doc.get("updated_at")
    )


def _message_direction(doc: Dict[str, Any], client_email: str = "") -> str:
    direction = _clean(doc.get("direction")).lower()
    if direction in {"inbound", "received"}:
        return "received"
    if direction in {"outbound", "sent"}:
        return "sent"

    from_email = _clean(doc.get("from_email") or doc.get("sender") or doc.get("sender_email")).lower()
    to_email = _clean(doc.get("to_email") or doc.get("recipient") or doc.get("recipient_email")).lower()
    if client_email:
        if from_email == client_email:
            return "received"
        if to_email == client_email:
            return "sent"

    mail_type = _clean(doc.get("mail_type")).lower()
    if mail_type in {"client_request", "client_slot_reply", "client_confirmation", "client_po"}:
        return "received"
    if mail_type.startswith("client_"):
        return "sent"
    if _clean(doc.get("status")).lower() == "sent":
        return "sent"
    return "sent"


def _message_label(doc: Dict[str, Any]) -> str:
    mail_type = _clean(doc.get("mail_type")).lower()
    if mail_type in CLIENT_MESSAGE_LABELS:
        return CLIENT_MESSAGE_LABELS[mail_type]
    if mail_type.startswith("client_"):
        return mail_type.replace("_", " ").title()
    return doc.get("subject") or "Client Message"


def _timeline_message(doc: Dict[str, Any], client_email: str = "") -> Dict[str, Any]:
    body = doc.get("body") or doc.get("body_snippet") or doc.get("reply_text") or doc.get("message") or ""
    return {
        "type": doc.get("mail_type") or doc.get("type") or "email",
        "label": _message_label(doc),
        "direction": _message_direction(doc, client_email),
        "status": doc.get("status") or "",
        "subject": doc.get("subject") or "",
        "body": body,
        "at": _message_time(doc),
        "email_id": doc.get("email_id") or doc.get("message_id") or "",
    }


def _preview_from_message(message: Dict[str, Any]) -> str:
    return _clean(message.get("body") or message.get("subject"))[:220]


def _message_dedupe_key(message: Dict[str, Any]) -> str:
    body = _clean(message.get("body")).lower()
    subject = _clean(message.get("subject")).lower()
    return "|".join([
        _clean(message.get("direction")).lower(),
        _clean(message.get("type")).lower(),
        subject,
        body[:500],
    ])


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = _clean(value)
    if not text:
        return datetime.min
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _is_client_conversation_log(log: Dict[str, Any], client_email: str) -> bool:
    mail_type = _clean(log.get("mail_type")).lower()
    if mail_type.startswith("trainer_"):
        return False
    if mail_type.startswith("client_"):
        return True
    if mail_type in {"commercial_negotiation", "trainer_commercials_to_client"}:
        return True
    from_email = _clean(log.get("from_email") or log.get("sender") or log.get("sender_email")).lower()
    to_email = _clean(log.get("to_email") or log.get("recipient") or log.get("recipient_email")).lower()
    if client_email and (from_email == client_email or to_email == client_email):
        return True
    return False


def _subject_family(value: Any) -> str:
    subject = _clean(value).lower()
    while subject.startswith("re:"):
        subject = subject[3:].strip()
    while subject.startswith("fwd:"):
        subject = subject[4:].strip()
    return " ".join(subject.split())


def _collapse_repeated_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    collapsed: List[Dict[str, Any]] = []
    for message in messages:
        if collapsed:
            previous = collapsed[-1]
            same_speaker = previous.get("direction") == message.get("direction")
            same_subject = _subject_family(previous.get("subject")) == _subject_family(message.get("subject"))
            same_type = _clean(previous.get("type")).lower() == _clean(message.get("type")).lower()
            if same_speaker and (same_subject or same_type):
                previous_body = _clean(previous.get("body"))
                current_body = _clean(message.get("body"))
                if len(current_body) > len(previous_body):
                    collapsed[-1] = message
                continue
        collapsed.append(message)
    return collapsed


async def _client_timeline(
    db: AsyncIOMotorDatabase,
    req_id: str,
    req: Dict[str, Any],
    client_po: Dict[str, Any],
    invoice: Dict[str, Any],
) -> Dict[str, Any]:
    client_email = _clean(req.get("client_email")).lower()
    logs = await (
        db["email_logs"]
        .find({"requirement_id": req_id}, {"_id": 0})
        .sort("created_at", 1)
        .limit(200)
        .to_list(200)
    )

    messages: List[Dict[str, Any]] = []
    seen = set()
    for log in logs:
        if _clean(log.get("requirement_id")) != req_id:
            continue
        if not _is_client_conversation_log(log, client_email):
            continue
        message = _timeline_message(log, client_email)
        key = _message_dedupe_key(message)
        if key in seen:
            continue
        seen.add(key)
        messages.append(message)

    if client_po:
        messages.append({
            "type": "client_po",
            "label": "Client PO",
            "direction": "received",
            "status": client_po.get("status") or "received",
            "subject": client_po.get("client_po_number") or client_po.get("po_number") or "Client PO received",
            "body": client_po.get("notes") or client_po.get("client_po_notes") or "",
            "at": client_po.get("received_at") or client_po.get("created_at") or client_po.get("updated_at"),
        })

    if invoice:
        messages.append({
            "type": "invoice",
            "label": "Invoice",
            "direction": "sent" if invoice.get("status") == "sent" else "system",
            "status": invoice.get("status") or "",
            "subject": invoice.get("invoice_number") or "Invoice generated",
            "body": invoice.get("notes") or "",
            "at": invoice.get("sent_at") or invoice.get("created_at") or invoice.get("updated_at"),
        })

    messages.sort(key=lambda item: _parse_time(item.get("at")))
    messages = _collapse_repeated_turns(messages)
    last_preview = ""
    for message in reversed(messages):
        last_preview = _preview_from_message(message)
        if last_preview:
            break
    return {"messages": messages, "last_preview": last_preview}


@router.get("")
async def get_client_pipeline(
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=200),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Aggregate view of requirements with their shortlist/trainer pipeline info.
    Mirrors the monolith's GET /client-pipeline endpoint.
    """
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    else:
        # Default: active requirements
        query["status"] = {"$nin": ["closed", "fulfilled", "cancelled"]}

    effective_page_size = min(limit or page_size, 200)
    total = await db["requirements"].count_documents(query)
    skip = (page - 1) * effective_page_size
    requirements = await (
        db["requirements"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(effective_page_size)
        .to_list(effective_page_size)
    )

    # Enrich each requirement with its shortlist entry
    result: List[Dict[str, Any]] = []
    for req in requirements:
        req_id = req.get("requirement_id") or str(req.get("_id", ""))
        shortlist = await db["shortlists"].find_one(
            {"requirement_id": req_id}, {"_id": 0}
        ) or {}
        top_trainers: List[Dict[str, Any]] = shortlist.get("top_trainers") or []
        selected_trainer_id = (
            shortlist.get("selected_trainer_id")
            or req.get("selected_trainer_id")
            or ""
        )
        selected_trainer = next(
            (trainer for trainer in top_trainers if trainer.get("trainer_id") == selected_trainer_id),
            None,
        )
        if not selected_trainer and selected_trainer_id:
            selected_trainer = await db["trainers"].find_one(
                {"trainer_id": selected_trainer_id}, {"_id": 0}
            )
        if not selected_trainer and shortlist.get("selected_trainer_name"):
            selected_trainer = {
                "trainer_id": selected_trainer_id,
                "name": shortlist.get("selected_trainer_name"),
            }

        client_po = await db["purchase_orders"].find_one(
            {"requirement_id": req_id}, {"_id": 0}, sort=[("created_at", -1)]
        ) or {}
        invoice = await db["invoices"].find_one(
            {"requirement_id": req_id}, {"_id": 0}, sort=[("created_at", -1)]
        ) or {}
        timeline = await _client_timeline(db, req_id, req, client_po, invoice)

        # Summarise pipeline stage counts
        stage_counts: Dict[str, int] = {}
        for t in top_trainers:
            stage = t.get("pipeline_status") or t.get("status") or "unknown"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        public_top_trainers = [
            {
                key: trainer.get(key)
                for key in (
                    "trainer_id",
                    "name",
                    "trainer_name",
                    "email",
                    "trainer_email",
                    "match_score",
                    "pipeline_status",
                    "status",
                    "rank",
                    "experience_years",
                    "technologies",
                    "technology_category",
                    "location",
                    "last_mail_type",
                    "last_mailed_at",
                    "last_mail_error",
                )
                if trainer.get(key) is not None
            }
            for trainer in top_trainers[:10]
        ]

        item = {
            **req,
            "client": {
                "name": req.get("client_name") or req.get("client_company") or "",
                "company": req.get("client_company") or req.get("client_name") or "",
                "email": req.get("client_email") or "",
            },
            "client_po": client_po,
            "invoice": invoice,
            "selected_trainer": selected_trainer or {},
            "shortlist": {
                "total_trainers": len(top_trainers),
                "top_trainers": public_top_trainers,
                "stage_counts": stage_counts,
                "selected_trainer_id": selected_trainer_id,
                "selected_trainer_name": shortlist.get("selected_trainer_name") or (selected_trainer or {}).get("name"),
                "selection_status": shortlist.get("selection_status"),
            },
            "top_trainers": public_top_trainers,
            "messages": timeline["messages"],
            "last_preview": timeline["last_preview"],
        }
        if q:
            haystack = " ".join(
                str(value or "")
                for value in (
                    req_id,
                    item.get("technology_needed"),
                    item.get("domain"),
                    item["client"].get("name"),
                    item["client"].get("company"),
                    item["client"].get("email"),
                    client_po.get("po_number"),
                    client_po.get("client_po_number"),
                    invoice.get("invoice_number"),
                    (selected_trainer or {}).get("name"),
                )
            ).lower()
            if q.lower() not in haystack:
                continue
        result.append(item)

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": effective_page_size,
        "pages": max(1, (total + effective_page_size - 1) // effective_page_size),
        "pipeline": result,
    }
