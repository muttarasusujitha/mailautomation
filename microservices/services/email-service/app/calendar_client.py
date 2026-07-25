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
                sendUpdates="none",
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
