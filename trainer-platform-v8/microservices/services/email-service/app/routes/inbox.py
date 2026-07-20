"""Gmail inbox polling and inbound client requirement processing."""
import asyncio
import html
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Annotated, Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.agents.email_classifier import classify_email
from app.agents.reply_templates import build_auto_reply
from app.calendar_client import create_google_meet_event
from app.database import get_db
from app.gmail_client import check_imap_replies, send_email_async
from app.routes.templates import InterviewEmailRequest, compose_interview

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

CORE_API_URL = settings.CORE_API_URL.rstrip("/")
TRAINER_SERVICE_URL = settings.TRAINER_SERVICE_URL.rstrip("/")
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
LOCAL_SERVICE_FALLBACKS = {
    "http://core-api:8001": "http://127.0.0.1:8001",
    "http://trainer-service:8004": "http://127.0.0.1:8004",
    "http://intelligence-service:8005": "http://127.0.0.1:8005",
}

FINAL_CLIENT_STATUSES = {"auto_sent", "sent", "approved", "rejected", "spam", "ignored"}
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
    r"\bgo\s+ahead\b",
    r"\bmove\s+ahead\b",
    r"\bstart\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\bbegin\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\b(?:please\s+)?share\b.{0,50}\b(?:profile|profiles|trainer profiles)\b",
    r"\b(?:send|provide)\b.{0,50}\b(?:profile|profiles|trainer profiles)\b",
    r"\b(?:suitable|relevant|available)\s+(?:trainer|trainer profile|trainer profiles|profiles)\b",
)
DETAILS_LATER_PATTERNS = (
    r"\b(?:send|sent|share|provide)\b.{0,50}\blater\b",
    r"\blater\b.{0,50}\b(?:send|share|provide|details?)\b",
    r"\bdetails?\s+(?:later|will\s+follow|to\s+follow|will\s+be\s+provided\s+later)\b",
    r"\bwill\s+share\s+details?\s+later\b",
    r"\bremaining\s+details?\b",
    r"\bonce\s+.*\b(?:available|finali[sz]ed)\b",
)
OPEN_REQUIREMENT_EXCLUDED_STATUSES = {"closed", "completed", "cancelled", "canceled", "inactive", "deleted"}


class PollRequest(BaseModel):
    since_days: int = 7
    max_messages: int = 50
    from_emails: Optional[list] = None


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


def _is_today_or_newer(email_doc: Dict[str, Any]) -> bool:
    # Always allow processing regardless of the original message timestamp.
    return True


def _today_client_email_query() -> Dict[str, Any]:
    # Do not limit pending work to today only.
    return {}


def _clean(value: Any) -> str:
    value = re.sub(r"[*_`]+", "", str(value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n:-")


def _plain_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_text_lines(value: Any) -> str:
    text = str(value or "")
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
    has_details_later_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in DETAILS_LATER_PATTERNS
    )
    return bool(has_proceed_signal or has_details_later_signal)


def _client_will_send_details_later(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in DETAILS_LATER_PATTERNS
    )


def _is_obvious_non_client_email(sender_email: str, subject: str, body: str) -> bool:
    email = _email_address(sender_email)
    local = email.split("@", 1)[0] if "@" in email else email
    domain = email.split("@", 1)[1] if "@" in email else ""
    automated_sender = (
        local in AUTOMATED_SENDER_LOCALS
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
        return _clean(fallback) or _clean((email or "").split("@")[0])
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
    explicit = _field_value(text, ["Technology", "Tech", "Domain", "Course", "Topic"])
    candidates = [explicit]

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


def _extract_preferred_dates(text: str) -> Dict[str, Any]:
    raw = _field_value(text, [
        "Preferred Training Dates",
        "Preferred Dates",
        "Dates/Timings",
        "Dates and Timings",
        "Training Dates",
        "Training Date",
        "Dates",
        "Date",
    ])
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
    rupee = re.escape(chr(0x20B9))
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


def _extract_requirement_from_email(subject: str, body: str, sender_email: str = "", sender_name: str = "") -> Dict[str, Any]:
    sender_email = _email_address(sender_email)
    body_text = _plain_text(body)
    field_body = _plain_text_lines(body) or body_text
    text = f"Subject: {subject}\n{field_body}"
    lower = f"Subject: {subject}\n{body_text}".lower()
    direct_request = _has_direct_training_request_language(subject, body_text)
    non_client_email = _is_obvious_non_client_email(sender_email, subject, body_text)
    technology = _infer_technology(subject, field_body)
    mode = _field_value(text, ["Mode", "Delivery Mode", "Training Mode"])
    if not mode:
        if "online" in lower or "virtual" in lower:
            mode = "Online"
        elif "offline" in lower or "onsite" in lower or "on-site" in lower:
            mode = "Offline"
        elif "hybrid" in lower:
            mode = "Hybrid"

    audience_level = _field_value(text, ["Participant Level", "Audience Level", "Learner Level", "Level", "Audience"])
    timing = _field_value(text, ["Training Timings", "Daily Training Timings", "Preferred Timings", "Timings", "Timing", "Time", "Schedule"])
    duration = _extract_duration(text)
    budget = _extract_budget(text)
    dates = _extract_preferred_dates(text)
    client_domain = _field_value(text, ["Client Domain", "Client Industry", "Industry", "Business Domain"])
    topics = _field_block_value(text, ["Topics to be Covered", "Topics", "Tools", "Scope"])

    participants = None
    participant_text = _field_value(text, ["Participants", "Participant Count", "Learners", "Trainees"])
    participant_match = re.search(
        r"(\d+)\s*(?:participants?|learners?|trainees?|people|pax)",
        participant_text or text,
        flags=re.IGNORECASE,
    )
    if participant_match:
        participants = _safe_int(participant_match.group(1))
    elif participant_text:
        participant_number = re.search(r"\d+", participant_text)
        if participant_number:
            participants = _safe_int(participant_number.group(0))

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
    if non_client_email:
        confidence = min(confidence, 0.25)

    requested_details = []
    detail_map = {
        "resume": "Updated Resume",
        "total experience": "Total Experience",
        "relevant training experience": "Relevant Training Experience",
        "availability": "Availability",
        "commercials": "Commercials Per Day",
        "linkedin": "LinkedIn Profile",
    }
    for needle, label in detail_map.items():
        if needle in lower:
            requested_details.append(label)

    is_training_request = bool(technology) and direct_request and not non_client_email
    inferred_client_name = _clean(sender_name)
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
        "client_domain": client_domain,
        "client_industry": client_domain,
        "topics": topics,
        "custom_topics": topics,
        "participant_count": participants,
        "client_company": _client_company_from_email(sender_email, sender_name),
        "client_name": inferred_client_name or "Client",
        "client_email": _clean(sender_email),
        "email_summary": _build_summary(technology, mode, duration.get("duration_text"), timing),
        "requested_details": requested_details,
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


def _build_summary(technology: str, mode: str, duration: Any, timing: str) -> str:
    parts = [part for part in [technology, mode, duration, timing] if part]
    return " / ".join(parts) if parts else "Training requirement details pending"


def _client_salutation(extracted: Dict[str, Any]) -> str:
    name = _clean(extracted.get("client_name"))
    if not name or name.lower() in {"client", "team"} or "@" in name or _looks_like_company_name(name):
        return "Client"
    return name[:1].upper() + name[1:]


def _reply_signature() -> str:
    return "Best Regards,\nRecruitment Team\nClahan Technologies"


def _format_missing_details(extracted: Dict[str, Any]) -> str:
    missing = extracted.get("needs_clarification") or []
    if not missing:
        return ""

    lines = [f"- {item}" for item in missing]
    return "\n".join(lines)


def _client_reply_for_requirement(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    duration = extracted.get("duration_text") or (
        f"{extracted.get('duration_days')} days" if extracted.get("duration_days") else "To be confirmed"
    )
    dates = (
        extracted.get("training_dates")
        or extracted.get("preferred_dates")
        or " to ".join(part for part in [extracted.get("timeline_start"), extracted.get("timeline_end")] if part)
        or extracted.get("timing")
        or "To be confirmed"
    )
    budget = "To be confirmed"
    if extracted.get("budget_range"):
        budget = str(extracted["budget_range"])
    elif extracted.get("budget_per_day"):
        budget = f"{extracted.get('budget_currency') or 'INR'} {extracted['budget_per_day']} per day"
    elif extracted.get("budget_total"):
        budget = f"{extracted.get('budget_currency') or 'INR'} {extracted['budget_total']}"
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing the required details.\n\n"
        "We have noted the following details:\n\n"
        f"Technology/Domain: {technology}\n"
        f"Duration: {duration}\n"
        f"Dates/Timings: {dates}\n"
        f"Mode/Location: {extracted.get('mode') or 'To be confirmed'}\n"
        f"Participant Count: {extracted.get('participant_count') if extracted.get('participant_count') is not None else 'To be confirmed'}\n"
        f"Participant Level: {extracted.get('audience_level') or 'To be confirmed'}\n"
        f"Client Domain: {extracted.get('client_domain') or extracted.get('client_industry') or 'To be confirmed'}\n"
        f"Budget/Commercial Range: {budget}\n\n"
        f"We will proceed with the trainer search for your {technology} requirement and share suitable profiles with availability and commercials for your review shortly.\n\n"
        + _reply_signature()
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_full_details_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing the required details for your training requirement.\n\n"
        "We will proceed with the trainer search and share suitable profiles with experience, skill set, availability, and commercials for your review shortly.\n\n"
        + _reply_signature()
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_proceed_ack_reply(extracted: Dict[str, Any], details_later: bool = False) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    if details_later:
        body = (
            "Dear Client,\n\n"
            "Thank you for the update.\n\n"
            "We have noted that you will share the remaining details later.\n\n"
            f"We will proceed with the initial trainer search for your {technology} requirement based on the information currently available.\n\n"
            "Our team will start identifying suitable trainers with relevant domain expertise, availability, and experience.\n\n"
            "Once you share the remaining details, we will refine the shortlist and align the training content more accurately with your participants.\n\n"
            "We will share the most suitable profiles with commercials and availability for your review.\n\n"
            + _reply_signature()
        )
        return {"subject": f"Re: {technology} Trainer Requirement", "body": body}

    missing_details = _format_missing_details(extracted)
    missing_block = ""
    if missing_details:
        missing_block = (
            "To help us refine the shortlist and design the best-fit training content, kindly share only the following missing details:\n\n"
            f"{missing_details}"
            "\n\nThese details will help us recommend better matched trainers and align the course content more accurately with your participants.\n\n"
        )
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing your training requirement.\n\n"
        "We have noted your requirement and will proceed with the initial trainer search for your training requirement based on the information currently available.\n\n"
        "Our team will start identifying suitable trainers with relevant domain expertise, availability, and experience.\n\n"
        f"{missing_block}"
        "We will share the most suitable profiles with commercials and availability for your review.\n\n"
        + _reply_signature()
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_clarification_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    body = (
        "Dear Client,\n\n"
        "Thank you for sharing the training requirement. To shortlist the right trainer profiles, "
        "please confirm the technology/topic, delivery mode, expected dates or duration, participant count, "
        "and commercials or budget range.\n\n"
        "Once we have these details, we will share suitable profiles for your review.\n\n"
        + _reply_signature()
    )
    return {"subject": "Re: Training Requirement Details", "body": body}


def _trainer_mail2_details_reply(email_doc: Dict[str, Any]) -> Dict[str, str]:
    trainer_name = _clean(email_doc.get("trainer_name") or email_doc.get("from_name") or "Trainer")
    domain = _clean(
        email_doc.get("technology")
        or (email_doc.get("extracted") or {}).get("technology_needed")
        or (email_doc.get("requirement") or {}).get("technology_needed")
        or "Training"
    )
    body = (
        f"Dear {trainer_name},\n\n"
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
        "Regards,\n"
        "TrainerSync Team"
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
        f"Reference: {requirement_id}\n\n"
        + _reply_signature()
    )
    return {"subject": f"Corporate Training Requirement - {tech}", "body": body}


def _client_email_status_for_reply(reply: dict) -> dict:
    return {
        "status": "received",
        "reply_status": "received",
        "auto_send_eligible": False,
        "confidence": 0,
        "auto_send_confidence": 0,
    }


async def _auto_send_settings(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    settings_doc = await _load_admin_settings(db)
    inbox_cfg = settings_doc.get("clientInboxCfg") or {}
    scheduler_cfg = settings_doc.get("schedulerCfg") or {}
    legacy_auto_send_cfg = settings_doc.get("autoSendCfg") or {}

    threshold_value = inbox_cfg.get("autoSendThreshold")
    if threshold_value is None:
        threshold_value = legacy_auto_send_cfg.get("threshold")
    if threshold_value is None:
        threshold_value = scheduler_cfg.get("autoSendConfidenceThreshold")

    return {
        "enabled": True,
        "threshold": _normalise_threshold(threshold_value, 0.7),
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


def _money_to_int(raw_amount: Any, suffix: str = "") -> int:
    amount = _safe_float(str(raw_amount or "").replace(",", ""), 0)
    suffix = str(suffix or "").lower()
    if suffix in {"k", "thousand"}:
        amount *= 1000
    elif suffix in {"lakh", "lakhs"}:
        amount *= 100000
    return int(round(amount))


def _trainer_commercial_amounts(text: Any) -> List[int]:
    reply_text = _strip_quoted_email_history(text)
    if not reply_text:
        return []

    rupee = re.escape(chr(0x20B9))
    amounts: List[int] = []
    patterns = [
        (rf"(?:INR|Rs\.?|{rupee})\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"\b(?:commercials?|rates?|charges?|fees?|cost)\b\D{0,80}([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?", False),
        (r"([0-9][0-9,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?\s*(?:/-)?\s*(?:per\s*(?:day|session)|/day|/session)", True),
    ]
    contextual_line = re.compile(r"\b(?:commercials?|rates?|charges?|fees?|cost)\b", flags=re.IGNORECASE)
    for line in reply_text.splitlines():
        line_has_money_context = bool(contextual_line.search(line))
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


def _find_shortlist_trainer(shortlist: Dict[str, Any], trainer_id: str) -> Dict[str, Any]:
    for trainer in shortlist.get("top_trainers") or []:
        if str(trainer.get("trainer_id") or "") == str(trainer_id or ""):
            return trainer
    return {}


def _client_name_from_context(requirement: Dict[str, Any], shortlist: Dict[str, Any]) -> str:
    for source in (requirement, shortlist):
        for key in ("client_name", "client_company", "company_name"):
            value = _clean(source.get(key))
            if value:
                return value
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
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_name = _client_name_from_context(requirement, shortlist)
    experience = _clean(trainer.get("experience_raw") or trainer.get("experience_years"))
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

    rate_lines = "\n".join(f"* INR {amount:,.0f} per day/session" for amount in client_rates)
    details = [
        f"* Trainer: {trainer_name}",
        f"* Technology: {technology}",
    ]
    if experience:
        details.append(f"* Experience: {experience}")
    if certifications_text:
        details.append(f"* Certifications: {certifications_text}")
    if skills_text:
        details.append(f"* Key skills: {skills_text}")

    subject = f"Trainer Commercials for Approval - {technology} | {trainer_name}"
    body = (
        f"Dear {client_name},\n\n"
        f"Trainer {trainer_name} has shared the required details and commercials for the {technology} requirement.\n\n"
        "Trainer Summary:\n"
        f"{chr(10).join(details)}\n\n"
        "Commercials for your review:\n"
        f"{rate_lines}\n\n"
        "Please review and confirm if we can proceed with this trainer. Once approved, we will move ahead with interview/slot coordination.\n\n"
        "Regards,\n"
        "Recruitment Team,\n"
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
        f"Thank you for sharing your details and commercials for the {technology} requirement.\n\n"
        f"After internal commercial review, kindly confirm if you can proceed at INR {target_amount:,.0f} {unit_text}.\n\n"
        "Please let us know if this revised commercial is workable.\n\n"
        "Regards,\n"
        "TrainerSync Team"
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
    bullet = chr(0x2022)
    slots_text = (
        f"{bullet} Monday, Jan 15, 2024 - 10:00 AM IST\n"
        f"{bullet} Tuesday, Jan 16, 2024 - 2:00 PM IST\n"
        f"{bullet} Wednesday, Jan 17, 2024 - 4:00 PM IST\n"
        f"{bullet} [Slot 1]\n"
        f"{bullet} [Slot 2]\n"
        f"{bullet} [Slot 3]"
    )
    subject = f"Interview Slot Booking - {technology}"
    body = (
        f"Dear {trainer_name},\n\n"
        "Thank you for sharing your details.\n\n"
        "We would like to book an interview slot with you. Based on your availability, please confirm one of the following slots:\n\n"
        "example\n"
        f"{slots_text}\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Regards,\n"
        "TrainerSync Team"
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


def _has_proper_interview_slots(text: Any) -> bool:
    metrics = _slot_reply_metrics(text)
    has_one_exact_slot = metrics["date_hits"] >= 1 and metrics["time_hits"] >= 1
    has_three_slot_options = (
        (metrics["date_hits"] >= 3 and metrics["time_hits"] >= 3)
        or (metrics["date_hits"] >= 3 and metrics["time_hits"] >= 2 and metrics["slot_hints"] >= 1)
    )
    return has_one_exact_slot or has_three_slot_options


def _slot_reply_intent(text: Any) -> str:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return "unknown"
    if re.search(r"\b(?:not available|unavailable|not possible|cannot|can't|cant|decline|no thanks)\b", lower, flags=re.IGNORECASE):
        return "rejected"
    if _has_proper_interview_slots(lower):
        return "valid_slots"
    metrics = _slot_reply_metrics(lower)
    if metrics["slot_count"] > 3:
        return "too_many_slots"
    if metrics["slot_count"] > 0 or metrics["slot_hints"] > 0 or metrics["date_hits"] > 0 or metrics["time_hits"] > 0:
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


def _slot_followup_message(trainer: Dict[str, Any], intent: str) -> Dict[str, str]:
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    if intent == "too_many_slots":
        return {
            "subject": "Re: Interview Slot Booking",
            "body": (
                f"Hi {trainer_name},\n\n"
                "Thank you for your availability. For our scheduling process, we typically work with 3 slots as it helps us coordinate efficiently.\n\n"
                "Could you please share your top 3 preferred slots with dates and times?\n\n"
                "Thank you."
            ),
        }
    return {
        "subject": "Interview Slot Details Required",
        "body": (
            f"Hi {trainer_name},\n\n"
            "Thank you for sharing the slot. Could you please provide the exact interview date and time, including whether it is AM or PM?\n\n"
            "Also, please share 3 available slots with the corresponding dates so that we can schedule the interview accordingly.\n\n"
            "Thanks."
        ),
    }


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
    trainer_name = _clean(trainer.get("name") or trainer.get("trainer_name")) or "Trainer"
    client_name = _client_name_from_context(requirement, shortlist)
    subject = f"Trainer Interview Slots - {technology} | {trainer_name}"
    body = (
        f"Dear {client_name},\n\n"
        f"Trainer {trainer_name} has shared the available interview slots for the {technology} requirement.\n\n"
        "Available slots:\n"
        f"{slot_text}\n\n"
        "Kindly confirm your preferred slot at the earliest.\n\n"
        "Regards,\n"
        "TrainerSync Team"
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
    body = (
        f"Dear {client_name or 'Team'},\n\n"
        f"The interview/discussion with Trainer {trainer_name or 'the trainer'} for the {technology} requirement is confirmed.\n\n"
        "Interview Details:\n"
        f"{date_line}"
        "Platform: Google Meet\n"
        f"Meeting Link: {meeting_link}\n\n"
        "Kindly join on time and let us know if any change is required.\n\n"
        "Regards,\n"
        "TrainerSync Team"
    )
    return {"subject": subject, "body": body}


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
    message = _client_interview_schedule_message(
        client_name=client_name,
        trainer_name=trainer_name,
        technology=technology,
        requirement_id=requirement_id,
        interview_date=interview_date,
        meeting_link=meeting_link,
    )
    success, error = await send_email_async(
        to=client_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    event = calendar_event or {}
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
        "mail_type": "client_interview_schedule",
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
            {"email_id": source_email_id, "mail_type": {"$in": ["mail3", "mail3_slot_followup", "mail3_too_many_slots"]}},
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
            "mail_type": {"$in": ["mail3", "mail3_slot_followup", "mail3_too_many_slots"]},
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
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
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


async def _handle_trainer_slot_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    is_slot_thread = (
        source_mail_type in {"mail3", "mail3_slot_followup", "mail3_too_many_slots"}
        or bool(re.search(r"(Interview Slot Booking|Slot Booking|Interview Availability|Trainer Availability Slots)", subject, flags=re.IGNORECASE))
    )
    if not is_slot_thread:
        return {"attempted": False, "reason": "not_slot_reply_thread"}

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

    trainer_email = _email_address(trainer.get("email") or trainer.get("trainer_email") or email_doc.get("from_email"))
    reply_text = _strip_quoted_email_history(
        email_doc.get("classification_body")
        or email_doc.get("clean_body")
        or email_doc.get("raw_body")
        or email_doc.get("body")
        or ""
    )
    intent = _slot_reply_intent(reply_text)
    now = _now()
    source_log = await _latest_mail3_log(db, email_doc, requirement_id, trainer_id)
    source_time = (source_log or {}).get("sent_at") or (source_log or {}).get("created_at")

    if intent == "rejected":
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
        if not trainer_email:
            return {"attempted": True, "success": False, "reason": "missing_trainer_email", "intent": intent, "error": "Trainer email missing"}

        followup_type = "mail3_too_many_slots" if intent == "too_many_slots" else "mail3_slot_followup"
        duplicate_terms = []
        if email_doc.get("email_id"):
            duplicate_terms.append({"source_email_id": email_doc.get("email_id")})
        source_gmail_message_id = _current_inbound_message_id(email_doc)
        if source_gmail_message_id:
            duplicate_terms.append({"source_gmail_message_id": source_gmail_message_id})
        duplicate_query: Dict[str, Any] = {
            "direction": "outbound",
            "status": "sent",
            "mail_type": followup_type,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
        }
        if duplicate_terms:
            duplicate_query["$or"] = duplicate_terms
        else:
            duplicate_query["created_at"] = {"$gte": source_time or now}
        existing = await db["email_logs"].find_one(
            duplicate_query,
            {"_id": 0, "email_id": 1, "to_email": 1, "recipient": 1, "sent_at": 1},
            sort=[("created_at", -1)],
        )
        if existing:
            return {
                "attempted": True,
                "success": True,
                "already_sent": True,
                "email_id": existing.get("email_id"),
                "to": existing.get("to_email") or existing.get("recipient"),
                "intent": intent,
                "mail_type": followup_type,
            }

        message = _slot_followup_message(trainer, intent)
        settings_doc = await _load_admin_settings(db)
        smtp_config = settings_doc.get("emailCfg") or None
        success, error = await send_email_async(
            to=trainer_email,
            subject=message["subject"],
            body=message["body"],
            smtp_config=smtp_config,
        )
        email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
        await db["email_logs"].insert_one({
            "email_id": email_id,
            "direction": "outbound",
            "recipient": trainer_email,
            "to_email": trainer_email,
            "subject": message["subject"],
            "body": message["body"],
            "body_snippet": message["body"][:300],
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "mail_type": followup_type,
            "source_email_id": email_doc.get("email_id"),
            "source_gmail_message_id": source_gmail_message_id,
            "requirement_id": requirement_id,
            "trainer_id": trainer_id,
            "trainer_name": trainer.get("name") or email_doc.get("trainer_name") or "",
            "sent_at": now if success else None,
            "created_at": now,
            "updated_at": now,
        })
        await db["shortlists"].update_one(
            {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "clarification_sent" if success else "clarification_send_failed",
                "top_trainers.$.slot_clarification_sent_at": now if success else None,
                "top_trainers.$.last_mail_type": followup_type if success else trainer.get("last_mail_type"),
                "top_trainers.$.last_mail_type_attempted": followup_type,
                "top_trainers.$.last_mail_attempted_at": now,
                "top_trainers.$.last_mailed_at": now if success else trainer.get("last_mailed_at"),
                "top_trainers.$.last_mail_error": "" if success else (error or "Slot clarification email failed"),
                "top_trainers.$.updated_at": now,
                "updated_at": now,
            }},
        )
        return {
            "attempted": True,
            "success": success,
            "error": error or "",
            "email_id": email_id,
            "to": trainer_email,
            "intent": intent,
            "mail_type": followup_type,
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

    slot_text = _extract_slot_lines(reply_text)
    message = _client_slots_message(requirement, shortlist, trainer, slot_text)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    success, error = await send_email_async(
        to=client_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
        "body": message["body"],
        "body_snippet": message["body"][:300],
        "status": "sent" if success else "failed",
        "error_message": error if not success else "",
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
    await db["shortlists"].update_one(
        {"requirement_id": requirement_id, "top_trainers.trainer_id": trainer_id},
        {"$set": {
            "top_trainers.$.pipeline_status": "slot_booked",
            "top_trainers.$.slot_status": "sent_to_client" if success else "client_slot_send_failed",
            "top_trainers.$.slot_reply_at": now,
            "top_trainers.$.slot_reply_text": slot_text,
            "top_trainers.$.client_slots_sent": bool(success),
            "top_trainers.$.client_slots_sent_at": now if success else None,
            "top_trainers.$.client_slots_email_id": email_id if success else "",
            "top_trainers.$.client_slot_error": "" if success else (error or "Client slot email failed"),
            "top_trainers.$.last_mail_error": "" if success else (error or "Client slot email failed"),
            "top_trainers.$.updated_at": now,
            "updated_at": now,
        }},
    )
    return {
        "attempted": True,
        "success": success,
        "error": error or "",
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
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("*", " ")
    )


def _parse_slot_date(text: str) -> Optional[datetime]:
    for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text):
        day, month, year = (int(match.group(i)) for i in range(1, 4))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day)
        except ValueError:
            continue
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    for match in re.finditer(
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?[,]?\s+"
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{2,4})\b",
        text,
        flags=re.IGNORECASE,
    ):
        month = month_names.get(match.group(1).lower())
        day = int(match.group(2))
        year = int(match.group(3))
        if year < 100:
            year += 2000
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                continue
    for match in re.finditer(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[,]?\s+(\d{2,4})\b",
        text,
        flags=re.IGNORECASE,
    ):
        day = int(match.group(1))
        month = month_names.get(match.group(2).lower())
        year = int(match.group(3))
        if year < 100:
            year += 2000
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                continue
    return None


def _time_to_24h(hour: int, minute: int, meridiem: str) -> tuple[int, int]:
    meridiem = (meridiem or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute


def _parse_time_range(text: str, date_value: datetime) -> Optional[tuple[datetime, datetime, str]]:
    match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:-|to)\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        _normalise_slot_text(text),
        flags=re.IGNORECASE,
    )
    if not match:
        single = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", _normalise_slot_text(text), flags=re.IGNORECASE)
        if not single:
            return None
        start_hour, start_minute = _time_to_24h(
            int(single.group(1)),
            int(single.group(2) or 0),
            single.group(3),
        )
        start = date_value.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        label = f"{start.strftime('%d/%m/%Y, %I:%M %p')} - {end.strftime('%I:%M %p')}"
        return start, end, label
    start_hour, start_minute = _time_to_24h(
        int(match.group(1)),
        int(match.group(2) or 0),
        match.group(3),
    )
    end_hour, end_minute = _time_to_24h(
        int(match.group(4)),
        int(match.group(5) or 0),
        match.group(6),
    )
    start = date_value.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = date_value.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    label = f"{start.strftime('%d/%m/%Y, %I:%M %p')} - {end.strftime('%I:%M %p')}"
    return start, end, label


def _selected_slot_number(text: str) -> Optional[int]:
    clean = _normalise_slot_text(text)
    match = re.search(r"\bslot\s*(\d+)\b", clean, flags=re.IGNORECASE)
    if match:
        return _safe_int(match.group(1), 0) or None
    match = re.search(r"(?:^|\s)(\d{1,2})\s*[\).:#-]?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", clean, flags=re.IGNORECASE)
    if match:
        return _safe_int(match.group(1), 0) or None
    return None


def _slot_options_from_text(source_text: Any) -> List[Dict[str, Any]]:
    clean = _normalise_slot_text(source_text)
    global_date = _parse_slot_date(clean)
    options: List[Dict[str, Any]] = []
    current_number: Optional[int] = None
    for raw_line in clean.splitlines():
        line = _clean(raw_line)
        if not line:
            continue
        line_date = _parse_slot_date(line) or global_date
        number_only = re.match(r"^(?:slot\s*)?(\d{1,2})[\).:]?$", line, flags=re.IGNORECASE)
        if number_only:
            current_number = _safe_int(number_only.group(1), 0) or None
            continue
        inline_number = re.match(r"^(?:slot\s*)?(\d{1,2})[\).:\s-]+", line, flags=re.IGNORECASE)
        parsed = _parse_time_range(line, line_date) if line_date else None
        if not parsed:
            continue
        start, end, label = parsed
        slot_number = (_safe_int(inline_number.group(1), 0) if inline_number else 0) or current_number or (len(options) + 1)
        options.append({"number": slot_number, "start": start, "end": end, "label": label, "line": line})
        current_number = None
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

    if len(options) == 1:
        return {**options[0], "selected_number": selected_number, "source": "single_source_slot"}
    return {"selected_number": selected_number, "source": "unresolved"}


def _is_google_meet_link(value: Any) -> bool:
    return "meet.google.com" in str(value or "").lower()


def _slot_confirmation_intent(text: Any) -> str:
    lower = _strip_quoted_email_history(text).lower()
    if not lower:
        return "unknown"
    if re.search(r"\b(?:not available|unavailable|not possible|cannot|can't|cant|decline|no thanks|nope|sorry)\b", lower, flags=re.IGNORECASE):
        return "rejected"
    if re.search(r"\bslot\s*\d+\b", lower, flags=re.IGNORECASE):
        return "selected_slot_number"
    if _has_proper_interview_slots(lower):
        return "selected_slot_details"
    if re.search(r"\b(book|confirm|select|choose|pick)\b[\s\S]*\bslot\b", lower, flags=re.IGNORECASE) and re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lower, flags=re.IGNORECASE):
        return "selected_slot_details"
    if re.search(r"\b(preferred slot|preferred option|selected slot|confirm(ed|ation)?|works for|works well|suits (?:me|us)|available|available for)\b", lower, flags=re.IGNORECASE):
        return "selected_slot"
    return "unknown"


async def _handle_client_slot_confirmation_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    subject = str(email_doc.get("subject") or "")
    requirement_id = email_doc.get("requirement_id") or ""
    trainer_id = email_doc.get("trainer_id") or ""
    is_client_slot_thread = (
        source_mail_type == "client_slots"
        or bool(re.search(
            r"(Trainer Interview Slots|Interview Slots|Slot options|Slot selection|Selected slot|Preferred slot|preferred slot|Interview Slot Booking|Slot Booking|Interview Availability|Trainer Availability Slots)",
            subject,
            flags=re.IGNORECASE,
        ))
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

    duplicate_terms = []
    if email_doc.get("email_id"):
        duplicate_terms.append({"source_email_id": email_doc.get("email_id")})
    if source_gmail_message_id:
        duplicate_terms.append({"source_gmail_message_id": source_gmail_message_id})
    duplicate_query: Dict[str, Any] = {
        "direction": "outbound",
        "status": "sent",
        "mail_type": "mail4",
        "requirement_id": requirement_id,
        "trainer_id": trainer_id,
    }
    if duplicate_terms:
        duplicate_query["$or"] = duplicate_terms
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
    if existing and _is_google_meet_link(existing_link):
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
        summary=f"{technology} Trainer Interview - {trainer_name}",
        description=(
            f"Trainer interview for {technology} requirement.\n"
            f"Requirement: {requirement_id}\n"
            f"Trainer: {trainer_name}"
        ),
        start=resolved_slot["start"],
        end=resolved_slot["end"],
        attendees=[
            trainer_email,
            client_email,
        ],
        timezone=calendar_timezone,
    )
    meeting_link = calendar_event.get("meet_link") or ""
    if not calendar_event.get("success") or not meeting_link:
        calendar_error = calendar_event.get("error") or "Google Meet link creation failed."
        calendar_event = {**calendar_event, "success": False, "error": calendar_error}
        meeting_link = ""

    mail_payload = InterviewEmailRequest(
        trainer_name=trainer_name,
        technology=technology,
        req_id=requirement_id,
        interview_date=interview_date,
        interview_link=meeting_link,
    )
    message = await compose_interview(mail_payload)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
        "body": message["body"],
        "body_snippet": message["body"][:300],
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
        r"\bcongratulations\b",
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

    mail5_result: Dict[str, Any] = {}
    try:
        prior_mail5 = await db["email_logs"].find_one(
            {
                "direction": "outbound",
                "requirement_id": requirement_id,
                "trainer_id": trainer_id,
                "mail_type": {"$in": ["mail5", "mail5_ok", "mail5_selection"]},
                "status": "sent",
            },
            {"_id": 0, "email_id": 1},
        )
        if prior_mail5:
            mail5_result = {"skipped": True, "reason": "mail5_already_sent", "email_id": prior_mail5.get("email_id")}
        else:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await _post_with_local_fallback(
                    client,
                    f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-mail",
                    json={
                        "requirement_id": requirement_id,
                        "trainer_ids": [trainer_id],
                        "mail_type": "mail5_ok",
                    },
                )
                mail5_result = {
                    "status_code": response.status_code,
                    "success": response.status_code < 400,
                    "body": response.text[:500],
                }
    except Exception as exc:
        logger.exception("Failed to auto-send Mail 5 after client selection for %s/%s", requirement_id, trainer_id)
        mail5_result = {"success": False, "error": str(exc)}

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
            "automation_result": mail5_result,
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
        return {"attempted": True, "success": False, "reason": "missing_client_budget", "error": "No client budget amount found"}
    client_budget = max(client_budget_amounts)
    unit = _commercial_unit(reply_text)
    markup = 500 if unit == "hour" else 5000
    target_amount = max(client_budget - markup, 0)
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
    success, error = await send_email_async(
        to=trainer_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": trainer_email,
        "to_email": trainer_email,
        "subject": message["subject"],
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
    set_fields = {
        "top_trainers.$.pipeline_status": "details_received",
        "top_trainers.$.commercial_status": status,
        "top_trainers.$.client_commercial_forward_status": status,
        "top_trainers.$.client_commercial_forward_error": error,
        "top_trainers.$.updated_at": now,
        "updated_at": now,
    }
    if status == "sent_to_client":
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
        }

    shortlist = await db["shortlists"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    requirement = await db["requirements"].find_one({"requirement_id": requirement_id}, {"_id": 0}) or {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id)
    if not trainer:
        trainer = await db["trainers"].find_one({"trainer_id": trainer_id}, {"_id": 0}) or {}
    if not trainer:
        trainer = {"trainer_id": trainer_id, "name": email_doc.get("trainer_name") or "Trainer", "email": trainer_email}

    if not amounts:
        error = "Trainer details received, but no commercial amount was found."
        await _set_trainer_commercial_forward_status(db, requirement_id, trainer_id, "waiting_for_commercials", error)
        return {"attempted": True, "success": False, "reason": "missing_commercial_amount", "error": error}

    client_email = await _client_email_from_context(db, requirement_id, trainer_email, requirement, shortlist)
    if not client_email:
        error = "Client email missing; trainer commercials were not sent to client."
        await _set_trainer_commercial_forward_status(db, requirement_id, trainer_id, "missing_client_email", error)
        return {"attempted": True, "success": False, "reason": "missing_client_email", "error": error}

    client_rates = [amount + 5000 for amount in amounts]
    message = _trainer_commercial_body(requirement, shortlist, trainer, client_rates)
    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    success, error = await send_email_async(
        to=client_email,
        subject=message["subject"],
        body=message["body"],
        smtp_config=smtp_config,
    )
    now = _now()
    email_id = f"EML-{uuid.uuid4().hex[:10].upper()}"
    await db["email_logs"].insert_one({
        "email_id": email_id,
        "direction": "outbound",
        "recipient": client_email,
        "to_email": client_email,
        "subject": message["subject"],
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
    else:
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
    }


async def _send_client_auto_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    reply: Dict[str, str],
    requirement_id: str = "",
) -> Dict[str, Any]:
    send_settings = await _auto_send_settings(db)
    if not send_settings["enabled"]:
        return {"success": False, "error": "Auto-send is disabled"}

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

    client_template_marker = ""
    if mail_type == "client_auto_reply":
        client_template_marker = (
            "We have noted that you will share the remaining details later."
            if "We have noted that you will share the remaining details later." in body
            else "Thank you for sharing the required details."
            if "Thank you for sharing the required details." in body
            else "Thank you for sharing the required details for your training requirement."
            if "Thank you for sharing the required details for your training requirement." in body
            else ""
        )

    source_gmail_message_id = _current_inbound_message_id(email_doc)
    duplicate_terms = []
    if email_doc.get("email_id"):
        duplicate_terms.append({"source_email_id": email_doc.get("email_id")})
    if source_gmail_message_id:
        duplicate_terms.append({"source_gmail_message_id": source_gmail_message_id})
    existing_sent_log = None
    duplicate_query = None
    if duplicate_terms:
        duplicate_mail_types = (
            ["client_auto_reply", "client_reply"]
            if mail_type == "client_auto_reply"
            else ["trainer_auto_reply", "mail2"] if mail_type in {"trainer_auto_reply", "mail2"}
            else ["office_auto_reply"]
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
        existing_sent_log = await db["email_logs"].find_one(duplicate_query, {"_id": 0, "sent_at": 1, "created_at": 1})
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
            "sent_at": sent_at,
            "source_gmail_message_id": source_gmail_message_id,
        }

    if mail_type == "client_auto_reply":
        recent_cutoff = _now() - timedelta(hours=12)
        template_marker = client_template_marker
        if template_marker:
            recent_template_reply = await db["email_logs"].find_one(
                {
                    "mail_type": "client_auto_reply",
                    "status": "sent",
                    "subject": subject,
                    "body": {"$regex": re.escape(template_marker), "$options": "i"},
                    "$and": [
                        {"$or": [{"to_email": to}, {"recipient": to}]},
                        {"$or": [{"sent_at": {"$gte": recent_cutoff}}, {"created_at": {"$gte": recent_cutoff}}]},
                    ],
                },
                {"_id": 0, "sent_at": 1, "created_at": 1, "email_id": 1},
                sort=[("created_at", -1)],
            )
            if recent_template_reply:
                sent_at = recent_template_reply.get("sent_at") or recent_template_reply.get("created_at") or _now()
                return {
                    "success": True,
                    "error": "",
                    "already_sent": True,
                    "deduped_by_template": True,
                    "to": to,
                    "subject": subject,
                    "sent_at": sent_at,
                    "source_gmail_message_id": source_gmail_message_id,
                }

    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    success, error = await send_email_async(to=to, subject=subject, body=body, smtp_config=smtp_config)
    now = _now()
    if success:
        await db["email_logs"].insert_one({
            "email_id": f"RPL-{uuid.uuid4().hex[:10].upper()}",
            "direction": "outbound",
            "recipient": to,
            "to_email": to,
            "subject": subject,
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
        "sent_at": now,
        "source_gmail_message_id": source_gmail_message_id,
    }


def _requirement_payload_from_email(email_doc: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    technology = extracted.get("technology_needed") or extracted.get("technology")
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
        "budget_min": extracted.get("budget_min"),
        "budget_max": extracted.get("budget_max"),
        "budget_range": extracted.get("budget_range"),
        "budget_currency": extracted.get("budget_currency"),
        "participant_count": extracted.get("participant_count"),
        "client_domain": extracted.get("client_domain"),
        "client_industry": extracted.get("client_industry"),
        "topics": extracted.get("topics"),
        "custom_topics": extracted.get("custom_topics"),
        "client_name": extracted.get("client_name"),
        "client_company": extracted.get("client_company"),
        "client_email": extracted.get("client_email"),
        "top_n": 10,
        "send_emails": False,
        "status": "active",
        "priority": "high" if extracted.get("urgency") == "urgent" else "medium",
        "customer_id": extracted.get("client_email") or "client-inbox",
        "metadata": {
            "source": "client_inbox",
            "source_email_id": email_doc.get("email_id"),
            "gmail_message_id": email_doc.get("gmail_message_id"),
            "original_subject": email_doc.get("subject"),
            "requested_details": extracted.get("requested_details", []),
            "parser": extracted.get("extraction_method"),
        },
    }


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
        "client_domain",
        "client_industry",
        "topics",
        "custom_topics",
        "client_name",
        "client_company",
        "client_email",
    )
    for field in optional_fields:
        value = extracted.get(field)
        if value not in (None, "", []):
            update[field] = value

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
    if not technology or not client_email:
        return None

    status_filter = {"$nin": list(OPEN_REQUIREMENT_EXCLUDED_STATUSES)}
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
) -> Dict[str, Any]:
    email_id = email_doc.get("email_id")
    if email_doc.get("requirement_id"):
        await _update_existing_requirement_from_extracted(db, email_doc["requirement_id"], extracted)
        return {"requirement_id": email_doc["requirement_id"], "existing": True}

    existing = await db["requirements"].find_one({"metadata.source_email_id": email_id}, {"_id": 0})
    if existing:
        await _update_existing_requirement_from_extracted(db, existing.get("requirement_id"), extracted)
        return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    if reuse_existing_client_requirement:
        existing = await _find_existing_client_requirement(db, email_doc, extracted)
        if existing:
            await _update_existing_requirement_from_extracted(db, existing.get("requirement_id"), extracted)
            return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    payload = _requirement_payload_from_email(email_doc, extracted)
    async with httpx.AsyncClient(timeout=90) as client:
        response = await _post_with_local_fallback(client, f"{CORE_API_URL}/api/v1/requirements", json=payload)
        response.raise_for_status()
        return response.json()


async def _send_initial_trainer_mail(
    requirement_id: str,
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await _post_with_local_fallback(
            client,
            f"{TRAINER_SERVICE_URL}/api/v1/shortlists/send-mail",
            json={
                "requirement_id": requirement_id,
                "mail_type": "mail1",
            },
        )
        response.raise_for_status()
        return response.json()


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
    requirement_id = requirement_result.get("requirement_id")
    if not requirement_id:
        raise RuntimeError("No requirement_id available for trainer automation")

    send_result = await _send_initial_trainer_mail(requirement_id, extracted)
    sent_count = _safe_int(send_result.get("sent"), 0)
    automation_update = _trainer_automation_update(send_result)
    trainer_automation_started = automation_update.get("trainer_automation_status") == "started"
    return {
        "requirement_id": requirement_id,
        "requirement_created": True,
        **automation_update,
        "mail_automation": send_result,
        "status": "auto_sent" if sent_count > 0 or trainer_automation_started else "trainer_email_failed",
    }


async def _process_client_requirement_email(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
) -> Dict[str, Any]:
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
    now = _now()
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

    source_mail_type = str(email_doc.get("source_outbound_mail_type") or "").strip()
    if source_mail_type in {"mail1", "mail1_reminder"} and email_doc.get("requirement_id") and email_doc.get("trainer_id"):
        reply = _trainer_mail2_details_reply(email_doc)
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
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "trainer_mail1_reply",
            "auto_reply": auto_reply_result,
        }

    if source_mail_type in {"mail2", "mail2_followup"} and email_doc.get("requirement_id") and email_doc.get("trainer_id"):
        trainer_doc = {
            **email_doc,
            "from_email": sender_email or email_doc.get("from_email") or email_doc.get("sender") or "",
            "classification_body": _strip_quoted_email_history(body) or body,
            "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
            "office_mail_category": "trainer_details_sent",
        }
        forward_result = await _forward_trainer_commercials_to_client(
            db,
            trainer_doc,
            {"person_type": "trainer", "scenario": "trainer_details_sent"},
        )
        success = bool(forward_result.get("success") or forward_result.get("attempted"))
        update = {
            "processed": True,
            "processed_at": now,
            "status": "processed" if success else "needs_manual_review",
            "reply_status": "details_received" if success else "pending_review",
            "reply_template_key": "trainer_details_received",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_details_sent"},
            "office_mail_category": "trainer_details_sent",
            "trainer_details_received": True,
            "trainer_details_received_at": now,
            "commercial_forward_result": forward_result,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "auto_send_block_reason": "",
            "auto_send_error": "" if success else forward_result.get("error", forward_result.get("reason", "")),
            "reply_error": "" if success else forward_result.get("error", forward_result.get("reason", "")),
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "email_id": email_doc.get("email_id"),
            "status": update["status"],
            "reason": "trainer_mail2_details_received",
            "commercial_forward": forward_result,
        }

    latest_body = _strip_quoted_email_history(body)
    extraction_body = latest_body or body
    extracted = _extract_requirement_from_email(
        subject=subject,
        body=extraction_body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
    extracted = _merge_existing_requirement_context(extracted, email_doc)
    classification_body = latest_body
    classification = classify_email(
        subject=subject,
        body=classification_body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
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
    should_start_trainer_search = _should_start_trainer_automation(subject, email_doc, extracted)
    reply: Dict[str, str] = {}
    template_reply = build_auto_reply(
        classification,
        extracted,
        subject=subject,
        sender_name=email_doc.get("from_name") or "",
    )
    selected_template_key = template_reply.get("template_key") or ""
    if extracted.get("is_training_request"):
        missing_details = extracted.get("needs_clarification") or []
        if not missing_details:
            reply = _client_full_details_reply(extracted)
            selected_template_key = "client_full_details_received"
        elif client_authorized_search:
            reply = _client_proceed_ack_reply(extracted, details_later=details_later)
            selected_template_key = "client_proceed_ack"
        else:
            reply = _client_reply_for_requirement(extracted)
            selected_template_key = "client_missing_details"
    elif extracted.get("direct_request_language") and not extracted.get("is_non_client_email"):
        reply = _client_clarification_reply(extracted)
        selected_template_key = "client_clarification"
    elif template_reply.get("body"):
        reply = {"subject": template_reply.get("subject") or subject, "body": template_reply["body"]}

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
    if source_mail_type_for_routing in {"mail3", "mail3_slot_followup", "mail3_too_many_slots"}:
        try:
            trainer_slot_result = await _handle_trainer_slot_reply(db, send_email_doc)
        except Exception as exc:
            logger.exception("Trainer slot automation failed for %s", email_doc.get("email_id"))
            trainer_slot_result = {"attempted": True, "success": False, "error": str(exc)}
        if trainer_slot_result.get("attempted"):
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
                "status": "auto_sent" if trainer_slot_result.get("success") else "needs_manual_review",
                "reply_status": "auto_sent" if trainer_slot_result.get("success") else "needs_manual_review",
                "processed": True,
                "processed_at": trainer_slot_result.get("sent_at") or now,
                "classification_reason": "trainer_slot_reply",
                "reply_template_key": "trainer_slot_reply",
                "trainer_slot_automation": trainer_slot_result,
                "mail_automation": automation,
                "auto_send_candidate": False,
                "auto_send_eligible": False,
                "auto_send_ready": False,
                "updated_at": _now(),
            }
            await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
            return {
                "processed": True,
                "reason": "trainer_slot_reply",
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
            "status": "auto_sent" if trainer_slot_result.get("success") else "needs_manual_review",
            "reply_status": "auto_sent" if trainer_slot_result.get("success") else "needs_manual_review",
            "processed": True,
            "processed_at": trainer_slot_result.get("sent_at") or now,
            "classification_reason": "trainer_slot_reply",
            "trainer_slot_automation": trainer_slot_result,
            "mail_automation": automation,
            "auto_send_candidate": False,
            "auto_send_eligible": False,
            "auto_send_ready": False,
            "updated_at": _now(),
        }
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": set_update})
        return {
            "processed": True,
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

    try:
        requirement_result = await _create_requirement(
            email_doc,
            extracted,
            db,
            reuse_existing_client_requirement=_is_reply_thread(subject, email_doc),
        )
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
                    "auto_sent_at": auto_reply_result.get("sent_at"),
                    "auto_send_error": "",
                    "auto_send_candidate": False,
                    "auto_send_eligible": False,
                    "auto_send_ready": False,
                    "auto_send_retry_after": None,
                })
                # Run intelligence search to enrich candidates before emailing trainers
                try:
                    intel_result = await _call_intelligence_search(extracted, max_results=20)
                    send_result["intel_search"] = intel_result
                    # If intelligence found profiles, prefer sending to trainers via trainer service
                    if _safe_int(intel_result.get("found"), 0) > 0:
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
                    else:
                        # No profiles found; mark pending automation so background processes can retry
                        reply_sent_update.update({
                            "trainer_automation_status": "no_profiles_found",
                            "pending_trainer_automation": True,
                        })
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
        await db["client_emails"].update_one({"email_id": email_doc.get("email_id")}, {"$set": update})
        return {
            "processed": True,
            "requirement_id": requirement_id,
            "status": final_status,
            "mail_automation": send_result,
        }
    except Exception as exc:
        logger.exception("Client requirement automation failed for %s", email_doc.get("email_id"))
        await db["client_emails"].update_one(
            {"email_id": email_doc.get("email_id")},
            {"$set": {
                "status": "needs_manual_review",
                "reply_status": "needs_manual_review",
                "automation_error": str(exc),
                "updated_at": _now(),
            }},
        )
        return {"processed": False, "reason": "automation_failed", "error": str(exc)}


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
            {"gmail_message_id": {"$in": message_id_candidates}},
            {"_id": 0},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if exact_match:
            return exact_match

    if is_thread_reply and thread_message_ids:
        message_match = await db["client_emails"].find_one(
            {
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
                "status": {"$nin": ["spam", "rejected"]},
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
) -> Optional[Dict[str, Any]]:
    if not from_email:
        return None

    message_id_candidates = _message_id_candidates(*message_ids)
    if message_id_candidates:
        exact = await db["email_logs"].find_one(
            {
                "direction": "outbound",
                "status": "sent",
                "gmail_message_id": {"$in": message_id_candidates},
                "$or": [
                    {"recipient": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                    {"to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                ],
            },
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if exact:
            return exact

    cursor = (
        db["email_logs"]
        .find(
            {
                "direction": "outbound",
                "status": "sent",
                "requirement_id": {"$exists": True, "$nin": ["", None]},
                "$or": [
                    {"recipient": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                    {"to_email": {"$regex": f"^{re.escape(from_email)}$", "$options": "i"}},
                ],
            },
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(25)
    )
    async for log in cursor:
        if _subjects_match_thread(subject, log.get("subject")):
            return log
    return None


async def _persist_client_email_from_reply(db: AsyncIOMotorDatabase, reply: dict) -> str:
    raw_from = reply.get("from_raw") or reply.get("from_email") or ""
    parsed_name, parsed_email = parseaddr(raw_from)
    from_email = _email_address(reply.get("from_email") or parsed_email or raw_from)
    from_name = _clean(parsed_name) or from_email.split("@")[0]
    msg_id_hdr = reply.get("message_id_header", "")
    in_reply_to = reply.get("in_reply_to")
    references = reply.get("references")
    message_ids = _message_id_candidates(msg_id_hdr, in_reply_to, references)
    is_thread_reply = bool(
        in_reply_to
        or references
        or re.match(r"^\s*(?:re|fw|fwd)\s*:", str(reply.get("subject") or ""), flags=re.IGNORECASE)
    )
    existing = await _find_existing_client_email_for_reply(
        db,
        from_email=from_email,
        subject=reply.get("subject"),
        message_id=msg_id_hdr,
        thread_message_ids=message_ids,
        is_thread_reply=is_thread_reply,
    )
    related_outbound = await _find_outbound_log_for_reply(
        db,
        from_email=from_email,
        subject=reply.get("subject"),
        message_ids=message_ids,
    )
    now = _now()
    previous_message_id = _clean(
        (existing or {}).get("latest_gmail_message_id")
        or (existing or {}).get("gmail_message_id")
        or ""
    )
    is_new_inbound_message = bool(msg_id_hdr and msg_id_hdr != previous_message_id)
    update_fields = {
        "from_email": from_email,
        "from_name": from_name,
        "subject": reply.get("subject"),
        "body": (reply.get("body") or "")[:2000],
        "raw_body": reply.get("body") or "",
        "clean_body": reply.get("body") or "",
        "body_snippet": (reply.get("body") or "")[:500],
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
            and _has_details_for_trainer_search(candidate_extracted)
        )
        source_mail_type = str(
            update_fields.get("source_outbound_mail_type")
            or merged.get("source_outbound_mail_type")
            or ""
        ).strip()
        should_process_linked_automation_reply = (
            is_new_inbound_message
            and bool(merged.get("requirement_id"))
            and source_mail_type in {
                "mail1",
                "mail1_reminder",
                "mail2",
                "mail2_followup",
                "trainer_commercials_to_client",
                "commercial_negotiation",
                "trainer_rate_discussion",
                "client_budget_revision_request",
                "mail3",
                "mail3_slot_followup",
                "mail3_too_many_slots",
                "mail6_toc",
                "client_slots",
                "client_interview_schedule",
                "mail4",
            }
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
    for reply in replies:
        msg_id_hdr = reply.get("message_id_header", "")
        if msg_id_hdr:
            existing = await db.email_logs.find_one({"gmail_message_id": msg_id_hdr})
            if existing:
                client_email_id = await _persist_client_email_from_reply(db, reply)
                linked_doc = await db["client_emails"].find_one(
                    {"email_id": client_email_id},
                    {
                        "_id": 0,
                        "requirement_id": 1,
                        "trainer_id": 1,
                        "trainer_name": 1,
                        "source_outbound_email_id": 1,
                        "source_outbound_mail_type": 1,
                        "processed": 1,
                    },
                )
                if linked_doc:
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
                    if not linked_doc.get("processed"):
                        await _process_client_requirement_email(db, linked_doc)
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
            {
                "_id": 0,
                "requirement_id": 1,
                "trainer_id": 1,
                "trainer_name": 1,
                "source_outbound_email_id": 1,
                "source_outbound_mail_type": 1,
                "processed": 1,
            },
        )
        if linked_doc:
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
            if not linked_doc.get("processed"):
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
                    {"processed": {"$ne": True}},
                    {"extracted": {"$exists": False}},
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
            {"source_outbound_mail_type": {
                "$in": [
                    "mail1",
                    "mail1_reminder",
                    "mail2",
                    "mail2_followup",
                    "commercial_negotiation",
                    "trainer_rate_discussion",
                    "mail3",
                    "mail3_slot_followup",
                    "mail3_too_many_slots",
                    "mail6_toc",
                    "client_slots",
                    "client_interview_schedule",
                    "mail4",
                ]
            }},
            {"processed": {"$ne": True}},
            {"status": {"$nin": list(FINAL_CLIENT_STATUSES)}},
            retry_due_query,
        ],
    }
    query = {
        "$or": [
            linked_trainer_reply_query,
            {"$and": [today_query, {"pending_trainer_automation": True}, retry_due_query]},
            {"$and": [today_query, latest_message_needs_reply_query]},
            pending_work_query,
        ]
    }
    cursor = (
        db["client_emails"]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 500)))
    )
    items = [doc async for doc in cursor]
    results = [await _process_client_requirement_email(db, doc) for doc in items]
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
) -> int:
    """Poll IMAP and persist/process messages."""
    settings_doc = await _load_admin_settings(db)
    imap_config = settings_doc.get("emailCfg") or None
    loop = asyncio.get_event_loop()
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
