"""
Email Automation Agent — Gmail SMTP + IMAP reply monitoring
Fixed: uses correct env key GMAIL_APP_PASSWORD or GMAIL_PASS
"""

import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any
from datetime import datetime, timedelta
import asyncio
import os

from config import get_settings

settings = get_settings()

POSITIVE_SIGNALS = ['yes', 'available', 'interested', 'confirm', 'accept',
                    'happy to', 'sure', 'okay', 'ok', 'look forward', 'schedule', 'agree']
NEGATIVE_SIGNALS = ['no', 'not available', 'not interested', 'decline',
                    'unable', 'cannot', 'busy', 'engaged', 'withdraw']


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


def send_email(to: str, subject: str, body: str) -> tuple:
    gmail_user = settings.gmail_user
    gmail_pass = get_gmail_password()
    from_name  = get_from_name()
    from_email = get_from_email()

    if not gmail_user or not gmail_pass:
        err = "Gmail credentials not set in .env (GMAIL_USER + GMAIL_PASS)"
        print(f"❌ {err}")
        return False, err

    try:
        msg_obj = MIMEMultipart("alternative")
        msg_obj["Subject"]  = subject
        msg_obj["From"]     = f"{from_name} <{from_email}>"
        msg_obj["To"]       = to
        msg_obj["Reply-To"] = from_email

        msg_obj.attach(MIMEText(body, "plain"))

        html_body = body.replace('\n', '<br>')
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
</body></html>"""
        msg_obj.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, to, msg_obj.as_string())
        except Exception:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
                server.ehlo(); server.starttls()
                server.login(gmail_user, gmail_pass)
                server.sendmail(from_email, to, msg_obj.as_string())

        print(f"✅ Email sent to {to}")
        return True, ""

    except smtplib.SMTPAuthenticationError:
        err = "Gmail authentication failed — check GMAIL_USER and GMAIL_PASS"
        print(f"❌ {err}")
        return False, err
    except Exception as e:
        print(f"❌ Email send failed to {to}: {e}")
        return False, str(e)


async def send_email_async(to: str, subject: str, body: str) -> tuple:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_email, to, subject, body)


async def send_bulk_emails(payloads: List[Dict]) -> List[Dict]:
    results = []
    for p in payloads:
        success, error = await send_email_async(p["to"], p["subject"], p["body"])
        results.append({
            **p,
            "status": "sent" if success else "failed",
            "error_message": error if not success else "",
            "sent_at": datetime.utcnow().isoformat() if success else None,
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


def check_email_replies(since_days: int = 7) -> List[Dict[str, Any]]:
    replies = []
    try:
        gmail_user = settings.gmail_user
        gmail_pass = get_gmail_password()
        if not gmail_user or not gmail_pass:
            return []

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")

        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        _, msg_ids = mail.search(None, f'(SINCE {since_date} UNSEEN)')

        for msg_id in (msg_ids[0].split() if msg_ids[0] else []):
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            from_addr = msg.get("From", "")
            subject   = msg.get("Subject", "")
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
                "from_email": from_addr, "subject": subject, "body": body[:500],
                "sentiment": "positive" if is_pos else ("negative" if is_neg else "neutral"),
                "action": "mark_interested" if is_pos else ("mark_declined" if is_neg else "requires_review"),
                "received_at": datetime.utcnow().isoformat(),
            })
            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close(); mail.logout()
    except Exception as e:
        print(f"❌ IMAP check failed: {e}")
    return replies


def compose_shortlist_first_email(trainer_name: str, domain: str, duration: str,
                                   mode: str, participants: str) -> str:
    return f"""Dear Sir/Madam,

We have received a training requirement for {domain} and are looking for a trainer with relevant experience.

Training Details:

* Domain/Technology: {domain}
* Duration: {duration or '[Hours/Days]'}
* Mode: {mode or '[Online/Offline]'}
* Participants: {participants or '[Number]'}

Please let us know if you are interested and available for this requirement. Kindly share your updated trainer profile along with relevant experience.

Regards,
{get_from_name()}
{get_from_email()}"""


def compose_toc_request_email(trainer_name: str) -> str:
    return f"""Dear Sir/Madam,

Congratulations on clearing the discussion round.

Kindly share the Table of Contents (ToC) / Course Agenda for the training so we can proceed further with the client.

Regards,
{get_from_name()}
{get_from_email()}"""
