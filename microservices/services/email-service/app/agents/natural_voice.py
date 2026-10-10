"""One voice choice for templates and drafted replies.

Annapurna U writes the coordination mail: Hi, a short thanks, and
"Thanks, Annapurna U." Murali Mohan M writes the short finance notes:
Hello, please find or please share, and "Thanks and Regards."
"""

import re


ANNAPURNA = "annapurna"
MURALI = "murali"

SIGNATURES = {
    ANNAPURNA: "Thanks,\nAnnapurna U.\nClahan Technologies",
    MURALI: "Thanks and Regards,\nMurali Mohan M\nClahan Technologies",
}
GREETINGS = {ANNAPURNA: "Hi", MURALI: "Hello"}
NOTES = {
    ANNAPURNA: (
        "Write as Annapurna U. Open with Hi <name>, or Hi, when no reliable name is available. "
        "When thanking someone for a requirement or details, begin that sentence with Greetings of the day. "
        "Use Thanks for reaching out, Thanks for sharing, and Please share. "
        "Close with Thanks, then Annapurna U., then Clahan Technologies."
    ),
    MURALI: (
        "Write as Murali Mohan M. Open with Hello <name>, or Hello, when no reliable name is available. "
        "Keep it to one or two direct sentences. Use Please find, Please share, or Thanks for. "
        "Close with Thanks and Regards, then Murali Mohan M, then Clahan Technologies."
    ),
}
_MURALI_MARKERS = (
    "invoice", "payment", "finance", "legal", "nda",
    "purchase order", "purchase_order", "client_po", "po_received",
)
_GENERIC_NAMES = {"team", "client", "trainer", "sender", "there", "candidate", "vendor", "student"}
_SIGNOFF_LINE = re.compile(
    r"^(?:thanks(?:\s+(?:and|&))?\s+)?(?:(?:best|kind|warm)\s+)?regards,?$"
    r"|^thanks,?$"
    r"|^thank you,?$"
    r"|^sincerely,?$",
    re.IGNORECASE,
)
_IDENTITY_LINE = re.compile(
    r"^(?:recruitment team|clahan technologies\.?|calhan technologies\.?|"
    r"murali mohan m|murali mohan|annapurna u\.?,?|annapurna\.?,?)$",
    re.IGNORECASE,
)
_GREETING_LINE = re.compile(
    r"^(?:hi|hello|dear)\b\s*([^,!\n]{0,70})?[,!]?\s*$",
    re.IGNORECASE,
)
_PHRASES = (
    ("Thank you for sharing", "Thanks for sharing"),
    ("Thank you for your email", "Thanks for the email"),
    ("Thank you for your response", "Thanks for your response"),
    ("Thank you for the update", "Thanks for the update"),
    ("Thank you for reaching out", "Thanks for reaching out"),
    ("Thank you for your message", "Thanks for your message"),
    ("Thank you for confirming", "Thanks for confirming"),
    ("Thank you for following up", "Thanks for following up"),
    ("Thank you for checking", "Thanks for checking"),
    ("Thank you for requesting", "Thanks for requesting"),
    ("To help us refine the shortlist, please share:", "Please share:"),
    ("To proceed further, kindly share", "Please share"),
    ("To proceed further, please share", "Please share"),
    ("To proceed further, kindly", "Please"),
    ("To proceed further, please", "Please"),
    ("To proceed further for", "For"),
    ("We will revert with a concrete status shortly.", "We will send the next update."),
    ("We will revert with the next step shortly.", "We will send the next step."),
    ("We will revert with the available approach shortly.", "We will send what we can offer."),
    ("We will revert with the confirmation shortly.", "We will confirm this."),
    ("We will revert with an updated option or recommendation shortly.", "We will send an updated option."),
    ("We will revert with the relevant confirmation shortly.", "We will confirm the payment terms."),
    ("We will revert with the feasible option shortly.", "We will send a workable option."),
    ("and revert shortly", "and write back"),
    ("revert shortly", "write back"),
    ("We will revert", "We will write back"),
    ("route it to the concerned team", "check it with the team"),
    ("route it to the appropriate team", "check it with the team"),
    ("the concerned team", "the team"),
    (" as applicable", ""),
    (" accordingly", ""),
)


def choose_voice(*hints: object) -> str:
    """Finance and billing notes use Murali. Coordination mail uses Annapurna."""
    blob = " ".join(str(hint or "") for hint in hints).lower()
    if any(marker in blob for marker in _MURALI_MARKERS):
        return MURALI
    return ANNAPURNA


def voice_for_situation(*situation: object, subject: str = "") -> str:
    """Use the classified situation. The subject is only a fallback."""
    if any(str(item or "").strip() for item in situation):
        return choose_voice(*situation)
    return choose_voice(subject)


def signature_for(voice: str = ANNAPURNA) -> str:
    return SIGNATURES.get(voice, SIGNATURES[ANNAPURNA])


def greeting_line(name: str = "", voice: str = ANNAPURNA) -> str:
    spoken = re.sub(r"\s+", " ", str(name or "")).strip(" ,")
    hello = GREETINGS.get(voice, GREETINGS[ANNAPURNA])
    if not spoken or spoken.lower() in _GENERIC_NAMES:
        return f"{hello},"
    return f"{hello} {spoken},"


def writing_note(voice: str = ANNAPURNA) -> str:
    return NOTES.get(voice, NOTES[ANNAPURNA])


def signature_keeping_extras(tail: str, voice: str = ANNAPURNA) -> str:
    extras: list[str] = []
    for line in str(tail or "").splitlines():
        stripped = line.strip()
        if not stripped or _SIGNOFF_LINE.match(stripped) or _IDENTITY_LINE.match(stripped):
            continue
        extras.append(line.rstrip())
    signature = signature_for(voice)
    if not extras:
        return signature
    return signature + "\n" + "\n".join(extras)


def apply_voice(body: str, voice: str = ANNAPURNA) -> str:
    text = str(body or "").strip()
    if not text:
        return ""
    voice = voice if voice in SIGNATURES else ANNAPURNA
    for old, new in _PHRASES:
        text = text.replace(old, new)
    text = re.sub(r" +([,.])", r"\1", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\bKindly\b", "Please", text)
    text = re.sub(r"\bkindly\b", "please", text)
    lines = text.splitlines()
    if lines:
        match = _GREETING_LINE.match(lines[0].strip())
        if match:
            lines[0] = greeting_line(match.group(1) or "", voice)
        elif re.match(r"^dear\s+team\s*$", lines[0].strip(), re.IGNORECASE):
            lines[0] = greeting_line("", voice)
    if voice == ANNAPURNA:
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or _GREETING_LINE.match(stripped):
                continue
            if stripped.startswith("Thanks for sharing") and not stripped.lower().startswith("greetings of the day"):
                lines[index] = f"Greetings of the day! {stripped}"
            break
    sign_at = next(
        (index for index in range(len(lines) - 1, -1, -1) if _SIGNOFF_LINE.match(lines[index].strip())),
        None,
    )
    if sign_at is not None:
        lines = lines[:sign_at] + signature_keeping_extras("\n".join(lines[sign_at:]), voice).splitlines()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()
