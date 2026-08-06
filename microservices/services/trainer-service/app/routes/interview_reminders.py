"""Interview reminder scheduling — create, list, cancel, reschedule."""
import logging
import re
import uuid
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db

schedules_router = APIRouter()
router = APIRouter()
logger = logging.getLogger(__name__)


class ScheduleReminderRequest(BaseModel):
    email_id: str
    trainer_id: Optional[str] = ""
    trainer_name: Optional[str] = ""
    trainer_phone: Optional[str] = ""
    trainer_email: Optional[str] = ""
    requirement_id: Optional[str] = ""
    technology: Optional[str] = ""
    interview_at: str  # ISO datetime string
    platform: Optional[str] = "Online"
    interview_link: Optional[str] = ""
    reminder_hours_before: int = 1


class RescheduleRequest(BaseModel):
    new_interview_at: str
    interview_link: Optional[str] = ""


class InterviewNotesRequest(BaseModel):
    schedule_key: str
    transcript: str
    trainer_name: Optional[str] = ""
    trainer_email: Optional[str] = ""
    client_name: Optional[str] = ""
    client_email: Optional[str] = ""
    domain: Optional[str] = ""
    meeting_link: Optional[str] = ""
    meeting_time: Optional[str] = ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_interview_date_text(value: Any) -> Dict[str, str]:
    text = _clean(value)
    if not text:
        return {}
    normalized = re.sub(r"\*\*", "", text)
    normalized = re.sub(r"\bInterview Date\s*&\s*Time\b\s*:?", "", normalized, flags=re.I).strip()
    match = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b[^0-9]*"
        r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?"
        r"(?:\s*[-–—]\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?)?",
        normalized,
        flags=re.I,
    )
    if not match:
        return {}

    day = int(match.group(1))
    month = int(match.group(2))
    year = int(f"20{match.group(3)}") if len(match.group(3)) == 2 else int(match.group(3))

    def build(hour_text: str, minute_text: Optional[str], meridiem_text: Optional[str], fallback_meridiem: str = "") -> datetime:
        hour = int(hour_text)
        minute = int(minute_text or 0)
        meridiem = _clean(meridiem_text or fallback_meridiem).upper()
        if meridiem == "PM" and hour < 12:
            hour += 12
        if meridiem == "AM" and hour == 12:
            hour = 0
        return datetime(year, month, day, hour, minute)

    start_meridiem = match.group(6) or match.group(9) or ""
    start = build(match.group(4), match.group(5), start_meridiem)
    end = None
    if match.group(7):
        end = build(match.group(7), match.group(8), match.group(9), start_meridiem)
        if end <= start:
            end += timedelta(hours=12)
    return {
        "start_iso": start.isoformat(),
        "end_iso": end.isoformat() if end else "",
        "timezone": "Asia/Kolkata",
        "date_time_text": normalized,
    }


def _with_meeting_start_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    raw_start = normalized.get("interview_at") or normalized.get("start_iso")
    if isinstance(raw_start, datetime):
        normalized["start_iso"] = raw_start.isoformat()
    elif raw_start:
        normalized["start_iso"] = _clean(raw_start)
    else:
        parsed = _parse_interview_date_text(normalized.get("date_time_text") or normalized.get("interview_date"))
        normalized.update({k: v for k, v in parsed.items() if v})
    normalized.setdefault("host_status", "scheduled")
    return normalized


def _sentences(text: str) -> List[str]:
    return [
        item.strip(" -\n\t")
        for item in re.split(r"(?<=[.!?])\s+|\n+", text)
        if item.strip(" -\n\t")
    ]


def _meeting_analysis(transcript: str) -> Dict[str, Any]:
    text = _clean(transcript)
    if not text:
        raise HTTPException(400, "Transcript is required")
    sentences = _sentences(text)
    lower_pairs = [(sentence, sentence.lower()) for sentence in sentences]
    action_words = ("will", "need", "todo", "to do", "action", "share", "send", "confirm", "schedule", "follow")
    decision_words = ("agreed", "decided", "confirmed", "selected", "approved", "final")
    risk_words = ("issue", "risk", "blocked", "concern", "problem", "delay", "not available", "unavailable")
    actions = [s for s, low in lower_pairs if any(word in low for word in action_words)][:8]
    decisions = [s for s, low in lower_pairs if any(word in low for word in decision_words)][:8]
    risks = [s for s, low in lower_pairs if any(word in low for word in risk_words)][:6]
    key_points = sentences[:8]
    if not actions:
        actions = ["Share interview feedback with the client and trainer.", "Confirm next step and expected timeline."]
    if not decisions:
        decisions = ["Decision not explicitly captured in transcript."]
    return {
        "summary": "Interview meeting notes captured and structured from the live transcript.",
        "key_points": key_points,
        "decisions": decisions,
        "action_items": actions,
        "risks": risks,
    }


def _document(payload: InterviewNotesRequest, analysis: Dict[str, Any]) -> str:
    lines = [
        "Interview Meeting Notes",
        "",
        f"Domain: {_clean(payload.domain) or 'Not available'}",
        f"Trainer: {_clean(payload.trainer_name) or 'Not available'}",
        f"Trainer Email: {_clean(payload.trainer_email) or 'Not available'}",
        f"Client: {_clean(payload.client_name) or 'Not available'}",
        f"Client Email: {_clean(payload.client_email) or 'Not available'}",
        f"Meeting Time: {_clean(payload.meeting_time) or 'Not available'}",
        f"Meeting Link: {_clean(payload.meeting_link) or 'Not available'}",
        "",
        "Summary",
        analysis["summary"],
        "",
        "Key Points",
        *[f"- {item}" for item in analysis["key_points"]],
        "",
        "Decisions",
        *[f"- {item}" for item in analysis["decisions"]],
        "",
        "Action Items",
        *[f"- {item}" for item in analysis["action_items"]],
    ]
    if analysis.get("risks"):
        lines.extend(["", "Risks / Concerns", *[f"- {item}" for item in analysis["risks"]]])
    lines.extend(["", "Transcript", payload.transcript])
    return "\n".join(lines)


def _html_document(text: str) -> str:
    import html
    escaped = html.escape(text)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Interview Meeting Notes</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #0f172a; background: #f8fafc; }}
    main {{ max-width: 920px; margin: 0 auto; background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 28px; }}
    pre {{ white-space: pre-wrap; font-family: Arial, sans-serif; line-height: 1.65; font-size: 14px; }}
  </style>
</head>
<body><main><pre>{escaped}</pre></main></body>
</html>"""


def _excel_cell(value: Any) -> str:
    import html
    return f'<c t="inlineStr"><is><t>{html.escape(_clean(value))}</t></is></c>'


def _excel_row(values: List[Any]) -> str:
    return f"<row>{''.join(_excel_cell(value) for value in values)}</row>"


def _notes_rows(doc: Dict[str, Any]) -> List[List[Any]]:
    analysis = doc.get("analysis") or {}
    rows: List[List[Any]] = [
        ["Field", "Value"],
        ["Document ID", doc.get("document_id")],
        ["Domain", doc.get("domain")],
        ["Trainer", doc.get("trainer_name")],
        ["Trainer Email", doc.get("trainer_email")],
        ["Client", doc.get("client_name")],
        ["Client Email", doc.get("client_email")],
        ["Meeting Time", doc.get("meeting_time")],
        ["Meeting Link", doc.get("meeting_link")],
        ["Created At", doc.get("created_at")],
        [],
        ["Section", "Point"],
        ["Summary", analysis.get("summary")],
    ]
    for key, label in (
        ("key_points", "Key Point"),
        ("decisions", "Decision"),
        ("action_items", "Action Item"),
        ("risks", "Risk / Concern"),
    ):
        for item in analysis.get(key) or []:
            rows.append([label, item])
    rows.extend([[], ["Transcript", doc.get("transcript")], ["Formatted Document", doc.get("document_text")]])
    return rows


def _xlsx_bytes(rows: List[List[Any]]) -> bytes:
    sheet_rows = "\n".join(_excel_row(row) if row else "<row/>" for row in rows)
    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{sheet_rows}</sheetData>
</worksheet>"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Meeting Notes" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


@router.get("")
async def list_reminders(
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    cursor = db["interview_reminders"].find(query, {"_id": 0}).sort("interview_at", 1).limit(200)
    items = [d async for d in cursor]
    return {"success": True, "count": len(items), "reminders": items}


@router.get("/interview-schedules")
async def list_interview_schedules(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Return email_logs where an interview is scheduled."""
    cursor = (
        db["email_logs"]
        .find({"interview_scheduled": True}, {"_id": 0})
        .sort("interview_at", 1)
        .limit(200)
    )
    items = [_with_meeting_start_fields(d) async for d in cursor]
    return {"success": True, "count": len(items), "schedules": items}


@schedules_router.get("")
async def list_interview_schedules_alias(db: AsyncIOMotorDatabase = Depends(get_db)):
    """Frontend-compatible alias for /api/v1/interview-schedules."""
    return await list_interview_schedules(db)


@schedules_router.post("/notes/analyze")
async def analyze_interview_notes(payload: InterviewNotesRequest):
    analysis = _meeting_analysis(payload.transcript)
    return {"success": True, "analysis": analysis, "document_text": _document(payload, analysis)}


@schedules_router.post("/notes")
async def save_interview_notes(payload: InterviewNotesRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    analysis = _meeting_analysis(payload.transcript)
    document_id = f"IMN-{uuid.uuid4().hex[:10].upper()}"
    doc = {
        "document_id": document_id,
        "schedule_key": payload.schedule_key,
        "trainer_name": payload.trainer_name,
        "trainer_email": payload.trainer_email,
        "client_name": payload.client_name,
        "client_email": payload.client_email,
        "domain": payload.domain,
        "meeting_link": payload.meeting_link,
        "meeting_time": payload.meeting_time,
        "transcript": payload.transcript,
        "analysis": analysis,
        "document_text": _document(payload, analysis),
        "document_url": f"/api/interview-schedules/notes/{document_id}/document",
        "download_url": f"/api/interview-schedules/notes/{document_id}/download",
        "excel_url": f"/api/interview-schedules/notes/{document_id}/excel",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db["interview_meeting_notes"].insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "document": doc}


@schedules_router.get("/notes/{document_id}/document")
async def view_interview_notes_document(document_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["interview_meeting_notes"].find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Meeting document not found")
    return Response(content=_html_document(doc.get("document_text", "")), media_type="text/html")


@schedules_router.get("/notes/{document_id}/download")
async def download_interview_notes_document(document_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["interview_meeting_notes"].find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Meeting document not found")
    filename = f"{document_id}.txt"
    return Response(
        content=doc.get("document_text", ""),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@schedules_router.get("/notes/{document_id}/excel")
async def download_interview_notes_excel(document_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    doc = await db["interview_meeting_notes"].find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Meeting document not found")
    filename = f"{document_id}.xlsx"
    return Response(
        content=_xlsx_bytes(_notes_rows(doc)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("")
async def schedule_reminder(
    payload: ScheduleReminderRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    now = datetime.utcnow()
    try:
        interview_at = datetime.fromisoformat(payload.interview_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid interview_at: {exc}") from exc

    remind_at = interview_at - timedelta(hours=max(0, payload.reminder_hours_before))

    reminder_id = f"REM-{uuid.uuid4().hex[:10].upper()}"
    doc = {
        "reminder_id": reminder_id,
        "email_id": payload.email_id,
        "trainer_id": payload.trainer_id,
        "trainer_name": payload.trainer_name,
        "trainer_phone": payload.trainer_phone,
        "trainer_email": payload.trainer_email,
        "requirement_id": payload.requirement_id,
        "technology": payload.technology,
        "interview_at": interview_at,
        "remind_at": remind_at,
        "platform": payload.platform,
        "interview_link": payload.interview_link,
        "status": "scheduled",
        "whatsapp_reminder_status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    await db["interview_reminders"].insert_one(doc)

    # Also mark the email_log with interview details
    await db["email_logs"].update_one(
        {"email_id": payload.email_id},
        {"$set": {
            "interview_scheduled": True,
            "interview_at": interview_at,
            "interview_link": payload.interview_link,
            "reminder_id": reminder_id,
            "whatsapp_reminder_status": "pending",
            "updated_at": now,
        }},
    )
    doc.pop("_id", None)
    doc["interview_at"] = interview_at.isoformat()
    doc["remind_at"] = remind_at.isoformat()
    return {"success": True, "reminder_id": reminder_id, "remind_at": remind_at.isoformat()}


@router.post("/{reminder_id}/cancel")
async def cancel_reminder(reminder_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    result = await db["interview_reminders"].update_one(
        {"reminder_id": reminder_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Reminder not found")
    return {"success": True, "reminder_id": reminder_id, "status": "cancelled"}


@router.post("/{reminder_id}/reschedule")
async def reschedule_reminder(
    reminder_id: str,
    payload: RescheduleRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db["interview_reminders"].find_one({"reminder_id": reminder_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Reminder not found")

    try:
        new_at = datetime.fromisoformat(payload.new_interview_at.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    hours_before = doc.get("reminder_hours_before", 1)
    new_remind_at = new_at - timedelta(hours=hours_before)
    now = datetime.utcnow()

    update: Dict[str, Any] = {
        "interview_at": new_at,
        "remind_at": new_remind_at,
        "status": "rescheduled",
        "rescheduled_at": now,
        "updated_at": now,
    }
    if payload.interview_link:
        update["interview_link"] = payload.interview_link

    await db["interview_reminders"].update_one({"reminder_id": reminder_id}, {"$set": update})
    return {"success": True, "reminder_id": reminder_id, "new_interview_at": new_at.isoformat()}
