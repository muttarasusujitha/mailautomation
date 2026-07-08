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
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.gmail_client import check_imap_replies, send_email_async

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

CORE_API_URL = settings.CORE_API_URL.rstrip("/")
TRAINER_SERVICE_URL = settings.TRAINER_SERVICE_URL.rstrip("/")
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))

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
    "updates",
    "updates-noreply",
}
BULK_SENDER_DOMAINS = {
    "alison.com",
    "github.com",
    "linkedin.com",
    "naukri.com",
    "nptel.iitm.ac.in",
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
    r"\bplease\s+(?:share|send|provide)\b.{0,90}\b(?:trainer|profiles?|resume|commercials?|availability)\b",
    r"\b(?:corporate|classroom|online|offline|virtual|onsite|on-site)\s+training\s+(?:requirement|program|session|workshop)\b",
)
PROCEED_NOW_PATTERNS = (
    r"\b(?:please\s+)?proceed(?:\s+(?:now|further|ahead|with))?\b",
    r"\bgo\s+ahead\b",
    r"\bmove\s+ahead\b",
    r"\bstart\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
    r"\bbegin\b.{0,40}\b(?:search|shortlist|process|trainer)\b",
)
DETAILS_LATER_PATTERNS = (
    r"\b(?:send|sent|share|provide)\b.{0,50}\blater\b",
    r"\blater\b.{0,50}\b(?:send|share|provide|details?)\b",
    r"\bdetails?\s+(?:later|will\s+follow|to\s+follow)\b",
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
    return _clean(email_doc.get("latest_gmail_message_id") or email_doc.get("gmail_message_id") or "")


def _has_replied_to_latest_message(email_doc: Dict[str, Any]) -> bool:
    if not email_doc.get("reply_sent"):
        return False

    current_message_id = _current_inbound_message_id(email_doc)
    if not current_message_id:
        return True

    replied_message_id = _clean(
        email_doc.get("reply_sent_for_message_id")
        or email_doc.get("replied_to_gmail_message_id")
        or ""
    )
    if replied_message_id:
        return replied_message_id == current_message_id

    original_message_id = _clean(email_doc.get("gmail_message_id") or "")
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
    if not _auto_send_retry_due(email_doc):
        logger.debug("Auto-reply blocked: retry not due. email_id=%s retry_after=%s", email_doc.get("email_id"), email_doc.get("auto_send_retry_after"))
        return False
    return True


def _has_details_for_trainer_search(extracted: Dict[str, Any]) -> bool:
    return bool(extracted.get("is_training_request")) and not extracted.get("needs_clarification")


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
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?im)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?\s*(?:{label_pattern})"
        rf"\s*(?:\*\*)?\s*[:\-]\s*(.+?)\s*$"
    )
    match = pattern.search(text or "")
    return _clean(match.group(1)) if match else ""


def _has_direct_training_request_language(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in DIRECT_REQUEST_PATTERNS)


def _client_wants_to_proceed_now(subject: str, body: str) -> bool:
    text = _plain_text(f"{subject}\n{body}").lower()
    has_proceed_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in PROCEED_NOW_PATTERNS
    )
    if not has_proceed_signal:
        return False
    has_details_later_signal = any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in DETAILS_LATER_PATTERNS
    )
    return has_details_later_signal or "proceed now" in text or "go ahead" in text


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


def _extract_budget(text: str) -> Dict[str, Any]:
    rupee = re.escape(chr(0x20B9))
    pattern = re.compile(
        r"(?:budget|commercials?|rate|cost|price)[^\n\r\d]{0,30}"
        rf"(?:INR|Rs\.?|{rupee}|USD|\$)?\s*([\d,]+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return {}
    amount = _safe_float(match.group(1))
    if amount <= 0:
        return {}
    currency = "USD" if "$" in match.group(0) or "USD" in match.group(0).upper() else "INR"
    per_day = bool(re.search(r"per\s*day|/day|daily", match.group(0), flags=re.IGNORECASE))
    return {
        "budget_per_day" if per_day else "budget_total": amount,
        "budget_currency": currency,
    }


def _missing_training_details(details: Dict[str, Any]) -> List[str]:
    missing = []
    if not (details.get("budget_total") or details.get("budget_per_day")):
        missing.append("Commercials not provided by client")
    if not (details.get("duration_days") or details.get("duration_hours") or details.get("duration_text")):
        missing.append("Training duration not provided")
    if not details.get("timing"):
        missing.append("Exact dates not provided")
    if not details.get("mode"):
        missing.append("Location / mode not provided")
    if details.get("participant_count") is None:
        missing.append("Participant count not provided")
    return missing


def _extract_requirement_from_email(subject: str, body: str, sender_email: str = "", sender_name: str = "") -> Dict[str, Any]:
    sender_email = _email_address(sender_email)
    body_text = _plain_text(body)
    text = f"Subject: {subject}\n{body_text}"
    lower = text.lower()
    direct_request = _has_direct_training_request_language(subject, body_text)
    non_client_email = _is_obvious_non_client_email(sender_email, subject, body_text)
    technology = _infer_technology(subject, body_text)
    mode = _field_value(text, ["Mode", "Delivery Mode", "Training Mode"])
    if not mode:
        if "online" in lower or "virtual" in lower:
            mode = "Online"
        elif "offline" in lower or "onsite" in lower or "on-site" in lower:
            mode = "Offline"
        elif "hybrid" in lower:
            mode = "Hybrid"

    audience_level = _field_value(text, ["Audience Level", "Level", "Audience"])
    timing = _field_value(text, ["Timings", "Timing", "Time", "Schedule"])
    duration = _extract_duration(text)
    budget = _extract_budget(text)

    participants = None
    participant_text = _field_value(text, ["Participants", "Participant Count", "Learners", "Trainees"])
    participant_match = re.search(
        r"(\d+)\s*(?:participants?|learners?|trainees?|people|pax)",
        participant_text or text,
        flags=re.IGNORECASE,
    )
    if participant_match:
        participants = _safe_int(participant_match.group(1))

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
        "participant_count",
        "duration_text",
        "duration_days",
        "duration_hours",
        "budget_total",
        "budget_per_day",
        "budget_currency",
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

    technology = merged.get("technology_needed") or merged.get("technology") or merged.get("domain")
    if technology:
        merged["technology_needed"] = technology
        merged["technology"] = technology
        merged["domain"] = technology
        if not merged.get("required_skills"):
            merged["required_skills"] = [technology]

    merged["needs_clarification"] = _missing_training_details(merged)
    if email_doc.get("requirement_id") and technology and not merged.get("is_non_client_email"):
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
    return f"Regards,\n{settings.FROM_NAME or 'TrainerSync'}"


def _format_missing_details(extracted: Dict[str, Any]) -> str:
    missing = extracted.get("requested_details") or []
    if not missing:
        missing = extracted.get("needs_clarification") or []
    if not missing:
        return ""

    lines = [f"* {item}" for item in missing]
    return "\n" + "\n".join(lines) + "\n\n"


def _client_reply_for_requirement(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "Devops"
    missing_details = _format_missing_details(extracted)
    if missing_details:
        body = (
            "Dear Client,\n\n"
            "Thank you for sharing your Devops training requirement.\n\n"
            "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
            f"{missing_details}"
            "Meanwhile, we will begin an initial trainer search based on the Devops domain and the information currently available. "
            "Once we receive the above details, we will refine the shortlist and share the most relevant trainer profiles for your review.\n\n"
            "We look forward to your response.\n\n"
            "Regards,\n"
            "Recruitment Team,\n"
            "Calhan Technologies"
        )
    else:
        body = (
            "Dear Client,\n\n"
            "Thank you for sharing your Devops training requirement.\n\n"
            "To help us identify and recommend the most suitable trainers, kindly provide the following details:\n\n"
            "* Training duration\n"
            "* Preferred training dates\n"
            "* Daily training timings\n"
            "* Audience level (Beginner / Intermediate / Advanced)\n"
            "* Training mode (Online / Offline / Hybrid)\n"
            "* Budget or expected commercial charges per day/session\n\n"
            "Meanwhile, we will begin an initial trainer search based on the Devops domain and the information currently available. "
            "Once we receive the above details, we will refine the shortlist and share the most relevant trainer profiles for your review.\n\n"
            "We look forward to your response.\n\n"
            "Regards,\n"
            "Recruitment Team,\n"
            "Calhan Technologies"
        )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_proceed_ack_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    technology = extracted.get("technology_needed") or "training"
    client_name = _client_salutation(extracted)
    body = (
        f"Dear {client_name},\n\n"
        "Thank you for your confirmation.\n\n"
        f"Sure, we will proceed with the initial trainer search for your {technology} training requirement "
        "based on the information currently available.\n\n"
        "Once you share the remaining details, we will refine the shortlist further and share the most suitable "
        "trainer profiles with experience, certifications, availability, and commercials for your review.\n\n"
        + _reply_signature()
    )
    return {"subject": f"Re: {technology} Trainer Requirement", "body": body}


def _client_clarification_reply(extracted: Dict[str, Any]) -> Dict[str, str]:
    client_name = _client_salutation(extracted)
    body = (
        f"Dear {client_name},\n\n"
        "Thank you for sharing the training requirement. To shortlist the right trainer profiles, "
        "please confirm the technology/topic, delivery mode, expected dates or duration, participant count, "
        "and commercials or budget range.\n\n"
        "Once we have these details, we will share suitable profiles for your review.\n\n"
        + _reply_signature()
    )
    return {"subject": "Re: Training Requirement Details", "body": body}


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
        f"Dear Trainer,\n\n"
        f"We have an immediate corporate training requirement and would like to check your interest and availability.\n\n"
        f"Requirement Details:\n"
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

    enabled_value = inbox_cfg.get("autoSendEnabled")
    if enabled_value is None:
        enabled_value = legacy_auto_send_cfg.get("enabled")
    if enabled_value is None:
        enabled_value = scheduler_cfg.get("autoSendEnabled")

    threshold_value = inbox_cfg.get("autoSendThreshold")
    if threshold_value is None:
        threshold_value = legacy_auto_send_cfg.get("threshold")
    if threshold_value is None:
        threshold_value = scheduler_cfg.get("autoSendConfidenceThreshold")

    return {
        "enabled": _coerce_bool(enabled_value, True),
        "threshold": _normalise_threshold(threshold_value, 0.7),
        "mailbox_addresses": _configured_mailbox_addresses(settings_doc),
    }


async def _send_client_auto_reply(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    reply: Dict[str, str],
    requirement_id: str = "",
) -> Dict[str, Any]:
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

    settings_doc = await _load_admin_settings(db)
    smtp_config = settings_doc.get("emailCfg") or None
    success, error = await send_email_async(to=to, subject=subject, body=body, smtp_config=smtp_config)
    now = _now()
    source_gmail_message_id = _current_inbound_message_id(email_doc)
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
            "mail_type": "client_auto_reply",
            "source_email_id": email_doc.get("email_id"),
            "source_gmail_message_id": source_gmail_message_id,
            "requirement_id": requirement_id,
            "sent_at": now,
            "created_at": now,
            "updated_at": now,
        })

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
        "timing": extracted.get("timing"),
        "budget": extracted.get("budget_total") or extracted.get("budget_per_day"),
        "budget_per_day": extracted.get("budget_per_day"),
        "budget_currency": extracted.get("budget_currency"),
        "participant_count": extracted.get("participant_count"),
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


async def _find_existing_client_requirement(
    db: AsyncIOMotorDatabase,
    email_doc: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
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
        return {"requirement_id": email_doc["requirement_id"], "existing": True}

    existing = await db["requirements"].find_one({"metadata.source_email_id": email_id}, {"_id": 0})
    if existing:
        return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    if reuse_existing_client_requirement:
        existing = await _find_existing_client_requirement(db, email_doc, extracted)
        if existing:
            return {"requirement_id": existing.get("requirement_id"), "existing": True, "requirement": existing}

    payload = _requirement_payload_from_email(email_doc, extracted)
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{CORE_API_URL}/api/v1/requirements", json=payload)
        response.raise_for_status()
        return response.json()


async def _send_initial_trainer_mail(
    requirement_id: str,
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
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
            r = await client.post(
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
        reuse_existing_client_requirement=True,
    )
    requirement_id = requirement_result.get("requirement_id")
    if not requirement_id:
        raise RuntimeError("No requirement_id available for trainer automation")

    send_result = await _send_initial_trainer_mail(requirement_id, extracted)
    sent_count = _safe_int(send_result.get("sent"), 0)
    automation_update = _trainer_automation_update(send_result)
    return {
        "requirement_id": requirement_id,
        "requirement_created": True,
        **automation_update,
        "mail_automation": send_result,
        "status": "auto_sent" if sent_count > 0 else "trainer_email_failed",
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
    sender_email = _email_address(email_doc.get("from_email") or "")
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

    extracted = _extract_requirement_from_email(
        subject=subject,
        body=body,
        sender_email=email_doc.get("from_email") or "",
        sender_name=email_doc.get("from_name") or "",
    )
    extracted = _merge_existing_requirement_context(extracted, email_doc)
    client_authorized_search = _client_wants_to_proceed_now(subject, body)
    details_ready_for_search = _has_details_for_trainer_search(extracted)
    should_start_trainer_search = _should_start_trainer_automation(subject, email_doc, extracted)
    reply: Dict[str, str] = {}
    if extracted.get("is_training_request"):
        reply = _client_proceed_ack_reply(extracted) if (client_authorized_search or details_ready_for_search) else _client_reply_for_requirement(extracted)
    elif extracted.get("direct_request_language") and not extracted.get("is_non_client_email"):
        reply = _client_clarification_reply(extracted)

    is_initial_requirement_request = (
        extracted.get("direct_request_language")
        and not extracted.get("is_non_client_email")
        and not _is_reply_thread(subject, email_doc)
    )
    auto_send_candidate = bool(reply) and (
        extracted.get("is_training_request")
        or extracted.get("direct_request_language")
        or is_initial_requirement_request
    )
    confidence = _safe_float(extracted.get("confidence"), 0)
    auto_send_eligible = auto_send_candidate
    auto_send_ready = settings["enabled"] and auto_send_candidate
    auto_send_block_reason = ""
    if reply and not settings["enabled"]:
        auto_send_block_reason = "auto_send_disabled"
    elif reply and not auto_send_candidate:
        auto_send_block_reason = "not_auto_send_candidate"

    base_update = {
        "extracted": extracted,
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
                auto_reply_result = await _send_client_auto_reply(db, email_doc, reply)
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
            reuse_existing_client_requirement=client_authorized_search or _is_reply_thread(subject, email_doc),
        )
        requirement_id = requirement_result.get("requirement_id")
        if not requirement_id:
            raise RuntimeError("Core API did not return a requirement_id")

        send_result: Dict[str, Any] = {
            "auto_send_enabled": settings["enabled"],
            "auto_send_threshold": settings["threshold"],
            "auto_send_candidate": auto_send_candidate,
            "auto_send_eligible": auto_send_eligible,
            "auto_send_ready": auto_send_ready,
            "auto_send_block_reason": auto_send_block_reason,
            "client_authorized_search": client_authorized_search,
            "pending_client_reply": False,
            "sent": 0,
            "total": 0,
        }
        already_replied_to_latest = _has_replied_to_latest_message(email_doc)
        final_status = "auto_sent" if already_replied_to_latest else "pending_approval"
        reply_status = "auto_sent" if already_replied_to_latest else "pending_approval"
        reply_sent_update: Dict[str, Any] = {}

        should_auto_send_reply = _should_attempt_auto_reply(email_doc, settings, auto_send_eligible, reply, confidence=confidence)
        if should_auto_send_reply:
            auto_reply_result = await _send_client_auto_reply(db, email_doc, reply, requirement_id)
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
                        if trainer_sent_count == 0 and _safe_int(trainer_send_result.get("total"), 0) > 0:
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
        if should_start_trainer_search and not trainer_already_handled and (already_replied_to_latest or final_status == "auto_sent"):
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
        if not merged.get("requirement_id") or should_process_proceed_reply or should_process_details_reply:
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
                await _persist_client_email_from_reply(db, reply)
                continue

        now = _now()
        doc = {
            "email_id": f"INB-{uuid.uuid4().hex[:10].upper()}",
            "direction": "inbound",
            "sender": reply.get("from_email"),
            "subject": reply.get("subject"),
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
        await _persist_client_email_from_reply(db, reply)
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
    query = {
        "$or": [
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
