"""Read-only timing analysis for the configured Hostinger mailbox."""
from collections import Counter, defaultdict
from datetime import datetime
from email import message_from_bytes
from email.utils import parsedate_to_datetime
import imaplib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env():
    values = {}
    for line in (ROOT / "mailautomation" / "microservices" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def key(subject):
    return re.sub(r"\s+", " ", re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", subject or "", flags=re.I)).strip().lower()


def read_headers(mail, folder):
    ok, _ = mail.select(folder, readonly=True)
    if ok != "OK":
        raise RuntimeError(f"Cannot open {folder}")
    ok, data = mail.search(None, "ALL")
    ids = (data[0] if ok == "OK" and data else b"").split()
    out = []
    for index in range(0, len(ids), 100):
        ok, results = mail.fetch(b",".join(ids[index:index + 100]), "(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT)])")
        if ok != "OK":
            continue
        for item in results:
            if not isinstance(item, tuple):
                continue
            msg = message_from_bytes(item[1])
            try:
                when = parsedate_to_datetime(msg.get("Date"))
                if when.tzinfo is None:
                    continue
                out.append((key(msg.get("Subject", "")), when))
            except (TypeError, ValueError, IndexError):
                pass
    return out


def main():
    cfg = load_env()
    mail = imaplib.IMAP4_SSL(cfg["STYLE_IMAP_HOST"], int(cfg.get("STYLE_IMAP_PORT", "993")), timeout=45)
    mail.login(cfg["STYLE_IMAP_USER"], cfg["STYLE_IMAP_PASSWORD"])
    try:
        inbox = read_headers(mail, "INBOX")
        sent = read_headers(mail, cfg.get("STYLE_IMAP_FOLDER") or "INBOX.Sent")
    finally:
        mail.logout()
    offset = 19800
    hours = Counter((item[1].timestamp() + offset) // 3600 % 24 for item in sent)
    inbound = defaultdict(list)
    for subject, when in inbox:
        if subject:
            inbound[subject].append(when)
    delays = []
    for subject, sent_when in sent:
        previous = [when for when in inbound.get(subject, []) if when <= sent_when]
        if previous:
            delay = (sent_when - max(previous)).total_seconds() / 60
            if 0 <= delay <= 60 * 24 * 30:
                delays.append(delay)
    hours_label = {f"{int(hour):02d}:00–{int(hour):02d}:59": count for hour, count in hours.most_common(8)}
    delays.sort()
    median = delays[len(delays) // 2] if delays else None
    print({"inbox_messages": len(inbox), "sent_messages": len(sent), "top_sent_hours_ist": hours_label,
           "subject_matched_replies": len(delays), "median_reply_delay_minutes": round(median, 1) if median is not None else None,
           "same_day_or_earlier_reply_percent": round(100 * sum(1 for value in delays if value <= 24 * 60) / len(delays), 1) if delays else None})


if __name__ == "__main__":
    main()
