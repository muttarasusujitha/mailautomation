"""Reply envelope taken from Murali Mohan M's Hostinger mail.

His messages open with Hello, stay short, and close with
"Thanks and Regards," followed by his name. This module only adjusts
greeting, stock phrasing, and the signature. It leaves facts in place.
"""

import re


SIGNATURE = "Thanks and Regards,\nMurali Mohan M\nClahan Technologies"

_SIGNOFF_LINE = re.compile(
    r"^(?:thanks(?:\s+(?:and|&))?\s+)?(?:(?:best|kind|warm)\s+)?regards,?$"
    r"|^thanks,?$"
    r"|^thank you,?$"
    r"|^sincerely,?$",
    re.IGNORECASE,
)
_IDENTITY_LINE = re.compile(
    r"^(?:recruitment team|clahan technologies\.?|calhan technologies\.?|"
    r"murali mohan m|murali mohan)$",
    re.IGNORECASE,
)
_GREETING_LINE = re.compile(
    r"^(?:hi|hello|dear)\b\s*([^,!\n]{0,70})?[,!]?\s*$",
    re.IGNORECASE,
)


def hello_line(name: str = "") -> str:
    spoken = re.sub(r"\s+", " ", str(name or "")).strip(" ,")
    if not spoken or spoken.lower() in {"team", "client", "trainer", "sender", "there"}:
        return "Hello,"
    return f"Hello {spoken},"


def signature_keeping_extras(tail: str) -> str:
    extras: list[str] = []
    for line in str(tail or "").splitlines():
        stripped = line.strip()
        if not stripped or _SIGNOFF_LINE.match(stripped) or _IDENTITY_LINE.match(stripped):
            continue
        extras.append(line.rstrip())
    if not extras:
        return SIGNATURE
    return SIGNATURE + "\n" + "\n".join(extras)


def apply_murali_voice(body: str) -> str:
    text = str(body or "").strip()
    if not text:
        return ""
    replacements = (
        ("Thank you for sharing", "Thanks for sharing"),
        ("Thank you for your email", "Thanks for the email"),
        ("Thank you for your response", "Thanks for your response"),
        ("Thank you for the update", "Thanks for the update"),
        ("To help us refine the shortlist, please share:", "Please share:"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    lines = text.splitlines()
    if lines:
        match = _GREETING_LINE.match(lines[0].strip())
        if match:
            lines[0] = hello_line(match.group(1) or "")
        elif re.match(r"^dear\s+team\s*$", lines[0].strip(), re.IGNORECASE):
            lines[0] = "Hello,"
    sign_at = next(
        (index for index in range(len(lines) - 1, -1, -1) if _SIGNOFF_LINE.match(lines[index].strip())),
        None,
    )
    if sign_at is not None:
        lines = lines[:sign_at] + signature_keeping_extras("\n".join(lines[sign_at:])).splitlines()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()
