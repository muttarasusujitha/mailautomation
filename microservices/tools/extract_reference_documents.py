"""Read-only IMAP extraction of representative TOC and lab-cost attachments."""
from __future__ import annotations

import email
import imaplib
import re
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = Path(__file__).resolve().parents[1] / ".env"
OUT = ROOT / "tmp" / "reference_documents"
LIMITS = {"toc": 6, "lab_cost": 6}


def config() -> dict[str, str]:
    result = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "attachment"


def category(subject: str, filename: str) -> str | None:
    text = f"{subject} {filename}".lower()
    if any(term in text for term in ("lab cost", "labcost", "lab quote", "lab pricing")):
        return "lab_cost"
    if any(term in text for term in ("toc", "table of contents", "course outline", "agenda")):
        return "toc"
    return None


def main() -> None:
    cfg = config()
    OUT.mkdir(parents=True, exist_ok=True)
    mail = imaplib.IMAP4_SSL(cfg["STYLE_IMAP_HOST"], int(cfg.get("STYLE_IMAP_PORT", "993")), timeout=45)
    mail.login(cfg["STYLE_IMAP_USER"], cfg["STYLE_IMAP_PASSWORD"])
    try:
        mail.select(cfg.get("STYLE_IMAP_FOLDER") or "INBOX.Sent", readonly=True)
        candidate_ids: set[bytes] = set()
        for term in ("toc", "table of contents", "course outline", "agenda", "lab cost", "lab pricing", "lab access"):
            for field in ("SUBJECT", "BODY"):
                status, data = mail.search(None, field, f'"{term}"')
                if status == "OK" and data:
                    candidate_ids.update(data[0].split())
        ids = sorted(candidate_ids, key=lambda value: int(value))
        print({"candidate_messages": len(ids), "folder": "Sent"}, flush=True)
        saved = {key: 0 for key in LIMITS}
        for reviewed, message_id in enumerate(reversed(ids), 1):
            if all(saved[key] >= limit for key, limit in LIMITS.items()):
                break
            status, payload = mail.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1], policy=policy.default)
            subject = str(msg.get("Subject", ""))
            for part in msg.walk():
                filename = part.get_filename() or ""
                if not filename or part.get_content_disposition() != "attachment":
                    continue
                kind = category(subject, filename)
                if not kind or saved[kind] >= LIMITS[kind]:
                    continue
                raw = part.get_payload(decode=True)
                if not raw:
                    continue
                suffix = Path(filename).suffix.lower()
                if suffix not in {".pdf", ".xlsx", ".xls", ".docx", ".doc"}:
                    continue
                target = OUT / kind / f"{saved[kind] + 1:02d}_{safe_name(filename)}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                saved[kind] += 1
            if reviewed % 50 == 0:
                print({"reviewed": reviewed, "total": len(ids), "saved": saved}, flush=True)
        print({"saved": saved, "folder": "Sent", "destination": str(OUT)})
    finally:
        mail.logout()


if __name__ == "__main__":
    main()
