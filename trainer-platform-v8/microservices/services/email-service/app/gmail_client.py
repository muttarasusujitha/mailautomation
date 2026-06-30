"""Gmail OAuth2 + SMTP/IMAP helpers for the email-service."""
import asyncio
import base64
import imaplib
import logging
import os
import smtplib
from email import message_from_bytes
from email.header import decode_header, make_header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

POSITIVE_SIGNALS = [
    "yes", "available", "interested", "confirm", "accept",
    "happy to", "sure", "okay", "ok", "look forward", "schedule", "agree",
]
NEGATIVE_SIGNALS = [
    "no", "not available", "not interested", "decline",
    "unable", "cannot", "busy", "engaged", "withdraw",
]


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def _token_path() -> str:
    path = settings.GOOGLE_TOKEN_FILE or "config/token.json"
    if os.path.isabs(path):
        return path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, path)


def _load_oauth_service():
    """Load Gmail OAuth2 service. Returns (service, error_str)."""
    token_file = _token_path()
    if not os.path.exists(token_file):
        return None, "Gmail OAuth token not found. Please reconnect Gmail."
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_file, GMAIL_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        if not creds or not creds.valid:
            return None, "Gmail OAuth token is invalid. Please reconnect Gmail."
        return build("gmail", "v1", credentials=creds), ""
    except Exception as exc:
        logger.exception("Gmail OAuth service init failed")
        return None, str(exc)


def _html_template(body: str, from_name: str, from_email: str, tracking_url: str = "") -> str:
    html_body = body.replace("\n", "<br>")
    pixel = (
        f'<img src="{tracking_url}" width="1" height="1" alt="" style="display:none;" />'
        if tracking_url else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07);">
<tr><td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 36px;">
<h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">TrainerSync</h1>
<p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">AI-Powered Trainer Matching Platform</p>
</td></tr>
<tr><td style="padding:32px 36px;color:#1e293b;font-size:15px;line-height:1.8;">{html_body}</td></tr>
<tr><td style="background:#f1f5f9;padding:20px 36px;border-top:1px solid #e2e8f0;">
<p style="margin:0;color:#94a3b8;font-size:12px;">{from_name} &bull; {from_email}</p>
</td></tr>
</table></td></tr></table>
{pixel}
</body></html>"""


def send_gmail_oauth(
    to: str,
    subject: str,
    body: str,
    from_name: str = "",
    tracking_url: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, str]:
    service, error = _load_oauth_service()
    if not service:
        return False, error
    try:
        profile = service.users().getProfile(userId="me").execute()
        gmail_user = profile.get("emailAddress") or settings.GMAIL_USER
        sender_name = from_name or settings.FROM_NAME

        msg = MIMEMultipart("mixed") if attachments else MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{gmail_user}>"
        msg["To"] = to
        msg["Reply-To"] = gmail_user

        alt = MIMEMultipart("alternative") if attachments else msg
        if attachments:
            msg.attach(alt)
        alt.attach(MIMEText(body, "plain", "utf-8"))
        alt.attach(MIMEText(_html_template(body, sender_name, gmail_user, tracking_url), "html", "utf-8"))

        for att in attachments or []:
            part = MIMEApplication(att.get("content") or b"", _subtype=att.get("subtype") or "octet-stream")
            part.add_header("Content-Disposition", "attachment", filename=att.get("filename") or "attachment")
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, ""
    except Exception as exc:
        logger.exception("Gmail OAuth send failed to %s", to)
        return False, str(exc)


def send_smtp(
    to: str,
    subject: str,
    body: str,
    smtp_config: Optional[Dict[str, Any]] = None,
    tracking_url: str = "",
) -> Tuple[bool, str]:
    cfg = smtp_config or {}
    user = cfg.get("smtpUser") or settings.GMAIL_USER
    pwd = (cfg.get("smtpPass") or settings.effective_gmail_pass).replace(" ", "")
    from_name = cfg.get("fromName") or settings.FROM_NAME
    from_email = cfg.get("fromEmail") or settings.FROM_EMAIL or user
    host = cfg.get("smtpHost") or settings.SMTP_HOST
    port = int(cfg.get("smtpPort") or settings.SMTP_PORT)

    if not user or not pwd:
        # fall back to OAuth
        return send_gmail_oauth(to, subject, body, from_name, tracking_url)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to
        msg["Reply-To"] = from_email
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(_html_template(body, from_name, from_email, tracking_url), "html"))

        try:
            with smtplib.SMTP_SSL(host, 465 if port == 587 else port, timeout=15) as s:
                s.login(user, pwd)
                s.sendmail(from_email, to, msg.as_string())
        except Exception:
            with smtplib.SMTP(host, 587 if port == 465 else port, timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.login(user, pwd)
                s.sendmail(from_email, to, msg.as_string())

        logger.info("Email sent to %s", to)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        # try OAuth fallback for Gmail
        if "gmail" in host.lower():
            return send_gmail_oauth(to, subject, body, from_name, tracking_url)
        return False, "SMTP authentication failed"
    except Exception as exc:
        logger.exception("SMTP send failed to %s", to)
        return False, str(exc)


async def send_email_async(
    to: str,
    subject: str,
    body: str,
    smtp_config: Optional[Dict[str, Any]] = None,
    tracking_url: str = "",
) -> Tuple[bool, str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_smtp, to, subject, body, smtp_config, tracking_url)


def check_imap_replies(
    since_days: int = 7,
    max_messages: int = 50,
    from_emails: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Poll Gmail IMAP inbox for replies."""
    user = settings.GMAIL_USER
    pwd = settings.effective_gmail_pass
    if not user or not pwd:
        return []

    replies = []
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT, timeout=20)
        mail.login(user, pwd)
        mail.select("inbox")
        since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")

        msg_ids: List[bytes] = []
        if from_emails:
            seen: set = set()
            for sender in from_emails[:100]:
                _, data = mail.search(None, f'(SINCE {since} FROM "{sender}")')
                for mid in (data[0].split() if data and data[0] else []):
                    if mid not in seen:
                        seen.add(mid)
                        msg_ids.append(mid)
        else:
            _, data = mail.search(None, f"(SINCE {since})")
            msg_ids = data[0].split() if data and data[0] else []

        for mid in msg_ids[-max_messages:]:
            try:
                _, msg_data = mail.fetch(mid, "(RFC822)")
                if not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = message_from_bytes(msg_data[0][1])
                from_addr = msg.get("From", "")
                from_email = parseaddr(from_addr)[1] or from_addr
                subject = _decode_header(msg.get("Subject", ""))
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                else:
                    body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                try:
                    date_hdr = msg.get("Date", "")
                    received_at = parsedate_to_datetime(date_hdr).replace(tzinfo=None) if date_hdr else datetime.utcnow()
                except Exception:
                    received_at = datetime.utcnow()

                lower = body_text.lower()
                is_pos = any(s in lower for s in POSITIVE_SIGNALS)
                is_neg = any(s in lower for s in NEGATIVE_SIGNALS)
                sentiment = "positive" if is_pos else ("negative" if is_neg else "neutral")
                action = "mark_interested" if is_pos else ("mark_declined" if is_neg else "requires_review")

                replies.append({
                    "msg_id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "message_id_header": msg.get("Message-ID", ""),
                    "in_reply_to": msg.get("In-Reply-To", ""),
                    "references": msg.get("References", ""),
                    "from_email": from_email,
                    "from_raw": from_addr,
                    "subject": subject,
                    "body": body_text[:2000],
                    "sentiment": sentiment,
                    "action": action,
                    "received_at": received_at.isoformat(),
                })
            except Exception:
                continue
    except Exception:
        logger.exception("IMAP check failed")
    finally:
        try:
            if mail:
                mail.close()
        except Exception:
            pass
        try:
            if mail:
                mail.logout()
        except Exception:
            pass

    return replies
