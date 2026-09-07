"""Build a local, read-only Hostinger mailbox documentation report."""
from __future__ import annotations
import email, html, imaplib, re
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = Path(__file__).resolve().parents[1] / ".env"
OUT = ROOT / "outputs" / "clahan_mail_documentation.md"

def cfg():
    return {k.strip(): v.strip() for k,v in (x.split("=",1) for x in ENV.read_text(encoding="utf-8").splitlines() if "=" in x and not x.lstrip().startswith("#"))}
def body(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_type() not in ("text/plain", "text/html"): continue
        try: s = p.get_content()
        except Exception: s = (p.get_payload(decode=True) or b"").decode("utf-8","replace")
        if p.get_content_type() == "text/html": s = re.sub(r"<[^>]+>", " ", html.unescape(s))
        return re.sub(r"\s+", " ", s).strip()
    return ""
def kind(subject, text, sender):
    s = f"{subject} {text} {sender}".lower()
    if any(x in s for x in ("trainer", "resume", "curriculum vitae", "availability", "slot", "to c", "table of contents", "course outline")): return "Trainer"
    if any(x in s for x in ("training requirement", "corporate", "purchase order", "budget", "quotation", "company", "client")): return "Client"
    return "Unclassified"
def clean(s): return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
def main():
    c = cfg(); OUT.parent.mkdir(parents=True, exist_ok=True)
    m = imaplib.IMAP4_SSL(c["STYLE_IMAP_HOST"], int(c.get("STYLE_IMAP_PORT","993")), timeout=90); m.login(c["STYLE_IMAP_USER"], c["STYLE_IMAP_PASSWORD"])
    rows=[]
    try:
        for folder in ("INBOX", c.get("STYLE_IMAP_FOLDER") or "INBOX.Sent"):
            if m.select(folder, readonly=True)[0] != "OK": continue
            ids=(m.search(None,"ALL")[1][0] or b"").split()
            for start in range(0,len(ids),250):
                ok,data=m.fetch(b",".join(ids[start:start+250]),"(BODY.PEEK[]<0.12000>)")
                if ok != "OK": continue
                for item in data:
                    if not isinstance(item,tuple): continue
                    try: msg=email.message_from_bytes(item[1],policy=policy.default)
                    except Exception: continue
                    subj=str(msg.get("Subject", "(no subject)")); text=body(msg)
                    rows.append((folder, str(msg.get("Date", "")), str(msg.get("From", "")), subj, text))
    finally: m.logout()
    rows.sort(key=lambda r:r[1], reverse=True)
    with OUT.open("w",encoding="utf-8") as f:
        f.write("# Clahan Technologies Mail Documentation\n\n")
        f.write(f"Read-only export of {len(rows)} Hostinger messages. Replies are drafts only.\n\n")
        for group in ("Client","Trainer","Unclassified"):
            subset=[r for r in rows if kind(r[3],r[4],r[2])==group]
            f.write(f"## {group} messages ({len(subset)})\n\n")
            for i,(folder,date,sender,subj,text) in enumerate(subset,1):
                snippet=clean(text[:1200]) or "(no readable text)"
                f.write(f"### {i}. {clean(subj)}\n\n- Folder: `{folder}`\n- Date: {clean(date)}\n- From: {clean(sender)}\n- Message: {snippet}\n- Clahan reply draft: Review the request above and respond with the confirmed requirement, next step, owner, and expected timeline.\n\n")
    print(f"Wrote {len(rows)} messages to {OUT}")
if __name__ == "__main__": main()
