"""Read-only aggregate analysis of Hostinger Inbox and Sent mail.

No message bodies, addresses, credentials, or attachments are written to disk or
printed. The output contains only scenario and writing-style aggregates.
"""

from __future__ import annotations

import email
import html
import imaplib
import json
import re
from collections import Counter, defaultdict
from email import policy
from pathlib import Path
from statistics import median


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
FOLDERS = {"inbox": "INBOX", "sent": "INBOX.Sent"}
SCENARIOS = {
    "trainer_profiles": ("trainer profile", "resume", "curriculum vitae", "linkedin"),
    "toc_agenda": ("toc", "table of contents", "course outline", "day-wise", "agenda"),
    "labs": ("hands-on", "hands on", "lab plan", "lab access", "laboratory"),
    "commercials": ("commercial", "quotation", "quote", "pricing", "rate", "cost"),
    "availability": ("availability", "available", "slot", "schedule"),
    "follow_up": ("follow up", "follow-up", "reminder", "gentle reminder"),
    "meeting_interview": ("interview", "meeting", "discussion", "call"),
    "requirement": ("training requirement", "corporate trainer", "training program", "training programme"),
}


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _body(message: email.message.EmailMessage) -> str:
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_maintype() != "text" or part.get_content_subtype() not in {"plain", "html"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            content = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        if part.get_content_subtype() == "html":
            content = re.sub(r"<[^>]+>", " ", html.unescape(content))
        return re.sub(r"\s+", " ", content).strip()
    return ""


def _subject_key(subject: str) -> str:
    value = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", subject or "", flags=re.I)
    return re.sub(r"\s+", " ", value).strip().lower()[:160]


def _scenario_hits(text: str) -> set[str]:
    lower = text.lower()
    return {name for name, terms in SCENARIOS.items() if any(term in lower for term in terms)}


def _tone(text: str) -> tuple[str, str]:
    lower = text.lower()
    if lower.startswith("dear "):
        greeting = "Dear"
    elif lower.startswith("hi "):
        greeting = "Hi"
    elif lower.startswith("hello "):
        greeting = "Hello"
    else:
        greeting = "other"
    tail = lower[-500:]
    if "best regards" in tail:
        signoff = "Best Regards"
    elif "warm regards" in tail:
        signoff = "Warm Regards"
    elif "regards" in tail:
        signoff = "Regards"
    else:
        signoff = "other"
    return greeting, signoff


def _read_folder(mail: imaplib.IMAP4_SSL, folder: str) -> list[dict[str, object]]:
    status, _ = mail.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Could not open {folder}")
    status, data = mail.search(None, "ALL")
    if status != "OK":
        raise RuntimeError(f"Could not list {folder}")
    ids = (data[0] if data else b"").split()
    print(json.dumps({"progress": folder, "reviewed": 0, "total": len(ids)}), flush=True)
    records: list[dict[str, object]] = []
    for batch_start in range(0, len(ids), 100):
        batch = ids[batch_start:batch_start + 100]
        # Read only the first 20 KB of each MIME message. This includes normal
        # email text and headers while avoiding large binary attachments.
        status, result = mail.fetch(b",".join(batch), "(BODY.PEEK[]<0.20000>)")
        if status != "OK":
            continue
        for item in result:
            if not isinstance(item, tuple):
                continue
            try:
                message = email.message_from_bytes(item[1], policy=policy.default)
            except Exception:
                continue
            subject = str(message.get("Subject", ""))
            body = _body(message)
            combined = f"{subject} {body}"
            greeting, signoff = _tone(body)
            records.append({
                "subject": _subject_key(subject),
                "thread": str(message.get("In-Reply-To", "") or message.get("References", "")).strip(),
                "scenarios": _scenario_hits(combined),
                "words": len(body.split()),
                "greeting": greeting,
                "signoff": signoff,
            })
        print(json.dumps({"progress": folder, "reviewed": min(batch_start + len(batch), len(ids)), "total": len(ids)}), flush=True)
    return records


def main() -> None:
    cfg = _env()
    mail = imaplib.IMAP4_SSL(cfg["STYLE_IMAP_HOST"], int(cfg.get("STYLE_IMAP_PORT", "993")), timeout=45)
    mail.login(cfg["STYLE_IMAP_USER"], cfg["STYLE_IMAP_PASSWORD"])
    try:
        inbox = _read_folder(mail, FOLDERS["inbox"])
        sent = _read_folder(mail, cfg.get("STYLE_IMAP_FOLDER") or FOLDERS["sent"])
    finally:
        mail.logout()

    grouped_inbox: defaultdict[str, int] = defaultdict(int)
    for item in inbox:
        if item["subject"]:
            grouped_inbox[str(item["subject"])] += 1
    paired = sum(1 for item in sent if item["subject"] and str(item["subject"]) in grouped_inbox)
    scenario_counts = {side: Counter() for side in ("inbox", "sent")}
    greetings = Counter()
    signoffs = Counter()
    for side, items in (("inbox", inbox), ("sent", sent)):
        for item in items:
            scenario_counts[side].update(item["scenarios"])
            if side == "sent":
                greetings[str(item["greeting"])] += 1
                signoffs[str(item["signoff"])] += 1
    sent_lengths = [int(item["words"]) for item in sent if int(item["words"]) > 0]
    print(json.dumps({
        "analysis_complete": True,
        "inbox_reviewed": len(inbox),
        "sent_reviewed": len(sent),
        "subject_matched_sent_replies": paired,
        "scenario_counts": {side: dict(counter) for side, counter in scenario_counts.items()},
        "sent_style": {
            "median_words": int(median(sent_lengths)) if sent_lengths else 0,
            "greetings": dict(greetings),
            "signoffs": dict(signoffs),
        },
    }), flush=True)


if __name__ == "__main__":
    main()
