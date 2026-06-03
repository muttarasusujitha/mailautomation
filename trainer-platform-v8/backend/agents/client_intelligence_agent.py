import base64
import email as email_lib
import html
import imaplib
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from utils.time_utils import utc_from_timestamp, utc_now
from email.header import make_header, decode_header
from html.parser import HTMLParser
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any, Dict, List, Optional, Tuple

import httpx
import fitz
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import get_settings


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]
GOOGLE_OAUTH_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(BACKEND_DIR, "config")
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_FILE", os.path.join(CONFIG_DIR, "credentials.json"))
TOKEN_PATH = os.getenv("GOOGLE_TOKEN_FILE", os.path.join(CONFIG_DIR, "token.json"))

TRAINING_KEYWORDS = [
    "training", "trainer", "workshop", "corporate training", "need trainer",
    "require trainer", "kubernetes", "devops", "python", "java", "azure", "aws",
    "data science", "machine learning", "power bi", "tableau", "cloud", "genai",
    "sap", "salesforce", "full stack", "react", "node", "cybersecurity",
]

AUTO_REPLY_MARKERS = [
    "out of office", "automatic reply", "auto-reply", "autoreply", "vacation responder",
    "i am away", "away from office", "delivery status notification",
]


def _is_placeholder_value(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return (
        lowered in {"yourgmail@gmail.com", "your_gmail_app_password", "your-project-id"}
        or "your_project_id" in lowered
        or "projects/your" in lowered
        or lowered.startswith("your_")
    )


def _env_file_value(name: str) -> str:
    if not os.path.exists(ENV_PATH):
        return ""
    prefix = f"{name.upper()}="
    values: List[str] = []
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if stripped.startswith(prefix):
                    values.append(stripped.split("=", 1)[1].strip())
    except OSError:
        return ""
    for value in reversed(values):
        if value and not _is_placeholder_value(value):
            return value
    return ""


def _settings_value(name: str, default: str = "") -> str:
    settings = get_settings()
    candidates = [
        os.getenv(name.upper(), ""),
        _env_file_value(name),
        getattr(settings, name, ""),
        default,
    ]
    for value in candidates:
        cleaned = str(value or "").strip()
        if cleaned and not _is_placeholder_value(cleaned):
            return cleaned
    return default


def _load_oauth_client_config() -> Tuple[str, Dict[str, Any]]:
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError(f"Google OAuth credentials not found at {CREDENTIALS_PATH}")
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as credentials_file:
        config = json.load(credentials_file)
    client_type = "web" if "web" in config else "installed" if "installed" in config else ""
    if not client_type:
        raise RuntimeError("Google OAuth credentials must contain a 'web' or 'installed' client.")
    return client_type, config[client_type]


def _default_redirect_uri() -> str:
    _, client = _load_oauth_client_config()
    redirects = client.get("redirect_uris") or []
    return redirects[0] if redirects else "http://localhost:5173/auth/callback"


def _oauth_flow(redirect_uri: Optional[str] = None) -> Flow:
    redirect = redirect_uri or _default_redirect_uri()
    if redirect.startswith("http://localhost") or redirect.startswith("http://127.0.0.1"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # NOSONAR: local OAuth callback only
    return Flow.from_client_secrets_file(
        CREDENTIALS_PATH,
        scopes=GOOGLE_OAUTH_SCOPES,
        redirect_uri=redirect,
    )


def get_gmail_oauth_url(redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    redirect = redirect_uri or _default_redirect_uri()
    flow = _oauth_flow(redirect)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"auth_url": auth_url, "state": state, "redirect_uri": redirect}


def save_gmail_oauth_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    if not code:
        raise RuntimeError("Missing Google OAuth authorization code")
    redirect = redirect_uri or _default_redirect_uri()
    flow = _oauth_flow(redirect)
    flow.fetch_token(code=code)
    creds = flow.credentials
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return {
        "success": True,
        "connected": True,
        "gmail_user": profile.get("emailAddress") or _settings_value("gmail_user"),
        "redirect_uri": redirect,
    }


def _gemini_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY", "") or
        _settings_value("gemini_api_key")
    )


def _gmail_b64decode(value: str) -> bytes:
    if not value:
        return b""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def parse_email_address(value: str) -> Tuple[str, str]:
    name, addr = parseaddr(decode_header_value(value))
    return (name or "").strip(), (addr or value or "").strip().lower()


def sender_domain(email_address: str) -> str:
    if "@" not in (email_address or ""):
        return ""
    return email_address.rsplit("@", 1)[1].lower().strip()


def _headers_to_dict(headers: List[Dict[str, str]]) -> Dict[str, str]:
    return {h.get("name", "").lower(): decode_header_value(h.get("value", "")) for h in headers or []}


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._chunks: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag in {"br", "p", "div", "li", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split()).strip()


def _html_to_text(raw_html: str) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(raw_html or "")
    return html.unescape(parser.text())


def strip_quoted_history(text: str) -> str:
    if not text:
        return ""

    has_forwarded_requirement = bool(re.search(r"forwarded message|original message", text, re.I))
    clean_lines = []
    quote_boundary = re.compile(
        r"^\s*(on\s.+wrote:|from:\s.+|sent:\s.+|to:\s.+|subject:\s.+)",
        re.I,
    )

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if quote_boundary.match(stripped) and not has_forwarded_requirement:
            break
        clean_lines.append(line)

    return "\n".join(clean_lines).strip()


def strip_signature(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        if re.match(r"^\s*(--|regards\b|thanks\b|best\b)", line, re.I):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def clean_email_body(text: str) -> str:
    text = strip_quoted_history(text or "")
    text = strip_signature(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_auto_reply(headers: Dict[str, str], subject: str, body: str) -> bool:
    auto_submitted = headers.get("auto-submitted", "").lower()
    precedence = headers.get("precedence", "").lower()
    subject_body = f"{subject}\n{body[:1000]}".lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if precedence in {"bulk", "junk", "list"}:
        return True
    return any(marker in subject_body for marker in AUTO_REPLY_MARKERS)


def is_likely_training_email(
    subject: str,
    from_email: str = "",
    whitelist_domains: Optional[List[str]] = None,
    body_preview: str = "",
) -> bool:
    domain = sender_domain(from_email)
    whitelist = {d.lower().strip() for d in (whitelist_domains or []) if d.strip()}
    if domain and domain in whitelist:
        return True
    lowered_email = (from_email or "").lower()
    automated_markers = ("no-reply", "noreply", "notification", "linkedin.com", "naukri.com")
    if any(marker in lowered_email for marker in automated_markers):
        return False

    subject_haystack = (subject or "").lower()
    if any(keyword in subject_haystack for keyword in TRAINING_KEYWORDS):
        return True

    haystack = f"{subject or ''}\n{body_preview or ''}".lower()
    request_markers = (
        "training", "trainer", "workshop", "corporate batch", "participants",
        "duration", "mode:", "technology:", "budget", "share suitable trainer",
    )
    return (
        any(marker in haystack for marker in request_markers)
        and any(keyword in haystack for keyword in TRAINING_KEYWORDS)
    )


def _walk_gmail_parts(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    parts = [part]
    for child in part.get("parts") or []:
        parts.extend(_walk_gmail_parts(child))
    return parts


def _extract_pdf_text(pdf_bytes: bytes, limit: int = 20000) -> str:
    if not pdf_bytes:
        return ""
    try:
        chunks = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                chunks.append(page.get_text("text"))
                if sum(len(chunk) for chunk in chunks) >= limit:
                    break
        return "\n".join(chunks)[:limit].strip()
    except Exception:
        return ""


def _google_credentials(scopes: Optional[List[str]] = None):
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"Gmail token not found at {TOKEN_PATH}")

    requested_scopes = scopes or GMAIL_SCOPES
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, requested_scopes)
    except Exception as exc:
        raise RuntimeError(
            "Gmail OAuth token is invalid. Reconnect Gmail from Client Inbox to create a fresh token."
        ) from exc
    if any(scope in requested_scopes for scope in CALENDAR_SCOPES) and hasattr(creds, "has_scopes") and not creds.has_scopes(requested_scopes):
        raise RuntimeError(
            "Google OAuth token is missing Calendar permission. Reconnect Google from Settings so Calendar/Meet access is granted."
        )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    if not creds.valid:
        raise RuntimeError("Gmail OAuth token is not valid")

    return creds


def get_gmail_service():
    creds = _google_credentials(GMAIL_SCOPES)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_calendar_service():
    creds = _google_credentials(GOOGLE_OAUTH_SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def get_gmail_auth_status(db=None) -> Dict[str, Any]:
    status = {
        "connected": False,
        "valid": False,
        "credentials_present": os.path.exists(CREDENTIALS_PATH),
        "token_present": os.path.exists(TOKEN_PATH),
        "gmail_user": _settings_value("gmail_user"),
        "last_history_id": None,
        "last_webhook_received_at": None,
        "watch_expiration": None,
    }
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        status.update({"connected": True, "valid": True})
        if profile.get("emailAddress"):
            status["gmail_user"] = profile["emailAddress"]
    except Exception as exc:
        status["error"] = str(exc)

    try:
        calendar_service = get_calendar_service()
        calendar_service.events().list(calendarId="primary", maxResults=1).execute()
        status["calendar_connected"] = True
    except Exception as exc:
        error = str(exc)
        status["calendar_connected"] = False
        status["calendar_reconnect_required"] = "insufficient" in error.lower() and "scope" in error.lower()
        status["calendar_error"] = (
            "Google Calendar permission is missing. Reconnect Google from Settings so Calendar/Meet access is granted."
            if status["calendar_reconnect_required"]
            else error
        )

    if db is not None:
        sync = await db["gmail_sync"].find_one({"sync_id": "default"}, {"_id": 0})
        if sync:
            status.update({
                "last_history_id": sync.get("last_history_id"),
                "last_webhook_received_at": sync.get("last_webhook_received_at"),
                "watch_expiration": sync.get("watch_expiration"),
            })
    return status


async def renew_gmail_watch(db=None, gmail_service=None) -> Dict[str, Any]:
    topic = os.getenv("PUBSUB_TOPIC", "") or _settings_value("pubsub_topic")
    if not topic or "YOUR_PROJECT_ID" in topic or "PROJECT_ID" in topic:
        raise RuntimeError(
            "PUBSUB_TOPIC is not configured. Set it in backend/.env as "
            "projects/<your-google-cloud-project-id>/topics/trainersync-inbox."
        )

    service = gmail_service or get_gmail_service()

    body = {
        "topicName": topic,
        "labelIds": ["INBOX"],
        "labelFilterAction": "include",
    }
    result = service.users().watch(userId="me", body=body).execute()
    expires_ms = int(result.get("expiration", "0") or 0)
    expires_at = utc_from_timestamp(expires_ms / 1000) if expires_ms else None

    if db is not None:
        await db["gmail_sync"].update_one(
            {"sync_id": "default"},
            {"$set": {
                "last_history_id": result.get("historyId"),
                "watch_expiration": expires_at,
                "watch_response": result,
                "watch_renewed_at": utc_now(),
                "gmail_user": _settings_value("gmail_user"),
            }},
            upsert=True,
        )

    return {
        "success": True,
        "historyId": result.get("historyId"),
        "expiration": result.get("expiration"),
        "watch_expiration": expires_at,
    }


def fetch_gmail_email(message_id: str, gmail_service) -> Dict[str, Any]:
    message = gmail_service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()
    payload = message.get("payload") or {}
    headers = _headers_to_dict(payload.get("headers") or [])
    from_name, from_email = parse_email_address(headers.get("from", ""))
    reply_name, reply_to = parse_email_address(headers.get("reply-to", ""))
    subject = headers.get("subject", "")

    plain_chunks: List[str] = []
    html_chunks: List[str] = []
    attachment_texts: List[str] = []

    for part in _walk_gmail_parts(payload):
        mime_type = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data", "")
        filename = part.get("filename") or ""

        if data and mime_type == "text/plain":
            plain_chunks.append(_gmail_b64decode(data).decode("utf-8", errors="ignore"))
        elif data and mime_type == "text/html":
            html_chunks.append(_html_to_text(_gmail_b64decode(data).decode("utf-8", errors="ignore")))

        attachment_id = body.get("attachmentId")
        if attachment_id and filename.lower().endswith(".pdf"):
            attachment = gmail_service.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id,
            ).execute()
            text = _extract_pdf_text(_gmail_b64decode(attachment.get("data", "")))
            if text:
                attachment_texts.append(f"Attachment {filename}:\n{text}")

    raw_body = "\n".join(plain_chunks).strip() or "\n".join(html_chunks).strip() or message.get("snippet", "")
    clean_body = clean_email_body(raw_body)

    received_at = None
    internal_date = message.get("internalDate")
    if internal_date:
        received_at = utc_from_timestamp(int(internal_date) / 1000)

    return {
        "email_id": message_id,
        "thread_id": message.get("threadId"),
        "received_at": received_at or utc_now(),
        "from_email": reply_to or from_email,
        "from_name": reply_name or from_name,
        "subject": subject,
        "headers": headers,
        "message_id_header": headers.get("message-id", ""),
        "raw_body": raw_body,
        "clean_body": clean_body,
        "attachments_text": "\n\n".join(attachment_texts).strip(),
        "is_auto_reply": is_auto_reply(headers, subject, raw_body),
        "snippet": message.get("snippet", ""),
    }


async def _gemini_json(prompt: str, max_tokens: int = 1600) -> Dict[str, Any]:
    api_key = _gemini_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    url = GEMINI_API_URL.format(model=GEMINI_MODEL) + f"?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    raw = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Gemini did not return JSON. Response: {raw[:300]}")
    return json.loads(raw[start:end + 1])


def _normalise_extraction(extracted: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "client_name": None,
        "client_company": None,
        "client_email": meta.get("from_email"),
        "client_phone": None,
        "technology_needed": None,
        "secondary_technologies": [],
        "duration_days": None,
        "duration_hours": None,
        "participant_count": None,
        "audience_level": None,
        "mode": None,
        "location": None,
        "budget_per_day": None,
        "budget_total": None,
        "budget_currency": None,
        "timeline_start": None,
        "timeline_flexible": False,
        "urgency": "normal",
        "special_requirements": None,
        "language_of_training": "English",
        "email_subject": meta.get("subject"),
        "email_summary": "",
        "confidence": 0.0,
        "needs_clarification": [],
        "is_training_request": False,
        "sender_is_known_client": False,
    }
    merged = {**defaults, **(extracted or {})}
    merged["client_email"] = merged.get("client_email") or meta.get("from_email")
    merged["email_subject"] = merged.get("email_subject") or meta.get("subject")
    merged["secondary_technologies"] = merged.get("secondary_technologies") or []
    merged["needs_clarification"] = merged.get("needs_clarification") or []
    try:
        merged["confidence"] = max(0.0, min(1.0, float(merged.get("confidence") or 0)))
    except Exception:
        merged["confidence"] = 0.0
    return merged


def _field_from_text(text: str, label: str) -> Optional[str]:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text or "")
    return match.group(1).strip() if match else None


def _heuristic_training_extraction(meta: Dict[str, Any]) -> Dict[str, Any]:
    body = meta.get("clean_body") or meta.get("raw_body") or ""
    subject = meta.get("subject") or ""
    haystack = f"{subject}\n{body}"
    tech = _field_from_text(body, "Technology")
    client_phone = (
        _field_from_text(body, "Phone")
        or _field_from_text(body, "Mobile")
        or _field_from_text(body, "Contact")
        or _field_from_text(body, "WhatsApp")
    )
    if not tech:
        for keyword in TRAINING_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", haystack, re.IGNORECASE):
                tech = keyword.title()
                break
    participants = _field_from_text(body, "Participants")
    duration = _field_from_text(body, "Duration")
    budget = _field_from_text(body, "Budget")
    budget_number = None
    if budget:
        number_match = re.search(r"[\d,]+", budget)
        if number_match:
            budget_number = int(number_match.group(0).replace(",", ""))
    participant_count = None
    if participants:
        participant_match = re.search(r"\d+", participants)
        if participant_match:
            participant_count = int(participant_match.group(0))
    duration_days = None
    if duration:
        duration_match = re.search(r"\d+", duration)
        if duration_match and "day" in duration.lower():
            duration_days = int(duration_match.group(0))

    needs = []
    if not _field_from_text(body, "Audience Level"):
        needs.append("audience level")
    if not _field_from_text(body, "Start Date"):
        needs.append("start date")

    return {
        "client_name": meta.get("from_name") or None,
        "client_company": None,
        "client_email": meta.get("from_email"),
        "client_phone": client_phone,
        "technology_needed": tech or "Training Requirement",
        "secondary_technologies": [],
        "duration_days": duration_days,
        "duration_hours": None,
        "participant_count": participant_count,
        "audience_level": None,
        "mode": (_field_from_text(body, "Mode") or "").lower() or None,
        "location": _field_from_text(body, "Location"),
        "budget_per_day": budget_number if budget and "day" in budget.lower() else None,
        "budget_total": budget_number if budget and "day" not in budget.lower() else None,
        "budget_currency": "INR" if budget and re.search(r"\binr\b|rs\.?|₹", budget, re.IGNORECASE) else None,
        "timeline_start": _field_from_text(body, "Start Date"),
        "timeline_flexible": False,
        "urgency": "normal",
        "special_requirements": None,
        "language_of_training": "English",
        "email_subject": subject,
        "email_summary": f"Client needs {tech or 'a'} trainer for a corporate training requirement.",
        "confidence": 0.72,
        "needs_clarification": needs,
        "is_training_request": True,
        "sender_is_known_client": False,
    }


_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _time_to_24h(hour: str, minute: str = "", meridiem: str = "") -> Tuple[int, int]:
    h = int(hour)
    m = int(minute or 0)
    ampm = (meridiem or "").lower()
    if ampm == "pm" and h != 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return h, m


def _slot_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _heuristic_client_slot_confirmation(reply_text: str, timezone_name: str = "Asia/Kolkata") -> Dict[str, Any]:
    text = re.sub(r"\s+", " ", str(reply_text or "")).strip()
    empty = {
        "confirmed": False,
        "date_time_text": "",
        "start_iso": "",
        "end_iso": "",
        "timezone": timezone_name,
        "confidence": 0,
    }
    if not text:
        return {**empty, "reason": "No client reply text"}

    date_match = re.search(
        r"\b(\d{1,2})\s+("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?|tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if date_match:
        day = int(date_match.group(1))
        month = _MONTHS[date_match.group(2).lower()[:3]]
        year = int(date_match.group(3))
    else:
        numeric_date = re.search(r"\b(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{2,4})\b", text)
        if numeric_date:
            day = int(numeric_date.group(1))
            month = int(numeric_date.group(2))
            year = int(numeric_date.group(3))
            if year < 100:
                year += 2000
        elif re.search(r"\btomorrow\b", text, flags=re.IGNORECASE):
            tomorrow = utc_now() + timedelta(days=1)
            day, month, year = tomorrow.day, tomorrow.month, tomorrow.year
        else:
            return {**empty, "reason": "No concrete date found"}

    range_match = re.search(
        r"\b(?:from\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|-|–|—)\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text,
        flags=re.IGNORECASE,
    )
    single_match = None if range_match else re.search(
        r"\b(?:at|from)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not range_match and not single_match:
        return {**empty, "reason": "No concrete time found"}

    if range_match:
        start_ampm = range_match.group(3) or range_match.group(6)
        sh, sm = _time_to_24h(range_match.group(1), range_match.group(2), start_ampm)
        eh, em = _time_to_24h(range_match.group(4), range_match.group(5), range_match.group(6))
    else:
        sh, sm = _time_to_24h(single_match.group(1), single_match.group(2), single_match.group(3))
        end_tmp = datetime(year, month, day, sh, sm) + timedelta(minutes=30)
        eh, em = end_tmp.hour, end_tmp.minute

    try:
        start_dt = datetime(year, month, day, sh, sm)
        end_dt = datetime(year, month, day, eh, em)
        if end_dt <= start_dt:
            end_dt += timedelta(hours=12)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=30)
    except ValueError as exc:
        return {**empty, "reason": f"Invalid date/time: {exc}"}

    confirmation_words = re.search(
        r"\b(confirm|confirmed|works|available|schedule|book|proceed|convenient)\b",
        text,
        flags=re.IGNORECASE,
    )
    return {
        "confirmed": True,
        "date_time_text": f"{start_dt.strftime('%d %b %Y %I:%M %p')} - {end_dt.strftime('%I:%M %p')}",
        "start_iso": _slot_iso(start_dt),
        "end_iso": _slot_iso(end_dt),
        "timezone": timezone_name,
        "confidence": 0.9 if confirmation_words else 0.7,
        "reason": "Parsed date/time with deterministic fallback",
    }


async def process_client_email(message_id, gmail_service, meta: Optional[Dict[str, Any]] = None) -> dict:
    meta = meta or fetch_gmail_email(message_id, gmail_service)

    if meta.get("is_auto_reply"):
        meta["extracted"] = _normalise_extraction({
            "client_email": meta.get("from_email"),
            "email_subject": meta.get("subject"),
            "email_summary": "Auto-reply or out-of-office message. Not processed as a training request.",
            "confidence": 0,
            "is_training_request": False,
        }, meta)
        return meta

    body_for_gemini = meta.get("clean_body") or meta.get("raw_body") or ""
    if meta.get("attachments_text"):
        body_for_gemini = f"{body_for_gemini}\n\nPDF/RFP attachment text:\n{meta['attachments_text']}"

    prompt = f"""You are an intelligent email analyst for Calhan Technologies,
a corporate training company in India.

Read this client email and extract all training requirement details.
The client may write in formal English, casual English, Hinglish,
Hindi, Tamil, Telugu, or any Indian regional language mixed with
English. Understand the intent regardless of language or writing
style.

Extract and return ONLY valid JSON with no extra text:
{{
  "client_name": "full name if found else null",
  "client_company": "company name if found else null",
  "client_email": "reply-to email address",
  "client_phone": "client phone or WhatsApp number if explicitly found else null",
  "technology_needed": "primary technology or skill required",
  "secondary_technologies": ["array of additional skills if any"],
  "duration_days": number or null,
  "duration_hours": number or null,
  "participant_count": number or null,
  "audience_level": "beginner or intermediate or advanced or mixed or null",
  "mode": "online or offline or hybrid or null",
  "location": "city or null if offline",
  "budget_per_day": number or null,
  "budget_total": number or null,
  "budget_currency": "INR or USD or null",
  "timeline_start": "date string or description like next week or null",
  "timeline_flexible": true or false,
  "urgency": "urgent or normal or flexible",
  "special_requirements": "any specific tools versions labs etc or null",
  "language_of_training": "English or Hindi or Tamil etc",
  "email_subject": "original subject line",
  "email_summary": "2 sentence summary of what client needs",
  "confidence": number from 0 to 1 how complete the extraction is,
  "needs_clarification": ["list of important fields that are missing and the client should be asked about"],
  "is_training_request": true or false,
  "sender_is_known_client": false
}}

Email metadata:
From name: {meta.get("from_name") or ""}
From email: {meta.get("from_email") or ""}
Subject: {meta.get("subject") or ""}

Email text:
---
{body_for_gemini[:45000]}
---"""

    try:
        extracted = await _gemini_json(prompt, max_tokens=1800)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {429, 503}:
            raise
        extracted = _heuristic_training_extraction(meta)
    meta["extracted"] = _normalise_extraction(extracted, meta)
    return meta


async def extract_client_slot_confirmation(
    reply_text: str,
    slot_text: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = context or {}
    timezone_name = context.get("timezone") or "Asia/Kolkata"
    today = utc_now().strftime("%Y-%m-%d")
    prompt = f"""You extract calendar scheduling confirmations for Calhan Technologies.

The client has replied after Calhan sent trainer availability slots. Determine whether the client selected or proposed a concrete interview/discussion date and time.

Rules:
- If the client clearly declines, asks only a question, or gives no concrete date/time, set confirmed=false.
- If the client says a listed slot works, or proposes a specific alternate date/time, set confirmed=true.
- Interpret relative dates using today's date: {today}.
- Use timezone "{timezone_name}" unless the email explicitly gives another timezone.
- Default duration is 30 minutes when duration is not mentioned.
- Return ISO 8601 local datetimes with timezone offset if you can infer them.

Original trainer slot options:
---
{slot_text[:4000]}
---

Client reply:
---
{reply_text[:4000]}
---

Context:
{json.dumps(context, ensure_ascii=False, default=str)}

Return ONLY valid JSON:
{{
  "confirmed": true or false,
  "date_time_text": "human readable confirmed slot or empty string",
  "start_iso": "YYYY-MM-DDTHH:MM:SS+05:30 or empty string",
  "end_iso": "YYYY-MM-DDTHH:MM:SS+05:30 or empty string",
  "timezone": "{timezone_name}",
  "confidence": 0.0,
  "reason": "one sentence"
}}"""

    heuristic = _heuristic_client_slot_confirmation(reply_text, timezone_name)

    try:
        data = await _gemini_json(prompt, max_tokens=700)
    except Exception as exc:
        if heuristic.get("confirmed"):
            return heuristic
        return {
            "confirmed": False,
            "date_time_text": "",
            "start_iso": "",
            "end_iso": "",
            "timezone": timezone_name,
            "confidence": 0,
            "reason": f"Could not parse slot automatically: {exc}",
        }

    result = {
        "confirmed": bool(data.get("confirmed")),
        "date_time_text": str(data.get("date_time_text") or "").strip(),
        "start_iso": str(data.get("start_iso") or "").strip(),
        "end_iso": str(data.get("end_iso") or "").strip(),
        "timezone": str(data.get("timezone") or timezone_name).strip(),
        "confidence": float(data.get("confidence") or 0),
        "reason": str(data.get("reason") or "").strip(),
    }
    if heuristic.get("confirmed") and (not result["confirmed"] or not result["start_iso"] or result["confidence"] < 0.5):
        return heuristic
    return result


async def generate_calhan_reply(extracted: dict, context: dict) -> dict:
    technology = extracted.get("technology_needed") or "your training"
    needs = extracted.get("needs_clarification") or []
    budget = extracted.get("budget_total") or extracted.get("budget_per_day")
    original_subject = extracted.get("email_subject") or context.get("subject") or "Training Requirement"
    signature = context.get("reply_signature") or "Regards,\nRecruitment Team,\nCalhan Technologies"

    prompt = f"""You are the recruitment team at Calhan Technologies, a premium
corporate training company based in India.

Write a professional reply to this client email. The client has
enquired about {technology} training. Your reply must:
- Acknowledge their specific requirement by name
- Confirm you are shortlisting trainers and will share profiles
  within 24 hours
- If any of these details are missing ask for them naturally:
  {needs}
- If budget is mentioned acknowledge it
- Keep it under 150 words
- End with: Regards, Recruitment Team, Calhan Technologies

Client extraction JSON:
{json.dumps(extracted, ensure_ascii=False)}

Original subject: {original_subject}
Budget mentioned: {budget if budget else "not mentioned"}
Required signature:
{signature}

Return ONLY valid JSON:
{{
  "subject": "reply subject line starting with Re:",
  "body": "full professional email body",
  "whatsapp_message": "short WhatsApp version under 300 chars",
  "tone": "formal or friendly or neutral",
  "asks_for_clarification": true or false
}}"""

    try:
        reply = await _gemini_json(prompt, max_tokens=900)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {429, 503}:
            raise
        reply = {
            "subject": f"Re: {original_subject}",
            "body": (
                f"Hi,\n\nThank you for sharing the {technology} training requirement. "
                "We are reviewing suitable trainer profiles and will get back to you shortly. "
                "If there are any additional details around schedule, audience level, or delivery expectations, "
                "please share them with us.\n\nRegards,\nRecruitment Team,\nCalhan Technologies"
            ),
            "whatsapp_message": f"New {technology} training requirement received. Please review the client inbox.",
            "tone": "formal",
            "asks_for_clarification": bool(needs),
        }
    subject = str(reply.get("subject") or f"Re: {original_subject}").strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    body = str(reply.get("body") or "").strip()
    if "Calhan Technologies" not in body:
        body = f"{body.rstrip()}\n\n{signature}"
    whatsapp_message = re.sub(r"\s+", " ", str(reply.get("whatsapp_message") or "")).strip()
    if len(whatsapp_message) > 300:
        whatsapp_message = whatsapp_message[:297].rstrip() + "..."
    return {
        "subject": subject,
        "body": body,
        "whatsapp_message": whatsapp_message,
        "tone": reply.get("tone") or "neutral",
        "asks_for_clarification": bool(reply.get("asks_for_clarification", needs)),
    }


async def check_if_duplicate(extracted: dict, db) -> bool:
    technology = (extracted.get("technology_needed") or "").strip()
    if not technology:
        return False

    client_email = (extracted.get("client_email") or "").strip().lower()
    query: Dict[str, Any] = {
        "created_at": {"$gte": utc_now() - timedelta(days=7)},
        "technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
    }
    if not client_email:
        return False

    query["client_email"] = {"$regex": f"^{re.escape(client_email)}$", "$options": "i"}

    timeline = (extracted.get("timeline_start") or "").strip()
    if timeline:
        query["timeline_start"] = {"$regex": f"^{re.escape(timeline)}$", "$options": "i"}

    participant_count = extracted.get("participant_count")
    if participant_count not in (None, ""):
        query["participant_count"] = participant_count

    return bool(await db["requirements"].find_one(query, {"_id": 1}))


async def create_requirement_from_email(extracted: dict, email_id: str, db) -> str:
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    technology = extracted.get("technology_needed") or "Training Requirement"
    secondary = extracted.get("secondary_technologies") or []
    required_skills = [technology, *secondary]
    required_skills = [skill for skill in required_skills if skill]

    doc = {
        "requirement_id": req_id,
        "technology_needed": technology,
        "min_experience_years": 2,
        "required_skills": required_skills,
        "preferred_skills": secondary,
        "required_certifications": [],
        "preferred_location": extracted.get("location") or "",
        "must_have_linkedin": False,
        "must_have_resume": False,
        "top_n": 5,
        "job_title": f"{technology} Trainer",
        "job_description": extracted.get("email_summary") or extracted.get("special_requirements") or "",
        "send_emails": False,
        "source": "email_auto",
        "status": "active",
        "original_email_id": email_id,
        "client_name": extracted.get("client_name"),
        "client_company": extracted.get("client_company"),
        "client_email": extracted.get("client_email"),
        "client_phone": extracted.get("client_phone"),
        "client_email_domain": sender_domain(extracted.get("client_email", "")),
        "duration_days": extracted.get("duration_days"),
        "duration_hours": extracted.get("duration_hours"),
        "participant_count": extracted.get("participant_count"),
        "audience_level": extracted.get("audience_level"),
        "mode": extracted.get("mode"),
        "location": extracted.get("location"),
        "budget_per_day": extracted.get("budget_per_day"),
        "budget_total": extracted.get("budget_total"),
        "budget_currency": extracted.get("budget_currency"),
        "timeline_start": extracted.get("timeline_start"),
        "timeline_flexible": extracted.get("timeline_flexible"),
        "urgency": extracted.get("urgency"),
        "special_requirements": extracted.get("special_requirements"),
        "language_of_training": extracted.get("language_of_training"),
        "total_matched": 0,
        "created_at": utc_now(),
    }
    await db["requirements"].insert_one(doc)
    return req_id


def get_history_message_ids(gmail_service, start_history_id: str) -> Tuple[List[str], Optional[str]]:
    if not start_history_id:
        return [], None

    message_ids: List[str] = []
    latest_history_id = None
    page_token = None

    while True:
        request = gmail_service.users().history().list(
            userId="me",
            startHistoryId=str(start_history_id),
            historyTypes=["messageAdded"],
            pageToken=page_token,
        )
        response = request.execute()
        latest_history_id = response.get("historyId") or latest_history_id
        for history in response.get("history", []):
            latest_history_id = history.get("id") or latest_history_id
            for added in history.get("messagesAdded", []):
                msg = added.get("message") or {}
                if msg.get("id") and "SENT" not in (msg.get("labelIds") or []):
                    message_ids.append(msg["id"])
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return sorted(set(message_ids)), latest_history_id


def send_gmail_reply(
    gmail_service,
    *,
    to_email: str,
    subject: str,
    body: str,
    thread_id: str = "",
    in_reply_to: str = "",
) -> Dict[str, Any]:
    gmail_user = _settings_value("gmail_user")
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["From"] = f"Calhan Technologies <{gmail_user}>"
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    payload = {"raw": encoded}
    if thread_id:
        payload["threadId"] = thread_id

    return gmail_service.users().messages().send(userId="me", body=payload).execute()


async def poll_imap_client_inbox(db) -> Dict[str, Any]:
    settings = get_settings()
    gmail_user = getattr(settings, "gmail_user", "") or os.getenv("GMAIL_USER", "")
    gmail_pass = (
        getattr(settings, "gmail_app_password", "")
        or getattr(settings, "gmail_pass", "")
        or os.getenv("GMAIL_APP_PASSWORD", "")
        or os.getenv("GMAIL_PASS", "")
    ).replace(" ", "")
    if not gmail_user or not gmail_pass:
        return {"processed": 0, "skipped": "IMAP credentials missing"}

    processed = 0
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")
        _, ids = mail.search(None, "UNSEEN")
        for raw_id in (ids[0].split() if ids and ids[0] else []):
            _, data = mail.fetch(raw_id, "(RFC822)")
            if not data or not data[0]:
                continue
            raw_msg = data[0][1]
            msg = email_lib.message_from_bytes(raw_msg)
            subject = decode_header_value(msg.get("Subject", ""))
            from_name, from_email = parse_email_address(msg.get("Reply-To") or msg.get("From", ""))

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get_filename():
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            clean_body = clean_email_body(body)
            if not is_likely_training_email(subject, from_email, body_preview=clean_body[:1000]):
                continue

            pseudo_id = f"IMAP-{uuid.uuid4().hex[:12].upper()}"
            meta = {
                "email_id": pseudo_id,
                "thread_id": "",
                "received_at": utc_now(),
                "from_email": from_email,
                "from_name": from_name,
                "subject": subject,
                "raw_body": body,
                "clean_body": clean_body,
                "attachments_text": "",
            }
            extraction_prompt_context = {
                "from_email": from_email,
                "from_name": from_name,
                "subject": subject,
                "clean_body": clean_body,
                "raw_body": body,
            }
            extracted = await _extract_from_text(extraction_prompt_context)
            reply = await generate_calhan_reply(extracted, {"subject": subject})
            requirement_id = None
            if extracted.get("is_training_request") and not await check_if_duplicate(extracted, db):
                requirement_id = await create_requirement_from_email(extracted, pseudo_id, db)

            await db["client_emails"].update_one(
                {"email_id": pseudo_id},
                {"$setOnInsert": {
                    **meta,
                    "extracted": extracted,
                    "generated_reply": reply,
                    "requirement_id": requirement_id,
                    "status": "pending_approval",
                    "confidence": extracted.get("confidence", 0),
                    "auto_send_eligible": False,
                    "sent_at": None,
                    "sent_by": None,
                    "whatsapp_notified": False,
                    "created_at": utc_now(),
                }},
                upsert=True,
            )
            processed += 1
    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass
    return {"processed": processed}


async def _extract_from_text(meta: Dict[str, Any]) -> Dict[str, Any]:
    body_for_gemini = meta.get("clean_body") or meta.get("raw_body") or ""
    prompt = f"""You are an intelligent email analyst for Calhan Technologies,
a corporate training company in India.

Read this client email and extract all training requirement details.
The client may write in formal English, casual English, Hinglish,
Hindi, Tamil, Telugu, or any Indian regional language mixed with
English. Understand the intent regardless of language or writing
style.

Extract and return ONLY valid JSON with no extra text:
{{
  "client_name": "full name if found else null",
  "client_company": "company name if found else null",
  "client_email": "reply-to email address",
  "client_phone": "client phone or WhatsApp number if explicitly found else null",
  "technology_needed": "primary technology or skill required",
  "secondary_technologies": ["array of additional skills if any"],
  "duration_days": number or null,
  "duration_hours": number or null,
  "participant_count": number or null,
  "audience_level": "beginner or intermediate or advanced or mixed or null",
  "mode": "online or offline or hybrid or null",
  "location": "city or null if offline",
  "budget_per_day": number or null,
  "budget_total": number or null,
  "budget_currency": "INR or USD or null",
  "timeline_start": "date string or description like next week or null",
  "timeline_flexible": true or false,
  "urgency": "urgent or normal or flexible",
  "special_requirements": "any specific tools versions labs etc or null",
  "language_of_training": "English or Hindi or Tamil etc",
  "email_subject": "original subject line",
  "email_summary": "2 sentence summary of what client needs",
  "confidence": number from 0 to 1 how complete the extraction is,
  "needs_clarification": ["list of important fields that are missing and the client should be asked about"],
  "is_training_request": true or false,
  "sender_is_known_client": false
}}

Email metadata:
From name: {meta.get("from_name") or ""}
From email: {meta.get("from_email") or ""}
Subject: {meta.get("subject") or ""}

Email text:
---
{body_for_gemini[:45000]}
---"""
    return _normalise_extraction(await _gemini_json(prompt, max_tokens=1800), meta)
