"""
Email Automation Agent — Gmail SMTP + IMAP reply monitoring
Fixed: uses correct env key GMAIL_APP_PASSWORD or GMAIL_PASS
"""

import smtplib
import imaplib
import email as email_lib
import base64
from email.header import decode_header, make_header
from email.utils import parseaddr
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Dict, Any
from datetime import datetime, timedelta
from utils.time_utils import utc_now
import asyncio
import os
import logging

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BACKEND_DIR, "config")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", os.path.join(CONFIG_DIR, "token.json"))
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

POSITIVE_SIGNALS = ['yes', 'available', 'interested', 'confirm', 'accept',
                    'happy to', 'sure', 'okay', 'ok', 'look forward', 'schedule', 'agree']
NEGATIVE_SIGNALS = ['no', 'not available', 'not interested', 'decline',
                    'unable', 'cannot', 'busy', 'engaged', 'withdraw']


def decode_mime_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def get_gmail_password() -> str:
    pw = (
        getattr(settings, 'gmail_app_password', '') or
        getattr(settings, 'gmail_pass', '') or
        os.environ.get('GMAIL_PASS', '') or
        os.environ.get('GMAIL_APP_PASSWORD', '')
    )
    return pw.replace(' ', '')

def get_from_name() -> str:
    return getattr(settings, 'from_name', 'TrainerSync') or 'TrainerSync'

def get_from_email() -> str:
    return getattr(settings, 'from_email', '') or settings.gmail_user


def _looks_like_gmail_oauth_config(smtp_config: Dict[str, Any], smtp_host: str, smtp_user: str, from_email: str) -> bool:
    smtp_config = smtp_config or {}
    host = str(smtp_host or "").lower()
    user = str(smtp_user or "").lower()
    sender = str(from_email or "").lower()
    return (
        "gmail" in host
        or user.endswith("@gmail.com")
        or sender.endswith("@gmail.com")
        or bool(smtp_config.get("useGmailOAuth"))
    )


def _load_gmail_oauth_service():
    if not os.path.exists(GOOGLE_TOKEN_FILE):
        return None, "Gmail OAuth token not found. Please reconnect Gmail."
    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GMAIL_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
        if not creds or not creds.valid:
            return None, "Gmail OAuth token is invalid. Please reconnect Gmail."
        return build("gmail", "v1", credentials=creds), ""
    except Exception as exc:
        logger.exception("Gmail OAuth service initialization failed")
        return None, str(exc)


def send_gmail_oauth_message(
    to: str,
    subject: str,
    body: str,
    from_name: str = "",
    tracking_url: str = "",
    attachments: List[Dict[str, Any]] = None,
) -> tuple:
    service, error = _load_gmail_oauth_service()
    if not service:
        return False, error

    try:
        profile = service.users().getProfile(userId="me").execute()
        gmail_user = profile.get("emailAddress") or getattr(settings, "gmail_user", "")
        sender_name = from_name or get_from_name()

        msg_obj = MIMEMultipart("mixed") if attachments else MIMEMultipart("alternative")
        msg_obj["Subject"] = subject
        msg_obj["From"] = f"{sender_name} <{gmail_user}>"
        msg_obj["To"] = to
        msg_obj["Reply-To"] = gmail_user

        if attachments:
            alternative = MIMEMultipart("alternative")
            msg_obj.attach(alternative)
        else:
            alternative = msg_obj

        alternative.attach(MIMEText(body, "plain", "utf-8"))

        html_body = body.replace("\n", "<br>")
        tracking_pixel = (
            f'<img src="{tracking_url}" width="1" height="1" alt="" '
            'style="display:none;width:1px;height:1px;opacity:0;border:0;" />'
            if tracking_url else ""
        )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07);">
<tr><td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 36px;">
<h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">TrainerSync</h1>
<p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">AI-Powered Trainer Matching Platform</p>
</td></tr>
<tr><td style="padding:32px 36px;color:#1e293b;font-size:15px;line-height:1.8;">{html_body}</td></tr>
<tr><td style="background:#f1f5f9;padding:20px 36px;border-top:1px solid #e2e8f0;">
<p style="margin:0;color:#94a3b8;font-size:12px;">{sender_name} &bull; {gmail_user}</p>
</td></tr>
</table></td></tr></table>
{tracking_pixel}
</body></html>"""
        alternative.attach(MIMEText(html, "html", "utf-8"))

        for item in attachments or []:
            filename = item.get("filename") or "attachment"
            file_bytes = item.get("content") or b""
            subtype = item.get("subtype") or "octet-stream"
            attachment = MIMEApplication(file_bytes, _subtype=subtype)
            attachment.add_header("Content-Disposition", "attachment", filename=filename)
            msg_obj.attach(attachment)

        encoded = base64.urlsafe_b64encode(msg_obj.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": encoded}).execute()
        logger.info("Gmail OAuth email sent to %s", to)
        return True, ""
    except Exception as exc:
        logger.exception("Gmail OAuth send failed to %s", to)
        return False, str(exc)


def _append_sent_copy(msg_obj: MIMEMultipart, smtp_config: Dict[str, Any]) -> None:
    smtp_config = smtp_config or {}
    smtp_host = str(smtp_config.get("smtpHost") or "").lower()
    smtp_user = str(smtp_config.get("smtpUser") or "").strip()
    hostinger = "hostinger" in smtp_host or smtp_user.endswith("@clahantechnologies.com")
    imap_host = smtp_config.get("imapHost") or ("imap.hostinger.com" if hostinger else "")
    imap_port = int(smtp_config.get("imapPort") or 993)
    imap_user = smtp_config.get("imapUser") or smtp_config.get("smtpUser") or ""
    imap_pass = (smtp_config.get("imapPass") or smtp_config.get("smtpPass") or "").replace(" ", "")
    if not imap_host or not imap_user or not imap_pass:
        return

    folder_candidates = [
        smtp_config.get("sentFolder"),
        "INBOX.Sent" if hostinger else "",
        "Sent",
        "Sent Items",
        "INBOX.Sent Items",
    ]
    try:
        with imaplib.IMAP4_SSL(imap_host, imap_port) as imap:
            imap.login(imap_user, imap_pass)
            message_bytes = msg_obj.as_bytes()
            internal_date = imaplib.Time2Internaldate(datetime.now().timestamp())
            for folder in [f for f in folder_candidates if f]:
                try:
                    status, _ = imap.append(str(folder), "\\Seen", internal_date, message_bytes)
                    if status == "OK":
                        logger.info("Saved sent copy to IMAP folder %s", folder)
                        return
                except Exception:
                    continue
            logger.warning("Email sent, but could not append copy to IMAP Sent folder for %s", imap_user)
    except Exception:
        logger.exception("Email sent, but IMAP sent-folder copy failed for %s", imap_user)


def send_email(to: str, subject: str, body: str, smtp_config: Dict[str, Any] = None, tracking_url: str = "") -> tuple:
    smtp_config = smtp_config or {}
    gmail_user = smtp_config.get("smtpUser") or settings.gmail_user
    gmail_pass = (smtp_config.get("smtpPass") or get_gmail_password()).replace(" ", "")
    from_name  = smtp_config.get("fromName") or get_from_name()
    from_email = smtp_config.get("fromEmail") or get_from_email()
    smtp_host  = smtp_config.get("smtpHost") or "smtp.gmail.com"
    smtp_port  = int(smtp_config.get("smtpPort") or 587)
    can_use_gmail_oauth = _looks_like_gmail_oauth_config(smtp_config, smtp_host, gmail_user, from_email)

    if not gmail_user or not gmail_pass:
        if can_use_gmail_oauth:
            return send_gmail_oauth_message(to, subject, body, from_name, tracking_url)
        err = "Gmail SMTP credentials not set in Admin Email Configuration"
        logger.error("Email error: %s", err)
        return False, err

    try:
        msg_obj = MIMEMultipart("alternative")
        msg_obj["Subject"]  = subject
        msg_obj["From"]     = f"{from_name} <{from_email}>"
        msg_obj["To"]       = to
        msg_obj["Reply-To"] = from_email

        msg_obj.attach(MIMEText(body, "plain"))

        html_body = body.replace('\n', '<br>')
        tracking_pixel = (
            f'<img src="{tracking_url}" width="1" height="1" alt="" '
            'style="display:none;width:1px;height:1px;opacity:0;border:0;" />'
            if tracking_url else ""
        )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07);">
<tr><td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 36px;">
<h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">TrainerSync</h1>
<p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">AI-Powered Trainer Matching Platform</p>
</td></tr>
<tr><td style="padding:32px 36px;color:#1e293b;font-size:15px;line-height:1.8;">{html_body}</td></tr>
<tr><td style="background:#f1f5f9;padding:20px 36px;border-top:1px solid #e2e8f0;">
<p style="margin:0;color:#94a3b8;font-size:12px;">{from_name} &bull; {from_email}</p>
</td></tr>
</table></td></tr></table>
{tracking_pixel}
</body></html>"""
        msg_obj.attach(MIMEText(html, "html"))

        try:
            ssl_port = 465 if smtp_port == 587 else smtp_port
            with smtplib.SMTP_SSL(smtp_host, ssl_port, timeout=15) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, to, msg_obj.as_string())
        except smtplib.SMTPAuthenticationError:
            raise
        except Exception:
            starttls_port = smtp_port if smtp_port != 465 else 587
            with smtplib.SMTP(smtp_host, starttls_port, timeout=15) as server:
                server.ehlo(); server.starttls()
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, to, msg_obj.as_string())

        logger.info("Email sent to %s", to)
        _append_sent_copy(msg_obj, smtp_config)
        return True, ""

    except smtplib.SMTPAuthenticationError:
        if can_use_gmail_oauth:
            logger.warning("SMTP authentication failed for Gmail; falling back to Gmail OAuth")
            return send_gmail_oauth_message(to, subject, body, from_name, tracking_url)
        err = "Gmail authentication failed - check GMAIL_USER and GMAIL_PASS"
        logger.error("Email error: %s", err)
        return False, err
    except Exception as e:
        logger.exception("Email send failed to %s", to)
        return False, str(e)


async def send_email_async(to: str, subject: str, body: str, smtp_config: Dict[str, Any] = None, tracking_url: str = "") -> tuple:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_email, to, subject, body, smtp_config, tracking_url)


async def send_bulk_emails(payloads: List[Dict], smtp_config: Dict[str, Any] = None) -> List[Dict]:
    results = []
    for p in payloads:
        success, error = await send_email_async(p["to"], p["subject"], p["body"], smtp_config, p.get("tracking_url", ""))
        results.append({
            **p,
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": utc_now().isoformat() if success else None,
        })
        if success:
            await asyncio.sleep(1.5)
    return results


def compose_interview_email(trainer_name: str, technology: str, req_id: str,
                             interview_date: str = "", interview_link: str = "") -> str:
    link = interview_link or f"https://calendly.com/trainersync/{req_id}"
    date_line = f"\n📅 Scheduled: {interview_date}\n" if interview_date else ""
    return f"""Dear {trainer_name},

Thank you for your interest in the {technology} training opportunity!

We are pleased to confirm your interview/discussion session.
{date_line}
Interview Details:
- Technology: {technology}
- Reference ID: {req_id}
- Duration: 30 minutes
- Mode: Video Call (Google Meet / Zoom)
- Book/Join: {link}

Please confirm your availability by replying to this email.

We look forward to speaking with you!

Warm regards,
{get_from_name()}
{get_from_email()}
"""


def compose_retry_email(trainer_name: str, technology: str, req_id: str) -> str:
    return f"""Dear {trainer_name},

I hope you're doing well!

I wanted to follow up on my earlier message regarding a {technology} training opportunity.

We remain very interested in your profile. Could you please let us know:
✅ Are you available for a quick call this week?
✅ What is your availability for training engagements?

Book a slot: https://calendly.com/trainersync/{req_id}

Warm regards,
{get_from_name()}
{get_from_email()}
"""


def check_email_replies(
    since_days: int = 7,
    max_messages: int = 50,
    from_emails: List[str] = None,
    gmail_user: str = "",
    gmail_pass: str = "",
    imap_host: str = "",
    imap_port: int = 993,
) -> List[Dict[str, Any]]:
    replies = []
    mail = None
    try:
        gmail_user = gmail_user or settings.gmail_user
        gmail_pass = (gmail_pass or get_gmail_password()).replace(" ", "")
        if not gmail_user or not gmail_pass:
            return []

        mail = imaplib.IMAP4_SSL(imap_host or "imap.gmail.com", int(imap_port or 993), timeout=20)
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")

        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        ids = []
        seen_ids = set()
        targeted = [
            str(item or "").strip()
            for item in (from_emails or [])
            if str(item or "").strip() and "@" in str(item)
        ]
        for sender in targeted[:100]:
            _, msg_ids = mail.search(None, f'(SINCE {since_date} FROM "{sender}")')
            for msg_id in (msg_ids[0].split() if msg_ids and msg_ids[0] else []):
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    ids.append(msg_id)

        if not ids and not targeted:
            _, msg_ids = mail.search(None, f'(SINCE {since_date})')
            ids = msg_ids[0].split() if msg_ids and msg_ids[0] else []
        ids = ids[-max_messages:]

        for msg_id in ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            from_addr = msg.get("From", "")
            from_email = parseaddr(from_addr)[1] or from_addr.strip()
            subject   = decode_mime_header(msg.get("Subject", ""))
            received_at = utc_now()
            try:
                date_header = msg.get("Date", "")
                if date_header:
                    parsed_date = parsedate_to_datetime(date_header)
                    if parsed_date:
                        if parsed_date.tzinfo is not None:
                            parsed_date = parsed_date.astimezone().replace(tzinfo=None)
                        received_at = parsed_date
            except Exception:
                received_at = utc_now()
            message_id_header = msg.get("Message-ID", "") or msg.get("Message-Id", "")
            in_reply_to = msg.get("In-Reply-To", "")
            references = msg.get("References", "")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            body_lower = body.lower()
            is_pos = any(s in body_lower for s in POSITIVE_SIGNALS)
            is_neg = any(s in body_lower for s in NEGATIVE_SIGNALS)

            replies.append({
                "msg_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                "message_id_header": message_id_header,
                "in_reply_to": in_reply_to,
                "references": references,
                "from_email": from_email,
                "from_raw": from_addr,
                "subject": subject,
                "body": body[:2000],
                "sentiment": "positive" if is_pos else ("negative" if is_neg else "neutral"),
                "action": "mark_interested" if is_pos else ("mark_declined" if is_neg else "requires_review"),
                "received_at": received_at.isoformat(),
            })

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


def mark_emails_seen(msg_ids: List[str]) -> None:
    if not msg_ids:
        return
    mail = None
    try:
        gmail_user = settings.gmail_user
        gmail_pass = get_gmail_password()
        if not gmail_user or not gmail_pass:
            return
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=20)
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")
        for msg_id in msg_ids:
            if str(msg_id).isdigit():
                mail.store(str(msg_id), "+FLAGS", "\\Seen")
    except Exception:
        logger.exception("IMAP mark seen failed")
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


def compose_shortlist_first_email(trainer_name: str, domain: str, duration: str,
                                   mode: str, participants: str) -> str:
    detail_lines = [f"* Domain/Technology: {domain}"]
    if duration:
        detail_lines.append(f"* Duration: {duration}")
    if mode:
        detail_lines.append(f"* Mode: {mode}")
    if participants:
        detail_lines.append(f"* Participants: {participants}")
    detail_text = "\n".join(detail_lines)
    missing_details_note = ""
    if not duration or not participants:
        missing_details_note = (
            "\n\nAt this stage, we are checking your interest and availability first. "
            "Once you confirm, we will share the confirmed duration, schedule, participants, "
            "and other requirement details as they are finalized."
        )

    return f"""Dear {trainer_name or 'Trainer'},

We have received a training requirement for {domain} and are looking for a trainer with relevant experience.

Training Details:

{detail_text}{missing_details_note}

Please let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.

Regards,
{get_from_name()}
{get_from_email()}"""


def compose_toc_request_email(trainer_name: str) -> str:
    return f"""Dear {trainer_name or 'Trainer'},

Congratulations on clearing the discussion round.

Kindly share the Table of Contents (ToC) / Course Agenda for the training so we can proceed further with the client.

Regards,
{get_from_name()}
{get_from_email()}"""
