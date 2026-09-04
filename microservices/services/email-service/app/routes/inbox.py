"""Gmail inbox polling and inbound client requirement processing."""
import asyncio
import base64
import html
import hashlib
import io
import logging
import math
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Annotated, Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import get_settings
from app.agents.email_classifier import SAFETY_SCENARIOS, classify_email
from app.agents.reply_templates import build_auto_reply
from app.calendar_client import (
    add_google_calendar_attendees,
    cancel_google_calendar_event,
    create_google_meet_event,
)
from shared.database.service import get_db
from app.gmail_client import check_gmail_api_replies, check_imap_replies, generate_message_id, send_email_async
from app.routes.templates import (
    GenericSimpleRequest,
    compose_mail5_rejection,
    compose_mail5_selection,
)

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

CORE_API_URL = settings.CORE_API_URL.rstrip("/")
TRAINER_SERVICE_URL = settings.TRAINER_SERVICE_URL.rstrip("/")
DOCUMENT_SERVICE_URL = "http://document-service:8006"
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
LOCAL_SERVICE_FALLBACKS = {
    "https://core-api:8001": "http://127.0.0.1:8001",
    "http://core-api:8001": "http://127.0.0.1:8001",
    "https://trainer-service:8004": "http://127.0.0.1:8004",
    "http://trainer-service:8004": "http://127.0.0.1:8004",
    "http://document-service:8006": "http://127.0.0.1:8006",
    "https://intelligence-service:8005": "http://127.0.0.1:8005",
    "http://intelligence-service:8005": "http://127.0.0.1:8005",
    "http://127.0.0.1:8001": "http://127.0.0.1:8001",
    "http://127.0.0.1:8004": "http://127.0.0.1:8004",
    "http://127.0.0.1:8005": "http://127.0.0.1:8005",
    "http://127.0.0.1:8006": "http://127.0.0.1:8006",
}
REPLY_OUTBOUND_MAIL_PRIORITY = {
    "mail1": 10,
    "mail1_reminder": 11,
    "mail1_toc_correction": 12,
    "mail2": 20,
    "mail2_followup": 21,
    "trainer_commercials_to_client": 30,
    "commercial_details_notification": 31,
    "commercial_negotiation": 40,
    "trainer_rate_discussion": 41,
    "mail3": 50,
    "mail3_slot_followup": 51,
    "mail3_too_many_slots": 52,
    "client_slots": 60,
    "client_interview_schedule": 70,
    "mail4": 80,
    "mail5": 90,
    "mail5_ok": 91,
    "mail5_selection": 92,
    "mail5_no": 93,
    "mail5_rejection": 94,
    "mail6": 100,
    "mail6_toc": 101,
    "toc-request": 102,
    "mail7": 110,
    "mail7_confirm": 111,
    "training_confirmation": 112,
}
TRAINER_REPLY_SOURCE_MAIL_TYPES = {
    "mail1",
    "mail1_reminder",
    "mail1_toc_correction",
    "mail2",
    "mail2_followup",
    "trainer_commercials_to_client",
    "commercial_negotiation",
    "trainer_rate_discussion",
    "client_budget_revision_request",
    "mail3",
    "mail3_slot_followup",
    "mail3_too_many_slots",
    "mail4_reschedule_request",
    "mail5",
    "mail5_ok",
    "mail5_selection",
    "mail6_toc",
    "toc-request",
    "mail7",
    "mail7_confirm",
    "training_confirmation",
    "client_slots",
    "client_interview_schedule",
    "mail4",
}
CLIENT_REPLY_SOURCE_MAIL_TYPES = {
    "client_auto_reply",
    "client_reply",
    "office_auto_reply",
    "trainer_commercials_to_client",
    "commercial_details_notification",
    "client_budget_acknowledgment",
    "client_budget_revision_request",
    "client_slots",
    "client_interview_schedule",
    "client_interview_reschedule_request",
    "client_toc_details_request",
    "client_toc_details_followup",
}

FINAL_CLIENT_STATUSES = {"auto_sent", "sent", "approved", "rejected", "spam", "ignored", "deleted"}
BLOCKED_CLIENT_STATUSES = {"rejected", "spam", "ignored"}
TRAINING_SIGNALS = (
    "trainer",
    "training",
    "requirement",
    "workshop",
    "profiles",
    "profile",
    "commercials",
    "duration",
    "audience level",
    "mode",
)
KNOWN_TECHNOLOGIES = (
    "DevOps",
    "AWS",
    "Azure",
    "GCP",
    "Kubernetes",
    "Docker",
    "Python",
    "Java",
    "React",
    "Angular",
    "Salesforce",
    "SAP",
    "ServiceNow",
    "Power BI",
    "Tableau",
    "Machine Learning",
    "Generative AI",
    "Gen AI",
)
NON_TECH_CANDIDATE_WORDS = {
    "availability",
    "budget",
    "commercials",
    "date",
    "dates",
    "duration",
    "hour",
    "hours",
    "mode",
    "next",
    "participants",
    "profile",
    "profiles",
    "rate",
    "resume",
    "schedule",
    "slot",
    "slots",
    "today",
    "tomorrow",
    "week",
}
AUTOMATED_SENDER_LOCALS = {
    "bounce",
    "do-not-reply",
    "donotreply",
    "mail",
    "mailer-daemon",
    "newsletter",
    "no-reply",
    "noreply",
    "notification",
    "notifications",
    "onlinecourses",
    "postmaster",
    "recommendationnc",
    "security",
    "support",
    "system",
    "updates",
    "updates-noreply",
}
BULK_SENDER_DOMAINS = {
    "alison.com",
    "facebookmail.com",
    "github.com",
    "instagram.com",
    "linkedin.com",
    "naukri.com",
    "nptel.iitm.ac.in",
    "support.whatsapp.com",
    "whatsapp.com",
    "reliancedigital.in",
}
NON_CLIENT_BULK_SIGNALS = (
    "unsubscribe",
    "manage your preferences",
    "view in browser",
    "exclusive deals",
    "newsletter",
    "promotion",
    "promotional",
    "sale",
    "offer",
    "password reset",
    "otp",
    "verification code",
    "reacted to this",
    "commented a post",
    "join our whatsapp channel",
)
DIRECT_REQUEST_PATTERNS = (
    r"\b(?:need|require|required|looking\s+for|seeking|want|hire)\b.{0,90}\b(?:trainer|training|workshop|instructor|profiles?|resource|consultant)\b",
    r"\b(?:trainer|training|workshop|instructor)\b.{0,90}\b(?:need|required|requirement|profiles?|commercials?|available|availability|share|send|provide)\b",
    r"\brequirement\s+(?:for|of)\b.{0,90}\b(?:trainer|training|workshop|instructor|facilitator)\b",
    r"\b(?:please|kindly)\s+(?:share|send|provide)\b.{0,90}\b(?:trainer|profiles?|resume|commercials?|availability)\b",
    r"\b(?:corporate|classroom|online|offline|virtual|onsite|on-site)\s+training\s+(?:requirement|program|session|workshop)\b",
)
PROCEED_NOW_PATTERNS = (
    r"\b(?:please\s+)?proceed(?:\s+(?:now|further|ahead|with))?\b",
    r"\b(?:we|you|clahan)\s+can\s+proceed\b",
    r"\bproceed\b.{0,60}\b(?:available|current|existing|shared|these|same)\s+details?\b",
    r"\b(?:available|current|existing|shared|these|same)\s+details?\b.{0,60}\b(?:proceed|start|begin|continue)\b",
    r"\bproceed\b.{0,60}\b(?:information|info)\s+(?:available|currently\s+available|we\s+have)\b",
    r"\bgo\s+ahead\b",
    r"\bmove\s+ahead\b",
    r"\bmove\s+forward\b",
    r"\bcontinue\b.{0,40}\b(?:search|shortlist|process|trainer|with)\b",
    r"\bonwards?\b",
    r"\bstart\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\bbegin\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\b(?:please\s+)?share\b.{0,50}\b(?:profile|profiles|trainer profiles)\b",
    r"\b(?:send|provide)\b.{0,50}\b(?:profile|profiles|trainer profiles)\b",
    r"\b(?:suitable|relevant|available)\s+(?:trainer|trainer profile|trainer profiles|profiles)\b",
)
DETAILS_LATER_PATTERNS = (
    r"\b(?:send|sent|share|provide)\b.{0,50}\blater\b",
    r"\bwill\s+(?:send|share|provide)\b.{0,50}\blater\b",
    r"\bwill\s+(?:send|share|provide)\b.{0,80}\b(?:remaining|missing|more|other)\s+details?\b",
    r"\b(?:remaining|missing|more|other)\s+details?\b.{0,80}\bwill\s+(?:send|share|provide)\b",
    r"\blater\b.{0,50}\b(?:send|share|provide|details?)\b",
    r"\bdetails?\s+(?:later|will\s+follow|to\s+follow|will\s+be\s+provided\s+later)\b",
    r"\bwill\s+share\s+details?\s+later\b",
    r"\b(?:details?|dates?|timings?|duration|budget|commercials?)\s+(?:are|is)\s+(?:not\s+)?(?:final|finalized|finalised|available)\b",
    r"\bremaining\s+details?\b",
    r"\bonce\s+.*\b(?:available|finali[sz]ed)\b",
)
OPEN_REQUIREMENT_EXCLUDED_STATUSES = {"closed", "completed", "cancelled", "canceled", "inactive", "deleted"}


class PollRequest(BaseModel):
    since_days: int = 7
    max_messages: int = 50
    from_emails: Optional[list] = None
    search_query: str = ""


class ProcessPendingRequest(BaseModel):
    limit: int = 100


def _now() -> datetime:
    return datetime.utcnow()


def _today_start_utc() -> datetime:
    local_now = datetime.now(LOCAL_TZ)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _message_time(email_doc: Dict[str, Any]) -> Optional[datetime]:
    return (
        _parse_datetime(email_doc.get("received_at"))
        or _parse_datetime(email_doc.get("updated_at"))
        or _parse_datetime(email_doc.get("created_at"))
    )


def _inbox_process_after() -> Optional[datetime]:
    """Return the reset boundary for inbound mail, if one is configured."""
    return _parse_datetime(get_settings().INBOX_PROCESS_AFTER)


def _is_today_or_newer(email_doc: Dict[str, Any]) -> bool:
    cutoff = _inbox_process_after()
    if not cutoff:
        return True
    message_time = _message_time(email_doc)
    return bool(message_time and message_time >= cutoff)


def _today_client_email_query() -> Dict[str, Any]:
    # Do not limit pending work to today only.
    return {}


def _clean(value: Any) -> str:
    value = re.sub(r"[*_`]+", "", str(value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n:-")


def _fix_mojibake(value: Any) -> str:
    text = str(value or "")
    if not any(marker in text for marker in ("â", "ð", "Ã")):
        return text
    try:
        repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
        return repaired or text
    except Exception:
        return text


def _plain_text(value: Any) -> str:
    text = _fix_mojibake(value)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_text_lines(value: Any) -> str:
    text = _fix_mojibake(value)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</(?:p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _strip_quoted_email_history(value: Any) -> str:
    text = _plain_text_lines(value)
    if not text:
        return ""

    kept: List[str] = []
    quote_markers = (
        r"^On .{0,160} wrote:$",
        r"^From:\s+",
        r"^Sent:\s+",
        r"^To:\s+",
        r"^Subject:\s+",
        r"^-{2,}\s*Original Message\s*-{2,}$",
        r"^_{5,}$",
    )
    marker_re = re.compile("|".join(f"(?:{marker})" for marker in quote_markers), flags=re.IGNORECASE)
    for line in text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            if kept:
                kept.append("")
            continue
        if clean_line.startswith(">") or marker_re.search(clean_line):
            break
        kept.append(clean_line)

    stripped = "\n".join(kept).strip()
    return stripped or text


def _email_address(value: Any) -> str:
    return _clean(parseaddr(str(value or ""))[1] or value).lower()


def _subject_thread_key(subject: Any) -> str:
    value = _clean(subject).lower()
    while True:
        stripped = re.sub(r"^\s*(?:re|fw|fwd)\s*:\s*", "", value, flags=re.IGNORECASE)
        if stripped == value:
            break
        value = stripped
    value = re.sub(r"\[[a-z]+-[a-z0-9]+\]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:urgent|immediate)\b", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _subjects_match_thread(left: Any, right: Any) -> bool:
    left_key = _subject_thread_key(left)
    right_key = _subject_thread_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shortest, longest = sorted((left_key, right_key), key=len)
    if len(shortest) >= 12 and shortest in longest:
        return True

    stopwords = {"for", "the", "and", "with", "about"}
    left_terms = {term for term in re.findall(r"[a-z0-9]+", left_key) if len(term) > 2 and term not in stopwords}
    right_terms = {term for term in re.findall(r"[a-z0-9]+", right_key) if len(term) > 2 and term not in stopwords}
    if not left_terms or not right_terms:
        return False
    shared = left_terms & right_terms
    return len(shared) >= min(3, len(left_terms), len(right_terms)) and (
        len(shared) / max(1, min(len(left_terms), len(right_terms))) >= 0.75
    )


def _message_id_candidates(*values: Any) -> List[str]:
    candidates: List[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        tokens = re.findall(r"<[^>]+>", raw)
        if not tokens and " " not in raw:
            tokens = [raw]
        for token in tokens:
            token = token.strip()
            if token and token not in candidates:
                candidates.append(token)
    return candidates


def _clean_message_id(value: Any) -> str:
    candidates = _message_id_candidates(value)
    return candidates[0] if candidates else str(value or "").strip()


def _extract_trainer_reply_ref(*values: Any) -> Dict[str, str]:
    text = "\n".join(str(value or "") for value in values if value)
    if not text:
        return {}
    # Prefer explicit "Ref: REQ-... / TR-..." but tolerate missing boundaries
    match = re.search(r"\bRef\s*:\s*(REQ-[A-Z0-9-]+)\s*/\s*(TR-[A-Z0-9-]+)", text, flags=re.IGNORECASE)
    if not match:
        # Fallback: find any REQ-... / TR-... pair in the text
        match = re.search(r"(REQ-[A-Z0-9-]+)\s*/\s*(TR-[A-Z0-9-]+)", text, flags=re.IGNORECASE)
        if not match:
            return {}
    return {
        "requirement_id": match.group(1).upper(),
        "trainer_id": match.group(2).upper(),
    }


def _outbound_reply_stage_priority(log: Dict[str, Any]) -> int:
    return REPLY_OUTBOUND_MAIL_PRIORITY.get(str(log.get("mail_type") or "").strip(), 0)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _normalise_threshold(value: Any, default: float = 0.7) -> float:
    threshold = _safe_float(value, default)
    if threshold > 1:
        threshold /= 100
    return max(0.0, min(threshold, 1.0))


async def _post_with_local_fallback(
    client: httpx.AsyncClient,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await client.post(url, **kwargs)
    except httpx.RequestError:
        for docker_base, local_base in LOCAL_SERVICE_FALLBACKS.items():
            if url.startswith(docker_base):
                fallback_url = local_base + url[len(docker_base):]
                return await client.post(fallback_url, **kwargs)
        raise


async def _get_with_local_fallback(
    client: httpx.AsyncClient,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await client.get(url, **kwargs)
    except httpx.RequestError:
        for docker_base, local_base in LOCAL_SERVICE_FALLBACKS.items():
            if url.startswith(docker_base):
                fallback_url = local_base + url[len(docker_base):]
                return await client.get(fallback_url, **kwargs)
        raise


def _configured_mailbox_addresses(settings_doc: Dict[str, Any]) -> List[str]:
    email_cfg = settings_doc.get("emailCfg") or {}
    candidates = [
        settings.GMAIL_USER,
        settings.FROM_EMAIL,
        email_cfg.get("smtpUser"),
        email_cfg.get("fromEmail"),
        email_cfg.get("imapUser"),
    ]
    addresses: List[str] = []
    for candidate in candidates:
        address = _email_address(candidate)
        if address and address not in addresses:
            addresses.append(address)
    return addresses


def _fill_missing(target: Dict[str, Any], key: str, value: Any) -> None:
    if value in (None, ""):
        return
    if target.get(key) in (None, ""):
        target[key] = value


def _merge_unique_detail_values(*values: Any) -> List[str]:
    """Combine client-requested detail lists without losing prior thread context."""
    merged: List[str] = []
    seen = set()
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            text = _clean(item)
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                merged.append(text)
    return merged


def _merge_settings_doc(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _normalise_admin_settings_doc(settings_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Support both current nested settings and older top-level helper-script keys."""
    doc = dict(settings_doc or {})

    email_cfg = dict(doc.get("emailCfg") or {})
    for key in (
        "smtpHost",
        "smtpPort",
        "smtpUser",
        "smtpPass",
        "imapHost",
        "imapPort",
        "imapUser",
        "imapPass",
        "fromName",
        "fromEmail",
    ):
        _fill_missing(email_cfg, key, doc.get(key))

    legacy_mail_user = doc.get("gmailUser") or doc.get("GMAIL_USER")
    legacy_mail_pass = doc.get("gmailPass") or doc.get("gmailAppPassword") or doc.get("gmailPassword")
    _fill_missing(email_cfg, "smtpUser", legacy_mail_user)
    _fill_missing(email_cfg, "imapUser", legacy_mail_user)
    _fill_missing(email_cfg, "smtpPass", legacy_mail_pass)
    _fill_missing(email_cfg, "imapPass", legacy_mail_pass)
    if email_cfg:
        doc["emailCfg"] = email_cfg

    client_inbox_cfg = dict(doc.get("clientInboxCfg") or {})
    for legacy_key in (
        "inboxProvider",
        "autoSendEnabled",
        "autoSendThreshold",
        "clientDomainsWhitelist",
        "replySignature",
        "vendorWhatsAppNumber",
    ):
        _fill_missing(client_inbox_cfg, legacy_key, doc.get(legacy_key))
    if client_inbox_cfg:
        doc["clientInboxCfg"] = client_inbox_cfg

    auto_send_cfg = dict(doc.get("autoSendCfg") or {})
    _fill_missing(auto_send_cfg, "enabled", doc.get("autoSendEnabled"))
    _fill_missing(auto_send_cfg, "threshold", doc.get("autoSendThreshold"))
    if auto_send_cfg:
        doc["autoSendCfg"] = auto_send_cfg

    return doc


async def _load_admin_settings(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    legacy_doc = await db["admin_settings"].find_one({"_id": "default"}, {"_id": 0}) or {}
    current_doc = await db["admin_settings"].find_one({"settings_id": "default"}, {"_id": 0}) or {}
    return _normalise_admin_settings_doc(_merge_settings_doc(legacy_doc, current_doc))


def _parse_retry_after(value: Any) -> Optional[datetime]:
    match = re.search(r"Retry after\s+([0-9T:.\-+Z]+)", str(value or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        parsed = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _client_handoff_retry_after(value: Any, now: Optional[datetime] = None) -> datetime:
    """Choose a bounded automatic retry time for a transient client handoff failure."""
    current = now or _now()
    candidates: List[Any] = [value]
    while candidates:
        candidate = candidates.pop(0)
        if isinstance(candidate, datetime):
            if candidate.tzinfo:
                candidate = candidate.astimezone(timezone.utc).replace(tzinfo=None)
            if candidate > current:
                return candidate
            continue
        if isinstance(candidate, dict):
            retry_at = candidate.get("retry_after")
            if retry_at is not None:
                candidates.append(retry_at)
            candidates.extend(candidate.get(key) for key in ("detail", "upstream_detail", "error") if candidate.get(key) is not None)
            continue
        raw = _clean(candidate)
        if not raw:
            continue
        parsed = _parse_retry_after(raw)
        if not parsed:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                parsed = None
        if parsed and parsed > current:
            return parsed
    return current + timedelta(minutes=5)


def _client_handoff_retry_pending(result: Dict[str, Any]) -> bool:
    """Only delivery/transient failures are retried; invalid trainer data is not."""
    return bool(not result.get("success") and result.get("retry_pending"))


def _auto_send_retry_due(email_doc: Dict[str, Any]) -> bool:
    retry_after = email_doc.get("auto_send_retry_after")
    if isinstance(retry_after, str):
        retry_after = _parse_retry_after(f"Retry after {retry_after}")
    return not retry_after or retry_after <= _now()


def _current_inbound_message_id(email_doc: Dict[str, Any]) -> str:
    return _clean_message_id(email_doc.get("latest_gmail_message_id") or email_doc.get("gmail_message_id") or "")


def _has_replied_to_latest_message(email_doc: Dict[str, Any]) -> bool:
    if not email_doc.get("reply_sent"):
        return False

    current_message_id = _current_inbound_message_id(email_doc)
    if not current_message_id:
        return True

    replied_message_id = _clean_message_id(
        email_doc.get("reply_sent_for_message_id")
        or email_doc.get("replied_to_gmail_message_id")
        or ""
    )
    if replied_message_id:
        return replied_message_id == current_message_id

    original_message_id = _clean_message_id(email_doc.get("gmail_message_id") or "")
    if original_message_id and original_message_id != current_message_id:
        return False
    return True


def _is_reply_thread(subject: str, email_doc: Dict[str, Any]) -> bool:
    if email_doc.get("in_reply_to"):
        return True
    return bool(re.match(r"^\s*(?:re|fw|fwd)\s*:", subject or "", flags=re.IGNORECASE))


def _should_attempt_auto_reply(
    email_doc: Dict[str, Any],
    settings: Dict[str, Any],
    auto_send_eligible: bool,
    reply: Dict[str, str],
    confidence: Optional[float] = None,
) -> bool:
    risk_reason = _auto_send_risk_reason(email_doc)
    if risk_reason:
        logger.info(
            "Auto-reply blocked: risk category %s. email_id=%s",
            risk_reason,
            email_doc.get("email_id"),
        )
        return False
    confidence_score = (
        _safe_float(confidence, 0)
        if confidence is not None
        else _safe_float(email_doc.get("auto_send_confidence", email_doc.get("confidence", 0)), 0)
    )
    if not bool(reply):
        logger.debug("Auto-reply blocked: no generated reply. email_id=%s", email_doc.get("email_id"))
        return False
    if not settings["enabled"]:
        logger.debug("Auto-reply blocked: auto-send disabled. email_id=%s", email_doc.get("email_id"))
        return False
    if not auto_send_eligible:
        logger.debug("Auto-reply blocked: not eligible for auto-send. email_id=%s", email_doc.get("email_id"))
        return False
    if _has_replied_to_latest_message(email_doc):
        logger.debug("Auto-reply blocked: already replied. email_id=%s", email_doc.get("email_id"))
        return False
    status = email_doc.get("status")
    reply_status = email_doc.get("reply_status")
    already_replied_to_latest = _has_replied_to_latest_message(email_doc)
    if status in BLOCKED_CLIENT_STATUSES:
        logger.debug("Auto-reply blocked: blocked status %s. email_id=%s", status, email_doc.get("email_id"))
        return False
    if reply_status in BLOCKED_CLIENT_STATUSES:
        logger.debug("Auto-reply blocked: blocked reply_status %s. email_id=%s", reply_status, email_doc.get("email_id"))
        return False
    if status in FINAL_CLIENT_STATUSES and already_replied_to_latest:
        logger.debug("Auto-reply blocked: final status %s. email_id=%s", email_doc.get("status"), email_doc.get("email_id"))
        return False
    if reply_status in FINAL_CLIENT_STATUSES and already_replied_to_latest:
        logger.debug("Auto-reply blocked: final reply_status %s. email_id=%s", email_doc.get("reply_status"), email_doc.get("email_id"))
        return False
    if confidence_score < settings.get("threshold", 0):
        logger.debug("Auto-reply blocked: confidence below threshold %s. email_id=%s", confidence_score, email_doc.get("email_id"))
        return False
    if not _auto_send_retry_due(email_doc):
        logger.debug("Auto-reply blocked: retry not due. email_id=%s retry_after=%s", email_doc.get("email_id"), email_doc.get("auto_send_retry_after"))
        return False
    return True


def _auto_send_risk_reason(email_doc: Dict[str, Any]) -> str:
    """Return a deterministic reason when an inbound email needs a human.

    This gate intentionally runs independently of LLM classification so a model
    can never override commercial, legal, or complaint-related safeguards.
    """
    runtime_settings = get_settings()
    keywords = [
        keyword.strip().lower()
        for keyword in runtime_settings.AUTO_SEND_RISK_KEYWORDS.split(",")
        if keyword.strip()
    ]
    subject = str(email_doc.get("subject") or "")
    body = str(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    text = f"{subject}\n{body}".lower()
    for keyword in keywords:
        if re.search(rf"(?<!\\w){re.escape(keyword)}(?!\\w)", text):
            return f"risky_keyword:{keyword}"
    return ""


def _has_training_domain(extracted: Dict[str, Any]) -> bool:
    return bool(
        extracted.get("technology_needed")
        or extracted.get("technology")
        or extracted.get("domain")
    )


def _has_training_duration(extracted: Dict[str, Any]) -> bool:
    return bool(
        extracted.get("duration_days")
        or extracted.get("duration_hours")
        or extracted.get("duration_text")
    )


def _has_minimum_details_for_trainer_search(extracted: Dict[str, Any]) -> bool:
    return bool(
        not extracted.get("is_non_client_email")
        and _has_training_domain(extracted)
        and _has_training_duration(extracted)
    )


def _has_details_for_trainer_search(extracted: Dict[str, Any]) -> bool:
    if _has_minimum_details_for_trainer_search(extracted):
        return True
    if not extracted.get("is_training_request"):
        return False
    has_technology = _has_training_domain(extracted)
    if has_technology and extracted.get("direct_request_language") and not extracted.get("is_non_client_email"):
        return True
    if not extracted.get("needs_clarification"):
        return True
    has_timing = bool(extracted.get("timing"))
    return bool(has_technology and has_timing)


def _has_all_required_client_details(extracted: Dict[str, Any]) -> bool:
    if not extracted.get("is_training_request") or extracted.get("is_non_client_email"):
        return False
    if extracted.get("needs_clarification"):
        return False
    has_budget = bool(
        extracted.get("budget_range")
        or extracted.get("budget_total")
        or extracted.get("budget_per_day")
        or extracted.get("commercials")
    )
    return bool(
        _has_training_domain(extracted)
        and _has_training_duration(extracted)
        and (
            extracted.get("training_dates")
            or extracted.get("preferred_dates")
            or extracted.get("timeline_start")
            or extracted.get("timing")
        )
        and (extracted.get("mode") or extracted.get("location"))
        and has_budget
    )


def _should_start_trainer_automation(subject: str, email_doc: Dict[str, Any], extracted: Dict[str, Any]) -> bool:
    if not extracted.get("is_training_request"):
        return False
    if email_doc.get("trainer_automation_status") in {"started", "no_trainers_emailed"}:
        return False
    existing_mail = (email_doc.get("mail_automation") or {}).get("trainer_mail") or {}
    if _safe_int(existing_mail.get("sent"), 0) > 0:
        return False
    return (
        bool(email_doc.get("pending_trainer_automation"))
        or _client_wants_to_proceed_now(subject, email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or "")
        or _has_details_for_trainer_search(extracted)
    )


def _trainer_automation_update(send_result: Dict[str, Any]) -> Dict[str, Any]:
    sent_count = _safe_int(send_result.get("sent"), 0)
    total_count = _safe_int(send_result.get("total"), 0)
    already_sent_count = sum(
        1 for item in send_result.get("results", [])
        if item.get("status") == "skipped_already_sent"
    )
    retry_after = _parse_retry_after(str(send_result))
    now = _now()

    if send_result.get("handoff") == "shortlist1":
        return {
            "trainer_automation_status": "shortlist1_handoff",
            "trainer_automation_started_at": now,
            "pending_trainer_automation": False,
            "auto_send_retry_after": None,
        }
    if sent_count > 0 or already_sent_count > 0:
        return {
            "trainer_automation_status": "started",
            "trainer_automation_started_at": now,
            "pending_trainer_automation": False,
            "auto_send_retry_after": None,
        }
    if total_count > 0:
        return {
            "trainer_automation_status": "failed",
            "trainer_automation_error": str(send_result)[:2000],
            "trainer_automation_failed_at": now,
            "pending_trainer_automation": True,
            "auto_send_retry_after": retry_after,
        }
    return {
        "trainer_automation_status": "no_trainers_emailed",
        "trainer_automation_started_at": now,
        "pending_trainer_automation": False,
    }


def _field_value(text: str, labels: List[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    pattern = re.compile(
        rf"(?im)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:{label_pattern})"
        rf"(?![A-Za-z0-9])\s*(?:\*\*)?\s*[:\-]\s*(.+?)\s*$"
    )
    match = pattern.search(text or "")
    return _clean(match.group(1)) if match else ""


def _field_value_loose(text: str, labels: List[str]) -> str:
    direct = _field_value(text, labels)
    if direct:
        return direct
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    start_pattern = re.compile(
        rf"(?im)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:{label_pattern})"
        rf"(?![A-Za-z0-9])\s*(?:\*\*)?\s*:?\s*$"
    )
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if not start_pattern.match(line):
            continue
        for continuation in lines[index + 1:index + 6]:
            value = _clean(continuation)
            if value:
                return value
    return ""


def _field_block_value(text: str, labels: List[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    start_pattern = re.compile(
        rf"(?i)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:{label_pattern})"
        rf"(?![A-Za-z0-9])\s*(?:\*\*)?\s*[:\-]\s*(.*?)\s*$"
    )
    next_label_pattern = re.compile(
        r"(?i)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*[A-Z][A-Za-z /&()]{1,45}"
        r"\s*(?:\*\*)?\s*[:\-]\s*"
    )
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        match = start_pattern.match(line)
        if not match:
            continue
        values = [_clean(match.group(1))]
        for continuation in lines[index + 1:]:
            if not continuation.strip() or next_label_pattern.match(continuation):
                break
            values.append(_clean(continuation))
        return _clean(" ".join(value for value in values if value))
    return ""


def _has_direct_training_request_language(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in DIRECT_REQUEST_PATTERNS)


def _client_wants_to_proceed_now(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    has_proceed_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in PROCEED_NOW_PATTERNS
    )
    return bool(has_proceed_signal)


def _client_will_send_details_later(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in DETAILS_LATER_PATTERNS
    )


def _client_provided_requirement_details(subject: str, body: str, extracted: Optional[Dict[str, Any]] = None) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    labelled_detail = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in (
            r"\btraining\s+duration\b\s*[:\-]",
            r"\b(?:preferred\s+)?(?:dates?|timings?|schedule)\b\s*[:\-]",
            r"\b(?:training\s+)?(?:mode|location|venue)\b\s*[:\-]",
            r"\bparticipant\s+count\b\s*[:\-]",
            r"\b(?:budget|commercials?|commercial\s+range|expected\s+commercial)\b\s*[:\-]",
        )
    )
    natural_detail = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in (
            r"\b\d+\s*(?:days?|hours?|hrs?)\b",
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?\s+(?:to|until|through|till|-|–|—)\s+(?:(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+)?\d{1,2}(?:st|nd|rd|th)?\b",
            r"\b\d+\s*(?:participants?|learners?|trainees?|people|pax)\b",
            r"\b(?:online|offline|onsite|on-site|virtual|hybrid)\b",
            r"\b(?:inr|rs\.?|₹|\$)\s*[0-9][0-9,]*(?:\s*(?:per|/)\s*(?:day|hour|hr|session))?\b",
        )
    )
    if labelled_detail or natural_detail:
        return True
    return bool(extracted and _has_details_for_trainer_search(extracted))


def _is_obvious_non_client_email(sender_email: str, subject: str, body: str) -> bool:
    email = _email_address(sender_email)
    local = email.split("@", 1)[0] if "@" in email else email
    domain = email.split("@", 1)[1] if "@" in email else ""
    automated_sender = (
        local in AUTOMATED_SENDER_LOCALS
        # Providers use names such as googleaistudio-noreply.  Treat any
        # no-reply marker in the local part as automated, not just prefixes.
        or "noreply" in local
        or "no-reply" in local
        or local.startswith(("bounce", "no-reply", "noreply", "donotreply", "do-not-reply"))
        or "mailer-daemon" in local
    )
    bulk_domain = any(domain == item or domain.endswith(f".{item}") for item in BULK_SENDER_DOMAINS)
    if automated_sender or bulk_domain:
        return True

    if _has_direct_training_request_language(subject, body):
        return False
    text = _plain_text(f"{subject}\n{body}").lower()
    bulk_content = any(signal in text for signal in NON_CLIENT_BULK_SIGNALS)
    return bulk_content


def _client_company_from_email(email: str, fallback: str = "") -> str:
    email = _email_address(email)
    domain = (email or "").split("@")[-1].lower()
    if not domain or domain in {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com"}:
        fallback_name = _clean(fallback)
        if fallback_name and "@" not in fallback_name:
            return fallback_name
        local_name = _extract_person_name_from_local_part((email or "").split("@")[0])
        return local_name or "Client"
    return _clean(domain.split(".")[0]).title()


def _looks_like_company_name(name: str) -> bool:
    if not name:
        return False
    cleaned = _clean(name).lower()
    company_keywords = [
        "inc", "ltd", "llp", "corp", "company", "solutions", "services", "technologies",
        "group", "net", "org", "com", "co", "tech",
    ]
    known_brand_names = {"spotify", "google", "microsoft", "amazon", "facebook", "meta", "apple", "ibm", "oracle", "accenture"}
    if cleaned in known_brand_names:
        return True
    if any(keyword in cleaned for keyword in company_keywords):
        return True
    if re.match(r"^[a-z0-9_.+-]+$", cleaned) and cleaned.endswith(("inc", "ltd", "llp", "corp", "co", "tech")):
        return True
    if cleaned in {"info", "contact", "support", "sales", "admin", "hello", "team", "recruiter"}:
        return True
    return False


def _extract_person_name_from_local_part(local_part: str) -> str:
    cleaned = _clean(local_part)
    if not cleaned or _looks_like_company_name(cleaned):
        return ""
    compact = re.sub(r"[^a-z]", "", cleaned.lower())
    if compact.startswith("murali") and "mohan" in compact:
        return "Murali Mohan"
    tokens = [token for token in re.split(r"[._+-]", cleaned) if token]
    if not tokens:
        return ""
    if any(not token.isalpha() for token in tokens):
        return ""
    if len(tokens) == 1:
        return tokens[0].title() if len(tokens[0]) > 1 else ""
    if 1 < len(tokens) <= 3:
        return " ".join(token.title() for token in tokens)
    return ""


def _infer_technology(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    explicit = _field_value_loose(text, ["Training name", "Training Name", "Technology", "Tech", "Domain", "Course", "Topic"])
    candidates = []

    subject_match = re.search(
        r"\btraining\s+requirements?\s*[-:]\s*([^\n\r]{3,100})",
        subject,
        flags=re.IGNORECASE,
    )
    if subject_match:
        candidates.append(subject_match.group(1))
    candidates.append(explicit)

    phrase_patterns = [
        r"requirement\s+for\s+(?:an?\s+|the\s+)?([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70}?)\s+(?:trainer|training|course|workshop)\b",
        r"(?:need|require|looking\s+for)\s+(?:an?\s+)?([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70}?)\s+(?:trainer|training|course|workshop)\b",
        r"(?:trainer|training|course|workshop)\s+(?:for|on|in)\s+([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70})\b",
        r"(?:need|require|looking\s+for)\s+(?:an?\s+)?(?:trainer|training|course|workshop)\s+(?:for|on|in)\s+([A-Za-z0-9][A-Za-z0-9 .+#/&-]{1,70})\b",
    ]
    for pattern in phrase_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    for tech in KNOWN_TECHNOLOGIES:
        if re.search(rf"\b{re.escape(tech)}\b", text, flags=re.IGNORECASE):
            candidates.append(tech)

    for candidate in candidates:
        candidate = re.split(r"[.;,\n\r]|\bplease\b", _clean(candidate), maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = re.sub(
            r"\b(?:trainer|training|course|workshop|profiles?|requirement)\b.*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate_words = {word.lower() for word in re.findall(r"[A-Za-z]+", candidate)}
        if candidate_words <= {"below", "mentioned", "training", "requirement", "details", "detail"}:
            continue
        if candidate_words & NON_TECH_CANDIDATE_WORDS:
            continue
        if 1 < len(candidate) <= 60:
            return candidate
    return ""


def _extract_duration(text: str) -> Dict[str, Any]:
    raw = _field_value(text, ["Duration", "Training Duration"])
    source = raw or text
    match = re.search(r"(\d+(?:\.\d+)?)\s*(days?|weeks?|months?|hours?|hrs?)", source, flags=re.IGNORECASE)
    if not match:
        return {"duration_text": raw}

    amount = _safe_float(match.group(1))
    unit = match.group(2).lower()
    result: Dict[str, Any] = {"duration_text": raw or match.group(0)}
    if unit.startswith("hour") or unit.startswith("hr"):
        result["duration_hours"] = amount
        result["duration_days"] = max(1, round(amount / 7, 2))
    elif unit.startswith("week"):
        result["duration_days"] = int(amount * 5)
    elif unit.startswith("month"):
        result["duration_days"] = int(amount * 20)
    else:
        result["duration_days"] = int(amount) if amount.is_integer() else amount
    return result


def _normalise_date_text(value: str) -> str:
    return _clean(re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", value or "", flags=re.IGNORECASE))


MONTHS = {
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


def _date_piece(value: str, default_month: int = 0, default_year: int = 0) -> Optional[datetime]:
    clean = _normalise_date_text(value)
    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+)?(?:\s+(\d{4}))?\b",
        clean,
        flags=re.IGNORECASE,
    )
    if not match:
        month_first = re.search(
            r"\b([A-Za-z]+)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
            clean,
            flags=re.IGNORECASE,
        )
        if month_first:
            day = _safe_int(month_first.group(2), 0)
            month = MONTHS.get((month_first.group(1) or "").lower(), 0)
            year = _safe_int(month_first.group(3), 0) or default_year
            if day and month and year:
                try:
                    return datetime(year, month, day)
                except ValueError:
                    return None
    if not match:
        return None
    day = _safe_int(match.group(1), 0)
    month = MONTHS.get((match.group(2) or "").lower(), 0) or default_month
    year = _safe_int(match.group(3), 0) or default_year
    if not day or not month or not year:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _working_days_between(start: datetime, end: datetime) -> int:
    if end < start:
        start, end = end, start
    days = 0
    current = start
    while current.date() <= end.date():
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return max(days, 1)


def _training_working_days_from_dates(dates_text: Any) -> int:
    text = _normalise_date_text(str(dates_text or ""))
    if not text:
        return 0
    parts = re.split(r"\s+(?:to|until|through|till)\s+|\s+[\u2013\u2014-]\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        single = _date_piece(text, default_year=datetime.utcnow().year)
        return 1 if single else 0
    end = _date_piece(parts[1], default_year=datetime.utcnow().year)
    if not end:
        return 0
    start = _date_piece(parts[0], default_month=end.month, default_year=end.year)
    if not start:
        return 0
    return _working_days_between(start, end)


def _extract_preferred_dates(text: str) -> Dict[str, Any]:
    raw = _field_value(text, [
        "Preferred Training Dates",
        "Preferred dates or timings",
        "Preferred Dates or Timings",
        "Preferred Dates",
        "Dates/Timings",
        "Dates and Timings",
        "Training Dates",
        "Training Date",
        "Start Date",
        "Dates",
        "Date",
    ])
    if not raw:
        month_names = "|".join(re.escape(name) for name in MONTHS)
        range_match = re.search(
            rf"\b(?:{month_names})\s+\d{{1,2}}(?:st|nd|rd|th)?\s+"
            rf"(?:to|until|through|till|-|–|—)\s+"
            rf"(?:(?:{month_names})\s+)?\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,?\s*\d{{4}})?\b",
            text or "",
            flags=re.IGNORECASE,
        )
        if range_match:
            raw = range_match.group(0)
    if not raw:
        month_names = "|".join(re.escape(name) for name in MONTHS)
        range_match = re.search(
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{month_names})(?:\s*,?\s*\d{{4}})?\s+"
            rf"(?:to|until|through|till|-|â€“|â€”)\s+"
            rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{month_names})(?:\s*,?\s*\d{{4}})?\b",
            text or "",
            flags=re.IGNORECASE,
        )
        if range_match:
            raw = range_match.group(0)
    if not raw:
        return {}

    preferred_dates = _normalise_date_text(raw)
    result: Dict[str, Any] = {
        "preferred_dates": preferred_dates,
        "training_dates": preferred_dates,
    }
    parts = re.split(r"\s+(?:to|until|through|till)\s+|\s+[\u2013\u2014-]\s+", preferred_dates, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        result["timeline_start"] = _normalise_date_text(parts[0])
        result["timeline_end"] = _normalise_date_text(parts[1])
    return result


def _extract_budget(text: str) -> Dict[str, Any]:
    # Gmail bodies can occasionally arrive with a UTF-8 rupee sign decoded as
    # the literal mojibake sequence "â‚¹".  Accept both representations.
    rupee = rf"(?:{re.escape(chr(0x20B9))}|â‚¹)"
    raw = _field_value(text, [
        "Budget",
        "Budget Range",
        "Commercial Range",
        "Commercials",
        "Commercial",
        "Rate",
        "Cost",
        "Price",
    ])
    source = raw or text
    per_day_amount = re.search(
        rf"(?:INR|Rs\.?|{rupee})\s*([\d,]+(?:\.\d+)?)(?:\s*/-)?\s*(?:per\s*day|/day|daily)",
        source,
        flags=re.IGNORECASE,
    )
    if per_day_amount:
        amount = _safe_float(per_day_amount.group(1))
        if amount > 0:
            return {
                "budget_currency": "INR",
                "budget_range": _clean(per_day_amount.group(0)),
                "budget_per_day": amount,
            }
    marker_match = re.search(r"(?:budget|commercials?|rate|cost|price)[^\n\r]{0,160}", source, flags=re.IGNORECASE)
    if not raw and not marker_match:
        return {}
    search_text = marker_match.group(0) if marker_match else source
    amounts = [
        _safe_float(match.group(1))
        for match in re.finditer(rf"(?:INR|Rs\.?|{rupee}|USD|\$)?\s*([\d,]+(?:\.\d+)?)", search_text, flags=re.IGNORECASE)
    ]
    amounts = [amount for amount in amounts if amount > 0]
    if not amounts:
        return {}

    currency = "USD" if "$" in search_text or "USD" in search_text.upper() else "INR"
    per_day = bool(re.search(r"per\s*day|/day|daily", search_text, flags=re.IGNORECASE))
    low = min(amounts)
    high = max(amounts)
    result = {
        "budget_currency": currency,
        "budget_range": _clean(raw or search_text),
    }
    if len(amounts) > 1:
        result["budget_min"] = low
        result["budget_max"] = high
    result["budget_per_day" if per_day else "budget_total"] = high
    return result


def _missing_training_details(details: Dict[str, Any]) -> List[str]:
    missing = []
    if not (details.get("duration_days") or details.get("duration_hours") or details.get("duration_text")):
        missing.append("Training duration")
    if not (
        details.get("timing")
        or details.get("preferred_dates")
        or details.get("training_dates")
        or details.get("timeline_start")
    ):
        missing.append("Preferred dates or timings")
    if not details.get("mode"):
        missing.append("Training mode/location")
    if details.get("participant_count") is None:
        missing.append("Participant count")
    if not (details.get("budget_total") or details.get("budget_per_day")):
        missing.append("Budget or expected commercial range, if available")
    return missing


def _client_thread_coordination_intent(text: Any) -> str:
    latest = _strip_quoted_email_history(text)
    lower = latest.lower()
    if not lower:
        return ""

    # A new requirement can request a ToC among several trainer documents.
    # That is not a revision request unless the client explicitly refers to an
    # earlier/shared ToC.
    is_new_requirement = bool(re.search(
        r"\b(?:proposed|new|upcoming|corporate)\b.{0,80}\b(?:training\s+)?requirement\b",
        lower,
        flags=re.IGNORECASE,
    ))

    if re.search(r"\b(?:additional|new|more|alternate|another)\b.{0,80}\b(?:slots?|availability|dates?)\b", lower, flags=re.IGNORECASE):
        if re.search(r"\b(?:tech(?:nical)?\s+call|discussion|interview|evaluation|client\s+call)\b", lower, flags=re.IGNORECASE):
            return "request_additional_trainer_slots"
    if re.search(r"\b(?:share|send|provide)\b.{0,80}\b(?:slots?|availability)\b", lower, flags=re.IGNORECASE):
        if re.search(r"\b(?:tomorrow|monday|tuesday|wednesday|thursday|friday|next\s+week|this\s+week|tech(?:nical)?\s+call)\b", lower, flags=re.IGNORECASE):
            return "request_additional_trainer_slots"
    if re.search(r"\b(?:preferred|confirm|confirmed|selected|schedule|scheduled)\b.{0,80}\b(?:slot|time|date|discussion|interview|tech(?:nical)?\s+call)\b", lower, flags=re.IGNORECASE):
        return "client_selected_slot"
    if re.search(r"\b(?:lab\s+cost|lab\s+charges?|separate\s+lab|lab\s+setup)\b", lower, flags=re.IGNORECASE):
        return "lab_cost_clarification"
    if not is_new_requirement and re.search(r"\b(?:revised|updated|add(?:ed)?|review)\b.{0,100}\b(?:toc|table\s+of\s+content|course\s+content|topics?|scope)\b", lower, flags=re.IGNORECASE):
        return "toc_revision_requested"
    if re.search(r"\bpfa\b.{0,80}\b(?:profile|toc|content|lab|details)\b", lower, flags=re.IGNORECASE):
        return "trainer_submission_forwarded"
    if re.search(r"\b(?:any\s+updates?|update\s+regarding|check\s+and\s+confirm)\b", lower, flags=re.IGNORECASE):
        return "client_followup"
    return ""


def _is_technology_catalogue_inquiry(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return bool(re.search(
        r"\b(?:list|catalog(?:ue)?)\s+(?:of\s+)?(?:available\s+|current(?:ly)?\s+)?(?:training\s+)?(?:technolog(?:y|ies)|courses?|programs?)\b"
        r"|\b(?:what|which)\s+(?:technolog(?:y|ies)|courses?|trainings?|programs?)\s+(?:do\s+you|are\s+(?:you|currently))\s+(?:teach|offer|conduct|provid)",
        text,
    ))


def _is_lab_cost_inquiry(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return bool(re.search(
        r"\blab(?:oratory)?\b.{0,50}\b(?:cost|price|charges?|quote|quotation|commercials?)\b"
        r"|\b(?:cost|price|charges?|quote|quotation|commercials?)\b.{0,50}\blab(?:oratory)?\b",
        text,
    ))


def _is_lab_cost_only_inquiry(subject: str, body: str) -> bool:
    """Keep standalone lab-cost work out of trainer batch pipelines.

    A domain, ToC or a few listed topics are inputs to costing, not evidence
    that the client wants trainer sourcing.  Only an explicit trainer/profile
    request is allowed to enter a confirmed/proposal trainer workflow.
    """
    if not _is_lab_cost_inquiry(subject, body):
        return False
    text = _plain_text(f"{subject}\n{body}").lower()
    trainer_request = re.search(
        r"\b(?:need|require|share|source|find|shortlist)\b.{0,70}"
        r"\b(?:trainer|trainer profile|cv|resume|linkedin|interview slots?)\b"
        r"|\btrainer\b.{0,70}\b(?:profile|cv|resume|availability|shortlist)\b",
        text,
        flags=re.IGNORECASE,
    )
    return not bool(trainer_request)


def _is_toc_only_inquiry(subject: str, body: str) -> bool:
    """Identify a request for course content without trainer sourcing."""
    text = _plain_text(f"{subject}\n{body}").lower()
    asks_toc = bool(re.search(
        r"\b(?:toc|table\s+of\s+contents?|course\s+agenda|curriculum|syllabus|day[-\s]?wise\s+(?:toc|content|agenda))\b",
        text,
        flags=re.IGNORECASE,
    ))
    if not asks_toc:
        return False
    trainer_request = re.search(
        r"\b(?:need|require|share|source|find|shortlist)\b.{0,70}"
        r"\b(?:trainer|trainer profile|cv|resume|linkedin|interview slots?)\b"
        r"|\btrainer\b.{0,70}\b(?:profile|cv|resume|availability|shortlist)\b",
        text,
        flags=re.IGNORECASE,
    )
    return not bool(trainer_request)


def _looks_like_general_client_question(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    question_language = bool(
        "?" in text
        or re.search(r"\b(?:could|can|would|will|do|does|is|are|what|which|when|where|how|please)\b", text)
    )
    business_topic = bool(re.search(
        r"\b(?:training|trainer|course|technology|institute|workshop|toc|curriculum|lab|cost|price|commercial|"
        r"invoice|purchase order|\bpo\b|schedule|date|timing|availability|certificate|material|profile|resume|"
        r"payment|service|proposal|assessment|recording|online|offline|corporate)\b",
        text,
    ))
    return question_language and business_topic


def _is_linked_trainer_thread(email_doc: Dict[str, Any]) -> bool:
    """Return True only for an inbound reply linked to a trainer workflow."""
    # Workflow identifiers contain underscores; `_clean` intentionally strips
    # underscores from prose and therefore must not be used here.
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip().lower()
    return bool(
        email_doc.get("requirement_id")
        and email_doc.get("trainer_id")
        and source_mail_type in TRAINER_REPLY_SOURCE_MAIL_TYPES
    )


def _is_linked_trainer_question(email_doc: Dict[str, Any], subject: str, body: str) -> bool:
    """Detect a real question before a trainer reply can advance the pipeline."""
    if not _is_linked_trainer_thread(email_doc):
        return False
    latest = _plain_text(_strip_quoted_email_history(body) or body).strip().lower()
    if not latest:
        return False
    # Do not mistake normal acceptance/details statements such as "I can take
    # the training" for questions merely because they contain the word "can".
    explicit_question = bool(
        "?" in latest
        or re.search(
            r"^(?:hi\b[^\n]*\n+\s*)?(?:could|can|would|will|do|does|is|are|what|which|when|where|how|why)\b",
            latest,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:i have (?:a )?(?:question|doubt)|please (?:clarify|confirm|advise)|"
            r"need clarification|could you (?:clarify|confirm|share)|can you (?:clarify|confirm|share))\b",
            latest,
            flags=re.IGNORECASE,
        )
    )
    return explicit_question and _looks_like_general_client_question(subject, latest)


async def _global_ai_wording_enabled(db: AsyncIOMotorDatabase) -> bool:
    """The one UI switch is the only authority for AI email wording."""
    setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    return _clean(setting.get("value")).lower() == "ai"


def _approved_question_reply(sender_name: str = "") -> Dict[str, str]:
    name = _clean(sender_name)
    greeting = f"Hi {name}," if name and "@" not in name else "Hi,"
    return {
        "subject": "Re: Your Enquiry",
        "body": (
            f"{greeting}\n\n"
            "Thank you for your question. We are checking the relevant training details and will share a confirmed response shortly. "
            "If you need an immediate update on a specific item, please let us know the requirement or topic you are referring to.\n\n"
            "Best Regards,\nRecruitment Team\nClahan Technologies"
        ),
    }


async def _generate_general_client_question_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    subject: str,
    body: str,
) -> Optional[Dict[str, str]]:
    """Use the LLM only after deterministic workflow routes have had priority."""
    if not await _global_ai_wording_enabled(db):
        return None
    try:
        from app.routes.inbox_actions import _ai_draft_reply, _load_reply_workflow_context

        context = await _load_reply_workflow_context(db, email_doc, classification, extracted, body)
        catalogue = await _technology_catalogue_reply(db, subject)
        context["company_identity"] = {
            "name": "Clahan Technologies",
            "role": "corporate training coordination and delivery services",
        }
        context["current_training_catalogue_reference"] = catalogue.get("body", "")[:5000]
        safe_reference = {
            "body": (
                "Dear Client,\n\nThank you for your question. We will answer using the information currently "
                "available in our records. If a requested commercial, availability, policy, or delivery commitment "
                "is not verified, we will clearly state that it requires confirmation.\n\nBest Regards,\n"
                "Recruitment Team\nClahan Technologies"
            )
        }
        generated = await _ai_draft_reply(
            subject=subject,
            body=body,
            hint=(
                "Answer the client's actual question directly as Clahan Technologies. Do not redirect a general "
                "question into the trainer-shortlisting workflow. Use only facts in the authoritative context. "
                "If the answer is not present, say that the Clahan team will verify that specific point and respond; "
                "do not invent it. Follow the concise Clahan/Hostinger sent-mail style: brief acknowledgement, "
                "direct answer or next step, and simple professional close."
            ),
            workflow_context=context,
            reference_reply=safe_reference,
            require_openai=True,
        )
        if not _clean(generated):
            return None
        return {
            "subject": f"Re: {subject}" if subject else "Re: Your Enquiry",
            "body": generated.strip(),
        }
    except Exception:
        logger.exception("General client-question generation failed for %s", email_doc.get("email_id"))
        return None


async def _generate_verified_question_reply(
    db: AsyncIOMotorDatabase,
    *,
    email_doc: Dict[str, Any],
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    subject: str,
    body: str,
    reference_reply: Dict[str, str],
    recipient_kind: str,
) -> Optional[Dict[str, str]]:
    """Answer a trainer/client question from its thread and verified workflow state."""
    if not await _global_ai_wording_enabled(db):
        return None
    try:
        from app.routes.inbox_actions import _ai_draft_reply, _load_reply_workflow_context

        context = await _load_reply_workflow_context(db, email_doc, classification, extracted, body)
        context["verified_conversation_history"] = await _verified_question_history(db, email_doc)
        context["question_recipient_kind"] = recipient_kind
        generated = await _ai_draft_reply(
            subject=subject,
            body=body,
            hint=(
                "Answer the sender's actual question directly and briefly. Check the current requirement first, then "
                "the bounded conversation history. A client inbound message or an already-sent Clahan response in "
                "that same requirement/thread can confirm a fact; a trainer question cannot. Use only verified facts. "
                "If the answer is not confirmed, say exactly that it is being checked; "
                "do not invent commercial, date, slot, trainer, attachment, policy, or delivery commitments."
            ),
            workflow_context=context,
            reference_reply=reference_reply,
            require_openai=True,
        )
        if _clean(generated):
            return {"subject": f"Re: {subject}" if subject else "Re: Your Enquiry", "body": generated.strip()}
    except Exception:
        logger.exception("Verified AI question reply failed for %s", email_doc.get("email_id"))
    return None


async def _verified_question_history(
    db: AsyncIOMotorDatabase, email_doc: Dict[str, Any], limit: int = 8
) -> List[Dict[str, str]]:
    """Load a small, requirement-scoped history with explicit source labels."""
    requirement_id = _clean(email_doc.get("requirement_id"))
    trainer_id = _clean(email_doc.get("trainer_id"))
    thread_id = _clean(email_doc.get("gmail_thread_id") or email_doc.get("thread_id"))
    current_email_id = _clean(email_doc.get("email_id"))
    identity_clauses: List[Dict[str, Any]] = []
    if requirement_id:
        identity_clauses.append({"requirement_id": requirement_id})
    if thread_id:
        identity_clauses.append({"gmail_thread_id": thread_id})
        identity_clauses.append({"thread_id": thread_id})
    if not identity_clauses:
        return []

    history: List[Dict[str, str]] = []
    query: Dict[str, Any] = {"$or": identity_clauses}
    if trainer_id:
        query["$and"] = [{"$or": [
            {"trainer_id": trainer_id},
            {"trainer_id": {"$in": [None, ""]}},
            {"trainer_id": {"$exists": False}},
        ]}]
    try:
        cursor = db["email_logs"].find(
            query,
            {"_id": 0, "direction": 1, "body": 1, "subject": 1, "mail_type": 1, "status": 1, "from_email": 1, "to_email": 1},
        ).sort("created_at", -1).limit(limit)
        async for message in cursor:
            message_body = _strip_quoted_email_history(message.get("body") or "")
            if not message_body:
                continue
            direction = _clean(message.get("direction")).lower()
            history.append({
                "source": "sent_clahan_email" if direction == "outbound" else "inbound_email",
                "direction": direction,
                "from": _email_address(message.get("from_email")),
                "to": _email_address(message.get("to_email")),
                "subject": _clean(message.get("subject"))[:300],
                "mail_type": _clean(message.get("mail_type")),
                "text": message_body[:1200],
            })
    except Exception:
        logger.exception("Unable to load email-log history for question %s", current_email_id)

    # Some Gmail inbound messages have not yet been copied to email_logs. Add
    # those records too, but label them as inbound rather than treating every
    # previous draft as authoritative.
    remaining = max(0, limit - len(history))
    if remaining:
        inbox_query: Dict[str, Any] = {"$or": identity_clauses}
        if current_email_id:
            inbox_query["email_id"] = {"$ne": current_email_id}
        try:
            cursor = db["client_emails"].find(
                inbox_query,
                {"_id": 0, "body": 1, "clean_body": 1, "subject": 1, "from_email": 1},
            ).sort("received_at", -1).limit(remaining)
            async for message in cursor:
                message_body = _strip_quoted_email_history(
                    message.get("clean_body") or message.get("body") or ""
                )
                if message_body:
                    history.append({
                        "source": "inbound_email",
                        "direction": "inbound",
                        "from": _email_address(message.get("from_email")),
                        "subject": _clean(message.get("subject"))[:300],
                        "text": message_body[:1200],
                    })
        except Exception:
            logger.exception("Unable to load inbox history for question %s", current_email_id)
    return history[:limit]


async def _humanize_verified_client_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    subject: str,
    body: str,
    verified_reply: Dict[str, str],
) -> Dict[str, str]:
    """Let GPT phrase verified facts naturally; return the safe reference if generation fails."""
    try:
        from app.config import get_settings

        setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
        if (
            _clean(setting.get("value")).lower() != "ai"
            or not bool(getattr(get_settings(), "USE_LLM_FOR_EMAILS", False))
        ):
            return {**verified_reply, "generation_source": "template"}
    except Exception:
        return {**verified_reply, "generation_source": "template"}

    try:
        from app.routes.inbox_actions import _ai_draft_reply, _load_reply_workflow_context

        context = await _load_reply_workflow_context(db, email_doc, classification, extracted, body)
        generated = await _ai_draft_reply(
            subject=subject,
            body=body,
            hint=(
                "Rewrite the verified reference as a natural human-to-human email from Clahan Technologies, using "
                "the concise Clahan/Hostinger sent-mail style. "
                "Preserve every business fact and restriction. Answer directly, choose vocabulary appropriate to "
                "the sender, and make the length proportional to the incoming message. Do not make it sound like "
                "a fixed template and do not add facts or promises."
            ),
            workflow_context=context,
            reference_reply=verified_reply,
            require_openai=True,
        )
        if _clean(generated):
            return {**verified_reply, "body": generated.strip(), "generation_source": "openai"}
    except Exception:
        logger.exception("Client reply humanization failed for %s", email_doc.get("email_id"))
    return {**verified_reply, "llm_generation_failed": True, "generation_source": "verified_reference_only"}


async def _technology_catalogue_reply(db: AsyncIOMotorDatabase, subject: str) -> Dict[str, str]:
    # Public-facing programme families follow Clahan's published positioning.
    # Individual trainer keywords are deliberately not dumped into client mail.
    programmes = [
        "DevOps and DevSecOps with AWS, Microsoft Azure, and Google Cloud",
        "Cloud Engineering and Multi-Cloud Operations",
        "Kubernetes, OpenShift, Docker, and Cloud-Native Engineering",
        "Site Reliability Engineering (SRE), Observability, and Monitoring",
        "GitOps, CI/CD, Infrastructure as Code, and Automation",
        "Cloud Security, SecOps, and Compliance",
        "FinOps and Cloud Cost Optimization",
        "MLOps, Artificial Intelligence, Generative AI, and AI Agents",
        "Data Science, Data Engineering, and Analytics",
        "Python, Java, Go, and Full-Stack Development",
        "Red Hat Linux, VMware, and Enterprise Infrastructure",
    ]
    technology_lines = "\n".join(f"- {programme}" for programme in programmes)
    return {
        "subject": f"Re: {subject}" if subject else "Available Training Technologies",
        "body": (
            "Dear Sujitha,\n\n"
            "Thank you for your enquiry. Our primary corporate training capabilities include:\n\n"
            f"{technology_lines}\n\n"
            "We can also arrange customized corporate training based on your required technology, audience level, "
            "duration, delivery mode, and preferred dates. Please share the technology you are interested in, and "
            "we will provide the relevant course outline, trainer profile, availability, and commercials.\n\n"
            "Best Regards,\nClahan Technologies"
        ),
    }


def _client_coordination_reply(intent: str, extracted: Dict[str, Any], subject: str) -> Dict[str, str]:
    technology = _clean(extracted.get("technology") or extracted.get("technology_needed") or "the training")
    subject_prefix = f"Re: {subject}" if subject else "Training requirement update"
    messages = {
        "request_additional_trainer_slots": (
            "We will check the trainer's availability for the requested technical-call slots and share the additional options shortly."
        ),
        "client_selected_slot": (
            "We will coordinate the confirmed meeting and share the interview link with all participants."
        ),
        "lab_cost_clarification": (
            "We will confirm the lab charges and the training commercials shortly."
        ),
        "toc_revision_requested": (
            "We will arrange the revised day-wise TOC and share it for your review."
        ),
        "trainer_submission_forwarded": (
            "We will review the trainer profile, TOC, and lab information and coordinate the next steps."
        ),
        "client_followup": (
            "We are coordinating the requested details and will share an update shortly."
        ),
    }
    message = messages.get(intent)
    if not message:
        return {}
    opening = f"Thank you for your message regarding {technology}." if technology and technology != "the training" else "Thank you for your message."
    return {
        "subject": subject_prefix,
        "body": f"Dear Team,\n\n{opening}\n\n{message}\n\nRegards,\nClahan Technologies",
    }


def _requirement_line_items(body: Any) -> List[Dict[str, str]]:
    """Extract client requirements from bullets, ordinary sentences, and paragraphs."""
    items: List[Dict[str, str]] = []
    seen: set[str] = set()
    # `_plain_text` deliberately flattens whitespace for intent detection.
    # Requirement extraction must instead retain line breaks, otherwise a
    # multi-bullet request is accidentally treated as one long sentence.
    source = _plain_text_lines(body) or _plain_text(body)
    for raw_line in str(source).replace("\r\n", "\n").replace("\r", "\n").splitlines():
        is_bullet = bool(re.match(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", raw_line))
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", raw_line).strip()
        line = re.sub(r"\s+", " ", line)
        lower = line.lower()
        if not line:
            continue
        category = ""
        automation = ""
        if re.search(r"\b(?:once|after)\b.{0,120}\b(?:receive|received|finali[sz]e|allocation|setup)\b", lower):
            category, automation = "workflow_condition", "record_completion_condition"
        elif re.search(r"\b(?:toc|table of contents?|course agenda)\b", lower):
            category, automation = "toc", "generate_toc"
        elif re.search(r"\blab(?:oratory)?\b.{0,80}\b(?:requirements?|required tools?|tools?)\b", lower):
            category, automation = "lab_requirements", "generate_lab_cost_estimate"
        elif re.search(r"\b(?:local|cloud)\s+lab(?:oratory)?\b|\blab(?:oratory)?\s+preference\b", lower):
            category, automation = "lab_delivery_preference", "generate_lab_cost_estimate"
        elif re.search(r"\b(?:trainer\s+)?(?:cv|resume|profile)\b", lower):
            category, automation = "trainer_profile", "attach_client_aligned_profile"
        elif re.search(r"\b(?:commercials?|budget|quote|quotation|price|charges?)\b", lower):
            category, automation = "commercials", "prepare_client_commercials"
        elif re.search(r"\b(?:dates?|schedule|timings?|duration|days?)\b", lower):
            category, automation = "training_schedule", "record_training_schedule"
        elif re.search(r"\b(?:participant|learner|trainee|pax|batch\s+size)\b", lower):
            category, automation = "participants", "record_participant_count"
        elif re.search(r"\b(?:certificate|certification)\b", lower):
            category, automation = "certification", "record_certification_requirement"
        elif re.search(r"\b(?:program|training|course)\b.{0,100}\b(?:cover|include|topics?|scope|capstone|project)\b", lower):
            category, automation = "training_scope", "build_toc_and_lab_scope"
        elif re.search(r"\b(?:confirm|confirmed|confirmation)\b.{0,100}\b(?:program|training|batch|requirement)\b", lower):
            category, automation = "batch_confirmation", "record_confirmed_batch"
        elif re.search(r"\b(?:tax|gst|inclusive|exclusive)\b", lower):
            category, automation = "taxes", "record_commercial_tax_terms"

        # A meaningful ordinary sentence and every bullet are retained. This
        # avoids treating greetings/signatures as requirements while ensuring
        # a client can write requirements in any normal email structure.
        if not category:
            meaningful_sentence = bool(re.search(
                r"\b(?:need|require|request|share|send|provide|confirm|approve|"
                r"training|course|program|batch|lab|toc|table of contents|trainer|"
                r"cv|profile|commercial|budget|date|duration|participant|tool|cloud|local)\b",
                lower,
                flags=re.IGNORECASE,
            ))
            if not is_bullet and not meaningful_sentence:
                continue
            category, automation = "other_requirement", "preserve_for_workflow"
        # Keep repeated requirements when their wording differs (for example,
        # a bullet that requests a ToC and a later sentence that makes the ToC
        # a condition for finalising the batch). Only an exact duplicate line
        # from rich-email rendering is collapsed.
        dedupe_key = f"{category}:{lower}"
        if dedupe_key not in seen:
            items.append({"category": category, "source_line": line, "automation": automation})
            seen.add(dedupe_key)
    return items


def _extract_requirement_from_email(subject: str, body: str, sender_email: str = "", sender_name: str = "") -> Dict[str, Any]:
    sender_email = _email_address(sender_email)
    body_text = _plain_text(body)
    latest_body_text = _strip_quoted_email_history(body_text)
    field_body = _plain_text_lines(body) or body_text
    requirement_source_text = _plain_text_lines(body) or body_text
    text = f"Subject: {subject}\n{field_body}"
    lower = f"Subject: {subject}\n{body_text}".lower()
    # Keep the original email layout for the client requirement checklist.
    # `body_text` is intentionally flattened for language detection, but it
    # must not be used here because it would merge multiple bullet points.
    requirement_items = _requirement_line_items(body)
    requirement_categories = {item["category"] for item in requirement_items}
    # Initial proposal requests often list a TOC among the requested trainer
    # documents. Only a reply thread can be a request to revise that TOC.
    is_reply_thread = bool(re.match(r"^\s*(?:re|fw|fwd)\s*:", subject or "", flags=re.IGNORECASE))
    latest_coordination_intent = _client_thread_coordination_intent(body_text) if is_reply_thread else ""
    direct_request = _has_direct_training_request_language(subject, latest_body_text or body_text)
    if latest_coordination_intent:
        direct_request = False
    non_client_email = _is_obvious_non_client_email(sender_email, subject, body_text)
    technology = _infer_technology(subject, field_body)
    if not technology:
        technology = _field_value_loose(text, ["Training name", "Training Name", "Training"])
    mode = _field_value_loose(
        text,
        [
            "Mode",
            "Location",
            "Venue",
            "Mode/Location",
            "Training Mode",
            "Mode of Training",
            "Training Location",
            "Training Mode/Location",
            "Delivery Mode",
        ],
    )
    if not mode:
        if "online" in lower or "virtual" in lower:
            mode = "Online"
        elif "offline" in lower or "onsite" in lower or "on-site" in lower:
            mode = "Offline"
        elif "hybrid" in lower:
            mode = "Hybrid"

    audience_level = _field_value_loose(text, ["Participant Level", "Audience Level", "Learner Level", "Level", "Audience", "Batch size", "Batch Size"])
    timing = _field_value_loose(text, ["Training Timings", "Training Time", "Daily Training Timings", "Preferred Timings", "Timings", "Timing", "Time", "Schedule"])
    hands_on_lab = _field_value_loose(text, ["Hands-on Lab", "Hands on Lab", "Daily Lab", "Lab Duration", "Lab Hours"])
    # For a confirmed training requirement, requesting lab requirements,
    # tools, setup, access, or a local/cloud choice means Clahan must prepare
    # the lab-cost estimate. Clients often do not use the literal words
    # "lab cost" in this kind of request.
    lab_delivery_requested = "lab_requirements" in requirement_categories or "lab_delivery_preference" in requirement_categories or bool(re.search(
        r"\blab(?:oratory)?\s+(?:requirements?|required\s+tools?|setup|access|support|availability|preference|environment)\b"
        r"|\b(?:local|cloud)\s+lab(?:oratory)?\b"
        r"|\blab(?:oratory)?\b.{0,80}\b(?:required\s+tools?|local|cloud|access)\b",
        lower,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    explicit_lab_cost_requested = bool(re.search(
        r"\blab(?:oratory)?\b.{0,50}\b(?:cost|price|charges?|quote|quotation|commercials?|estimate)\b"
        r"|\b(?:cost|price|charges?|quote|quotation|commercials?|estimate)\b.{0,50}\blab(?:oratory)?\b",
        lower,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    lab_cost_requested = lab_delivery_requested or explicit_lab_cost_requested
    lab_hours_per_day = None
    total_lab_duration_hours = None
    lab_daily_match = re.search(
        r"\b(?:lab(?:oratory)?\s+(?:duration|access|preference|requirements?)\s*:?\s*)?"
        r"(\d+(?:\.\d+)?)\s*hours?\s*(?:per\s*day|/\s*day|daily)\b",
        text,
        flags=re.IGNORECASE,
    )
    if lab_daily_match and lab_delivery_requested:
        lab_hours_per_day = _safe_float(lab_daily_match.group(1))
    lab_total_match = re.search(r"\btotal\s+lab\s+duration\s*:\s*(\d+(?:\.\d+)?)\s*hours?", text, flags=re.IGNORECASE)
    if lab_total_match:
        total_lab_duration_hours = _safe_float(lab_total_match.group(1))
    duration = _extract_duration(text)
    budget = _extract_budget(text)
    dates = _extract_preferred_dates(text)
    if not (duration.get("duration_days") or duration.get("duration_hours") or duration.get("duration_text")):
        inferred_days = _training_working_days_from_dates(dates.get("training_dates") or dates.get("preferred_dates"))
        if inferred_days:
            duration = {
                "duration_days": inferred_days,
                "duration_text": f"{inferred_days} working days",
                "duration_inferred_from_dates": True,
            }
    client_domain = _field_value_loose(text, ["Client Domain", "Client Industry", "Industry", "Business Domain", "Client Name"])
    topics = _field_block_value(text, ["Topics to be Covered", "Topics", "Tools", "Scope", "Scope of the delivery", "Table of Content", "TOC"])

    participants = None
    participant_text = _field_value(text, [
        "Participants", "Participant Count", "Learners", "Trainees",
        "No. of Pax", "No of Pax", "Pax", "Batch size", "Batch Size",
    ])
    participant_match = re.search(
        r"(\d+)\s*(?:participants?|learners?|trainees?|people|pax)",
        participant_text or text,
        flags=re.IGNORECASE,
    )
    if participant_match:
        participants = _safe_int(participant_match.group(1))
    elif participant_text:
        participant_number = re.search(r"\d+\s*[-\u2013]\s*(\d+)|\d+", participant_text)
        if participant_number:
            participants = _safe_int(participant_number.group(1) or participant_number.group(0))
    if participants is None:
        pax_match = re.search(r"\bno\.?\s*of\s*pax\s*:\s*(\d+)(?:\s*[-\u2013]\s*(\d+))?", text, flags=re.IGNORECASE)
        if pax_match:
            participants = _safe_int(pax_match.group(2) or pax_match.group(1))

    signals = sum(1 for signal in TRAINING_SIGNALS if signal in lower)
    confidence = 0.15
    if technology:
        confidence += 0.4
    if direct_request:
        confidence += 0.2
    if "trainer" in lower:
        confidence += 0.15
    if "requirement" in lower:
        confidence += 0.1
    if duration.get("duration_days") or duration.get("duration_hours"):
        confidence += 0.08
    if mode:
        confidence += 0.06
    if "share suitable trainer profiles" in lower or "trainer profiles" in lower:
        confidence += 0.08
    confidence = min(0.98, confidence + min(signals, 4) * 0.02)
    if technology and direct_request:
        # A named training request is safe for the acknowledgement template,
        # even when the client has not supplied the batch logistics yet.
        confidence = max(confidence, 0.9)
    if non_client_email:
        confidence = min(confidence, 0.25)

    requested_details = []
    clahan_managed_details = []
    detail_map = {
        "cv": "Updated CV / Trainer Profile",
        "resume": "Updated Resume",
        "trainer profile": "Updated CV / Trainer Profile",
        "consultant profile": "Updated CV / Trainer Profile",
        "updated profile": "Updated CV / Trainer Profile",
        "current location": "Current Location",
        "total experience": "Total Experience",
        "relevant experience": "Relevant Experience",
        "implementation experience": "Relevant Experience",
        "relevant training experience": "Relevant Training Experience",
        "availability": "Availability",
        "available dates for training": "Available dates for training",
        "available time slots": "Available time slots for technical call",
        "technical call": "Available time slots for technical call",
        "commercials": "Commercials (per hour/day)",
        "commercial": "Commercials (per hour/day)",
        "per hour": "Commercials (per hour/day)",
        "per day": "Commercials (per hour/day)",
        "linkedin": "LinkedIn Profile",
        "toc": "ToC",
        "table of contents": "ToC",
        "table of content": "ToC",
        "day wise content": "Day-wise ToC / course content",
        "day-wise content": "Day-wise ToC / course content",
        "course agenda": "ToC",
        "training agenda": "ToC",
        "detailed training proposal": "Training Proposal",
        "training proposal": "Training Proposal",
        "proposal": "Training Proposal",
        "methodology": "Methodology",
        "certification cost": "Certification cost, if applicable",
        "certifications": "Relevant Certifications",
        "relevant certifications": "Relevant Certifications",
        "similar technology": "Number of similar batches delivered",
        "batches delivered": "Number of similar batches delivered",
        "client names": "Client names where similar trainings were delivered",
        "system requirement": "System requirements / hardware",
        "hardware": "System requirements / hardware",
        "software required": "Software required for training",
        "availability of required software": "Availability of required software from trainer side",
    }
    for needle, label in detail_map.items():
        if needle in lower and label not in requested_details:
            requested_details.append(label)
    if lab_cost_requested:
        clahan_managed_details.append("Lab availability and cost")

    toc_requested = any(
        any(token in str(item or "").lower() for token in ("toc", "table of content", "course agenda", "day-wise", "day wise", "scope"))
        for item in requested_details
    )
    clahan_toc_request = bool(re.search(
        r"\b(?:prepare|create|generate|draft|share|send)\b.{0,80}\b(?:toc|table\s+of\s+content|course\s+agenda|day[-\s]?wise\s+content)\b",
        lower,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    trainer_toc_request = bool(re.search(
        r"\b(?:trainer|consultant|faculty)\b.{0,80}\b(?:share|send|provide)\b.{0,80}\b(?:toc|table\s+of\s+content|course\s+agenda|day[-\s]?wise\s+content)\b",
        lower,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    scope_attached = bool(re.search(r"\b(?:scope\s+of\s+the\s+delivery\s+attached|scope\s+attached|attached\s+scope|attachment)\b", lower))
    # When a client supplies scope and asks for day-wise content from the
    # trainer, preserve that scope and request a trainer-aligned delivery plan.
    if toc_requested and scope_attached and (
        trainer_toc_request
        or bool(re.search(r"\b(?:from\s+your\s+end|aligned\s+with\s+(?:the\s+)?(?:attached|shared)\s+scope)\b", lower))
    ):
        toc_action = "trainer_validate_scope"
    elif toc_requested:
        toc_action = "generate_by_clahan"
    else:
        toc_action = ""

    is_training_request = bool(technology) and direct_request and not non_client_email and not latest_coordination_intent
    inferred_client_name = _clean(sender_name)
    if "@" in inferred_client_name:
        inferred_client_name = ""
    if not inferred_client_name:
        local_part = _clean((sender_email or "").split("@")[0])
        inferred_client_name = _extract_person_name_from_local_part(local_part)

    return {
        "technology_needed": technology,
        "technology": technology,
        "domain": technology,
        "required_skills": [technology] if technology else [],
        "mode": mode,
        "delivery_mode": mode,
        "audience_level": audience_level,
        "timing": timing,
        "hands_on_lab": hands_on_lab,
        "lab_hours_per_day": lab_hours_per_day,
        "total_lab_duration_hours": total_lab_duration_hours,
        "lab_cost_requested": lab_cost_requested,
        "lab_required_tools_requested": "lab_requirements" in requirement_categories,
        "lab_delivery_preference": "local_or_cloud_to_be_confirmed" if "lab_delivery_preference" in requirement_categories else "",
        "trainer_cv_approval_requested": "trainer_profile" in requirement_categories,
        "requirement_items": requirement_items,
        "client_domain": client_domain,
        "client_industry": client_domain,
        "topics": topics,
        "custom_topics": topics,
        "participant_count": participants,
        "client_company": _client_company_from_email(sender_email, sender_name),
        "client_name": inferred_client_name or "Client",
        "client_email": _clean(sender_email),
        "requirement_source_text": requirement_source_text,
        "email_summary": _build_summary(technology, mode, duration.get("duration_text"), timing),
        "requested_details": requested_details,
        "clahan_managed_details": clahan_managed_details,
        "toc_requested": toc_requested,
        "toc_action": toc_action,
        "scope_attached": scope_attached,
        "scope_text": topics,
        "needs_clarification": _missing_training_details({
            "budget_total": budget.get("budget_total"),
            "budget_per_day": budget.get("budget_per_day"),
            "duration_days": duration.get("duration_days"),
            "duration_hours": duration.get("duration_hours"),
            "duration_text": duration.get("duration_text"),
            "timing": timing,
            "preferred_dates": dates.get("preferred_dates"),
            "training_dates": dates.get("training_dates"),
            "timeline_start": dates.get("timeline_start"),
            "mode": mode,
            "participant_count": participants,
        }),
        "urgency": "urgent" if "immediate" in lower or "earliest" in lower or "urgent" in lower else "normal",
        "confidence": round(confidence, 2),
        "is_training_request": is_training_request,
        "latest_coordination_intent": latest_coordination_intent,
        "latest_message_text": latest_body_text,
        "direct_request_language": direct_request,
        "is_non_client_email": non_client_email,
        "extraction_method": "deterministic_email_parser",
        **duration,
        **dates,
        **budget,
    }


def _merge_existing_requirement_context(
    extracted: Dict[str, Any],
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    previous = email_doc.get("extracted") or {}
    if not previous:
        return extracted

    merged = dict(extracted)
    carry_fields = (
        "technology_needed",
        "technology",
        "domain",
        "required_skills",
        "mode",
        "delivery_mode",
        "audience_level",
        "timing",
        "preferred_dates",
        "training_dates",
        "timeline_start",
        "timeline_end",
        "participant_count",
        "duration_text",
        "duration_days",
        "duration_hours",
        "budget_total",
        "budget_per_day",
        "budget_min",
        "budget_max",
        "budget_range",
        "budget_currency",
        "client_domain",
        "client_industry",
        "topics",
        "custom_topics",
        "client_company",
        "client_name",
        "client_email",
    )
    for field in carry_fields:
        value = merged.get(field)
        if value in (None, "", []):
            previous_value = previous.get(field)
            if previous_value not in (None, "", []):
                merged[field] = previous_value

    # A client may add a ToC, lab-cost, or other request in a later reply.
    # Retain the entire thread's requested deliverables rather than replacing
    # them with only the most recent message.
    merged["requested_details"] = _merge_unique_detail_values(
        previous.get("requested_details"), merged.get("requested_details"),
    )
    merged["clahan_managed_details"] = _merge_unique_detail_values(
        previous.get("clahan_managed_details"), merged.get("clahan_managed_details"),
    )
    merged["toc_requested"] = bool(previous.get("toc_requested") or merged.get("toc_requested"))
    if not merged.get("toc_action"):
        merged["toc_action"] = previous.get("toc_action") or ""

    budget_range = str(merged.get("budget_range") or "")
    if re.search(r"\bSubject:\b|\bTraining Dates?:\b", budget_range, flags=re.IGNORECASE):
        for field in ("budget_total", "budget_per_day", "budget_min", "budget_max", "budget_range", "budget_currency"):
            merged.pop(field, None)

    technology = merged.get("technology_needed") or merged.get("technology") or merged.get("domain")
    if technology:
        merged["technology_needed"] = technology
        merged["technology"] = technology
        merged["domain"] = technology
        if not merged.get("required_skills"):
            merged["required_skills"] = [technology]

    merged["needs_clarification"] = _missing_training_details(merged)
    if (
        technology
        and not merged.get("is_non_client_email")
        and (email_doc.get("requirement_id") or _has_training_duration(merged))
    ):
        merged["direct_request_language"] = True
        merged["is_training_request"] = True
    return merged


async def _merge_requirement_record_context(
    db: AsyncIOMotorDatabase,
    extracted: Dict[str, Any],
    requirement_id: Any,
) -> Dict[str, Any]:
    requirement_id = _clean(requirement_id)
    if not requirement_id:
        return extracted

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        return extracted

    merged = dict(extracted)
    field_map = {
        "technology_needed": "technology_needed",
        "technology": "technology_needed",
        "domain": "domain",
        "required_skills": "required_skills",
        "mode": "mode",
        "delivery_mode": "mode",
        "audience_level": "audience_level",
        "timing": "timing",
        "preferred_dates": "preferred_dates",
        "training_dates": "training_dates",
        "timeline_start": "timeline_start",
        "timeline_end": "timeline_end",
        "participant_count": "participant_count",
        "duration_text": "duration_text",
        "duration_days": "duration_days",
        "duration_hours": "duration_hours",
        "budget_total": "budget_total",
        "budget_per_day": "budget_per_day",
        "budget_min": "budget_min",
        "budget_max": "budget_max",
        "budget_range": "budget_range",
        "budget_currency": "budget_currency",
        "client_domain": "client_domain",
        "client_industry": "client_industry",
        "topics": "topics",
        "custom_topics": "custom_topics",
        "client_company": "client_company",
        "client_name": "client_name",
        "client_email": "client_email",
    }
    for target_field, source_field in field_map.items():
        value = merged.get(target_field)
        if value in (None, "", []):
            requirement_value = requirement.get(source_field)
            if requirement_value not in (None, "", []):
                merged[target_field] = requirement_value

    merged["requested_details"] = _merge_unique_detail_values(
        requirement.get("requested_details") or (requirement.get("metadata") or {}).get("requested_details"),
        merged.get("requested_details"),
    )
    merged["clahan_managed_details"] = _merge_unique_detail_values(
        requirement.get("clahan_managed_details") or (requirement.get("metadata") or {}).get("clahan_managed_details"),
        merged.get("clahan_managed_details"),
    )
    merged["toc_requested"] = bool(requirement.get("toc_requested") or merged.get("toc_requested"))
    if not merged.get("toc_action"):
        merged["toc_action"] = requirement.get("toc_action") or ""

    technology = merged.get("technology_needed") or merged.get("technology") or merged.get("domain")
    if technology:
        merged["technology_needed"] = technology
        merged["technology"] = technology
        merged["domain"] = technology
        if not merged.get("required_skills"):
            merged["required_skills"] = [technology]
        if not merged.get("is_non_client_email"):
            merged["direct_request_language"] = True
            merged["is_training_request"] = True
            merged["confidence"] = max(_safe_float(merged.get("confidence"), 0), 0.9)

    merged["needs_clarification"] = _missing_training_details(merged)
    return merged


def _build_summary(technology: str, mode: str, duration: Any, timing: str) -> str:
    parts = [part for part in [technology, mode, duration, timing] if part]
    return " / ".join(parts) if parts else "Training requirement details pending"


def _client_salutation(extracted: Dict[str, Any]) -> str:
    name = _clean(extracted.get("client_name"))
    if not name or name.lower() in {"client", "team"} or "@" in name or _looks_like_company_name(name):
        return "Client"
    return name[:1].upper() + name[1:]


def _client_time_greeting(name: str) -> str:
    clean_name = _clean(name) or "Team"
    hour = datetime.now(LOCAL_TZ).hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    return f"{greeting} {clean_name}"


def _reply_signature() -> str:
    return "Best Regards,\nClahan Technologies"


def _client_requested_items_for_reply(extracted: Dict[str, Any]) -> str:
    requested_details = extracted.get("requested_details") or []
    if isinstance(requested_details, (list, tuple, set)):
        request_texts = [str(item or "").lower() for item in requested_details]
        items = []
        checks = [
            (("cv", "resume", "profile"), "CV"),
            (("linkedin", "linked in"), "LinkedIn profile"),
            (("toc", "table of contents", "course agenda", "agenda", "curriculum"), "ToC"),
            (("experience", "implementation"), "relevant experience"),
            (("current location", "location"), "current location"),
            (("availability", "available"), "availability"),
            (("technical call", "slots", "time slots"), "technical call slots"),
            (("commercial", "commercials", "rate", "per hour", "per day"), "commercials"),
            (("software", "hardware", "system requirement"), "software/hardware requirements"),
            (("certification", "certifications"), "certifications"),
        ]
        for keys, label in checks:
            if any(any(key in text for key in keys) for text in request_texts) and label not in items:
                items.append(label)
        if items:
            if len(items) == 1:
                return items[0]
            if len(items) == 2:
                return f"{items[0]} and {items[1]}"
            return f"{', '.join(items[:-1])}, and {items[-1]}"

    haystack = " ".join(
        str(value or "")
        for value in extracted.values()
        if not isinstance(value, (dict, list, tuple, set))
    ).lower()
    items = []
    checks = [
        (("cv", "resume", "profile"), "CV"),
        (("linkedin", "linked in"), "LinkedIn profile"),
        (("toc", "table of contents", "course agenda", "agenda", "curriculum"), "ToC"),
        (("experience", "implementation"), "relevant experience"),
        (("current location", "location"), "current location"),
        (("availability", "available"), "availability"),
        (("technical call", "slots", "time slots"), "technical call slots"),
        (("commercial", "commercials", "rate", "per hour", "per day"), "commercials"),
        (("software", "hardware", "system requirement"), "software/hardware requirements"),
        (("certification", "certifications"), "certifications"),
    ]
    for keys, label in checks:
        if any(key in haystack for key in keys) and label not in items:
            items.append(label)
    if not items:
        items = ["CV", "LinkedIn profile", "requested details"]
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _has_explicit_profile_request(extracted: Dict[str, Any]) -> bool:
    requested_details = extracted.get("requested_details") or []
    if not isinstance(requested_details, (list, tuple, set)):
        return False
    profile_markers = ("cv", "resume", "profile", "linkedin", "linked in")
    return any(
        any(marker in str(item or "").lower() for marker in profile_markers)
        for item in requested_details
    )


def _client_short_requirement_ack(
    extracted: Dict[str, Any],
    intro: str = "",
    ask_missing: bool = True,
) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    missing = _format_missing_details(extracted) if ask_missing else ""
    opening = _clean(intro) or (
        "Thank you for sharing your training requirement."
        if missing
        else f"Thank you for sharing the {technology} training requirement."
    )
    clahan_note = (
        "\n\nWe will confirm lab availability and cost separately."
        if "Lab availability and cost" in (extracted.get("clahan_managed_details") or [])
        else ""
    )
    if missing:
        body = (
            "Dear Team\n\n"
            f"{opening}\n\n"
            "To help us refine the shortlist, please share:\n"
            f"{missing}{clahan_note}\n\n"
            + _reply_signature()
        )
    else:
        profile_action = (
            "We will share suitable trainer profiles with "
            if _has_explicit_profile_request(extracted)
            else "We will check suitable trainer availability and share suitable trainer profiles with "
        )
        body = (
            "Dear Team,\n\n"
            f"{opening}\n\n"
            f"{profile_action}"
            f"{_client_requested_items_for_reply(extracted)} for your review.{clahan_note}\n\n"
            + _reply_signature()
        )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _format_missing_details(extracted: Dict[str, Any]) -> str:
    if _has_explicit_profile_request(extracted):
        return ""

    missing = list(extracted.get("needs_clarification") or [])
    if extracted.get("duration_inferred_from_dates") and "Training duration" not in missing:
        missing.insert(0, "Training duration")
    if not missing:
        return ""

    lines = [f"- {item}" for item in missing]
    return "\n".join(lines)


def _client_reply_for_requirement(extracted: Dict[str, Any]) -> Dict[str, str]:
    return _client_short_requirement_ack(extracted)


def _client_full_details_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    return _client_short_requirement_ack(
        extracted,
        "Thank you for sharing the required details for your training requirement.",
    )


def _client_proceed_ack_reply(extracted: Dict[str, Any], details_later: bool = False) -> Dict[str, str]:
    if not details_later and not (extracted.get("needs_clarification") or []):
        return _client_short_requirement_ack(
            extracted,
            "Thank you for sharing the required details for your training requirement.",
        )
    return _client_short_requirement_ack(extracted, ask_missing=not details_later)


def _client_clarification_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    return _client_short_requirement_ack(extracted)


def _trainer_mail2_details_reply(email_doc: Dict[str, Any]) -> Dict[str, str]:
    trainer_name = _clean(email_doc.get("trainer_name") or email_doc.get("from_name") or "Trainer")
    extracted = email_doc.get("extracted") or {}
    requirement = email_doc.get("requirement") or {}
    domain = _clean(
        email_doc.get("technology")
        or extracted.get("technology_needed")
        or requirement.get("technology_needed")
        or "Training"
    )
    has_client_budget = bool(
        requirement.get("budget_total")
        or requirement.get("budget_per_day")
        or extracted.get("budget_total")
        or extracted.get("budget_per_day")
        or requirement.get("budget")
    )
    raw_requested_details = (
        requirement.get("requested_details")
        or extracted.get("requested_details")
        or []
    )
    requested_details = [_clean(item).lower() for item in raw_requested_details if _clean(item)]
    detail_lines: List[str] = []
    missing_requested_details = [
        _clean(item)
        for item in (email_doc.get("missing_requested_details") or [])
        if _clean(item)
    ]

    def add_detail(label: str) -> None:
        line = f"* {label}"
        if line not in detail_lines:
            detail_lines.append(line)

    if missing_requested_details:
        for item in missing_requested_details:
            add_detail(item)
    else:
        for item in requested_details:
            if any(token in item for token in ("trainer profile", "profile summary", "trainer details")):
                add_detail("Trainer profile")
            elif any(token in item for token in ("cv", "resume")):
                add_detail("CV/resume")
            elif "linkedin" in item or "linked in" in item:
                add_detail("LinkedIn profile")
            elif any(token in item for token in ("availability", "interview", "slot", "time slot", "schedule")):
                add_detail("Availability / interview slots")
            elif any(token in item for token in ("commercial", "budget", "cost", "charges", "rate")):
                if not has_client_budget:
                    add_detail("Commercial expectation per day/session")
            elif any(token in item for token in ("toc", "proposal", "agenda", "course outline")):
                add_detail("Table of Contents (ToC) / course agenda")
            elif "certification" in item or "certificate" in item:
                add_detail("Relevant certifications")

    if not detail_lines:
        detail_lines = [
            "* Trainer profile",
            "* CV/resume",
            "* LinkedIn profile",
        ]

    def first_value(*keys: str) -> str:
        for source in (requirement, extracted, email_doc):
            for key in keys:
                value = _clean(source.get(key) if isinstance(source, dict) else "")
                if value:
                    return value
        return ""

    training_lines = [f"* Technology: {domain}"]
    detail_fields = [
        ("Training dates", first_value("training_dates", "preferred_dates", "timeline_start")),
        (
            "Duration",
            first_value("duration_text")
            or (
                f"{first_value('duration_days')} days"
                if first_value("duration_days")
                else ""
            ),
        ),
        ("Mode", first_value("mode", "training_mode")),
        ("Audience", first_value("audience_level", "audience")),
        ("Participants", first_value("participant_count", "participants")),
        ("Timings", first_value("timing", "session_timing", "training_time")),
    ]
    for label, value in detail_fields:
        if value:
            training_lines.append(f"* {label}: {value}")

    body = (
        f"Dear {trainer_name},\n\n"
        "Thank you for your response. The confirmed training details are below:\n\n"
        + "\n".join(training_lines)
        + "\n\n"
        "To proceed, please share only the following outstanding item(s):\n\n"
        + "\n".join(detail_lines)
        + "\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": f"Training Requirement - {domain} | Additional Details Required", "body": body}


def _trainer_mail_for_requirement(extracted: Dict[str, Any], requirement_id: str) -> Dict[str, str]:
    # sanitize extracted technology to avoid accidental verb phrases like "conducting a corporate"
    raw_tech = _clean(extracted.get("technology_needed") or extracted.get("technology") or "").strip()
    tech = raw_tech
    if not tech or re.search(r"\bconduct(?:ing|ed)?\b|\blooking for\b|\brequirement for\b", tech, flags=re.IGNORECASE) or len(tech) > 60:
        tech = "Training"

    lines = [
        f"Technology: {tech}",
        f"Mode: {extracted.get('mode') or 'To be confirmed'}",
        f"Audience Level: {extracted.get('audience_level') or 'To be confirmed'}",
        f"Duration: {extracted.get('duration_text') or (str(extracted.get('duration_days')) + ' days' if extracted.get('duration_days') else 'To be confirmed')}",
        f"Timings: {extracted.get('timing') or 'To be confirmed'}",
    ]

    # Use a concise, single-render template matching the requested clean version.
    body = (
        "Dear Trainer,\n\n"
        "We have an immediate corporate training requirement and would like to check your interest and availability.\n\n"
        "Requirement Details:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\nPlease share the following details if you are interested and available:\n"
        "- Updated resume/profile\n"
        "- Total experience\n"
        "- Relevant training experience\n"
        "- Availability\n"
        "- Commercials per day\n"
        "- LinkedIn profile, if available\n\n"
        "Please also share 3 convenient interview/discussion slots with the date, time, and time zone. For example:\n"
        "- Monday, 15 September, 10:00 AM IST\n"
        "- Tuesday, 16 September, 2:00 PM IST\n"
        "- Wednesday, 17 September, 4:00 PM IST\n\n"
        f"Reference: {requirement_id}\n\n"
        + _reply_signature()
    )
    return {"subject": f"Corporate Training Requirement - {tech}", "body": body}


def _client_email_status_for_reply(reply: dict) -> dict:
    extracted = _extract_requirement_from_email(
        subject=reply.get("subject") or "",
        body=reply.get("clean_body") or reply.get("raw_body") or reply.get("body") or "",
        sender_email=reply.get("from_email") or reply.get("sender") or "",
        sender_name=reply.get("from_name") or "",
    )
    confidence = _safe_float(extracted.get("confidence"), 0)
    return {
        "status": "received",
        "reply_status": "received",
        "auto_send_eligible": False,
        "confidence": confidence,
        "auto_send_confidence": confidence,
        "extracted": extracted,
    }


async def _auto_send_settings(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    settings_doc = await _load_admin_settings(db)
    runtime_settings = get_settings()
    threshold_value = runtime_settings.AUTO_SEND_CONFIDENCE_THRESHOLD

    return {
        "enabled": bool(runtime_settings.AUTO_SEND_ENABLED),
        "threshold": _normalise_threshold(threshold_value, 0.85),
        "mailbox_addresses": _configured_mailbox_addresses(settings_doc),
    }


async def _mark_shortlist_pipeline_mail_sent(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    mail_type: str,
    sent_at: Optional[datetime] = None,
    requirement_id: str = "",
) -> bool:
    if mail_type != "mail2":
        return False

    effective_requirement_id = requirement_id or email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not effective_requirement_id or not trainer_id:
        return False

    now = sent_at or _now()
    result = await db["shortlists"].update_one(
        {"requirement_id": effective_requirement_id, "top_trainers.trainer_id": trainer_id},
        {
            "$set": {
                "top_trainers.$.pipeline_status": "mail2",
                "top_trainers.$.last_mail_type": "mail2",
                "top_trainers.$.last_mail_type_attempted": "mail2",
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mailed_at": now,
                "top_trainers.$.last_mail_error": "",
                "updated_at": now,
            }
        },
    )
    if result.matched_count:
        logger.info(
            "Advanced shortlist pipeline to mail2 for requirement=%s trainer=%s",
            effective_requirement_id,
            trainer_id,
        )
    return bool(result.matched_count)


async def _mark_shortlist_trainer_reply_received(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    *,
    stage: str,
    status: str,
    reply_at: Optional[datetime] = None,
    error: str = "",
) -> bool:
    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return False

    now = reply_at or _now()
    body = email_doc.get("body_snippet") or email_doc.get("clean_body") or email_doc.get("body") or ""
    set_fields = {
        "top_trainers.$.pipeline_status": status,
        "top_trainers.$.reply_status": "received",
        "top_trainers.$.last_reply_at": now,
        "top_trainers.$.last_reply_email_id": email_doc.get("email_id") or "",
        "top_trainers.$.last_reply_snippet": str(body or "")[:500],
        "top_trainers.$.reply_sentiment": email_doc.get("sentiment") or email_doc.get("reply_sentiment") or "",
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if stage == "mail1":
        set_fields["top_trainers.$.mail1_replied_at"] = now
    elif stage == "mail2":
        set_fields["top_trainers.$.mail2_replied_at"] = now
        set_fields["top_trainers.$.trainer_details_received"] = True
        set_fields["top_trainers.$.trainer_details_received_at"] = now
    if error:
        set_fields["top_trainers.$.last_mail_error"] = error

    result = await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": set_fields},
    )
    return bool(result.matched_count)


async def _send_missing_trainer_details_followup(
    db: AsyncIOMotorDatabase,
    *,
    email_doc: Dict[str, Any],
    requirement: Dict[str, Any],
    trainer_state: Dict[str, Any],
    missing_details: List[str],
    now: datetime,
) -> Dict[str, Any]:
    """Send one Mail 2 follow-up for real gaps from a positive Mail 1 reply."""
    requirement_id = _clean(email_doc.get("requirement_id"))
    trainer_id = _clean(email_doc.get("trainer_id"))
    if not requirement_id or not trainer_id:
        return {"success": False, "reason": "missing_requirement_or_trainer_link"}

    # This is deliberately one attempt per trainer and requirement. A polling
    # retry, a reopened message, or an incomplete second reply must never send
    # the same missing-details request again.
    existing = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "mail_type": "mail2_followup",
        },
        {"_id": 0, "email_id": 1, "status": 1, "sent_at": 1, "error_message": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        return {
            "success": existing.get("status") == "sent",
            "already_attempted": True,
            "email_id": existing.get("email_id") or "",
            "status": existing.get("status") or "",
            "error": existing.get("error_message") or "",
        }

    clean_missing = list(dict.fromkeys(_clean(item) for item in missing_details if _clean(item)))
    if not clean_missing:
        return {"success": False, "reason": "no_missing_details"}

    # Persist exactly what was missing before the email is sent. This makes the
    # message auditable and ensures any later reply is evaluated against the
    # same one-time request.
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.missing_requested_details": clean_missing,
            "top_trainers.$.pipeline_status": "mail1_replied",
            "top_trainers.$.last_reply_at": now,
            "top_trainers.$.last_reply_email_id": email_doc.get("email_id") or "",
            "top_trainers.$.last_reply_snippet": _clean(email_doc.get("classification_body") or email_doc.get("body"))[:500],
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )

    followup_doc = {
        **email_doc,
        "trainer_name": email_doc.get("trainer_name") or trainer_state.get("name") or trainer_state.get("trainer_name"),
        "requirement": requirement,
        "missing_requested_details": clean_missing,
        "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
        "office_mail_category": "trainer_interested",
    }
    message = _trainer_mail2_details_reply(followup_doc)
    # Reuse the standard, idempotent sender but explicitly mark this as the
    # one permitted missing-details follow-up, not the old generic Mail 2.
    send_result = await _send_client_auto_reply(
        db,
        followup_doc,
        message,
        requirement_id,
        mail_type_override="mail2_followup",
    )
    success = bool(send_result.get("success"))
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "waiting_reply2" if success else "mail1_replied",
            "top_trainers.$.last_mail_type": "mail2_followup" if success else trainer_state.get("last_mail_type"),
            "top_trainers.$.last_mail_type_attempted": "mail2_followup",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": now if success else trainer_state.get("last_mailed_at"),
            "top_trainers.$.last_mail_error": "" if success else _clean(send_result.get("error") or send_result.get("reason")),
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    return {**send_result, "missing_requested_details": clean_missing, "subject": message["subject"]}


def _money_to_int(raw_amount: Any, suffix: str = "") -> int:
    amount = _safe_float(str(raw_amount or "").replace(",", ""), 0)
    suffix = str(suffix or "").lower()
    if suffix in {"k", "thousand"}:
        amount *= 1000
    elif suffix in {"lakh", "lakhs"}:
        amount *= 100000
    return int(round(amount))


def _trainer_profile_commercial_amounts(trainer: Dict[str, Any]) -> List[int]:
    amounts: List[int] = []
    for key in (
        "commercial_amount",
        "commercial_rate",
        "quoted_amount",
        "quoted_rate",
        "day_rate",
        "rate",
        "trainer_target_rate",
    ):
        amount = _money_to_int(trainer.get(key))
        if amount >= 1000 and amount not in amounts:
            amounts.append(amount)

    for key in (
        "commercials",
        "commercial_text",
        "commercial_details",
        "reply_text",
        "last_reply_snippet",
    ):
        text = trainer.get(key)
        if not text:
            continue
        for amount in _trainer_commercial_amounts(text):
            if amount >= 1000 and amount not in amounts:
                amounts.append(amount)

    return sorted(amounts)


def _requested_trainer_details_for_client(requirement: Dict[str, Any], trainer: Dict[str, Any]) -> str:
    requested = {
        _clean(item).lower()
        for item in (
            requirement.get("requested_details")
            or (requirement.get("extracted") or {}).get("requested_details")
            or []
        )
        if _clean(item)
    }
    if not requested:
        requested = {"trainer profile", "cv", "resume", "linkedin profile", "availability", "commercials"}
    proposal_flow = "proposal" in _clean(
        requirement.get("batch_flow") or requirement.get("batch_type") or requirement.get("requirement_type")
    ).lower()
    if proposal_flow:
        managed_terms = ("commercial", "toc", "course agenda", "day-wise", "lab", "hardware", "software")
        requested = {item for item in requested if not any(term in item for term in managed_terms)}

    def wanted(*needles: str) -> bool:
        return any(any(needle in item for needle in needles) for item in requested)

    def first_value(*keys: str) -> str:
        for key in keys:
            value = trainer.get(key)
            if isinstance(value, list):
                text = ", ".join(_clean(item) for item in value if _clean(item))
            else:
                text = _clean(value)
            if text:
                return text
        return ""

    def clean_reply_text(value: str) -> str:
        text = _strip_quoted_email_history(_clean(value))
        lines = []
        for line in text.splitlines():
            stripped = _clean(line)
            if not stripped or stripped.startswith(">"):
                continue
            if re.search(r"(?i)\b(dear|regards),?\s*(clahan|team|trainer|megha|mohit)?\b", stripped):
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    reply_detail_text = clean_reply_text(
        first_value("details_reply_text", "trainer_details_text", "mail1_reply_text", "mail2_reply_text", "reply_text", "last_reply_snippet")
    )

    def extract_links(text: str) -> List[str]:
        links = re.findall(r"https?://[^\s<>)]+", text or "", flags=re.IGNORECASE)
        cleaned: List[str] = []
        for link in links:
            clean_link = link.rstrip(".,;:")
            if clean_link not in cleaned:
                cleaned.append(clean_link)
        return cleaned

    def linkedin_link(text: str) -> str:
        for link in extract_links(text):
            if "linkedin.com" in link.lower():
                return link
        return ""

    def reply_lines(*needles: str, limit: int = 3) -> str:
        matches: List[str] = []
        for line in reply_detail_text.splitlines():
            text = _clean(line)
            if not text:
                continue
            lower = text.lower()
            if any(needle in lower for needle in needles):
                matches.append(text)
            if len(matches) >= limit:
                break
        return "; ".join(matches)

    lines: List[str] = []
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name"))
    if trainer_name:
        lines.append(f"- Trainer: {trainer_name}")
    if wanted("trainer profile", "profile"):
        resume = first_value("resume_url", "resume_link", "cv_url", "cv_link", "resume_filename", "source_file")
        if resume:
            lines.append(f"- Trainer profile/CV: attached/shared ({resume})")
        else:
            lines.append("- Trainer profile/CV: attached/shared for review")
    if wanted("cv", "resume"):
        resume = first_value("resume_url", "resume_link", "cv_url", "cv_link", "resume_filename", "source_file")
        if resume:
            resume_line = f"- CV/resume: attached/shared ({resume})"
            if resume_line not in lines:
                lines.append(resume_line)
    if wanted("linkedin", "linked in"):
        linkedin = first_value("linkedin", "linkedin_url", "linkedin_profile") or linkedin_link(reply_detail_text)
        if linkedin:
            lines.append(f"- LinkedIn profile: {linkedin}")
    if wanted("availability", "available", "slot"):
        availability = first_value("availability", "available_dates", "availability_text")
        if availability:
            lines.append(f"- Availability: {clean_reply_text(availability)[:300]}")
    if wanted("commercial", "rate"):
        amounts = _trainer_profile_commercial_amounts(trainer)
        commercial_text = first_value("commercials", "commercial_text", "commercial_details") or reply_lines("commercial", "rate", "charges", "fee", "inr", "rs", "₹")
        if amounts:
            lines.append("- Commercials: " + ", ".join(f"INR {amount:,.0f} per day/session" for amount in amounts))
        elif commercial_text:
            lines.append(f"- Commercials: {commercial_text[:400]}")
    if wanted("toc", "agenda", "curriculum"):
        toc = first_value("toc_reply_text", "toc_text", "toc", "course_agenda", "agenda")
        if toc:
            lines.append(f"- ToC/course agenda: {toc[:800]}")
    if wanted("certification"):
        certifications = first_value("certifications", "certification")
        if certifications:
            lines.append(f"- Certifications: {certifications}")
    return "\n".join(lines)


def _trainer_commercial_amounts(text: Any) -> List[int]:
    reply_text = _strip_quoted_email_history(text)
    if not reply_text:
        return []

    rupee = re.escape(chr(0x20B9))
    amounts: List[int] = []
    range_pattern = (
        rf"(?:INR|Rs\.?|{rupee}|commercials?|rates?|charges?|fees?|cost)?\D{{0,30}}"
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:-|to|–|—)\s*"
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?"
    )
    patterns = [
        (rf"(?:INR|Rs\.?|{rupee})\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"\b(?:commercials?|rates?|charges?|fees?|cost)\b\D{0,80}([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:/-)?\s*(?:per\s*(?:day|session)|/day|/session)", True),
    ]
    contextual_line = re.compile(r"\b(?:commercials?|rates?|charges?|fees?|cost)\b", flags=re.IGNORECASE)
    for line in reply_text.splitlines():
        line_has_money_context = bool(contextual_line.search(line))
        for match in re.finditer(range_pattern, line, flags=re.IGNORECASE):
            suffix = match.group(4) or match.group(2)
            for raw_amount, raw_suffix in ((match.group(1), suffix), (match.group(3), suffix)):
                amount = _money_to_int(raw_amount, raw_suffix)
                if amount >= 1000 and amount not in amounts:
                    amounts.append(amount)
        for pattern, requires_context in patterns:
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                if requires_context and not line_has_money_context:
                    continue
                amount = _money_to_int(match.group(1), match.group(2) if len(match.groups()) > 1 else "")
                if amount >= 1000 and amount not in amounts:
                    amounts.append(amount)
    return amounts


def _client_budget_amounts(text: Any) -> List[int]:
    reply_text = _strip_quoted_email_history(text)
    if not reply_text:
        return []

    rupee = re.escape(chr(0x20B9))
    amounts: List[int] = []
    budget_context = re.compile(r"\b(?:budget|commercials?|rates?|charges?|fees?|cost)\b", flags=re.IGNORECASE)
    patterns = [
        (rf"(?:INR|Rs\.?|{rupee})\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"\b(?:budget|commercials?|rates?|charges?|fees?|cost)\b\D{0,30}([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:/-)?\s*(?:per\s*(?:day|session|hour|hr)|/day|/session|/hour|/hr)?", True),
    ]
    for line in reply_text.splitlines():
        line_has_budget_context = bool(budget_context.search(line))
        for pattern, requires_context in patterns:
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                if requires_context and not line_has_budget_context:
                    continue
                amount = _money_to_int(match.group(1), match.group(2) if len(match.groups()) > 1 else "")
                if amount >= 1000 and amount not in amounts:
                    amounts.append(amount)
    return amounts


def _commercial_unit(text: Any) -> str:
    reply_text = _strip_quoted_email_history(text).lower()
    if re.search(r"\b(?:per\s*(?:hour|hr)|/hour|/hr)\b", reply_text):
        return "hour"
    return "day"


def _trainer_rate_from_client_budget(client_budget: float) -> float:
    raw_rate = max(float(client_budget or 0) * 0.70, 0)
    if raw_rate <= 0:
        return 0
    # Present trainer offers in whole-thousand commercial bands while ensuring
    # the trainer's approved 70% share is never rounded down.
    return int(math.ceil(raw_rate / 1000.0) * 1000)


def _client_rate_from_trainer_rate(trainer_rate: float) -> float:
    trainer_rate = float(trainer_rate or 0)
    return trainer_rate / 0.70 if trainer_rate > 0 else 0


def _client_budget_from_requirement(requirement: Dict[str, Any]) -> float:
    return _safe_float(
        requirement.get("client_budget_per_day")
        or requirement.get("budget_per_day")
        or requirement.get("budget"),
        0.0,
    )


def _trainer_target_from_requirement(requirement: Dict[str, Any]) -> float:
    target = _safe_float(
        requirement.get("trainer_visible_budget_per_session")
        or requirement.get("trainer_requested_budget_per_session"),
        0.0,
    )
    if not target:
        target = _trainer_rate_from_client_budget(_client_budget_from_requirement(requirement))
    return target


def _client_rate_for_trainer_quote(trainer_rate: float, requirement: Dict[str, Any]) -> float:
    trainer_rate = float(trainer_rate or 0)
    if trainer_rate <= 0:
        return 0
    flow_value = _clean(
        requirement.get("batch_flow")
        or requirement.get("batch_type")
        or requirement.get("requirement_type")
        or requirement.get("pipeline_target")
    ).lower()
    if "proposal" in flow_value:
        return trainer_rate * 1.30
    client_budget = _client_budget_from_requirement(requirement)
    trainer_target = _trainer_target_from_requirement(requirement)
    if client_budget and trainer_target and trainer_rate <= trainer_target:
        return client_budget
    return trainer_rate * 1.30


def _trainer_commercial_matches_requirement(amounts: List[int], requirement: Dict[str, Any]) -> bool:
    if not amounts:
        return False
    trainer_budget = _trainer_target_from_requirement(requirement)
    return bool(trainer_budget and min(amounts) <= trainer_budget)


def _trainer_budget_amounts_from_requirement(requirement: Dict[str, Any]) -> List[int]:
    trainer_budget = _safe_float(
        requirement.get("trainer_visible_budget_per_session")
        or requirement.get("trainer_requested_budget_per_session"),
        0.0,
    )
    if not trainer_budget:
        client_budget = _safe_float(
            requirement.get("client_budget_per_day")
            or requirement.get("budget_per_day")
            or requirement.get("budget"),
            0.0,
        )
        trainer_budget = _trainer_rate_from_client_budget(client_budget)
    return [int(round(trainer_budget))] if trainer_budget >= 1000 else []


def _find_shortlist_trainer(shortlist: Dict[str, Any], trainer_id: str) -> Dict[str, Any]:
    for trainer in shortlist.get("top_trainers") or []:
        if str(trainer.get("trainer_id") or "") == str(trainer_id or ""):
            return trainer
    return {}


async def _find_active_slot_context_by_trainer_email(
    db: AsyncIOMotorDatabase,
    trainer_email: str,
) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
    email = _email_address(trainer_email)
    if not email:
        return "", "", {}, {}
    shortlist = await db["shortlists"].find_one(
        {
            "top_trainers": {
                "$elemMatch": {
                    "$or": [
                        {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
                        {"trainer_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
                    ],
                    "pipeline_status": {"$in": ["slot_booked", "details_received", "waiting_reply3"]},
                }
            }
        },
        {"_id": 0},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    if not shortlist:
        return "", "", {}, {}
    for trainer in shortlist.get("top_trainers") or []:
        trainer_addr = _email_address(trainer.get("email") or trainer.get("trainer_email"))
        if trainer_addr == email:
            status = _clean(trainer.get("pipeline_status") or trainer.get("slot_status")).lower()
            if status in {"slot_booked", "details_received", "waiting_reply3", "sent_to_client", "clarification_sent"}:
                return _clean(shortlist.get("requirement_id")), _clean(trainer.get("trainer_id")), shortlist, trainer
    return "", "", {}, {}


def _client_name_from_context(requirement: Dict[str, Any], shortlist: Dict[str, Any]) -> str:
    for source in (requirement, shortlist):
        for key in ("client_name", "client_company", "company_name"):
            value = _clean(source.get(key))
            if value and "@" not in value and value.lower() not in {"client", "unknown", "none"}:
                return value
        email_value = _email_address(source.get("client_email") or source.get("email") or "")
        if email_value:
            inferred = _extract_person_name_from_local_part(email_value.split("@", 1)[0])
            if inferred:
                return inferred
    return "Team"


async def _client_email_from_context(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    trainer_email: str,
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
) -> str:
    for source in (requirement, shortlist):
        for key in ("client_email", "contact_email", "from_email"):
            value = _email_address(source.get(key))
            if value and "@" in value and value != trainer_email:
                return value

    query = {
        "requirement_id": requirement_id,
        "from_email": {"$exists": True, "$nin": ["", None, trainer_email]},
        "$or": [
            {"email_classification.person_type": "corporate_client"},
            {"extracted.is_training_request": True},
            {"is_training_request": True},
        ],
    }
    client_doc = await db["client_emails"].find_one(
        query,
        {"_id": 0, "from_email": 1, "extracted": 1},
        sort=[("created_at", 1), ("received_at", 1)],
    )
    if client_doc:
        value = _email_address(client_doc.get("from_email"))
        if value and "@" in value and value != trainer_email:
            return value
    return ""


def _trainer_commercial_body(
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    trainer: Dict[str, Any],
    client_rates: List[int],
) -> Dict[str, str]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "training"
    )
    if technology.strip().lower() == "devops":
        technology = "DevOps"
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_name = _client_name_from_context(requirement, shortlist)
    certifications = trainer.get("certifications") or []
    if isinstance(certifications, list):
        certifications_text = ", ".join(_clean(item) for item in certifications if _clean(item))
    else:
        certifications_text = _clean(certifications)
    skills = trainer.get("skills") or []
    if isinstance(skills, list):
        skills_text = ", ".join(_clean(item) for item in skills[:8] if _clean(item))
    else:
        skills_text = _clean(skills)
    def _client_safe_profile(value: Any) -> str:
        text = _clean(value)
        if not text:
            return ""
        text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:email|e-mail|phone|mobile|contact)\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d{10,}\b", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text[:900].strip()

    def _fallback_toc() -> str:
        source_topics = (
            requirement.get("topics")
            or requirement.get("scope")
            or requirement.get("requested_topics")
            or requirement.get("extracted", {}).get("topics")
            or shortlist.get("topics")
            or []
        )
        if isinstance(source_topics, str):
            topics = [part.strip(" -") for part in re.split(r"[,;\n]+", source_topics) if part.strip(" -")]
        elif isinstance(source_topics, list):
            topics = [_clean(item) for item in source_topics if _clean(item)]
        else:
            topics = []
        if not topics and skills_text:
            topics = [part.strip() for part in skills_text.split(",") if part.strip()]
        topics = topics[:8] or [technology]
        return "\n".join(f"- {item}" for item in topics)

    profile_text = _client_safe_profile(
        trainer.get("profile_summary")
        or trainer.get("trainer_profile")
        or trainer.get("profile")
        or trainer.get("summary")
    )
    toc_text = _clean(
        trainer.get("toc_reply_text")
        or trainer.get("toc_text")
        or trainer.get("toc")
        or trainer.get("course_agenda")
        or trainer.get("agenda")
    )

    duration_days = _safe_int(
        requirement.get("duration_days")
        or requirement.get("commercial_working_days")
        or requirement.get("number_of_days"),
        0,
    )
    rate_lines_list = []
    for amount in client_rates:
        line = f"- INR {amount:,.0f} per day/session"
        if duration_days > 1:
            line += f" x {duration_days} days = INR {amount * duration_days:,.0f} total"
        rate_lines_list.append(line)
    rate_lines = "\n".join(rate_lines_list)
    details = [
        f"- Trainer: {trainer_name}",
        f"- Technology: {technology}",
    ]
    if certifications_text:
        details.append(f"- Certifications: {certifications_text}")
    if skills_text:
        details.append(f"- Core strengths: {skills_text}")
    profile_lines = []
    if profile_text:
        profile_lines.append("Trainer Profile Summary")
        profile_lines.append(profile_text)
    elif skills_text or certifications_text:
        profile_lines.append("Trainer Profile Summary")
        profile_lines.append("A suitable trainer profile is available for client review, with relevant delivery experience aligned to the requested technology.")
    requested_text = " ".join(
        _clean(item).lower()
        for item in (
            requirement.get("requested_details")
            or (requirement.get("extracted") or {}).get("requested_details")
            or []
        )
    )
    wants_toc = bool(re.search(r"\b(?:toc|table of contents?|course agenda|curriculum|syllabus)\b", requested_text))
    toc_lines = []
    if toc_text:
        toc_lines.append("Proposed ToC / Course Agenda")
        toc_lines.append(toc_text)
    elif wants_toc:
        toc_lines.append("Proposed ToC / Course Agenda")
        toc_lines.append(_fallback_toc())

    subject = f"Shortlisted Trainer Profile - {technology}"
    extra_sections = ""
    if profile_lines:
        extra_sections += "\n\n" + "\n".join(profile_lines)
    if toc_lines:
        extra_sections += "\n\n" + "\n".join(toc_lines)
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"Trainer {trainer_name} has shared the required details and commercials for the {technology} requirement.\n\n"
        "Trainer Summary:\n"
        f"{chr(10).join(details)}\n\n"
        "Commercials for your review:\n"
        f"{rate_lines}"
        f"{extra_sections}\n\n"
        "Please review and confirm if we can proceed with this trainer. Once approved, we will move ahead with interview/slot coordination.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _trainer_budget_negotiation_message(
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    client_budget: int,
    target_amount: int,
    unit: str,
) -> Dict[str, str]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "the training requirement"
    )
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    unit_text = "per hour" if unit == "hour" else "per day"
    subject = f"Re: Training Requirement - {technology} | Commercial Discussion"
    body = (
        f"Dear {trainer_name},\n\n"
        f"Thank you for sharing your commercial expectation for the {technology} requirement.\n\n"
        f"For this engagement, please confirm if you can proceed at INR {target_amount:,.0f} {unit_text}.\n\n"
        "Once confirmed, we will move ahead with the client coordination.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _commercial_negotiation_reply_intent(text: Any, target_amount: int = 0) -> str:
    reply_text = _strip_quoted_email_history(text)
    lower = reply_text.lower()
    if not lower:
        return "unknown"

    negative_patterns = (
        r"\b(?:not|can't|cannot|cant|unable)\b.{0,40}\b(?:accept|agree|proceed|work|workable|possible|ok|okay)\b",
        r"\b(?:not\s+possible|not\s+workable|not\s+okay|not\s+ok|cannot\s+do|can't\s+do|cant\s+do)\b",
        r"\b(?:decline|declined|reject|rejected|no\s+thanks|commercials?\s+are\s+fixed|rate\s+is\s+fixed)\b",
    )
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in negative_patterns):
        return "rejected"

    amounts = _trainer_commercial_amounts(reply_text)
    if amounts and target_amount > 0:
        return "accepted" if min(amounts) <= target_amount else "counter_offer"

    acceptance_patterns = (
        r"\bi\s+(?:accept|agree|confirm)\b",
        r"\b(?:accepted|agreed|confirmed)\b",
        r"\baccept(?:ed)?\s+(?:the\s+)?same\b",
        r"\b(?:same\s+is\s+fine|same\s+works|this\s+is\s+fine|this\s+works)\b",
        r"\b(?:ok|okay|sure|yes)\b.{0,40}\b(?:proceed|confirm|accept|agree|workable|fine)\b",
        r"\b(?:workable|fine\s+with\s+me|good\s+to\s+go|let'?s\s+proceed)\b",
    )
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in acceptance_patterns):
        return "accepted"

    if amounts:
        return "counter_offer"
    return "unknown"


def _client_same_commercial_acceptance(text: Any) -> bool:
    reply_text = _strip_quoted_email_history(text)
    lower = reply_text.lower()
    if not lower:
        return False

    rejection_patterns = (
        r"\b(?:not|cannot|can't|cant|unable)\b.{0,40}\b(?:accept|approve|agree|proceed|work|ok|okay|fine)\b",
        r"\b(?:not\s+approved|not\s+accepted|not\s+okay|not\s+ok|not\s+fine|too\s+high|reduce|negotiate)\b",
    )
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in rejection_patterns):
        return False

    acceptance_patterns = (
        r"\b(?:same|shared|quoted|mentioned|given|current)\s+(?:commercials?|rates?|charges?|fees?|cost|amount|quote)\b.{0,80}\b(?:accept(?:ed)?|approv(?:e|ed)|agree(?:d)?|confirm(?:ed)?|ok(?:ay)?|fine|work(?:s|able)?|proceed)\b",
        r"\b(?:accept(?:ed)?|approv(?:e|ed)|agree(?:d)?|confirm(?:ed)?|ok(?:ay)?|fine|work(?:s|able)?|proceed)\b.{0,80}\b(?:same|shared|quoted|mentioned|given|current)\s+(?:commercials?|rates?|charges?|fees?|cost|amount|quote)\b",
        r"\b(?:same\s+is\s+fine|same\s+works|same\s+accepted|same\s+approved|same\s+commercials?\s+(?:ok|okay|fine|accepted|approved|workable))\b",
        r"\b(?:go\s+ahead|please\s+proceed|we\s+can\s+proceed|proceed\s+with\s+(?:this|the)\s+trainer)\b",
    )
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in acceptance_patterns)


def _trainer_initial_reply_intent(text: Any) -> str:
    reply_text = _strip_quoted_email_history(text)
    lower = reply_text.lower()
    if not lower:
        return "unknown"
    negative_patterns = (
        r"\b(?:not|no)\b.{0,35}\b(?:interested|intersted|available|avaliable|possible|able|free)\b",
        r"\b(?:unavailable|unavaliable|decline|declined|reject|rejected|no\s+thanks)\b",
        r"\bsorry\b.{0,45}\b(?:not|can't|cannot|cant|unable)\b",
    )
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in negative_patterns):
        return "declined"
    positive_patterns = (
        r"\b(?:interested|available|yes|ok|okay|sure|confirm|can\s+do|will\s+do)\b",
    )
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in positive_patterns):
        return "interested"
    return "unknown"


def _trainer_resume_attachment_present(email_doc: Optional[Dict[str, Any]] = None) -> bool:
    email_doc = email_doc or {}
    # A profile already held in the trainer record is just as authoritative as
    # a newly attached CV.  Do not ask a shortlisted trainer to resend it.
    for profile in email_doc.get("attachment_profiles") or []:
        if not isinstance(profile, dict):
            continue
        if any(_clean(profile.get(key)) for key in (
            "resume_url", "resume_link", "cv_url", "cv_link", "resume_filename",
            "source_file", "profile", "trainer_profile", "resume", "resume_text",
        )) or profile.get("profile_document_present"):
            return True
    # Receiving the requested document and extracting claims from it are
    # separate concerns. A bounded, safely captured CV/profile file satisfies
    # the document handoff even when profile extraction is delayed or fails.
    for attachment in email_doc.get("attachments") or []:
        if not isinstance(attachment, dict) or not attachment.get("safe_client_scope"):
            continue
        filename = str(attachment.get("filename") or "").strip().lower()
        filename_words = re.sub(r"[^a-z0-9]+", " ", filename)
        if filename.endswith((".pdf", ".doc", ".docx", ".rtf", ".odt")) and re.search(
            r"\b(?:cv|resume|profile|biodata)\b", filename_words
        ):
            return True
    return False


def _requested_detail_matches_category(detail: Any, key: str) -> bool:
    text = _clean(detail).lower()
    if not text:
        return False
    if key == "cv" and re.search(r"\b(?:linkedin|linked\s*in)\b", text):
        return False
    checks = {
        "cv": r"\b(?:cv|resume|trainer profile|updated profile|trainer biodata|biodata)\b",
        "linkedin": r"\b(?:linkedin|linked\s*in)\b",
        "experience": r"\b(?:experience|implementation|hands[-\s]?on|batches delivered|trainings delivered|similar trainings?)\b",
        "certifications": r"\b(?:certification|certifications|certificate|certified)\b",
        "current_location": r"\b(?:current location|trainer location|consultant location|location)\b",
        "availability": r"\b(?:availability|available|dates?|timings?|schedule|free)\b",
        "technical_slots": r"\b(?:technical call|available time slots|interview slots|discussion slots)\b",
        "training_dates": r"\b(?:available dates for training|training dates availability|dates for training|training dates)\b",
        "commercials": r"\b(?:commercial|commercials|per hour|per day|rate|charges|budget|cost|fee|fees)\b",
        "certification_cost": r"\b(?:certification cost|certificate cost)\b",
        "toc": r"\b(?:toc|table of content|table of contents|day[-\s]?wise|course agenda|curriculum|syllabus|scope of the delivery)\b",
        "similar_batches": r"\b(?:batches delivered|number of similar batches|similar batches)\b",
        "similar_clients": r"\b(?:client names|similar trainings were delivered|similar clients)\b",
        "hardware": r"\b(?:system requirement|system requirements|hardware)\b",
        "software": r"\b(?:software required|required software|software)\b",
    }
    pattern = checks.get(key)
    return bool(pattern and re.search(pattern, text, flags=re.IGNORECASE))


def _trainer_detail_evidence_doc(
    email_doc: Optional[Dict[str, Any]] = None,
    trainer_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    email_doc = email_doc or {}
    trainer_state = trainer_state or {}
    text_values: List[str] = []
    for source in (trainer_state, email_doc):
        if not isinstance(source, dict):
            continue
        for key in (
            "classification_body",
            "clean_body",
            "body",
            "body_snippet",
            "details_reply_text",
            "trainer_details_text",
            "mail1_reply_text",
            "mail2_reply_text",
            "reply_text",
            "last_reply_snippet",
            "linkedin",
            "linkedin_url",
            "linkedin_profile",
            "availability",
            "available_dates",
            "availability_text",
            "commercials",
            "commercial_text",
            "commercial_details",
            "current_location",
            "location",
            "certifications",
            "certification",
            "toc_reply_text",
            "toc_text",
            "toc",
            "course_agenda",
            "agenda",
        ):
            value = source.get(key)
            if isinstance(value, list):
                value = ", ".join(_clean(item) for item in value if _clean(item))
            value = _clean(value)
            if value:
                text_values.append(value)

    attachments = list(email_doc.get("attachments") or [])
    profiles = list(email_doc.get("attachment_profiles") or [])
    if any(_clean(trainer_state.get(key)) for key in (
        "resume_url", "resume_link", "cv_url", "cv_link", "resume_filename",
        "source_file", "profile", "trainer_profile", "resume", "resume_text",
    )):
        profiles.append({
            "source": "shortlist",
            "profile_document_present": True,
            "resume_url": trainer_state.get("resume_url") or trainer_state.get("cv_url"),
            "resume_filename": trainer_state.get("resume_filename") or trainer_state.get("source_file"),
            "profile": trainer_state.get("profile") or trainer_state.get("trainer_profile") or trainer_state.get("resume"),
        })

    combined = {
        **email_doc,
        "classification_body": "\n".join(dict.fromkeys(text_values)),
        "clean_body": "\n".join(dict.fromkeys(text_values)),
        "attachments": attachments,
        "attachment_profiles": profiles,
    }
    return combined


def _trainer_missing_requested_details(
    text: Any,
    requirement: Optional[Dict[str, Any]] = None,
    email_doc: Optional[Dict[str, Any]] = None,
) -> List[str]:
    reply_text = _strip_quoted_email_history(text)
    lower = reply_text.lower()
    requirement = requirement or {}
    proposal_flow = "proposal" in _clean(
        requirement.get("batch_flow") or requirement.get("batch_type") or requirement.get("requirement_type")
    ).lower()
    if not lower:
        return ["Updated CV / Trainer Profile", "LinkedIn Profile", "Relevant training and implementation experience", "Availability"]
    source = " ".join(
        _clean(requirement.get(key))
        for key in ("client_request", "requirement_text", "original_email_body", "email_body", "raw_email", "description")
    ).lower()
    raw_requested_details = requirement.get("requested_details") or (requirement.get("metadata") or {}).get("requested_details") or []
    if not isinstance(raw_requested_details, (list, tuple, set)):
        raw_requested_details = [raw_requested_details] if _clean(raw_requested_details) else []
    requested_details = [_clean(item) for item in raw_requested_details if _clean(item)]
    explicit_requests = " ".join(requested_details).lower()
    has_explicit_requests = bool(requested_details)
    request_context = f"{explicit_requests} {source}".strip()
    technology = _clean(requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain") or "training")
    requested = [
        ("cv", "Updated CV / Trainer Profile", r"\b(?:cv|resume|trainer profile|profile attached|attached profile|attached my profile|updated profile|attachment|attached)\b"),
        ("linkedin", "LinkedIn Profile", r"linkedin\.com|linked\s*in|linkedin profile|linkedin"),
        ("experience", f"{technology} implementation and training experience", r"\b(?:experience|implementation|hands[-\s]?on|training experience|trained|delivered|worked on|years?|yrs?)\b"),
        ("certifications", "Relevant certifications", r"\b(?:certification|certifications|certified|certificate|not certified|no certification|none)\b"),
        ("current_location", "Current Location", r"\b(?:current location|location|based in|from|pune|mumbai|bangalore|bengaluru|hyderabad|chennai|delhi|noida|gurgaon|remote|onsite)\b"),
        ("availability", "Availability", r"\b(?:available|availability|slots?|dates?|timings?|schedule|free|can join|can take|from|to|weekdays|weekends|morning|afternoon|evening)\b"),
        ("technical_slots", "Available time slots for technical call", r"\b(?:slot|slots|technical call|discussion|interview|am|pm|ist|available)\b"),
        ("training_dates", "Available dates for training", r"\b(?:available|availability|dates?|from|start|can start|training)\b"),
        ("commercials", "Commercials (per hour/day)", r"\b(?:inr|rs\.?|₹|rate|charges?|commercial|commercials|fee|fees|per day|per hour|per session|cost)\b"),
        ("certification_cost", "Certification cost, if applicable", r"\b(?:certification cost|certificate cost|not applicable|na|n/a|none|included|extra)\b"),
        ("toc", "Table of Content (TOC) / day-wise content", r"\b(?:toc|table of content|table of contents|agenda|curriculum|day[-\s]?wise|scope|content|modules?)\b"),
        ("similar_batches", "Number of similar batches delivered", r"\b(?:batches|trainings delivered|delivered|similar technology|corporate trainings?|count|number)\b"),
        ("similar_clients", "Client names where similar trainings were delivered", r"\b(?:client names?|delivered for|trained for|companies|organizations|confidential|nda)\b"),
        ("hardware", "System requirements / hardware", r"\b(?:hardware|system requirements?|ram|cpu|laptop|machine|browser|not applicable|na|n/a)\b"),
        ("software", "Software required for training", r"\b(?:software|required software|tools?|install|license|availability of required software|not applicable|na|n/a)\b"),
    ]
    fallback_required = {
        "cv": True,
        "linkedin": True,
        "experience": bool(re.search(r"experience|implementation|hands[-\s]?on|batches delivered|trainings delivered", request_context)),
        "certifications": not source or bool(re.search(r"certification|certifications|certificate|certified", source)),
        "current_location": bool(re.search(r"current location|trainer location|consultant location", source)),
        "availability": True,
        "technical_slots": bool(re.search(r"technical call|available time slots|interview slots|discussion slots", source)),
        "training_dates": bool(re.search(r"available dates for training|training dates availability|dates for training", source)),
        "commercials": not source or bool(re.search(r"commercial|commercials|per hour|per day|rate|charges|budget|cost", source)),
        "certification_cost": bool(re.search(r"certification cost", source)),
        "toc": bool(re.search(r"toc|table of content|table of contents|day[-\s]?wise content|scope of the delivery|course agenda", source)),
        "similar_batches": bool(re.search(r"batches delivered|similar technology", source)),
        "similar_clients": bool(re.search(r"client names|similar trainings were delivered", source)),
        "hardware": bool(re.search(r"system requirement|hardware", source)),
        "software": bool(re.search(r"software required|required software", source)),
    }
    resume_attached = _trainer_resume_attachment_present(email_doc)
    positive_intent = _trainer_initial_reply_intent(reply_text) == "interested"
    has_offered_budget = any(requirement.get(key) not in (None, "", []) for key in ("budget_total", "budget_per_day", "client_budget_per_day", "trainer_visible_budget_per_session"))
    client_toc_supplied = False
    for attachment in requirement.get("source_attachments") or []:
        if not isinstance(attachment, dict) or not attachment.get("safe_client_scope"):
            continue
        filename_words = re.sub(r"[^a-z0-9]+", " ", str(attachment.get("filename") or "").lower())
        if re.search(r"\b(?:toc|agenda|curriculum|syllabus|course outline)\b", filename_words):
            client_toc_supplied = True
            break
    missing: List[str] = []
    for key, label, pattern in requested:
        # Commercials, ToC and lab-cost inputs are Clahan-managed in every
        # flow. They are never a trainer quote or a late duplicate request.
        if key in {"commercials", "certification_cost", "toc", "hardware", "software"}:
            continue
        required = (
            any(_requested_detail_matches_category(item, key) for item in requested_details)
            if has_explicit_requests
            else fallback_required.get(key, False)
        )
        supplied_by_resume = resume_attached and key == "cv"
        if key == "experience":
            supplied_by_resume = resume_attached
        supplied_by_intent = positive_intent and (
            key == "availability" or (key == "commercials" and has_offered_budget)
        )
        supplied_by_client = key == "toc" and client_toc_supplied
        if required and not supplied_by_resume and not supplied_by_intent and not supplied_by_client and not re.search(pattern, lower, flags=re.IGNORECASE):
            missing.append(label)
    # A detail-only reply must not be blocked by interview slots unless the
    # client or requirement explicitly requested those slots.
    slots_required = bool(requirement.get("request_interview_slots")) or any(
        _requested_detail_matches_category(item, "technical_slots")
        for item in requested_details
    ) or (not has_explicit_requests and fallback_required.get("technical_slots", False))
    if slots_required and _slot_reply_intent(reply_text) != "valid_slots":
        missing.append("Exactly three interview/discussion slots (date, time, and time zone)")
    return missing


def _trainer_reply_has_requested_details(
    text: Any,
    requirement: Optional[Dict[str, Any]] = None,
    email_doc: Optional[Dict[str, Any]] = None,
) -> bool:
    return not _trainer_missing_requested_details(text, requirement, email_doc)

def _trainer_slot_booking_message(
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
) -> Dict[str, str]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "the training requirement"
    )
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    slots_text = (
        "- Date: 1 September 2026, Time: 10:00 AM - 10:30 AM IST\n"
        "- Date: 2 September 2026, Time: 2:00 PM - 2:30 PM IST\n"
        "- Date: 3 September 2026, Time: 4:00 PM - 4:30 PM IST"
    )
    subject = f"Interview Slot Booking - {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        "Please share three convenient interview/discussion slots with date, time, and time zone so we can coordinate with the client.\n\n"
        "Preferred format:\n"
        f"{slots_text}\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _slot_reply_metrics(text: Any) -> Dict[str, int]:
    clean = _strip_quoted_email_history(text).lower()
    if not clean:
        return {"date_hits": 0, "time_hits": 0, "slot_hints": 0, "slot_count": 0}

    date_patterns = (
        r"\b\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b",
        r"\b(?:today|tomorrow)\b",
    )
    time_patterns = (
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        r"\b\d{1,2}(?::\d{2})?\s*[-\u2013]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    )
    date_hits = sum(len(re.findall(pattern, clean, flags=re.IGNORECASE)) for pattern in date_patterns)
    time_hits = sum(len(re.findall(pattern, clean, flags=re.IGNORECASE)) for pattern in time_patterns)
    slot_hints = len(re.findall(r"\b(?:slot|option|available|availability)\b", clean, flags=re.IGNORECASE))
    bullet_slots = len(re.findall(r"(?:^|\n)\s*(?:[-*\u2022]|\d+[.)]|slot\s*\d+)", clean, flags=re.IGNORECASE))
    slot_count = max(date_hits, bullet_slots)
    return {
        "date_hits": date_hits,
        "time_hits": time_hits,
        "slot_hints": slot_hints,
        "slot_count": slot_count,
    }


def _dated_interview_slot_count(text: Any) -> int:
    """Count unique, fully dated options using the same parser used at handoff."""
    clean = _strip_quoted_email_history(text)
    if not clean:
        return 0
    return len(_slot_options_from_text(clean))


def _has_proper_interview_slots(text: Any) -> bool:
    return _dated_interview_slot_count(text) == 3


def _slot_reply_intent(text: Any) -> str:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return "unknown"
    if re.search(r"\b(?:not available|unavailable|not possible|cannot|can't|cant|decline|no thanks)\b", lower, flags=re.IGNORECASE):
        return "rejected"
    if _has_proper_interview_slots(lower):
        return "valid_slots"
    slot_count = _dated_interview_slot_count(lower)
    if slot_count > 3:
        return "too_many_slots"
    metrics = _slot_reply_metrics(lower)
    if slot_count > 0 or metrics["slot_hints"] > 0 or metrics["date_hits"] > 0 or metrics["time_hits"] > 0:
        return "unclear_slots"
    return "unknown"


def _extract_slot_lines(text: Any) -> str:
    reply_text = _strip_quoted_email_history(text)
    lines = [line.strip() for line in reply_text.splitlines() if line.strip()]
    slot_lines: List[str] = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if re.search(
            r"(\bslot\s*\d+\b|(?:^|[\s*.-])\d+[.)]\s*|\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|\b\d{1,2}[:.]\d{2}\s*(?:am|pm)\b)",
            normalized,
            flags=re.IGNORECASE,
        ):
            slot_lines.append(normalized)
    return "\n".join(slot_lines) if slot_lines else reply_text


def _client_slots_message(
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    trainer: Dict[str, Any],
    slot_text: str,
) -> Dict[str, str]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "training"
    )
    client_name = _client_name_from_context(requirement, shortlist)
    is_reschedule = bool(trainer.get("reschedule_requested"))
    trainer_details = _requested_trainer_details_for_client(requirement, trainer)
    trainer_details_section = (
        f"Trainer details shared for your review:\n{trainer_details}\n\n"
        if trainer_details and not is_reschedule
        else ""
    )
    subject = f"{'Revised ' if is_reschedule else ''}Interview Slots - {technology}"
    opening = (
        f"The trainer has shared three revised interview slots for the {technology} requirement.\n\n"
        if is_reschedule
        else f"We have received the requested trainer details for the shortlisted {technology} trainer.\n\n"
    )
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"{opening}"
        f"{trainer_details_section}"
        "Available slots:\n"
        f"{slot_text}\n\n"
        "Kindly confirm one preferred slot. We will then send the Google Meet invitation to both you and the trainer.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _client_interview_schedule_message(
    *,
    client_name: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    interview_date: str,
    meeting_link: str,
) -> Dict[str, str]:
    subject = f"Interview Schedule Confirmation - {technology} | Ref: {requirement_id}"
    date_line = f"Date & Time: {interview_date}\n" if interview_date else ""
    link = _clean(meeting_link)
    body = (
        f"Dear {client_name or 'Team'},\n\n"
        f"The interview/discussion for the shortlisted {technology} trainer is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        "Platform: Google Meet\n"
        f"Meeting Link: {link}\n\n"
        "Kindly join on time and let us know if any change is required.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _trainer_interview_schedule_message(
    *,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    interview_date: str,
    meeting_link: str,
) -> Dict[str, str]:
    subject = f"Interview Schedule Confirmation - {technology} | Ref: {requirement_id}"
    date_line = f"Date & Time: {interview_date}\n" if interview_date else ""
    body = (
        f"Dear {trainer_name or 'Trainer'},\n\n"
        f"The interview/discussion for the {technology} requirement is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        "Platform: Google Meet\n"
        f"Meeting Link: {_clean(meeting_link)}\n\n"
        "Please join on time and reply if a change is required.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {"subject": subject, "body": body}


def _toc_request_messages(
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    trainer: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or trainer.get("domain")
        or "training"
    )
    requirement_id = _clean(requirement.get("requirement_id") or shortlist.get("requirement_id"))
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_name = _client_name_from_context(requirement, shortlist)
    ref = f" | Ref: {requirement_id}" if requirement_id else ""
    trainer_body = (
        f"Dear {trainer_name},\n\n"
        f"Thank you for confirming your interest in the {technology} requirement.\n\n"
        "Before we proceed with interview slot booking, please share the Table of Contents (ToC) / Course Agenda for the proposed training delivery.\n\n"
        "This will help us align the discussion with the client requirement.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    client_body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"We are proceeding with Trainer {trainer_name} for the {technology} requirement. Before slot booking, "
        "we have requested the trainer to share the Table of Contents (ToC) / Course Agenda.\n\n"
        "We will share the ToC once received and then proceed with interview slot coordination.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    return {
        "trainer": {
            "subject": f"ToC / Course Agenda Request - {technology}{ref}",
            "body": trainer_body,
        },
        "client": {
            "subject": f"ToC / Course Agenda Requested - {technology}{ref}",
            "body": client_body,
        },
    }


async def _send_toc_request_before_slot_if_missing(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    trainer_id: str,
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    source_email_id: str = "",
    source_gmail_message_id: str = "",
) -> Dict[str, Any]:
    existing_trainer = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": {"$in": ["mail6", "mail6_toc", "toc-request"]},
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0, "email_id": 1, "sent_at": 1, "to_email": 1, "recipient": 1},
        sort=[("created_at", -1)],
    )
    existing_client = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "client_toc_details_request",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0, "email_id": 1, "sent_at": 1, "to_email": 1, "recipient": 1},
        sort=[("created_at", -1)],
    )
    if existing_trainer and existing_client:
        sent_at = existing_trainer.get("sent_at") or _now()
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "toc_requested",
                "top_trainers.$.toc_status": "requested",
                "top_trainers.$.toc_email_id": existing_trainer.get("email_id") or "",
                "top_trainers.$.client_toc_email_id": existing_client.get("email_id") or "",
                "top_trainers.$.last_mail_type": "mail6_toc",
                "top_trainers.$.last_mail_type_attempted": "mail6_toc",
                "top_trainers.$.last_mailed_at": sent_at,
                "top_trainers.$.last_mail_error": "",
                "top_trainers.$.updated_at": _now(),
                "updated_at": _now(),
            }},
        )
        return {
            "success": True,
            "already_sent": True,
            "trainer_email_id": existing_trainer.get("email_id"),
            "client_email_id": existing_client.get("email_id"),
            "reason": "toc_already_requested_before_slot",
        }

    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email"))
    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not trainer_email:
        return {"success": False, "reason": "missing_trainer_email", "error": "Trainer email missing"}
    if not client_email:
        return {"success": False, "reason": "missing_client_email", "error": "Client email missing"}

    messages = _toc_request_messages(requirement, shortlist, trainer)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    now = _now()

    async def _send_and_log(to_email: str, message: Dict[str, str], mail_type: str) -> Dict[str, Any]:
        message_id_header = generate_message_id()
        success, error = await send_email_async(
            to=to_email,
            subject=message["subject"],
            body=message["body"],
            smtp_config=smtp_config,
            message_id_header=message_id_header,
        )
        email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
        await db["email_logs"].insert_one({
            "email_id": email_id,
            "direction": "outbound",
            "recipient": to_email,
            "to_email": to_email,
            "subject": message["subject"],
            "gmail_message_id": message_id_header,
            "message_id_header": message_id_header,
            "body": message["body"],
            "body_snippet": message["body"][:300],
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "mail_type": mail_type,
            "source_email_id": source_email_id,
            "source_gmail_message_id": source_gmail_message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer.get("name") or trainer.get("trainer_name") or "",
            "client_email": client_email,
            "client_name": requirement.get("client_name") or shortlist.get("client_name") or "",
            "sent_at": now if success else None,
            "created_at": now,
            "updated_at": now,
        })
        return {"success": bool(success), "error": error or "", "email_id": email_id, "to": to_email}

    trainer_result = existing_trainer or await _send_and_log(trainer_email, messages["trainer"], "mail6_toc")
    client_result = existing_client or await _send_and_log(client_email, messages["client"], "client_toc_details_request")
    overall_success = bool(trainer_result.get("success", True) and client_result.get("success", True))
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "toc_requested" if overall_success else "toc_request_failed",
            "top_trainers.$.toc_status": "requested" if overall_success else "request_failed",
            "top_trainers.$.toc_email_id": trainer_result.get("email_id") or "",
            "top_trainers.$.client_toc_email_id": client_result.get("email_id") or "",
            "top_trainers.$.toc_requested_at": now if overall_success else None,
            "top_trainers.$.last_mail_type": "mail6_toc" if overall_success else trainer.get("last_mail_type", ""),
            "top_trainers.$.last_mail_type_attempted": "mail6_toc",
            "top_trainers.$.last_mailed_at": now if overall_success else trainer.get("last_mailed_at"),
            "top_trainers.$.last_mail_error": "" if overall_success else (trainer_result.get("error") or client_result.get("error") or "ToC request send failed"),
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    return {
        "success": overall_success,
        "reason": "toc_requested_before_slot" if overall_success else "toc_request_failed",
        "trainer_email_id": trainer_result.get("email_id"),
        "client_email_id": client_result.get("email_id"),
        "trainer": trainer_result,
        "client": client_result,
    }


def _client_requested_toc_or_proposal(requirement: Dict[str, Any], shortlist: Dict[str, Any]) -> bool:
    sources = [requirement, shortlist, requirement.get("extracted") or {}, shortlist.get("extracted") or {}]
    requested: List[str] = []
    for source in sources:
        values = source.get("requested_details") or []
        if isinstance(values, str):
            requested.append(values)
        else:
            requested.extend(str(item) for item in values)
        for key in ("raw_body", "body", "clean_body", "email_summary", "notes", "client_notes"):
            if source.get(key):
                requested.append(str(source.get(key)))
    text = " ".join(requested).lower()
    return bool(re.search(r"\b(?:toc|table\s+of\s+contents?|course\s+agenda|training\s+agenda|day[-\s]?wise\s+content|curriculum|syllabus|methodology)\b", text))


async def _send_next_step_after_commercial_approval(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    trainer_id: str,
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    source_email_id: str = "",
    source_gmail_message_id: str = "",
) -> Dict[str, Any]:
    # Mail 1 already contains the trainer's ToC and asks for exactly three
    # dated slots. Commercial processing must never reactivate the retired
    # ToC/Mail 3 chain and create a second trainer email.
    return {
        "success": True,
        "skipped": True,
        "reason": "slots_and_toc_already_in_mail1",
    }

    if _client_requested_toc_or_proposal(requirement, shortlist):
        return await _send_toc_request_before_slot_if_missing(
            db,
            requirement_id,
            trainer_id,
            trainer,
            requirement,
            shortlist,
            source_email_id=source_email_id,
            source_gmail_message_id=source_gmail_message_id,
        )
    return await _send_trainer_mail3_if_missing(
        db,
        requirement_id,
        trainer_id,
        trainer,
        requirement,
        shortlist,
        source_email_id=source_email_id,
        source_gmail_message_id=source_gmail_message_id,
    )


async def _send_client_toc_received_email(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    trainer: Dict[str, Any],
    toc_text: str,
) -> Dict[str, Any]:
    requirement_id = email_doc.get("requirement_id") or requirement.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or trainer.get("trainer_id") or ""
    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email"))
    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not client_email:
        return {"success": False, "reason": "missing_client_email", "error": "Client email missing"}
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "training"
    )
    client_name = _client_name_from_context(requirement, shortlist)
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name") or email_doc.get("trainer_name")) or "Trainer"
    subject = f"Trainer ToC / Course Agenda - {technology}"
    body = (
        f"{_client_time_greeting(client_name)},\n\n"
        f"The shortlisted trainer has shared the ToC / Course Agenda for the {technology} requirement.\n\n"
        "ToC / Course Agenda:\n"
        f"{toc_text}\n\n"
        "We will now proceed with interview slot booking.\n\n"
        "Regards,\n"
        "Clahan Technologies"
    )
    settings_doc = await _load_admin_settings(db)
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=client_email,
        subject=subject,
        body=body,
        smtp_config=settings_doc.get("emailCfg") or None,
        message_id_header=message_id_header,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": subject,
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": body,
        "body_snippet": body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "client_toc_received",
        "source_email_id": email_doc.get("email_id") or "",
        "source_gmail_message_id": _current_inbound_message_id(email_doc),
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "client_email": client_email,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    return {"success": bool(success), "error": error or "", "email_id": email_id, "to": client_email, "subject": subject}


async def _client_pipeline_email_body(
    db: AsyncIOMotorDatabase,
    *,
    requirement: Dict[str, Any],
    workflow: str,
    subject: str,
    reference_body: str,
    context: Dict[str, Any],
) -> Tuple[str, str]:
    """Use global AI wording mode while keeping workflow facts authoritative."""
    setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    if _clean(setting.get("value")).lower() != "ai":
        return reference_body, "template"
    try:
        from app.routes.inbox_actions import _ai_draft_reply

        generated = await _ai_draft_reply(
            subject=subject,
            body=reference_body,
            hint=(
                "Write this client-facing pipeline email naturally. Preserve every verified fact from the "
                "reference exactly, especially meeting links, dates, times, attachments and the requested "
                "next action. Do not invent trainer availability, commercial values, documents, decisions, "
                "or completion status. Keep the Clahan Technologies sign-off."
            ),
            workflow_context={
                **context,
                "workflow": workflow,
                "requirement_id": requirement.get("requirement_id"),
                "technology": requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain"),
            },
            reference_reply={"body": reference_body},
            require_openai=True,
        )
        is_logistics_workflow = (
            workflow.startswith("trainer_logistics_")
            or workflow == "client_logistics_clarification"
        )
        if _clean(generated) and (
            not is_logistics_workflow
            or _logistics_ai_output_is_grounded(generated, reference_body)
        ):
            return generated.strip(), "ai"
        if _clean(generated):
            logger.warning("Rejected ungrounded AI logistics wording for %s", requirement.get("requirement_id"))
    except Exception:
        logger.exception("AI client pipeline wording failed for %s", requirement.get("requirement_id"))
    return reference_body, "template_fallback"


async def _send_client_interview_schedule_email(
    db: AsyncIOMotorDatabase,
    *,
    client_email: str,
    client_name: str,
    trainer_name: str,
    technology: str,
    requirement_id: str,
    trainer_id: str,
    meeting_link: str,
    interview_date: str,
    smtp_config: Optional[Dict[str, Any]] = None,
    interview_start: Optional[datetime] = None,
    interview_end: Optional[datetime] = None,
    calendar_event: Optional[Dict[str, Any]] = None,
    source_email_id: str = "",
    source_gmail_message_id: str = "",
    source_trainer_email_id: str = "",
    slot_text: str = "",
    timezone_name: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    sent_at = now or _now()
    if not _clean(meeting_link):
        error = "Meeting link missing; client interview schedule mail was not sent."
        await db["email_logs"].insert_one({
            "email_id": f"CAL-{uuid.uuid4().hex[:10].upper()}",
            "direction": "internal",
            "subject": f"Client Interview Schedule Blocked - {technology} | {requirement_id}",
            "body": (
                "Client interview schedule mail was blocked because the meeting link is missing.\n\n"
                f"Requirement: {requirement_id}\n"
                f"Trainer: {trainer_name}\n"
                f"Client Email: {client_email}\n"
                f"Interview Date: {interview_date}\n"
                f"Slot Text: {slot_text}"
            ),
            "body_snippet": error,
            "status": "needs_manual_review",
            "error_message": error,
            "mail_type": "calendar_failure_report",
            "source_email_id": source_email_id,
            "source_gmail_message_id": source_gmail_message_id,
            "source_trainer_email_id": source_trainer_email_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "client_email": client_email,
            "interview_date": interview_date,
            "slot_text": slot_text,
            "created_at": sent_at,
            "updated_at": sent_at,
        })
        return {"success": False, "reason": "missing_meeting_link_no_mail_sent", "error": error, "email_id": "", "to": client_email}
    # Claim the delivery before SMTP. Inbox polling and manual sync may reach
    # one client reply concurrently; only one process may send this email.
    send_claim = await db["shortlists"].update_one(
        {
            "requirement_id": requirement_id,
            "top_trainers": {"$elemMatch": {
                "trainer_id": trainer_id,
                "client_schedule_sending": {"$ne": True},
                # A replacement Meet link is a new client delivery even
                # though the old interview invitation was already sent.
                "$or": [
                    {"client_email_sent": {"$ne": True}},
                    {"meet_link": {"$ne": meeting_link}},
                    {"interview_link": {"$ne": meeting_link}},
                ],
            }},
        },
        {"$set": {"top_trainers.$.client_schedule_sending": True, "top_trainers.$.updated_at": sent_at, "updated_at": sent_at}},
    )
    if not send_claim.modified_count:
        existing_delivery = await db["email_logs"].find_one(
            {
                "direction": "outbound", "status": "sent", "mail_type": "client_interview_schedule",
                "requirement_id": requirement_id, "trainer_id": trainer_id, "interview_link": meeting_link,
            },
            {"_id": 0, "email_id": 1, "to_email": 1, "recipient": 1, "subject": 1, "sent_at": 1},
            sort=[("created_at", -1)],
        )
        if existing_delivery:
            return {"success": True, "already_sent": True, "email_id": existing_delivery.get("email_id") or "", "to": existing_delivery.get("to_email") or existing_delivery.get("recipient") or client_email, "subject": existing_delivery.get("subject") or "", "sent_at": existing_delivery.get("sent_at")}
        return {"success": True, "send_in_progress": True, "email_id": "", "to": client_email}

    message = _client_interview_schedule_message(
        client_name=client_name,
        trainer_name=trainer_name,
        technology=technology,
        requirement_id=requirement_id,
        interview_date=interview_date,
        meeting_link=meeting_link,
    )
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    message_body, generation_source = await _client_pipeline_email_body(
        db,
        requirement=requirement,
        workflow="client_interview_confirmation",
        subject=message["subject"],
        reference_body=message["body"],
        context={
            "client_name": client_name,
            "trainer_name": trainer_name,
            "meeting_link": meeting_link,
            "interview_date": interview_date,
            "calendar_invite_attached": bool(calendar_event),
        },
    )
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=client_email,
        subject=message["subject"],
        body=message_body,
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    event = calendar_event or {}
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message_body,
        "body_snippet": message_body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "client_interview_schedule",
        "generation_source": generation_source,
        "source_email_id": source_email_id,
        "source_gmail_message_id": source_gmail_message_id,
        "source_trainer_email_id": source_trainer_email_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "client_email": client_email,
        "client_name": client_name,
        "slot_text": slot_text,
        "interview_date": interview_date,
        "date_time_text": interview_date,
        "interview_at": interview_start,
        "interview_end_at": interview_end,
        "interview_link": meeting_link,
        "meet_link": meeting_link,
        "calendar_event": event,
        "calendar_event_id": event.get("event_id") or "",
        "calendar_html_link": event.get("html_link") or "",
        "timezone": timezone_name,
        "interview_scheduled": bool(success),
        "client_email_sent": bool(success),
        "trainer_email_sent": False,
        "sent_at": sent_at if success else None,
        "created_at": sent_at,
        "updated_at": sent_at,
    })
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {"top_trainers.$.client_schedule_sending": False, "top_trainers.$.updated_at": _now(), "updated_at": _now()}},
    )
    return {
        "success": success,
        "error": error or "",
        "email_id": email_id,
        "to": client_email,
        "subject": message["subject"],
        "sent_at": sent_at if success else None,
    }


async def _latest_mail3_log(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    requirement_id: str,
    trainer_id: str,
) -> Optional[Dict[str, Any]]:
    source_email_id = email_doc.get("source_outbound_email_id")
    if source_email_id:
        source_log = await db["email_logs"].find_one(
            {"email_id": source_email_id, "mail_type": {"$in": ["mail2", "mail3", "mail3_slot_followup", "mail3_too_many_slots"]}},
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if source_log:
            return source_log

    if not requirement_id or not trainer_id:
        return None
    return await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": {"$in": ["mail2", "mail3", "mail3_slot_followup", "mail3_too_many_slots"]},
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _latest_client_commercial_log(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    requirement_id: str,
    trainer_id: str,
) -> Optional[Dict[str, Any]]:
    source_email_id = email_doc.get("source_outbound_email_id")
    if source_email_id:
        source_log = await db["email_logs"].find_one(
            {"email_id": source_email_id, "mail_type": "trainer_commercials_to_client"},
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if source_log:
            return source_log

    if not requirement_id or not trainer_id:
        return None
    return await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "trainer_commercials_to_client",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _latest_commercial_negotiation_log(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    requirement_id: str,
    trainer_id: str,
) -> Optional[Dict[str, Any]]:
    source_email_id = email_doc.get("source_outbound_email_id")
    if source_email_id:
        source_log = await db["email_logs"].find_one(
            {
                "email_id": source_email_id,
                "mail_type": {"$in": ["commercial_negotiation", "trainer_rate_discussion"]},
            },
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if source_log:
            return source_log

    if not requirement_id or not trainer_id:
        return None
    return await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": {"$in": ["commercial_negotiation", "trainer_rate_discussion"]},
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _handle_trainer_commercial_negotiation_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    is_negotiation_thread = (
        source_mail_type in {"commercial_negotiation", "trainer_rate_discussion"}
        or bool(re.search(r"(Commercial Discussion|Rate Discussion)", subject, flags=re.IGNORECASE))
    )
    if not is_negotiation_thread:
        return {"attempted": False, "reason": "not_commercial_negotiation_thread"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": False, "reason": "missing_requirement_or_trainer_link"}

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer"}

    source_log = await _latest_commercial_negotiation_log(db, email_doc, requirement_id, trainer_id)
    target_amount = _safe_int(
        (source_log or {}).get("trainer_target_rate")
        or trainer.get("trainer_target_rate")
        or trainer.get("target_rate")
        or 0
    )
    reply_text = email_doc.get("classification_body") or email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or ""
    intent = _commercial_negotiation_reply_intent(reply_text, target_amount)
    now = _now()

    if intent == "rejected":
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "rejected",
                "top_trainers.$.commercial_status": "rejected_by_trainer",
                "top_trainers.$.commercial_rejected_at": now,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": True, "reason": "trainer_rejected_commercial", "intent": intent}

    if intent != "accepted":
        status = "counter_offer_from_trainer" if intent == "counter_offer" else "needs_manual_review"
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.commercial_status": status,
                "top_trainers.$.commercial_reply_review_at": now,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": False, "reason": status, "intent": intent}

    # Commercial negotiation is not a trigger for a second slot request.
    # Current Mail 1 already asks for exactly three slots; keep the accepted
    # status recorded and wait for the Mail 1/Mail 2 slot reply.
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "details_received",
            "top_trainers.$.commercial_status": "accepted_by_trainer",
            "top_trainers.$.commercial_accepted_at": now,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    return {
        "attempted": True,
        "success": True,
        "skipped": True,
        "reason": "commercial_accepted_slots_already_requested_in_mail1",
        "intent": intent,
    }

    source_email_id = email_doc.get("email_id")
    source_negotiation_email_id = (source_log or {}).get("email_id") or email_doc.get("source_outbound_email_id") or ""
    source_gmail_message_id = _current_inbound_message_id(email_doc)
    existing_filters: List[Dict[str, Any]] = []
    if source_email_id:
        existing_filters.append({"source_email_id": source_email_id})
    if source_negotiation_email_id:
        existing_filters.append({"source_commercial_negotiation_email_id": source_negotiation_email_id})
    if source_gmail_message_id:
        existing_filters.append({"source_gmail_message_id": source_gmail_message_id})
    if target_amount:
        existing_filters.append({"trainer_target_rate": target_amount})
    existing_query: Dict[str, Any] = {
        "direction": "outbound",
        "status": "sent",
        "mail_type": "mail3",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "$or": existing_filters or [{"source_email_id": source_email_id or ""}],
    }
    existing = await db["email_logs"].find_one(
        existing_query,
        {"_id": 0, "email_id": 1, "sent_at": 1, "recipient": 1, "to_email": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        sent_at = existing.get("sent_at") or now
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.last_mail_type": "mail3",
                "top_trainers.$.last_mail_type_attempted": "mail3",
                "top_trainers.$.last_mail_attempted_at": sent_at,
                "top_trainers.$.last_mailed_at": sent_at,
                "top_trainers.$.last_mail_error": "",
                "top_trainers.$.commercial_status": "accepted_by_trainer",
                "top_trainers.$.commercial_accepted_at": sent_at,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to": existing.get("to_email") or existing.get("recipient"),
            "intent": intent,
        }

    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email"))
    if not trainer_email:
        return {"attempted": True, "success": False, "reason": "missing_trainer_email", "error": "Trainer email missing", "intent": intent}

    message = _trainer_slot_booking_message(trainer, requirement, shortlist)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "mail3",
        "source_email_id": source_email_id,
        "source_gmail_message_id": source_gmail_message_id,
        "source_commercial_negotiation_email_id": source_negotiation_email_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
        "client_email": requirement.get("client_email") or "",
        "client_name": requirement.get("client_name") or requirement.get("client_company") or "",
        "trainer_target_rate": target_amount,
        "commercial_unit": (source_log or {}).get("commercial_unit") or trainer.get("commercial_unit") or "day",
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })

    set_fields = {
        "top_trainers.$.pipeline_status": "slot_booked" if success else "waiting_reply2",
        "top_trainers.$.last_mail_type_attempted": "mail3",
        "top_trainers.$.last_mail_attempted_at": now,
        "top_trainers.$.commercial_status": "accepted_by_trainer" if success else "slot_booking_send_failed",
        "top_trainers.$.commercial_accepted_at": now,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if success:
        set_fields.update({
            "top_trainers.$.last_mail_type": "mail3",
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
        })
    else:
        set_fields["top_trainers.$.last_mail_error"] = error or "Slot booking email failed"

    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": set_fields},
    )

    return {
        "attempted": True,
        "success": success,
        "error": error or "",
        "email_id": email_id,
        "to": trainer_email,
        "subject": message["subject"],
        "intent": intent,
        "trainer_target_rate": target_amount,
    }


async def _send_trainer_mail3_if_missing(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    trainer_id: str,
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Dict[str, Any],
    source_email_id: str = "",
    source_gmail_message_id: str = "",
) -> Dict[str, Any]:
    # Slots belong in Mail 1.  The legacy Mail 3 stage is retired and must
    # never send a second standalone trainer slot request.  A partial Mail 1
    # reply is handled by the single Mail 2 missing-details follow-up instead.
    return {
        "success": False,
        "skipped": True,
        "reason": "mail3_slot_request_retired",
        "error": "Slots are requested in Mail 1; use the one permitted Mail 2 follow-up only for missing slots.",
    }

    existing = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "mail3",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0, "email_id": 1, "sent_at": 1, "recipient": 1, "to_email": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        sent_at = existing.get("sent_at") or _now()
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.last_mail_type": "mail3",
                "top_trainers.$.last_mail_type_attempted": "mail3",
                "top_trainers.$.last_mail_attempted_at": sent_at,
                "top_trainers.$.last_mailed_at": sent_at,
                "top_trainers.$.last_mail_error": "",
                "top_trainers.$.updated_at": _now(),
                "updated_at": _now(),
            }},
        )
        return {
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to": existing.get("to_email") or existing.get("recipient"),
        }

    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email"))
    if not trainer_email:
        return {"success": False, "reason": "missing_trainer_email", "error": "Trainer email missing"}

    # Make mail3 idempotent when two inbox workers process the same reply together.
    lock_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mail3|{requirement_id}|{trainer_id}|{trainer_email.lower()}"))
    try:
        await db["email_send_locks"].insert_one({
            "_id": lock_id,
            "mail_type": "mail3",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "created_at": _now(),
        })
    except DuplicateKeyError:
        return {"success": True, "already_sent": True, "already_sending": True, "to": trainer_email}

    message = _trainer_slot_booking_message(trainer, requirement, shortlist)
    settings_doc = await _load_admin_settings(db)
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=settings_doc.get("emailCfg") or None,
        message_id_header=message_id_header,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "mail3",
        "source_email_id": source_email_id,
        "source_gmail_message_id": source_gmail_message_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer.get("name") or trainer.get("trainer_name") or "",
        "client_email": requirement.get("client_email") or shortlist.get("client_email") or "",
        "client_name": requirement.get("client_name") or requirement.get("client_company") or shortlist.get("client_name") or "",
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    set_fields = {
        "top_trainers.$.pipeline_status": "slot_booked" if success else "details_received",
        "top_trainers.$.last_mail_type_attempted": "mail3",
        "top_trainers.$.last_mail_attempted_at": now,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if success:
        set_fields.update({
            "top_trainers.$.last_mail_type": "mail3",
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
        })
    else:
        set_fields["top_trainers.$.last_mail_error"] = error or "Mail 3 slot booking send failed"
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": set_fields},
    )
    return {
        "success": bool(success),
        "error": error or "",
        "email_id": email_id,
        "to": trainer_email,
        "subject": message["subject"],
    }


async def _handle_trainer_slot_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    reply_text_preview = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    probable_slot_reply = _slot_reply_intent(reply_text_preview) in {"valid_slots", "unclear_slots", "too_many_slots"}
    is_slot_thread = (
        source_mail_type in {"mail3", "mail3_slot_followup", "mail3_too_many_slots", "mail4_reschedule_request"}
        or bool(re.search(r"(Interview Slot Booking|Slot Booking|Interview Availability|Trainer Availability Slots)", subject, flags=re.IGNORECASE))
        or probable_slot_reply
    )
    if not is_slot_thread:
        return {"attempted": False, "reason": "not_slot_reply_thread"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    inferred_shortlist: Dict[str, Any] = {}
    inferred_trainer: Dict[str, Any] = {}
    if not requirement_id or not trainer_id:
        inferred_requirement_id, inferred_trainer_id, inferred_shortlist, inferred_trainer = await _find_active_slot_context_by_trainer_email(
            db,
            email_doc.get("from_email") or email_doc.get("sender") or "",
        )
        requirement_id = requirement_id or inferred_requirement_id
        trainer_id = trainer_id or inferred_trainer_id
    if not requirement_id or not trainer_id:
        return {"attempted": False, "reason": "missing_requirement_or_trainer_link"}

    shortlist = inferred_shortlist or await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = inferred_trainer or _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer"}

    is_reschedule_slot_reply = bool(
        source_mail_type == "mail4_reschedule_request"
        and trainer.get("reschedule_requested")
    )
    # A later/repeated trainer availability email must never move a completed
    # interview back to "Slot Booked".  The client handoff and calendar invite
    # are already complete when both delivery flags and the Meet link exist.
    existing_meet_link = _clean(trainer.get("meet_link") or trainer.get("interview_link"))
    if (
        trainer.get("interview_scheduled_at")
        and existing_meet_link
        and trainer.get("client_email_sent")
        and trainer.get("trainer_email_sent")
        and not is_reschedule_slot_reply
    ):
        return {
            "attempted": True,
            "success": True,
            "already_scheduled": True,
            "reason": "interview_already_scheduled",
            "interview_link": existing_meet_link,
        }

    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email"))
    reply_text = reply_text_preview
    intent = _slot_reply_intent(reply_text)
    # A trainer may say that the original date is unavailable and immediately
    # provide three replacements.  Those usable replacements take precedence
    # over the unavailable wording.
    if is_reschedule_slot_reply and _has_proper_interview_slots(reply_text):
        intent = "valid_slots"
    now = _now()
    source_log = await _latest_mail3_log(db, email_doc, requirement_id, trainer_id)
    source_time = (source_log or {}).get("sent_at") or (source_log or {}).get("created_at")

    if intent == "rejected":
        if is_reschedule_slot_reply:
            client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
            client_name = _client_name_from_context(requirement, shortlist)
            technology = _clean(
                requirement.get("technology_needed")
                or requirement.get("technology")
                or requirement.get("domain")
                or shortlist.get("technology_needed")
                or "training"
            )
            requested_date = _clean(trainer.get("reschedule_requested_date"))
            if not client_email:
                await db["shortlists"].update_one(
                    {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
                    {"$set": {
                        "top_trainers.$.pipeline_status": "interview_reschedule_requested",
                        "top_trainers.$.slot_status": "reschedule_needs_client_date",
                        "top_trainers.$.reschedule_trainer_reply": reply_text,
                        "top_trainers.$.last_mail_error": "Client email missing for reschedule date request.",
                        "top_trainers.$.updated_at": now,
                        "updated_at": now,
                    }},
                )
                return {
                    "attempted": True,
                    "success": False,
                    "reason": "missing_client_email_for_reschedule",
                    "intent": intent,
                    "error": "Client email missing for reschedule date request.",
                }
            subject_line = f"Alternate Interview Date Required - {technology}"
            unavailable_date = f" for {requested_date}" if requested_date else ""
            reference_body = (
                f"{_client_time_greeting(client_name)},\n\n"
                f"The trainer is not available{unavailable_date}.\n\n"
                "Please share your preferred alternate interview date, including the time zone. "
                "Once you confirm the date, we will ask the trainer for exactly three convenient slots on that date.\n\n"
                "Regards,\nClahan Technologies"
            )
            body, generation_source = await _reschedule_mail_body(
                db=db,
                requirement=requirement,
                recipient_kind="client",
                subject=subject_line,
                inbound_text=reply_text,
                reference_body=reference_body,
                requested_date=requested_date,
            )
            settings_doc = await _load_admin_settings(db)
            message_id_header = generate_message_id()
            success, error = await send_email_async(
                to=client_email,
                subject=subject_line,
                body=body,
                smtp_config=settings_doc.get("emailCfg") or None,
                message_id_header=message_id_header,
            )
            email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
            await db["email_logs"].insert_one({
                "email_id": email_id,
                "direction": "outbound",
                "recipient": client_email,
                "to_email": client_email,
                "subject": subject_line,
                "gmail_message_id": message_id_header,
                "message_id_header": message_id_header,
                "body": body,
                "body_snippet": body[:300],
                "status": "sent" if success else "failed",
                "error_message": error if not success else "",
                "mail_type": "client_interview_reschedule_date_request",
                "source_email_id": email_doc.get("email_id"),
                "source_gmail_message_id": _current_inbound_message_id(email_doc),
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "trainer_name": trainer.get("name") or trainer.get("trainer_name") or "Trainer",
                "client_email": client_email,
                "client_name": client_name,
                "reschedule_requested": True,
                "reschedule_requested_date": requested_date,
                "generation_source": generation_source,
                "sent_at": now if success else None,
                "created_at": now,
                "updated_at": now,
            })
            await db["shortlists"].update_one(
                {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
                {"$set": {
                    "top_trainers.$.pipeline_status": "interview_reschedule_requested",
                    "top_trainers.$.slot_status": "reschedule_waiting_client_date" if success else "reschedule_client_date_send_failed",
                    "top_trainers.$.reschedule_requested": True,
                    "top_trainers.$.reschedule_requested_by": "client",
                    "top_trainers.$.reschedule_trainer_reply": reply_text,
                    "top_trainers.$.reschedule_client_date_email_id": email_id if success else "",
                    "top_trainers.$.last_mail_type": "client_interview_reschedule_date_request",
                    "top_trainers.$.last_mail_error": "" if success else error,
                    "top_trainers.$.updated_at": now,
                    "updated_at": now,
                }},
            )
            return {
                "attempted": True,
                "success": bool(success),
                "reason": "trainer_unavailable_asked_client_for_alternate_date",
                "intent": intent,
                "email_id": email_id,
                "to": client_email,
                "error": error or "",
                "sent_at": now if success else None,
            }
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "rejected",
                "top_trainers.$.slot_status": "rejected_by_trainer",
                "top_trainers.$.slot_rejected_at": now,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": True, "reason": "trainer_rejected_slot", "intent": intent}

    if intent in {"too_many_slots", "unclear_slots", "unknown"}:
        # Mail 1 already asks for exactly three dated slots.  The only valid
        # follow-up is the one idempotent Mail 2 request for that missing
        # item.  The former Mail 3 wording asking for "2-3" slots is retired.
        followup_result = await _send_missing_trainer_details_followup(
            db,
            email_doc={
                **email_doc,
                "trainer_name": email_doc.get("trainer_name") or trainer.get("name") or trainer.get("trainer_name"),
                "classification_body": reply_text,
            },
            requirement=requirement,
            trainer_state=trainer,
            missing_details=["Exactly three interview/discussion slots (date, time, and time zone)"],
            now=now,
        )
        success = bool(followup_result.get("success") or followup_result.get("already_attempted"))
        return {
            "attempted": True,
            "success": success,
            "error": "" if success else _clean(followup_result.get("error") or followup_result.get("reason")),
            "email_id": followup_result.get("email_id") or "",
            "to": trainer_email,
            "intent": intent,
            "mail_type": "mail2_followup",
            "reason": "one_missing_slot_followup",
        }

    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not client_email:
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.slot_status": "missing_client_email",
                "top_trainers.$.client_slot_error": "Client email missing; trainer slots were not sent to client.",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": False, "reason": "missing_client_email", "intent": intent, "error": "Client email missing"}

    duplicate_terms = []
    if email_doc.get("email_id"):
        duplicate_terms.append({"source_email_id": email_doc.get("email_id")})
    source_gmail_message_id = _current_inbound_message_id(email_doc)
    if source_gmail_message_id:
        duplicate_terms.append({"source_gmail_message_id": source_gmail_message_id})
    duplicate_query = {
        "direction": "outbound",
        "status": "sent",
        "mail_type": "client_slots",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
    }
    if duplicate_terms:
        duplicate_query["$or"] = duplicate_terms
    elif source_time:
        duplicate_query["created_at"] = {"$gte": source_time}
    existing = await db["email_logs"].find_one(
        duplicate_query,
        {"_id": 0, "email_id": 1, "to_email": 1, "recipient": 1, "sent_at": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        sent_at = existing.get("sent_at") or now
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "sent_to_client",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.client_slots_sent": True,
                "top_trainers.$.client_slots_sent_at": sent_at,
                "top_trainers.$.client_slots_email_id": existing.get("email_id"),
                "top_trainers.$.client_slot_error": "",
                "top_trainers.$.client_handoff_error_detail": "",
                "top_trainers.$.client_handoff_retry_after": None,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to": existing.get("to_email") or existing.get("recipient"),
            "intent": intent,
        }

    pending_retry_after = trainer.get("client_handoff_retry_after")
    if isinstance(pending_retry_after, str):
        pending_retry_after = _parse_retry_after(f"Retry after {pending_retry_after}")
    if isinstance(pending_retry_after, datetime) and pending_retry_after > now:
        return {
            "attempted": True,
            "success": False,
            "retry_pending": True,
            "reason": "client_handoff_retry_pending",
            "retry_after": pending_retry_after,
            "intent": intent,
            "error": "Client handoff is queued for automatic retry.",
        }

    slot_text = _extract_slot_lines(reply_text)
    if not _has_proper_interview_slots(slot_text):
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "invalid_slot_text",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.client_slot_error": "Trainer reply did not include dated time slots; client slot mail was not sent.",
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": False,
            "reason": "invalid_slot_text",
            "error": "Trainer reply did not include dated time slots; client slot mail was not sent.",
        }
    # The trainer may include details and slots in one reply.  Initialise this
    # before the optional lookup so client handoff never fails when there is
    # no earlier, separate details-only reply.
    detail_reply_text = ""
    detail_reply_query = {
        "direction": {"$in": ["inbound", "received"]},
        "requirement_id": requirement_id,
        "source_outbound_mail_type": {"$nin": ["mail3", "mail3_slot_booking", "mail3_slot_followup", "mail3_too_many_slots"]},
        "mail_type": {"$nin": ["mail3", "mail3_slot_booking", "mail3_slot_followup", "mail3_too_many_slots"]},
        "$or": [
            {"trainer_id": trainer_id},
            {"from_email": {"$regex": f"^{re.escape(_email_address(trainer.get('email') or trainer.get('trainer_email')))}$", "$options": "i"}},
            {"sender": {"$regex": f"^{re.escape(_email_address(trainer.get('email') or trainer.get('trainer_email')))}$", "$options": "i"}},
        ],
    }
    if email_doc.get("created_at"):
        detail_reply_query["created_at"] = {"$lte": email_doc.get("created_at")}
    latest_detail_reply = await db["email_logs"].find_one(
        detail_reply_query,
        {"_id": 0, "body": 1, "body_snippet": 1, "reply_text": 1, "mail_type": 1, "created_at": 1, "sent_at": 1},
        sort=[("created_at", -1)],
    )
    if latest_detail_reply:
        detail_reply_text = _clean(latest_detail_reply.get("body") or latest_detail_reply.get("reply_text") or latest_detail_reply.get("body_snippet"))
        if detail_reply_text:
            trainer = {
                **trainer,
                "reply_text": trainer.get("reply_text") or detail_reply_text,
                "last_reply_snippet": trainer.get("last_reply_snippet") or detail_reply_text[:800],
                "details_reply_text": trainer.get("details_reply_text") or detail_reply_text,
            }
    message = _client_slots_message(requirement, shortlist, trainer, slot_text)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = ""
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    retry_after: Optional[datetime] = None
    technical_error = ""
    handoff_in_progress = False
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await _post_with_local_fallback(
                client,
                f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-client-slots",
                json={
                    "requirement_id": requirement_id,
                    "trainer_id": trainer_id,
                    "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
                    "client_email": client_email,
                    "client_name": _client_name_from_context(requirement, shortlist),
                    "slot_text": slot_text,
                    "trainer_details_text": detail_reply_text,
                    "smtp_config": smtp_config,
                },
            )
            response.raise_for_status()
            sent = response.json()
        # The client handoff is complete only after the downstream service
        # confirms an actual outbound email record.  A generic 200 response
        # must not turn the UI green when SMTP delivery did not occur.
        downstream_email_id = _clean(sent.get("email_id"))
        success = bool(sent.get("success")) and bool(downstream_email_id)
        error = "" if success else _clean(
            sent.get("error")
            or sent.get("error_message")
            or sent.get("message")
            or "Client handoff was not confirmed as delivered."
        )
        email_id = downstream_email_id or email_id
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            response_detail: Any = response.json()
        except Exception:
            response_detail = response.text
        if isinstance(response_detail, dict):
            response_detail = response_detail.get("detail") or response_detail.get("error") or response_detail
        technical_error = _clean(response_detail) or f"Trainer service returned HTTP {response.status_code}"
        handoff_in_progress = response.status_code == 409 and "progress" in technical_error.lower()
        retry_after = _client_handoff_retry_after(response_detail, now)
        success = False
        error = (
            "Another worker is completing the client handoff. Delivery status will update automatically."
            if handoff_in_progress
            else "Client handoff is temporarily delayed and will retry automatically."
        )
    except Exception as exc:
        technical_error = str(exc)
        retry_after = _client_handoff_retry_after(technical_error, now)
        success = False
        error = "Client handoff is temporarily delayed and will retry automatically."

    if not success:
        technical_error = technical_error or error
        retry_after = retry_after or _client_handoff_retry_after(technical_error, now)

    # The email-service has already atomically claimed the idempotency key.
    # A competing worker must not overwrite the successful worker's shortlist
    # state with a false failure while that claimed send is still running.
    if handoff_in_progress:
        return {
            "attempted": True,
            "success": False,
            "retry_pending": True,
            "reason": "client_handoff_in_progress",
            "retry_after": retry_after,
            "intent": intent,
            "error": error,
        }

    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "error_detail": technical_error if not success else "",
        "mail_type": "client_slots",
        "source_email_id": email_doc.get("email_id"),
        "source_gmail_message_id": source_gmail_message_id,
        "source_mail3_email_id": (source_log or {}).get("email_id") or "",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
        "client_email": client_email,
        "slot_text": slot_text,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    retry_pending = not success
    update_filter: Dict[str, Any] = {
        "requirement_id": requirement_id,
        "top_trainers.trainer_id": trainer_id,
    }
    if not success:
        # A concurrent successful sender wins.  Do not regress a delivered
        # handoff back to a retry state.
        update_filter["top_trainers"] = {
            "$elemMatch": {
                "trainer_id": trainer_id,
                "client_slots_sent": {"$ne": True},
            }
        }
    update_fields = {
        "top_trainers.$.pipeline_status": "slot_booked",
        "top_trainers.$.slot_status": "sent_to_client" if success else "client_handoff_retry_pending",
        "top_trainers.$.slot_reply_at": now,
        "top_trainers.$.slot_reply_text": slot_text,
        "top_trainers.$.client_slots_sent": bool(success),
        "top_trainers.$.client_slots_sent_at": now if success else None,
        "top_trainers.$.client_slots_email_id": email_id if success else "",
        "top_trainers.$.client_slot_error": "" if success else error,
        "top_trainers.$.client_handoff_error_detail": "" if success else technical_error,
        "top_trainers.$.client_handoff_retry_after": None if success else retry_after,
        "top_trainers.$.last_mail_error": "" if success else error,
        "top_trainers.$.reschedule_slots_sent_at": now if success and trainer.get("reschedule_requested") else trainer.get("reschedule_slots_sent_at"),
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    update_doc: Dict[str, Any] = {"$set": update_fields}
    if not success:
        update_doc["$inc"] = {"top_trainers.$.client_handoff_attempts": 1}
    await db["shortlists"].update_one(
        update_filter,
        update_doc,
    )
    return {
        "attempted": True,
        "success": success,
        "retry_pending": retry_pending,
        "retry_after": retry_after if retry_pending else None,
        "error": error or "",
        "error_detail": technical_error if not success else "",
        "email_id": email_id,
        "to": client_email,
        "intent": intent,
        "slot_text": slot_text,
    }


def _extract_slot_selection_text(text: Any) -> str:
    reply_text = _strip_quoted_email_history(text)
    lines = [line.strip() for line in reply_text.splitlines() if line.strip()]
    for line in lines:
        if re.search(r"\b(slot\s*\d+|\d{1,2}[:.]\d{2}|\b(?:am|pm)\b|date|on)\b", line, flags=re.IGNORECASE):
            return line
    return lines[0] if lines else reply_text


def _normalise_slot_text(text: Any) -> str:
    return (
        str(text or "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("â€“", "-")
        .replace("â€”", "-")
        .replace("\ufffd", "-")
        .replace("a.m.", "am")
        .replace("p.m.", "pm")
        .replace("a.m", "am")
        .replace("p.m", "pm")
        .replace("*", " ")
    )


_SLOT_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
    "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_SLOT_MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def _slot_date_value(day: Any, month: Any, year: Any) -> Optional[datetime]:
    try:
        parsed_year = int(year)
        if parsed_year < 100:
            parsed_year += 2000
        return datetime(parsed_year, int(month), int(day))
    except (TypeError, ValueError):
        return None


def _slot_date_matches(text: Any) -> List[Dict[str, Any]]:
    """Find explicit date values and their positions in ordinary email prose."""
    clean = _normalise_slot_text(text)
    matches: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int]] = set()

    def add(match: re.Match, day: Any, month: Any, year: Any) -> None:
        value = _slot_date_value(day, month, year)
        span = match.span()
        if value and span not in seen:
            matches.append({"start": span[0], "end": span[1], "value": value})
            seen.add(span)

    # ISO dates are common in calendar exports and should not be interpreted
    # using the Indian DD/MM order used for the other numeric format.
    for match in re.finditer(r"\b(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\b", clean):
        add(match, match.group(3), match.group(2), match.group(1))
    # Do not allow spaces inside this compact date pattern: otherwise a slot
    # label such as "Slot 1 - 08/09/2026" can be misread as 1-Aug-2009.
    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", clean):
        add(match, match.group(1), match.group(2), match.group(3))
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+({_SLOT_MONTH_PATTERN})\s*,?\s+(\d{{2,4}})\b",
        clean,
        flags=re.IGNORECASE,
    ):
        add(match, match.group(1), _SLOT_MONTHS.get(match.group(2).lower()), match.group(3))
    for match in re.finditer(
        rf"\b({_SLOT_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{2,4}})\b",
        clean,
        flags=re.IGNORECASE,
    ):
        add(match, match.group(2), _SLOT_MONTHS.get(match.group(1).lower()), match.group(3))
    return sorted(matches, key=lambda item: item["start"])


def _parse_slot_date(text: str) -> Optional[datetime]:
    matches = _slot_date_matches(text)
    return matches[0]["value"] if matches else None


def _time_to_24h(hour: int, minute: int, meridiem: str) -> tuple[int, int]:
    meridiem = (meridiem or "").lower().replace(".", "")
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute


def _slot_time_candidates(text: Any) -> List[Dict[str, Any]]:
    """Extract every time or time range without relying on email line breaks."""
    clean = _normalise_slot_text(text)
    candidates: List[Dict[str, Any]] = []
    occupied: List[Tuple[int, int]] = []
    meridiem = r"a\.?m\.?|p\.?m\.?"

    def add(
        match: re.Match,
        start_hour: Any,
        start_minute: Any,
        start_meridiem: Any,
        end_hour: Any = None,
        end_minute: Any = None,
        end_meridiem: Any = None,
    ) -> None:
        try:
            start_hour_value = int(start_hour)
            start_minute_value = int(start_minute or 0)
            end_hour_value = int(end_hour) if end_hour is not None else None
            end_minute_value = int(end_minute or 0) if end_hour is not None else None
        except (TypeError, ValueError):
            return
        if not 0 <= start_minute_value <= 59 or (end_minute_value is not None and not 0 <= end_minute_value <= 59):
            return
        start_meridiem_value = str(start_meridiem or "").lower().replace(".", "")
        end_meridiem_value = str(end_meridiem or "").lower().replace(".", "")
        if start_meridiem_value:
            if not 1 <= start_hour_value <= 12:
                return
        elif not 0 <= start_hour_value <= 23:
            return
        if end_hour_value is not None:
            if end_meridiem_value:
                if not 1 <= end_hour_value <= 12:
                    return
            elif not 0 <= end_hour_value <= 23:
                return
        candidates.append({
            "start": match.start(), "end": match.end(),
            "start_hour": start_hour_value, "start_minute": start_minute_value,
            "start_meridiem": start_meridiem_value,
            "end_hour": end_hour_value, "end_minute": end_minute_value,
            "end_meridiem": end_meridiem_value,
        })
        occupied.append(match.span())

    # Accept both full ranges (10 AM - 10:30 AM) and abbreviated ranges
    # (10 - 11 AM). The end meridiem is propagated to the start when omitted.
    for match in re.finditer(
        rf"(?<![\w:])(?P<start_hour>0?[1-9]|1[0-2])(?:(?::|\.)(?P<start_minute>[0-5]\d))?\s*"
        rf"(?P<start_meridiem>{meridiem})?\s*(?:-|to|until)\s*"
        rf"(?P<end_hour>0?[1-9]|1[0-2])(?:(?::|\.)(?P<end_minute>[0-5]\d))?\s*"
        rf"(?P<end_meridiem>{meridiem})(?!\w)",
        clean,
        flags=re.IGNORECASE,
    ):
        add(
            match, match.group("start_hour"), match.group("start_minute"),
            match.group("start_meridiem") or match.group("end_meridiem"),
            match.group("end_hour"), match.group("end_minute"), match.group("end_meridiem"),
        )
    for match in re.finditer(
        r"(?<![\w:])(?P<start_hour>[01]?\d|2[0-3]):(?P<start_minute>[0-5]\d)\s*"
        r"(?:-|to|until)\s*(?P<end_hour>[01]?\d|2[0-3]):(?P<end_minute>[0-5]\d)(?!\d)",
        clean,
        flags=re.IGNORECASE,
    ):
        add(
            match, match.group("start_hour"), match.group("start_minute"), "",
            match.group("end_hour"), match.group("end_minute"), "",
        )

    def overlaps(span: Tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    for match in re.finditer(
        rf"(?<![\w:])(?P<hour>0?[1-9]|1[0-2])(?:(?::|\.)(?P<minute>[0-5]\d))?\s*"
        rf"(?P<meridiem>{meridiem})(?!\w)",
        clean,
        flags=re.IGNORECASE,
    ):
        if not overlaps(match.span()):
            add(match, match.group("hour"), match.group("minute"), match.group("meridiem"))
    for match in re.finditer(
        r"(?<![\w:])(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?!\d)",
        clean,
    ):
        if not overlaps(match.span()):
            add(match, match.group("hour"), match.group("minute"), "")
    return sorted(candidates, key=lambda item: item["start"])


def _slot_time_options(text: Any, date_value: datetime) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    for candidate in _slot_time_candidates(text):
        start_hour = candidate["start_hour"]
        start_minute = candidate["start_minute"]
        if candidate["start_meridiem"]:
            start_hour, start_minute = _time_to_24h(start_hour, start_minute, candidate["start_meridiem"])
        start = date_value.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        if candidate["end_hour"] is None:
            end = start + timedelta(minutes=30)
        else:
            end_hour = candidate["end_hour"]
            end_minute = candidate["end_minute"] or 0
            if candidate["end_meridiem"]:
                end_hour, end_minute = _time_to_24h(end_hour, end_minute, candidate["end_meridiem"])
            end = date_value.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
            if end <= start:
                end += timedelta(days=1)
        options.append({
            **candidate,
            "start_datetime": start,
            "end_datetime": end,
            "label": f"{start.strftime('%d/%m/%Y, %I:%M %p')} - {end.strftime('%I:%M %p')}",
        })
    return options


def _parse_time_range(text: str, date_value: datetime) -> Optional[tuple[datetime, datetime, str]]:
    options = _slot_time_options(text, date_value)
    if not options:
        return None
    first = options[0]
    return first["start_datetime"], first["end_datetime"], first["label"]


def _selected_slot_number(text: str) -> Optional[int]:
    clean = _normalise_slot_text(text)
    match = re.search(r"\b(?:slot|option)\s*(\d+)\b", clean, flags=re.IGNORECASE)
    if match:
        return _safe_int(match.group(1), 0) or None
    match = re.search(r"(?:^|\s)(\d{1,2})\s*[\).:#-]\s*(?:slot|option)\b", clean, flags=re.IGNORECASE)
    if match:
        return _safe_int(match.group(1), 0) or None
    return None


def _slot_options_from_text(source_text: Any) -> List[Dict[str, Any]]:
    clean = _normalise_slot_text(_strip_quoted_email_history(source_text))
    date_matches = _slot_date_matches(clean)
    options: List[Dict[str, Any]] = []
    seen_starts: set[datetime] = set()
    for time_candidate in _slot_time_candidates(clean):
        previous_dates = [item for item in date_matches if item["end"] <= time_candidate["start"]]
        if previous_dates:
            date_value = previous_dates[-1]["value"]
        else:
            # Support the natural wording "10 AM on 6 September 2026" while
            # preventing a date from a different paragraph being borrowed.
            next_dates = [item for item in date_matches if item["start"] >= time_candidate["end"]]
            if not next_dates:
                continue
            following = next_dates[0]
            between = clean[time_candidate["end"]:following["start"]]
            if "\n" in between or len(between) > 60:
                continue
            date_value = following["value"]
        candidate_options = _slot_time_options(clean[time_candidate["start"]:time_candidate["end"]], date_value)
        if not candidate_options:
            continue
        parsed = candidate_options[0]
        start = parsed["start_datetime"]
        if start in seen_starts:
            continue
        seen_starts.add(start)
        line_start = clean.rfind("\n", 0, time_candidate["start"]) + 1
        prefix = clean[line_start:time_candidate["start"]]
        inline_number = re.search(r"(?:^|\b(?:slot|option)\s+)(\d{1,2})\s*[\).:#-]", prefix, flags=re.IGNORECASE)
        if not inline_number:
            previous_line = clean[:line_start].rstrip().splitlines()
            if previous_line:
                inline_number = re.fullmatch(r"\s*(?:slot\s*)?(\d{1,2})[\).:]?\s*", previous_line[-1], flags=re.IGNORECASE)
        proposed_number = _safe_int(inline_number.group(1), 0) if inline_number else 0
        used_numbers = {option["number"] for option in options}
        slot_number = proposed_number if proposed_number and proposed_number not in used_numbers else len(options) + 1
        line_end = clean.find("\n", time_candidate["end"])
        line = clean[line_start:] if line_end < 0 else clean[line_start:line_end]
        options.append({
            "number": slot_number,
            "start": start,
            "end": parsed["end_datetime"],
            "label": parsed["label"],
            "line": _clean(line),
        })
    return options


def _resolve_interview_slot_datetime(
    reply_text: Any,
    source_slot_text: Any,
) -> Dict[str, Any]:
    reply_clean = _normalise_slot_text(_strip_quoted_email_history(reply_text))
    selected_number = _selected_slot_number(reply_clean)
    options = _slot_options_from_text(source_slot_text)
    if selected_number:
        for option in options:
            if option.get("number") == selected_number:
                return {**option, "selected_number": selected_number, "source": "source_slot_options"}

    reply_date = _parse_slot_date(reply_clean)
    parsed_reply = _parse_time_range(reply_clean, reply_date) if reply_date else None
    if parsed_reply:
        start, end, label = parsed_reply
        return {"start": start, "end": end, "label": label, "selected_number": selected_number, "source": "client_reply"}

    # Clients commonly reply with only the chosen time (for example,
    # "2:00 PM - 2:30 PM IST"). Match that time to the dated options that
    # were sent in the preceding client-slots email.
    for option in options:
        option_start = option.get("start")
        if not isinstance(option_start, datetime):
            continue
        reply_time = _parse_time_range(reply_clean, option_start)
        if not reply_time:
            continue
        start, end, _label = reply_time
        if (start.hour, start.minute, end.hour, end.minute) == (
            option_start.hour,
            option_start.minute,
            option["end"].hour,
            option["end"].minute,
        ):
            return {**option, "selected_number": selected_number, "source": "client_time_matched_to_source_slot"}

    if len(options) == 1:
        return {**options[0], "selected_number": selected_number, "source": "single_source_slot"}
    return {"selected_number": selected_number, "source": "unresolved"}


def _is_google_meet_link(value: Any) -> bool:
    return "meet.google.com" in str(value or "").lower()


def _is_reschedule_request(text: Any) -> bool:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return False
    return bool(re.search(
        r"\b(?:reschedul(?:e|ed|ing)|re-schedul(?:e|ed|ing)|postpone|prepone|change\s+(?:the\s+)?(?:time|slot|date)|new\s+(?:slot|time|date)|another\s+(?:slot|time|date)|busy|not\s+available|unavailable|cannot\s+attend|can't\s+attend|cant\s+attend)\b",
        lower,
        flags=re.IGNORECASE,
    ))


def _slot_confirmation_intent(text: Any) -> str:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return "unknown"
    if _is_reschedule_request(lower):
        return "reschedule"
    if re.search(r"\b(?:not available|unavailable|not possible|cannot|can't|cant|decline|no thanks|nope|sorry)\b", lower, flags=re.IGNORECASE):
        return "rejected"
    if re.search(r"\bslot\s*\d+\b", lower, flags=re.IGNORECASE):
        return "selected_slot_number"
    # Clients often reply conversationally rather than writing "Slot 3".
    # A dated time following "I am/was available at" is an explicit choice,
    # not a request for more availability details.
    if re.search(
        r"\b(?:i\s*(?:am|was)|we\s*(?:are|were))\s+available\s+(?:at|on|for)\b"
        r"[\s\S]*\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        lower,
        flags=re.IGNORECASE,
    ):
        return "selected_slot_details"
    if _has_proper_interview_slots(lower):
        return "selected_slot_details"
    if re.search(r"\b(book|confirm|select|choose|pick)\b[\s\S]*\bslot\b", lower, flags=re.IGNORECASE) and re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lower, flags=re.IGNORECASE):
        return "selected_slot_details"
    if re.search(r"\b(preferred slot|preferred option|selected slot|confirm(ed|ation)?|works for|works well|suits (?:me|us)|available|available for)\b", lower, flags=re.IGNORECASE):
        return "selected_slot"
    return "unknown"


async def _reschedule_mail_body(
    *,
    db: AsyncIOMotorDatabase,
    requirement: Dict[str, Any],
    recipient_kind: str,
    subject: str,
    inbound_text: str,
    reference_body: str,
    requested_date: str = "",
) -> Tuple[str, str]:
    """Use AI wording only when this requirement explicitly selected AI mode.

    The approved reference keeps the operational rule authoritative. AI can
    phrase it naturally but cannot change the recipient, slot count, or
    meeting-link promise. Failures always fall back to the reference text.
    """
    setting = await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    generation_mode = _clean(setting.get("value")).lower() or "template"
    if generation_mode != "ai":
        return reference_body, "template"
    try:
        from app.routes.inbox_actions import _ai_draft_reply

        generated = await _ai_draft_reply(
            subject=subject,
            body=inbound_text,
            hint=(
                "Write a concise interview-reschedule email to the stated recipient. "
                "Preserve the exact operational request in the reference: if the recipient is the trainer, "
                "ask for exactly three alternate slots with date, time, and time zone on the stated requested "
                "date. If that date is unavailable, ask the trainer for their nearest available date and exactly "
                "three slots on it. If the recipient is the client, ask for a preferred alternate date. Do not "
                "invent any date, availability, meeting link, "
                "commercial, or confirmation. Keep the Clahan Technologies sign-off."
            ),
            workflow_context={
                "workflow": "interview_reschedule",
                "generation_mode": generation_mode,
                "recipient_kind": recipient_kind,
                "requirement_id": requirement.get("requirement_id"),
                "technology": requirement.get("technology_needed") or requirement.get("domain"),
                "requested_date": requested_date,
                "required_action": "three alternate slots on the requested date" if recipient_kind == "trainer" else "one preferred alternate date",
            },
            reference_reply={"body": reference_body},
            require_openai=True,
        )
        if _clean(generated):
            return generated.strip(), "ai"
    except Exception:
        logger.exception("AI reschedule wording failed for %s", requirement.get("requirement_id"))
    return reference_body, "template_fallback"


def _is_trainer_logistics_question(text: str) -> bool:
    return bool(re.search(
        r"\b(?:travel|travelling|traveling|accommodation|stay|hotel|transport|local conveyance|reimbursement|expense|expenses)\b",
        _plain_text(text), flags=re.IGNORECASE,
    ))


def _requested_reschedule_date(text: Any) -> str:
    """Return the client-requested reschedule date without inventing one."""
    clean = _strip_quoted_email_history(text)
    lowered = clean.lower()
    if re.search(r"\b(?:tomorrow|tmrw|tmw)\b", lowered, flags=re.IGNORECASE):
        return (datetime.now(LOCAL_TZ).date() + timedelta(days=1)).strftime("%d %B %Y")
    parsed = _parse_slot_date(clean)
    if parsed:
        return parsed.strftime("%d %B %Y")
    return ""


def _email_subject_key(subject: Any) -> str:
    """Normalize reply prefixes so a logistics reply stays on its own thread."""
    value = _clean(subject).lower()
    while True:
        normalized = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", value, flags=re.IGNORECASE).strip()
        if normalized == value:
            return normalized
        value = normalized


def _verified_logistics_details(requirement: Dict[str, Any]) -> List[str]:
    """Return only logistics facts explicitly stored on the requirement."""
    return [
        str(requirement.get(key) or "").strip()
        for key in (
            "travel_policy", "travel_arrangement", "travel_reimbursement",
            "accommodation_policy", "stay_details", "location",
        )
        if str(requirement.get(key) or "").strip()
    ]


def _has_expense_commitment(text: str) -> bool:
    """Detect an affirmative commitment to cover or reimburse logistics costs."""
    return bool(re.search(
        r"\b(?:will|shall|is|are)\s+(?:be\s+)?(?:covered|reimbursed|paid|arranged|provided)\b"
        r"|\b(?:cover|reimburse|pay|arrange|provide)\s+(?:your\s+|all\s+|the\s+)?"
        r"(?:travel|stay|hotel|accommodation|transport|expense|expenses)\b",
        _plain_text(text),
        flags=re.IGNORECASE,
    ))


def _logistics_ai_output_is_grounded(generated: str, reference: str) -> bool:
    """Reject AI wording that turns a clarification into an expense approval."""
    currency = re.compile(r"(?:₹|\$|\b(?:inr|rs\.?|usd)\b)\s*[\d,]+", re.IGNORECASE)
    reference_amounts = {item.lower() for item in currency.findall(reference)}
    generated_amounts = {item.lower() for item in currency.findall(generated)}
    if not generated_amounts.issubset(reference_amounts):
        return False
    return not _has_expense_commitment(generated) or _has_expense_commitment(reference)


async def _handle_trainer_logistics_question(db: AsyncIOMotorDatabase, email_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Answer verified logistics facts or obtain them from the client."""
    requirement_id, trainer_id = _clean(email_doc.get("requirement_id")), _clean(email_doc.get("trainer_id"))
    text = _strip_quoted_email_history(email_doc.get("classification_body") or email_doc.get("body") or "")
    if not requirement_id or not trainer_id or not _is_trainer_logistics_question(text):
        return {"attempted": False}
    req = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}, trainer_id) or {}
    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email"))
    client_email = _email_address(req.get("client_email") or req.get("from_email") or req.get("requester_email"))
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name") or email_doc.get("from_name") or "Trainer")
    technology = _clean(req.get("technology_needed") or req.get("technology") or req.get("domain") or "training")
    known = _verified_logistics_details(req)
    settings_doc = await _load_admin_settings(db)
    if known and trainer_email:
        reference = f"Hi {trainer_name},\n\nRegarding your travel/stay query for the {technology} requirement:\n\n" + "\n".join(f"- {item}" for item in known) + "\n\nRegards,\nClahan Technologies"
        body, source = await _client_pipeline_email_body(db, requirement=req, workflow="trainer_logistics_answer", subject=f"Travel / Stay Details - {technology}", reference_body=reference, context={"trainer_name": trainer_name, "question": text, "verified_logistics": known})
        ok, error = await send_email_async(to=trainer_email, subject=f"Travel / Stay Details - {technology}", body=body, smtp_config=settings_doc.get("emailCfg") or None, message_id_header=generate_message_id())
        return {"attempted": True, "success": bool(ok), "generation_source": source, "error": error or ""}
    if not client_email:
        return {"attempted": True, "success": False, "error": "Client email unavailable for logistics clarification"}
    subject = f"Travel / Stay Clarification Required - {technology}"
    reference = f"Dear {req.get('client_name') or 'Team'},\n\nThe shortlisted trainer has asked about travel, stay, or related expense arrangements for the {technology} requirement.\n\nPlease confirm the travel policy, accommodation/stay arrangement, local transport or reimbursement terms, and training location.\n\nRegards,\nClahan Technologies"
    body, source = await _client_pipeline_email_body(db, requirement=req, workflow="client_logistics_clarification", subject=subject, reference_body=reference, context={"trainer_name": trainer_name, "trainer_question": text, "technology": technology})
    message_id = generate_message_id()
    ok, error = await send_email_async(to=client_email, subject=subject, body=body, smtp_config=settings_doc.get("emailCfg") or None, message_id_header=message_id)
    query_id = f"LQ-{uuid.uuid4().hex[:10].upper()}"
    await db["trainer_logistics_queries"].insert_one({"query_id": query_id, "requirement_id": requirement_id, "trainer_id": trainer_id, "trainer_name": trainer_name, "trainer_email": trainer_email, "client_email": client_email, "clarification_subject": subject, "clarification_message_id": message_id, "trainer_question": text, "status": "client_asked" if ok else "client_ask_failed", "generation_source": source, "created_at": _now(), "updated_at": _now()})
    return {"attempted": True, "success": bool(ok), "asked_client": True, "query_id": query_id, "error": error or ""}


async def _relay_client_logistics_answer(db: AsyncIOMotorDatabase, email_doc: Dict[str, Any]) -> Dict[str, Any]:
    sender = _email_address(email_doc.get("from_email") or "")
    text = _strip_quoted_email_history(email_doc.get("classification_body") or email_doc.get("body") or "")
    # A client commonly replies "Yes, that is included" without repeating
    # travel/stay vocabulary.  An open logistics query, matched to the client
    # sender, is the authoritative context for relaying that response.
    if not sender or not text:
        return {"attempted": False}
    query = await db["trainer_logistics_queries"].find_one({"client_email": {"$regex": f"^{re.escape(sender)}$", "$options": "i"}, "status": "client_asked"}, {"_id": 0}, sort=[("created_at", -1)])
    if not query or not _email_address(query.get("trainer_email")):
        return {"attempted": False}
    query_subject = _email_subject_key(query.get("clarification_subject"))
    inbound_subject = _email_subject_key(email_doc.get("subject"))
    # Queries created before this field existed remain eligible only when the
    # inbound mail is already linked to the clarification outbound message.
    source_message_id = _clean(email_doc.get("source_gmail_message_id") or email_doc.get("in_reply_to") or "")
    if query_subject and inbound_subject != query_subject:
        return {"attempted": False}
    if not query_subject and query.get("clarification_message_id") and source_message_id != _clean(query.get("clarification_message_id")):
        return {"attempted": False}
    req = await db["requirements"].find_one({"requirement_id": query.get("requirement_id")}, {"_id": 0}) or {}
    subject = f"Client Update: Travel / Stay Details - {_clean(req.get('technology_needed') or req.get('technology') or 'Training')}"
    reference = f"Hi {query.get('trainer_name') or 'Trainer'},\n\nThe client has shared the following response to your travel/stay query:\n\n{text}\n\nRegards,\nClahan Technologies"
    body, source = await _client_pipeline_email_body(db, requirement=req, workflow="trainer_logistics_client_answer", subject=subject, reference_body=reference, context={"trainer_name": query.get("trainer_name"), "client_answer": text})
    settings_doc = await _load_admin_settings(db)
    ok, error = await send_email_async(to=query["trainer_email"], subject=subject, body=body, smtp_config=settings_doc.get("emailCfg") or None, message_id_header=generate_message_id())
    await db["trainer_logistics_queries"].update_one({"query_id": query["query_id"]}, {"$set": {"status": "trainer_answer_sent" if ok else "trainer_answer_failed", "client_answer": text, "generation_source": source, "updated_at": _now()}})
    return {"attempted": True, "success": bool(ok), "error": error or ""}


def _question_reply_needs_clarification(reply: Dict[str, Any]) -> bool:
    """Return True when a grounded draft explicitly says the fact is unavailable."""
    text = _plain_text((reply or {}).get("body") or "").lower()
    return bool(re.search(
        r"\b(?:we (?:are|will be) check(?:ing)?|will (?:check|verify|confirm)|"
        r"requires? confirmation|need(?:s)? (?:to be )?(?:checked|verified|confirmed)|"
        r"not (?:yet )?(?:available|confirmed|specified)|do not have (?:a )?confirmed)\b",
        text,
        flags=re.IGNORECASE,
    ))


def _question_source_id(email_doc: Dict[str, Any]) -> str:
    """Stable inbound identity used to make question processing idempotent."""
    source_id = _clean(
        email_doc.get("source_gmail_message_id")
        or email_doc.get("gmail_message_id")
        or email_doc.get("message_id")
        or email_doc.get("email_id")
    )
    if source_id:
        return source_id
    fingerprint_input = "\n".join([
        _clean(email_doc.get("requirement_id")),
        _clean(email_doc.get("trainer_id")),
        _email_address(email_doc.get("from_email")),
        _clean(email_doc.get("subject")),
        _strip_quoted_email_history(email_doc.get("classification_body") or email_doc.get("body") or ""),
    ])
    return f"sha256:{hashlib.sha256(fingerprint_input.encode('utf-8')).hexdigest()}"


async def _claim_trainer_question(
    db: AsyncIOMotorDatabase,
    *,
    source_id: str,
    requirement_id: str,
    trainer_id: str,
    question: str,
) -> Dict[str, Any]:
    """Atomically acquire the right to send for one inbound trainer question."""
    now = _now()
    claim_token = uuid.uuid4().hex
    query_id = f"TQ-{uuid.uuid4().hex[:10].upper()}"
    claim = {
        "query_id": query_id,
        "source_message_id": source_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_question": question,
        "status": "processing",
        "claim_token": claim_token,
        "claim_expires_at": now + timedelta(minutes=10),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db["trainer_question_queries"].insert_one(claim)
        return {"claimed": True, **claim}
    except DuplicateKeyError:
        # A failed delivery may be retried, and an abandoned claim may be
        # reclaimed after its lease. Only one worker can win this CAS update.
        reclaimed = await db["trainer_question_queries"].find_one_and_update(
            {
                "source_message_id": source_id,
                "$or": [
                    {"status": {"$in": ["answer_failed", "client_ask_failed"]}},
                    {"status": "processing", "claim_expires_at": {"$lte": now}},
                ],
            },
            {"$set": {
                "status": "processing",
                "claim_token": claim_token,
                "claim_expires_at": now + timedelta(minutes=10),
                "updated_at": now,
            }},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        if reclaimed and reclaimed.get("claim_token") == claim_token:
            return {"claimed": True, **reclaimed}
        existing = await db["trainer_question_queries"].find_one(
            {"source_message_id": source_id}, {"_id": 0}
        ) or {}
        return {"claimed": False, **existing}


def _verified_requirement_question_answer(
    question: str, requirement: Dict[str, Any], trainer_name: str
) -> Optional[Dict[str, str]]:
    """Answer common factual questions directly from explicit requirement fields."""
    text = _plain_text(question).lower()
    field_groups = [
        (r"\b(?:online|offline|hybrid|mode|virtual|onsite|on-site)\b", "Training mode", ("mode", "training_mode", "delivery_mode")),
        (r"\b(?:date|dates|start date|end date|when)\b", "Training dates", ("training_dates", "preferred_dates", "timeline_start")),
        (r"\b(?:time|timing|session hours|hours per day)\b", "Training timing", ("timing", "training_time", "session_timing")),
        (r"\b(?:duration|how many days|number of days)\b", "Training duration", ("duration", "duration_text", "duration_days", "duration_hours")),
        (r"\b(?:location|venue|where|city)\b", "Training location", ("location", "training_location", "venue")),
        (r"\b(?:participant|participants|learners|batch size|audience size)\b", "Participants", ("participant_count", "participants", "batch_size")),
        (r"\b(?:audience|experience level|beginner|intermediate|advanced)\b", "Audience level", ("audience_level", "target_audience")),
        (r"\b(?:recording|recorded)\b", "Recording policy", ("recording_policy", "recording_details")),
        (r"\b(?:material|courseware|slides|source files)\b", "Material policy", ("material_policy", "material_details")),
        (r"\b(?:lab|account|cluster|tool|software|prerequisite|setup)\b", "Lab/setup details", ("lab_details", "hands_on_lab", "prerequisites", "software_requirements")),
        (r"\b(?:payment terms|payment cycle|when.*paid|invoice process)\b", "Payment terms", ("trainer_payment_terms", "payment_terms", "payment_cycle")),
    ]
    requested = []
    missing = False
    for pattern, label, keys in field_groups:
        if not re.search(pattern, text, flags=re.IGNORECASE):
            continue
        value = next((_clean(requirement.get(key)) for key in keys if _clean(requirement.get(key))), "")
        if value:
            requested.append((label, value))
        else:
            missing = True
    if not requested or missing:
        return None
    technology = _clean(
        requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain")
    )
    details = "\n".join(f"- {label}: {value}" for label, value in requested)
    topic = f" for the {technology} requirement" if technology else ""
    return {
        "subject": f"Re: {technology or 'Training'} Clarification",
        "body": (
            f"Hi {trainer_name or 'Trainer'},\n\n"
            f"The confirmed requirement details{topic} are:\n\n{details}\n\n"
            "Regards,\nClahan Technologies"
        ),
    }


async def _handle_trainer_general_question(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    generated_reply: Dict[str, Any],
) -> Dict[str, Any]:
    """Answer a trainer automatically or ask the linked client without changing pipeline state."""
    requirement_id = _clean(email_doc.get("requirement_id"))
    trainer_id = _clean(email_doc.get("trainer_id"))
    question = _strip_quoted_email_history(
        email_doc.get("classification_body") or email_doc.get("body") or ""
    )
    if not requirement_id or not trainer_id or not question:
        return {"attempted": False}

    source_id = _question_source_id(email_doc)
    claim = await _claim_trainer_question(
        db,
        source_id=source_id,
        requirement_id=requirement_id,
        trainer_id=trainer_id,
        question=question,
    )
    if not claim.get("claimed"):
        return {
            "attempted": True,
            "success": True,
            "skipped": True,
            "reason": "question_already_processing_or_processed",
            "query_id": claim.get("query_id"),
            "status": claim.get("status"),
        }
    query_id = _clean(claim.get("query_id"))
    claim_filter = {"query_id": query_id, "claim_token": claim.get("claim_token")}

    requirement = await db["requirements"].find_one(
        {"requirement_id": requirement_id}, {"_id": 0}
    ) or {}
    shortlist = await db["shortlists"].find_one(
        {"requirement_id": requirement_id}, {"_id": 0}
    ) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id) or {}
    trainer_email = _email_address(
        trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email")
    )
    trainer_name = _clean(
        trainer.get("name") or trainer.get("trainer_name") or email_doc.get("from_name") or "Trainer"
    )
    client_email = await _client_email_from_context(
        db, requirement_id, trainer_email, requirement, shortlist
    )
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or "Training"
    )
    settings_doc = await _load_admin_settings(db)
    now = _now()

    requirement_reply = _verified_requirement_question_answer(question, requirement, trainer_name)
    if requirement_reply:
        generated_reply = requirement_reply

    # A draft that contains a direct, verified answer can go straight back to
    # the trainer. The question record is deliberately separate from shortlist
    # state, so answering it cannot advance or reset the workflow.
    if generated_reply and not _question_reply_needs_clarification(generated_reply):
        if not trainer_email:
            await db["trainer_question_queries"].update_one(
                claim_filter,
                {"$set": {"status": "answer_failed", "error": "Trainer email unavailable", "updated_at": _now()}},
            )
            return {"attempted": True, "success": False, "error": "Trainer email unavailable"}
        ok, error = await send_email_async(
            to=trainer_email,
            subject=generated_reply.get("subject") or f"Re: {email_doc.get('subject') or technology}",
            body=generated_reply.get("body") or "",
            smtp_config=settings_doc.get("emailCfg") or None,
            message_id_header=generate_message_id(),
        )
        await db["trainer_question_queries"].update_one(
            claim_filter,
            {"$set": {
                "trainer_name": trainer_name,
                "trainer_email": trainer_email,
                "status": "answer_sent" if ok else "answer_failed",
                "answer_source": "verified_requirement_or_thread",
                "answer": generated_reply.get("body") or "",
                "error": error or "",
                "claim_expires_at": None,
                "updated_at": _now(),
            }},
        )
        return {"attempted": True, "success": bool(ok), "query_id": query_id, "error": error or ""}

    if not client_email:
        await db["trainer_question_queries"].update_one(
            claim_filter,
            {"$set": {"status": "client_ask_failed", "error": "Client email unavailable for clarification", "updated_at": _now()}},
        )
        return {"attempted": True, "success": False, "error": "Client email unavailable for clarification"}

    subject = f"Clarification Required [{query_id}] - {technology}"
    client_name = _clean(requirement.get("client_name") or "Team")
    reference = (
        f"Hi {client_name},\n\n"
        f"The shortlisted trainer has asked the following question about the {technology} requirement:\n\n"
        f"{question}\n\n"
        "Please reply to this email with the confirmed information. We will send your response to the trainer.\n\n"
        "Regards,\nClahan Technologies"
    )
    body, source = await _client_pipeline_email_body(
        db,
        requirement=requirement,
        workflow="client_trainer_question_clarification",
        subject=subject,
        reference_body=reference,
        context={"query_id": query_id, "trainer_name": trainer_name, "trainer_question": question},
    )
    clarification_message_id = generate_message_id()
    ok, error = await send_email_async(
        to=client_email,
        subject=subject,
        body=body,
        smtp_config=settings_doc.get("emailCfg") or None,
        message_id_header=clarification_message_id,
    )
    await db["trainer_question_queries"].update_one(
        claim_filter,
        {"$set": {
            "trainer_name": trainer_name,
            "trainer_email": trainer_email,
            "client_email": client_email,
            "clarification_subject": subject,
            "clarification_message_id": clarification_message_id,
            "status": "client_asked" if ok else "client_ask_failed",
            "generation_source": source,
            "error": error or "",
            "claim_expires_at": None,
            "updated_at": _now(),
        }},
    )
    return {
        "attempted": True,
        "success": bool(ok),
        "asked_client": True,
        "query_id": query_id,
        "error": error or "",
    }


async def _relay_client_question_answer(
    db: AsyncIOMotorDatabase, email_doc: Dict[str, Any]
) -> Dict[str, Any]:
    """Relay a client's answer to the trainer associated with the pending query."""
    sender = _email_address(email_doc.get("from_email") or "")
    answer = _strip_quoted_email_history(
        email_doc.get("classification_body") or email_doc.get("body") or ""
    )
    if not sender or not answer:
        return {"attempted": False}
    query = await db["trainer_question_queries"].find_one(
        {
            "client_email": {"$regex": f"^{re.escape(sender)}$", "$options": "i"},
            "status": "client_asked",
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not query or not _email_address(query.get("trainer_email")):
        return {"attempted": False}
    if _email_subject_key(email_doc.get("subject")) != _email_subject_key(query.get("clarification_subject")):
        return {"attempted": False}

    requirement = await db["requirements"].find_one(
        {"requirement_id": query.get("requirement_id")}, {"_id": 0}
    ) or {}
    technology = _clean(
        requirement.get("technology_needed") or requirement.get("technology") or "Training"
    )
    subject = f"Client Answer - {technology} | Ref: {query.get('query_id')}"
    reference = (
        f"Hi {query.get('trainer_name') or 'Trainer'},\n\n"
        "The client has confirmed the following information in response to your question:\n\n"
        f"{answer}\n\nRegards,\nClahan Technologies"
    )
    body, source = await _client_pipeline_email_body(
        db,
        requirement=requirement,
        workflow="trainer_client_question_answer",
        subject=subject,
        reference_body=reference,
        context={
            "query_id": query.get("query_id"),
            "trainer_name": query.get("trainer_name"),
            "trainer_question": query.get("trainer_question"),
            "client_answer": answer,
        },
    )
    settings_doc = await _load_admin_settings(db)
    ok, error = await send_email_async(
        to=query["trainer_email"],
        subject=subject,
        body=body,
        smtp_config=settings_doc.get("emailCfg") or None,
        message_id_header=generate_message_id(),
    )
    await db["trainer_question_queries"].update_one(
        {"query_id": query["query_id"]},
        {"$set": {
            "status": "trainer_answer_sent" if ok else "trainer_answer_failed",
            "client_answer": answer,
            "answer_source": "client_reply",
            "generation_source": source,
            "updated_at": _now(),
        }},
    )
    return {"attempted": True, "success": bool(ok), "query_id": query.get("query_id"), "error": error or ""}


async def _handle_interview_reschedule_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    is_client_date_reply = source_mail_type == "client_interview_reschedule_date_request"
    is_interview_thread = (
        source_mail_type in {
            "mail4",
            "client_interview_schedule",
            "mail4_reschedule_request",
            "client_interview_reschedule_date_request",
        }
        or bool(re.search(r"(Interview Schedule|Interview Link|Meeting Link|Google Meet|Reschedule Request)", subject, flags=re.IGNORECASE))
    )
    if not is_interview_thread:
        return {"attempted": False, "reason": "not_interview_thread"}

    reply_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    if not _is_reschedule_request(reply_text) and not is_client_date_reply:
        return {"attempted": False, "reason": "not_reschedule_reply"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": True, "success": False, "reason": "missing_requirement_or_trainer_link", "error": "Requirement/trainer link missing"}

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name") or email_doc.get("trainer_name")) or "Trainer"
    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("trainer_email"))
    inbound_sender = _email_address(email_doc.get("from_email") or email_doc.get("sender_email") or email_doc.get("from"))
    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    client_name = _client_name_from_context(requirement, shortlist)
    technology = _clean(requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain") or shortlist.get("technology_needed")) or "training"
    now = _now()
    inbound_sender = _email_address(email_doc.get("from_email") or email_doc.get("sender_email") or email_doc.get("from"))
    sender_is_trainer = bool(trainer_email and inbound_sender == trainer_email)
    requested_date = _requested_reschedule_date(reply_text)
    if is_client_date_reply and not requested_date:
        return {
            "attempted": True,
            "success": False,
            "reason": "missing_requested_reschedule_date",
            "error": "Client reply did not include an alternate date.",
        }

    # Gmail can surface the same client reschedule reply more than once (for
    # example after a Calendar RSVP notification).  Once a reschedule request
    # is already with the trainer, record the inbound message but do not send
    # a duplicate request.
    previous_requested_date = _clean(trainer.get("reschedule_requested_date"))
    if (
        str(trainer.get("pipeline_status") or "").lower() == "interview_reschedule_requested"
        and str(trainer.get("reschedule_requested_by") or "").lower() == "client"
        and not sender_is_trainer
        and (not requested_date or requested_date == previous_requested_date)
    ):
        return {
            "attempted": True,
            "success": True,
            "skipped": True,
            "reason": "reschedule_request_already_sent",
            "requested_by": "client",
            "to": trainer_email,
        }

    target_email = client_email if sender_is_trainer else trainer_email
    target_name = client_name if sender_is_trainer else trainer_name
    if not target_email:
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "interview_reschedule_requested",
                "top_trainers.$.slot_status": "reschedule_needs_manual_email",
                "top_trainers.$.reschedule_requested_by": "trainer" if sender_is_trainer else "client",
                "top_trainers.$.reschedule_request_text": reply_text,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": False, "reason": "missing_target_email", "error": "Other side email missing"}

    if sender_is_trainer:
        subject_line = f"Interview Reschedule Request - {technology} | {trainer_name}"
        body = (
            f"{_client_time_greeting(target_name or 'Team')},\n\n"
            f"Trainer {trainer_name} has requested to reschedule the interview for the {technology} requirement.\n\n"
            "Trainer message:\n"
            f"{reply_text}\n\n"
            "Please share one convenient alternate slot, including the date, time, and time zone. Once the trainer confirms it, we will send a new meeting link.\n\n"
            "Regards,\nClahan Technologies"
        )
        mail_type = "client_interview_reschedule_request"
        recipient_kind = "client"
    else:
        subject_line = f"Interview Reschedule Request - {technology}"
        date_request = (
            f"The client has requested {requested_date}.\n\n"
            if requested_date else
            "The client has requested a different interview date.\n\n"
        )
        slot_request = (
            f"Please share exactly three convenient slots on {requested_date}, including the date, time, and time zone. "
            "If that date is not possible, please share your nearest available date and exactly three slots on that date."
            if requested_date else
            "Please share your nearest available date and exactly three convenient slots on that date, including the date, time, and time zone."
        )
        body = (
            f"Hi {target_name or 'Trainer'},\n\n"
            f"The client has requested to reschedule the interview for the {technology} requirement.\n\n"
            f"{date_request}"
            "Client message:\n"
            f"{reply_text}\n\n"
            f"{slot_request} Once a slot is finalized, we will share the revised meeting invitation with you.\n\n"
            "Regards,\nClahan Technologies"
        )
        mail_type = "mail4_reschedule_request"
        recipient_kind = "trainer"

    body, generation_source = await _reschedule_mail_body(
        db=db,
        requirement=requirement,
        recipient_kind=recipient_kind,
        subject=subject_line,
        inbound_text=reply_text,
        reference_body=body,
        requested_date=requested_date,
    )

    settings_doc = await _load_admin_settings(db)
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=target_email,
        subject=subject_line,
        body=body,
        smtp_config=settings_doc.get("emailCfg") or None,
        message_id_header=message_id_header,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": target_email,
        "to_email": target_email,
        "subject": subject_line,
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": body,
        "body_snippet": body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": mail_type,
        "source_email_id": email_doc.get("email_id"),
        "source_gmail_message_id": _current_inbound_message_id(email_doc),
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "client_email": client_email,
        "client_name": client_name,
        "interview_scheduled": True,
        "reschedule_requested": True,
        "reschedule_requested_by": "trainer" if sender_is_trainer else "client",
        "reschedule_request_text": reply_text,
        "reschedule_requested_date": requested_date,
        "generation_mode": _clean((await db["automation_settings"].find_one({"key": "generation_mode"}, {"_id": 0}) or {}).get("value")) or "template",
        "generation_source": generation_source,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "interview_reschedule_requested",
            "top_trainers.$.slot_status": "reschedule_coordination",
            "top_trainers.$.reschedule_requested": True,
            "top_trainers.$.reschedule_requested_by": "trainer" if sender_is_trainer else "client",
            "top_trainers.$.reschedule_request_text": reply_text,
            "top_trainers.$.reschedule_requested_date": requested_date,
            "top_trainers.$.reschedule_forward_email_id": email_id,
            "top_trainers.$.last_mail_type": mail_type,
            "top_trainers.$.last_mail_type_attempted": mail_type,
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": now if success else None,
            "top_trainers.$.last_mail_error": "" if success else error,
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    return {
        "attempted": True,
        "success": bool(success),
        "reason": "interview_reschedule_forwarded",
        "requested_by": "trainer" if sender_is_trainer else "client",
        "email_id": email_id,
        "to": target_email,
        "mail_type": mail_type,
        "error": error or "",
        "sent_at": now,
    }


def _looks_like_toc_reply(text: Any) -> bool:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return False
    return bool(re.search(
        r"\b(?:toc|table\s+of\s+contents|course\s+agenda|training\s+agenda|day[-\s]?wise|curriculum|module\s+wise|session\s+plan|prerequisite|learning\s+outcomes?|attached|attachment)\b",
        lower,
        flags=re.IGNORECASE,
    ))


async def _handle_trainer_toc_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    is_toc_thread = (
        source_mail_type in {"mail6", "mail6_toc", "toc-request"}
        or bool(re.search(r"(ToC|Table of Contents|Course Agenda|Training Agenda)", subject, flags=re.IGNORECASE))
    )
    if not is_toc_thread:
        return {"attempted": False, "reason": "not_toc_thread"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": True, "success": False, "reason": "missing_requirement_or_trainer_link"}

    reply_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    if not _looks_like_toc_reply(reply_text):
        return {"attempted": False, "reason": "not_toc_content"}

    now = _now()
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "toc_received_pending",
            "top_trainers.$.toc_status": "received",
            "top_trainers.$.toc_received_at": now,
            "top_trainers.$.toc_reply_email_id": email_doc.get("email_id") or "",
            "top_trainers.$.toc_reply_text": reply_text,
            "top_trainers.$.last_mail_type": "mail6_toc",
            "top_trainers.$.updated_at": now,
            "selection_status": "toc_received_pending",
            "updated_at": now,
        }},
    )
    try:
        await db["email_logs"].insert_one({
            "email_id": f"EML-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "from": email_doc.get("from") or email_doc.get("from_email") or "",
            "from_email": email_doc.get("from_email") or "",
            "to_email": email_doc.get("to_email") or "",
            "subject": subject,
            "body_snippet": reply_text[:300],
            "status": "received",
            "mail_type": "trainer_toc_received",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "source_email_id": email_doc.get("email_id"),
            "created_at": now,
            "updated_at": now,
        })
    except Exception:
        pass

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {
            "trainer_id": trainer_id,
            "name": email_doc.get("trainer_name") or "Trainer",
            "email": email_doc.get("from_email") or "",
        }
    client_toc_result = await _send_client_toc_received_email(
        db,
        email_doc,
        requirement,
        shortlist,
        trainer,
        reply_text,
    )
    mail3_result = await _send_trainer_mail3_if_missing(
        db,
        requirement_id,
        trainer_id,
        trainer,
        requirement,
        shortlist,
        source_email_id=email_doc.get("email_id") or "",
        source_gmail_message_id=_current_inbound_message_id(email_doc),
    )
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.client_toc_received_email_id": client_toc_result.get("email_id") or "",
            "top_trainers.$.toc_status": "shared_with_client" if client_toc_result.get("success") else "client_share_failed",
            "top_trainers.$.pipeline_status": "slot_booked" if mail3_result.get("success") else "toc_received_pending",
            "top_trainers.$.last_mail_type": "mail3" if mail3_result.get("success") else "mail6_toc",
            "top_trainers.$.last_mail_error": "" if mail3_result.get("success") else (mail3_result.get("error") or client_toc_result.get("error") or ""),
            "top_trainers.$.updated_at": _now(),
            "updated_at": _now(),
        }},
    )

    return {
        "attempted": True,
        "success": bool(client_toc_result.get("success") and mail3_result.get("success")),
        "reason": "trainer_toc_received",
        "status": "slot_booked" if mail3_result.get("success") else "toc_received_pending",
        "client_toc": client_toc_result,
        "mail3": mail3_result,
        "sent_at": now,
    }


async def _handle_client_slot_confirmation_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    has_slot_subject = bool(re.search(
        r"(Trainer Interview Slots|Interview Slots|Slot options|Slot selection|Selected slot|Preferred slot|preferred slot|Interview Slot Booking|Slot Booking|Interview Availability|Trainer Availability Slots)",
        subject,
        flags=re.IGNORECASE,
    ))
    # A stale/mislinked source_outbound_mail_type must not turn the original
    # requirement into a slot choice.  Gmail replies normally retain either
    # In-Reply-To/References or the slot-email subject; require one of those
    # signals before creating a Meet event.
    has_reply_thread_link = bool(
        _clean(email_doc.get("in_reply_to"))
        or _clean(email_doc.get("references"))
        or re.match(r"^\s*(?:re|fw|fwd)\s*:", subject, flags=re.IGNORECASE)
    )
    is_client_slot_thread = has_slot_subject or (
        source_mail_type == "client_slots" and has_reply_thread_link
    )
    reply_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    if not is_client_slot_thread:
        return {"attempted": False, "reason": "not_client_slot_reply_thread"}
    if not requirement_id or not trainer_id:
        return {"attempted": False, "reason": "missing_requirement_or_trainer_link"}

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer"}

    # New slots sent during a reschedule must lead to a new Calendar event.
    # Do not let the normal Mail 4 duplicate protection reuse the old link.
    is_reschedule_selection = bool(trainer.get("reschedule_requested"))

    trainer_email = _email_address(
        trainer.get("email")
        or trainer.get("trainer_email")
        or email_doc.get("trainer_email")
        or email_doc.get("trainer_email")
    )
    reply_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    intent = _slot_confirmation_intent(reply_text)
    now = _now()

    if intent != "selected_slot_number" and intent != "selected_slot_details" and intent != "selected_slot":
        return {
            "attempted": True,
            "success": False,
            "reason": "invalid_slot_confirmation",
            "intent": intent,
            "error": "Client reply did not contain a valid selected interview slot.",
        }

    if not trainer_email:
        return {"attempted": True, "success": False, "reason": "missing_trainer_email", "error": "Trainer email missing", "intent": intent}

    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not client_email:
        inbound_sender = _email_address(email_doc.get("from_email") or email_doc.get("sender_email") or email_doc.get("from"))
        if inbound_sender and inbound_sender != trainer_email:
            client_email = inbound_sender
    client_name = _client_name_from_context(requirement, shortlist)
    if not client_email:
        error = "Client email missing; Google Meet link was not sent to client."
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "missing_client_email",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.last_mail_type_attempted": "mail4",
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mail_error": error,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {"attempted": True, "success": False, "reason": "missing_client_email", "error": error, "intent": intent}

    selected_slot_text = _extract_slot_selection_text(reply_text)
    interview_date = selected_slot_text or _strip_quoted_email_history(reply_text)
    source_gmail_message_id = _current_inbound_message_id(email_doc)
    client_slots_email_id = (
        (email_doc.get("source_outbound_email_id") if source_mail_type == "client_slots" else "")
        or trainer.get("client_slots_email_id")
        or ""
    )
    client_slots_sent_at = trainer.get("client_slots_sent_at")
    source_client_slots_log: Optional[Dict[str, Any]] = None
    if source_mail_type == "client_slots" and client_slots_email_id:
        source_client_slots_log = await db["email_logs"].find_one(
            {"email_id": client_slots_email_id, "mail_type": "client_slots"},
            {"_id": 0, "sent_at": 1, "created_at": 1, "slot_text": 1, "body": 1, "body_snippet": 1, "subject": 1},
            sort=[("created_at", -1)],
        )
        if source_client_slots_log:
            client_slots_sent_at = source_client_slots_log.get("sent_at") or source_client_slots_log.get("created_at") or client_slots_sent_at
    technology = _clean(
        requirement.get("technology_needed")
        or requirement.get("technology")
        or requirement.get("domain")
        or shortlist.get("technology_needed")
        or "training"
    )
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    source_slot_text = (
        (source_client_slots_log or {}).get("slot_text")
        or (source_client_slots_log or {}).get("body")
        or trainer.get("slot_reply_text")
        or ""
    )
    resolved_slot = _resolve_interview_slot_datetime(reply_text, source_slot_text)
    if resolved_slot.get("label"):
        interview_date = resolved_slot["label"]

    duplicate_query: Dict[str, Any] = {
        "direction": "outbound",
        "status": "sent",
        "mail_type": "mail4",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
    }
    existing = await db["email_logs"].find_one(
        duplicate_query,
        {
            "_id": 0,
            "email_id": 1,
            "to_email": 1,
            "recipient": 1,
            "subject": 1,
            "sent_at": 1,
            "interview_link": 1,
            "meet_link": 1,
            "calendar_event_id": 1,
        },
        sort=[("created_at", -1)],
    )
    if existing:
        sent_at = existing.get("sent_at") or now
        existing_link = existing.get("meet_link") or existing.get("interview_link") or ""
    if existing and _is_google_meet_link(existing_link) and not is_reschedule_selection:
        # Earlier events may have been created without attendees. Repair the
        # actual Calendar event so Google sends invitations to both parties.
        calendar_invite_result = await add_google_calendar_attendees(
            existing.get("calendar_event_id") or trainer.get("calendar_event_id") or "",
            [trainer_email, client_email],
        )
        if not calendar_invite_result.get("success"):
            logger.error(
                "Existing interview invite repair failed for %s/%s: %s",
                requirement_id,
                trainer_id,
                calendar_invite_result.get("error"),
            )
        client_schedule_result: Dict[str, Any] = {"success": True, "already_sent": True}
        existing_client_schedule = await db["email_logs"].find_one(
            {
                "direction": "outbound",
                "status": "sent",
                "mail_type": "client_interview_schedule",
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "$or": [
                    {"source_trainer_email_id": existing.get("email_id") or ""},
                    {"interview_link": existing_link},
                    {"meet_link": existing_link},
                ],
            },
            {"_id": 0, "email_id": 1, "sent_at": 1, "to_email": 1, "recipient": 1, "subject": 1},
            sort=[("created_at", -1)],
        )
        if existing_client_schedule:
            client_schedule_result = {
                "success": True,
                "already_sent": True,
                "email_id": existing_client_schedule.get("email_id"),
                "to": existing_client_schedule.get("to_email") or existing_client_schedule.get("recipient"),
                "subject": existing_client_schedule.get("subject"),
                "sent_at": existing_client_schedule.get("sent_at") or sent_at,
            }
        else:
            settings_doc = await _load_admin_settings(db)
            smtp_config = settings_doc.get("emailCfg") or None
            client_schedule_result = await _send_client_interview_schedule_email(
                db,
                client_email=client_email,
                client_name=client_name,
                trainer_name=trainer_name,
                technology=technology,
                requirement_id=requirement_id,
                trainer_id=trainer_id,
                meeting_link=existing_link,
                interview_date=interview_date,
                smtp_config=smtp_config,
                calendar_event={"event_id": existing.get("calendar_event_id") or "", "meet_link": existing_link},
                source_email_id=email_doc.get("email_id") or "",
                source_gmail_message_id=source_gmail_message_id,
                source_trainer_email_id=existing.get("email_id") or "",
                slot_text=reply_text,
                now=now,
            )
        client_schedule_success = bool(client_schedule_result.get("success"))
        client_schedule_sent_at = client_schedule_result.get("sent_at") or sent_at
        if existing.get("email_id"):
            await db["email_logs"].update_one(
                {"email_id": existing.get("email_id")},
                {"$set": {
                    "client_email": client_email,
                    "client_name": client_name,
                    "client_email_sent": client_schedule_success,
                    "trainer_email_sent": True,
                    "client_interview_email_id": client_schedule_result.get("email_id") or "",
                    "interview_scheduled": client_schedule_success,
                    "updated_at": now,
                }},
            )
        duplicate_update_fields = {
            "top_trainers.$.pipeline_status": "interview_scheduled" if client_schedule_success else "slot_booked",
            "top_trainers.$.slot_status": "confirmed_by_client" if client_schedule_success else "client_interview_send_failed",
            "top_trainers.$.slot_reply_at": now,
            "top_trainers.$.slot_confirmed_at": sent_at,
            "top_trainers.$.slot_reply_text": reply_text,
            "top_trainers.$.client_slots_sent": True,
            "top_trainers.$.mail4_email_id": existing.get("email_id") or "",
            "top_trainers.$.client_mail4_email_id": client_schedule_result.get("email_id") or "",
            "top_trainers.$.mail4_sent_at": sent_at,
            "top_trainers.$.client_mail4_sent_at": client_schedule_sent_at if client_schedule_success else None,
            "top_trainers.$.interview_scheduled_at": sent_at if client_schedule_success else None,
            "top_trainers.$.interview_date": interview_date,
            "top_trainers.$.interview_link": existing_link,
            "top_trainers.$.meet_link": existing_link,
            "top_trainers.$.calendar_event_id": existing.get("calendar_event_id") or "",
            "top_trainers.$.client_email_sent": client_schedule_success,
            "top_trainers.$.trainer_email_sent": True,
            "top_trainers.$.last_mail_type": "mail4",
            "top_trainers.$.last_mail_type_attempted": "mail4",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": sent_at,
            "top_trainers.$.last_mail_error": "" if client_schedule_success else (client_schedule_result.get("error") or "Client interview schedule email failed"),
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }
        if client_slots_email_id:
            duplicate_update_fields["top_trainers.$.client_slots_email_id"] = client_slots_email_id
        if client_slots_sent_at:
            duplicate_update_fields["top_trainers.$.client_slots_sent_at"] = client_slots_sent_at
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": duplicate_update_fields},
        )
        return {
            "attempted": True,
            "success": client_schedule_success,
            "already_sent": bool(client_schedule_result.get("already_sent")),
            "email_id": existing.get("email_id"),
            "client_email_id": client_schedule_result.get("email_id") or "",
            "to": existing.get("to_email") or existing.get("recipient"),
            "client_to": client_schedule_result.get("to") or client_email,
            "subject": existing.get("subject"),
            "intent": intent,
            "slot_text": reply_text,
            "interview_link": existing_link if client_schedule_success else "",
            "error": "" if client_schedule_success else (client_schedule_result.get("error") or "Client interview schedule email failed"),
            "sent_at": sent_at,
        }

    if not resolved_slot.get("start") or not resolved_slot.get("end"):
        error = "Could not resolve selected slot date/time for Google Meet creation."
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "meet_link_failed",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.last_mail_type_attempted": "mail4",
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mail_error": error,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": False,
            "reason": "missing_slot_datetime",
            "error": error,
            "intent": intent,
            "slot_text": reply_text,
        }

    calendar_timezone = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata"
    calendar_event = await create_google_meet_event(
        summary=f"{technology} Interview",
        description=(
            f"Interview coordination for {technology}.\n"
            f"Requirement: {requirement_id}"
        ),
        start=resolved_slot["start"],
        end=resolved_slot["end"],
        # Adding both participants is required for Google Calendar to deliver
        # the Meet invitation. Previously this was an empty list, so a link
        # was created but no calendar invite was sent to anyone.
        attendees=[trainer_email, client_email],
        timezone=calendar_timezone,
    )
    meeting_link = calendar_event.get("meet_link") or ""
    if not calendar_event.get("success") or not meeting_link:
        calendar_error = calendar_event.get("error") or "Google Meet link creation failed."
        calendar_event = {**calendar_event, "success": False, "error": calendar_error}
        await db["email_logs"].insert_one({
            "email_id": f"CAL-{uuid.uuid4().hex[:10].upper()}",
            "direction": "internal",
            "subject": f"Calendar/Meet Creation Failed - {technology} | {requirement_id}",
            "body": (
                "Google Meet creation failed. No interview schedule mail was sent to trainer or client.\n\n"
                f"Requirement: {requirement_id}\n"
                f"Trainer: {trainer_name}\n"
                f"Trainer Email: {trainer_email}\n"
                f"Client Email: {client_email}\n"
                f"Selected Slot: {interview_date}\n"
                f"Error: {calendar_error}"
            ),
            "body_snippet": f"Google Meet creation failed. No interview schedule mail sent. Error: {calendar_error}"[:300],
            "status": "needs_manual_review",
            "error_message": calendar_error,
            "mail_type": "calendar_failure_report",
            "source_email_id": email_doc.get("email_id"),
            "source_gmail_message_id": source_gmail_message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "trainer_email": trainer_email,
            "client_email": client_email,
            "slot_text": reply_text,
            "interview_date": interview_date,
            "calendar_event": calendar_event,
            "created_at": now,
            "updated_at": now,
        })
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "calendar_failed_manual_review",
                "top_trainers.$.slot_status": "calendar_failed_no_mail_sent",
                "top_trainers.$.slot_reply_at": now,
                "top_trainers.$.slot_reply_text": reply_text,
                "top_trainers.$.interview_date": interview_date,
                "top_trainers.$.interview_link": "",
                "top_trainers.$.meet_link": "",
                "top_trainers.$.calendar_event": calendar_event,
                "top_trainers.$.calendar_event_id": "",
                "top_trainers.$.google_meet_error": calendar_error,
                "top_trainers.$.client_email_sent": False,
                "top_trainers.$.trainer_email_sent": False,
                "top_trainers.$.last_mail_type": "mail3",
                "top_trainers.$.last_mail_type_attempted": "mail4",
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mail_error": calendar_error,
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": False,
            "reason": "calendar_failed_no_mail_sent",
            "error": calendar_error,
            "intent": intent,
            "slot_text": reply_text,
            "interview_link": "",
            "calendar_event": calendar_event,
        }

    message = _trainer_interview_schedule_message(
        trainer_name=trainer_name,
        technology=technology,
        requirement_id=requirement_id,
        interview_date=interview_date,
        meeting_link=meeting_link,
    )
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_body, trainer_generation_source = await _client_pipeline_email_body(
        db,
        requirement=requirement,
        workflow="trainer_interview_confirmation",
        subject=message["subject"],
        reference_body=message["body"],
        context={
            "trainer_name": trainer_name,
            "meeting_link": meeting_link,
            "interview_date": interview_date,
            "calendar_invite_attached": True,
        },
    )
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message_body,
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message_body,
        "body_snippet": message_body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "mail4",
        "source_email_id": email_doc.get("email_id"),
        "source_gmail_message_id": source_gmail_message_id,
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "client_email": client_email,
        "client_name": client_name,
        "slot_text": reply_text,
        "interview_date": interview_date,
        "date_time_text": interview_date,
        "interview_at": resolved_slot["start"],
        "interview_end_at": resolved_slot["end"],
        "interview_link": meeting_link,
        "meet_link": meeting_link,
        "calendar_event": calendar_event,
        "calendar_event_id": calendar_event.get("event_id") or "",
        "calendar_html_link": calendar_event.get("html_link") or "",
        "timezone": calendar_timezone,
        "generation_source": trainer_generation_source,
        "interview_scheduled": bool(success),
        "trainer_email_sent": bool(success),
        "client_email_sent": False,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })

    client_schedule_result = await _send_client_interview_schedule_email(
        db,
        client_email=client_email,
        client_name=client_name,
        trainer_name=trainer_name,
        technology=technology,
        requirement_id=requirement_id,
        trainer_id=trainer_id,
        meeting_link=meeting_link,
        interview_date=interview_date,
        smtp_config=smtp_config,
        interview_start=resolved_slot["start"],
        interview_end=resolved_slot["end"],
        calendar_event=calendar_event,
        source_email_id=email_doc.get("email_id") or "",
        source_gmail_message_id=source_gmail_message_id,
        source_trainer_email_id=email_id,
        slot_text=reply_text,
        timezone_name=calendar_timezone,
        now=now,
    )
    client_schedule_success = bool(client_schedule_result.get("success"))
    overall_success = bool(success and client_schedule_success)
    await db["email_logs"].update_one(
        {"email_id": email_id},
        {"$set": {
            "client_email_sent": client_schedule_success,
            "client_interview_email_id": client_schedule_result.get("email_id") or "",
            "interview_scheduled": overall_success,
            "updated_at": now,
        }},
    )

    # The replacement is now delivered to both parties.  Only at this point
    # may the old calendar invite be cancelled, preventing a gap with no
    # usable meeting link if Calendar or SMTP fails.
    superseded_event_result: Dict[str, Any] = {}
    if is_reschedule_selection and overall_success and existing:
        previous_event_id = _clean(existing.get("calendar_event_id") or trainer.get("calendar_event_id"))
        replacement_event_id = _clean(calendar_event.get("event_id"))
        if previous_event_id and previous_event_id != replacement_event_id:
            superseded_event_result = await cancel_google_calendar_event(previous_event_id)
            superseded_fields: Dict[str, Any] = {
                "superseded_by_email_id": email_id,
                "superseded_by_calendar_event_id": replacement_event_id,
                "superseded_at": now,
                "interview_scheduled": False,
                "updated_at": now,
            }
            if superseded_event_result.get("success"):
                superseded_fields.update({
                    "status": "cancelled",
                    "calendar_cancelled_at": now,
                })
            else:
                superseded_fields["calendar_cancel_error"] = _clean(
                    superseded_event_result.get("error") or "Calendar cancellation failed"
                )
            await db["email_logs"].update_one(
                {"email_id": existing.get("email_id")},
                {"$set": superseded_fields},
            )

    update_fields = {
        "top_trainers.$.pipeline_status": "interview_scheduled" if overall_success else "slot_booked",
        "top_trainers.$.slot_status": (
            "confirmed_by_client"
            if overall_success
            else ("client_interview_send_failed" if success else "trainer_interview_send_failed")
        ),
        "top_trainers.$.slot_reply_at": now,
        "top_trainers.$.slot_confirmed_at": now if overall_success else None,
        "top_trainers.$.slot_reply_text": reply_text,
        "top_trainers.$.client_slots_sent": True,
        "top_trainers.$.mail4_email_id": email_id if success else "",
        "top_trainers.$.client_mail4_email_id": client_schedule_result.get("email_id") if client_schedule_success else "",
        "top_trainers.$.mail4_sent_at": now if success else None,
        "top_trainers.$.client_mail4_sent_at": now if client_schedule_success else None,
        "top_trainers.$.interview_scheduled_at": now if overall_success else None,
        "top_trainers.$.interview_date": interview_date,
        "top_trainers.$.interview_link": meeting_link if (success or client_schedule_success) else "",
        "top_trainers.$.meet_link": meeting_link if (success or client_schedule_success) else "",
        "top_trainers.$.calendar_event": calendar_event if (success or client_schedule_success) else {},
        "top_trainers.$.calendar_event_id": calendar_event.get("event_id") if (success or client_schedule_success) else "",
        "top_trainers.$.google_meet_error": "" if (success or client_schedule_success) else (calendar_event.get("error") or ""),
        "top_trainers.$.client_email_sent": client_schedule_success,
        "top_trainers.$.trainer_email_sent": bool(success),
        "top_trainers.$.reschedule_requested": False if overall_success else trainer.get("reschedule_requested", False),
        "top_trainers.$.reschedule_completed_at": now if overall_success and trainer.get("reschedule_requested") else trainer.get("reschedule_completed_at"),
        "top_trainers.$.superseded_calendar_event_id": (
            _clean(existing.get("calendar_event_id")) if is_reschedule_selection and existing else ""
        ),
        "top_trainers.$.superseded_calendar_cancelled": bool(superseded_event_result.get("success")) if superseded_event_result else False,
        "top_trainers.$.superseded_calendar_cancel_error": _clean(superseded_event_result.get("error")) if superseded_event_result else "",
        "top_trainers.$.last_mail_type": "mail4" if overall_success else "mail3",
        "top_trainers.$.last_mail_type_attempted": "mail4",
        "top_trainers.$.last_mail_attempted_at": now,
        "top_trainers.$.last_mailed_at": now if overall_success else None,
        "top_trainers.$.last_mail_error": (
            ""
            if overall_success
            else (client_schedule_result.get("error") or error or "Interview schedule email failed")
        ),
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if client_slots_email_id:
        update_fields["top_trainers.$.client_slots_email_id"] = client_slots_email_id
    if client_slots_sent_at:
        update_fields["top_trainers.$.client_slots_sent_at"] = client_slots_sent_at
    if not overall_success:
        update_fields["top_trainers.$.last_mail_error"] = client_schedule_result.get("error") or error or "Interview schedule email failed"

    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": update_fields},
    )

    return {
        "attempted": True,
        "success": overall_success,
        "error": "" if overall_success else (client_schedule_result.get("error") or error or "Interview schedule email failed"),
        "email_id": email_id,
        "client_email_id": client_schedule_result.get("email_id") or "",
        "to": trainer_email,
        "client_to": client_email,
        "subject": message["subject"],
        "intent": intent,
        "slot_text": reply_text,
        "interview_link": meeting_link if overall_success else "",
        "calendar_event": calendar_event,
        "sent_at": now if overall_success else None,
    }


async def _auto_request_client_po(
    db: AsyncIOMotorDatabase,
    *,
    requirement_id: str,
    trainer_id: str,
) -> Dict[str, Any]:
    if not requirement_id:
        return {"attempted": False, "reason": "missing_requirement_id"}

    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
    if not requirement:
        return {"attempted": True, "success": False, "reason": "requirement_not_found"}
    if requirement.get("client_po_requested"):
        return {"attempted": True, "skipped": True, "reason": "po_already_requested"}

    prior_po = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "requirement_id": requirement_id,
            "mail_type": "client_po_request",
            "status": "sent",
        },
        {"_id": 0, "email_id": 1},
    )
    if prior_po:
        now = _now()
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": {"client_po_requested": True, "client_po_requested_at": now, "updated_at": now}},
        )
        return {"attempted": True, "skipped": True, "reason": "po_request_already_sent", "email_id": prior_po.get("email_id")}

    client_email = (
        requirement.get("client_email")
        or requirement.get("from_email")
        or requirement.get("requester_email")
        or ""
    )
    if not client_email:
        return {"attempted": True, "success": False, "reason": "missing_client_email"}

    trainer_name = ""
    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0, "top_trainers": 1})
    for trainer in (shortlist or {}).get("top_trainers", []):
        if str(trainer.get("trainer_id") or "") == str(trainer_id or ""):
            trainer_name = trainer.get("name") or trainer.get("trainer_name") or ""
            break

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await _post_with_local_fallback(
                client,
                f"{CORE_API_URL}/api/v1/requirements/{requirement_id}/request-client-po",
                json={
                    "client_email": client_email,
                    "client_name": requirement.get("client_name") or requirement.get("client_company") or "",
                    "trainer_id": trainer_id,
                    "trainer_name": trainer_name,
                    "training_dates": requirement.get("training_dates") or requirement.get("timeline_start") or "",
                },
            )
        return {
            "attempted": True,
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "body": response.text[:500],
        }
    except Exception as exc:
        logger.exception("Failed to auto-request client PO for %s/%s", requirement_id, trainer_id)
        return {"attempted": True, "success": False, "error": str(exc)}


async def _handle_client_selection_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """Detect explicit client 'selection' replies and mark the shortlist entry selected.

    Looks for phrases like 'we have selected', 'we selected', 'you have been selected',
    and updates the matching `top_trainers` element to `selected: True` and `pipeline_status: selected`.
    """
    subject = str(email_doc.get("subject") or "")
    body = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    text = (subject + "\n" + body).lower()
    patterns = [
        r"\bwe have selected\b",
        r"\bwe selected\b",
        r"\bhe is selected\b",
        r"\bshe is selected\b",
        r"\btrainer is selected\b",
        r"\bselected the trainer\b",
        r"\byou have been selected\b",
        r"\btrainer selected\b",
        r"\bfinali[sz]ed\s+(?:this|the)?\s*trainer\b",
        r"\bgo\s+ahead\s+with\s+(?:this|the)?\s*trainer\b",
    ]
    if not any(re.search(p, text, flags=re.IGNORECASE) for p in patterns):
        return {"attempted": False}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": True, "success": False, "reason": "missing_requirement_or_trainer_link"}

    now = _now()
    update = {
        "top_trainers.$.pipeline_status": "selected",
        "top_trainers.$.selected": True,
        "top_trainers.$.selected_at": now,
        "top_trainers.$.slot_status": "selected_by_client",
        "top_trainers.$.last_mail_type": "mail5_ok",
        "top_trainers.$.last_mail_type_attempted": "mail5_ok",
        "top_trainers.$.last_mail_attempted_at": now,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    await db["shortlists"].update_one({"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id}, {"$set": update})

    shortlist_doc = await db["shortlists"].find_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"_id": 0, "top_trainers.$": 1, "requirement_id": 1},
    ) or {}
    trainer_doc = (shortlist_doc.get("top_trainers") or [{}])[0] or {}
    trainer_email = trainer_doc.get("email") or trainer_doc.get("trainer_email") or email_doc.get("trainer_email") or ""
    trainer_name = trainer_doc.get("name") or trainer_doc.get("trainer_name") or email_doc.get("trainer_name") or "Trainer"
    technology = (
        email_doc.get("technology")
        or email_doc.get("technology_needed")
        or email_doc.get("domain")
        or "training"
    )
    mail5_result: Dict[str, Any]
    if trainer_email:
        message = await compose_mail5_selection(GenericSimpleRequest(name=trainer_name, technology=technology))
        settings_doc = await _load_admin_settings(db)
        smtp_config = settings_doc.get("emailCfg") or None
        message_id_header = generate_message_id()
        success, error = await send_email_async(
            to=trainer_email,
            subject=message["subject"],
            body=message["body"],
            smtp_config=smtp_config,
            message_id_header=message_id_header,
        )
        mail5_email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
        await db["email_logs"].insert_one({
            "email_id": mail5_email_id,
            "direction": "outbound",
            "recipient": trainer_email,
            "to_email": trainer_email,
            "subject": message["subject"],
            "gmail_message_id": message_id_header,
            "message_id_header": message_id_header,
            "body": message["body"],
            "body_snippet": message["body"][:300],
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "mail_type": "mail5_ok",
            "source_email_id": email_doc.get("email_id") or "",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer_name,
            "sent_at": now if success else None,
            "created_at": now,
            "updated_at": now,
        })
        mail5_result = {
            "success": bool(success),
            "email_id": mail5_email_id,
            "to": trainer_email,
            "error": error if not success else "",
        }
    else:
        mail5_result = {
            "success": False,
            "skipped": True,
            "reason": "trainer_email_missing",
            "message": "Trainer selection mail was not sent because trainer email is missing.",
        }

    po_request_result = await _auto_request_client_po(
        db,
        requirement_id=requirement_id,
        trainer_id=trainer_id,
    )

    try:
        email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
        await db["email_logs"].insert_one({
            "email_id": email_id,
            "direction": "inbound",
            "from": email_doc.get("from") or email_doc.get("from_email") or "",
            "from_email": email_doc.get("from_email") or "",
            "to_email": email_doc.get("to_email") or "",
            "subject": subject,
            "body_snippet": body[:300],
            "status": "received",
            "mail_type": "client_selection",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "automation_result": {
                "mail5_result": mail5_result,
                "po_request_result": po_request_result,
            },
            "created_at": now,
            "updated_at": now,
        })
    except Exception:
        pass

    return {
        "attempted": True,
        "success": True,
        "reason": "client_selected",
        "selected_at": now,
        "mail5_result": mail5_result,
        "po_request_result": po_request_result,
    }


async def _send_trainer_decision_mail(
    db: AsyncIOMotorDatabase,
    *,
    email_doc: Dict[str, Any],
    requirement_id: str,
    trainer_id: str,
    decision: str,
    now: datetime,
) -> Dict[str, Any]:
    shortlist_doc = await db["shortlists"].find_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"_id": 0, "top_trainers.$": 1, "requirement_id": 1},
    ) or {}
    trainer_doc = (shortlist_doc.get("top_trainers") or [{}])[0] or {}
    trainer_email = trainer_doc.get("email") or trainer_doc.get("trainer_email") or email_doc.get("trainer_email") or ""
    trainer_name = trainer_doc.get("name") or trainer_doc.get("trainer_name") or email_doc.get("trainer_name") or "Trainer"
    technology = (
        email_doc.get("technology")
        or email_doc.get("technology_needed")
        or email_doc.get("domain")
        or "training"
    )
    if not trainer_email:
        return {
            "success": False,
            "skipped": True,
            "reason": "trainer_email_missing",
            "message": f"Trainer {decision} mail was not sent because trainer email is missing.",
        }

    payload = GenericSimpleRequest(name=trainer_name, technology=technology)
    if decision == "selected":
        message = await compose_mail5_selection(payload)
        mail_type = "mail5_ok"
    else:
        message = await compose_mail5_rejection(payload)
        mail_type = "mail5_no"

    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message_body,
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    mail5_email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": mail5_email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message_body,
        "body_snippet": message_body[:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": mail_type,
        "source_email_id": email_doc.get("email_id") or "",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    if success:
        await db["email_send_locks"].update_one({"_id": lock_id}, {"$set": {"status": "sent", "sent_at": now}})
    else:
        await db["email_send_locks"].delete_one({"_id": lock_id})
    return {
        "success": bool(success),
        "email_id": mail5_email_id,
        "to": trainer_email,
        "mail_type": mail_type,
        "error": error if not success else "",
    }


async def _advance_to_next_trainer_after_client_rejection(
    db: AsyncIOMotorDatabase,
    *,
    requirement_id: str,
    rejected_trainer_id: str,
) -> Dict[str, Any]:
    """Move to the next ranked viable trainer without repeating Mail 1."""
    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0, "top_trainers": 1}) or {}
    ranked_trainers = shortlist.get("top_trainers") or []
    rejected_index = next(
        (index for index, trainer in enumerate(ranked_trainers) if _clean(trainer.get("trainer_id")) == rejected_trainer_id),
        -1,
    )
    # Preserve shortlist ranking: first try the trainers after the rejected
    # candidate, then any remaining viable candidate if data was reordered.
    ordered = ranked_trainers[rejected_index + 1:] + ranked_trainers[:rejected_index] if rejected_index >= 0 else ranked_trainers
    excluded_stages = {"rejected", "declined", "stopped_selected", "selected", "training_confirmed"}
    candidates = [
        trainer for trainer in ordered
        if _clean(trainer.get("trainer_id")) != rejected_trainer_id
        and _clean(trainer.get("pipeline_status") or trainer.get("status")).lower() not in excluded_stages
        and _clean(trainer.get("email") or trainer.get("trainer_email"))
    ]
    if not candidates:
        return {"attempted": True, "success": False, "reason": "no_next_suitable_trainer"}

    next_trainer = candidates[0]
    next_trainer_id = _clean(next_trainer.get("trainer_id"))
    next_email = _email_address(next_trainer.get("email") or next_trainer.get("trainer_email"))
    existing_mail1 = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "requirement_id": requirement_id,
            "mail_type": {"$in": ["mail1", "first"]},
            "$or": [
                {"trainer_id": next_trainer_id} if next_trainer_id else {"recipient": {"$regex": f"^{re.escape(next_email)}$", "$options": "i"}},
                {"recipient": {"$regex": f"^{re.escape(next_email)}$", "$options": "i"}},
            ],
        },
        {"_id": 0, "email_id": 1, "sent_at": 1},
        sort=[("created_at", -1)],
    )

    now = _now()
    set_fields = {
        "top_trainers.$.next_candidate_after_rejection": True,
        "top_trainers.$.activated_after_rejection_at": now,
        "top_trainers.$.updated_at": now,
        "pipeline_summary.status": "in_progress",
        "pipeline_summary.current_stage": "contacting_next_trainer",
        "updated_at": now,
    }
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": next_trainer_id},
        {"$set": set_fields},
    )
    if existing_mail1:
        # The candidate is already active in the same requirement. Never
        # duplicate an outreach merely because another trainer was rejected.
        return {
            "attempted": True,
            "success": True,
            "already_contacted": True,
            "reason": "next_trainer_already_in_pipeline",
            "trainer_id": next_trainer_id,
            "trainer_name": next_trainer.get("name") or next_trainer.get("trainer_name") or "Trainer",
            "email_id": existing_mail1.get("email_id") or "",
        }

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await _post_with_local_fallback(
                client,
                f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-mail",
                json={
                    "requirement_id": requirement_id,
                    "mail_type": "mail1",
                    "trainer_ids": [next_trainer_id],
                },
            )
            response.raise_for_status()
            result = response.json() or {}
    except Exception as exc:
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": next_trainer_id},
            {"$set": {
                "top_trainers.$.last_mail_error": str(exc),
                "top_trainers.$.updated_at": _now(),
                "updated_at": _now(),
            }},
        )
        return {"attempted": True, "success": False, "reason": "next_trainer_mail1_failed", "error": str(exc), "trainer_id": next_trainer_id}

    sent_count = int(result.get("sent") or 0) if isinstance(result, dict) else 0
    return {
        "attempted": True,
        "success": sent_count > 0,
        "reason": "next_trainer_mail1_sent" if sent_count > 0 else "next_trainer_mail1_not_sent",
        "trainer_id": next_trainer_id,
        "trainer_name": next_trainer.get("name") or next_trainer.get("trainer_name") or "Trainer",
        "result": result,
    }


async def _handle_client_rejection_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    subject = str(email_doc.get("subject") or "")
    body = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    text = (subject + "\n" + body).lower()
    patterns = [
        r"\bnot\s+selected\b",
        r"\bnot\s+shortlisted\b",
        r"\breject(?:ed)?\b",
        r"\bnot\s+suitable\b",
        r"\bnot\s+moving\s+ahead\b",
        r"\bwill\s+not\s+proceed\b",
        r"\bproceed(?:ing)?\s+with\s+another\s+(?:profile|trainer|option)\b",
        r"\bselected\s+another\s+(?:profile|trainer|option)\b",
        r"\bchoose\s+another\s+(?:profile|trainer|option)\b",
        r"\bgo\s+with\s+another\s+(?:profile|trainer|option)\b",
    ]
    if not any(re.search(p, text, flags=re.IGNORECASE) for p in patterns):
        return {"attempted": False}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": True, "success": False, "reason": "missing_requirement_or_trainer_link"}

    now = _now()
    mail5_result = await _send_trainer_decision_mail(
        db,
        email_doc=email_doc,
        requirement_id=requirement_id,
        trainer_id=trainer_id,
        decision="rejected",
        now=now,
    )
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "rejected",
            "top_trainers.$.selected": False,
            "top_trainers.$.rejected_at": now,
            "top_trainers.$.slot_status": "rejected_by_client",
            "top_trainers.$.last_mail_type": "mail5_no",
            "top_trainers.$.last_mail_type_attempted": "mail5_no",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    next_trainer_result = await _advance_to_next_trainer_after_client_rejection(
        db,
        requirement_id=requirement_id,
        rejected_trainer_id=trainer_id,
    )
    return {
        "attempted": True,
        "success": bool(mail5_result.get("success")),
        "reason": "client_rejected",
        "rejected_at": now,
        "mail5_result": mail5_result,
        "next_trainer": next_trainer_result,
    }


async def _handle_client_budget_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    is_budget_thread = (
        source_mail_type == "trainer_commercials_to_client"
        or bool(re.search(r"Trainer Commercials for Approval", subject, flags=re.IGNORECASE))
    )
    if not is_budget_thread:
        return {"attempted": False, "reason": "not_client_budget_thread"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    if not requirement_id or not trainer_id:
        return {"attempted": False, "reason": "missing_requirement_or_trainer_link"}

    reply_text = email_doc.get("classification_body") or email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or ""
    client_budget_amounts = _client_budget_amounts(reply_text)
    if not client_budget_amounts:
        if _client_same_commercial_acceptance(reply_text):
            shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
            requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
            trainer = _find_shortlist_trainer(shortlist, trainer_id)
            if not trainer:
                trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
            if not trainer:
                trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer"}
            current_stage = _clean(trainer.get("pipeline_status") or trainer.get("status")).lower()
            commercial_status = _clean(trainer.get("commercial_status")).lower()
            commercial_approval_stages = {
                "details_received",
                "waiting_reply2",
                "commercial_negotiation",
                "trainer_rate_discussion",
            }
            commercial_approval_statuses = {
                "sent_to_client",
                "pending_client_approval",
                "forwarded_to_client",
                "negotiating_with_trainer",
                "accepted_by_trainer",
            }
            if current_stage not in commercial_approval_stages and commercial_status not in commercial_approval_statuses:
                return {
                    "attempted": True,
                    "success": False,
                    "reason": "invalid_stage_for_client_commercial_approval",
                    "stage": current_stage,
                    "commercial_status": commercial_status,
                    "error": "Client commercial approval reply is not valid for the current trainer stage.",
                }
            toc_result = await _send_next_step_after_commercial_approval(
                db,
                requirement_id,
                trainer_id,
                trainer,
                requirement,
                shortlist,
                source_email_id=email_doc.get("email_id") or "",
                source_gmail_message_id=_current_inbound_message_id(email_doc),
            )
            now = _now()
            await db["shortlists"].update_one(
                {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
                {"$set": {
                    "top_trainers.$.commercial_status": "approved_by_client",
                    "top_trainers.$.client_commercial_approved_at": now,
                    "top_trainers.$.updated_at": now,
                    "updated_at": now,
                }},
            )
            return {
                **toc_result,
                "attempted": True,
                "reason": "client_approved_commercial_toc_requested" if toc_result.get("success") else "client_approved_commercial_toc_failed",
                "client_commercial_acceptance": True,
            }
        return {
            "attempted": True,
            "success": False,
            "reason": "missing_client_budget_or_same_commercial_acceptance",
            "error": "No commercial amount or same-commercial acceptance found.",
        }
    client_budget = max(client_budget_amounts)
    unit = _commercial_unit(reply_text)
    target_amount = _trainer_rate_from_client_budget(client_budget)
    if target_amount <= 0:
        return {"attempted": True, "success": False, "reason": "invalid_target_rate", "error": "Client budget is too low to calculate trainer rate"}

    source_email_id = email_doc.get("email_id")
    source_commercial_email_id = email_doc.get("source_outbound_email_id") or ""
    source_gmail_message_id = _current_inbound_message_id(email_doc)
    existing_filters: List[Dict[str, Any]] = []
    if source_email_id:
        existing_filters.append({"source_email_id": source_email_id})
    if source_commercial_email_id:
        existing_filters.append({"source_client_commercial_email_id": source_commercial_email_id})
    if source_gmail_message_id:
        existing_filters.append({"source_gmail_message_id": source_gmail_message_id})
    existing_filters.append({"client_budget": client_budget, "trainer_target_rate": target_amount})
    existing = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "commercial_negotiation",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "$or": existing_filters,
        },
        {"_id": 0, "email_id": 1, "sent_at": 1, "recipient": 1, "to_email": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        now = existing.get("sent_at") or _now()
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {
                "$set": {
                    "top_trainers.$.pipeline_status": "waiting_reply2",
                    "top_trainers.$.last_mail_type": "commercial_negotiation",
                    "top_trainers.$.last_mail_type_attempted": "commercial_negotiation",
                    "top_trainers.$.last_mail_attempted_at": now,
                    "top_trainers.$.last_mailed_at": now,
                    "top_trainers.$.last_mail_error": "",
                    "top_trainers.$.commercial_status": "negotiating_with_trainer",
                    "top_trainers.$.client_budget_amount": client_budget,
                    "top_trainers.$.trainer_target_rate": target_amount,
                    "top_trainers.$.commercial_negotiation_sent_at": now,
                    "top_trainers.$.updated_at": now,
                    "updated_at": now,
                }
            },
        )
        return {
            "attempted": True,
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to": existing.get("to_email") or existing.get("recipient"),
            "client_budget": client_budget,
            "trainer_target_rate": target_amount,
            "unit": unit,
        }

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer"}
    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email"))
    if not trainer_email:
        return {"attempted": True, "success": False, "reason": "missing_trainer_email", "error": "Trainer email missing"}

    commercial_log = await _latest_client_commercial_log(db, email_doc, requirement_id, trainer_id)
    client_rate_amounts = _trainer_commercial_amounts((commercial_log or {}).get("body") or (commercial_log or {}).get("body_snippet") or "")
    client_rate = max(client_rate_amounts) if client_rate_amounts else 0
    message = _trainer_budget_negotiation_message(trainer, requirement, shortlist, client_budget, target_amount, unit)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "commercial_negotiation",
        "source_email_id": source_email_id,
        "source_gmail_message_id": source_gmail_message_id,
        "source_client_commercial_email_id": (commercial_log or {}).get("email_id") or "",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
        "client_budget": client_budget,
        "client_rate": client_rate,
        "trainer_target_rate": target_amount,
        "commercial_unit": unit,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })

    set_fields = {
        "top_trainers.$.pipeline_status": "waiting_reply2" if success else "details_received",
        "top_trainers.$.last_mail_type_attempted": "commercial_negotiation",
        "top_trainers.$.last_mail_attempted_at": now,
        "top_trainers.$.commercial_status": "negotiating_with_trainer" if success else "negotiation_send_failed",
        "top_trainers.$.client_budget_amount": client_budget,
        "top_trainers.$.trainer_target_rate": target_amount,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if success:
        set_fields.update({
            "top_trainers.$.last_mail_type": "commercial_negotiation",
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.commercial_negotiation_sent_at": now,
        })
    else:
        set_fields["top_trainers.$.last_mail_error"] = error or "Commercial negotiation email failed"

    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": set_fields},
    )

    return {
        "attempted": True,
        "success": success,
        "error": error or "",
        "email_id": email_id,
        "to": trainer_email,
        "subject": message["subject"],
        "client_budget": client_budget,
        "client_rate": client_rate,
        "trainer_target_rate": target_amount,
        "unit": unit,
    }


async def _set_trainer_commercial_forward_status(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    trainer_id: str,
    status: str,
    error: str = "",
    sent_at: Optional[datetime] = None,
) -> None:
    if not requirement_id or not trainer_id:
        return
    now = sent_at or _now()
    shortlist = await db["shortlists"].find_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"_id": 0, "top_trainers.$": 1},
    ) or {}
    current_trainer = (shortlist.get("top_trainers") or [{}])[0]
    current_stage = str(current_trainer.get("pipeline_status") or "")
    commercial_forward_terminal_stages = {
        "slot_booked",
        "interview_scheduled",
        "selected",
        "toc_requested",
        "toc_received_pending",
        "training_confirmed",
        "po_requested",
        "client_po_received",
        "invoice_generated",
        "invoice_sent",
    }
    preserve_pipeline_stage = current_stage in commercial_forward_terminal_stages
    set_fields = {
        "top_trainers.$.commercial_status": status,
        "top_trainers.$.client_commercial_forward_status": status,
        "top_trainers.$.client_commercial_forward_error": error,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if not preserve_pipeline_stage:
        set_fields["top_trainers.$.pipeline_status"] = "details_received"
    if status == "sent_to_client" and not preserve_pipeline_stage:
        set_fields.update({
            "top_trainers.$.last_mail_type": "trainer_commercials_to_client",
            "top_trainers.$.last_mail_type_attempted": "trainer_commercials_to_client",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mailed_at": now,
            "top_trainers.$.last_mail_error": "",
            "top_trainers.$.client_commercial_sent": True,
            "top_trainers.$.client_commercial_sent_at": now,
        })
    elif error:
        set_fields.update({
            "top_trainers.$.last_mail_type_attempted": "trainer_commercials_to_client",
            "top_trainers.$.last_mail_attempted_at": now,
            "top_trainers.$.last_mail_error": error,
        })
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": set_fields},
    )


async def _forward_trainer_commercials_to_client(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    scenario = str(classification.get("scenario") or email_doc.get("office_mail_category") or "").strip().lower()
    trainer_reply_scenarios = {"trainer_details_sent", "trainer_commercials_sent"}
    reply_text = email_doc.get("classification_body") or email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or ""
    amounts = _trainer_commercial_amounts(reply_text)
    if scenario not in trainer_reply_scenarios and not amounts:
        return {"attempted": False, "reason": "not_trainer_commercial_reply"}

    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    trainer_email = _email_address(email_doc.get("from_email"))
    if not requirement_id or not trainer_id:
        return {"attempted": False, "reason": "missing_requirement_or_trainer_link"}

    existing = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "trainer_commercials_to_client",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0, "email_id": 1, "sent_at": 1, "recipient": 1, "to_email": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
        trainer = _find_shortlist_trainer(shortlist, trainer_id)
        if not trainer:
            trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
        if not trainer:
            trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer", "email": trainer_email}
        comparable_amounts = amounts or _trainer_profile_commercial_amounts(trainer)
        if _trainer_commercial_matches_requirement(comparable_amounts, requirement):
            mail3_result = await _send_next_step_after_commercial_approval(
                db,
                requirement_id,
                trainer_id,
                trainer,
                requirement,
                shortlist,
                source_email_id=email_doc.get("email_id") or "",
                source_gmail_message_id=_current_inbound_message_id(email_doc),
            )
        else:
            mail3_result = {"success": False, "skipped": True, "reason": "waiting_for_client_commercial_approval"}
        await _set_trainer_commercial_forward_status(
            db,
            requirement_id,
            trainer_id,
            "sent_to_client",
            sent_at=existing.get("sent_at") or _now(),
        )
        return {
            "attempted": True,
            "success": True,
            "already_sent": True,
            "email_id": existing.get("email_id"),
            "to": existing.get("to_email") or existing.get("recipient"),
            "mail3": mail3_result,
        }

    recent_failed = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "failed",
            "mail_type": "trainer_commercials_to_client",
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        },
        {"_id": 0, "email_id": 1, "created_at": 1, "error_message": 1, "recipient": 1, "to_email": 1},
        sort=[("created_at", -1)],
    )
    if recent_failed:
        failed_at = recent_failed.get("created_at") or _now()
        error_text = str(recent_failed.get("error_message") or "")
        if "quota" in error_text.lower() and failed_at > _now() - timedelta(hours=24):
            await _set_trainer_commercial_forward_status(
                db,
                requirement_id,
                trainer_id,
                "send_failed",
                error_text,
                failed_at,
            )
            return {
                "attempted": True,
                "success": False,
                "already_failed": True,
                "reason": "gmail_quota_cooldown",
                "email_id": recent_failed.get("email_id"),
                "to": recent_failed.get("to_email") or recent_failed.get("recipient"),
                "error": error_text,
                "retry_after": failed_at + timedelta(hours=24),
            }

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer", "email": trainer_email}

    if not amounts:
        fallback_amounts = _trainer_profile_commercial_amounts(trainer)
        if fallback_amounts:
            amounts = fallback_amounts
    if not amounts:
        fallback_amounts = _trainer_budget_amounts_from_requirement(requirement)
        if fallback_amounts:
            amounts = fallback_amounts

    if not amounts:
        error = "Trainer details received, but no commercial amount was found."
        await _set_trainer_commercial_forward_status(db, requirement_id, trainer_id, "waiting_for_commercials", error)
        return {"attempted": True, "success": False, "reason": "missing_commercial_amount", "error": error}

    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not client_email:
        error = "Client email missing; trainer commercials were not sent to client."
        await _set_trainer_commercial_forward_status(db, requirement_id, trainer_id, "missing_client_email", error)
        return {"attempted": True, "success": False, "reason": "missing_client_email", "error": error}

    client_rates = [_client_rate_for_trainer_quote(amount, requirement) for amount in amounts]
    message = _trainer_commercial_body(requirement, shortlist, trainer, client_rates)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = generate_message_id()
    success, error = await send_email_async(
        to=client_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
        message_id_header=message_id_header,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
        "gmail_message_id": message_id_header,
        "message_id_header": message_id_header,
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "trainer_commercials_to_client",
        "source_email_id": email_doc.get("email_id"),
        "source_gmail_message_id": _current_inbound_message_id(email_doc),
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
        "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
        "client_email": client_email,
        "sent_at": now if success else None,
        "created_at": now,
        "updated_at": now,
    })
    if success:
        await _set_trainer_commercial_forward_status(db, requirement_id, trainer_id, "sent_to_client", sent_at=now)
        if _trainer_commercial_matches_requirement(amounts, requirement):
            mail3_result = await _send_next_step_after_commercial_approval(
                db,
                requirement_id,
                trainer_id,
                trainer,
                requirement,
                shortlist,
                source_email_id=email_doc.get("email_id") or "",
                source_gmail_message_id=_current_inbound_message_id(email_doc),
            )
        else:
            mail3_result = {"success": False, "skipped": True, "reason": "waiting_for_client_commercial_approval"}
    else:
        mail3_result = {"success": False, "reason": "commercial_forward_failed"}
        await _set_trainer_commercial_forward_status(
            db,
            requirement_id,
            trainer_id,
            "send_failed",
            error or "Email delivery failed",
            now,
        )
    return {
        "attempted": True,
        "success": success,
        "error": error or "",
        "email_id": email_id,
        "to": client_email,
        "subject": message["subject"],
        "client_rates": client_rates,
        "mail3": mail3_result,
    }


async def _send_client_auto_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    reply: Dict[str, str],
    requirement_id: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    mail_type_override: str = "",
) -> Dict[str, Any]:
    send_settings = await _auto_send_settings(db)
    if not send_settings["enabled"]:
        return {"success": False, "error": "Auto-send is disabled"}

    risk_reason = _auto_send_risk_reason(email_doc)
    if risk_reason:
        return {
            "success": False,
            "error": "Auto-send blocked by deterministic safety rule",
            "blocked": True,
            "reason": risk_reason,
        }

    source_mail_type_guard = _clean(email_doc.get("source_outbound_mail_type") or "").lower()
    classification_guard = email_doc.get("email_classification") or {}
    scenario_guard = _clean(classification_guard.get("scenario") or email_doc.get("office_mail_category") or "").lower()
    person_type_guard = _clean(classification_guard.get("person_type")).lower()
    is_trainer_thread = bool(
        email_doc.get("trainer_id")
        or person_type_guard == "trainer"
        or scenario_guard.startswith("trainer_")
        or source_mail_type_guard in {
            "mail1",
            "mail1_reminder",
            "mail1_toc_correction",
            "mail2",
            "mail2_followup",
            "mail3",
            "mail3_slot_booking",
            "mail3_slot_followup",
            "mail3_too_many_slots",
            "mail3_too_few_slots",
            "commercial_negotiation",
        }
    )
    reply_body_preview = (reply.get("body") or "").lower()
    looks_like_client_ack = (
        "thank you for sharing the" in reply_body_preview
        and "training requirement" in reply_body_preview
        and "share suitable trainer profiles" in reply_body_preview
    )
    if is_trainer_thread and looks_like_client_ack:
        return {
            "success": False,
            "error": "Blocked client acknowledgement on trainer thread",
            "blocked": True,
            "reason": "client_ack_on_trainer_thread",
        }

    to = _email_address(email_doc.get("from_email"))
    body = reply.get("body") or ""
    subject = reply.get("subject") or email_doc.get("subject") or "Training Requirement"
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    if not to:
        return {"success": False, "error": "No recipient address available"}
    if _is_obvious_non_client_email(to, email_doc.get("subject") or "", email_doc.get("body") or ""):
        return {"success": False, "error": f"Recipient is an automated/bulk sender: {to}"}
    if not body:
        return {"success": False, "error": "No reply body available"}

    effective_requirement_id = requirement_id or email_doc.get("requirement_id") or ""
    classification = email_doc.get("email_classification") or {}
    scenario = str(classification.get("scenario") or email_doc.get("office_mail_category") or "").strip().lower()
    person_type = str(classification.get("person_type") or "").strip().lower()
    if person_type == "trainer" or scenario.startswith("trainer_"):
        has_shortlist_link = bool(effective_requirement_id and email_doc.get("trainer_id"))
        mail_type = "mail2" if scenario == "trainer_interested" and has_shortlist_link else "trainer_auto_reply"
    elif person_type == "corporate_client" or scenario.startswith("client_"):
        mail_type = "client_auto_reply"
    else:
        mail_type = "office_auto_reply"
    if _clean(mail_type_override):
        mail_type = _clean(mail_type_override).lower()

    if mail_type == "mail2" and effective_requirement_id and email_doc.get("trainer_id"):
        trainer_reply_text = (
            email_doc.get("classification_body")
            or email_doc.get("clean_body")
            or email_doc.get("raw_body")
            or email_doc.get("body")
            or ""
        )
        requirement_doc = await db["requirements"].find_one(
                {"requirement_id": effective_requirement_id},
                {"_id": 0},
            ) or {}
        shortlist_doc = await db["shortlists"].find_one(
            {"requirement_id": effective_requirement_id, "top_trainers.trainer_id": email_doc.get("trainer_id")},
            {"_id": 0, "top_trainers.$": 1, "client_email": 1, "client_name": 1, "technology_needed": 1},
        ) or {}
        current_trainer = (shortlist_doc.get("top_trainers") or [{}])[0] or {}
        evidence_doc = _trainer_detail_evidence_doc(email_doc, current_trainer)
        evidence_text = evidence_doc.get("classification_body") or trainer_reply_text
        if _trainer_reply_has_requested_details(evidence_text, requirement_doc, evidence_doc):
            await _mark_shortlist_trainer_reply_received(
                db,
                {
                    **email_doc,
                    "classification_body": _strip_quoted_email_history(trainer_reply_text) or trainer_reply_text,
                    "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
                    "office_mail_category": "trainer_details_sent",
                },
                stage="mail1",
                status="details_received",
                reply_at=_now(),
            )
            mail3_result = await _send_trainer_mail3_if_missing(
                db,
                effective_requirement_id,
                email_doc.get("trainer_id"),
                current_trainer,
                requirement_doc,
                shortlist_doc,
                source_email_id=email_doc.get("email_id") or "",
                source_gmail_message_id=_current_inbound_message_id(email_doc),
            )
            return {
                "success": bool(mail3_result.get("success")),
                "error": "" if mail3_result.get("success") else mail3_result.get("error", mail3_result.get("reason", "Mail 3 send failed")),
                "skipped_mail2": True,
                "reason": "trainer_details_already_shared_mail3_sent",
                "mail3": mail3_result,
                "to": current_trainer.get("email") or current_trainer.get("trainer_email") or to,
                "subject": (mail3_result or {}).get("subject") or "Interview Slot Booking",
                "body": (mail3_result or {}).get("body") or "",
                "source_gmail_message_id": _current_inbound_message_id(email_doc),
            }
        # Mail 2 used to be a generic request for CV, LinkedIn and other
        # details.  That is no longer a valid outbound stage: Mail 1 asks
        # only for details absent from the stored trainer record, then the
        # trainer's slots are sent to the client.  Do not revive the old
        # behaviour when a legacy caller reaches this generic send helper.
        return {
            "success": False,
            "blocked": True,
            "reason": "legacy_mail2_detail_request_blocked",
            "error": "Trainer details are incomplete; record for review instead of sending a generic Mail 2 request.",
            "to": to,
            "subject": subject,
            "body": body,
            "source_gmail_message_id": _current_inbound_message_id(email_doc),
        }

    client_template_marker = ""
    if mail_type == "client_auto_reply":
        client_template_marker = (
            "We have noted that you will share the remaining details later."
            if "We have noted that you will share the remaining details later." in body
            else "Thank you for sharing the complete details"
            if "Thank you for sharing the complete details" in body
            else "Thank you for sharing the required details."
            if "Thank you for sharing the required details." in body
            else "Thank you for sharing the required details for your training requirement."
            if "Thank you for sharing the required details for your training requirement." in body
            else ""
        )

    source_gmail_message_id = _current_inbound_message_id(email_doc)
    duplicate_terms = []
    if source_gmail_message_id:
        duplicate_terms.append({"source_gmail_message_id": source_gmail_message_id})
    elif email_doc.get("email_id"):
        duplicate_terms.append({"source_email_id": email_doc.get("email_id")})
    existing_sent_log = None
    duplicate_query = None
    if duplicate_terms:
        duplicate_mail_types = (
            ["client_auto_reply", "client_reply"]
            if mail_type == "client_auto_reply"
            else ["trainer_auto_reply", "mail2"] if mail_type in {"trainer_auto_reply", "mail2"}
            else ["office_auto_reply"] if mail_type == "office_auto_reply"
            else [mail_type]
        )
        duplicate_query = {
            "mail_type": {"$in": duplicate_mail_types},
            "status": "sent",
            "$and": [
                {"$or": [{"to_email": to}, {"recipient": to}]},
                {"$or": duplicate_terms},
            ],
        }
        if mail_type == "client_auto_reply" and client_template_marker:
            duplicate_query["body"] = {"$regex": re.escape(client_template_marker), "$options": "i"}
        existing_sent_log = await db["email_logs"].find_one(
            duplicate_query,
            {"_id": 0, "sent_at": 1, "created_at": 1, "body": 1},
        )
    if existing_sent_log:
        sent_at = existing_sent_log.get("sent_at") or existing_sent_log.get("created_at") or _now()
        if mail_type == "mail2":
            if duplicate_query:
                await db["email_logs"].update_many(
                    duplicate_query,
                    {
                        "$set": {
                            "mail_type": "mail2",
                            "requirement_id": effective_requirement_id,
                            "trainer_id": email_doc.get("trainer_id") or "",
                            "trainer_name": email_doc.get("trainer_name") or "",
                            "updated_at": _now(),
                        }
                    },
                )
            await _mark_shortlist_pipeline_mail_sent(db, email_doc, "mail2", sent_at, effective_requirement_id)
        return {
            "success": True,
            "error": "",
            "already_sent": True,
            "to": to,
            "subject": subject,
            "body": existing_sent_log.get("body") or body,
            "sent_at": sent_at,
            "source_gmail_message_id": source_gmail_message_id,
        }

    if (
        mail_type == "client_auto_reply"
        and client_template_marker
        and effective_requirement_id
    ):
        requirement_sent_log = await db["email_logs"].find_one(
            {
                "mail_type": {"$in": ["client_auto_reply", "client_reply"]},
                "status": "sent",
                "requirement_id": effective_requirement_id,
                "$and": [
                    {"$or": [{"to_email": to}, {"recipient": to}]},
                    {"body": {"$regex": re.escape(client_template_marker), "$options": "i"}},
                ],
            },
            {"_id": 0, "sent_at": 1, "created_at": 1, "body": 1, "subject": 1},
        )
        if requirement_sent_log:
            sent_at = requirement_sent_log.get("sent_at") or requirement_sent_log.get("created_at") or _now()
            return {
                "success": True,
                "error": "",
                "already_sent": True,
                "reason": "client_template_already_sent_for_requirement",
                "to": to,
                "subject": requirement_sent_log.get("subject") or subject,
                "body": requirement_sent_log.get("body") or body,
                "sent_at": sent_at,
                "source_gmail_message_id": source_gmail_message_id,
            }

    if mail_type == "mail2" and effective_requirement_id and email_doc.get("trainer_id"):
        existing_mail2 = await db["email_logs"].find_one(
            {
                "direction": "outbound",
                "status": "sent",
                "mail_type": "mail2",
                "requirement_id": effective_requirement_id,
                "trainer_id": email_doc.get("trainer_id"),
            },
            {"_id": 0, "sent_at": 1, "created_at": 1, "email_id": 1, "recipient": 1, "to_email": 1, "subject": 1},
            sort=[("created_at", -1)],
        )
        if existing_mail2:
            sent_at = existing_mail2.get("sent_at") or existing_mail2.get("created_at") or _now()
            await _mark_shortlist_pipeline_mail_sent(db, email_doc, "mail2", sent_at, effective_requirement_id)
            return {
                "success": True,
                "error": "",
                "already_sent": True,
                "to": existing_mail2.get("to_email") or existing_mail2.get("recipient") or to,
                "subject": existing_mail2.get("subject") or subject,
                "body": body,
                "sent_at": sent_at,
                "source_gmail_message_id": source_gmail_message_id,
            }

    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    message_id_header = generate_message_id()
    send_lock_id = ""
    if source_gmail_message_id:
        send_lock_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mail_type}|{to}|{source_gmail_message_id}"))
        try:
            await db["email_send_locks"].insert_one({
                "_id": send_lock_id,
                "mail_type": mail_type,
                "recipient": to,
                "source_gmail_message_id": source_gmail_message_id,
                "status": "sending",
                "created_at": _now(),
            })
        except DuplicateKeyError:
            return {
                "success": True,
                "error": "",
                "already_sent": True,
                "already_sending": True,
                "to": to,
                "subject": subject,
                "body": body,
                "source_gmail_message_id": source_gmail_message_id,
            }
    success, error = await send_email_async(
        to=to,
        subject=subject,
        body=body,
        smtp_config=smtp_config,
        attachments=attachments or None,
        message_id_header=message_id_header,
    )
    now = _now()
    if send_lock_id:
        if success:
            await db["email_send_locks"].update_one(
                {"_id": send_lock_id},
                {"$set": {"status": "sent", "sent_at": now, "updated_at": now}},
            )
        else:
            await db["email_send_locks"].delete_one({"_id": send_lock_id})
    if success:
        await db["email_logs"].insert_one({
            "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
            "direction": "outbound",
            "recipient": to,
            "to_email": to,
            "subject": subject,
            "gmail_message_id": message_id_header,
            "message_id_header": message_id_header,
            "body": body,
            "body_snippet": body[:300],
            "status": "sent",
            "mail_type": mail_type,
            "reply_template_key": email_doc.get("reply_template_key") or "",
            "source_email_id": email_doc.get("email_id"),
            "source_gmail_message_id": source_gmail_message_id,
            "requirement_id": effective_requirement_id,
            "trainer_id": email_doc.get("trainer_id") or "",
            "trainer_name": email_doc.get("trainer_name") or "",
            "attachments": [item.get("filename", "") for item in (attachments or [])],
            "sent_at": now,
            "created_at": now,
            "updated_at": now,
        })
        await _mark_shortlist_pipeline_mail_sent(db, email_doc, mail_type, now, effective_requirement_id)

    return {
        "success": success,
        "error": error or "",
        "to": to,
        "subject": subject,
        "body": body,
        "attachments": [item.get("filename", "") for item in (attachments or [])],
        "sent_at": now,
        "source_gmail_message_id": source_gmail_message_id,
    }


def _requirement_payload_from_email(email_doc: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    technology = extracted.get("technology_needed") or extracted.get("technology")
    working_days = _safe_int(extracted.get("duration_days"), 0)
    if not working_days:
        working_days = _training_working_days_from_dates(
        extracted.get("training_dates")
        or extracted.get("preferred_dates")
        or " to ".join(part for part in [extracted.get("timeline_start"), extracted.get("timeline_end")] if part)
        )
    client_budget = extracted.get("budget_per_day")
    if client_budget in (None, "", []) and extracted.get("budget_total") not in (None, "", []):
        try:
            total_budget = float(extracted.get("budget_total"))
            client_budget = total_budget / working_days if working_days else total_budget
        except (TypeError, ValueError):
            client_budget = extracted.get("budget_total")
    trainer_share = 0.70
    trainer_budget = None
    if client_budget not in (None, "", []):
        try:
            raw_trainer_budget = max(float(client_budget) * trainer_share, 0)
            if raw_trainer_budget > 0:
                trainer_budget = _trainer_rate_from_client_budget(float(client_budget))
            else:
                trainer_budget = None
        except (TypeError, ValueError):
            trainer_budget = None
    source_text = " ".join([
        str(extracted.get("experience") or ""),
        str(extracted.get("experience_years") or ""),
        str(extracted.get("min_experience_years") or ""),
        str(email_doc.get("classification_body") or ""),
        str(email_doc.get("clean_body") or ""),
        str(email_doc.get("raw_body") or ""),
        str(email_doc.get("body") or ""),
    ])
    min_experience_years = _safe_int(extracted.get("min_experience_years") or extracted.get("experience_years"), 0)
    if not min_experience_years:
        exp_match = re.search(
            r"\b(?:minimum|min\.?|at\s+least|required|require|need|needs|with|above)?\s*(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)?\b",
            source_text,
            flags=re.IGNORECASE,
        )
        if exp_match:
            min_experience_years = _safe_int(exp_match.group(1), 0)
    client_requirement_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    flow_type = _requirement_flow_from_email(extracted, client_requirement_text)
    return {
        "title": f"{technology} Trainer",
        "technology_needed": technology,
        "domain": technology,
        "required_skills": extracted.get("required_skills") or [technology],
        "mode": extracted.get("mode"),
        "audience_level": extracted.get("audience_level"),
        "duration_days": extracted.get("duration_days"),
        "duration_hours": extracted.get("duration_hours"),
        "duration_text": extracted.get("duration_text"),
        "timing": extracted.get("timing"),
        "preferred_dates": extracted.get("preferred_dates"),
        "training_dates": extracted.get("training_dates"),
        "timeline_start": extracted.get("timeline_start"),
        "timeline_end": extracted.get("timeline_end"),
        "budget": extracted.get("budget_total") or extracted.get("budget_per_day"),
        "budget_total": extracted.get("budget_total"),
        "budget_per_day": extracted.get("budget_per_day"),
        "client_budget_per_day": client_budget,
        "trainer_visible_budget_per_session": trainer_budget,
        "trainer_requested_budget_per_session": trainer_budget,
        "trainer_commercial_includes_tds": True if trainer_budget else False,
        "commercial_working_days": working_days or None,
        "commercial_calculation": (
            "total_70_percent_below_10000_per_day"
            if client_budget not in (None, "", []) and float(client_budget) < 10000
            else "total_budget_divided_by_training_days"
            if extracted.get("budget_total") and working_days
            else "per_day_70_percent"
            if extracted.get("budget_per_day")
            else ""
        ),
        "min_experience_years": min_experience_years or None,
        "budget_min": extracted.get("budget_min"),
        "budget_max": extracted.get("budget_max"),
        "budget_range": extracted.get("budget_range"),
        "budget_currency": extracted.get("budget_currency"),
        "participant_count": extracted.get("participant_count"),
        "hands_on_lab": extracted.get("hands_on_lab"),
        "lab_hours_per_day": extracted.get("lab_hours_per_day"),
        "total_lab_duration_hours": extracted.get("total_lab_duration_hours"),
        "lab_cost_requested": bool(extracted.get("lab_cost_requested")),
        "lab_cost_status": "requested" if extracted.get("lab_cost_requested") else "",
        "lab_required_tools_requested": bool(extracted.get("lab_required_tools_requested")),
        "lab_delivery_preference": extracted.get("lab_delivery_preference"),
        "trainer_cv_approval_requested": bool(extracted.get("trainer_cv_approval_requested")),
        "requirement_items": extracted.get("requirement_items", []),
        "client_domain": extracted.get("client_domain"),
        "client_industry": extracted.get("client_industry"),
        "topics": extracted.get("topics"),
        "custom_topics": extracted.get("custom_topics"),
        "requested_details": extracted.get("requested_details", []),
        "clahan_managed_details": extracted.get("clahan_managed_details", []),
        "toc_requested": extracted.get("toc_requested"),
        "toc_action": extracted.get("toc_action"),
        "scope_attached": extracted.get("scope_attached"),
        "scope_text": extracted.get("scope_text"),
        "attachment_names": email_doc.get("attachment_names") or [],
        "source_attachments": email_doc.get("attachments") or [],
        "client_name": extracted.get("client_name"),
        "client_company": extracted.get("client_company"),
        "client_email": extracted.get("client_email"),
        "requirement_source_text": extracted.get("requirement_source_text"),
        "client_requirement_text": client_requirement_text[:2500],
        "batch_flow": flow_type,
        "batch_type": flow_type,
        "requirement_type": flow_type,
        "training_status": flow_type,
        "top_n": 5,
        "send_emails": True,
        "status": "active",
        "priority": "high" if extracted.get("urgency") == "urgent" else "medium",
        "customer_id": extracted.get("client_email") or "client-inbox",
        "metadata": {
            "source": "client_inbox",
            "source_email_id": email_doc.get("email_id"),
            "gmail_message_id": email_doc.get("gmail_message_id"),
            "latest_gmail_message_id": email_doc.get("latest_gmail_message_id"),
            "gmail_thread_id": email_doc.get("gmail_thread_id") or email_doc.get("thread_id"),
            "original_subject": email_doc.get("subject"),
            "original_body": client_requirement_text[:2500],
            "requirement_source_text": extracted.get("requirement_source_text"),
            "requested_details": extracted.get("requested_details", []),
            "clahan_managed_details": extracted.get("clahan_managed_details", []),
            "lab_cost_requested": bool(extracted.get("lab_cost_requested")),
            "requirement_items": extracted.get("requirement_items", []),
            "toc_requested": extracted.get("toc_requested"),
            "toc_action": extracted.get("toc_action"),
            "scope_attached": extracted.get("scope_attached"),
            "scope_text": extracted.get("scope_text"),
            "attachment_names": email_doc.get("attachment_names") or [],
            "parser": extracted.get("extraction_method"),
        },
    }


def _flow_has_value(value: Any) -> bool:
    text = _clean(value).lower()
    return bool(text) and text not in {
        "to be confirmed",
        "tbc",
        "tbd",
        "na",
        "n/a",
        "not confirmed",
        "not finalized",
        "not finalised",
        "unknown",
    }


def _requirement_flow_from_email(extracted: Dict[str, Any], client_requirement_text: str) -> str:
    explicit = _clean(
        extracted.get("batch_flow")
        or extracted.get("batch_type")
        or extracted.get("requirement_type")
        or extracted.get("training_status")
    ).lower()
    text = f"{client_requirement_text}\n{extracted}".lower()
    # A confirmed batch is only one type of real training request. A sourcing
    # enquiry with multiple core logistics explicitly still TBD is a proposal
    # batch even when the client did not use the word "proposal".
    proposal_signals = (
        "proposal batch",
        "request for proposal",
        "rfp",
        "need a proposal",
        "require a proposal",
        "send a proposal",
        "share a proposal",
        "need quotation",
        "require quotation",
        "send quotation",
        "share quotation",
        "need a quote",
        "request a quote",
    )
    confirmed_signals = (
        "purchase order",
        "po no",
        "program confirmation",
        "confirmed batch",
        "confirmed training batch",
        "confirmed training requirement",
        "requirement is confirmed",
        "confirmed training",
        "training confirmed",
        "we confirm the training",
        "we confirm this training",
        "we confirm the batch",
        "we confirm this batch",
        "we hereby confirm the training",
        "we hereby confirm the batch",
        "we are happy to confirm",
        "we are pleased to confirm",
    )
    # Client confirmation is stronger than an extractor's tentative proposal label.
    if any(signal in text for signal in confirmed_signals):
        return "confirmed"
    # Extractor labels are useful only when they are backed by a clear
    # proposal/quotation request in the client's actual message.  This stops
    # tentative AI extraction from misrouting real confirmed requirements.
    if "proposal" in explicit and any(signal in text for signal in proposal_signals):
        return "proposal"
    if any(signal in text for signal in proposal_signals):
        return "proposal"

    placeholder_patterns = (
        r"\bmode\s*:\s*(?:to\s+be\s+confirmed|tbc|tbd|not\s+confirmed|unknown)",
        r"\bduration\s*:\s*(?:to\s+be\s+confirmed|tbc|tbd|not\s+confirmed|unknown)",
        r"\b(?:location|venue)\s*:\s*(?:to\s+be\s+confirmed|tbc|tbd|not\s+confirmed|unknown)",
        r"\b(?:dates?|schedule)\s*:\s*(?:to\s+be\s+confirmed|tbc|tbd|not\s+confirmed|unknown)",
    )
    unresolved_logistics = sum(
        1 for pattern in placeholder_patterns if re.search(pattern, text, flags=re.IGNORECASE)
    )
    sourcing_signals = (
        "upcoming corporate training",
        "if you have a suitable trainer",
        "share suitable trainer",
        "share the following details",
        "share trainer profiles",
        "trainer profile",
        "commercials (per hour/day)",
    )
    # Two or more unconfirmed core logistics plus a request for profiles or
    # commercials means the client is evaluating options, not confirming a
    # delivery. A clear confirmation above always wins.
    if unresolved_logistics >= 2 and any(signal in text for signal in sourcing_signals):
        return "proposal"
    # Do not let an unknown phrasing start the confirmed-batch workflow.
    # Confirmation has real downstream effects (trainer mail, client handoff,
    # meeting and commercial flow), so it must be explicit in the client's
    # message.  New, incomplete or unfamiliar requirements stay in the safe
    # proposal flow until the client provides an explicit confirmation.
    return "proposal"


async def _update_existing_requirement_from_extracted(
    db: AsyncIOMotorDatabase,
    requirement_id: str,
    extracted: Dict[str, Any],
) -> None:
    if not requirement_id:
        return

    update: Dict[str, Any] = {"updated_at": _now()}
    technology = _clean(
        extracted.get("technology_needed")
        or extracted.get("technology")
        or extracted.get("domain")
    )
    if technology:
        update.update({
            "title": f"{technology} Trainer",
            "technology_needed": technology,
            "domain": technology,
        })
        skills = extracted.get("required_skills") or [technology]
        if skills:
            update["required_skills"] = skills

    optional_fields = (
        "mode",
        "audience_level",
        "duration_days",
        "duration_hours",
        "duration_text",
        "timing",
        "preferred_dates",
        "training_dates",
        "timeline_start",
        "timeline_end",
        "budget_total",
        "budget_per_day",
        "budget_min",
        "budget_max",
        "budget_range",
        "budget_currency",
        "participant_count",
        "hands_on_lab",
        "lab_hours_per_day",
        "total_lab_duration_hours",
        "lab_cost_requested",
        "lab_required_tools_requested",
        "lab_delivery_preference",
        "trainer_cv_approval_requested",
        "requirement_items",
        "client_domain",
        "client_industry",
        "topics",
        "custom_topics",
        "client_name",
        "client_company",
        "client_email",
        "requirement_source_text",
        "client_requirement_text",
        "requested_details",
        "clahan_managed_details",
        "toc_requested",
        "toc_action",
    )
    for field in optional_fields:
        value = extracted.get(field)
        if value not in (None, "", []):
            update[field] = value

    flow_type = _requirement_flow_from_email(extracted, extracted.get("client_requirement_text") or "")
    update.update({
        "batch_flow": flow_type,
        "batch_type": flow_type,
        "requirement_type": flow_type,
        "training_status": flow_type,
    })

    budget = extracted.get("budget_total") or extracted.get("budget_per_day")
    if budget not in (None, "", []):
        update["budget"] = budget

    if len(update) > 1:
        await db["requirements"].update_one(
            {"requirement_id": requirement_id},
            {"$set": update},
        )


async def _find_existing_client_requirement(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not _is_reply_thread(email_doc.get("subject") or "", email_doc):
        return None

    technology = _clean(extracted.get("technology_needed") or extracted.get("technology"))
    client_email = _clean(extracted.get("client_email") or email_doc.get("from_email"))
    if not client_email:
        return None

    status_filter = {"$nin": list(OPEN_REQUIREMENT_EXCLUDED_STATUSES)}
    thread_requirement_id = _clean(email_doc.get("requirement_id"))
    if thread_requirement_id:
        existing = await db["requirements"].find_one(
            {
                "requirement_id": thread_requirement_id,
                "status": status_filter,
            },
            {"_id": 0},
        )
        if existing:
            return existing

    if not technology:
        prior_email = await db["client_emails"].find_one(
            {
                "email_id": {"$ne": email_doc.get("email_id")},
                "from_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
                "requirement_id": {"$exists": True, "$nin": ["", None]},
                "deleted": {"$ne": True},
                "status": {"$nin": ["spam", "rejected"]},
                "reply_status": {"$ne": "deleted"},
            },
            {"_id": 0, "requirement_id": 1, "subject": 1},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if prior_email and _subjects_match_thread(email_doc.get("subject"), prior_email.get("subject")):
            return await db["requirements"].find_one(
                {"requirement_id": prior_email.get("requirement_id"), "status": status_filter},
                {"_id": 0},
            )
        return None

    if not _is_reply_thread(email_doc.get("subject") or "", email_doc):
        return None

    query = {
        "client_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
        "technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
        "status": status_filter,
    }
    existing = await db["requirements"].find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if existing:
        return existing

    source_email_id = email_doc.get("email_id")
    prior_email = await db["client_emails"].find_one(
        {
            "email_id": {"$ne": source_email_id},
            "from_email": {"$regex": f"^{re.escape(client_email)}$", "$options": "i"},
            "extracted.technology_needed": {"$regex": f"^{re.escape(technology)}$", "$options": "i"},
            "requirement_id": {"$exists": True, "$nin": ["", None]},
            "deleted": {"$ne": True},
            "status": {"$ne": "deleted"},
            "reply_status": {"$ne": "deleted"},
        },
        {"_id": 0, "requirement_id": 1},
        sort=[("created_at", -1)],
    )
    if not prior_email:
        return None
    return await db["requirements"].find_one(
        {"requirement_id": prior_email.get("requirement_id"), "status": status_filter},
        {"_id": 0},
    )


async def _create_requirement(
    email_doc: Dict[str, Any],
    extracted: Dict[str, Any],
    db: AsyncIOMotorDatabase,
    reuse_existing_client_requirement: bool = False,
    force_new_requirement: bool = False,
) -> Dict[str, Any]:
    email_id = email_doc.get("email_id")
    deleted_identity_clauses: List[Dict[str, Any]] = []
    if email_id:
        deleted_identity_clauses.append({"source_email_id": email_id})
    gmail_message_id = _clean(email_doc.get("gmail_message_id") or email_doc.get("latest_gmail_message_id") or "")
    if gmail_message_id:
        deleted_identity_clauses.extend([
            {"gmail_message_id": gmail_message_id},
            {"latest_gmail_message_id": gmail_message_id},
            {"thread_message_ids": gmail_message_id},
        ])
    gmail_thread_id = _clean(email_doc.get("gmail_thread_id") or email_doc.get("thread_id") or "")
    if gmail_thread_id:
        deleted_identity_clauses.append({"gmail_thread_id": gmail_thread_id})
    if deleted_identity_clauses and not force_new_requirement:
        deleted_identity = await db["deleted_requirements"].find_one(
            {"$or": deleted_identity_clauses},
            {"_id": 0, "requirement_id": 1, "source_email_id": 1, "client_email": 1},
        )
        if deleted_identity:
            return {
                "requirement_id": "",
                "deleted": True,
                "reason": "requirement_deleted",
                "deleted_requirement_id": deleted_identity.get("requirement_id", ""),
            }

    if email_doc.get("requirement_id") and not force_new_requirement:
        requirement_id = email_doc["requirement_id"]
        deleted_requirement = await db["deleted_requirements"].find_one(
            {"requirement_id": requirement_id},
            {"_id": 0, "requirement_id": 1, "deleted_at": 1},
        )
        if deleted_requirement:
            return {
                "requirement_id": "",
                "deleted": True,
                "reason": "requirement_deleted",
                "deleted_requirement_id": requirement_id,
            }
        existing_requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0})
        if existing_requirement:
            await _update_existing_requirement_from_extracted(db, requirement_id, extracted)
            return {"requirement_id": requirement_id, "existing": True, "requirement": existing_requirement}

        payload = _requirement_payload_from_email(email_doc, extracted)
        payload["requirement_id"] = requirement_id
        return await _create_requirement_via_core_or_db(db, payload)

    existing = await db["requirements"].find_one({"metadata.source_email_id": email_id}, {"_id": 0})
    if existing:
        deleted_requirement = await db["deleted_requirements"].find_one(
            {"requirement_id": existing.get("requirement_id")},
            {"_id": 0, "requirement_id": 1},
        )
        if deleted_requirement:
            if force_new_requirement:
                existing = None
            else:
                return {
                    "requirement_id": "",
                    "deleted": True,
                    "reason": "requirement_deleted",
                    "deleted_requirement_id": existing.get("requirement_id"),
                }
        if existing:
            await _update_existing_requirement_from_extracted(db, existing.get("requirement_id"), extracted)
            return {
                "requirement_id": existing.get("requirement_id"),
                "existing": True,
                "requirement": existing,
            }

    if reuse_existing_client_requirement:
        existing = await _find_existing_client_requirement(db, email_doc, extracted)
        if existing:
            await _update_existing_requirement_from_extracted(db, existing.get("requirement_id"), extracted)
            return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    payload = _requirement_payload_from_email(email_doc, extracted)
    return await _create_requirement_via_core_or_db(db, payload)


async def _send_initial_trainer_mail(
    requirement_id: str,
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await _get_with_local_fallback(
            client,
            f"{TRAINER_SERVICE_URL}/api/v1/shortlists/{requirement_id}",
        )
        response.raise_for_status()
        shortlist_result = response.json()
    shortlist = shortlist_result.get("shortlist") if isinstance(shortlist_result, dict) else {}
    trainers = (shortlist or {}).get("top_trainers") or []
    pending_trainers = [
        trainer for trainer in trainers
        if _clean(trainer.get("pipeline_status")).lower() in {"", "shortlisted"}
        and _clean(trainer.get("last_mail_type")).lower() not in {"mail1", "mail1_reminder"}
        and not trainer.get("mail1_sent_at")
    ]
    if not trainers:
        return {
            "success": True,
            "sent": 0,
            "total": 0,
            "message": "Shortlist prepared, but no eligible trainers were found.",
            "requirement_id": requirement_id,
        }
    if not pending_trainers:
        return {
            "success": True,
            "sent": 0,
            "total": len(trainers),
            "message": "Mail1 already sent or in progress for all shortlisted trainers.",
            "requirement_id": requirement_id,
        }

    async with httpx.AsyncClient(timeout=180) as client:
        send_response = await _post_with_local_fallback(
            client,
            f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-mail",
            json={
                "requirement_id": requirement_id,
                "mail_type": "mail1",
                "trainer_ids": [
                    trainer.get("trainer_id") for trainer in pending_trainers
                    if trainer.get("trainer_id")
                ],
            },
        )
        send_response.raise_for_status()
        send_result = send_response.json()

    if isinstance(send_result, dict):
        send_result.setdefault("requirement_id", requirement_id)
        send_result.setdefault("total", len(trainers))
        return send_result
    return {
        "success": False,
        "sent": 0,
        "total": len(trainers),
        "error": "Trainer send-mail returned an invalid response",
        "requirement_id": requirement_id,
    }


async def _call_intelligence_search(
    extracted: Dict[str, Any],
    max_results: int = 20,
) -> Dict[str, Any]:
    """Call the intelligence service free-search and return results.

    This is a best-effort enrichment step that runs before trainer emails are sent.
    """
    domain = (extracted.get("technology_needed") or extracted.get("technology") or extracted.get("domain") or "")
    location = extracted.get("client_company") or ""
    payload = {"domain": domain, "location": location or "", "max_results": max_results, "save_leads": True}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await _post_with_local_fallback(
                client,
                "http://intelligence-service:8005/api/v1/intelligence/trainers/search",
                json=payload,
            )
            if r.status_code < 400:
                return r.json()
    except Exception:
        logger.exception("Intelligence free-search call failed for domain=%s", domain)
    return {"domain": domain, "location": location, "found": 0, "profiles": []}


async def _create_requirement_via_core_or_db(
    db: AsyncIOMotorDatabase,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await _post_with_local_fallback(client, f"{CORE_API_URL}/api/v1/requirements", json=payload)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("Core API requirement creation failed; falling back to direct DB insert: %s", exc)

    now = _now()
    doc = dict(payload)
    req_id = _clean(doc.get("requirement_id")) or f"REQ-{uuid.uuid4().hex[:8].upper()}"
    doc.update({
        "requirement_id": req_id,
        "created_at": now,
        "updated_at": now,
    })
    await db["requirements"].update_one(
        {"requirement_id": req_id},
        {
            "$setOnInsert": doc,
        },
        upsert=True,
    )
    return {
        "success": True,
        "requirement_id": req_id,
        "shortlist": {},
        "requirement": doc,
        "created_via": "email_service_db_fallback",
    }


async def _start_trainer_search_after_client_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    extracted = email_doc.get("extracted") or {}
    if not extracted:
        extracted = _extract_requirement_from_email(
            subject=email_doc.get("subject") or "",
            body=email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or "",
            sender_email=email_doc.get("from_email") or "",
            sender_name=email_doc.get("from_name") or "",
        )

    requirement_result = await _create_requirement(
        email_doc,
        extracted,
        db,
        reuse_existing_client_requirement=_is_reply_thread(email_doc.get("subject") or "", email_doc),
    )
    if requirement_result.get("deleted"):
        deleted_requirement_id = requirement_result.get("deleted_requirement_id") or email_doc.get("requirement_id") or ""
        now = _now()
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {
                "$set": {
                    "status": "deleted",
                    "reply_status": "deleted",
                    "deleted": True,
                    "deleted_requirement_id": deleted_requirement_id,
                    "processed": True,
                    "processed_at": now,
                    "updated_at": now,
                },
                "$unset": {"requirement_id": ""},
            },
        )
        return {"requirement_id": "", "reason": "requirement_deleted", "status": "deleted"}
    requirement_id = requirement_result.get("requirement_id")
    if not requirement_id:
        raise RuntimeError("No requirement_id available for trainer automation")

    send_result = await _send_initial_trainer_mail(requirement_id, extracted)
    sent_count = _safe_int(send_result.get("sent"), 0)
    automation_update = _trainer_automation_update(send_result)
    trainer_automation_started = automation_update.get("trainer_automation_status") in {"started", "shortlist1_handoff"}
    return {
        "requirement_id": requirement_id,
        "requirement_created": True,
        **automation_update,
        "mail_automation": send_result,
        "status": "auto_sent" if sent_count > 0 or trainer_automation_started else "trainer_email_failed",
    }


async def _create_revised_lab_cost_attachment(
    db: AsyncIOMotorDatabase,
    requirement: Dict[str, Any],
    lab_context: Dict[str, Any],
    generation_mode: str = "template",
) -> Optional[Dict[str, str]]:
    """Build a lab-cost workbook from the saved ToC and latest client inputs."""
    known = lab_context.get("known_inputs") or {}
    participants = _safe_int(known.get("participant_count") or requirement.get("participant_count"), 1) or 1
    hours = _safe_float(known.get("hours_per_day") or requirement.get("hours_per_day"), 3) or 3
    duration = _safe_float(
        requirement.get("duration_days") or known.get("duration_days") or 1,
        1,
    ) or 1
    technology = _clean(requirement.get("technology_needed") or requirement.get("technology") or requirement.get("domain"))
    if not technology:
        return None
    provider = _clean(known.get("cloud_provider") or requirement.get("cloud_provider") or "aws").lower()
    provider = "aws" if provider not in {"aws", "azure", "gcp"} else provider
    # Price the approved/saved day-wise ToC when it exists. Regenerating a
    # generic ToC here can silently change its topics and make the workbook
    # disagree with the ToC already shared with the client.
    toc: Optional[Dict[str, Any]] = None
    requirement_id = _clean(requirement.get("requirement_id"))
    if requirement_id:
        saved_toc = await db["toc_generations"].find_one(
            {"requirement_id": requirement_id, "toc": {"$type": "object"}},
            {"_id": 0, "toc": 1},
            sort=[("created_at", -1)],
        )
        if isinstance((saved_toc or {}).get("toc"), dict):
            toc = saved_toc["toc"]

    toc_payload = {
        "domain": technology,
        "duration_days": duration,
        "mode": _clean(requirement.get("mode") or "Online"),
        "audience_level": _clean(requirement.get("audience_level") or ""),
        "training_dates": _clean(requirement.get("training_dates") or requirement.get("preferred_dates") or ""),
        "requirement_id": requirement.get("requirement_id") or "",
        "generation_mode": "ai" if _clean(generation_mode).lower() == "ai" else "template",
        "custom_topics": _clean(requirement.get("toc_or_topics") or requirement.get("topics") or requirement.get("custom_topics")),
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            if toc is None:
                toc_response = await _post_with_local_fallback(
                    client, f"{TRAINER_SERVICE_URL}/api/v1/toc/generate", json=toc_payload,
                )
                if toc_response.status_code >= 400:
                    logger.error("Lab-cost TOC generation failed: %s", toc_response.text[:300])
                    return None
                toc = (toc_response.json() or {}).get("toc_data") or (toc_response.json() or {}).get("toc")
                if not isinstance(toc, dict):
                    return None
            workbook_response = await _post_with_local_fallback(
                client,
                f"{DOCUMENT_SERVICE_URL}/api/v1/documents/excel/toc/lab-cost",
                json={"toc": toc, "assumptions": {
                    "cloud_provider": provider,
                    "participant_count": participants,
                    "hours_per_day": hours,
                    "include_default_hour_options": False,
                }},
            )
        if workbook_response.status_code >= 400 or not workbook_response.content:
            logger.error("Revised lab-cost workbook generation failed: %s", workbook_response.text[:300])
            return None
        return {
            "filename": f"{technology} - Lab Cost Estimate ({participants} participants, {hours:g} hours per day).xlsx",
            "content_base64": base64.b64encode(workbook_response.content).decode(),
            "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    except Exception:
        logger.exception("Failed to create revised lab-cost workbook")
        return None


def _lab_cost_template_reply(subject: str, sender_name: str, known: Dict[str, Any]) -> Dict[str, str]:
    """Client-facing lab-cost acknowledgement; workbook generation is manual."""
    participants = _safe_int(known.get("participant_count"), 1) or 1
    duration = _safe_float(known.get("duration_days"), 1) or 1
    hours = _safe_float(known.get("hours_per_day"), 3) or 3
    provider = _clean(known.get("cloud_provider") or "AWS")
    name = (_clean(sender_name) or "Team").split()[0]
    return {
        "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
        "body": (
            f"Hi {name},\n\n"
            f"We have noted the {provider} lab requirement for {participants} participant(s), "
            f"{duration:g} day(s), and {hours:g} hours of access per day. "
            "The lab-cost template has been prepared from these inputs and the applicable ToC scope. "
            "Our team will share the final workbook separately after the manual cost review.\n\n"
            "Best Regards,\nRecruitment Team\nClahan Technologies"
        ),
    }


async def _recover_client_slot_reply_context(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """Recover the handoff context when a Gmail reply has no usable thread IDs.

    Some mail clients strip ``In-Reply-To`` / ``References`` headers.  A client
    can still reply with an exact offered date and time, so failing to attach
    that reply to the most recent *sent* client-slots handoff leaves the
    interview permanently at "Slot Booked".  This fallback is deliberately
    narrow: it only applies to an explicit selection from the same recipient.
    """
    if _clean(email_doc.get("source_outbound_mail_type")):
        return email_doc

    sender_email = _email_address(email_doc.get("from_email") or email_doc.get("sender") or "")
    reply_text = (
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    if not sender_email or _slot_confirmation_intent(reply_text) not in {
        "selected_slot_number", "selected_slot_details", "selected_slot",
    }:
        return email_doc

    candidate = await db["email_logs"].find_one(
        {
            "direction": "outbound",
            "status": "sent",
            "mail_type": "client_slots",
            "requirement_id": {"$exists": True, "$nin": ["", None]},
            "trainer_id": {"$exists": True, "$nin": ["", None]},
            "$or": [
                {"recipient": {"$regex": f"^{re.escape(sender_email)}$", "$options": "i"}},
                {"to_email": {"$regex": f"^{re.escape(sender_email)}$", "$options": "i"}},
            ],
        },
        {"_id": 0, "email_id": 1, "requirement_id": 1, "trainer_id": 1, "trainer_name": 1, "recipient_name": 1},
        sort=[("created_at", -1)],
    )
    if not candidate:
        return email_doc

    recovered = {
        "requirement_id": candidate.get("requirement_id") or "",
        "trainer_id": candidate.get("trainer_id") or "",
        "trainer_name": candidate.get("trainer_name") or candidate.get("recipient_name") or "",
        "source_outbound_email_id": candidate.get("email_id") or "",
        "source_outbound_mail_type": "client_slots",
        "updated_at": _now(),
    }
    if email_doc.get("email_id"):
        await db["client_emails"].update_one({"email_id": email_doc["email_id"]}, {"$set": recovered})
        await db["email_logs"].update_one({"email_id": email_doc["email_id"]}, {"$set": recovered})
    logger.info(
        "Recovered client-slot handoff context for %s: %s/%s",
        sender_email,
        recovered["requirement_id"],
        recovered["trainer_id"],
    )
    return {**email_doc, **recovered}


async def _process_client_requirement_email(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    force_new_requirement: bool = False,
) -> Dict[str, Any]:
    if force_new_requirement and email_doc.get("email_id"):
        await db["deleted_requirements"].delete_many({"source_email_id": email_doc.get("email_id")})

    sender_email = email_doc.get("from_email") or email_doc.get("sender") or ""
    if not force_new_requirement and _is_obvious_non_client_email(
        sender_email,
        email_doc.get("subject") or "",
        email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or "",
    ):
        now = _now()
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "processed": True,
                "processed_at": now,
                "status": "ignored",
                "reply_status": "ignored",
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": "Automated or no-reply sender",
                "updated_at": now,
            }},
        )
        return {"processed": True, "email_id": email_doc.get("email_id"), "status": "ignored", "reason": "automated_sender"}

    # TOC-correction messages are exceptional follow-ups to an already-sent
    # Mail 1. Their replies must not be interpreted as fresh client requests or
    # trigger another trainer template. Hold them for a human to review.
    if _clean(email_doc.get("source_outbound_mail_type")).lower() == "mail1_toc_correction":
        now = _now()
        update = {
            "processed": True,
            "processed_at": now,
            "status": "needs_manual_review",
            "reply_status": "needs_manual_review",
            "office_mail_category": "trainer_reply",
            "classification_reason": "trainer_reply_to_toc_correction",
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": now,
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": "needs_manual_review",
            "reason": "trainer_reply_to_toc_correction",
        }

    deleted_source_clauses: List[Dict[str, Any]] = []
    if email_doc.get("email_id"):
        deleted_source_clauses.append({"source_email_id": email_doc.get("email_id")})
    inbound_message_id = _clean(email_doc.get("gmail_message_id") or email_doc.get("latest_gmail_message_id") or "")
    if inbound_message_id:
        deleted_source_clauses.extend([
            {"gmail_message_id": inbound_message_id},
            {"latest_gmail_message_id": inbound_message_id},
            {"thread_message_ids": inbound_message_id},
        ])
    inbound_thread_id = _clean(email_doc.get("gmail_thread_id") or email_doc.get("thread_id") or "")
    if inbound_thread_id:
        deleted_source_clauses.append({"gmail_thread_id": inbound_thread_id})
    deleted_source = None
    if deleted_source_clauses and not force_new_requirement:
        deleted_source = await db["deleted_requirements"].find_one(
            {"$or": deleted_source_clauses},
            {"_id": 0, "requirement_id": 1, "deleted_at": 1},
        )

    if (email_doc.get("deleted") is True or deleted_source) and not force_new_requirement:
        now = _now()
        deleted_requirement_id = (
            email_doc.get("deleted_requirement_id")
            or (deleted_source or {}).get("requirement_id")
            or email_doc.get("requirement_id")
            or ""
        )
        update_doc = {
            "$set": {
                "processed": True,
                "processed_at": now,
                "status": "deleted",
                "reply_status": "deleted",
                "deleted": True,
                "deleted_at": email_doc.get("deleted_at") or (deleted_source or {}).get("deleted_at") or now,
                "pending_trainer_automation": False,
                "client_authorized_trainer_search": False,
                "updated_at": now,
            },
            "$unset": {"requirement_id": ""},
        }
        if deleted_requirement_id:
            update_doc["$set"]["deleted_requirement_id"] = deleted_requirement_id
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, update_doc)
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "reason": "deleted",
            "status": "deleted",
        }

    if not _is_today_or_newer(email_doc):
        now = _now()
        extracted = email_doc.get("extracted") or {
            "confidence": 0,
            "is_training_request": False,
            "direct_request_language": False,
            "is_non_client_email": False,
            "extraction_method": "skipped_before_today_cutoff",
        }
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "processed": True,
                "processed_at": now,
                "status": "ignored",
                "reply_status": "ignored",
                "auto_send_eligible": False,
                "confidence": extracted.get("confidence", 0),
                "auto_send_confidence": extracted.get("confidence", 0),
                "extracted": extracted,
                "classification_reason": "ignored_before_today_cutoff",
                "updated_at": now,
            }},
        )
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "reason": "ignored_before_today_cutoff",
            "status": "ignored",
        }

    subject = email_doc.get("subject") or ""
    body = email_doc.get("clean_body") or email_doc.get("raw_body") or email_doc.get("body") or ""
    # Header-less replies are common in mobile clients.  Recover their exact
    # client-slots handoff before deciding whether this is a generic request.
    email_doc = await _recover_client_slot_reply_context(db, email_doc)
    now = _now()
    trainer_doc = None
    settings = await _auto_send_settings(db)
    sender_email = _email_address(email_doc.get("from_email") or email_doc.get("sender") or "")
    if sender_email and sender_email in set(settings.get("mailbox_addresses") or []):
        update = {
            "processed": True,
            "processed_at": now,
            "status": "ignored",
            "reply_status": "ignored",
            "auto_send_eligible": False,
            "auto_send_candidate": False,
            "auto_send_ready": False,
            "auto_send_confidence": 0,
            "auto_send_threshold": settings["threshold"],
            "auto_send_block_reason": "own_mailbox_sender",
            "classification_reason": "ignored_own_mailbox_sender",
            "updated_at": now,
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "reason": "ignored_own_mailbox_sender",
            "status": "ignored",
        }

    # Never infer a new lab-cost request from quoted thread history. In
    # particular, a client choosing an interview slot quotes the earlier
    # profile/ToC email, which can itself mention lab costs.
    latest_message_body = _strip_quoted_email_history(body) or body
    linked_trainer_thread = _is_linked_trainer_thread(email_doc)

    # Questions from a trainer must be resolved without changing shortlist
    # state. This has to run before the content-only and Mail 1 handlers:
    # otherwise a ToC doubt is treated as a client ToC request, while any
    # other non-decline reply is treated as acceptance and triggers Step 2.
    if _is_linked_trainer_question(email_doc, subject, latest_message_body):
        question_doc = {
            **email_doc,
            "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
            "classification_body": latest_message_body,
            "email_classification": {"person_type": "trainer", "scenario": "trainer_general_question"},
            "office_mail_category": "trainer_general_question",
        }
        reference_reply = _approved_question_reply(email_doc.get("from_name") or "Trainer")
        reference_reply["subject"] = f"Re: {subject}" if subject and not subject.lower().startswith("re:") else (subject or "Re: Training Clarification")
        try:
            question_result = await _handle_trainer_general_question(db, question_doc, reference_reply)
        except Exception as exc:
            logger.exception("Early trainer question resolution failed for %s", email_doc.get("email_id"))
            question_result = {"attempted": True, "success": False, "error": str(exc)}
        if question_result.get("attempted"):
            question_status = "auto_sent" if question_result.get("success") else "pending_retry"
            await db["client_emails"].update_one(
                {"email_id": email_doc.get("email_id")},
                {"$set": {
                    "processed": bool(question_result.get("success")),
                    "processed_at": _now() if question_result.get("success") else None,
                    "status": question_status,
                    "reply_status": question_status,
                    "email_classification": question_doc["email_classification"],
                    "office_mail_category": "trainer_general_question",
                    "classification_reason": "trainer_question_resolution_before_pipeline",
                    "reply_template_key": "trainer_question_resolution",
                    "question_resolution": question_result,
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "updated_at": _now(),
                }},
            )
            log_identity = []
            if email_doc.get("gmail_message_id"):
                log_identity.append({"gmail_message_id": email_doc.get("gmail_message_id")})
            if email_doc.get("email_id"):
                log_identity.append({"email_id": email_doc.get("email_id")})
            if log_identity:
                await db["email_logs"].update_one(
                    {"$or": log_identity},
                    {"$set": {
                        "processed": bool(question_result.get("success")),
                        "reply_status": question_status,
                        "person_type": "trainer",
                        "scenario": "trainer_general_question",
                        "office_mail_category": "trainer_general_question",
                        "classification_reason": "trainer_question_resolution_before_pipeline",
                        "updated_at": _now(),
                    }},
                )
            return {
                "processed": bool(question_result.get("success")),
                "email_id": email_doc.get("email_id"),
                "reason": "trainer_question_resolution_before_pipeline",
                "status": question_status,
                "question_resolution": question_result,
            }

    lab_requirement_probe: Dict[str, Any] = {}
    if _is_lab_cost_inquiry(subject, latest_message_body):
        lab_requirement_probe = _extract_requirement_from_email(
            subject=subject,
            body=latest_message_body,
            sender_email=sender_email,
            sender_name=email_doc.get("from_name") or "",
        )
    # A standalone request for lab cost (even with a domain, ToC or listed
    # topics) is its own service flow. It must never send Mail 1 or search for
    # trainers unless the client explicitly also asked for a trainer.
    lab_email_is_new_training_requirement = bool(
        lab_requirement_probe.get("is_training_request")
        and lab_requirement_probe.get("direct_request_language")
        and _has_training_domain(lab_requirement_probe)
        and not _is_reply_thread(subject, email_doc)
        and not _is_lab_cost_only_inquiry(subject, latest_message_body)
    )

    # A reply to the client-slots email can include both the chosen interview
    # time and lab-cost details.  The interview confirmation must take
    # priority; otherwise the lab handler returns early and neither side gets
    # the meeting link.
    if (
        _is_lab_cost_inquiry(subject, latest_message_body)
        and not linked_trainer_thread
        and not lab_email_is_new_training_requirement
        and str(email_doc.get("source_outbound_mail_type") or "").strip() != "client_slots"
    ):
        from app.routes.inbox_actions import _build_lab_reference_reply, _lab_request_context

        extracted = _merge_existing_requirement_context(lab_requirement_probe, email_doc)
        extracted = await _merge_requirement_record_context(db, extracted, email_doc.get("requirement_id"))
        lab_context = _lab_request_context(latest_message_body, extracted)
        # A lab-cost follow-up in an active trainer/interview thread updates
        # the requirement.  Do not send another generic question: the revised
        # estimate belongs with the interview-link email if the client asked
        # for lab cost.
        if email_doc.get("requirement_id"):
            known = lab_context.get("known_inputs") or {}
            lab_update = {
                "participant_count": known.get("participant_count"),
                "hours_per_day": known.get("hours_per_day"),
                "cloud_provider": known.get("cloud_provider") or "AWS",
                "lab_cost_requested": True,
                "lab_cost_status": "inputs_received",
                "updated_at": _now(),
            }
            await db["requirements"].update_one(
                {"requirement_id": email_doc["requirement_id"]},
                {"$set": lab_update},
            )
            requirement = await db["requirements"].find_one(
                {"requirement_id": email_doc["requirement_id"]}, {"_id": 0},
            ) or {**extracted, **lab_update, "requirement_id": email_doc["requirement_id"]}
            # Generate from the exact saved ToC plus the latest client inputs.
            # A message must only claim an attachment when this succeeds.
            attachment = await _create_revised_lab_cost_attachment(db, requirement, lab_context)
            if attachment:
                reply = {
                    "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
                    "body": (
                        f"Dear {(_clean(email_doc.get('from_name')) or 'Team').split()[0]},\n\n"
                        f"Please find the revised lab-cost estimate attached for {known.get('participant_count') or requirement.get('participant_count') or 1} participant(s), "
                        f"with {known.get('hours_per_day') or requirement.get('hours_per_day') or 3} hours of lab access per day. "
                        "The calculation is aligned to the current training dates and TOC.\n\n"
                        "Regards,\nClahan Technologies"
                    ),
                }
                send_result = await _send_client_auto_reply(
                    db,
                    {**email_doc, "from_email": sender_email},
                    reply,
                    requirement_id=email_doc["requirement_id"],
                    attachments=[attachment],
                    mail_type_override="client_lab_cost_revised",
                )
                success = bool(send_result.get("success"))
                lab_update["lab_cost_status"] = "revised_estimate_sent" if success else "revised_estimate_failed"
                await db["requirements"].update_one({"requirement_id": email_doc["requirement_id"]}, {"$set": lab_update})
                await db["client_emails"].update_one(
                    {"email_id": email_doc.get("email_id")},
                    {"$set": {
                        "processed": True, "status": "auto_sent" if success else "reply_failed",
                        "reply_status": "sent" if success else "failed",
                        "classification_reason": "revised_lab_cost_sent",
                        "lab_cost_context": lab_context,
                        "lab_cost_attachments": [attachment["filename"]],
                        "updated_at": _now(),
                    }},
                )
                return {"processed": True, "email_id": email_doc.get("email_id"), "status": "auto_sent" if success else "reply_failed", "reason": "revised_lab_cost_sent", "auto_reply": send_result}
            await db["client_emails"].update_one(
                {"email_id": email_doc.get("email_id")},
                {"$set": {
                    "processed": True,
                    "status": "lab_inputs_received",
                    "reply_status": "not_sent",
                    "classification_reason": "lab_inputs_saved_for_interview_link",
                    "lab_cost_context": lab_context,
                    "updated_at": _now(),
                }},
            )
            return {"processed": True, "email_id": email_doc.get("email_id"), "status": "lab_inputs_received", "reason": "lab_inputs_saved_for_interview_link"}
        # Standalone lab-cost work is persisted separately and never creates a
        # trainer requirement.  Once every costing input is present, generate
        # the client workbook immediately from the supplied domain/ToC context.
        known = lab_context.get("known_inputs") or {}
        if not (lab_context.get("missing_quote_inputs") or []):
            lab_request_id = f"LAB-{uuid.uuid4().hex[:10].upper()}"
            standalone_requirement = {
                **extracted,
                "requirement_id": lab_request_id,
                "technology_needed": extracted.get("technology_needed") or extracted.get("technology") or extracted.get("domain"),
                "duration_days": known.get("duration_days") or extracted.get("duration_days") or 1,
                "participant_count": known.get("participant_count"),
                "hours_per_day": known.get("hours_per_day"),
                "cloud_provider": known.get("cloud_provider"),
                "lab_cost_only": True,
                "client_email": sender_email,
                "client_name": email_doc.get("from_name") or "",
            }
            await db["lab_cost_requests"].update_one(
                {"source_email_id": email_doc.get("email_id") or lab_request_id},
                {"$set": {
                    **standalone_requirement,
                    "source_email_id": email_doc.get("email_id") or "",
                    "source_attachment_names": [str(item.get("filename") or "") for item in (email_doc.get("attachments") or []) if isinstance(item, dict)],
                    "toc_or_topics": extracted.get("toc_text") or extracted.get("course_agenda") or extracted.get("topics") or extracted.get("custom_topics") or "",
                    "lab_context": lab_context,
                    "status": "generating_workbook",
                    "updated_at": _now(),
                }, "$setOnInsert": {"created_at": _now()}},
                upsert=True,
            )
            attachment = await _create_revised_lab_cost_attachment(
                db,
                standalone_requirement,
                lab_context,
                generation_mode="ai" if await _global_ai_wording_enabled(db) else "template",
            )
            if attachment:
                reply = {
                    "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
                    "body": (
                        f"Dear {(_clean(email_doc.get('from_name')) or 'Team').split()[0]},\n\n"
                        "Please find the lab-cost estimate attached. It is prepared from the domain/ToC details and the lab inputs you shared.\n\n"
                        "Regards,\nClahan Technologies"
                    ),
                }
                lab_classification = {"person_type": "corporate_client", "scenario": "client_asks_lab_cost", "confidence": 0.99, "auto_reply_allowed": True, "requires_human": False}
                reply = await _humanize_verified_client_reply(db, email_doc, lab_classification, standalone_requirement, subject, body, reply)
                send_result = await _send_client_auto_reply(
                    db, {**email_doc, "from_email": sender_email, "email_classification": lab_classification,
                         "office_mail_category": "client_asks_lab_cost"}, reply,
                    requirement_id=lab_request_id, attachments=[attachment], mail_type_override="client_lab_cost_estimate",
                )
                success = bool(send_result.get("success"))
                await db["lab_cost_requests"].update_one(
                    {"source_email_id": email_doc.get("email_id") or lab_request_id},
                    {"$set": {"status": "estimate_sent" if success else "estimate_send_failed", "workbook_filename": attachment["filename"], "updated_at": _now()}},
                )
                await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": {"processed": True, "status": "auto_sent" if success else "reply_failed", "reply_status": "sent" if success else "failed", "classification_reason": "standalone_lab_cost_estimate_sent", "lab_cost_context": lab_context, "lab_cost_attachments": [attachment["filename"]], "updated_at": _now()}})
                return {"processed": True, "email_id": email_doc.get("email_id"), "status": "auto_sent" if success else "reply_failed", "reason": "standalone_lab_cost_estimate_sent", "auto_reply": send_result}
        lab_classification = {
            "person_type": "corporate_client",
            "scenario": "client_asks_lab_cost",
            "confidence": 0.99,
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        reply = _build_lab_reference_reply(
            lab_context,
            extracted,
            email_doc.get("from_name") or "",
            subject,
        )
        reply = await _humanize_verified_client_reply(
            db, email_doc, lab_classification, extracted, subject, body, reply,
        )
        if reply.get("llm_generation_failed"):
            logger.warning(
                "OpenAI wording unavailable for grounded lab-cost reply %s; using verified cost template",
                email_doc.get("email_id"),
            )
        send_result = await _send_client_auto_reply(
            db,
            {**email_doc, "from_email": sender_email, "email_classification": lab_classification,
             "office_mail_category": "client_asks_lab_cost"},
            reply,
        )
        success = bool(send_result.get("success"))
        update = {
            "processed": True, "processed_at": send_result.get("sent_at") or now,
            "status": "auto_sent" if success else "reply_failed",
            "reply_status": "sent" if success else "failed",
            "email_classification": lab_classification, "office_mail_category": "client_asks_lab_cost",
            "classification_reason": "lab_cost_inputs_requested",
            "reply_template_key": "client_lab_cost_grounded",
            "generated_reply": {"subject": reply["subject"], "body": reply["body"]},
            "ai_reply": reply["body"], "draft_reply": reply["body"], "lab_cost_context": lab_context,
            "lab_cost_attachments": [],
            "reply_sent": success, "reply_sent_at": send_result.get("sent_at"),
            "sent_reply_body": send_result.get("body") or reply["body"],
            "sent_reply_subject": send_result.get("subject") or reply["subject"],
            "auto_send_error": "" if success else send_result.get("error", "Send failed"),
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {"processed": True, "email_id": email_doc.get("email_id"), "status": update["status"], "reason": "lab_cost_inputs_requested", "auto_reply": send_result}

    # A stand-alone ToC request is a content-delivery enquiry, not a trainer
    # requirement. Keep it outside both confirmed and proposal pipelines.
    if not linked_trainer_thread and _is_toc_only_inquiry(subject, body):
        toc_extracted = _extract_requirement_from_email(
            subject=subject,
            body=body,
            sender_email=sender_email,
            sender_name=email_doc.get("from_name") or "",
        )
        technology = _clean(toc_extracted.get("technology_needed") or toc_extracted.get("technology") or toc_extracted.get("domain"))
        duration = _clean(toc_extracted.get("duration_text") or toc_extracted.get("duration_days"))
        missing = []
        if not technology:
            missing.append("technology/domain")
        if not duration:
            missing.append("training duration or number of days")
        client_name = _clean(email_doc.get("from_name") or "Client").split()[0]
        toc_attachment = None
        generation_mode = "ai" if await _global_ai_wording_enabled(db) else "template"
        if not missing:
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    toc_response = await _post_with_local_fallback(client, f"{TRAINER_SERVICE_URL}/api/v1/toc/generate", json={
                        "domain": technology,
                        "duration_days": max(1, _safe_int(toc_extracted.get("duration_days"), 1)),
                        "mode": toc_extracted.get("mode") or "Online",
                        "generation_mode": generation_mode,
                        "custom_topics": toc_extracted.get("topics") or toc_extracted.get("custom_topics") or "",
                        "client_notes": body[:4000],
                    })
                    toc_response.raise_for_status()
                    toc_data = (toc_response.json() or {}).get("toc_data") or {}
                    workbook_response = await _post_with_local_fallback(client, f"{DOCUMENT_SERVICE_URL}/api/v1/documents/excel/toc", json={"toc": toc_data})
                    workbook_response.raise_for_status()
                if workbook_response.content:
                    toc_attachment = {"filename": f"{technology} - Training ToC.xlsx", "content_base64": base64.b64encode(workbook_response.content).decode(), "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            except Exception:
                logger.exception("Standalone ToC generation failed for %s", email_doc.get("email_id"))
        if missing:
            action = "To prepare the right ToC, please confirm " + " and ".join(missing) + "."
        elif toc_attachment:
            action = "Please find the day-wise ToC attached, prepared using the technology and duration you shared."
        else:
            action = "We will prepare the day-wise ToC using the technology and duration you shared."
        toc_reply = {
            "subject": f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject,
            "body": (
                f"Dear {client_name},\n\n"
                "Thank you for your ToC/course-agenda request. "
                f"{action}\n\n"
                "We have treated this as a ToC-only request and will not start trainer shortlisting.\n\n"
                "Regards,\nClahan Technologies"
            ),
        }
        toc_classification = {
            "person_type": "corporate_client",
            "scenario": "client_asks_toc_only",
            "confidence": 0.99,
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        toc_reply = await _humanize_verified_client_reply(
            db, email_doc, toc_classification, toc_extracted, subject, body, toc_reply,
        )
        send_result = await _send_client_auto_reply(
            db,
            {**email_doc, "from_email": sender_email, "email_classification": toc_classification,
             "office_mail_category": "client_asks_toc_only"},
            toc_reply,
            attachments=[toc_attachment] if toc_attachment else None,
            mail_type_override="client_toc_only",
        )
        success = bool(send_result.get("success"))
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "processed": True,
                "processed_at": send_result.get("sent_at") or now,
                "status": "auto_sent" if success else "reply_failed",
                "reply_status": "sent" if success else "failed",
                "email_classification": toc_classification,
                "office_mail_category": "client_asks_toc_only",
                "classification_reason": "toc_only_request",
                "reply_template_key": "client_toc_only",
                "sent_reply_body": send_result.get("body") or toc_reply["body"],
                "auto_send_error": "" if success else send_result.get("error", "Send failed"),
                "updated_at": _now(),
            }},
        )
        return {"processed": True, "email_id": email_doc.get("email_id"), "status": "auto_sent" if success else "reply_failed", "reason": "toc_only_request", "auto_reply": send_result}

    if not linked_trainer_thread and _is_technology_catalogue_inquiry(subject, body):
        reply = await _technology_catalogue_reply(db, subject)
        catalogue_classification = {
            "person_type": "corporate_client",
            "scenario": "client_asks_technology_catalogue",
            "confidence": 0.99,
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        reply = await _humanize_verified_client_reply(
            db,
            email_doc,
            catalogue_classification,
            email_doc.get("extracted") or {},
            subject,
            body,
            reply,
        )
        if reply.get("llm_generation_failed"):
            logger.warning(
                "OpenAI wording unavailable for technology catalogue reply %s; using verified catalogue template",
                email_doc.get("email_id"),
            )
        send_result = await _send_client_auto_reply(
            db,
            {
                **email_doc,
                "from_email": sender_email,
                "email_classification": catalogue_classification,
                "office_mail_category": "client_asks_technology_catalogue",
            },
            reply,
        )
        success = bool(send_result.get("success"))
        update = {
            "processed": True,
            "processed_at": send_result.get("sent_at") or now,
            "status": "auto_sent" if success else "reply_failed",
            "reply_status": "sent" if success else "failed",
            "email_classification": catalogue_classification,
            "office_mail_category": "client_asks_technology_catalogue",
            "classification_reason": "technology_catalogue_inquiry",
            "reply_template_key": "technology_catalogue",
            "generated_reply": reply,
            "ai_reply": reply["body"],
            "draft_reply": reply["body"],
            "auto_send_candidate": True,
            "auto_send_eligible": True,
            "auto_send_ready": True,
            "auto_send_error": "" if success else send_result.get("error", "Send failed"),
            "reply_error": "" if success else send_result.get("error", "Send failed"),
            "reply_sent": success,
            "reply_sent_at": send_result.get("sent_at"),
            "reply_sent_for_message_id": send_result.get("source_gmail_message_id"),
            "sent_reply_body": send_result.get("body") or reply["body"],
            "sent_reply_subject": send_result.get("subject") or reply["subject"],
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        await db["email_logs"].update_one(
            {"gmail_message_id": email_doc.get("gmail_message_id")},
            {"$set": {
                "processed": True,
                "processed_at": update["processed_at"],
                "reply_status": update["reply_status"],
                "office_mail_category": "client_asks_technology_catalogue",
                "classification_reason": "technology_catalogue_inquiry",
                "updated_at": _now(),
            }},
        )
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "technology_catalogue_inquiry",
            "auto_reply": send_result,
        }

    # Client replies to slot-selection emails are operational confirmations,
    # not requirement replies. Handle them before generic sentiment analysis.
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    if source_mail_type in {"client_slots", "client_interview_reschedule_request"}:
        try:
            slot_result = await _handle_client_slot_confirmation_reply(db, email_doc)
        except Exception as exc:
            logger.exception("Client slot confirmation automation failed for %s", email_doc.get("email_id"))
            slot_result = {"attempted": True, "success": False, "error": str(exc)}
        if slot_result.get("attempted"):
            now = _now()
            status = "auto_sent" if slot_result.get("success") else "needs_manual_review"
            calendar_retry_needed = (
                not slot_result.get("success")
                and slot_result.get("reason") == "calendar_failed_no_mail_sent"
            )
            prior_retry_count = int(email_doc.get("calendar_retry_count") or 0)
            revised_lab_result: Dict[str, Any] = {}
            if slot_result.get("success") and _is_lab_cost_inquiry(subject, latest_message_body) and email_doc.get("requirement_id"):
                from app.routes.inbox_actions import _lab_request_context

                lab_extracted = _merge_existing_requirement_context(lab_requirement_probe, email_doc)
                lab_extracted = await _merge_requirement_record_context(db, lab_extracted, email_doc["requirement_id"])
                lab_context = _lab_request_context(latest_message_body, lab_extracted)
                known = lab_context.get("known_inputs") or {}
                await db["requirements"].update_one(
                    {"requirement_id": email_doc["requirement_id"]},
                    {"$set": {
                        "participant_count": known.get("participant_count"),
                        "hours_per_day": known.get("hours_per_day"),
                        "cloud_provider": known.get("cloud_provider") or "AWS",
                        "lab_cost_requested": True,
                        "updated_at": now,
                    }},
                )
                requirement = await db["requirements"].find_one({"requirement_id": email_doc["requirement_id"]}, {"_id": 0}) or {}
                attachment = await _create_revised_lab_cost_attachment(db, requirement, lab_context)
                if attachment:
                    revised_lab_result = await _send_client_auto_reply(
                        db,
                        {**email_doc, "from_email": sender_email},
                        {
                            "subject": f"Re: {subject}" if not subject.lower().startswith("re:") else subject,
                            "body": "Please find the revised lab-cost estimate attached, calculated using the participant count and lab-access duration you shared.\n\nRegards,\nClahan Technologies",
                        },
                        requirement_id=email_doc["requirement_id"],
                        attachments=[attachment],
                        mail_type_override="client_lab_cost_revised",
                    )
            await db["client_emails"].update_one(
                {"email_id": email_doc.get("email_id")},
                {"$set": {
                    "processed": True,
                    "processed_at": slot_result.get("sent_at") or now,
                    "status": status,
                    "reply_status": status,
                    "classification_reason": "client_slot_confirmation",
                    "client_slot_confirmation": slot_result,
                    "revised_lab_cost": revised_lab_result,
                    "sentiment": "positive" if slot_result.get("success") else "neutral",
                    "action": "interview_link_sent" if slot_result.get("success") else "manual_interview_review",
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    # Only retry an unsent calendar operation. This prevents
                    # duplicate interview mails while allowing recovery after
                    # Calendar permission is connected.
                    "calendar_retry_pending": calendar_retry_needed,
                    "calendar_retry_count": prior_retry_count + 1 if calendar_retry_needed else prior_retry_count,
                    "calendar_retry_after": (now + timedelta(minutes=5)) if calendar_retry_needed else None,
                    "updated_at": now,
                }},
            )
            return {
                "processed": True,
                "email_id": email_doc.get("email_id"),
                "reason": "client_slot_confirmation",
                "status": status,
                "client_slot_confirmation": slot_result,
            }

    if source_mail_type in {"mail1", "mail1_reminder", "mail1_toc_correction"} and email_doc.get("requirement_id") and email_doc.get("trainer_id"):
        shortlist_state = await db["shortlists"].find_one(
            {
                "requirement_id": email_doc.get("requirement_id"),
                "top_trainers.trainer_id": email_doc.get("trainer_id"),
            },
            {"_id": 0, "top_trainers.$": 1},
        ) or {}
        current_trainer_state = (shortlist_state.get("top_trainers") or [{}])[0]
        current_stage = _clean(current_trainer_state.get("pipeline_status")).lower()
        current_last_mail = _clean(current_trainer_state.get("last_mail_type")).lower()
        current_commercial_status = _clean(current_trainer_state.get("commercial_status")).lower()
        already_past_mail1 = (
            current_stage in {
                "waiting_reply2",
                "details_received",
                "slot_booked",
                "interview_scheduled",
                "selected",
                "toc_requested",
                "training_confirmed",
            }
            or current_last_mail in {
                "mail2",
                "mail2_followup",
                "trainer_commercials_to_client",
                "mail3",
                "mail3_slot_booking",
            }
            or current_commercial_status in {
                "sent_to_client",
                "approved_by_client",
                "accepted_by_trainer",
                "negotiating_with_trainer",
            }
            or bool(current_trainer_state.get("trainer_details_received_at"))
            or bool(current_trainer_state.get("client_commercial_sent_at"))
        )
        if already_past_mail1:
            # If a trainer reply was already marked as details_received but Mail 3
            # was never actually sent, do not bury the reply as "stale". This can
            # happen when Gmail threading/linking catches a later trainer response
            # after the shortlist state moved forward.
            should_recover_missing_mail3 = (
                current_stage in {"details_received", "mail1_replied", "waiting_reply2"}
                or bool(current_trainer_state.get("trainer_details_received_at"))
            ) and current_last_mail not in {"mail3", "mail3_slot_booking", "mail3_slot_followup", "mail3_too_many_slots"}
            if should_recover_missing_mail3:
                requirement_id = email_doc.get("requirement_id") or ""
                trainer_id = email_doc.get("trainer_id") or ""
                existing_mail3 = await db["email_logs"].find_one(
                    {
                        "direction": "outbound",
                        "status": "sent",
                        "mail_type": "mail3",
                        "requirement_id": requirement_id,
                        "trainer_id": trainer_id,
                    },
                    {"_id": 0, "email_id": 1},
                    sort=[("created_at", -1)],
                )
                if not existing_mail3:
                    mail3_requirement = await db["requirements"].find_one(
                        {"requirement_id": requirement_id},
                        {"_id": 0},
                    ) or {}
                    shortlist_doc = await db["shortlists"].find_one(
                        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
                        {"_id": 0, "top_trainers.$": 1, "client_email": 1, "client_name": 1, "technology_needed": 1},
                    ) or {}
                    current_trainer = (shortlist_doc.get("top_trainers") or [current_trainer_state or {}])[0] or current_trainer_state or {}
                    mail3_result = await _send_trainer_mail3_if_missing(
                        db,
                        requirement_id,
                        trainer_id,
                        current_trainer,
                        mail3_requirement,
                        shortlist_doc,
                        source_email_id=email_doc.get("email_id") or "",
                        source_gmail_message_id=email_doc.get("gmail_message_id") or "",
                    )
                    update = {
                        "processed": True,
                        "processed_at": now,
                        "status": "processed" if mail3_result.get("success") else "needs_manual_review",
                        "reply_status": "details_received",
                        "reply_template_key": "mail3" if mail3_result.get("success") else "trainer_details_received",
                        "classification_reason": "recovered_missing_mail3_after_details_received",
                        "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
                        "office_mail_category": "trainer_details_sent",
                        "trainer_details_received": True,
                        "trainer_details_received_at": now,
                        "mail3_result": mail3_result,
                        "auto_send_candidate": False,
                        "auto_send_eligible": False,
                        "auto_send_ready": False,
                        "auto_send_block_reason": "",
                        "auto_send_error": "" if mail3_result.get("success") else mail3_result.get("error", mail3_result.get("reason", "")),
                        "reply_error": "" if mail3_result.get("success") else mail3_result.get("error", mail3_result.get("reason", "")),
                        "reply_sent": bool(mail3_result.get("success")),
                        "reply_sent_at": now if mail3_result.get("success") else None,
                        "updated_at": _now(),
                    }
                    await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
                    return {
                        "processed": True,
                        "email_id": email_doc.get("email_id"),
                        "status": update["status"],
                        "reason": "recovered_missing_mail3_after_details_received",
                        "mail3": mail3_result,
                    }
            update = {
                "processed": True,
                "processed_at": now,
                "status": "processed",
                "reply_status": "ignored_old_mail1_reply",
                "classification_reason": "stale_mail1_reply_ignored",
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": "trainer_already_past_mail1",
                "updated_at": now,
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
            return {
                "processed": True,
                "email_id": email_doc.get("email_id"),
                "status": "processed",
                "reason": "stale_mail1_reply_ignored",
                "current_stage": current_stage,
                "last_mail_type": current_last_mail,
            }
        latest_reply_text = _strip_quoted_email_history(body) or body
        initial_intent = _trainer_initial_reply_intent(latest_reply_text)
        if initial_intent == "declined":
            await _mark_shortlist_trainer_reply_received(
                db,
                {
                    **email_doc,
                    "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
                    "classification_body": latest_reply_text,
                    "email_classification": {"person_type": "trainer", "scenario": "trainer_not_interested"},
                    "office_mail_category": "trainer_not_interested",
                },
                stage="mail1",
                status="rejected",
                reply_at=now,
            )
            await db["shortlists"].update_one(
                {"requirement_id": email_doc.get("requirement_id"), "top_trainers.trainer_id": email_doc.get("trainer_id")},
                {"$set": {
                    "top_trainers.$.pipeline_status": "rejected",
                    "top_trainers.$.reply_sentiment": "negative",
                    "top_trainers.$.declined_at": now,
                    "top_trainers.$.decline_reason": latest_reply_text[:500],
                    "top_trainers.$.updated_at": now,
                    "updated_at": now,
                }},
            )
            update = {
                "processed": True,
                "processed_at": now,
                "status": "processed",
                "reply_status": "received",
                "reply_template_key": "",
                "email_classification": {"person_type": "trainer", "scenario": "trainer_not_interested"},
                "office_mail_category": "trainer_not_interested",
                "sentiment": "negative",
                "action": "mark_declined",
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": "trainer_declined",
                "reply_sent": False,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
            return {
                "processed": True,
                "email_id": email_doc.get("email_id"),
                "status": update["status"],
                "reason": "trainer_mail1_declined",
            }
        trainer_doc = {
            **email_doc,
            "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
            "classification_body": latest_reply_text,
            "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
            "office_mail_category": "trainer_interested",
        }
        await _mark_shortlist_trainer_reply_received(
            db,
            trainer_doc,
            stage="mail1",
            status="mail1_replied",
            reply_at=now,
        )
        mail2_requirement = {}
        if email_doc.get("requirement_id"):
            mail2_requirement = await db["requirements"].find_one(
                {"requirement_id": email_doc.get("requirement_id")},
                {"_id": 0},
            ) or {}
        evidence_doc = _trainer_detail_evidence_doc(email_doc, current_trainer_state)
        evidence_text = evidence_doc.get("classification_body") or latest_reply_text
        missing_requested_details = _trainer_missing_requested_details(evidence_text, mail2_requirement, evidence_doc)
        if missing_requested_details:
            # If three valid slots were already provided with this partial
            # reply, retain them while asking only for the remaining detail.
            # When the trainer replies to the one follow-up, those stored slots
            # can be handed to the client without another trainer email.
            if _slot_reply_intent(latest_reply_text) == "valid_slots":
                await db["shortlists"].update_one(
                    {"requirement_id": email_doc.get("requirement_id"), "top_trainers.trainer_id": email_doc.get("trainer_id")},
                    {"$set": {
                        "top_trainers.$.pending_slot_reply_text": latest_reply_text,
                        "top_trainers.$.availability_text": latest_reply_text,
                        "top_trainers.$.updated_at": now,
                        "updated_at": now,
                    }},
                )
            followup_result = await _send_missing_trainer_details_followup(
                db,
                email_doc={
                    **trainer_doc,
                    "trainer_name": email_doc.get("trainer_name") or current_trainer_state.get("name") or current_trainer_state.get("trainer_name"),
                },
                requirement=mail2_requirement,
                trainer_state=current_trainer_state,
                missing_details=missing_requested_details,
                now=now,
            )
            followup_success = bool(followup_result.get("success") or followup_result.get("already_attempted"))
            update = {
                "processed": True,
                "processed_at": now,
                "status": "processed" if followup_success else "needs_manual_review",
                "reply_status": "missing_details_followup_sent" if followup_success else "missing_details_followup_failed",
                "reply_template_key": "mail2_followup",
                "email_classification": {"person_type": "trainer", "scenario": "trainer_details_partial"},
                "office_mail_category": "trainer_details_partial",
                "missing_requested_details": missing_requested_details,
                "missing_details_followup": followup_result,
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_error": "" if followup_success else _clean(followup_result.get("error") or followup_result.get("reason")),
                "reply_error": "" if followup_success else _clean(followup_result.get("error") or followup_result.get("reason")),
                "reply_sent": bool(followup_result.get("success")),
                "reply_sent_at": followup_result.get("sent_at") if followup_result.get("success") else None,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
            return {
                "processed": True,
                "email_id": email_doc.get("email_id"),
                "status": update["status"],
                "reason": "trainer_mail1_missing_details_followup",
                "missing_requested_details": missing_requested_details,
                "followup": followup_result,
            }

        advance_directly_to_slot_booking = initial_intent != "declined"
        if advance_directly_to_slot_booking:
            requirement_id = email_doc.get("requirement_id") or ""
            trainer_id = email_doc.get("trainer_id") or ""
            shortlist_doc = await db["shortlists"].find_one(
                {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
                {"_id": 0, "top_trainers.$": 1, "client_email": 1, "client_name": 1, "technology_needed": 1},
            ) or {}
            current_trainer = (shortlist_doc.get("top_trainers") or [current_trainer_state or {}])[0] or current_trainer_state or {}
            await _mark_shortlist_trainer_reply_received(
                db,
                {
                    **trainer_doc,
                    "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
                    "office_mail_category": "trainer_details_sent",
                },
                stage="mail1",
                status="details_received",
                reply_at=now,
            )
            # Mail 1 already requested three dated interview slots.  If the
            # trainer includes them in the interested reply, forward them to
            # the client directly instead of spending another mail on Mail 3.
            slot_intent = _slot_reply_intent(latest_reply_text)
            if slot_intent == "valid_slots":
                slot_result = await _handle_trainer_slot_reply(
                    db,
                    {
                        **trainer_doc,
                        "classification_body": latest_reply_text,
                        "source_outbound_mail_type": "mail1",
                    },
                )
            else:
                # Mail 1 already contains the requested slot format. Do not
                # generate a second slot request when the reply omits it.
                slot_result = {
                    "attempted": False,
                    "success": False,
                    "reason": "interested_reply_missing_valid_slots",
                    "intent": slot_intent,
                }
            handoff_retry_pending = _client_handoff_retry_pending(slot_result)
            update = {
                "processed": not handoff_retry_pending,
                "processed_at": now,
                "status": "processed" if slot_result.get("success") else "pending_retry" if handoff_retry_pending else "needs_manual_review",
                "reply_status": "slots_sent_to_client" if slot_result.get("success") else "client_handoff_retry_pending" if handoff_retry_pending else "interested_without_slots",
                "reply_template_key": "client_slots" if slot_result.get("success") else "trainer_interested",
                "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
                "office_mail_category": "trainer_interested",
                "trainer_details_received": not bool(missing_requested_details),
                "trainer_details_received_at": now if not missing_requested_details else None,
                "missing_requested_details": missing_requested_details,
                "slot_result": slot_result,
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": "",
                "auto_send_error": "" if slot_result.get("success") else slot_result.get("error", slot_result.get("reason", "")),
                "reply_error": "" if slot_result.get("success") else slot_result.get("error", slot_result.get("reason", "")),
                "auto_send_retry_after": None if slot_result.get("success") else slot_result.get("retry_after") if handoff_retry_pending else None,
                "reply_sent": bool(slot_result.get("success")),
                "reply_sent_at": now if slot_result.get("success") else None,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
            return {
                "processed": not handoff_retry_pending,
                "email_id": email_doc.get("email_id"),
                "status": update["status"],
                "reason": "trainer_mail1_slots_forwarded",
                "slots": slot_result,
            }
        # Defensive terminal guard: this legacy branch used to compose a
        # generic Mail 2 that repeated profile/CV/LinkedIn requests. It must
        # never send now that Mail 1 and the one-item follow-up are the only
        # permitted trainer-detail requests.
        update = {
            "processed": True,
            "processed_at": now,
            "status": "needs_manual_review",
            "reply_status": "generic_mail2_blocked",
            "reply_template_key": "",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
            "office_mail_category": "trainer_interested",
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "generic_mail2_disabled",
            "reply_sent": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "generic_mail2_disabled",
        }

        reply = _trainer_mail2_details_reply({
            **evidence_doc,
            "from_name": email_doc.get("from_name") or evidence_doc.get("from_name"),
            "trainer_name": email_doc.get("trainer_name") or current_trainer_state.get("name") or current_trainer_state.get("trainer_name"),
            "requirement": mail2_requirement,
            "missing_requested_details": missing_requested_details,
        })
        send_email_doc = {
            **email_doc,
            "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
            "office_mail_category": "trainer_interested",
        }
        auto_reply_result = await _send_client_auto_reply(db, send_email_doc, reply, email_doc.get("requirement_id") or "")
        update = {
            "processed": True,
            "processed_at": auto_reply_result.get("sent_at") or now,
            "status": "processed" if auto_reply_result.get("success") else "reply_failed",
            "reply_status": "sent" if auto_reply_result.get("success") else "failed",
            "generated_reply": reply,
            "ai_reply": reply["body"],
            "draft_reply": reply["body"],
            "reply_template_key": "mail2",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_interested"},
            "office_mail_category": "trainer_interested",
            "auto_send_candidate": True,
            "auto_send_eligible": True,
            "auto_send_ready": True,
            "auto_send_error": "" if auto_reply_result.get("success") else auto_reply_result.get("error", "Send failed"),
            "reply_error": "" if auto_reply_result.get("success") else auto_reply_result.get("error", "Send failed"),
            "reply_sent": bool(auto_reply_result.get("success")),
            "reply_sent_at": auto_reply_result.get("sent_at"),
            "reply_sent_for_message_id": auto_reply_result.get("source_gmail_message_id"),
            "sent_reply_body": auto_reply_result.get("body") or reply["body"],
            "sent_reply_subject": auto_reply_result.get("subject") or reply.get("subject"),
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        await _mark_shortlist_trainer_reply_received(
            db,
            trainer_doc,
            stage="mail1",
            status="waiting_reply2" if auto_reply_result.get("success") else "mail1_replied",
            reply_at=now,
            error="" if auto_reply_result.get("success") else auto_reply_result.get("error", "Send failed"),
        )
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "trainer_mail1_reply",
            "auto_reply": auto_reply_result,
        }

    if source_mail_type == "mail2" and email_doc.get("requirement_id") and email_doc.get("trainer_id"):
        mail2_requirement = await db["requirements"].find_one(
            {"requirement_id": email_doc.get("requirement_id")},
            {"_id": 0, "batch_flow": 1, "batch_type": 1, "requirement_type": 1},
        ) or {}
        flow_value = _clean(
            mail2_requirement.get("batch_flow")
            or mail2_requirement.get("batch_type")
            or mail2_requirement.get("requirement_type")
        ).lower()
        latest_mail2_body = _strip_quoted_email_history(body) or body
        if "proposal" in flow_value and _slot_reply_intent(latest_mail2_body) in {"valid_slots", "unclear_slots", "too_many_slots", "rejected"}:
            slot_result = await _handle_trainer_slot_reply(
                db,
                {
                    **email_doc,
                    "classification_body": latest_mail2_body,
                    "source_outbound_mail_type": "mail3",
                },
            )
            if slot_result.get("attempted"):
                success = bool(slot_result.get("success"))
                handoff_retry_pending = _client_handoff_retry_pending(slot_result)
                update = {
                    "processed": not handoff_retry_pending,
                    "processed_at": now,
                    "status": "auto_sent" if success else "pending_retry" if handoff_retry_pending else "needs_manual_review",
                    "reply_status": "slot_received" if success else "client_handoff_retry_pending" if handoff_retry_pending else "pending_review",
                    "reply_template_key": "trainer_slot_reply",
                    "trainer_slot_reply": slot_result,
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "auto_send_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
                    "reply_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
                    "auto_send_retry_after": None if success else slot_result.get("retry_after") if handoff_retry_pending else None,
                    "updated_at": _now(),
                }
                await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
                return {
                    "processed": not handoff_retry_pending,
                    "email_id": email_doc.get("email_id"),
                    "status": update["status"],
                    "reason": "proposal_mail2_slot_reply",
                    "trainer_slot_reply": slot_result,
                }

    if source_mail_type in {"mail2", "mail2_followup"} and email_doc.get("requirement_id") and email_doc.get("trainer_id"):
        mail2_requirement = await db["requirements"].find_one(
            {"requirement_id": email_doc.get("requirement_id")},
            {"_id": 0},
        ) or {}
        shortlist_state = await db["shortlists"].find_one(
            {
                "requirement_id": email_doc.get("requirement_id"),
                "top_trainers.trainer_id": email_doc.get("trainer_id"),
            },
            {"_id": 0, "top_trainers.$": 1},
        ) or {}
        current_trainer_state = (shortlist_state.get("top_trainers") or [{}])[0] or {}
        trainer_doc = {
            **email_doc,
            "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
            "classification_body": _strip_quoted_email_history(body) or body,
            "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
            "office_mail_category": "trainer_details_sent",
        }
        latest_mail2_details_body = _strip_quoted_email_history(body) or body
        # Mail 2 is a legacy thread type.  The current workflow asks for the
        # profile and interview slots in Mail 1, so a reply containing valid
        # slots must go directly to the client handoff instead of triggering
        # another request for the same trainer details.
        legacy_slot_intent = _slot_reply_intent(latest_mail2_details_body)
        if legacy_slot_intent in {"valid_slots", "unclear_slots", "too_many_slots", "rejected"}:
            slot_result = await _handle_trainer_slot_reply(
                db,
                {
                    **trainer_doc,
                    "source_outbound_mail_type": "mail3",
                },
            )
            if slot_result.get("attempted"):
                success = bool(slot_result.get("success"))
                handoff_retry_pending = _client_handoff_retry_pending(slot_result)
                update = {
                    "processed": not handoff_retry_pending,
                    "processed_at": now,
                    "status": "auto_sent" if success else "pending_retry" if handoff_retry_pending else "needs_manual_review",
                    "reply_status": "slots_sent_to_client" if success else "client_handoff_retry_pending" if handoff_retry_pending else "pending_review",
                    "reply_template_key": "client_slots" if success else "trainer_slot_reply",
                    "trainer_slot_reply": slot_result,
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "auto_send_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
                    "reply_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
                    "auto_send_retry_after": None if success else slot_result.get("retry_after") if handoff_retry_pending else None,
                    "updated_at": _now(),
                }
                await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
                return {
                    "processed": not handoff_retry_pending,
                    "email_id": email_doc.get("email_id"),
                    "status": update["status"],
                    "reason": "legacy_mail2_slots_forwarded",
                    "trainer_slot_reply": slot_result,
                }
        evidence_doc = _trainer_detail_evidence_doc(trainer_doc, current_trainer_state)
        evidence_text = evidence_doc.get("classification_body") or latest_mail2_details_body
        missing_requested_details = _trainer_missing_requested_details(evidence_text, mail2_requirement, evidence_doc)
        if missing_requested_details:
            # Do not send a follow-up Mail 2.  Mail 1 already asked for the
            # entire requirement, profile and three slots; re-asking creates
            # duplicate and confusing trainer emails.
            update = {
                "processed": True,
                "processed_at": now,
                "status": "processed",
                "reply_status": "details_recorded_waiting_for_slots",
                "reply_template_key": "trainer_details_recorded",
                "email_classification": {"person_type": "trainer", "scenario": "trainer_details_partial"},
                "office_mail_category": "trainer_details_partial",
                "missing_requested_details": missing_requested_details,
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_error": "",
                "reply_error": "",
                "reply_sent": False,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
            await _mark_shortlist_trainer_reply_received(
                db,
                trainer_doc,
                stage="mail1",
                status="details_received",
                reply_at=now,
                error="",
            )
            return {
                "processed": True,
                "email_id": email_doc.get("email_id"),
                "status": update["status"],
                "reason": "trainer_details_recorded_waiting_for_slots",
                "missing_requested_details": missing_requested_details,
            }
        await _mark_shortlist_trainer_reply_received(
            db,
            trainer_doc,
            stage="mail2",
            status="trainer_details_received",
            reply_at=now,
        )
        # A Mail 2 follow-up is only for an item missing from Mail 1. When the
        # trainer had already supplied the three slots in Mail 1, use those
        # saved slots now that the profile/details are complete. Do not start
        # the old commercial-forwarding branch or send another trainer mail.
        stored_slot_text = _clean(
            current_trainer_state.get("pending_slot_reply_text")
            or current_trainer_state.get("slot_reply_text")
            or current_trainer_state.get("availability_text")
        )
        slot_result: Dict[str, Any] = {"attempted": False, "success": False, "reason": "missing_valid_slots"}
        if _slot_reply_intent(stored_slot_text) == "valid_slots":
            slot_result = await _handle_trainer_slot_reply(
                db,
                {
                    **trainer_doc,
                    "classification_body": stored_slot_text,
                    "source_outbound_mail_type": "mail3",
                },
            )
        success = bool(slot_result.get("success"))
        handoff_retry_pending = _client_handoff_retry_pending(slot_result)
        update = {
            "processed": not handoff_retry_pending,
            "processed_at": now,
            "status": "processed" if success else "pending_retry" if handoff_retry_pending else "needs_manual_review",
            "reply_status": "slots_sent_to_client" if success else "client_handoff_retry_pending" if handoff_retry_pending else "pending_review",
            "reply_template_key": "client_slots" if success else "trainer_details_received",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
            "office_mail_category": "trainer_details_sent",
            "trainer_details_received": True,
            "trainer_details_received_at": now,
            "slot_result": slot_result,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "auto_send_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
            "reply_error": "" if success else slot_result.get("error", slot_result.get("reason", "")),
            "auto_send_retry_after": None if success else slot_result.get("retry_after") if handoff_retry_pending else None,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": not handoff_retry_pending,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "trainer_mail2_details_and_slots_forwarded" if success else "trainer_mail2_details_received_waiting_for_slots",
            "slots": slot_result,
        }

    latest_body = _strip_quoted_email_history(body)
    extraction_body = latest_body or body
    extracted = _extract_requirement_from_email(
        subject=subject,
        body=extraction_body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
    extracted = _merge_client_toc_attachment_topics(extracted, email_doc)
    extracted = _merge_existing_requirement_context(extracted, email_doc)
    extracted = await _merge_requirement_record_context(db, extracted, email_doc.get("requirement_id"))
    attachment_validation = _validate_trainer_attachments_against_requirement(email_doc, extracted)
    toc_recheck = _build_toc_recheck_state(email_doc, attachment_validation)
    if email_doc.get("email_id"):
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "attachment_validation": attachment_validation,
                "toc_recheck": toc_recheck,
                "updated_at": _now(),
            }},
        )
    classification_body = latest_body
    classification = classify_email(
        subject=subject,
        body=classification_body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
    # Finance is deliberately separate from trainer workflows.  A client PO
    # or invoice request creates a visible approval item; nothing is sent
    # until a human validates the PO/invoice values in the dashboard.
    if classification.get("scenario") in {"client_sends_po", "client_asks_invoice"}:
        now = _now()
        finance_id = f"FIN-{uuid.uuid4().hex[:10].upper()}"
        await db["finance_approvals"].update_one(
            {"source_email_id": email_doc.get("email_id") or finance_id},
            {"$set": {
                "finance_id": finance_id,
                "source_email_id": email_doc.get("email_id") or "",
                "client_email": _email_address(email_doc.get("from_email") or ""),
                "client_name": email_doc.get("from_name") or "",
                "subject": subject,
                "request_type": "po_to_invoice" if classification.get("scenario") == "client_sends_po" else "invoice_request",
                "status": "pending_human_approval",
                "notification_title": "PO / Invoice Approval Required",
                "notification_message": "Review PO/invoice details before generating or sending an invoice.",
                "attachment_names": [str(x.get("filename") or "") for x in (email_doc.get("attachments") or []) if isinstance(x, dict)],
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}}, upsert=True,
        )
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": {"processed": True, "status": "pending_approval", "reply_status": "pending_review", "office_mail_category": "finance_approval_required", "classification_reason": "po_invoice_human_approval", "finance_approval_id": finance_id, "updated_at": now}})
        return {"processed": True, "email_id": email_doc.get("email_id"), "status": "pending_approval", "reason": "finance_human_approval_required", "finance_approval_id": finance_id}
    extracted_client_requirement = bool(
        not extracted.get("is_non_client_email")
        and extracted.get("direct_request_language")
        and _has_training_domain(extracted)
    )
    if extracted_client_requirement:
        classification = {
            **classification,
            "person_type": "corporate_client",
            "scenario": "new_training_requirement",
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        extracted["is_training_request"] = True
        extracted["is_non_client_email"] = False
    non_requirement_person_types = {
        "trainer",
        "job_seeker",
        "vendor",
        "referral",
        "student",
        "media",
        "finance_legal",
        "partner",
        "internal_team",
        "system",
        "bounce",
        "ooo",
    }
    if (
        classification.get("person_type") in non_requirement_person_types
        or str(classification.get("scenario") or "").startswith("trainer_")
        or classification.get("scenario") in {
            "job_application",
            "vendor_hotlist",
            "referral",
            "student_enquiry",
            "media_enquiry",
            "finance_legal",
            "partnership",
        }
    ):
        extracted["is_non_client_email"] = True
        extracted["is_training_request"] = False
    details_later = _client_will_send_details_later(subject, classification_body)
    client_authorized_search = _client_wants_to_proceed_now(subject, classification_body)
    client_provided_details = _client_provided_requirement_details(subject, classification_body, extracted)
    client_coordination_intent = str(extracted.get("latest_coordination_intent") or "")
    if client_coordination_intent and not extracted.get("is_non_client_email"):
        classification = {
            **classification,
            "person_type": "corporate_client",
            "scenario": f"client_{client_coordination_intent}",
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        extracted["is_non_client_email"] = False
    if details_later and not extracted.get("is_non_client_email"):
        classification = {
            **classification,
            "person_type": "corporate_client",
            "scenario": "client_will_share_details_later",
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        extracted["is_non_client_email"] = False
        extracted["is_training_request"] = True
        extracted["direct_request_language"] = True
        extracted["confidence"] = max(_safe_float(extracted.get("confidence"), 0), 0.9)
    is_linked_client_requirement_reply = bool(
        email_doc.get("requirement_id")
        and _is_reply_thread(subject, email_doc)
        and extracted.get("is_training_request")
        and _has_training_domain(extracted)
    )
    if is_linked_client_requirement_reply and client_provided_details:
        classification = {
            **classification,
            "person_type": "corporate_client",
            "scenario": "client_requirement_details",
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        extracted["is_non_client_email"] = False
        extracted["is_training_request"] = True
    should_start_trainer_search = _should_start_trainer_automation(subject, email_doc, extracted)
    is_first_client_mail = bool(
        extracted.get("direct_request_language")
        and not _is_reply_thread(subject, email_doc)
        and not email_doc.get("requirement_id")
    )
    details_ready_on_client_reply = bool(
        is_linked_client_requirement_reply
        and client_provided_details
        and not details_later
    )
    explicit_trainer_authorization = bool(
        client_authorized_search
        or details_later
        or email_doc.get("client_authorized_trainer_search")
    )
    should_start_trainer_search = bool(
        should_start_trainer_search
        and not is_first_client_mail
        and (explicit_trainer_authorization or details_ready_on_client_reply)
        and extracted.get("is_training_request")
        and _has_training_domain(extracted)
    )
    if (
        extracted.get("is_training_request")
        and _has_training_domain(extracted)
        and (client_provided_details or client_authorized_search or details_later)
    ):
        extracted["confidence"] = max(_safe_float(extracted.get("confidence"), 0), 0.9)
    elif (
        extracted.get("is_training_request")
        and extracted.get("direct_request_language")
        and _has_training_domain(extracted)
        and not _is_reply_thread(subject, email_doc)
    ):
        # A first-time proposal inquiry with a clear topic is safe to acknowledge.
        # Missing logistics still prevent trainer outreach below.
        extracted["confidence"] = max(_safe_float(extracted.get("confidence"), 0), 0.9)
    reply: Dict[str, str] = {}
    template_reply: Dict[str, Any] = {}
    selected_template_key = ""
    if client_coordination_intent and not extracted.get("is_non_client_email"):
        reply = _client_coordination_reply(client_coordination_intent, extracted, subject)
        selected_template_key = f"client_{client_coordination_intent}"
    elif extracted.get("is_training_request"):
        missing_details = extracted.get("needs_clarification") or []
        has_all_required_details = _has_all_required_client_details(extracted)
        if has_all_required_details:
            reply = _client_full_details_reply(extracted)
            selected_template_key = "client_full_details_received"
        elif missing_details:
            reply = _client_proceed_ack_reply(extracted, details_later=details_later)
            selected_template_key = "client_missing_details"
        elif client_authorized_search or details_later or client_provided_details:
            reply = _client_proceed_ack_reply(extracted, details_later=details_later)
            selected_template_key = "client_proceed_ack"
        else:
            reply = _client_reply_for_requirement(extracted)
            selected_template_key = "client_missing_details"
    elif extracted.get("direct_request_language") and not extracted.get("is_non_client_email"):
        reply = _client_clarification_reply(extracted)
        selected_template_key = "client_clarification"
    else:
        template_reply = build_auto_reply(
            classification,
            extracted,
            subject=subject,
            sender_name=email_doc.get("from_name") or "",
        )
        selected_template_key = template_reply.get("template_key") or ""
        if template_reply.get("body"):
            reply = {"subject": template_reply.get("subject") or subject, "body": template_reply["body"]}

    general_client_question = bool(
        not extracted.get("is_non_client_email")
        and not extracted.get("is_training_request")
        and not client_coordination_intent
        and _looks_like_general_client_question(subject, classification_body)
        and classification.get("person_type") not in non_requirement_person_types
        and classification.get("scenario") not in SAFETY_SCENARIOS
    )
    if general_client_question:
        classification = {
            **classification,
            "person_type": "corporate_client",
            "scenario": "general_client_question",
            "confidence": max(_safe_float(classification.get("confidence"), 0), 0.95),
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        llm_reply = await _generate_general_client_question_reply(
            db, email_doc, classification, extracted, subject, classification_body,
        )
        if llm_reply:
            reply = llm_reply
            template_reply = {"auto_send_safe": True}
            selected_template_key = "gpt_general_client_question"
        else:
            # Global Template mode and an AI failure both keep the enquiry
            # moving with approved wording.  Unknown facts are never guessed.
            reply = _approved_question_reply(email_doc.get("from_name") or "")
            reply["subject"] = f"Re: {subject}" if subject else "Re: Your Enquiry"
            template_reply = {"auto_send_safe": True}
            selected_template_key = "general_client_question_template"

    # A trainer can also ask a genuine question in an existing thread.  Run
    # this only after all deterministic mail/slot/detail routes above have
    # had priority, so it cannot replace a required workflow action.
    general_trainer_question = bool(
        not general_client_question
        and classification.get("person_type") == "trainer"
        and classification.get("scenario") in {
            "general_enquiry",
            "trainer_content_doubt",
            "trainer_logistics_query",
            "trainer_payment_query",
            "trainer_onsite_travel_query",
            "trainer_recording_material_policy",
        }
        and _looks_like_general_client_question(subject, classification_body)
        and classification.get("scenario") not in SAFETY_SCENARIOS
    )
    if general_trainer_question:
        trainer_reference = reply or _approved_question_reply(email_doc.get("from_name") or "Trainer")
        ai_question_reply = await _generate_verified_question_reply(
            db,
            email_doc=email_doc,
            classification=classification,
            extracted=extracted,
            subject=subject,
            body=classification_body,
            reference_reply=trainer_reference,
            recipient_kind="trainer",
        )
        reply = ai_question_reply or trainer_reference
        classification = {
            **classification,
            "scenario": "trainer_general_question",
            "confidence": max(_safe_float(classification.get("confidence"), 0), 0.9),
            "auto_reply_allowed": True,
            "requires_human": False,
        }
        template_reply = {"auto_send_safe": True}
        selected_template_key = "gpt_trainer_question" if ai_question_reply else "trainer_question_template"

    should_humanize_workflow_reply = bool(
        reply
        and selected_template_key != "gpt_general_client_question"
        and not classification.get("requires_human")
        and (
            classification.get("person_type") == "corporate_client"
            or extracted.get("is_training_request")
            or bool(client_coordination_intent)
        )
    )
    if should_humanize_workflow_reply:
        reply = await _humanize_verified_client_reply(
            db, email_doc, classification, extracted, subject, classification_body, reply,
        )
        if reply.get("llm_generation_failed"):
            logger.warning(
                "OpenAI wording unavailable for verified workflow reply %s; using approved template %s",
                email_doc.get("email_id"),
                selected_template_key or "client_reply",
            )

    is_client_requirement_template = bool(
        extracted.get("is_training_request")
        and selected_template_key in {"client_proceed_ack", "client_missing_details", "client_full_details_received"}
    )

    is_initial_requirement_request = (
        extracted.get("direct_request_language")
        and not extracted.get("is_non_client_email")
        and not _is_reply_thread(subject, email_doc)
    )
    classifier_blocked_auto_send = bool(
        classification.get("requires_human")
        or not classification.get("auto_reply_allowed", True)
        or not template_reply.get("auto_send_safe", True)
    )
    classified_auto_reply_candidate = bool(
        template_reply.get("auto_send_safe")
        and classification.get("scenario") != "general_enquiry"
        and classification.get("person_type") not in {"unknown", "bounce", "system", "ooo"}
    )
    auto_send_candidate = bool(reply) and (
        not classifier_blocked_auto_send
        and (
            extracted.get("is_training_request")
            or extracted.get("direct_request_language")
            or is_initial_requirement_request
            or bool(client_coordination_intent)
            or general_client_question
            or general_trainer_question
            or classified_auto_reply_candidate
        )
    )
    confidence = max(_safe_float(extracted.get("confidence"), 0), _safe_float(classification.get("confidence"), 0))
    auto_send_eligible = auto_send_candidate and settings["enabled"] and confidence >= settings["threshold"]
    auto_send_ready = settings["enabled"] and auto_send_candidate and confidence >= settings["threshold"]
    auto_send_block_reason = ""
    if reply and classifier_blocked_auto_send:
        auto_send_block_reason = "requires_human_review" if classification.get("requires_human") else "classifier_auto_send_blocked"
    elif reply and not settings["enabled"]:
        auto_send_block_reason = "auto_send_disabled"
    elif reply and not auto_send_candidate:
        auto_send_block_reason = "not_auto_send_candidate"
    elif reply and confidence < settings["threshold"]:
        auto_send_block_reason = "confidence_below_threshold"

    base_update = {
        "extracted": extracted,
        "email_classification": classification,
        "requires_human": bool(classification.get("requires_human")),
        "office_mail_category": classification.get("scenario"),
        "reply_template_key": selected_template_key,
        "confidence": confidence,
        "auto_send_confidence": confidence,
        "auto_send_threshold": settings["threshold"],
        "auto_send_candidate": auto_send_candidate,
        "auto_send_eligible": auto_send_eligible,
        "auto_send_ready": auto_send_ready,
        "auto_send_block_reason": auto_send_block_reason,
        "updated_at": now,
    }
    if reply:
        base_update.update({
            "generated_reply": reply,
            "ai_reply": reply["body"],
            "draft_reply": reply["body"],
        })

    send_email_doc = {
        **email_doc,
        "email_classification": classification,
        "office_mail_category": classification.get("scenario"),
        "reply_template_key": selected_template_key,
        "classification_body": classification_body,
    }

    source_mail_type_for_routing = str(send_email_doc.get("source_outbound_mail_type") or "").strip()
    try:
        client_question_result = await _relay_client_question_answer(db, send_email_doc)
    except Exception as exc:
        logger.exception("Client question-answer relay failed for %s", email_doc.get("email_id"))
        client_question_result = {"attempted": True, "success": False, "error": str(exc)}
    if client_question_result.get("attempted"):
        question_status = "auto_sent" if client_question_result.get("success") else "pending_retry"
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                **base_update,
                "processed": bool(client_question_result.get("success")),
                "status": question_status,
                "reply_status": question_status,
                "classification_reason": "client_question_answer_relayed",
                "question_resolution": client_question_result,
                "updated_at": _now(),
            }},
        )
        return {
            "processed": bool(client_question_result.get("success")),
            "reason": "client_question_answer_relayed",
            "status": question_status,
            "question_resolution": client_question_result,
        }
    try:
        client_logistics_result = await _relay_client_logistics_answer(db, send_email_doc)
    except Exception as exc:
        logger.exception("Client logistics answer relay failed for %s", email_doc.get("email_id"))
        client_logistics_result = {"attempted": True, "success": False, "error": str(exc)}
    if client_logistics_result.get("attempted"):
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": {**base_update, "processed": True, "status": "auto_sent" if client_logistics_result.get("success") else "needs_manual_review", "reply_status": "auto_sent" if client_logistics_result.get("success") else "needs_manual_review", "classification_reason": "client_logistics_answer_relayed", "client_logistics": client_logistics_result, "updated_at": _now()}})
        return {"processed": True, "reason": "client_logistics_answer_relayed", "status": "auto_sent" if client_logistics_result.get("success") else "needs_manual_review", "client_logistics": client_logistics_result}
    try:
        trainer_logistics_result = await _handle_trainer_logistics_question(db, send_email_doc)
    except Exception as exc:
        logger.exception("Trainer logistics clarification failed for %s", email_doc.get("email_id"))
        trainer_logistics_result = {"attempted": True, "success": False, "error": str(exc)}
    if trainer_logistics_result.get("attempted"):
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": {**base_update, "processed": True, "status": "auto_sent" if trainer_logistics_result.get("success") else "needs_manual_review", "reply_status": "auto_sent" if trainer_logistics_result.get("success") else "needs_manual_review", "classification_reason": "trainer_logistics_question", "trainer_logistics": trainer_logistics_result, "updated_at": _now()}})
        return {"processed": True, "reason": "trainer_logistics_question", "status": "auto_sent" if trainer_logistics_result.get("success") else "needs_manual_review", "trainer_logistics": trainer_logistics_result}
    if general_trainer_question:
        try:
            trainer_question_result = await _handle_trainer_general_question(db, send_email_doc, reply or {})
        except Exception as exc:
            logger.exception("Trainer question resolution failed for %s", email_doc.get("email_id"))
            trainer_question_result = {"attempted": True, "success": False, "error": str(exc)}
        if trainer_question_result.get("attempted"):
            question_status = "auto_sent" if trainer_question_result.get("success") else "pending_retry"
            await db["client_emails"].update_one(
                {"email_id": email_doc.get("email_id")},
                {"$set": {
                    **base_update,
                    "processed": bool(trainer_question_result.get("success")),
                    "status": question_status,
                    "reply_status": question_status,
                    "classification_reason": "trainer_question_resolution",
                    "question_resolution": trainer_question_result,
                    "updated_at": _now(),
                }},
            )
            return {
                "processed": bool(trainer_question_result.get("success")),
                "reason": "trainer_question_resolution",
                "status": question_status,
                "question_resolution": trainer_question_result,
            }
    if source_mail_type_for_routing in {"mail3", "mail3_slot_followup", "mail3_too_many_slots", "mail4_reschedule_request"}:
        try:
            trainer_slot_result = await _handle_trainer_slot_reply(db, send_email_doc)
        except Exception as exc:
            logger.exception("Trainer slot automation failed for %s", email_doc.get("email_id"))
            trainer_slot_result = {"attempted": True, "success": False, "error": str(exc)}
        if trainer_slot_result.get("attempted"):
            handoff_retry_pending = _client_handoff_retry_pending(trainer_slot_result)
            automation = {
                "auto_send_enabled": settings["enabled"],
                "auto_send_threshold": settings["threshold"],
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": "",
                "client_authorized_search": False,
                "pending_client_reply": False,
                "sent": 1 if trainer_slot_result.get("success") else 0,
                "total": 1,
                "trainer_slot_automation": trainer_slot_result,
            }
            set_update: Dict[str, Any] = {
                **base_update,
                "status": "auto_sent" if trainer_slot_result.get("success") else "pending_retry" if handoff_retry_pending else "needs_manual_review",
                "reply_status": "auto_sent" if trainer_slot_result.get("success") else "client_handoff_retry_pending" if handoff_retry_pending else "needs_manual_review",
                "processed": not handoff_retry_pending,
                "processed_at": trainer_slot_result.get("sent_at") or now,
                "classification_reason": "trainer_slot_reply",
                "reply_template_key": "trainer_slot_reply",
                "trainer_slot_automation": trainer_slot_result,
                "mail_automation": automation,
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_retry_after": None if trainer_slot_result.get("success") else trainer_slot_result.get("retry_after") if handoff_retry_pending else None,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
            return {
                "processed": not handoff_retry_pending,
                "reason": "trainer_slot_reply",
                "status": set_update.get("status"),
                "mail_automation": automation,
                "extracted": extracted,
            }

    try:
        interview_reschedule_result = await _handle_interview_reschedule_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Interview reschedule automation failed for %s", email_doc.get("email_id"))
        interview_reschedule_result = {"attempted": True, "success": False, "error": str(exc)}
    if interview_reschedule_result.get("attempted"):
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 1 if interview_reschedule_result.get("success") else 0,
            "total": 1,
            "interview_reschedule": interview_reschedule_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if interview_reschedule_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if interview_reschedule_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": interview_reschedule_result.get("sent_at") or now,
            "classification_reason": "interview_reschedule",
            "interview_reschedule": interview_reschedule_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "interview_reschedule",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    try:
        trainer_toc_result = await _handle_trainer_toc_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Trainer ToC automation failed for %s", email_doc.get("email_id"))
        trainer_toc_result = {"attempted": True, "success": False, "error": str(exc)}
    if trainer_toc_result.get("attempted"):
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 0,
            "total": 1,
            "trainer_toc": trainer_toc_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if trainer_toc_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if trainer_toc_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": trainer_toc_result.get("sent_at") or now,
            "classification_reason": "trainer_toc_received",
            "trainer_toc": trainer_toc_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "trainer_toc_received",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    try:
        # First check if the client reply indicates the trainer was selected
        try:
            client_selection_result = await _handle_client_selection_reply(db, send_email_doc)
        except NameError:
            client_selection_result = {"attempted": False}
        if client_selection_result.get("attempted"):
            client_slot_confirmation_result = client_selection_result
        else:
            client_rejection_result = await _handle_client_rejection_reply(db, send_email_doc)
            if client_rejection_result.get("attempted"):
                client_slot_confirmation_result = client_rejection_result
            else:
                client_slot_confirmation_result = await _handle_client_slot_confirmation_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Client slot confirmation automation failed for %s", email_doc.get("email_id"))
        client_slot_confirmation_result = {"attempted": True, "success": False, "error": str(exc)}
    if client_slot_confirmation_result.get("attempted"):
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 1 if client_slot_confirmation_result.get("success") else 0,
            "total": 1,
            "client_slot_confirmation": client_slot_confirmation_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if client_slot_confirmation_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if client_slot_confirmation_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": client_slot_confirmation_result.get("sent_at") or now,
            "classification_reason": "client_slot_confirmation",
            "client_slot_confirmation": client_slot_confirmation_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "client_slot_confirmation",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    try:
        trainer_slot_result = await _handle_trainer_slot_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Trainer slot automation failed for %s", email_doc.get("email_id"))
        trainer_slot_result = {"attempted": True, "success": False, "error": str(exc)}
    if trainer_slot_result.get("attempted"):
        handoff_retry_pending = _client_handoff_retry_pending(trainer_slot_result)
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 1 if trainer_slot_result.get("success") else 0,
            "total": 1,
            "trainer_slot_automation": trainer_slot_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if trainer_slot_result.get("success") else "pending_retry" if handoff_retry_pending else "needs_manual_review",
            "reply_status": "auto_sent" if trainer_slot_result.get("success") else "client_handoff_retry_pending" if handoff_retry_pending else "needs_manual_review",
            "processed": not handoff_retry_pending,
            "processed_at": trainer_slot_result.get("sent_at") or now,
            "classification_reason": "trainer_slot_reply",
            "trainer_slot_automation": trainer_slot_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_retry_after": None if trainer_slot_result.get("success") else trainer_slot_result.get("retry_after") if handoff_retry_pending else None,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": not handoff_retry_pending,
            "reason": "trainer_slot_reply",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    try:
        trainer_negotiation_result = await _handle_trainer_commercial_negotiation_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Trainer commercial negotiation automation failed for %s", email_doc.get("email_id"))
        trainer_negotiation_result = {"attempted": True, "success": False, "error": str(exc)}
    if trainer_negotiation_result.get("attempted"):
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 1 if trainer_negotiation_result.get("success") else 0,
            "total": 1,
            "trainer_commercial_negotiation": trainer_negotiation_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if trainer_negotiation_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if trainer_negotiation_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": trainer_negotiation_result.get("sent_at") or now,
            "classification_reason": "trainer_commercial_negotiation_reply",
            "trainer_commercial_negotiation": trainer_negotiation_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "trainer_commercial_negotiation_reply",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    try:
        client_budget_result = await _handle_client_budget_reply(db, send_email_doc)
    except Exception as exc:
        logger.exception("Client budget automation failed for %s", email_doc.get("email_id"))
        client_budget_result = {"attempted": True, "success": False, "error": str(exc)}
    if client_budget_result.get("attempted"):
        automation = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "client_authorized_search": False,
            "pending_client_reply": False,
            "sent": 1 if client_budget_result.get("success") else 0,
            "total": 1,
            "client_budget_automation": client_budget_result,
        }
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "auto_sent" if client_budget_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if client_budget_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": client_budget_result.get("sent_at") or now,
            "classification_reason": "client_budget_reply",
            "reply_template_key": "client_budget_reply",
            "client_budget_automation": client_budget_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "client_budget_reply",
            "status": set_update.get("status"),
            "mail_automation": automation,
            "extracted": extracted,
        }

    if classification.get("requires_human"):
        set_update: Dict[str, Any] = {
            **base_update,
            "status": "needs_manual_review",
            "reply_status": "needs_manual_review",
            "processed": True,
            "processed_at": now,
            "classification_reason": "requires_human_review",
            "mail_automation": {
                "auto_send_enabled": settings["enabled"],
                "auto_send_threshold": settings["threshold"],
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "auto_send_block_reason": auto_send_block_reason or "requires_human_review",
                "client_authorized_search": False,
                "pending_client_reply": bool(reply),
                "sent": 0,
                "total": 0,
            },
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
            "reason": "requires_human_review",
            "status": "needs_manual_review",
            "mail_automation": set_update.get("mail_automation"),
            "extracted": extracted,
            "classification": classification,
        }

    if not extracted.get("is_training_request"):
        status = "pending_approval" if reply else "spam"
        reason = "needs_requirement_clarification" if reply else "ignored_non_client_email"
        set_update: Dict[str, Any] = {
            **base_update,
            "status": status,
            "reply_status": "pending_review" if reply else "spam",
            "processed": True,
            "processed_at": now,
            "classification_reason": reason,
        }
        if reply:
            send_result: Dict[str, Any] = {
                "auto_send_enabled": settings["enabled"],
                "auto_send_threshold": settings["threshold"],
                "auto_send_candidate": auto_send_candidate,
                "auto_send_eligible": auto_send_eligible,
                "auto_send_ready": auto_send_ready,
                "auto_send_block_reason": auto_send_block_reason,
                "client_authorized_search": False,
                "pending_client_reply": False,
                "sent": 0,
                "total": 0,
            }
            set_update["mail_automation"] = send_result
            if _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply, confidence=confidence):
                auto_reply_result = await _send_client_auto_reply(db, send_email_doc, reply)
                send_result["client_reply"] = {
                    "sent": bool(auto_reply_result.get("success")),
                    "to": auto_reply_result.get("to"),
                    "subject": auto_reply_result.get("subject"),
                    "error": auto_reply_result.get("error", ""),
                }
                if auto_reply_result.get("success"):
                    set_update.update({
                        "status": "auto_sent",
                        "reply_status": "auto_sent",
                        "reply_sent": True,
                        "reply_sent_at": auto_reply_result.get("sent_at"),
                        "reply_sent_for_message_id": auto_reply_result.get("source_gmail_message_id"),
                        "sent_reply_body": auto_reply_result.get("body") or reply["body"],
                        "sent_reply_subject": auto_reply_result.get("subject") or reply.get("subject"),
                        "auto_sent_at": auto_reply_result.get("sent_at"),
                        "auto_send_error": "",
                        "auto_send_candidate": False,
                        "auto_send_eligible": False,
                        "auto_send_ready": False,
                        "auto_send_retry_after": None,
                        "processed": True,
                        "processed_at": auto_reply_result.get("sent_at"),
                    })
                else:
                    error = auto_reply_result.get("error", "Send failed")
                    retry_after = _parse_retry_after(error)
                    set_update.update({
                        "status": "pending_approval" if retry_after else "needs_manual_review",
                        "reply_status": "pending_review" if retry_after else "needs_manual_review",
                        "reply_sent": False,
                        "auto_send_error": error,
                        "reply_error": error,
                        "auto_send_retry_after": retry_after,
                        "processed": True,
                        "processed_at": now,
                    })
            try:
                commercial_forward_result = await _forward_trainer_commercials_to_client(db, send_email_doc, classification)
            except Exception as exc:
                logger.exception("Trainer commercial forward failed for %s", email_doc.get("email_id"))
                commercial_forward_result = {"attempted": True, "success": False, "error": str(exc)}
            if commercial_forward_result.get("attempted"):
                send_result["client_commercial_forward"] = commercial_forward_result
                set_update["client_commercial_forward"] = commercial_forward_result
        unset_update = {} if reply else {"generated_reply": "", "ai_reply": "", "draft_reply": ""}
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": set_update, **({"$unset": unset_update} if unset_update else {})},
        )
        return {
            "processed": True,
            "reason": reason,
            "status": set_update.get("status"),
            "mail_automation": set_update.get("mail_automation"),
            "extracted": extracted,
        }

    status_update: Dict[str, Any] = {
        **base_update,
        "auto_send_eligible": auto_send_eligible,
        "status": "pending_approval",
        "reply_status": "pending_review",
    }
    await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": status_update})

    must_wait_for_client_details = bool(
        selected_template_key == "client_missing_details"
        and not _is_reply_thread(subject, email_doc)
        and (extracted.get("needs_clarification") or details_later)
        and not client_provided_details
        and not _has_all_required_client_details(extracted)
        and not should_start_trainer_search
        and not details_later
    )
    if must_wait_for_client_details:
        send_result: Dict[str, Any] = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": auto_send_candidate,
            "auto_send_eligible": auto_send_eligible,
            "auto_send_ready": auto_send_ready,
            "auto_send_block_reason": auto_send_block_reason,
            "client_authorized_search": False,
            "pending_client_reply": True,
            "sent": 0,
            "total": 0,
        }
        final_status = "pending_approval"
        reply_status = "pending_review"
        reply_sent_update: Dict[str, Any] = {}

        if reply and _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply, confidence=confidence):
            auto_reply_result = await _send_client_auto_reply(db, send_email_doc, reply)
            send_result["client_reply"] = {
                "sent": bool(auto_reply_result.get("success")),
                "to": auto_reply_result.get("to"),
                "subject": auto_reply_result.get("subject"),
                "error": auto_reply_result.get("error", ""),
            }
            if auto_reply_result.get("success"):
                final_status = "auto_sent"
                reply_status = "auto_sent"
                send_result["sent"] = 1
                send_result["total"] = 1
                reply_sent_update.update({
                    "reply_sent": True,
                    "reply_sent_at": auto_reply_result.get("sent_at"),
                    "reply_sent_for_message_id": auto_reply_result.get("source_gmail_message_id"),
                    "sent_reply_body": auto_reply_result.get("body") or reply["body"],
                    "sent_reply_subject": auto_reply_result.get("subject") or reply.get("subject"),
                    "auto_sent_at": auto_reply_result.get("sent_at"),
                    "auto_send_error": "",
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "auto_send_retry_after": None,
                })
            else:
                error = auto_reply_result.get("error", "Send failed")
                retry_after = _parse_retry_after(error)
                final_status = "pending_approval" if retry_after else "needs_manual_review"
                reply_status = "pending_review" if retry_after else "needs_manual_review"
                reply_sent_update.update({
                    "reply_sent": False,
                    "auto_send_error": error,
                    "reply_error": error,
                    "auto_send_retry_after": retry_after,
                })

        wait_update = {
            "requirement_created": False,
            "client_authorized_trainer_search": False,
            "pending_trainer_automation": False,
            "mail_automation": send_result,
            "processed": True,
            "processed_at": now,
            "status": final_status,
            "reply_status": reply_status,
            "classification_reason": "waiting_for_client_requirement_details",
            "updated_at": now,
            **reply_sent_update,
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": wait_update})
        return {
            "processed": True,
            "reason": "waiting_for_client_requirement_details",
            "status": final_status,
            "mail_automation": send_result,
            "extracted": extracted,
        }

    try:
        requirement_result = await _create_requirement(
            email_doc,
            extracted,
            db,
            reuse_existing_client_requirement=not force_new_requirement and _is_reply_thread(subject, email_doc),
            force_new_requirement=force_new_requirement,
        )
        if requirement_result.get("deleted"):
            deleted_requirement_id = requirement_result.get("deleted_requirement_id") or email_doc.get("requirement_id") or ""
            skip_update = {
                "status": "deleted",
                "reply_status": "deleted",
                "deleted": True,
                "deleted_requirement_id": deleted_requirement_id,
                "processed": True,
                "processed_at": now,
                "updated_at": now,
                "pending_trainer_automation": False,
                "client_authorized_trainer_search": False,
            }
            await db["client_emails"].update_one(
                {"email_id": email_doc.get("email_id")},
                {"$set": skip_update, "$unset": {"requirement_id": ""}},
            )
            return {
                "processed": True,
                "reason": "requirement_deleted",
                "status": "deleted",
                "deleted_requirement_id": deleted_requirement_id,
            }
        requirement_id = requirement_result.get("requirement_id")
        if not requirement_id:
            raise RuntimeError("Core API did not return a requirement_id")

        existing_mail_automation = email_doc.get("mail_automation") or {}
        already_replied_to_latest = _has_replied_to_latest_message(email_doc)
        send_result: Dict[str, Any] = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": auto_send_candidate,
            "auto_send_eligible": auto_send_eligible,
            "auto_send_ready": auto_send_ready,
            "auto_send_block_reason": auto_send_block_reason,
            "client_authorized_search": client_authorized_search,
            "pending_client_reply": bool(reply and is_client_requirement_template and not already_replied_to_latest),
            "sent": 0,
            "total": 0,
        }
        if not should_start_trainer_search:
            for key in ("client_reply", "intel_search", "trainer_mail"):
                if key in existing_mail_automation:
                    send_result[key] = existing_mail_automation[key]
            if _safe_int(existing_mail_automation.get("sent"), 0) > 0:
                send_result["sent"] = _safe_int(existing_mail_automation.get("sent"), 0)
                send_result["total"] = _safe_int(existing_mail_automation.get("total"), send_result["sent"])
        final_status = "auto_sent" if already_replied_to_latest else "pending_approval"
        reply_status = "auto_sent" if already_replied_to_latest else "pending_approval"
        reply_sent_update: Dict[str, Any] = {}

        needs_corrective_full_details_reply = bool(
            already_replied_to_latest
            and selected_template_key == "client_full_details_received"
            and reply
        )
        should_auto_send_reply = (
            needs_corrective_full_details_reply
            or _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply, confidence=confidence)
        )
        if should_auto_send_reply:
            auto_reply_result = await _send_client_auto_reply(db, {**send_email_doc, "requirement_id": requirement_id}, reply, requirement_id)
            send_result["client_reply"] = {
                "sent": bool(auto_reply_result.get("success")),
                "to": auto_reply_result.get("to"),
                "subject": auto_reply_result.get("subject"),
                "error": auto_reply_result.get("error", ""),
            }
            if auto_reply_result.get("success"):
                final_status = "auto_sent"
                reply_status = "auto_sent"
                reply_sent_update.update({
                    "reply_sent": True,
                    "reply_sent_at": auto_reply_result.get("sent_at"),
                    "reply_sent_for_message_id": auto_reply_result.get("source_gmail_message_id"),
                    "sent_reply_body": auto_reply_result.get("body") or reply["body"],
                    "sent_reply_subject": auto_reply_result.get("subject") or reply.get("subject"),
                    "auto_sent_at": auto_reply_result.get("sent_at"),
                    "auto_send_error": "",
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "auto_send_retry_after": None,
                })
                if should_start_trainer_search:
                    try:
                        trainer_send_result = await _send_initial_trainer_mail(requirement_id, extracted)
                        trainer_sent_count = _safe_int(trainer_send_result.get("sent"), 0)
                        send_result["trainer_mail"] = trainer_send_result
                        send_result["sent"] = trainer_sent_count
                        send_result["total"] = _safe_int(trainer_send_result.get("total"), trainer_sent_count)
                        reply_sent_update.update(_trainer_automation_update(trainer_send_result))
                        if (
                            trainer_sent_count == 0
                            and _safe_int(trainer_send_result.get("total"), 0) > 0
                            and reply_sent_update.get("trainer_automation_status") == "failed"
                        ):
                            final_status = "trainer_email_failed"
                    except Exception as exc:
                        logger.exception("Trainer automation failed after auto client reply for %s", email_doc.get("email_id"))
                        send_result["trainer_mail"] = {"sent": 0, "error": str(exc)}
                        final_status = "trainer_email_failed"
                        reply_sent_update.update({
                            "trainer_automation_status": "failed",
                            "trainer_automation_error": str(exc),
                            "trainer_automation_failed_at": _now(),
                            "pending_trainer_automation": True,
                            "auto_send_retry_after": _parse_retry_after(str(exc)),
                        })
            else:
                error = auto_reply_result.get("error", "Send failed")
                retry_after = _parse_retry_after(error)
                final_status = "pending_approval" if retry_after else "needs_manual_review"
                reply_status = "pending_review" if retry_after else "needs_manual_review"
                reply_sent_update.update({
                    "reply_sent": False,
                    "auto_send_error": error,
                    "reply_error": error,
                    "auto_send_retry_after": retry_after,
                })

        trainer_already_handled = "trainer_automation_status" in reply_sent_update
        if should_start_trainer_search and not trainer_already_handled:
            try:
                trainer_send_result = await _send_initial_trainer_mail(requirement_id, extracted)
                trainer_sent_count = _safe_int(trainer_send_result.get("sent"), 0)
                send_result["trainer_mail"] = trainer_send_result
                send_result["sent"] = trainer_sent_count
                send_result["total"] = _safe_int(trainer_send_result.get("total"), trainer_sent_count)
                reply_sent_update.update(_trainer_automation_update(trainer_send_result))
                if trainer_sent_count == 0 and _safe_int(trainer_send_result.get("total"), 0) > 0 and reply_sent_update.get("trainer_automation_status") == "failed":
                    final_status = "trainer_email_failed"
            except Exception as exc:
                logger.exception("Trainer automation retry failed for %s", email_doc.get("email_id"))
                send_result["trainer_mail"] = {"sent": 0, "error": str(exc)}
                final_status = "trainer_email_failed"
                reply_sent_update.update({
                    "trainer_automation_status": "failed",
                    "trainer_automation_error": str(exc),
                    "trainer_automation_failed_at": _now(),
                    "pending_trainer_automation": True,
                    "auto_send_retry_after": _parse_retry_after(str(exc)),
                })

        update = {
            "requirement_id": requirement_id,
            "requirement_created": True,
            "requirement_created_at": now,
            "client_authorized_trainer_search": client_authorized_search,
            "pending_trainer_automation": should_start_trainer_search,
            "mail_automation": send_result,
            "processed": True,
            "processed_at": now,
            "status": final_status,
            "reply_status": reply_status,
            "updated_at": now,
            **reply_sent_update,
        }
        if force_new_requirement:
            update.update({
                "deleted": False,
                "deleted_at": None,
                "deleted_requirement_id": "",
            })
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "requirement_id": requirement_id,
            "status": final_status,
            "mail_automation": send_result,
        }
    except Exception as exc:
        logger.exception("Client requirement automation failed for %s", email_doc.get("email_id"))
        fallback_update: Dict[str, Any] = {
            "status": "needs_manual_review",
            "reply_status": "needs_manual_review",
            "automation_error": str(exc),
            "updated_at": _now(),
        }
        fallback_mail_automation: Dict[str, Any] = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": auto_send_candidate,
            "auto_send_eligible": auto_send_eligible,
            "auto_send_ready": auto_send_ready,
            "auto_send_block_reason": auto_send_block_reason,
            "client_authorized_search": client_authorized_search,
            "pending_client_reply": bool(reply and is_client_requirement_template),
            "sent": 0,
            "total": 0,
        }
        if reply and _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply, confidence=confidence):
            try:
                auto_reply_result = await _send_client_auto_reply(db, send_email_doc, reply)
                fallback_mail_automation["client_reply"] = {
                    "sent": bool(auto_reply_result.get("success")),
                    "to": auto_reply_result.get("to"),
                    "subject": auto_reply_result.get("subject"),
                    "error": auto_reply_result.get("error", ""),
                }
                if auto_reply_result.get("success"):
                    fallback_update.update({
                        "status": "auto_sent",
                        "reply_status": "auto_sent",
                        "reply_sent": True,
                        "reply_sent_at": auto_reply_result.get("sent_at"),
                        "reply_sent_for_message_id": auto_reply_result.get("source_gmail_message_id"),
                        "sent_reply_body": auto_reply_result.get("body") or reply["body"],
                        "sent_reply_subject": auto_reply_result.get("subject") or reply.get("subject"),
                        "auto_sent_at": auto_reply_result.get("sent_at"),
                        "auto_send_error": "",
                        "auto_send_retry_after": None,
                        "processed": True,
                        "processed_at": auto_reply_result.get("sent_at") or _now(),
                    })
                else:
                    error = auto_reply_result.get("error", "Send failed")
                    fallback_update.update({
                        "reply_sent": False,
                        "auto_send_error": error,
                        "reply_error": error,
                        "auto_send_retry_after": _parse_retry_after(error),
                    })
            except Exception as reply_exc:
                logger.exception("Fallback client auto-reply failed for %s", email_doc.get("email_id"))
                fallback_update.update({
                    "reply_sent": False,
                    "auto_send_error": str(reply_exc),
                    "reply_error": str(reply_exc),
                    "auto_send_retry_after": _parse_retry_after(str(reply_exc)),
                })
        fallback_update["mail_automation"] = fallback_mail_automation
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": fallback_update},
        )
        return {
            "processed": bool(fallback_update.get("processed")),
            "reason": "automation_failed",
            "error": str(exc),
            "status": fallback_update.get("status"),
            "mail_automation": fallback_mail_automation,
        }


async def _find_existing_client_email_for_reply(
    db: AsyncIOMotorDatabase,
    from_email: str,
    subject: Any,
    message_id: str,
    thread_message_ids: List[str],
    is_thread_reply: bool,
) -> Optional[Dict[str, Any]]:
    message_id_candidates = _message_id_candidates(message_id)
    if message_id_candidates:
        exact_match = await db["client_emails"].find_one(
            {
                "gmail_message_id": {"$in": message_id_candidates},
                "deleted": {"$ne": True},
                "status": {"$ne": "deleted"},
                "reply_status": {"$ne": "deleted"},
            },
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if exact_match:
            return exact_match
        deleted_exact_match = await db["client_emails"].find_one(
            {
                "gmail_message_id": {"$in": message_id_candidates},
                "$or": [
                    {"deleted": True},
                    {"status": "deleted"},
                    {"reply_status": "deleted"},
                ],
            },
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if deleted_exact_match:
            return deleted_exact_match

    if is_thread_reply and thread_message_ids:
        message_match = await db["client_emails"].find_one(
            {
                "deleted": {"$ne": True},
                "status": {"$ne": "deleted"},
                "reply_status": {"$ne": "deleted"},
                "$or": [
                    {"latest_gmail_message_id": {"$in": thread_message_ids}},
                    {"thread_message_ids": {"$in": thread_message_ids}},
                    {"in_reply_to": {"$in": thread_message_ids}},
                ],
            },
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if message_match:
            return message_match

    if not from_email or not is_thread_reply:
        return None

    cursor = (
        db["client_emails"]
        .find(
            {
                "from_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"},
                "requirement_id": {"$exists": True, "$nin": ["", None]},
                "deleted": {"$ne": True},
                "status": {"$nin": ["spam", "rejected"]},
                "reply_status": {"$ne": "deleted"},
            },
            {"_id": 0},
        )
        .sort("updated_at", -1)
        .limit(25)
    )
    async for candidate in cursor:
        if _subjects_match_thread(subject, candidate.get("subject")):
            return candidate
    return None


async def _find_outbound_log_for_reply(
    db: AsyncIOMotorDatabase,
    from_email: str,
    subject: Any,
    message_ids: List[str],
    body: Any = "",
    received_at: Any = None,
    is_thread_reply: bool = False,
) -> Optional[Dict[str, Any]]:
    if not from_email:
        return None

    received_dt = _parse_datetime(received_at)
    sent_before_reply_query: Dict[str, Any] = {}
    if received_dt:
        sent_before_reply_query = {
            "$or": [
                {"sent_at": {"$lte": received_dt}},
                {"created_at": {"$lte": received_dt}},
                {"sent_at": {"$exists": False}, "created_at": {"$exists": False}},
            ]
        }

    message_id_candidates = _message_id_candidates(*message_ids)
    if message_id_candidates:
        exact_query: Dict[str, Any] = {
                "direction": "outbound",
                "status": "sent",
                "gmail_message_id": {"$in": message_id_candidates},
                "$or": [
                    {"recipient": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                    {"to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                ],
        }
        if sent_before_reply_query:
            exact_query = {"$and": [exact_query, sent_before_reply_query]}
        exact = await db["email_logs"].find_one(
            exact_query,
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if exact:
            return exact

    reply_ref = _extract_trainer_reply_ref(subject, body)
    if reply_ref:
        ref_query: Dict[str, Any] = {
            "direction": "outbound",
            "status": "sent",
            "requirement_id": reply_ref["requirement_id"],
            "trainer_id": reply_ref["trainer_id"],
            "$or": [
                {"recipient": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                {"to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
            ],
        }
        if sent_before_reply_query:
            ref_query = {"$and": [ref_query, sent_before_reply_query]}
        ref_candidates = await (
            db["email_logs"]
            .find(
                ref_query,
                {"_id": 0},
            )
            .sort("created_at", -1)
            .limit(25)
            .to_list(25)
        )
        if ref_candidates:
            ref_candidates.sort(
                key=lambda log: (
                    _outbound_reply_stage_priority(log),
                    str(log.get("created_at") or ""),
                ),
                reverse=True,
            )
            for candidate in ref_candidates:
                if _subjects_match_thread(subject, candidate.get("subject")):
                    return candidate
            return ref_candidates[0]

    # A sender may later contact us with a new requirement. Do not attach that
    # message to an old trainer outreach merely because the address and subject
    # happen to be similar; only thread replies may use this loose fallback.
    if not is_thread_reply:
        return None

    fallback_query: Dict[str, Any] = {
        "direction": "outbound",
        "status": "sent",
        "requirement_id": {"$exists": True, "$nin": ["", None]},
        "$or": [
            {"recipient": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
            {"to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
        ],
    }
    if sent_before_reply_query:
        fallback_query = {"$and": [fallback_query, sent_before_reply_query]}
    cursor = (
        db["email_logs"]
        .find(
            fallback_query,
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(25)
    )
    async for log in cursor:
        if _subjects_match_thread(subject, log.get("subject")):
            return log
    return None


def _classify_inbound_attachment(attachment: Dict[str, Any], subject: str = "", body: str = "") -> str:
    """Route inbound documents before parsing; filenames alone are not CV proof."""
    filename = _clean((attachment or {}).get("filename")).lower()
    if re.search(r"\b(?:toc|agenda|curriculum|syllabus|course[ _-]?outline|module[ _-]?wise)\b", filename):
        return "toc"
    if re.search(r"\b(?:lab[ _-]?(?:cost|pricing|quote)|commercials?|quotation|pricing|budget)\b", filename):
        return "lab_cost"
    if re.search(r"\b(?:cv|resume|trainer[ _-]?profile|consultant[ _-]?profile|biodata)\b", filename):
        return "cv"
    context = f"{subject}\n{body[:1500]}".lower()
    mentioned = {
        "toc": bool(re.search(r"\b(?:toc|agenda|curriculum|syllabus|course[ _-]?outline)\b", context)),
        "lab_cost": bool(re.search(r"\b(?:lab[ _-]?(?:cost|pricing|quote)|commercials?|quotation|pricing|budget)\b", context)),
        "cv": bool(re.search(r"\b(?:cv|resume|trainer[ _-]?profile|consultant[ _-]?profile|biodata)\b", context)),
    }
    # If the mail talks about just one document type, use it.  Mixed or vague
    # mail is kept as "other" for review rather than mis-parsing a TOC as a CV.
    if sum(mentioned.values()) == 1:
        return next(kind for kind, present in mentioned.items() if present)
    return "other"


def _extract_attachment_pages(attachment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract page/section text so every later claim has source evidence."""
    filename = _clean((attachment or {}).get("filename"))
    encoded = (attachment or {}).get("content_base64")
    if not filename or not encoded:
        return []
    try:
        file_bytes = base64.b64decode(encoded, validate=True)
        lower = filename.lower()
        if lower.endswith(".pdf"):
            import fitz
            with fitz.open(stream=file_bytes, filetype="pdf") as document:
                pages = [
                    {"page": index + 1, "text": page.get_text("text")[:12000]}
                    for index, page in enumerate(document)
                ]
                # Scanned PDFs have no usable text layer. OCR only those pages
                # so normal PDFs remain fast and local (no AI/API charge).
                if not any(len(str(page.get("text") or "").strip()) >= 50 for page in pages):
                    import pytesseract
                    from PIL import Image
                    for index, page in enumerate(document):
                        image = Image.open(io.BytesIO(page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")))
                        pages[index] = {"page": index + 1, "text": pytesseract.image_to_string(image)[:12000], "ocr": True}
                return pages
        if lower.endswith(".docx"):
            from docx import Document
            document = Document(io.BytesIO(file_bytes))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    parts.extend(cell.text for cell in row.cells if cell.text.strip())
            return [{"page": 1, "text": "\n".join(parts)[:50000]}]
        if lower.endswith(".doc"):
            # Legacy Word documents need the container's antiword reader.
            with tempfile.NamedTemporaryFile(suffix=".doc") as temporary_file:
                temporary_file.write(file_bytes)
                temporary_file.flush()
                result = subprocess.run(
                    ["antiword", temporary_file.name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            if result.returncode == 0 and result.stdout.strip():
                return [{"page": 1, "text": result.stdout[:50000]}]
        if lower.endswith(".xlsx"):
            from openpyxl import load_workbook
            workbook = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            pages = []
            for sheet in workbook.worksheets:
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value not in (None, "")]
                    if values:
                        rows.append(" | ".join(values))
                if rows:
                    pages.append({"page": f"Sheet: {sheet.title}", "text": "\n".join(rows)[:50000]})
            return pages
        if lower.endswith(".xls"):
            import xlrd
            workbook = xlrd.open_workbook(file_contents=file_bytes)
            pages = []
            for sheet in workbook.sheets():
                rows = []
                for row_index in range(sheet.nrows):
                    values = [str(value).strip() for value in sheet.row_values(row_index) if str(value).strip()]
                    if values:
                        rows.append(" | ".join(values))
                if rows:
                    pages.append({"page": f"Sheet: {sheet.name}", "text": "\n".join(rows)[:50000]})
            return pages
        if lower.endswith((".txt", ".csv")):
            return [{"page": 1, "text": file_bytes.decode("utf-8", errors="replace")[:50000]}]
    except Exception:
        logger.exception("Could not extract attachment text for %s", filename)
    return []


def _evidence_lines(pages: List[Dict[str, Any]], pattern: str, limit: int = 5) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for page in pages:
        for line_number, line in enumerate(str(page.get("text") or "").splitlines(), start=1):
            if re.search(pattern, line, re.IGNORECASE):
                evidence.append({"page": page.get("page", 1), "line": line_number, "text": line[:500]})
                if len(evidence) >= limit:
                    return evidence
    return evidence


def _attachment_analysis(attachment: Dict[str, Any], subject: str = "", body: str = "") -> Dict[str, Any]:
    filename = _clean((attachment or {}).get("filename"))
    attachment_type = _classify_inbound_attachment(attachment, subject, body)
    pages = _extract_attachment_pages(attachment)
    text = "\n".join(str(page.get("text") or "") for page in pages)[:50000]
    lower = text.lower()
    technologies = [technology for technology in KNOWN_TECHNOLOGIES if technology.lower() in lower]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    toc_rows = [line for line in lines if re.search(r"\b(?:day|module|session|agenda|topic)\b", line, re.IGNORECASE)][:80]
    topic_candidates = [line for line in lines if len(line) >= 3][:180]
    return {
        "filename": _clean(attachment.get("filename")),
        "attachment_type": attachment_type,
        "text_extracted": bool(text),
        "text_length": len(text),
        "extracted_text": text,
        "page_count": len(pages),
        "ocr_used": any(bool(page.get("ocr")) for page in pages),
        "ocr_required": filename.lower().endswith(".pdf") and len(text.strip()) < 50,
        "technologies": technologies,
        "toc_rows": toc_rows if attachment_type == "toc" else [],
        "topic_candidates": topic_candidates if attachment_type == "toc" else [],
        "evidence": {
            "experience": _evidence_lines(pages, r"\b\d+(?:\.\d+)?\+?\s*(?:years?|yrs?)\b"),
            "projects": _evidence_lines(pages, r"\b(?:project|implementation|delivered|client)\b"),
            "skills": _evidence_lines(pages, r"\b(?:skills?|technologies|tools?)\b"),
            "toc": _evidence_lines(pages, r"\b(?:day|module|session|agenda|topic)\b"),
        },
    }


async def _extract_profiles_from_attachments(
    attachments: List[Dict[str, Any]],
    subject: str = "",
    body: str = "",
) -> List[Dict[str, Any]]:
    """Parse safe inbound CV attachments through the resume service.

    The Gmail client only retains allow-listed attachments up to its size cap.
    This function deliberately uses only those retained bytes and never treats a
    filename alone as proof of a trainer's experience.
    """
    profiles: List[Dict[str, Any]] = []
    for attachment in attachments or []:
        filename = _clean((attachment or {}).get("filename"))
        encoded = (attachment or {}).get("content_base64")
        analysis = _attachment_analysis(attachment, subject, body)
        attachment["analysis"] = analysis
        attachment_type = analysis["attachment_type"]
        attachment["attachment_type"] = attachment_type
        if attachment_type != "cv" or not filename.lower().endswith((".pdf", ".docx")) or not encoded:
            continue
        try:
            file_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            logger.warning("Skipping invalid encoded attachment %s", filename)
            continue
        if not file_bytes:
            continue
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await _post_with_local_fallback(
                    client,
                    f"{DOCUMENT_SERVICE_URL}/api/v1/documents/resume/upload",
                    files={"file": (filename, file_bytes, attachment.get("content_type") or "application/octet-stream")},
                )
            if response.status_code >= 400:
                logger.warning("Resume attachment parsing failed for %s: HTTP %s", filename, response.status_code)
                continue
            result = response.json()
            profile = result.get("profile") if isinstance(result, dict) else None
            if isinstance(profile, dict) and profile:
                profiles.append({"filename": filename, **profile})
        except Exception:
            logger.exception("Resume attachment parsing failed for %s", filename)
    return profiles


def _validate_trainer_attachments_against_requirement(email_doc: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Evidence-based CV/TOC comparison; recommendations never alter a CV."""
    attachments = email_doc.get("attachments") or []
    analyses = [item.get("analysis") for item in attachments if isinstance(item, dict) and isinstance(item.get("analysis"), dict)]
    profiles = [item for item in (email_doc.get("attachment_profiles") or []) if isinstance(item, dict)]
    requirement_technology = _clean(extracted.get("technology_needed") or extracted.get("technology") or extracted.get("domain"))
    required_terms = _attachment_requirement_terms(extracted, requirement_technology)
    generated_toc_text = _clean(
        extracted.get("generated_toc_text")
        or extracted.get("generated_toc")
        or extracted.get("toc_text")
        or extracted.get("toc_content")
        or extracted.get("toc")
        or extracted.get("course_agenda")
        or extracted.get("topics")
        or extracted.get("custom_topics")
        or ""
    )
    generated_toc_available = bool(
        generated_toc_text
        and (
            extracted.get("toc_action") == "generate_by_clahan"
            or extracted.get("toc_generated")
            or extracted.get("generated_toc_id")
            or extracted.get("toc_id")
            or extracted.get("scope_attached")
        )
    )
    profile_text = " ".join(
        " ".join(map(str, profile.get(key) or [])) if isinstance(profile.get(key), list) else str(profile.get(key) or "")
        for profile in profiles for key in ("skills", "summary", "technology_category", "secondary_categories")
    ) + " " + " ".join(
        str(analysis.get("extracted_text") or "")
        for analysis in analyses if analysis.get("attachment_type") == "cv"
    )
    profile_text = profile_text.lower()
    toc_text = " ".join(
        str(analysis.get("extracted_text") or "")
        for analysis in analyses if analysis.get("attachment_type") == "toc"
    )
    if generated_toc_available:
        toc_text = f"{toc_text}\n{requirement_technology}\n{generated_toc_text}"
    toc_text = toc_text.lower()
    profile_matches = [term for term in required_terms if term.lower() in profile_text]
    toc_matches = [term for term in required_terms if term.lower() in toc_text]
    profile_gaps = [term for term in required_terms if term not in profile_matches]
    toc_gaps = [term for term in required_terms if term not in toc_matches]
    domain_match = bool(requirement_technology and requirement_technology.lower() in profile_text)
    project_evidence = []
    for analysis in analyses:
        if analysis.get("attachment_type") != "cv":
            continue
        for evidence in (analysis.get("evidence") or {}).get("projects") or []:
            line = _clean(evidence.get("text"))
            if not line:
                continue
            relevant = any(term.lower() in line.lower() for term in required_terms)
            project_evidence.append({**evidence, "relevant_to_requirement": relevant})
    relevant_projects = [item for item in project_evidence if item.get("relevant_to_requirement")]
    project_status = "relevant_project_found" if relevant_projects else "basic_project_evidence" if project_evidence else "not_available"
    actions: List[str] = []
    if not profiles:
        actions.append("Ask the trainer to attach a readable PDF/DOCX CV or trainer profile.")
    elif profile_gaps:
        actions.append(f"Ask the trainer to confirm verified {', '.join(profile_gaps)} experience or projects.")
    has_toc_evidence = generated_toc_available or any(analysis.get("attachment_type") == "toc" for analysis in analyses)
    if not has_toc_evidence:
        actions.append("Ask the trainer for a day-wise TOC/agenda.")
    elif toc_gaps:
        actions.append(f"Ask the trainer to add or explain coverage for {', '.join(toc_gaps)} in the TOC.")
    score_parts = [
        35 if profiles else 0,
        25 if profiles and any(_safe_float(profile.get("experience_years"), 0) > 0 for profile in profiles) else 0,
        20 if domain_match else 0,
        20 if has_toc_evidence and bool(toc_matches) else 0,
    ]
    match_score = sum(score_parts)
    return {
        "requirement_technology": requirement_technology,
        "required_topics": required_terms,
        "domain_match": domain_match,
        "matched_profile_topics": profile_matches,
        "matched_toc_topics": toc_matches,
        "project_status": project_status,
        "project_evidence": (relevant_projects or project_evidence)[:5],
        "profile_attachment_count": len(profiles),
        "toc_attachment_count": sum(1 for analysis in analyses if analysis.get("attachment_type") == "toc"),
        "generated_toc_evidence": generated_toc_available,
        "toc_evidence_source": "generated_or_saved" if generated_toc_available else "attachment" if any(analysis.get("attachment_type") == "toc" for analysis in analyses) else "",
        "lab_cost_attachment_count": sum(1 for analysis in analyses if analysis.get("attachment_type") == "lab_cost"),
        "profile_gaps": profile_gaps,
        "toc_gaps": toc_gaps,
        "match_score": match_score,
        "match_status": "ready" if match_score >= 80 else "needs_update" if match_score >= 35 else "incomplete",
        "recommended_actions": actions,
        "evidence_only": True,
    }


def _merge_client_toc_attachment_topics(extracted: Dict[str, Any], email_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Add explicit client TOC rows to the requirement before trainer shortlist matching."""
    attachment_topics: List[str] = []
    for attachment in email_doc.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        analysis = attachment.get("analysis") or {}
        if analysis.get("attachment_type") != "toc":
            continue
        attachment_topics.extend(_clean(item) for item in analysis.get("topic_candidates") or [] if _clean(item))
    if not attachment_topics:
        return extracted
    existing = extracted.get("topics") or extracted.get("custom_topics") or ""
    existing_text = "\n".join(existing) if isinstance(existing, list) else str(existing)
    combined = [line for line in (existing_text.splitlines() + attachment_topics) if _clean(line)]
    unique: List[str] = []
    for line in combined:
        value = _clean(line)
        if value and value.lower() not in {item.lower() for item in unique}:
            unique.append(value)
    return {
        **extracted,
        "topics": "\n".join(unique[:180]),
        "custom_topics": "\n".join(unique[:180]),
        "attachment_topics": attachment_topics[:180],
        "scope_attached": True,
    }


def _attachment_requirement_terms(extracted: Dict[str, Any], technology: str) -> List[str]:
    """Get the client domain plus explicit scope subtopics, without guessing synonyms."""
    values: List[str] = [technology] if technology else []
    for key in ("topics", "custom_topics", "required_skills", "skills"):
        value = extracted.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.extend(re.split(r"[,;\n•|]+", str(value)))
    ignored = {"topic", "topics", "scope", "training", "course", "agenda", "toc", "table of contents"}
    result: List[str] = []
    for value in values:
        term = _clean(str(value).strip(" -:*"))
        normalized = term.lower()
        if len(term) < 3 or normalized in ignored or normalized in {item.lower() for item in result}:
            continue
        result.append(term)
    return result[:80]


def _build_toc_recheck_state(email_doc: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, Any]:
    """Store attachment review status only; trainer follow-up is intentionally manual."""
    toc_gaps = [str(item) for item in validation.get("toc_gaps") or [] if _clean(item)]
    has_toc = bool(validation.get("toc_attachment_count") or validation.get("generated_toc_evidence"))
    needs_review = bool(toc_gaps or not has_toc)
    previous = email_doc.get("toc_recheck") if isinstance(email_doc.get("toc_recheck"), dict) else {}
    if not needs_review:
        return {
            "status": "resolved",
            "resolved_at": _now(),
            "required_topics": [],
            "reason": "TOC evidence now covers the requested topic.",
            "previous_status": previous.get("status", ""),
        }
    topics = toc_gaps or [str(validation.get("requirement_technology") or "the requested training topic")]
    return {
        "status": "needs_profile_review",
        "created_at": previous.get("created_at") or _now(),
        "last_checked_at": _now(),
        "required_topics": topics,
        "reason": "No day-wise TOC was attached." if not has_toc else "The attached TOC does not evidence all requested topics.",
        "review_note": "Use the trainer profile template only after verifying the domain and subtopic evidence.",
        "recheck_on_next_trainer_reply": True,
        "auto_send": False,
    }


async def _persist_client_email_from_reply(db: AsyncIOMotorDatabase, reply: dict) -> str:
    raw_from = reply.get("from_raw") or reply.get("from_email") or ""
    parsed_name, parsed_email = parseaddr(raw_from)
    from_email = _email_address(reply.get("from_email") or parsed_email or raw_from)
    from_name = _clean(parsed_name) or from_email.split("@")[0]
    msg_id_hdr = reply.get("message_id_header", "")
    in_reply_to = reply.get("in_reply_to")
    references = reply.get("references")
    message_ids = _message_id_candidates(msg_id_hdr, in_reply_to, references)
    outbound_reply_message_ids = _message_id_candidates(in_reply_to, references)
    is_thread_reply = bool(
        in_reply_to
        or references
        or re.match(r"^\s*(?:re|fw|fwd)\s*:", str(reply.get("subject") or ""), flags=re.IGNORECASE)
    )
    # First reuse the exact Gmail message when it was already imported.  This
    # is deliberately done before outbound lookup: an imported reply can have
    # a valid outbound handoff reference, but it must never be inserted again
    # on every inbox sync.
    existing_exact = None
    if msg_id_hdr:
        existing_exact = await db["client_emails"].find_one(
            {
                "$or": [
                    {"gmail_message_id": msg_id_hdr},
                    {"latest_gmail_message_id": msg_id_hdr},
                ],
            },
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
    # Then resolve the actual outbound Gmail message referenced by a new
    # reply. The same client can have older emails with the same subject.
    # The same client can have older emails with the same subject/trainer; using
    # a previously merged client email first can attach a fresh slot choice to
    # that old requirement and create the meeting for the wrong slot.
    related_outbound = await _find_outbound_log_for_reply(
        db,
        from_email=from_email,
        subject=reply.get("subject"),
        message_ids=outbound_reply_message_ids,
        body=reply.get("body") or "",
        received_at=reply.get("received_at"),
        is_thread_reply=is_thread_reply,
    )
    existing = existing_exact or (
        None if related_outbound else await _find_existing_client_email_for_reply(
            db,
            from_email=from_email,
            subject=reply.get("subject"),
            message_id=msg_id_hdr,
            thread_message_ids=message_ids,
            is_thread_reply=is_thread_reply,
        )
    )
    now = _now()
    previous_message_id = _clean(
        (existing or {}).get("latest_gmail_message_id")
        or (existing or {}).get("gmail_message_id")
        or ""
    )
    is_new_inbound_message = bool(msg_id_hdr and msg_id_hdr != previous_message_id)
    if related_outbound is None and (not existing or is_new_inbound_message or not existing.get("source_outbound_email_id")):
        related_outbound = await _find_outbound_log_for_reply(
            db,
            from_email=from_email,
            subject=reply.get("subject"),
            message_ids=outbound_reply_message_ids,
            body=reply.get("body") or "",
            received_at=reply.get("received_at"),
            is_thread_reply=is_thread_reply,
        )
    attachment_profiles = list((existing or {}).get("attachment_profiles") or [])
    if not existing or is_new_inbound_message:
        attachment_profiles = await _extract_profiles_from_attachments(
            reply.get("attachments") or [],
            reply.get("subject") or "",
            reply.get("full_body") or reply.get("body") or "",
        )
    update_fields = {
        "from_email": from_email,
        "from_name": from_name,
        "subject": reply.get("subject"),
        "body": (reply.get("body") or "")[:2000],
        "raw_body": reply.get("full_body") or reply.get("body") or "",
        "clean_body": reply.get("full_body") or reply.get("body") or "",
        "body_snippet": (reply.get("full_body") or reply.get("body") or "")[:500],
        "attachments": reply.get("attachments") or [],
        "attachment_names": reply.get("attachment_names") or [],
        "attachment_profiles": attachment_profiles,
        "latest_gmail_message_id": msg_id_hdr,
        "in_reply_to": in_reply_to,
        "references": references,
        "sentiment": reply.get("sentiment"),
        "action": reply.get("action"),
        "received_at": reply.get("received_at"),
        "updated_at": now,
    }
    if related_outbound:
        update_fields.update({
            "requirement_id": related_outbound.get("requirement_id") or "",
            "trainer_id": related_outbound.get("trainer_id") or "",
            "trainer_name": related_outbound.get("trainer_name") or related_outbound.get("recipient_name") or "",
            "source_outbound_email_id": related_outbound.get("email_id") or "",
            "source_outbound_mail_type": related_outbound.get("mail_type") or "",
        })
    if not existing:
        update_fields.update(_client_email_status_for_reply(reply))
        if msg_id_hdr:
            update_fields["gmail_message_id"] = msg_id_hdr
    else:
        if not existing.get("status"):
            update_fields["status"] = "received"
        if not existing.get("reply_status"):
            update_fields["reply_status"] = "received"
        if is_new_inbound_message:
            update_fields.update({
                "processed": False,
                "status": "received",
                "reply_status": "received",
                "reply_sent": False,
                "reply_sent_at": None,
                "reply_sent_for_message_id": "",
                "auto_sent_at": None,
                "auto_send_error": "",
                "reply_error": "",
            })
        if "auto_send_eligible" not in existing:
            update_fields["auto_send_eligible"] = False
        if "confidence" not in existing:
            update_fields["confidence"] = 0
        if "auto_send_confidence" not in existing:
            update_fields["auto_send_confidence"] = 0
        if not existing.get("gmail_message_id") and msg_id_hdr:
            update_fields["gmail_message_id"] = msg_id_hdr

    if existing:
        if existing.get("deleted") or existing.get("status") == "deleted" or existing.get("reply_status") == "deleted":
            delete_set = {
                "deleted": True,
                "deleted_at": existing.get("deleted_at") or now,
                "processed": True,
                "processed_at": now,
                "status": "deleted",
                "reply_status": "deleted",
                "requirement_id": "",
                "requirement_created": False,
                "client_authorized_trainer_search": False,
                "pending_trainer_automation": False,
                "updated_at": now,
            }
            if existing.get("deleted_requirement_id") or existing.get("requirement_id"):
                delete_set["deleted_requirement_id"] = existing.get("deleted_requirement_id") or existing.get("requirement_id")
            update_fields.update({
                **delete_set,
            })
        add_to_set = {"thread_message_ids": {"$each": message_ids}} if message_ids else {}
        update_doc: Dict[str, Any] = {"$set": update_fields}
        if add_to_set:
            update_doc["$addToSet"] = add_to_set
        await db["client_emails"].update_one(
            {"email_id": existing["email_id"]},
            update_doc,
        )
        merged = {**existing, **update_fields}
        candidate_extracted = _extract_requirement_from_email(
            subject=merged.get("subject") or "",
            body=merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
            sender_email=merged.get("from_email") or "",
            sender_name=merged.get("from_name") or "",
        )
        candidate_extracted = _merge_existing_requirement_context(candidate_extracted, merged)
        should_process_proceed_reply = (
            _client_wants_to_proceed_now(
                merged.get("subject") or "",
                merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
            )
            and not merged.get("client_authorized_trainer_search")
            and not merged.get("pending_trainer_automation")
        )
        should_process_details_reply = (
            bool(merged.get("requirement_id"))
            and (
                _has_details_for_trainer_search(candidate_extracted)
                or _client_provided_requirement_details(
                    merged.get("subject") or "",
                    merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
                    candidate_extracted,
                )
                or _client_wants_to_proceed_now(
                    merged.get("subject") or "",
                    merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
                )
                or _client_will_send_details_later(
                    merged.get("subject") or "",
                    merged.get("clean_body") or merged.get("raw_body") or merged.get("body") or "",
                )
            )
        )
        source_mail_type = str(
            update_fields.get("source_outbound_mail_type")
            or merged.get("source_outbound_mail_type")
            or ""
        ).strip()
        should_process_linked_automation_reply = (
            is_new_inbound_message
            and bool(merged.get("requirement_id"))
            and source_mail_type in (TRAINER_REPLY_SOURCE_MAIL_TYPES | CLIENT_REPLY_SOURCE_MAIL_TYPES)
        )
        if (
            not merged.get("requirement_id")
            or should_process_proceed_reply
            or should_process_details_reply
            or should_process_linked_automation_reply
        ):
            await _process_client_requirement_email(db, merged)
        return existing["email_id"]

    doc = {
        "email_id": f"CLH-{uuid.uuid4().hex[:10].upper()}",
        "created_at": now,
        "processed": False,
        **update_fields,
    }
    if message_ids:
        doc["thread_message_ids"] = message_ids
    await db["client_emails"].insert_one(doc)
    await _process_client_requirement_email(db, doc)
    return doc["email_id"]


async def _process_and_store_replies(db: AsyncIOMotorDatabase, replies: list) -> int:
    """Persist inbound replies to email logs and process client requirements."""
    stored = 0
    cutoff = _inbox_process_after()
    for reply in replies:
        received_at = _parse_datetime(reply.get("received_at"))
        if cutoff and (not received_at or received_at < cutoff):
            logger.info(
                "Skipping inbound email before configured reset boundary. received_at=%s cutoff=%s",
                reply.get("received_at"),
                cutoff.isoformat(),
            )
            continue
        msg_id_hdr = reply.get("message_id_header", "")
        if msg_id_hdr:
            existing = await db.email_logs.find_one({"gmail_message_id": msg_id_hdr})
            if existing:
                client_email_id = await _persist_client_email_from_reply(db, reply)
                linked_doc = await db["client_emails"].find_one(
                    {"email_id": client_email_id},
                    {"_id": 0},
                )
                if linked_doc:
                    linked_source_mail_type = str(linked_doc.get("source_outbound_mail_type") or "").strip()
                    await db.email_logs.update_one(
                        {"gmail_message_id": msg_id_hdr},
                        {"$set": {
                            "from_email": reply.get("from_email") or existing.get("from_email") or existing.get("sender") or "",
                            "sender": reply.get("from_email") or existing.get("sender") or "",
                            "body": (reply.get("body") or existing.get("body") or "")[:2000],
                            "raw_body": reply.get("body") or existing.get("raw_body") or "",
                            "clean_body": reply.get("body") or existing.get("clean_body") or "",
                            "body_snippet": (reply.get("body") or existing.get("body_snippet") or "")[:500],
                            "requirement_id": linked_doc.get("requirement_id") or "",
                            "trainer_id": linked_doc.get("trainer_id") or "",
                            "trainer_name": linked_doc.get("trainer_name") or "",
                            "source_outbound_email_id": linked_doc.get("source_outbound_email_id") or "",
                            "source_outbound_mail_type": linked_doc.get("source_outbound_mail_type") or "",
                            "updated_at": _now(),
                        }},
                    )
                    if not linked_doc.get("processed") and _auto_send_retry_due(linked_doc):
                        await _process_client_requirement_email(db, linked_doc)
                    stored += 1
                continue

        now = _now()
        doc = {
            "email_id": f"INB-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "sender": reply.get("from_email"),
            "from_email": reply.get("from_email"),
            "from_raw": reply.get("from_raw"),
            "subject": reply.get("subject"),
            "body": (reply.get("body") or "")[:2000],
            "raw_body": reply.get("body") or "",
            "clean_body": reply.get("body") or "",
            "body_snippet": (reply.get("body") or "")[:500],
            "gmail_message_id": msg_id_hdr,
            "latest_gmail_message_id": msg_id_hdr,
            "in_reply_to": reply.get("in_reply_to"),
            "references": reply.get("references"),
            "thread_message_ids": _message_id_candidates(
                msg_id_hdr,
                reply.get("in_reply_to"),
                reply.get("references"),
            ),
            "sentiment": reply.get("sentiment"),
            "action": reply.get("action"),
            "status": "received",
            "processed": False,
            "received_at": reply.get("received_at"),
            "created_at": now,
            "updated_at": now,
        }
        await db.email_logs.insert_one(doc)
        client_email_id = await _persist_client_email_from_reply(db, reply)
        linked_doc = await db["client_emails"].find_one(
            {"email_id": client_email_id},
            {"_id": 0},
        )
        if linked_doc:
            linked_source_mail_type = str(linked_doc.get("source_outbound_mail_type") or "").strip()
            await db.email_logs.update_one(
                {"email_id": doc["email_id"]},
                {"$set": {
                    "requirement_id": linked_doc.get("requirement_id") or "",
                    "trainer_id": linked_doc.get("trainer_id") or "",
                    "trainer_name": linked_doc.get("trainer_name") or "",
                    "source_outbound_email_id": linked_doc.get("source_outbound_email_id") or "",
                    "source_outbound_mail_type": linked_doc.get("source_outbound_mail_type") or "",
                    "updated_at": _now(),
                }},
            )
            if not linked_doc.get("processed") and _auto_send_retry_due(linked_doc):
                await _process_client_requirement_email(db, linked_doc)
        stored += 1
    return stored


async def _process_pending_client_emails(db: AsyncIOMotorDatabase, limit: int = 100) -> Dict[str, Any]:
    now = _now()
    today_query = _today_client_email_query()
    retry_due_query = {
        "$or": [
            {"auto_send_retry_after": {"$exists": False}},
            {"auto_send_retry_after": None},
            {"auto_send_retry_after": {"$lte": now}},
        ],
    }
    latest_message_needs_reply_query = {
        "$and": [
            {"latest_gmail_message_id": {"$exists": True, "$nin": ["", None]}},
            {"reply_sent": True},
            {
                "$expr": {
                    "$ne": [
                        {"$ifNull": ["$reply_sent_for_message_id", "$gmail_message_id"]},
                        "$latest_gmail_message_id",
                    ]
                }
            },
            retry_due_query,
        ],
    }
    pending_work_query = {
        "$and": [
            today_query,
            {"status": {"$nin": list(FINAL_CLIENT_STATUSES)}},
            {
                "$or": [
                    {"$and": [
                        {"processed": {"$ne": True}},
                        retry_due_query,
                    ]},
                    {"$and": [
                        {"extracted": {"$exists": False}},
                        retry_due_query,
                    ]},
                    {
                        "$and": [
                            {"reply_sent": {"$ne": True}},
                            {
                                "$or": [
                                    {"status": {"$in": ["pending_approval", "pending_review", "needs_manual_review"]}},
                                    {"reply_status": {"$in": ["pending_approval", "pending_review", "needs_manual_review"]}},
                                ],
                            },
                            {"auto_send_block_reason": {"$exists": False}},
                            retry_due_query,
                        ],
                    },
                    {
                        "reply_sent": {"$ne": True},
                        "auto_send_eligible": True,
                        "$and": [
                            {
                                "$or": [
                                    {"status": {"$in": ["pending_approval", "pending_review"]}},
                                    {"reply_status": {"$in": ["pending_approval", "pending_review"]}},
                                ],
                            },
                            retry_due_query,
                        ],
                    },
                    {
                        "reply_sent": {"$ne": True},
                        "auto_send_eligible": True,
                        "auto_send_error": {"$exists": True, "$ne": ""},
                        "$and": [retry_due_query],
                    },
                ],
            },
        ],
    }
    linked_trainer_reply_query = {
        "$and": [
            {"requirement_id": {"$nin": ["", None]}},
            {"trainer_id": {"$nin": ["", None]}},
            {"source_outbound_mail_type": {"$in": list(TRAINER_REPLY_SOURCE_MAIL_TYPES)}},
            {"processed": {"$ne": True}},
            {"status": {"$nin": list(FINAL_CLIENT_STATUSES)}},
            retry_due_query,
        ],
    }
    # Records written before the retry state existed were marked as manual
    # review even when the only problem was a transient downstream 502 or a
    # Gmail quota window. Pick up those old client handoffs automatically once
    # after deployment; invalid trainer slots do not match this query.
    legacy_client_handoff_retry_query = {
        "$and": [
            {"requirement_id": {"$nin": ["", None]}},
            {"trainer_id": {"$nin": ["", None]}},
            {"source_outbound_mail_type": {"$in": list(TRAINER_REPLY_SOURCE_MAIL_TYPES)}},
            {"status": "needs_manual_review"},
            {"auto_send_error": {"$regex": r"(?:502\s+Bad\s+Gateway|Gmail\s+sending\s+quota|Client\s+handoff)", "$options": "i"}},
            retry_due_query,
        ],
    }
    # A trainer reply may have been marked as needing review solely because an
    # older parser did not understand its otherwise valid date/time layout.
    # Re-evaluate those saved replies once after a parser upgrade. The marker
    # prevents a genuinely incomplete reply from being processed repeatedly.
    legacy_slot_parser_recheck_query = {
        "$and": [
            {"requirement_id": {"$nin": ["", None]}},
            {"trainer_id": {"$nin": ["", None]}},
            {"source_outbound_mail_type": {"$in": list(TRAINER_REPLY_SOURCE_MAIL_TYPES)}},
            {"status": "needs_manual_review"},
            {"slot_parser_rechecked_at": {"$exists": False}},
            {"$or": [
                {"reply_status": {"$in": ["interested_without_slots", "needs_manual_review"]}},
                {"slot_result.reason": {"$in": ["one_missing_slot_followup", "invalid_slot_text"]}},
                {"trainer_slot_automation.reason": {"$in": ["one_missing_slot_followup", "invalid_slot_text"]}},
            ]},
        ],
    }
    calendar_slot_retry_query = {
        "$and": [
            {"requirement_id": {"$nin": ["", None]}},
            {"trainer_id": {"$nin": ["", None]}},
            {"source_outbound_mail_type": "client_slots"},
            {"calendar_retry_pending": True},
            {"calendar_retry_count": {"$lt": 3}},
            {
                "$or": [
                    {"calendar_retry_after": {"$exists": False}},
                    {"calendar_retry_after": None},
                    {"calendar_retry_after": {"$lte": now}},
                ],
            },
        ],
    }
    query = {
        "$and": [
            {"deleted": {"$ne": True}},
            {
                "$or": [
                    linked_trainer_reply_query,
                    legacy_client_handoff_retry_query,
                    legacy_slot_parser_recheck_query,
                    calendar_slot_retry_query,
                    {"$and": [today_query, {"pending_trainer_automation": True}, retry_due_query]},
                    latest_message_needs_reply_query,
                    pending_work_query,
                ],
            },
        ]
    }
    cursor = (
        db["client_emails"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 500)))
    )
    items = [doc async for doc in cursor]
    recheck_email_ids = {
        doc.get("email_id")
        for doc in items
        if doc.get("email_id")
        and doc.get("status") == "needs_manual_review"
        and not doc.get("slot_parser_rechecked_at")
        and str(doc.get("source_outbound_mail_type") or "") in TRAINER_REPLY_SOURCE_MAIL_TYPES
    }
    results = []
    for doc in items:
        result = await _process_client_requirement_email(db, doc)
        results.append(result)
        if doc.get("email_id") in recheck_email_ids:
            await db["client_emails"].update_one(
                {"email_id": doc.get("email_id")},
                {"$set": {"slot_parser_rechecked_at": _now()}},
            )
    return {
        "checked": len(items),
        "requirements_created": sum(1 for item in results if item.get("requirement_id")),
        "auto_sent": sum(1 for item in results if item.get("status") == "auto_sent"),
        "failed": sum(1 for item in results if item.get("reason") == "automation_failed"),
        "results": results,
    }


async def _poll_and_store(
    db: AsyncIOMotorDatabase,
    since_days: int = 7,
    max_messages: int = 50,
    from_emails: Optional[list] = None,
    search_query: str = "",
) -> int:
    """Poll the configured inbox provider and persist/process messages."""
    settings_doc = await _load_admin_settings(db)
    inbox_provider = ((settings_doc.get("clientInboxCfg") or {}).get("inboxProvider") or "gmail_api").lower()
    imap_config = settings_doc.get("emailCfg") or None
    loop = asyncio.get_event_loop()
    if inbox_provider == "gmail_api":
        replies = await loop.run_in_executor(
            None,
            lambda: check_gmail_api_replies(
                since_days=since_days,
                max_messages=max_messages,
                from_emails=from_emails,
                search_query=search_query,
            ),
        )
    else:
        replies = await loop.run_in_executor(
            None,
            lambda: check_imap_replies(
                since_days=since_days,
                max_messages=max_messages,
                from_emails=from_emails,
                imap_config=imap_config,
            ),
        )
    return await _process_and_store_replies(db, replies)


@router.post("/poll")
async def poll_inbox(
    payload: PollRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Trigger a Gmail IMAP poll. Processing runs in background."""

    async def _run():
        await _poll_and_store(
            db,
            since_days=payload.since_days,
            max_messages=payload.max_messages,
            from_emails=payload.from_emails,
            search_query=payload.search_query,
        )

    background_tasks.add_task(_run)
    return {"message": "Inbox poll triggered", "since_days": payload.since_days}


@router.post("/poll/sync")
async def poll_inbox_sync(
    payload: PollRequest,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Synchronous poll - waits for completion and returns counts."""
    stored = await _poll_and_store(
        db,
        since_days=payload.since_days,
        max_messages=payload.max_messages,
        from_emails=payload.from_emails,
        search_query=payload.search_query,
    )
    pending = await _process_pending_client_emails(db, limit=payload.max_messages)
    return {"stored": stored, **pending}


@router.post("/process-pending")
async def process_pending_client_emails(
    payload: ProcessPendingRequest,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Re-run client requirement extraction/automation for stored inbox emails."""
    return {"success": True, **await _process_pending_client_emails(db, payload.limit)}


@router.get("/process-pending/preview")
async def preview_pending_client_emails(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return a bounded AI-processing preview; it never sends or generates."""
    query = {
        "$and": [
            _today_client_email_query(),
            {"deleted": {"$ne": True}},
            {"processed": {"$ne": True}},
            {"status": {"$nin": list(FINAL_CLIENT_STATUSES)}},
            {"reply_sent": {"$ne": True}},
            {"from_email": {"$not": re.compile(r"noreply|no-reply|mailer-daemon|postmaster", re.IGNORECASE)}},
        ]
    }
    eligible = await db["client_emails"].count_documents(query)
    planned = min(eligible, limit)
    # Based on observed GPT-5.5 usage in this workspace; it is an estimate,
    # not a billing guarantee.
    estimated_cost_usd = round(planned * 0.0112, 2)
    return {
        "success": True,
        "eligible": eligible,
        "planned": planned,
        "limit": limit,
        "estimated_ai_requests": planned,
        "estimated_cost_usd": estimated_cost_usd,
        "automation_enabled": (await _auto_send_settings(db))["enabled"],
    }


@router.get("/unprocessed")
async def get_unprocessed(
    limit: int = 50,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Return inbound emails not yet processed by the pipeline."""
    cursor = db.email_logs.find(
        {"direction": "inbound", "processed": False},
        {"_id": 0},
    ).limit(limit).sort("created_at", 1)
    items = [doc async for doc in cursor]
    return {"items": items, "count": len(items)}


@router.patch("/{email_id}/mark-processed")
async def mark_processed(
    email_id: str,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    now = _now()
    await db.email_logs.update_one(
        {"email_id": email_id},
        {"$set": {"processed": True, "processed_at": now, "updated_at": now}},
    )
    return {"message": "Marked as processed", "email_id": email_id}

