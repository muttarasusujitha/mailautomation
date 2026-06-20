import base64
import email as email_lib
import hashlib
import html
import imaplib
import json
import os
import re
import uuid
import logging
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
from googleapiclient.http import MediaFileUpload

from config import get_settings
from agents.email_agent import compose_shortlist_first_email, send_email_async
from agents.pipeline import run_pipeline


logger = logging.getLogger(__name__)


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]
GOOGLE_OAUTH_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES + DRIVE_SCOPES

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

TECHNOLOGY_KEYWORDS = [
    "full stack", "data science", "machine learning", "power bi", "cybersecurity",
    "kubernetes", "devops", "python", "java", "azure", "aws", "tableau", "cloud",
    "genai", "sap", "salesforce", "react", "node",
]

AUTO_REPLY_MARKERS = [
    "out of office", "automatic reply", "auto-reply", "autoreply", "vacation responder",
    "i am away", "away from office", "delivery status notification",
]

TRAINER_THREAD_MAIL_TYPES = {
    "mail1",
    "mail2",
    "mail2_followup",
    "mail3",
    "mail3_slot_followup",
    "mail4",
    "mail5_ok",
    "mail5_reject",
    "trainer_dates_clarification",
    "trainer_commercial_negotiation",
    "ai_extra_question_reply",
}


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
        include_granted_scopes="false",
        prompt="consent",
    )
    return {
        "auth_url": auth_url,
        "state": state,
        "redirect_uri": redirect,
        "required_scopes": GOOGLE_OAUTH_SCOPES,
    }


def save_gmail_oauth_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    if not code:
        raise RuntimeError("Missing Google OAuth authorization code")
    redirect = redirect_uri or _default_redirect_uri()
    flow = _oauth_flow(redirect)
    flow.fetch_token(code=code)
    creds = flow.credentials
    if hasattr(creds, "has_scopes") and not creds.has_scopes(GOOGLE_OAUTH_SCOPES):
        granted_scopes = sorted(getattr(creds, "scopes", None) or [])
        missing_scopes = [scope for scope in GOOGLE_OAUTH_SCOPES if scope not in granted_scopes]
        raise RuntimeError(
            "Google did not grant all required permissions. "
            f"Missing scopes: {', '.join(missing_scopes)}. "
            "Reconnect and approve Gmail, Calendar, and Drive permissions."
        )
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    calendar_service.calendarList().get(calendarId="primary").execute()
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    drive_service.files().list(pageSize=1, fields="files(id,name)").execute()
    return {
        "success": True,
        "connected": True,
        "calendar_connected": True,
        "drive_connected": True,
        "gmail_user": profile.get("emailAddress") or _settings_value("gmail_user"),
        "redirect_uri": redirect,
        "scopes": sorted(getattr(creds, "scopes", None) or []),
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


def looks_like_client_requirement_closed(text: str) -> bool:
    clean = clean_email_body(text or "")
    if not clean:
        return False
    lowered = re.sub(r"\s+", " ", clean.lower()).strip()
    if re.search(r"\b(do\s*not|don't|dont|not)\s+(close|cancel|withdraw)", lowered):
        return False
    closure_patterns = (
        r"\bclose(?:d)?\s+(?:the\s+)?requirement\b",
        r"\brequirement\s+(?:is\s+|was\s+)?closed\b",
        r"\brequirement\s+(?:is\s+|was\s+)?cancelled\b",
        r"\brequirement\s+(?:is\s+|was\s+)?canceled\b",
        r"\brequirement\s+(?:is\s+|was\s+)?withdrawn\b",
        r"\bposition\s+(?:is\s+|was\s+)?closed\b",
        r"\brole\s+(?:is\s+|was\s+)?closed\b",
        r"\bno\s+longer\s+(?:required|needed)\b",
        r"\bnot\s+required\s+anymore\b",
        r"\bfound\s+(?:another|other)\s+trainer\b",
        r"\balready\s+(?:finali[sz]ed|closed|hired|got)\b",
        r"\b(?:too|so|very)\s+late\b",
    )
    return any(re.search(pattern, lowered) for pattern in closure_patterns)


def client_requirement_closure_reason(text: str) -> str:
    clean = re.sub(r"\s+", " ", clean_email_body(text or "")).strip()
    lowered = clean.lower()
    if re.search(r"\b(?:too|so|very)?\s*late\b", lowered):
        return "Client said the requirement is closed because the response was late."
    if re.search(r"\bfound\s+(?:another|other)\s+trainer\b", lowered):
        return "Client said they found another trainer."
    if re.search(r"\balready\s+(?:finali[sz]ed|hired|got)\b", lowered):
        return "Client said the requirement was already finalized."
    if re.search(r"\bcancelled|canceled|withdrawn\b", lowered):
        return "Client cancelled or withdrew the requirement."
    if clean:
        return f"Client asked to close the requirement: {clean[:180]}"
    return "Client asked to close the requirement."


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
    haystack = f"{subject or ''}\n{body_preview or ''}".lower()
    reject_markers = (
        "hotlist", "bench sales", "available consultant", "available candidates",
        "my resume", "attached resume", "application for", "job application",
        "looking for job", "seeking opportunity", "freelance/permanent training position",
        "pfa my resume", "please find attached my resume", "please consider this email",
        "express my interest", "expression of interest", "immediate joiner",
        "job change", "suitable opportunity", "current salary", "expected salary",
        "newsletter", "webinar", "learn to build", "unsubscribe",
        "checking in regarding any upcoming training requirements",
        "scope of opportunity to serve training services",
        "introducing", "ai-powered integrated l&d solutions",
        "credit card was declined", "invoice charge failed", "suspended",
    )
    if any(marker in haystack for marker in reject_markers):
        return False

    request_markers = (
        "need trainer", "require trainer", "required trainer", "looking for trainer",
        "trainer requirement", "training requirement", "corporate training requirement",
        "need a trainer", "we need", "we require", "please share suitable trainer",
        "share trainer profiles", "duration", "participants", "budget",
        "mode:", "technology:", "domain:",
    )
    if any(keyword in subject_haystack for keyword in TRAINING_KEYWORDS) and any(marker in haystack for marker in request_markers):
        return True

    return (
        any(marker in haystack for marker in request_markers)
        and any(keyword in haystack for keyword in TRAINING_KEYWORDS)
    )


def classify_office_mail(subject: str, from_email: str = "", body_preview: str = "") -> str:
    haystack = f"{subject or ''}\n{from_email or ''}\n{body_preview or ''}".lower()
    if any(marker in haystack for marker in (
        "my resume", "attached resume", "pfa my resume", "please find attached my resume",
        "resume attached", "find my resume attached", "resume for your review",
        "application for", "job application", "immediate joiner", "looking for job",
        "job change", "seeking opportunity", "suitable opportunity", "exploring",
        "open to onsite", "open to hybrid", "open to remote", "willing to relocate",
        "offer in hand", "last working day", "current ctc",
        "expected ctc", "notice period", "manual and automation test engineer",
        "qa engineer", "qa automation", "automation engineer", "tester", "istqb",
        "playwright", "tosca automation", "postman", "software testing",
    )):
        return "job_application"
    if any(marker in haystack for marker in (
        "expression of interest", "express my interest", "trainer position",
        "freelance/permanent training position", "training position",
    )):
        return "trainer_interest"
    if any(marker in haystack for marker in (
        "hotlist", "bench sales", "available consultant", "available candidates",
    )):
        return "vendor_hotlist"
    if any(marker in haystack for marker in (
        "newsletter", "webinar", "unsubscribe", "learn to build", "event",
    )):
        return "marketing"
    if any(marker in haystack for marker in (
        "invoice charge failed", "credit card was declined", "suspended",
        "payment failed", "billing", "payment information",
    )):
        return "admin_alert"
    if any(marker in haystack for marker in (
        "following up", "follow up", "checking in", "business opportunity",
        "serve training services", "introducing",
    )):
        return "vendor_followup"
    return "other"


def generate_office_mail_reply(category: str, sender_name: str, subject: str) -> Optional[dict]:
    name = (sender_name or "").strip() or "Candidate"
    signature = "Best Regards,\nRecruitment Team\nClahan Technologies"
    if category == "job_application":
        return {
            "subject": f"Re: {subject or 'Application Received'}",
            "body": (
                f"Dear {name},\n\n"
                "Thank you for sharing your profile with us.\n\n"
                "We have received your application and our team will review your profile. "
                "We will get in touch with you if there is a suitable opening matching your experience and skill set.\n\n"
                "We appreciate your interest in Clahan Technologies.\n\n"
                f"{signature}"
            ),
            "tone": "formal",
            "asks_for_clarification": False,
        }
    if category == "trainer_interest":
        return {
            "subject": f"Re: {subject or 'Trainer Profile Received'}",
            "body": (
                f"Dear {name},\n\n"
                "Thank you for sharing your interest with us.\n\n"
                "Kindly share your domain, total training experience, trainings conducted, certifications, "
                "preferred mode, availability, location, and expected commercials. Our team will review your profile "
                "for suitable training requirements.\n\n"
                f"{signature}"
            ),
            "tone": "formal",
            "asks_for_clarification": True,
        }
    if category == "vendor_hotlist":
        return {
            "subject": f"Re: {subject or 'Hotlist Received'}",
            "body": (
                "Dear Team,\n\n"
                "Thank you for sharing the hotlist.\n\n"
                "We will review the profiles and get back to you if any profile matches our active requirements.\n\n"
                f"{signature}"
            ),
            "tone": "formal",
            "asks_for_clarification": False,
        }
    if category == "vendor_followup":
        return {
            "subject": f"Re: {subject or 'Business Enquiry'}",
            "body": (
                "Dear Team,\n\n"
                "Thank you for reaching out to Clahan Technologies.\n\n"
                "We have noted your message and will connect with you if there is a relevant business or training requirement.\n\n"
                f"{signature}"
            ),
            "tone": "formal",
            "asks_for_clarification": False,
        }
    return None


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
    if hasattr(creds, "has_scopes") and not creds.has_scopes(requested_scopes):
        missing_scopes = [scope for scope in requested_scopes if not creds.has_scopes([scope])]
        raise RuntimeError(
            "Google OAuth token is missing required permission(s): "
            f"{', '.join(missing_scopes)}. Reconnect Google from Settings."
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


def get_drive_service():
    creds = _google_credentials(GOOGLE_OAUTH_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_file_to_drive(
    local_path: str,
    *,
    name: str = "",
    folder_name: str = "TrainerSync Business Reports",
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> Dict[str, Any]:
    service = get_drive_service()

    folder_id = ""
    escaped_folder = folder_name.replace("'", "\\'")
    query = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{escaped_folder}' and trashed=false"
    )
    folder_result = service.files().list(q=query, pageSize=1, fields="files(id,name)").execute()
    folders = folder_result.get("files") or []
    if folders:
        folder_id = folders[0]["id"]
    else:
        folder = service.files().create(
            body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
            fields="id,name",
        ).execute()
        folder_id = folder["id"]

    metadata = {"name": name or os.path.basename(local_path), "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=False)
    uploaded = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink,webContentLink,createdTime",
    ).execute()
    return {
        "success": True,
        "file_id": uploaded.get("id"),
        "name": uploaded.get("name"),
        "web_view_link": uploaded.get("webViewLink"),
        "web_content_link": uploaded.get("webContentLink"),
        "folder_id": folder_id,
        "folder_name": folder_name,
    }


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
        lowered_error = error.lower()
        status["calendar_reconnect_required"] = (
            ("insufficient" in lowered_error and "scope" in lowered_error)
            or "missing calendar permission" in lowered_error
            or "missing scopes" in lowered_error
        )
        if status.get("connected"):
            status["calendar_optional"] = True
            status["calendar_error"] = (
                "Gmail is connected. Calendar/Meet is not connected; click Connect / Renew only when you want Meet scheduling."
                if status["calendar_reconnect_required"]
                else error
            )
        else:
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


def _extract_json_from_text(raw: str, provider: str = "AI") -> Dict[str, Any]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    if raw.startswith("`") and raw.endswith("`"):
        raw = raw[1:-1].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"{provider} did not return JSON. Response: {raw[:300]}")
    return json.loads(raw[start:end + 1])


async def _ollama_json(prompt: str, max_tokens: int = 1600) -> Dict[str, Any]:
    api_url = (
        os.getenv("OLLOMO_API_URL", "").strip()
        or "http://localhost:11434/v1/chat/completions"
    )
    model = os.getenv("OLLOMO_MODEL", "").strip() or "llama3.2:3b"
    timeout_seconds = int(os.getenv("OLLOMO_TIMEOUT_SECONDS", "600") or "600")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON. No markdown, no explanation, no extra text.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(api_url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    raw = ""
    if choices:
        message = choices[0].get("message") or {}
        raw = message.get("content") or choices[0].get("text") or ""
    if not raw:
        raw = data.get("response") or data.get("text") or data.get("output_text") or ""
    return _extract_json_from_text(raw, "Ollama")


async def _ai_json(prompt: str, max_tokens: int = 1600) -> Dict[str, Any]:
    try:
        return await _gemini_json(prompt, max_tokens=max_tokens)
    except Exception as gemini_exc:
        try:
            data = await _ollama_json(prompt, max_tokens=max_tokens)
            data["_ai_provider"] = "ollama"
            data["_gemini_error"] = str(gemini_exc)
            return data
        except Exception as ollama_exc:
            raise RuntimeError(
                f"Gemini failed: {gemini_exc}; Ollama failed: {ollama_exc}"
            ) from ollama_exc


def has_actionable_training_domain(value: Any) -> bool:
    clean = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    if not clean:
        return False
    generic_values = {
        "training",
        "trainer",
        "training requirement",
        "trainer requirement",
        "corporate training",
        "software training",
        "technical training",
        "it training",
        "domain",
        "technology",
        "not specified",
        "unknown",
        "general",
    }
    return clean not in generic_values


def _clean_ai_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return ", ".join(f"{key}: {val}" for key, val in value.items() if str(val).strip())
    return str(value).strip()


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
        "daily_timing": None,
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
    for key in [
        "client_name", "client_company", "client_email", "client_phone", "technology_needed",
        "daily_timing", "audience_level", "mode", "location", "budget_currency",
        "timeline_start", "urgency", "special_requirements", "language_of_training",
        "email_subject", "email_summary",
    ]:
        merged[key] = _clean_ai_text(merged.get(key)) or None
    merged["client_email"] = merged.get("client_email") or meta.get("from_email")
    merged["email_subject"] = merged.get("email_subject") or meta.get("subject")
    merged["secondary_technologies"] = merged.get("secondary_technologies") or []
    merged["needs_clarification"] = merged.get("needs_clarification") or []
    if not has_actionable_training_domain(merged.get("technology_needed")):
        merged["technology_needed"] = None
        existing_needs = {str(item).strip().lower() for item in merged["needs_clarification"]}
        if "training domain/technology" not in existing_needs:
            merged["needs_clarification"].insert(0, "Training domain/technology")
        if merged.get("is_training_request"):
            try:
                merged["confidence"] = min(float(merged.get("confidence") or 0.0), 0.55)
            except Exception:
                merged["confidence"] = 0.55
    deferred_patterns = (
        r"\b(after|post)\s+(the\s+)?(interview|discussion)\b",
        r"\b(will|shall)\s+(share|send|provide|confirm|update)\b",
        r"\b(later|future|afterwards|subsequently)\b",
        r"\b(to\s*be\s*(confirmed|decided|shared|provided)|tbd|tba|na|n/a)\b",
    )
    deferred_fields = [
        "duration_days", "duration_hours", "daily_timing", "audience_level", "mode",
        "budget_per_day", "budget_total", "budget_currency", "timeline_start", "timeline_end",
    ]
    for key in deferred_fields:
        value = merged.get(key)
        if isinstance(value, str) and any(re.search(pattern, value, re.IGNORECASE) for pattern in deferred_patterns):
            merged[key] = None
    try:
        merged["confidence"] = max(0.0, min(1.0, float(merged.get("confidence") or 0)))
    except Exception:
        merged["confidence"] = 0.0
    return merged


def client_requirement_closure_extraction(meta: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    body = meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or ""
    subject = meta.get("subject") or ""
    technology = None
    for keyword in TECHNOLOGY_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", f"{subject}\n{body}", re.IGNORECASE):
            technology = keyword.title()
            break
    extracted = _normalise_extraction({
        "client_name": meta.get("from_name") or None,
        "client_email": meta.get("from_email"),
        "technology_needed": technology,
        "email_subject": subject,
        "email_summary": reason or "Client asked to close the requirement.",
        "confidence": 0.98,
        "needs_clarification": [],
        "is_training_request": False,
        "client_request_closed": True,
        "client_closed_reason": reason or "Client asked to close the requirement.",
    }, meta)
    extracted["needs_clarification"] = []
    extracted["is_training_request"] = False
    extracted["client_request_closed"] = True
    extracted["client_closed_reason"] = reason or "Client asked to close the requirement."
    return extracted


def generate_client_requirement_closed_reply(
    meta: Dict[str, Any],
    reason: str = "",
    signature: str = "",
) -> Dict[str, Any]:
    subject = str(meta.get("subject") or "Training Requirement").strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    client_name = _clean_ai_text(meta.get("from_name")) or "Client"
    delay_context = bool(
        re.search(r"\blate\b", str(reason or ""), re.IGNORECASE)
        or re.search(r"\blate\b", str(meta.get("clean_body") or ""), re.IGNORECASE)
    )
    opening = (
        "Sorry for the delayed response."
        if delay_context else
        "Thank you for the update."
    )
    footer = (signature or "Regards,\nRecruitment Team,\nClahan Technologies").strip()
    body = (
        f"Dear {client_name},\n\n"
        f"{opening} We understand that this requirement has been closed, and we will not proceed further on it.\n\n"
        "For any future training requirements, please feel free to contact us. "
        "We will be happy to support you with suitable trainer profiles promptly.\n\n"
        f"{footer}"
    )
    return {
        "subject": subject,
        "body": body,
        "tone": "polite_closure_acknowledgement",
        "asks_for_clarification": False,
        "client_request_closed_ack": True,
    }


def _field_from_text(text: str, label: str) -> Optional[str]:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text or "")
    return match.group(1).strip() if match else None


def _heuristic_training_extraction(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Advanced heuristic fallback for extracting training requirements from client emails.

    Used when AI extraction fails (rate limits, network issues). Handles:
    - Structured emails with labeled fields (Technology: ..., Duration: ...)
    - Unstructured natural language emails
    - Mixed language (English/Hinglish/Regional)
    - Multiple technology mentions
    - Various date/time formats
    - Budget in INR/USD with different formats
    """
    body = meta.get("clean_body") or meta.get("raw_body") or ""
    subject = meta.get("subject") or ""
    haystack = f"{subject}\n{body}"
    haystack_lower = haystack.lower()

    # --- Technology extraction (multi-pass) ---
    # Pass 1: Explicit labeled field
    tech = _field_from_text(body, "Technology")
    if not tech:
        tech = _field_from_text(body, "Domain")
    if not tech:
        tech = _field_from_text(body, "Skill")
    if not tech:
        tech = _field_from_text(body, "Training on")
    if not tech:
        tech = _field_from_text(body, "Subject")

    # Pass 2: Technology keywords in context (prioritize subject line)
    EXTENDED_TECH_KEYWORDS = [
        # Cloud & DevOps
        "aws", "azure", "gcp", "google cloud", "devops", "kubernetes", "docker",
        "terraform", "ansible", "jenkins", "ci/cd", "cicd", "openshift",
        "cloudformation", "eks", "aks", "gke", "helm", "istio", "argocd",
        # Programming
        "python", "java", "javascript", "typescript", "golang", "go lang",
        "c#", "c++", "rust", "kotlin", "swift", "scala", "ruby",
        # Web/Mobile
        "react", "angular", "vue", "node.js", "nodejs", "express",
        "full stack", "fullstack", "frontend", "backend", "mern", "mean",
        "next.js", "nextjs", "flutter", "react native", "spring boot",
        # Data & AI
        "data science", "machine learning", "deep learning", "artificial intelligence",
        "genai", "generative ai", "llm", "nlp", "computer vision",
        "data engineering", "data analytics", "big data", "spark", "hadoop",
        "snowflake", "databricks", "airflow", "kafka",
        # BI & Visualization
        "power bi", "tableau", "looker", "qlik", "excel", "advanced excel",
        # Database
        "sql", "mysql", "postgresql", "mongodb", "oracle", "sql server",
        "nosql", "dynamodb", "redis", "cassandra",
        # Enterprise
        "sap", "sap s/4hana", "sap hana", "sap fico", "sap mm", "sap sd",
        "salesforce", "servicenow", "workday", "oracle erp",
        # Security
        "cybersecurity", "cyber security", "information security", "ethical hacking",
        "penetration testing", "soc", "siem", "network security",
        # Testing
        "selenium", "playwright", "cypress", "jmeter", "api testing",
        "automation testing", "manual testing", "performance testing",
        # Agile/Management
        "agile", "scrum", "safe", "project management", "pmp",
        "itil", "prince2", "six sigma", "lean",
        # Soft Skills
        "communication skills", "leadership", "soft skills",
        "presentation skills", "team building", "conflict resolution",
    ]

    secondary_techs = []
    if not tech:
        # Check subject first (highest priority)
        for keyword in EXTENDED_TECH_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", subject, re.IGNORECASE):
                tech = keyword.title()
                break

    if not tech:
        # Check body
        for keyword in EXTENDED_TECH_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", haystack, re.IGNORECASE):
                if not tech:
                    tech = keyword.title()
                elif keyword.title() != tech:
                    secondary_techs.append(keyword.title())
                if len(secondary_techs) >= 4:
                    break
    else:
        # Still look for secondary technologies
        for keyword in EXTENDED_TECH_KEYWORDS:
            if keyword.title() != tech and re.search(rf"\b{re.escape(keyword)}\b", haystack, re.IGNORECASE):
                secondary_techs.append(keyword.title())
                if len(secondary_techs) >= 4:
                    break

    # --- Client contact extraction ---
    client_phone = (
        _field_from_text(body, "Phone")
        or _field_from_text(body, "Mobile")
        or _field_from_text(body, "Contact No")
        or _field_from_text(body, "Contact Number")
        or _field_from_text(body, "WhatsApp")
        or _field_from_text(body, "Cell")
        or _field_from_text(body, "Mob")
    )
    # Also try regex for phone numbers in body
    if not client_phone:
        phone_match = re.search(r"(?:\+?91[\s.-]?)?[6-9]\d[\s.-]?\d[\s.-]?\d[\s.-]?\d[\s.-]?\d[\s.-]?\d[\s.-]?\d[\s.-]?\d[\s.-]?\d", body)
        if phone_match:
            client_phone = re.sub(r"[\s.-]", "", phone_match.group(0))

    # --- Client company extraction ---
    client_company = (
        _field_from_text(body, "Company")
        or _field_from_text(body, "Organization")
        or _field_from_text(body, "Organisation")
        or _field_from_text(body, "Client")
        or _field_from_text(body, "Firm")
    )
    # Try to extract from email signature domain
    if not client_company:
        from_email = meta.get("from_email", "")
        if "@" in from_email:
            domain = from_email.split("@")[1]
            if domain and not any(free in domain for free in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"]):
                client_company = domain.split(".")[0].title()

    # --- Participant count extraction ---
    participants = _field_from_text(body, "Participants")
    if not participants:
        participants = _field_from_text(body, "Batch Size")
    if not participants:
        participants = _field_from_text(body, "No of Participants")
    if not participants:
        participants = _field_from_text(body, "Number of Participants")
    if not participants:
        participants = _field_from_text(body, "Headcount")
    # Try regex: "15 participants", "batch of 20"
    if not participants:
        part_match = re.search(r"(\d{1,3})\s*(?:participants?|people|attendees?|learners?|candidates?)", haystack_lower)
        if part_match:
            participants = part_match.group(1)
        else:
            batch_match = re.search(r"batch\s*(?:of|size)?\s*[:\-]?\s*(\d{1,3})", haystack_lower)
            if batch_match:
                participants = batch_match.group(1)

    participant_count = None
    if participants:
        participant_match = re.search(r"\d+", str(participants))
        if participant_match:
            participant_count = int(participant_match.group(0))

    # --- Duration extraction ---
    duration = _field_from_text(body, "Duration")
    if not duration:
        duration = _field_from_text(body, "Training Duration")
    if not duration:
        duration = _field_from_text(body, "No of Days")
    if not duration:
        duration = _field_from_text(body, "Number of Days")

    duration_days = None
    duration_hours = None
    if duration:
        days_match = re.search(r"(\d+)\s*(?:days?|d\b)", duration, re.IGNORECASE)
        hours_match = re.search(r"(\d+)\s*(?:hours?|hrs?|h\b)", duration, re.IGNORECASE)
        weeks_match = re.search(r"(\d+)\s*(?:weeks?|wks?)", duration, re.IGNORECASE)
        if days_match:
            duration_days = int(days_match.group(1))
        elif weeks_match:
            duration_days = int(weeks_match.group(1)) * 5  # business days
        if hours_match:
            duration_hours = int(hours_match.group(1))
    else:
        # Try to find in body: "5 days training", "40 hours"
        dur_match = re.search(r"(\d{1,3})\s*(?:days?|d)\s*(?:training|program|course)?", haystack_lower)
        if dur_match:
            duration_days = int(dur_match.group(1))
        else:
            hrs_match = re.search(r"(\d{1,3})\s*(?:hours?|hrs?)\s*(?:training|program|course)?", haystack_lower)
            if hrs_match:
                duration_hours = int(hrs_match.group(1))

    # --- Daily timing extraction ---
    daily_timing = (
        _field_from_text(body, "Daily Timings")
        or _field_from_text(body, "Daily Timing")
        or _field_from_text(body, "Timings")
        or _field_from_text(body, "Timing")
        or _field_from_text(body, "Time")
        or _field_from_text(body, "Training Time")
        or _field_from_text(body, "Session Time")
        or _field_from_text(body, "Schedule")
    )
    # Try regex for time ranges
    if not daily_timing:
        time_match = re.search(
            r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*(?:to|-|–)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            haystack, re.IGNORECASE
        )
        if time_match:
            daily_timing = f"{time_match.group(1)} to {time_match.group(2)}"

    # --- Timeline/dates extraction ---
    timeline_start = (
        _field_from_text(body, "Start Date")
        or _field_from_text(body, "Training Date")
        or _field_from_text(body, "Training Dates")
        or _field_from_text(body, "Preferred Date")
        or _field_from_text(body, "Dates")
        or _field_from_text(body, "Date")
        or _field_from_text(body, "From")
        or _field_from_text(body, "Starting")
        or _field_from_text(body, "Commence")
    )

    # --- Audience level extraction ---
    audience_level = (
        _field_from_text(body, "Audience Level")
        or _field_from_text(body, "Level")
        or _field_from_text(body, "Audience")
        or _field_from_text(body, "Skill Level")
    )
    if not audience_level:
        if re.search(r"\b(beginner|basic|foundation|introduct)", haystack_lower):
            audience_level = "beginner"
        elif re.search(r"\b(intermediate|mid.?level)", haystack_lower):
            audience_level = "intermediate"
        elif re.search(r"\b(advanced|expert|senior|deep.?dive)", haystack_lower):
            audience_level = "advanced"
        elif re.search(r"\b(mixed|all levels?|varied)", haystack_lower):
            audience_level = "mixed"

    # --- Mode extraction ---
    mode = (_field_from_text(body, "Mode") or _field_from_text(body, "Training Mode") or "").lower() or None
    if not mode:
        if re.search(r"\b(online|virtual|remote|zoom|teams|webex|google meet)\b", haystack_lower):
            mode = "online"
        elif re.search(r"\b(offline|classroom|in.?person|onsite|on.?site|physical)\b", haystack_lower):
            mode = "offline"
        elif re.search(r"\b(hybrid|blended)\b", haystack_lower):
            mode = "hybrid"

    # --- Location extraction ---
    location = _field_from_text(body, "Location") or _field_from_text(body, "City") or _field_from_text(body, "Venue")

    # --- Budget extraction ---
    budget = (
        _field_from_text(body, "Budget")
        or _field_from_text(body, "Rate")
        or _field_from_text(body, "Commercial")
        or _field_from_text(body, "Charges")
        or _field_from_text(body, "Cost")
        or _field_from_text(body, "Price")
    )
    budget_number = None
    budget_currency = None
    is_per_day = False
    if budget:
        number_match = re.search(r"[\d,]+(?:\.\d+)?", budget)
        if number_match:
            budget_number = int(float(number_match.group(0).replace(",", "")))
        if re.search(r"\binr\b|rs\.?|₹|rupee", budget, re.IGNORECASE):
            budget_currency = "INR"
        elif re.search(r"\busd\b|\$|dollar", budget, re.IGNORECASE):
            budget_currency = "USD"
        is_per_day = bool(re.search(r"per\s*day|/day|per\s*session|daily", budget, re.IGNORECASE))
    else:
        # Try to find budget mentions in body
        budget_match = re.search(
            r"(?:budget|rate|commercial|charges?|cost)\s*[:\-]?\s*(?:(?:inr|rs\.?|₹|usd|\$)\s*)?(\d[\d,]*(?:\.\d+)?)",
            haystack_lower
        )
        if budget_match:
            budget_number = int(float(budget_match.group(1).replace(",", "")))
            context = haystack_lower[max(0, budget_match.start() - 20):budget_match.end() + 30]
            if re.search(r"inr|rs\.?|₹|rupee", context):
                budget_currency = "INR"
            elif re.search(r"usd|\$|dollar", context):
                budget_currency = "USD"
            is_per_day = bool(re.search(r"per\s*day|/day|per\s*session|daily", context))

    # --- Urgency detection ---
    urgency = "normal"
    if re.search(r"\b(urgent|asap|immediately|critical|priority|rush)\b", haystack_lower):
        urgency = "urgent"
    elif re.search(r"\b(flexible|no rush|whenever|at your convenience)\b", haystack_lower):
        urgency = "flexible"

    # --- Language of training ---
    language = "English"
    if re.search(r"\bhindi\b", haystack_lower):
        language = "Hindi"
    elif re.search(r"\btamil\b", haystack_lower):
        language = "Tamil"
    elif re.search(r"\btelugu\b", haystack_lower):
        language = "Telugu"
    elif re.search(r"\bkannada\b", haystack_lower):
        language = "Kannada"

    # --- Special requirements ---
    special_requirements = _field_from_text(body, "Special Requirements")
    if not special_requirements:
        special_requirements = _field_from_text(body, "Requirements")
    if not special_requirements:
        special_requirements = _field_from_text(body, "Additional Requirements")
    if not special_requirements:
        special_requirements = _field_from_text(body, "Lab")
    if not special_requirements:
        special_requirements = _field_from_text(body, "Tools")

    # --- Needs clarification ---
    needs = []
    if not tech:
        needs.append("Training domain/technology")
    if not audience_level:
        needs.append("Audience level (Beginner / Intermediate / Advanced)")
    if not timeline_start:
        needs.append("Preferred training dates")
    if not daily_timing:
        needs.append("Daily training timings")
    if not mode:
        needs.append("Training mode (Online / Offline / Hybrid)")
    if not duration_days and not duration_hours:
        needs.append("Training duration")

    # --- Confidence calculation ---
    confidence = 0.40  # base
    if tech:
        confidence += 0.20
    if participant_count:
        confidence += 0.08
    if duration_days or duration_hours:
        confidence += 0.08
    if daily_timing:
        confidence += 0.05
    if timeline_start:
        confidence += 0.05
    if budget_number:
        confidence += 0.05
    if mode:
        confidence += 0.04
    if audience_level:
        confidence += 0.03
    if location:
        confidence += 0.02
    confidence = round(min(confidence, 0.92), 2)

    return {
        "client_name": meta.get("from_name") or None,
        "client_company": client_company,
        "client_email": meta.get("from_email"),
        "client_phone": client_phone,
        "technology_needed": tech,
        "secondary_technologies": secondary_techs[:5],
        "duration_days": duration_days,
        "duration_hours": duration_hours,
        "daily_timing": daily_timing,
        "participant_count": participant_count,
        "audience_level": audience_level,
        "mode": mode,
        "location": location,
        "budget_per_day": budget_number if is_per_day else None,
        "budget_total": budget_number if budget_number and not is_per_day else None,
        "budget_currency": budget_currency,
        "timeline_start": timeline_start,
        "timeline_flexible": bool(re.search(r"\bflexible\b|\btentative\b|\bapprox", haystack_lower)),
        "urgency": urgency,
        "special_requirements": special_requirements,
        "language_of_training": language,
        "email_subject": subject,
        "email_summary": f"Client needs {tech or 'a'} trainer for a corporate training requirement." + (
            f" Duration: {duration_days} days." if duration_days else ""
        ) + (
            f" {participant_count} participants." if participant_count else ""
        ),
        "confidence": confidence,
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

    latest_client_text = meta.get("clean_body") or meta.get("raw_body") or meta.get("snippet") or ""
    if looks_like_client_requirement_closed(latest_client_text):
        reason = client_requirement_closure_reason(latest_client_text)
        meta["extracted"] = client_requirement_closure_extraction(meta, reason)
        return meta

    body_for_gemini = meta.get("clean_body") or meta.get("raw_body") or ""
    if meta.get("attachments_text"):
        body_for_gemini = f"{body_for_gemini}\n\nPDF/RFP attachment text:\n{meta['attachments_text']}"

    prompt = f"""You are an expert email analyst for Clahan Technologies, a premium corporate training company in India that connects clients with freelance trainers.

TASK: Read this client email and extract ALL training requirement details with high accuracy.

LANGUAGE HANDLING:
- The client may write in formal English, casual English, Hinglish, Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, or any Indian regional language mixed with English.
- Understand the intent regardless of language, slang, abbreviations, or writing style.
- Common abbreviations: "pls" = please, "req" = requirement, "dev" = development, "tech" = technology, "trng" = training, "avail" = availability/available

CRITICAL BUSINESS RULES:
1. Technology/Domain is the MOST IMPORTANT field. Extract it even if mentioned casually.
   - "We need someone for DevOps" → technology_needed: "DevOps"
   - "Python ka trainer chahiye" → technology_needed: "Python"
   - "AWS + Kubernetes training" → technology_needed: "AWS", secondary: ["Kubernetes"]
   - If ONLY generic words like "training" or "trainer" without domain → technology_needed: null

2. Do NOT ask for trainer name. Clahan finds trainers. Only extract what the CLIENT provides.

3. Extract client_phone ONLY if explicitly written (not from email signatures of other forwarded emails).

4. For budget: Extract the NUMBER and CURRENCY. "25k per day" = budget_per_day: 25000, budget_currency: "INR". "1.5L total" = budget_total: 150000.

5. For dates: Convert relative dates. "Next Monday" = actual date. "2nd week of July" = approximate date string.

6. Confidence scoring:
   - 0.9+ = All critical fields present (tech, duration, dates, mode, participants)
   - 0.7-0.9 = Technology + some details present
   - 0.5-0.7 = Technology present but many details missing
   - 0.3-0.5 = Might be a training request but very unclear
   - <0.3 = Probably not a training request

7. is_training_request = true ONLY if the email is genuinely asking for a trainer or training service. NOT for:
   - Job applications, vendor pitches, newsletters, invoices, general follow-ups
   - "Expression of interest" from trainers wanting to join Clahan's panel

EXTRACTION OUTPUT (return ONLY valid JSON, no markdown, no explanation):
{{
  "client_name": "full name of the person requesting training (from email body or signature, not just From header) or null",
  "client_company": "company/organization name if mentioned or inferable from email domain, else null",
  "client_email": "the email to reply to (usually from_email unless different reply-to is specified)",
  "client_phone": "phone/WhatsApp number if EXPLICITLY provided in body, else null",
  "technology_needed": "primary technology/domain/skill for the training, null if not mentioned",
  "secondary_technologies": ["additional technologies if training covers multiple areas"],
  "duration_days": "number of training days or null",
  "duration_hours": "total training hours if specified differently from days, or null",
  "daily_timing": "daily training schedule like '9:30 AM to 5:30 PM IST' or null",
  "participant_count": "number of participants/learners or null",
  "audience_level": "beginner or intermediate or advanced or mixed or null",
  "mode": "online or offline or hybrid or null",
  "location": "city/venue for offline training or null",
  "budget_per_day": "numeric budget per day/session or null",
  "budget_total": "numeric total budget or null",
  "budget_currency": "INR or USD or null",
  "timeline_start": "training start date or description or null",
  "timeline_flexible": "true if dates are flexible/tentative, false otherwise",
  "urgency": "urgent (need within days) or normal (standard 1-2 weeks) or flexible (no rush)",
  "special_requirements": "any specific tool versions, lab setup, prerequisites, certification prep, etc. or null",
  "language_of_training": "English or Hindi or Tamil or Telugu or Kannada or other, default English",
  "email_subject": "original email subject line",
  "email_summary": "2-3 sentence concise summary of what the client needs and key details",
  "confidence": "0.0 to 1.0 based on extraction completeness",
  "needs_clarification": ["list of critical missing fields the client should be asked about"],
  "is_training_request": "true or false - is this genuinely a training requirement email?"
}}

EMAIL METADATA:
From name: {meta.get("from_name") or "Unknown"}
From email: {meta.get("from_email") or "Unknown"}
Subject: {meta.get("subject") or "(no subject)"}

EMAIL BODY:
---
{body_for_gemini[:45000]}
---"""

    try:
        extracted = await _ai_json(prompt, max_tokens=2000)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {429, 503}:
            raise
        extracted = _heuristic_training_extraction(meta)
    except (ValueError, json.JSONDecodeError):
        extracted = _heuristic_training_extraction(meta)
    except Exception:
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
    prompt = f"""You extract calendar scheduling confirmations for Clahan Technologies.

The client has replied after Clahan sent trainer availability slots. Determine whether the client selected or proposed a concrete interview/discussion date and time.

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
        data = await _ai_json(prompt, max_tokens=700)
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
    has_domain = has_actionable_training_domain(extracted.get("technology_needed"))
    technology = extracted.get("technology_needed") if has_domain else "your training"
    raw_needs = list(extracted.get("needs_clarification") or [])
    budget = extracted.get("budget_total") or extracted.get("budget_per_day")
    original_subject = extracted.get("email_subject") or context.get("subject") or "Training Requirement"
    signature = context.get("reply_signature") or "Best Regards,\nRecruitment Team\nClahan Technologies"
    if signature.strip() == "Regards,\nRecruitment Team,\nClahan Technologies":
        signature = "Best Regards,\nRecruitment Team\nClahan Technologies"

    def has_any(*keys: str) -> bool:
        return any(str(extracted.get(key) or "").strip() for key in keys)

    field_terms = {
        "duration": ("duration", "days", "hours", "training hours"),
        "dates": ("date", "start date", "end date", "schedule", "timeline"),
        "timings": ("timing", "time", "daily"),
        "audience": ("audience", "level", "basic", "beginner", "intermediate", "advanced", "mixed"),
        "mode": ("mode", "online", "offline", "classroom", "hybrid"),
        "budget": ("budget", "commercial", "charge", "rate", "price", "cost"),
    }
    provided = {
        "domain": has_domain,
        "duration": has_any("duration_days", "duration_hours", "duration_text", "training_duration"),
        "dates": has_any("timeline_start", "timeline_end", "training_dates", "start_date", "end_date"),
        "timings": has_any("daily_timing", "timing", "training_timing", "daily_timings"),
        "audience": has_any("audience_level", "level"),
        "mode": has_any("mode", "training_mode", "preferred_mode"),
        "budget": bool(budget),
    }

    def need_is_known_detail_field(item: str) -> bool:
        text = str(item or "").lower()
        return any(any(term in text for term in terms) for terms in field_terms.values())

    needs = [item for item in raw_needs if item and not need_is_known_detail_field(str(item))]
    required_missing = [
        ("domain", "Training domain/technology"),
        ("duration", "Training duration"),
        ("dates", "Preferred training dates"),
        ("timings", "Daily training timings"),
        ("audience", "Audience level (Beginner / Intermediate / Advanced)"),
        ("mode", "Training mode (Online / Offline / Hybrid)"),
    ]
    existing_need_text = {str(item).strip().lower() for item in needs}
    for key, label in required_missing:
        if key == "domain":
            missing = not has_domain
        else:
            missing = not provided[key]
        if missing and label.lower() not in existing_need_text:
            needs.append(label)
    if not provided["budget"] and not any("commercial" in str(item).lower() or "budget" in str(item).lower() or "charge" in str(item).lower() for item in needs):
        needs.append("Budget or expected commercial charges per day/session")
    needs_text = "\n".join(f"- {item}" for item in needs) if needs else "- No clarification required"

    prompt = f"""You are the recruitment team at Clahan Technologies, a premium
corporate training company based in India.

Write a professional reply to this client email. The client has
enquired about {technology} training. Your reply must:
- Acknowledge their specific requirement by name
- If important details are missing, do not promise final trainer profiles yet.
  Ask the client to share the missing details, but clearly say Clahan will begin an initial trainer search
  based on the available technology/domain details.
- If enough details are available, confirm you are shortlisting trainers and will share profiles within 24 hours.
- Missing details to ask for, if listed:
{needs_text}
- If budget is mentioned acknowledge it
- Keep it under 150 words
- End with: Regards, Recruitment Team, Clahan Technologies

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

    if needs:
        body = (
            f"Dear Client,\n\n"
            f"Thank you for sharing your {technology} training requirement.\n\n"
            "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
            + "\n".join(f"* {item}" for item in needs)
            + (
                f"\n\nMeanwhile, we will begin an initial trainer search based on the {technology} domain "
                "and the information currently available. Once we receive the above details, we will refine the shortlist "
                "and share the most relevant trainer profiles for your review.\n\n"
                if has_domain else
                "\n\nOnce you confirm the domain/technology, we will begin trainer matching and share the most relevant profiles for your review.\n\n"
            )
            + "We look forward to your response.\n\n"
            f"{signature}"
        )
        return {
            "subject": f"Request for Additional Details - {technology.title() if not has_domain else technology} Trainer Requirement",
            "body": body,
            "whatsapp_message": (
                f"Client shared {technology} requirement. Start initial trainer matching by domain; details can be refined later."
                if has_domain else
                "Client shared a training requirement, but domain/technology is missing. Ask for the domain before trainer matching."
            ),
            "tone": "formal",
            "asks_for_clarification": True,
        }

    try:
        reply = await _ai_json(prompt, max_tokens=900)
    except Exception:
        reply = {
            "subject": f"Re: {original_subject}",
            "body": (
                f"Hi,\n\nThank you for sharing the {technology} training requirement. "
                "We are reviewing suitable trainer profiles and will get back to you shortly. "
                "If there are any additional details around schedule, audience level, or delivery expectations, "
                "please share them with us.\n\nRegards,\nRecruitment Team,\nClahan Technologies"
            ),
            "whatsapp_message": f"New {technology} training requirement received. Please review the client inbox.",
            "tone": "formal",
            "asks_for_clarification": bool(needs),
        }
    subject = str(reply.get("subject") or f"Re: {original_subject}").strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    body = str(reply.get("body") or "").strip()
    if "Clahan Technologies" not in body:
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
    return bool(await find_duplicate_requirement(extracted, db))


async def find_duplicate_requirement(extracted: dict, db) -> Optional[dict]:
    technology = _clean_ai_text(extracted.get("technology_needed"))
    if not technology:
        return None

    client_email = _clean_ai_text(extracted.get("client_email")).lower()
    query: Dict[str, Any] = {
        "created_at": {"$gte": utc_now() - timedelta(days=7)},
        "technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
    }
    if not client_email:
        return None

    query["client_email"] = {"$regex": f"^{re.escape(client_email)}$", "$options": "i"}

    timeline = _clean_ai_text(extracted.get("timeline_start"))
    if timeline:
        query["timeline_start"] = {"$regex": f"^{re.escape(timeline)}$", "$options": "i"}

    participant_count = extracted.get("participant_count")
    if participant_count not in (None, ""):
        query["participant_count"] = participant_count

    return await db["requirements"].find_one(query, {"_id": 0}, sort=[("created_at", -1)])


async def ensure_requirement_from_email(extracted: dict, email_id: str, db) -> str:
    if not has_actionable_training_domain(extracted.get("technology_needed")):
        return ""
    existing = await find_duplicate_requirement(extracted, db)
    if existing and existing.get("requirement_id"):
        await db["requirements"].update_one(
            {"requirement_id": existing["requirement_id"]},
            {"$set": {
                "last_client_email_id": email_id,
                "last_client_email_at": utc_now(),
                "auto_match_status": existing.get("auto_match_status") or "queued_duplicate",
            }},
        )
        await auto_match_trainers_for_requirement(db, existing)
        return existing["requirement_id"]
    return await create_requirement_from_email(extracted, email_id, db)


async def mark_client_requirement_closed(
    db,
    from_email: str = "",
    requirement_id: str = "",
    reason: str = "",
    email_id: str = "",
    subject: str = "",
    body: str = "",
) -> str:
    closed_statuses = ["closed", "completed", "fulfilled", "inactive", "cancelled", "archived"]
    req = None
    if requirement_id:
        req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    client_email = _clean_ai_text(from_email).lower()
    if not req and client_email:
        active_query = {
            "client_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
            "status": {"$nin": closed_statuses},
        }
        req = await db["requirements"].find_one(
            active_query,
            {"_id": 0},
            sort=[("last_client_email_at", -1), ("created_at", -1)],
        )
    if not req and client_email:
        req = await db["requirements"].find_one(
            {"client_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"}},
            {"_id": 0},
            sort=[("last_client_email_at", -1), ("created_at", -1)],
        )
    req_id = (req or {}).get("requirement_id") or requirement_id or ""
    if not req_id:
        return ""

    closed_at = utc_now()
    body_excerpt = re.sub(r"\s+", " ", clean_email_body(body or "")).strip()[:500]
    update_doc = {
        "status": "closed",
        "close_date": closed_at,
        "client_closed_at": closed_at,
        "client_closed_reason": reason or "Client asked to close the requirement.",
        "client_closed_email_id": email_id,
        "client_closed_subject": subject or "",
        "client_closed_body_excerpt": body_excerpt,
        "closed_by": "client_email",
        "auto_match_status": "client_closed",
        "trainer_outreach_status": "stopped_client_closed",
        "last_client_email_id": email_id,
        "last_client_email_at": closed_at,
        "updated_at": closed_at,
    }
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": update_doc},
    )
    await db["shortlists"].update_many(
        {"requirement_id": req_id},
        {"$set": {
            "status": "closed",
            "pipeline_status": "client_closed",
            "client_closed_at": closed_at,
            "client_closed_reason": update_doc["client_closed_reason"],
            "updated_at": closed_at,
        }},
    )
    return req_id


def _normalise_thread_subject(subject: str = "") -> str:
    value = re.sub(r"(?i)^\s*(re|fw|fwd)\s*:\s*", "", str(subject or "")).strip()
    value = re.sub(r"\s+", " ", value).lower()
    return value


def _trainer_reply_signal(body: str = "") -> bool:
    text = re.sub(r"\s+", " ", clean_email_body(body or "").lower()).strip()
    if not text:
        return False
    markers = (
        "trainer",
        "trainersync team",
        "calhan technologies team",
        "i am available",
        "available for the following",
        "time slots",
        "slot 1",
        "slot 2",
        "slot 3",
        "years of experience",
        "trainings conducted",
        "relevant certifications",
        "expected commercial",
        "commercial charges",
        "current location",
    )
    has_time = bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text, flags=re.I))
    has_slot_language = bool(re.search(r"\b(?:slot|available|availability|interview|discussion)\b", text, flags=re.I))
    return any(marker in text for marker in markers) or (has_time and has_slot_language)


async def find_matching_trainer_outbound_thread(
    db,
    from_email: str = "",
    subject: str = "",
    body: str = "",
) -> Optional[dict]:
    sender = _clean_ai_text(from_email).lower()
    if not sender:
        return None
    candidates = await db["email_logs"].find(
        {
            "to_email": {"$regex": f"^{re.escape(sender)}$", "$options": "i"},
            "status": "sent",
            "mail_type": {"$in": sorted(TRAINER_THREAD_MAIL_TYPES)},
        },
        {"_id": 0},
    ).sort("sent_at", -1).limit(30).to_list(30)
    if not candidates:
        return None

    reply_subject = _normalise_thread_subject(subject)
    body_text = clean_email_body(body or "")
    body_lower = body_text.lower()
    has_trainer_signal = _trainer_reply_signal(body_text)

    best: Optional[dict] = None
    best_score = 0
    for item in candidates:
        sent_subject = _normalise_thread_subject(item.get("subject") or "")
        trainer_name = _clean_ai_text(item.get("trainer_name")).lower()
        mail_type = str(item.get("mail_type") or "")
        score = 0
        if sent_subject and reply_subject and (sent_subject in reply_subject or reply_subject in sent_subject):
            score += 120
        if "interview slot booking" in reply_subject and mail_type in {"mail3", "mail3_slot_followup", "ai_extra_question_reply"}:
            score += 160
        if "additional details required" in reply_subject and mail_type in {"mail2", "mail2_followup"}:
            score += 120
        if "training requirement" in reply_subject and mail_type in {"mail1", "mail2", "mail2_followup"}:
            score += 70
        if trainer_name and trainer_name in body_lower:
            score += 100
        if has_trainer_signal:
            score += 60
        if mail_type.startswith("mail") and item.get("requirement_id") and item.get("trainer_id"):
            score += 20
        if score > best_score:
            best_score = score
            best = item

    return best if best_score >= 100 else None


async def record_trainer_reply_from_client_inbox(
    db,
    meta: Dict[str, Any],
    trainer_thread: dict,
) -> dict:
    now = utc_now()
    email_id = meta.get("email_id") or f"IMAP-TRAINER-{uuid.uuid4().hex[:8].upper()}"
    body = meta.get("clean_body") or meta.get("raw_body") or ""
    message_id_header = meta.get("message_id_header") or ""
    requirement_id = trainer_thread.get("requirement_id") or ""
    trainer_id = trainer_thread.get("trainer_id") or ""
    trainer_name = trainer_thread.get("trainer_name") or meta.get("from_name") or ""

    await db["email_logs"].update_one(
        {"email_id": trainer_thread.get("email_id")},
        {"$set": {
            "reply_received": True,
            "reply_text": body,
            "reply_subject": meta.get("subject") or "",
            "reply_message_id": message_id_header,
            "replied_at": now,
            "trainer_reply_routed_from_client_inbox": True,
            "trainer_reply_inbound_email_id": email_id,
            "updated_at": now,
        }},
    )

    conversation_query: Dict[str, Any] = {
        "direction": "received",
        "from_email": {"$regex": f"^{re.escape(meta.get('from_email') or '')}$", "$options": "i"},
        "source_email_id": trainer_thread.get("email_id") or "",
    }
    if message_id_header:
        conversation_query["message_id_header"] = message_id_header
    else:
        conversation_query["body"] = body

    existing_conversation = await db["conversations"].find_one(conversation_query, {"_id": 0, "email_id": 1})
    if not existing_conversation:
        await db["conversations"].insert_one({
            "email_id": email_id,
            "source_email_id": trainer_thread.get("email_id") or "",
            "message_id_header": message_id_header,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": requirement_id,
            "from_email": meta.get("from_email") or "",
            "from_name": meta.get("from_name") or "",
            "to_email": meta.get("from_email") or "",
            "subject": meta.get("subject") or "",
            "body": body,
            "direction": "received",
            "status": "received",
            "mail_type": "reply",
            "source": "client_inbox_trainer_thread",
            "sent_at": meta.get("received_at") or now,
            "created_at": now,
        })

    extracted = {
        "is_training_request": False,
        "client_email": meta.get("from_email") or "",
        "client_name": meta.get("from_name") or None,
        "email_subject": meta.get("subject") or "",
        "email_summary": "Inbound message matched an existing trainer outreach thread and was routed as a trainer reply.",
        "confidence": 0.99,
        "routed_to_trainer_reply": True,
    }
    inbox_doc = {
        **meta,
        "extracted": extracted,
        "generated_reply": {},
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "status": "routed_to_trainer_reply",
        "confidence": 0.99,
        "extraction_error": "",
        "auto_send_eligible": False,
        "sent_at": None,
        "sent_by": None,
        "trainer_reply_source_email_id": trainer_thread.get("email_id") or "",
        "trainer_reply_mail_type": trainer_thread.get("mail_type") or "",
        "whatsapp_notified": False,
        "created_at": now,
        "updated_at": now,
    }
    await db["client_emails"].update_one(
        {"email_id": email_id},
        {"$setOnInsert": inbox_doc},
        upsert=True,
    )
    return inbox_doc


async def get_email_auto_smtp_config(db) -> Dict[str, Any]:
    settings_doc = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "emailCfg": 1},
    )
    email_cfg = (settings_doc or {}).get("emailCfg") or {}
    return {key: value for key, value in email_cfg.items() if value not in (None, "")}


async def get_email_auto_imap_config(db) -> Dict[str, Any]:
    email_cfg = await get_email_auto_smtp_config(db)
    smtp_host = str(email_cfg.get("smtpHost") or "").lower()
    smtp_user = str(email_cfg.get("smtpUser") or "").strip()
    env_gmail_user = _settings_value("gmail_user")
    env_gmail_pass = _settings_value("gmail_app_password") or _settings_value("gmail_pass")
    hostinger = "hostinger" in smtp_host or smtp_user.endswith("@clahantechnologies.com")
    return {
        "imapHost": email_cfg.get("imapHost") or ("imap.hostinger.com" if hostinger else "imap.gmail.com"),
        "imapPort": int(email_cfg.get("imapPort") or 993),
        "imapUser": email_cfg.get("imapUser") or email_cfg.get("smtpUser") or env_gmail_user or "",
        "imapPass": email_cfg.get("imapPass") or email_cfg.get("smtpPass") or env_gmail_pass or "",
    }


def parse_client_domain_csv(value: str) -> List[str]:
    return [item.strip().lower() for item in (value or "").split(",") if item.strip()]


async def get_client_inbox_auto_settings(db) -> Dict[str, Any]:
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
        "replySignature": cfg.get("replySignature") or "Best Regards,\nRecruitment Team\nClahan Technologies",
        "vendorWhatsAppNumber": cfg.get("vendorWhatsAppNumber") or twilio.get("vendorWhatsAppNumber", ""),
        "inboxProvider": str(cfg.get("inboxProvider") or "gmail_api").strip().lower(),
    }


def client_reply_auto_send_eligible(
    extracted: Dict[str, Any],
    generated_reply: Dict[str, Any],
    confidence: float,
    settings: Dict[str, Any],
    domain_is_allowed: bool,
) -> bool:
    if extracted.get("client_request_closed"):
        return False
    if not domain_is_allowed:
        return False
    threshold = float(settings.get("autoSendThreshold") or 70) / 100
    if confidence >= threshold:
        return True

    if not extracted.get("is_training_request"):
        return False
    if not has_actionable_training_domain(extracted.get("technology_needed")):
        return False
    if not (generated_reply or {}).get("body"):
        return False
    if not ((generated_reply or {}).get("asks_for_clarification") or extracted.get("needs_clarification")):
        return False
    return confidence >= 0.55


def is_client_clarification_reply(extracted: Dict[str, Any], generated_reply: Dict[str, Any]) -> bool:
    reply = generated_reply or {}
    subject = str(reply.get("subject") or "").lower()
    body = str(reply.get("body") or "").lower()
    return bool(
        reply.get("asks_for_clarification")
        or (extracted or {}).get("needs_clarification")
        or "request for additional details" in subject
        or "kindly provide the following details" in body
    )


async def find_existing_client_clarification_request(
    db,
    *,
    from_email: str,
    requirement_id: str = "",
    generated_reply: Optional[Dict[str, Any]] = None,
    extracted: Optional[Dict[str, Any]] = None,
    exclude_email_id: str = "",
) -> Optional[dict]:
    if not from_email or not is_client_clarification_reply(extracted or {}, generated_reply or {}):
        return None
    query: Dict[str, Any] = {
        "from_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"},
        "sent_at": {"$nin": [None, ""]},
        "status": {"$in": ["auto_sent", "approved"]},
        "$or": [
            {"generated_reply.asks_for_clarification": True},
            {"generated_reply.subject": {"$regex": "request for additional details|additional details required", "$options": "i"}},
            {"generated_reply.body": {"$regex": "kindly provide the following details", "$options": "i"}},
        ],
    }
    if requirement_id:
        query["requirement_id"] = requirement_id
    if exclude_email_id:
        query["email_id"] = {"$ne": exclude_email_id}
    return await db["client_emails"].find_one(
        query,
        {"_id": 0, "email_id": 1, "sent_at": 1, "subject": 1, "generated_reply.subject": 1},
        sort=[("sent_at", -1), ("created_at", -1)],
    )


async def mark_duplicate_client_clarification_skipped(db, email_id: str, existing: dict) -> None:
    if not email_id:
        return
    await db["client_emails"].update_one(
        {"email_id": email_id, "sent_at": None},
        {"$set": {
            "status": "auto_skipped_duplicate_clarification",
            "auto_send_eligible": False,
            "duplicate_clarification_email_id": (existing or {}).get("email_id", ""),
            "duplicate_clarification_sent_at": (existing or {}).get("sent_at"),
            "duplicate_clarification_checked_at": utc_now(),
        }},
    )


async def auto_send_pending_client_replies_smtp(db, limit: int = 25) -> List[Dict[str, Any]]:
    settings = await get_client_inbox_auto_settings(db)
    if not settings.get("autoSendEnabled"):
        return []

    smtp_config = await get_email_auto_smtp_config(db)
    docs = await db["client_emails"].find(
        {"status": "pending_approval", "sent_at": None},
        {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit or 25), 100))).to_list(max(1, min(int(limit or 25), 100)))

    sent: List[Dict[str, Any]] = []
    whitelist = set(parse_client_domain_csv(settings.get("clientDomainsWhitelist", "")))
    for doc in docs:
        extracted = doc.get("extracted") or {}
        generated_reply = doc.get("generated_reply") or {}
        confidence = float(doc.get("confidence") or extracted.get("confidence") or 0)
        domain = sender_domain(doc.get("from_email", ""))
        domain_is_allowed = not whitelist or domain in whitelist
        if not client_reply_auto_send_eligible(extracted, generated_reply, confidence, settings, domain_is_allowed):
            continue
        if not doc.get("from_email") or not generated_reply.get("body"):
            continue

        existing_clarification = await find_existing_client_clarification_request(
            db,
            from_email=doc.get("from_email", ""),
            requirement_id=doc.get("requirement_id") or "",
            generated_reply=generated_reply,
            extracted=extracted,
            exclude_email_id=doc.get("email_id") or "",
        )
        if existing_clarification:
            await mark_duplicate_client_clarification_skipped(db, doc.get("email_id", ""), existing_clarification)
            sent.append({
                "status": "auto_skipped_duplicate_clarification",
                "email_id": doc.get("email_id"),
                "requirement_id": doc.get("requirement_id"),
                "existing_email_id": existing_clarification.get("email_id"),
            })
            continue

        subject = generated_reply.get("subject") or f"Re: {doc.get('subject') or 'Training Requirement'}"
        success, error = await send_email_async(
            doc.get("from_email", ""),
            subject,
            generated_reply.get("body") or "",
            smtp_config,
            "",
        )
        if not success:
            await db["client_emails"].update_one(
                {"email_id": doc.get("email_id"), "status": "pending_approval", "sent_at": None},
                {"$set": {"extraction_error": error or "SMTP send failed", "auto_send_eligible": True}},
            )
            continue

        now = utc_now()
        await db["client_emails"].update_one(
            {"email_id": doc.get("email_id"), "status": "pending_approval", "sent_at": None},
            {"$set": {
                "status": "auto_sent",
                "auto_send_eligible": True,
                "sent_at": now,
                "sent_by": "auto_imap_pending",
                "smtp_send_result": {"success": True, "provider": "smtp_imap_mode"},
            }},
        )
        sent.append({
            "status": "auto_sent",
            "email_id": doc.get("email_id"),
            "requirement_id": doc.get("requirement_id"),
        })
    return sent


async def auto_contact_shortlisted_trainers(db, requirement: dict, shortlist: dict) -> dict:
    req_id = requirement.get("requirement_id")
    if not req_id:
        return {"success": False, "error": "requirement_id missing"}

    top_trainers = (shortlist or {}).get("top_trainers") or []
    if not top_trainers:
        return {"success": True, "sent": 0, "failed": 0, "skipped": 0, "results": []}

    smtp_config = await get_email_auto_smtp_config(db)
    technology = requirement.get("technology_needed") or requirement.get("job_title") or "Training"
    duration = str(
        requirement.get("training_duration")
        or requirement.get("duration")
        or requirement.get("duration_days")
        or ""
    ).strip()
    mode = str(requirement.get("mode") or requirement.get("training_mode") or "").strip()
    participants = str(requirement.get("participant_count") or requirement.get("participants") or "").strip()
    results = []

    outreach_limit = min(5, max(3, int(requirement.get("top_n") or 5)))
    for item in top_trainers[:outreach_limit]:
        trainer_id = item.get("trainer_id")
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) if trainer_id else None
        trainer = trainer or item
        trainer_name = trainer.get("name") or trainer.get("trainer_name") or item.get("name") or "Trainer"
        to_email = (
            trainer.get("email")
            or trainer.get("trainer_email")
            or item.get("email")
            or item.get("trainer_email")
            or ""
        ).strip()

        if not trainer_id or not to_email:
            results.append({
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "status": "skipped",
                "error": "trainer email missing",
            })
            continue

        existing = await db["email_logs"].find_one(
            {
                "requirement_id": req_id,
                "trainer_id": trainer_id,
                "mail_type": {"$in": ["mail1", "first"]},
                "status": "sent",
            },
            {"_id": 0, "email_id": 1},
        )
        if existing:
            results.append({
                "trainer_id": trainer_id,
                "trainer_name": trainer_name,
                "to_email": to_email,
                "status": "already_sent",
                "email_id": existing.get("email_id"),
            })
            continue

        subject = f"Training Requirement - {technology}"
        body = compose_shortlist_first_email(trainer_name, technology, duration, mode, participants)
        outbound_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
        sent_at = utc_now()
        success, error = await send_email_async(to_email, subject, body, smtp_config, "")
        status = "sent" if success else "failed"

        log_doc = {
            "email_id": outbound_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "requirement_id": req_id,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "status": status,
            "email_stage": 1,
            "error_message": error if not success else "",
            "sent_at": sent_at if success else None,
            "reply_received": False,
            "opened": False,
            "open_count": 0,
            "tracking_url": "",
            "retry_count": 0,
            "mail_type": "mail1",
            "source": "email_auto_match",
            "technology": technology,
            "client_name": requirement.get("client_name") or requirement.get("client_company") or "",
            "client_email": requirement.get("client_email") or "",
            "trainer_phone": trainer.get("phone") or item.get("phone") or "",
            "created_at": sent_at,
        }
        await db["email_logs"].insert_one(log_doc)
        await db["conversations"].insert_one({
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "to_email": to_email,
            "requirement_id": req_id,
            "subject": subject,
            "body": body,
            "mail_type": "mail1",
            "direction": "sent",
            "status": status,
            "error": error if not success else "",
            "sent_at": sent_at,
            "email_id": outbound_id,
            "source": "email_auto_match",
            "client_name": requirement.get("client_name") or requirement.get("client_company") or "",
            "client_email": requirement.get("client_email") or "",
        })

        if success:
            await db["trainers"].update_one(
                {"trainer_id": trainer_id},
                {"$set": {"status": "contacted", "updated_at": sent_at}},
            )

        results.append({
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "to_email": to_email,
            "status": status,
            "error": error if not success else "",
            "email_id": outbound_id,
        })

    sent = sum(1 for result in results if result.get("status") == "sent")
    failed = sum(1 for result in results if result.get("status") == "failed")
    skipped = sum(1 for result in results if result.get("status") in {"skipped", "already_sent"})
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {"$set": {
            "send_emails": True,
            "trainer_outreach_status": "completed" if failed == 0 else "partial",
            "trainer_outreach_at": utc_now(),
            "trainer_outreach_sent": sent,
            "trainer_outreach_failed": failed,
            "trainer_outreach_skipped": skipped,
        }},
    )
    return {"success": True, "sent": sent, "failed": failed, "skipped": skipped, "results": results}


async def create_requirement_from_email(extracted: dict, email_id: str, db) -> str:
    if not has_actionable_training_domain(extracted.get("technology_needed")):
        return ""
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
        "send_emails": True,
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
        "daily_timing": extracted.get("daily_timing"),
        "participant_count": extracted.get("participant_count"),
        "audience_level": extracted.get("audience_level"),
        "mode": extracted.get("mode"),
        "location": extracted.get("location"),
        "budget_per_day": extracted.get("budget_per_day"),
        "budget_total": extracted.get("budget_total"),
        "budget_currency": extracted.get("budget_currency"),
        "timeline_start": extracted.get("timeline_start"),
        "timeline_flexible": extracted.get("timeline_flexible"),
        "needs_clarification": extracted.get("needs_clarification") or [],
        "matching_basis": "domain_initial" if extracted.get("needs_clarification") else "complete_requirement",
        "matching_notes": (
            "Initial trainer matching started from the available technology/domain. "
            "Schedule, audience, mode, and commercials can be refined when the client provides them."
            if extracted.get("needs_clarification") else ""
        ),
        "urgency": extracted.get("urgency"),
        "special_requirements": extracted.get("special_requirements"),
        "language_of_training": extracted.get("language_of_training"),
        "total_matched": 0,
        "created_at": utc_now(),
    }
    await db["requirements"].insert_one(doc)
    await auto_match_trainers_for_requirement(db, doc)
    return req_id


async def auto_match_trainers_for_requirement(db, requirement: dict) -> dict:
    """Build and persist the trainer shortlist for an email-created requirement."""
    req_id = requirement.get("requirement_id")
    if not req_id:
        return {"success": False, "error": "requirement_id missing"}

    existing = await db["shortlists"].find_one({"requirement_id": req_id}, {"_id": 0})
    if existing and existing.get("top_trainers"):
        outreach = await auto_contact_shortlisted_trainers(db, requirement, existing)
        return {"success": True, "already_exists": True, "outreach": outreach, "shortlist": existing}

    try:
        all_trainers = await db["trainers"].find({}, {"_id": 0}).to_list(10000)
        excluded_statuses = {"interested", "confirmed", "declined"}
        filtered_trainers = [
            trainer for trainer in all_trainers
            if trainer.get("status") not in excluded_statuses
        ]

        if filtered_trainers:
            result = await run_pipeline(filtered_trainers, requirement)
            top_trainers = [
                {key: value for key, value in trainer.items() if key != "_id"}
                for trainer in result.get("top_trainers", [])
            ]
            total_matched = len(result.get("ranked_trainers", []))
            category_filter_applied = result.get("category_filter_applied", False)
            no_category_match = result.get("no_category_match", False)
            category_match_count = result.get("category_match_count", 0)
        else:
            top_trainers = []
            total_matched = 0
            category_filter_applied = False
            no_category_match = True
            category_match_count = 0

        shortlist_doc = {
            "shortlist_id": f"SL-{uuid.uuid4().hex[:8].upper()}",
            "requirement_id": req_id,
            "technology_needed": requirement.get("technology_needed", ""),
            "top_trainers": top_trainers,
            "total_matched": total_matched,
            "category_filter_applied": category_filter_applied,
            "no_category_match": no_category_match,
            "category_match_count": category_match_count,
            "created_at": utc_now(),
            "auto_created": True,
            "source": "email_auto_match",
        }
        await db["shortlists"].insert_one(shortlist_doc)
        await db["requirements"].update_one(
            {"requirement_id": req_id},
            {"$set": {
                "total_matched": total_matched,
                "top_count": len(top_trainers),
                "auto_match_status": "completed",
                "auto_matched_at": utc_now(),
            }},
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
        outreach = await auto_contact_shortlisted_trainers(db, requirement, shortlist_doc)
        shortlist_doc.pop("_id", None)
        return {
            "success": True,
            "total_trainers_scanned": len(all_trainers),
            "total_available": len(filtered_trainers),
            "total_matched": total_matched,
            "top_trainers": len(top_trainers),
            "outreach": outreach,
            "shortlist": shortlist_doc,
        }
    except Exception as exc:
        logger.exception("Auto trainer matching failed for requirement %s", req_id)
        await db["requirements"].update_one(
            {"requirement_id": req_id},
            {"$set": {
                "auto_match_status": "failed",
                "auto_match_error": str(exc),
                "auto_matched_at": utc_now(),
            }},
        )
        return {"success": False, "error": str(exc)}


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
    msg["From"] = f"Clahan Technologies <{gmail_user}>"
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
    imap_cfg = await get_email_auto_imap_config(db)
    imap_user = str(imap_cfg.get("imapUser") or "").strip()
    imap_pass = str(imap_cfg.get("imapPass") or "").replace(" ", "")
    imap_host = str(imap_cfg.get("imapHost") or "imap.gmail.com").strip()
    imap_port = int(imap_cfg.get("imapPort") or 993)
    if not imap_user or not imap_pass:
        return {"processed": 0, "skipped": "IMAP credentials missing"}

    processed = 0
    smtp_config = await get_email_auto_smtp_config(db)
    inbox_settings = await get_client_inbox_auto_settings(db)
    auto_sent_existing = await auto_send_pending_client_replies_smtp(db)
    mail = imaplib.IMAP4_SSL(imap_host, imap_port)
    try:
        try:
            mail.login(imap_user, imap_pass)
        except imaplib.IMAP4.error as exc:
            return {
                "processed": 0,
                "skipped": "IMAP authentication failed; update the mailbox username/password in Admin > Email Configuration or backend .env",
                "imap_user": imap_user,
                "imap_host": imap_host,
                "error": str(exc),
                "auto_sent_existing": len(auto_sent_existing),
            }
        mail.select("inbox")
        _, unseen_ids = mail.search(None, "UNSEEN")
        _, all_ids = mail.search(None, "ALL")
        raw_ids = []
        seen = set()
        for raw_id in (unseen_ids[0].split() if unseen_ids and unseen_ids[0] else []):
            key = raw_id.decode("utf-8", errors="ignore") if isinstance(raw_id, bytes) else str(raw_id)
            if key not in seen:
                raw_ids.append(raw_id)
                seen.add(key)
        recent_all = (all_ids[0].split() if all_ids and all_ids[0] else [])[-50:]
        for raw_id in recent_all:
            key = raw_id.decode("utf-8", errors="ignore") if isinstance(raw_id, bytes) else str(raw_id)
            if key not in seen:
                raw_ids.append(raw_id)
                seen.add(key)

        for raw_id in raw_ids:
            _, data = mail.fetch(raw_id, "(RFC822)")
            if not data or not data[0]:
                continue
            raw_msg = data[0][1]
            msg = email_lib.message_from_bytes(raw_msg)
            subject = decode_header_value(msg.get("Subject", ""))
            from_name, from_email = parse_email_address(msg.get("Reply-To") or msg.get("From", ""))
            message_id_header = str(msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
            raw_id_text = raw_id.decode("utf-8", errors="ignore") if isinstance(raw_id, bytes) else str(raw_id)
            stable_source = message_id_header or f"{imap_user}:{raw_id_text}:{subject}:{from_email}"
            pseudo_id = f"IMAP-{hashlib.sha1(stable_source.encode('utf-8', errors='ignore')).hexdigest()[:12].upper()}"
            existing_query = {"$or": [{"email_id": pseudo_id}]}
            if message_id_header:
                existing_query["$or"].append({"message_id_header": message_id_header})
            if await db["client_emails"].find_one(existing_query, {"_id": 1}):
                continue

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get_filename():
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            clean_body = clean_email_body(body)
            meta = {
                "email_id": pseudo_id,
                "thread_id": "",
                "received_at": utc_now(),
                "from_email": from_email,
                "from_name": from_name,
                "subject": subject,
                "message_id_header": message_id_header,
                "raw_body": body,
                "clean_body": clean_body,
                "attachments_text": "",
            }
            trainer_thread = await find_matching_trainer_outbound_thread(db, from_email, subject, clean_body or body)
            if trainer_thread:
                await record_trainer_reply_from_client_inbox(db, meta, trainer_thread)
                processed += 1
                continue

            if looks_like_client_requirement_closed(clean_body or body):
                reason = client_requirement_closure_reason(clean_body or body)
                extracted = client_requirement_closure_extraction(meta, reason)
                reply = generate_client_requirement_closed_reply(
                    meta,
                    reason,
                    inbox_settings.get("replySignature"),
                )
                requirement_id = await mark_client_requirement_closed(
                    db,
                    from_email=from_email,
                    reason=reason,
                    email_id=pseudo_id,
                    subject=subject,
                    body=clean_body or body,
                )
                send_success = False
                send_error = ""
                sent_at = None
                if inbox_settings.get("autoSendEnabled") and from_email and reply.get("body"):
                    send_success, send_error = await send_email_async(
                        from_email,
                        reply.get("subject") or f"Re: {subject or 'Training Requirement'}",
                        reply.get("body") or "",
                        smtp_config,
                        "",
                    )
                    if send_success:
                        sent_at = utc_now()
                await db["client_emails"].update_one(
                    {"email_id": pseudo_id},
                    {"$setOnInsert": {
                        **meta,
                        "extracted": extracted,
                        "generated_reply": reply,
                        "requirement_id": requirement_id,
                        "status": "client_closed_requirement",
                        "confidence": float(extracted.get("confidence") or 0.98),
                        "extraction_error": send_error,
                        "auto_send_eligible": bool(inbox_settings.get("autoSendEnabled")),
                        "sent_at": sent_at,
                        "sent_by": "auto_imap_client_closure_ack" if send_success else None,
                        "smtp_send_result": {"success": True, "provider": "smtp_imap_mode"} if send_success else None,
                        "duplicate_clarification_email_id": "",
                        "duplicate_clarification_sent_at": None,
                        "client_closure_ack_sent": send_success,
                        "client_closure_ack_error": send_error,
                        "whatsapp_notified": False,
                        "created_at": utc_now(),
                    }},
                    upsert=True,
                )
                processed += 1
                continue
            if not is_likely_training_email(subject, from_email, body_preview=clean_body[:1000]):
                office_category = classify_office_mail(subject, from_email, clean_body[:1500])
                reply = generate_office_mail_reply(office_category, from_name, subject)
                if not reply:
                    continue
                existing_ack = await db["email_logs"].find_one(
                    {
                        "to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"},
                        "subject": reply.get("subject") or f"Re: {subject}",
                        "office_mail_category": office_category,
                        "status": "sent",
                        "source": "hostinger_office_mail_auto_reply",
                        "created_at": {"$gte": utc_now() - timedelta(days=30)},
                    },
                    {"_id": 0, "email_id": 1},
                )
                outbound_id = f"OFFICE-{uuid.uuid4().hex[:8].upper()}"
                sent_at = utc_now()
                if existing_ack:
                    success, error = True, ""
                    send_status = "already_sent"
                    outbound_id = existing_ack.get("email_id") or outbound_id
                else:
                    success, error = await send_email_async(
                        from_email,
                        reply.get("subject") or f"Re: {subject}",
                        reply.get("body") or "",
                        smtp_config,
                        "",
                    )
                    send_status = "sent" if success else "failed"
                meta = {
                    "email_id": pseudo_id,
                    "thread_id": "",
                    "received_at": utc_now(),
                    "from_email": from_email,
                    "from_name": from_name,
                    "subject": subject,
                    "message_id_header": message_id_header,
                    "raw_body": body,
                    "clean_body": clean_body,
                    "attachments_text": "",
                }
                await db["client_emails"].update_one(
                    {"email_id": pseudo_id},
                    {"$setOnInsert": {
                        **meta,
                        "office_mail_category": office_category,
                        "extracted": {
                            "is_training_request": False,
                            "client_email": from_email,
                            "client_name": from_name or None,
                            "email_subject": subject,
                            "email_summary": f"Office mail classified as {office_category}.",
                            "confidence": 0.75,
                        },
                        "generated_reply": reply,
                        "requirement_id": None,
                        "status": send_status,
                        "confidence": 0.75,
                        "extraction_error": error if not success else "",
                        "auto_send_eligible": True,
                        "sent_at": sent_at if success else None,
                        "sent_by": "auto_office_mail_ack",
                        "outbound_email_id": outbound_id,
                        "whatsapp_notified": False,
                        "created_at": utc_now(),
                    }},
                    upsert=True,
                )
                if not existing_ack:
                    await db["email_logs"].insert_one({
                        "email_id": outbound_id,
                        "mail_type": f"office_{office_category}_ack",
                        "source": "hostinger_office_mail_auto_reply",
                        "inbound_email_id": pseudo_id,
                        "to_email": from_email,
                        "to_name": from_name,
                        "subject": reply.get("subject") or f"Re: {subject}",
                        "body": reply.get("body") or "",
                        "status": send_status,
                        "error_message": error if not success else "",
                        "sent_at": sent_at if success else None,
                        "created_at": sent_at,
                        "office_mail_category": office_category,
                        "original_subject": subject,
                        "reply_received": False,
                        "opened": False,
                        "open_count": 0,
                        "tracking_url": "",
                        "retry_count": 0,
                    })
                processed += 1
                continue

            meta = {
                "email_id": pseudo_id,
                "thread_id": "",
                "received_at": utc_now(),
                "from_email": from_email,
                "from_name": from_name,
                "subject": subject,
                "message_id_header": message_id_header,
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
            extraction_error = ""
            try:
                extracted = await _extract_from_text(extraction_prompt_context)
            except Exception as exc:
                extraction_error = str(exc)
                extracted = {
                    "client_name": from_name or None,
                    "client_email": from_email,
                    "technology_needed": None,
                    "is_training_request": True,
                    "confidence": 0.3,
                    "needs_review": True,
                    "missing_fields": ["AI extraction unavailable; review manually"],
                }
            try:
                reply = await generate_calhan_reply(extracted, {
                    "subject": subject,
                    "reply_signature": inbox_settings.get("replySignature"),
                })
            except Exception:
                reply = {}
            requirement_id = None
            if extracted.get("is_training_request"):
                requirement_id = await ensure_requirement_from_email(extracted, pseudo_id, db)

            confidence = float(extracted.get("confidence") or 0)
            domain = sender_domain(from_email)
            whitelist = set(parse_client_domain_csv(inbox_settings.get("clientDomainsWhitelist", "")))
            domain_is_allowed = not whitelist or domain in whitelist
            auto_send_eligible = client_reply_auto_send_eligible(
                extracted,
                reply if isinstance(reply, dict) else {},
                confidence,
                inbox_settings,
                domain_is_allowed,
            )
            send_success = False
            send_error = ""
            sent_at = None
            duplicate_clarification = None
            if auto_send_eligible and inbox_settings.get("autoSendEnabled") and isinstance(reply, dict) and reply.get("body"):
                duplicate_clarification = await find_existing_client_clarification_request(
                    db,
                    from_email=from_email,
                    requirement_id=requirement_id or "",
                    generated_reply=reply,
                    extracted=extracted,
                    exclude_email_id=pseudo_id,
                )
                if duplicate_clarification:
                    auto_send_eligible = False
                else:
                    send_success, send_error = await send_email_async(
                        from_email,
                        reply.get("subject") or f"Re: {subject or 'Training Requirement'}",
                        reply.get("body") or "",
                        smtp_config,
                        "",
                    )
                    if send_success:
                        sent_at = utc_now()

            await db["client_emails"].update_one(
                {"email_id": pseudo_id},
                {"$setOnInsert": {
                    **meta,
                    "extracted": extracted,
                    "generated_reply": reply,
                    "requirement_id": requirement_id,
                    "status": (
                        "auto_sent"
                        if send_success else
                        "auto_skipped_duplicate_clarification"
                        if duplicate_clarification else
                        "pending_approval"
                    ),
                    "confidence": confidence,
                    "extraction_error": send_error or extraction_error,
                    "auto_send_eligible": auto_send_eligible,
                    "sent_at": sent_at,
                    "sent_by": "auto_imap" if send_success else None,
                    "duplicate_clarification_email_id": (duplicate_clarification or {}).get("email_id", ""),
                    "duplicate_clarification_sent_at": (duplicate_clarification or {}).get("sent_at"),
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
    return {
        "processed": processed,
        "imap_user": imap_user,
        "imap_host": imap_host,
        "auto_sent_existing": len(auto_sent_existing),
    }


async def _extract_from_text(meta: Dict[str, Any]) -> Dict[str, Any]:
    body_for_gemini = meta.get("clean_body") or meta.get("raw_body") or ""
    if looks_like_client_requirement_closed(body_for_gemini):
        return client_requirement_closure_extraction(
            meta,
            client_requirement_closure_reason(body_for_gemini),
        )
    prompt = f"""You are an intelligent email analyst for Clahan Technologies,
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
  "technology_needed": "primary technology or skill/domain required, or null if not mentioned",
  "secondary_technologies": ["array of additional skills if any"],
  "duration_days": number or null,
  "duration_hours": number or null,
  "daily_timing": "daily class time like 9 AM to 4 PM or null",
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
    return _normalise_extraction(await _ai_json(prompt, max_tokens=1800), meta)
