"""Google Calendar helpers for creating Meet links."""
import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def _token_path() -> str:
    path = settings.GOOGLE_TOKEN_FILE or "config/token.json"
    if os.path.isabs(path):
        return path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, path)


def _load_calendar_service() -> Tuple[Any, str]:
    token_file = _token_path()
    if not os.path.exists(token_file):
        return None, "Google OAuth token not found. Reconnect Gmail with Calendar access."

    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_file, CALENDAR_SCOPES)
        granted_scopes = [str(scope) for scope in (getattr(creds, "scopes", None) or [])]
        if granted_scopes and not any("/auth/calendar" in scope for scope in granted_scopes):
            return None, "Google Calendar scope is missing. Reconnect Gmail and allow Calendar access."

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            with open(token_file, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
        if not creds or not creds.valid:
            return None, "Google OAuth token is invalid. Reconnect Gmail with Calendar access."
        return build("calendar", "v3", credentials=creds), ""
    except Exception as exc:
        logger.exception("Google Calendar service init failed")
        return None, str(exc)


def _extract_meet_link(event: Dict[str, Any]) -> str:
    link = str(event.get("hangoutLink") or "").strip()
    if link:
        return link
    for entry in ((event.get("conferenceData") or {}).get("entryPoints") or []):
        uri = str(entry.get("uri") or "").strip()
        if entry.get("entryPointType") == "video" and uri:
            return uri
    return ""


def _create_google_meet_event_sync(
    *,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    attendees: Optional[List[str]] = None,
    timezone: str = "Asia/Kolkata",
) -> Dict[str, Any]:
    service, error = _load_calendar_service()
    if not service:
        return {"success": False, "error": error}

    attendee_items = [
        {"email": email.strip()}
        for email in (attendees or [])
        if str(email or "").strip()
    ]
    body: Dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        "conferenceData": {
            "createRequest": {
                "requestId": f"ts-{uuid.uuid4().hex[:20]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if attendee_items:
        body["attendees"] = attendee_items

    try:
        event = (
            service.events()
            .insert(
                calendarId=getattr(settings, "GOOGLE_CALENDAR_ID", "primary") or "primary",
                body=body,
                conferenceDataVersion=1,
                # Interview participants receive a private branded email from
                # TrainerSync.  Do not send a shared Calendar invitation,
                # which exposes every attendee's email address to the others.
                sendUpdates="all" if attendee_items else "none",
            )
            .execute()
        )
        meet_link = _extract_meet_link(event)
        if not meet_link:
            return {"success": False, "error": "Google Calendar event was created without a Meet link.", "event": event}
        return {
            "success": True,
            "meet_link": meet_link,
            "html_link": event.get("htmlLink") or "",
            "event_id": event.get("id") or "",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone,
        }
    except Exception as exc:
        logger.exception("Google Calendar event creation failed")
        return {"success": False, "error": str(exc)}


async def create_google_meet_event(
    *,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    attendees: Optional[List[str]] = None,
    timezone: str = "Asia/Kolkata",
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _create_google_meet_event_sync,
        summary=summary,
        description=description,
        start=start,
        end=end,
        attendees=attendees,
        timezone=timezone,
    )


def _add_calendar_attendees_sync(event_id: str, attendees: List[str]) -> Dict[str, Any]:
    """Add attendees to an existing event and make Google deliver invites."""
    service, error = _load_calendar_service()
    if not service:
        return {"success": False, "error": error}
    clean_attendees = sorted({str(email or "").strip().lower() for email in attendees if str(email or "").strip()})
    if not event_id or not clean_attendees:
        return {"success": False, "error": "Calendar event ID and attendees are required."}
    try:
        event = service.events().get(
            calendarId=getattr(settings, "GOOGLE_CALENDAR_ID", "primary") or "primary",
            eventId=event_id,
        ).execute()
        existing = {
            str(item.get("email") or "").strip().lower()
            for item in (event.get("attendees") or [])
            if str(item.get("email") or "").strip()
        }
        combined = sorted(existing | set(clean_attendees))
        updated = service.events().patch(
            calendarId=getattr(settings, "GOOGLE_CALENDAR_ID", "primary") or "primary",
            eventId=event_id,
            body={"attendees": [{"email": email} for email in combined]},
            sendUpdates="all",
        ).execute()
        return {
            "success": True,
            "event_id": updated.get("id") or event_id,
            "meet_link": _extract_meet_link(updated),
        }
    except Exception as exc:
        logger.exception("Failed to add interview attendees to calendar event %s", event_id)
        return {"success": False, "error": str(exc)}


async def add_google_calendar_attendees(event_id: str, attendees: List[str]) -> Dict[str, Any]:
    return await asyncio.to_thread(_add_calendar_attendees_sync, event_id, attendees)


def _cancel_google_calendar_event_sync(event_id: str) -> Dict[str, Any]:
    """Cancel a superseded interview event only after a replacement is ready."""
    service, error = _load_calendar_service()
    if not service:
        return {"success": False, "error": error}
    if not event_id:
        return {"success": False, "error": "Calendar event ID is required."}
    try:
        service.events().delete(
            calendarId=getattr(settings, "GOOGLE_CALENDAR_ID", "primary") or "primary",
            eventId=event_id,
            sendUpdates="all",
        ).execute()
        return {"success": True, "event_id": event_id}
    except Exception as exc:
        logger.exception("Failed to cancel superseded interview event %s", event_id)
        return {"success": False, "error": str(exc)}


async def cancel_google_calendar_event(event_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_cancel_google_calendar_event_sync, event_id)
