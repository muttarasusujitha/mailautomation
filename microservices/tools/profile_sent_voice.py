"""Read-only Hostinger style profile for sent mail.

Prints and writes aggregates only: folder names, counts, greeting and sign-off
patterns, and redacted opening stems. Message bodies, addresses, phone numbers,
links, and credentials are not written.
"""

from __future__ import annotations

import email
import html
import imaplib
import json
import os
import re
from collections import Counter
from email import policy
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from statistics import median


OUT_PATH = Path("sent-voice-profile.json")
DEFAULT_HOST = "imap.hostinger.com"
SENT_CANDIDATES = (
    "INBOX.Sent",
    "Sent",
    "INBOX.Sent Items",
    "Sent Items",
    "INBOX.Sent Mail",
)


def _clean_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def _redact(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", "{link}", text or "", flags=re.I)
    cleaned = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "{email}", cleaned)
    cleaned = re.sub(r"\+?\d[\d\s().-]{7,}\d", "{phone}", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _body(message: email.message.EmailMessage) -> str:
    parts = message.walk() if message.is_multipart() else [message]
    plain = ""
    html_text = ""
    for part in parts:
        if part.get_content_maintype() != "text" or part.get_content_subtype() not in {"plain", "html"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if not isinstance(content, str):
            content = str(content)
        if part.get_content_subtype() == "html":
            html_text = html_text or re.sub(r"<[^>]+>", " ", html.unescape(content))
        else:
            plain = plain or content
    text = plain or html_text
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _fresh_text(text: str) -> str:
    """Drop quoted replies so the profile describes the new message, not the thread."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        lowered = stripped.lower()
        if stripped.startswith(">") or lowered.startswith("on ") and " wrote:" in lowered:
            break
        if lowered.startswith(("sent via hostinger", "-------- original message", "from:", "-----original message")):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in _fresh_text(text).splitlines() if line.strip()]


def _person_name(signature: list[str]) -> str:
    for line in signature:
        cleaned = re.sub(r"[,.]$", "", line).strip()
        if not cleaned or cleaned.startswith("{") or cleaned in {">", "---"}:
            continue
        lowered = cleaned.lower()
        if any(token in lowered for token in ("http", "www", "phone", "mobile", "regards", "thanks", "clahan", "calhan", "technologies")):
            continue
        if 1 <= len(cleaned.split()) <= 4 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,40}", cleaned):
            return cleaned
    return ""


def _greeting(lines: list[str]) -> str:
    if not lines:
        return "none"
    first = lines[0].lower()
    for label in ("dear ", "hi ", "hello ", "good morning", "good afternoon", "good evening", "hey "):
        if first.startswith(label):
            return label.strip()
    return "other"


def _signoff(lines: list[str]) -> tuple[str, list[str]]:
    markers = ("regards", "thanks", "thank you", "sincerely", "cheers", "best")
    for index in range(len(lines) - 1, -1, -1):
        lowered = lines[index].lower().rstrip(",.")
        if any(lowered == marker or lowered.startswith(f"{marker},") or lowered.startswith(f"{marker} ") for marker in markers):
            if lowered in {"best", "warm", "kind"}:
                continue
            return _redact(lines[index])[:80], [_redact(line)[:80] for line in lines[index + 1:index + 5]]
    return "none", []


def _opening_stem(lines: list[str]) -> str:
    body_lines = lines[1:] if lines and _greeting(lines) != "other" and _greeting(lines) != "none" else lines
    # Drop a greeting line even when classified as other if it is a single short line ending with a comma.
    if body_lines and body_lines[0].endswith(",") and len(body_lines[0].split()) <= 6:
        body_lines = body_lines[1:]
    text = _redact(" ".join(body_lines[:2]))
    words = text.split()[:8]
    return " ".join(words)


def _summary(records: list[dict]) -> dict:
    if not records:
        return {"count": 0}
    lengths = [item["words"] for item in records if item["words"] > 0]
    greetings = Counter(item["greeting"] for item in records)
    signoffs = Counter(item["signoff"] for item in records)
    stems = Counter(item["stem"] for item in records if item["stem"])
    signature_lines = Counter(line for item in records for line in item["signature"] if line and line != "{email}")
    kindly = sum(1 for item in records if item["kindly"])
    please = sum(1 for item in records if item["please"])
    thanks = sum(1 for item in records if item["thanks"])
    bullets = sum(1 for item in records if item["bullets"])
    return {
        "count": len(records),
        "median_words": int(median(lengths)) if lengths else 0,
        "greetings": dict(greetings.most_common(12)),
        "signoffs": dict(signoffs.most_common(12)),
        "signature_lines": dict(signature_lines.most_common(12)),
        "opening_stems": dict(stems.most_common(20)),
        "share_kindly": round(kindly / len(records), 3),
        "share_please": round(please / len(records), 3),
        "share_thanks": round(thanks / len(records), 3),
        "share_bullets": round(bullets / len(records), 3),
    }


def _read_folder(mail: imaplib.IMAP4_SSL, folder: str) -> list[dict]:
    status, _ = mail.select(f'"{folder}"' if " " in folder else folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Could not open folder {folder}")
    status, data = mail.search(None, "ALL")
    if status != "OK":
        raise RuntimeError(f"Could not list folder {folder}")
    ids = (data[0] if data else b"").split()
    records: list[dict] = []
    for batch_start in range(0, len(ids), 80):
        batch = ids[batch_start:batch_start + 80]
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
            body = _body(message)
            lines = _lines(body)
            from_name = parseaddr(_clean_header(message.get("From", "")))[0]
            signoff, signature = _signoff(lines)
            fresh = _fresh_text(body)
            lowered = fresh.lower()
            author = _person_name(signature) or _redact(from_name)[:60]
            records.append({
                "words": len(fresh.split()),
                "greeting": _greeting(lines),
                "signoff": signoff,
                "signature": signature,
                "stem": _opening_stem(lines),
                "murali": "murali" in author.lower(),
                "author": author,
                "from_name": _redact(from_name)[:60],
                "kindly": "kindly" in lowered,
                "please": "please" in lowered,
                "thanks": "thank" in lowered,
                "bullets": bool(re.search(r"(?m)^(?:\*|-|•|\d+[.)])\s+", fresh)),
            })
        print(json.dumps({
            "progress": folder,
            "reviewed": min(batch_start + len(batch), len(ids)),
            "total": len(ids),
        }), flush=True)
    return records


def _folders(mail: imaplib.IMAP4_SSL) -> list[str]:
    status, data = mail.list()
    names: list[str] = []
    if status != "OK":
        return names
    for raw in data or []:
        if not isinstance(raw, bytes):
            continue
        match = re.search(rb'"([^"]+)"\s*$', raw) or re.search(rb"\s([^\s]+)$", raw)
        if match:
            names.append(match.group(1).decode("utf-8", "replace"))
    return names


def _write(payload: dict) -> None:
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT_PATH), "ok": payload.get("ok", False)}), flush=True)


def main() -> int:
    user = os.environ.get("STYLE_IMAP_USER", "").strip()
    password = os.environ.get("STYLE_IMAP_PASSWORD", "").strip()
    host = os.environ.get("STYLE_IMAP_HOST", "").strip() or DEFAULT_HOST
    port = int(os.environ.get("STYLE_IMAP_PORT", "").strip() or "993")
    preferred = os.environ.get("STYLE_IMAP_FOLDER", "").strip()
    if not user or not password:
        _write({"ok": False, "error": "missing_credentials"})
        return 1
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=60)
        mail.login(user, password)
    except Exception:
        _write({"ok": False, "error": "login_failed", "host": host, "port": port})
        return 1
    try:
        folders = _folders(mail)
        sent_name = preferred or next((name for name in SENT_CANDIDATES if name in folders), "")
        if not sent_name:
            sent_name = next((name for name in folders if "sent" in name.lower()), "")
        inbox_name = "INBOX" if "INBOX" in folders else next((name for name in folders if name.upper() == "INBOX"), "")
        sent = _read_folder(mail, sent_name) if sent_name else []
        inbox = _read_folder(mail, inbox_name) if inbox_name else []
    finally:
        try:
            mail.logout()
        except Exception:
            pass
    murali_sent = [item for item in sent if "murali" in f"{item['author']} {item['from_name']}".lower()]
    murali_inbox = [item for item in inbox if "murali" in f"{item['author']} {item['from_name']}".lower()]
    short_sent = [item for item in sent if 0 < item["words"] <= 80]
    authors = Counter(item["author"] for item in sent if item["author"])
    inbox_from = Counter(item["from_name"] for item in inbox if item["from_name"])
    author_profiles = {
        name: _summary([item for item in sent if item["author"] == name])
        for name, _count in authors.most_common(4)
    }
    payload = {
        "ok": True,
        "folders": folders,
        "sent_folder": sent_name,
        "inbox_folder": inbox_name,
        "inbox_count": len(inbox),
        "inbox_from_names": dict(inbox_from.most_common(15)),
        "sent": _summary(sent),
        "short_sent": _summary(short_sent),
        "murali_sent": _summary(murali_sent),
        "murali_inbox": _summary(murali_inbox),
        "authors": dict(authors.most_common(8)),
        "author_profiles": author_profiles,
    }
    _write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
