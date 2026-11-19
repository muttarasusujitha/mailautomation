"""Deterministic personalization engine for first client requirement replies.

The engine reads the client's latest message once, without any LLM call, and
builds a reply plan:

* batch type (confirmed or proposal), decided by the existing classifier;
* the items the client asked for, trainer first, then in the client's order;
* the details still missing (cloud platform, participant count, ...);
* conflicts inside the email (two start dates, lab days vs training days);
* the client's greeting style and the name they signed with.

The plan is used three ways:

1. ``render_plan_reply`` writes a complete, polite reply from the plan with
   templates. No LLM writes the reply text.
2. ``requirement_understanding`` can replace the rule-based reading with a
   verified LLM reading of the email (AI mode, one call).
3. ``check_reply`` verifies a reply against the plan before it is sent.

This module has no third-party dependencies so it can be tested in isolation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

SIGNATURE = "Best regards,\nAnnapurna U.\nClahan Technologies"

_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
)
_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b\.?(?:,?\s+(\d{{4}}))?",
    re.IGNORECASE,
)
_START_CONTEXT_RE = re.compile(r"(?:start|starting|commenc|begin|from)\w*[^.\n]{0,25}$", re.IGNORECASE)

_REQUEST_VERB_RE = re.compile(
    r"\b(?:please|kindly|share|send|provide|include|need|needs|require|required|"
    r"would like|want|looking for|proceed with|request|requesting)\b",
    re.IGNORECASE,
)
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*\u2022\u25aa\u25e6\u2023]|\d{1,2}[.)]|[a-hA-H][.)])\s*")
_LONE_MARKER_RE = re.compile(r"^\s*(?:[-*\u2022\u25aa\u25e6\u2023]|\d{1,2}[.)]|[a-hA-H][.)])\s*$")

_KIND_PATTERNS = (
    ("trainer", re.compile(r"\btrainers?\b|\bprofiles?\b|\bcvs?\b|\bresumes?\b", re.IGNORECASE)),
    ("availability", re.compile(
        r"\bavailability\b|\bearliest (?:possible )?start\b|\bschedule options\b|\bavailable dates\b",
        re.IGNORECASE,
    )),
    ("toc", re.compile(
        r"\btoc\b|table of contents|course outline|\boutline\b|syllabus|curriculum|\bagenda\b|course content",
        re.IGNORECASE,
    )),
    ("lab", re.compile(
        r"\blab[- ]?(?:cost|charges?|estimate|pricing|price|quote)s?\b"
        r"|\blab\b[^.\n]{0,30}\b(?:cost|charges?|estimate|pricing)\b"
        r"|\b(?:sandbox|lab|training) (?:\/ )?(?:training )?environment\b|\bsandbox\b",
        re.IGNORECASE,
    )),
    ("commercials", re.compile(
        r"\bcommercials?\b|\bquot(?:e|ation)s?\b|\bpricing\b|\bprices?\b|\brates?\b|\bcost(?:ing)?\b|\bbudget\b",
        re.IGNORECASE,
    )),
    ("proposal", re.compile(r"\bproposals?\b", re.IGNORECASE)),
)

_CLOUD_RE = re.compile(r"\b(?:aws|amazon web services|azure|gcp|google cloud)\b", re.IGNORECASE)
_PARTICIPANTS_RE = re.compile(
    r"\b\d+\s*(?:participants?|people|members|attendees|learners|employees|trainees|candidates|associates)\b"
    r"|\b(?:participants?|batch size|headcount|no\.? of (?:participants|attendees))\s*[:\-]?\s*(?:approx\.?\s*|around\s*|about\s*)?\d+"
    r"|\b(?:batch|group|team) of\s+\d+",
    re.IGNORECASE,
)
_MODE_RE = re.compile(r"\b(?:online|offline|onsite|on-site|virtual|classroom|hybrid|in-person)\b", re.IGNORECASE)
_TENTATIVE_RE = re.compile(
    r"to be (?:confirmed|decided|finali[sz]ed|discussed)|\btb[cd]\b|not (?:yet )?finali[sz]ed"
    r"|yet to be (?:confirmed|decided|finali[sz]ed)|still (?:to be|being) (?:confirmed|decided|finali[sz]ed)",
    re.IGNORECASE,
)
_TENTATIVE_FIELDS = (
    ("duration", re.compile(r"\bduration\b", re.IGNORECASE)),
    ("dates", re.compile(r"\bdates?\b|\btimeline\b|\bschedule\b", re.IGNORECASE)),
    ("delivery mode", re.compile(r"\b(?:delivery )?mode\b", re.IGNORECASE)),
    ("location", re.compile(r"\blocation\b|\bvenue\b", re.IGNORECASE)),
    ("budget", re.compile(r"\bbudget\b|\bcommercials?\b", re.IGNORECASE)),
    ("participant count", re.compile(r"\bparticipants?\b|\bheadcount\b|\bbatch size\b", re.IGNORECASE)),
)

_SIGNOFF_RE = re.compile(
    r"^(?:(?:best|kind|warm|with)\s+)?regards[,.!]?$|^thanks(?:\s+(?:and|&)\s+regards)?[,.!]?$"
    r"|^thank you[,.!]?$|^sincerely[,.!]?$|^cheers[,.!]?$",
    re.IGNORECASE,
)
_GENERIC_NAMES = {
    "client", "team", "hr", "admin", "regards", "thanks", "the", "training", "sir", "madam",
    "sender", "unknown", "none", "trainer", "there", "l&d", "ld", "procurement", "support", "info",
    "undefined", "null", "coordinator", "sales", "operations", "recruitment", "hello", "contact",
    "noreply", "no-reply", "mailer", "office", "accounts", "enquiry", "enquiries",
}

# A list item that describes what the trainer must have belongs in the
# trainer profile, not in the list of documents to send.
_TRAINER_DETAIL_RE = re.compile(
    r"\b(?:experience|experienced|expertise|exposure|certifications?|certified|background|"
    r"track record|trainings? delivered|delivery experience|proficien\w*|knowledge of|skills?)\b"
    r"(?![^.\n]*\b(?:details|exam|fees?|vouchers?|process|validity)\b)",
    re.IGNORECASE,
)
_CALL_RE = re.compile(
    r"\b(?:screening|technical|evaluation|interview|discussion|intro(?:duction|ductory)?)\s+(?:call|round|session|slots?)\b"
    r"|\bcall slots?\b|\binterview\b",
    re.IGNORECASE,
)
# Items the client asks us to recommend. We must not ask them back for these.
_RECOMMEND_FIELDS = (
    ("duration", re.compile(r"\bduration\b|\bno\.? of days\b|\bnumber of days\b|\bhours per day\b|\btraining hours\b"
                            r"|\bhours\s*/\s*days\b|\btotal hours\b", re.I)),
    ("dates", re.compile(r"\bstart date\b|\bschedule\b|\bdates?\b|\btimeline\b|\bwhen\b.{0,20}\bstart\b", re.I)),
    ("mode", re.compile(r"\bmode\b|\bdelivery (?:approach|format|method)\b|\bonline\s*/\s*(?:classroom|offline)\b", re.I)),
    ("lab_setup", re.compile(r"\blab\b.{0,30}\b(?:requirements?|setup|set-up|environment|access)\b"
                             r"|\bprerequisites?\b|\blicen[cs]\w*\b|\binfrastructure\b", re.I)),
)
_TRAINER_HEADER_RE = re.compile(
    r"\blooking for\b|\b(?:trainer|candidate|profile)\s+(?:requirements?|criteria|expectations)\b|\bmust[- ]have\b"
    r"|\bshould (?:have|be)\b|\bskills?\b|\bqualifications?\b|\bexpertise\b|\beligibility\b|\bexperience required\b",
    re.IGNORECASE,
)
_SCOPE_HEADER_RE = re.compile(
    r"\btopics?\b|\bmodules?\b|\bscope\b|\bsyllabus\b|\bagenda\b|\bcontents?\b|\bcover(?:ing|age|ed)?\b"
    r"|\bcurriculum\b|\boutline\b(?!.*\bshare\b)",
    re.IGNORECASE,
)
_NEUTRAL_HEADER_RE = re.compile(r"\bresponsibilit\w*\b|\bobjectives?\b|\boutcomes?\b|\babout\b|\bdetails\b", re.I)
_DELIVERABLE_NOUN_RE = re.compile(
    r"\b(?:plan|details|information|charges?|certificat\w*|materials?|approach|options|list|cost|fees?|"
    r"vouchers?|exams?|assessments?|quotes?|samples?|references?|case stud\w*|feedback|deck|brochure)\b",
    re.IGNORECASE,
)
_FACT_LINE_RE = re.compile(r"^[A-Za-z][\w /&().'-]{1,35}\s*[:\-\u2013]\s*\S")
_PLACEHOLDER_RE = re.compile(r"\((?:add|mention|specify)\b[^)]*\)|\bif required\)", re.IGNORECASE)
_URGENT_RE = re.compile(
    r"\burgent(?:ly)?\b|\basap\b|\bimmediate(?:ly)?\b|\bat the earliest\b|\bpriority\b|\bcritical\b"
    r"|\bearliest (?:response|possible)\b|\bon priority\b|\btime[- ]sensitive\b",
    re.IGNORECASE,
)
_END_CLIENT_RE = re.compile(
    r"\b(?:our|the|end|your)\s+client(?:'s|s)?\b|\bclient (?:location|site|requirement|side|premises)\b"
    r"|\bcustomer (?:location|site)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
_TOPIC_STOP_RE = re.compile(
    r"\b(?:someone|experienced|highly|onsite|on-site|offline|online|virtual|client|clients|deliver|who|"
    r"structured|practical|corporate|request|our|one of|for a|for an|please|suitable|senior|junior|"
    r"\w+-focused|kindly|urgent)\b|\b\d{1,2}(?:st|nd|rd|th)\b|[!?]|\.(?!\d)",
    re.IGNORECASE,
)

_LEAK_RE = re.compile(
    r"\bmargins?\b|\bmark-?ups?\b|\buplift\b|\b\d{1,3}\s*%"
    r"|\btrainer(?:'s|s')?\s+(?:rate|rates|share|fee|fees|payout|cost|commercials?|payment)\b"
    r"|\binternal(?:ly)?\s+(?:workflow|process|notes?|margin|cost|pricing|discussion|rate)s?\b",
    re.IGNORECASE,
)
_ATTACHMENT_CLAIM_RE = re.compile(r"\battached\b|\bplease find\b|\benclosed\b", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    rf"\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|tonight|eod|end of (?:the )?day"
    rf"|next week|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_RE})\b"
    r"|\bwithin\s+\d+\s*(?:hours?|hrs?|days?|business days?|working days?)\b",
    re.IGNORECASE,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _positive_int(value: Any) -> int:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0
    return int(number) if number > 0 and number.is_integer() else 0


def _strip_quoted_history(message: str) -> str:
    """Keep only the latest message: drop quoted replies and forwarded history."""
    lines: List[str] = []
    for line in str(message or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^on .{4,200} wrote:$", stripped, re.IGNORECASE):
            break
        if re.match(r"^-{2,}\s*(?:original message|forwarded message)\s*-{2,}$", stripped, re.IGNORECASE):
            break
        if re.match(r"^from:\s.+", stripped, re.IGNORECASE) and lines:
            break
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _logical_lines(message: str) -> List[Dict[str, Any]]:
    """Return message lines, joining a lone list marker with the text after it.

    Gmail often renders "1." or "-" on its own line with the item text two
    lines below, so the marker and the text must be paired again.
    """
    result: List[Dict[str, Any]] = []
    pending_marker = False
    for raw in message.split("\n"):
        if not raw.strip():
            continue
        if _LONE_MARKER_RE.match(raw):
            pending_marker = True
            continue
        is_item = pending_marker or bool(_LIST_MARKER_RE.match(raw))
        text = _LIST_MARKER_RE.sub("", raw).strip() if _LIST_MARKER_RE.match(raw) else raw.strip()
        result.append({"text": text, "item": is_item})
        pending_marker = False
    return result


def _request_segments(message: str) -> List[Dict[str, Any]]:
    """Return the parts of the email that ask for something, in order.

    A plain sentence counts when it contains a request verb. A list item counts
    when its own text asks for something or when the line introducing its list
    does ("Please share the following:"). Items under a neutral header such as
    "Training Details:" are facts, not requests.
    """
    segments: List[Dict[str, Any]] = []
    header_is_request = False
    header_role = ""
    for line in _logical_lines(message):
        text = line["text"]
        if line["item"]:
            if header_role:
                # Lists under "What we're looking for:" or "Topics to cover:" describe
                # the trainer or the course, they are not documents to send.
                segments.append({"text": text, "item": True, "role": header_role})
            elif header_is_request or _REQUEST_VERB_RE.search(text):
                segments.append({"text": text, "item": True})
            continue
        is_header = text.rstrip().endswith(":") or (len(text) < 60 and not re.search(r"[.!?]$", text))
        header_role = ""
        asks = bool(re.search(r"\b(?:please|kindly|share|send|provide|request you)\b", text, re.I))
        if is_header and _TRAINER_HEADER_RE.search(text):
            header_role = "trainer_detail"
        elif is_header and not asks and _SCOPE_HEADER_RE.search(text):
            header_role = "scope"
        elif is_header and not asks and _NEUTRAL_HEADER_RE.search(text):
            header_role = "ignore"
        header_is_request = bool(_REQUEST_VERB_RE.search(text)) and text.rstrip().endswith(":") and not header_role
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if _REQUEST_VERB_RE.search(sentence) and not re.match(
                r"^(?:regards|thanks|thank you|best regards)\b", sentence.strip(), re.IGNORECASE
            ):
                segments.append({"text": sentence.strip(), "item": False})
    return segments


def _kinds_in(text: str) -> List[str]:
    found: List[tuple] = []
    remaining = text
    for kind, pattern in _KIND_PATTERNS:
        if kind == "commercials":
            # "lab cost" is a lab request, not a request for training commercials.
            remaining = _KIND_PATTERNS[3][1].sub(" ", text)
            match = pattern.search(remaining)
        else:
            match = pattern.search(text)
        if match:
            found.append((match.start(), kind))
    kinds = [kind for _, kind in sorted(found)]
    if "lab" in kinds and "availability" in kinds and re.search(r"\b(?:sandbox|environment|lab)\b[^.\n]{0,30}availability", text, re.I):
        # "Sandbox / Training Environment Availability" is about the lab, not the trainer.
        kinds.remove("availability")
    return kinds


def _sentence_case(text: str) -> str:
    words = text.split()
    out = []
    for index, word in enumerate(words):
        keep = (word.isupper() and len(word) > 1) or bool(re.search(r"[a-z][A-Z]|\d", word))
        out.append(word if keep else word.lower())
    sentence = " ".join(out)
    return sentence[:1].upper() + sentence[1:]


def is_vendor_pitch(message: str) -> bool:
    """A training company offering us trainers is not a client requirement."""
    return bool(_VENDOR_PITCH_RE.search(_strip_quoted_history(message)[:3000]))


def _other_item(text: str) -> Optional[Dict[str, str]]:
    """Classify a list item that names no standard deliverable."""
    label = text.strip(" .;:*")
    if not label or _PLACEHOLDER_RE.search(label):
        return None
    if _CALL_RE.search(label):
        return {"kind": "call", "text": label}
    if _TRAINER_DETAIL_RE.search(label):
        return {"kind": "trainer_detail", "text": label}
    # "Mode: Virtual Instructor-Led Training" states a fact; it asks for nothing.
    fact = re.match(r"^[A-Za-z][\w /&().'-]{1,35}\s*[:\u2013]\s*(.+)$", label)
    if fact and not re.search(r"^(?:\(|if\b|tbd|tbc|to be)", fact.group(1).strip(), re.I):
        return None
    for field, pattern in _RECOMMEND_FIELDS:
        if pattern.search(label):
            return {"kind": "recommend", "field": field, "text": label}
    if re.search(r"\bnumber of participants\b|\bbatch size\b|\bparticipants?\b", label, re.I) and not re.search(r"\d", label):
        return {"kind": "recommend", "field": "participants", "text": label}
    if re.search(r"\b(?:level|audience)\b", label, re.I) and not re.search(r"[:\-]\s*\S", label):
        return {"kind": "recommend", "field": "audience", "text": label}
    # "Batch Size: 20 Participants" is a fact the client gave, not a request.
    if _FACT_LINE_RE.match(label):
        return None
    # Sub-points such as "Balance between concepts and demos" or a lone
    # "Additional Information" are not separate documents to promise.
    if not _DELIVERABLE_NOUN_RE.search(label) or len(label.split()) < 2 or re.match(
        r"^(?:additional information|others?|misc\w*|any other)\b", label, re.I
    ):
        return None
    return {"kind": "other", "text": label}


def _requested_items(message: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen = set()
    for segment in _request_segments(message):
        role = segment.get("role")
        if role == "ignore":
            continue
        if role in {"trainer_detail", "scope"}:
            label = segment["text"].strip(" .;:*")
            if label and len(label) <= 160 and label.lower() not in seen:
                seen.add(label.lower())
                items.append({"kind": role, "text": label})
            continue
        kinds = _kinds_in(segment["text"])
        if _CALL_RE.search(segment["text"]) and "call" not in seen:
            seen.add("call")
            items.append({"kind": "call", "text": segment["text"]})
            kinds = [kind for kind in kinds if kind != "availability"]
        if segment["item"] and _TRAINER_DETAIL_RE.search(segment["text"]) and set(kinds) <= {"trainer"}:
            # "Relevant experience with MCP" describes the profile, it is not a new deliverable.
            kinds = []
        if not kinds and segment["item"]:
            other = _other_item(segment["text"])
            key = other and other["text"].lower()
            if other and key not in seen:
                seen.add(key)
                items.append(other)
            continue
        if not kinds and _CALL_RE.search(segment["text"]) and "call" not in seen:
            seen.add("call")
            items.append({"kind": "call", "text": segment["text"]})
            continue
        for kind in kinds:
            if kind in seen:
                # Keep the most specific wording for lab and trainer items.
                for existing in items:
                    if existing["kind"] == kind and segment["item"] and not existing.get("from_item"):
                        existing["text"] = segment["text"]
                        existing["from_item"] = "1"
                continue
            seen.add(kind)
            items.append({"kind": kind, "text": segment["text"], **({"from_item": "1"} if segment["item"] else {})})
    for item in items:
        item.pop("from_item", None)
    return items


def _dates(message: str) -> List[Dict[str, Any]]:
    found = []
    for match in _DATE_RE.finditer(message):
        month_text = match.group(2).lower()[:3]
        month = next((name for name in _MONTHS if name.startswith(month_text)), month_text)
        day = int(match.group(1))
        year = match.group(3) or ""
        before = message[max(0, match.start() - 40):match.start()]
        found.append({
            "day": day,
            "month": month,
            "year": year,
            "label": f"{day} {month.title()}{(' ' + year) if year else ''}",
            "start_context": bool(_START_CONTEXT_RE.search(before)),
        })
    return found


def _start_date_conflict(message: str) -> Optional[Dict[str, Any]]:
    starts = [item for item in _dates(message) if item["start_context"]]
    distinct: List[Dict[str, Any]] = []
    for item in starts:
        if not any(item["day"] == other["day"] and item["month"] == other["month"] for other in distinct):
            distinct.append(item)
    if len(distinct) < 2:
        return None
    first, second = distinct[0], distinct[1]
    year = first["year"] or second["year"]
    labels = [
        f"{entry['day']} {entry['month'].title()}{(' ' + (entry['year'] or year)) if (entry['year'] or year) else ''}"
        for entry in (first, second)
    ]
    return {
        "kind": "start_date",
        "values": labels,
        "question": f"The start date, as the email mentions both {labels[0]} and {labels[1]}",
        "must_mention": [first["month"], second["month"]],
    }


def _training_days(message: str, extracted: Dict[str, Any], lab_text: str) -> int:
    days = _positive_int(extracted.get("duration_days"))
    if days:
        return days
    for line in message.split("\n"):
        if lab_text and lab_text in line:
            continue
        if re.search(r"\blab\b", line, re.IGNORECASE):
            continue
        match = re.search(r"\b(\d{1,3})\s*-?\s*(?:training\s+)?days?\b", line, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0


def _lab_hours(message: str, extracted: Dict[str, Any], lab_text: str) -> str:
    for text in (lab_text, message):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b[^.\n]{0,25}\b(?:per day|a day|daily|/day)?",
                          text or "", re.IGNORECASE)
        if match and (text is lab_text or re.search(r"\blab\b", text[max(0, match.start() - 40):match.end()], re.I)):
            return match.group(1).rstrip("0").rstrip(".") if "." in match.group(1) else match.group(1)
    hours = extracted.get("lab_hours_per_day")
    if hours not in (None, "", 0, "0"):
        text = _clean(hours)
        return text[:-2] if text.endswith(".0") else text
    return ""


def _greeting_word(message: str) -> str:
    first = next((line.strip() for line in message.split("\n") if line.strip()), "")
    match = re.match(r"^(dear|hello|hi|hey|good (?:morning|afternoon|evening))\b", first, re.IGNORECASE)
    if not match:
        return "Hello"
    word = match.group(1).lower()
    return {"dear": "Dear", "hello": "Hello", "hi": "Hi", "hey": "Hi"}.get(word, "Hello")


def _valid_name(token: str) -> str:
    token = re.sub(r"[^A-Za-z.'-]", "", token or "").strip(".'-")
    if len(token) < 2 or token.lower() in _GENERIC_NAMES:
        return ""
    return token[:1].upper() + token[1:].lower() if token.islower() or token.isupper() else token


def _signature_name(message: str) -> str:
    lines = [line.strip() for line in message.split("\n")]
    for index in range(len(lines) - 1, -1, -1):
        if _SIGNOFF_RE.match(lines[index]):
            for following in lines[index + 1:index + 4]:
                if not following:
                    continue
                if "@" in following or re.search(r"\d{5,}", following):
                    break
                return _valid_name(following.split()[0])
            break
    return ""


def _display_name(sender_name: str) -> str:
    text = re.sub(r"<[^>]*>|\([^)]*\)|\bvia\b.*$", "", str(sender_name or ""), flags=re.IGNORECASE).strip(" ,\"'")
    if not text or "@" in text:
        return ""
    return _valid_name(text.split()[0])


def _technology(extracted: Dict[str, Any]) -> str:
    for key in ("technology_needed", "technology", "domain"):
        value = _clean(extracted.get(key))
        if value and value.lower() not in {"training", "unknown", "tbd", "general"}:
            return value
    return ""


def _mode(message: str, extracted: Dict[str, Any]) -> str:
    for key in ("mode", "delivery_mode", "training_mode"):
        value = _clean(extracted.get(key)).lower()
        if value in {"online", "offline", "onsite", "on-site", "virtual", "classroom", "hybrid"}:
            return value
    match = re.search(r"\bmode\s*[:\-]\s*(online|offline|onsite|virtual|classroom|hybrid)\b", message, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _join(items: List[str]) -> str:
    items = [item for item in items if item]
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


_SUBJECT_NOISE_RE = re.compile(
    r"^(?:re|fw|fwd)\s*:\s*|\b(?:urgent|immediate|new|critical|priority)\b|\brequirements?\b|\brequest(?:ed)?\b"
    r"|\btrainers?\b|\btraining\b|\bprofiles?\b|\bavailability\b|\bproposals?\b|\bdetails\b|\bneeded\b"
    r"|\brequired\b|\bsupport\b|\bquotation\b|\bquote\b|\btoc\b|\bprogram(?:me)?\b|\bcorporate\b"
    r"|\bcertifications?\b|\bonline\b|\boffline\b|\bclassroom\b|\bonsite\b|\bvirtual\b|\bcourse\b",
    re.IGNORECASE,
)


def _clean_topic(value: str) -> str:
    text = re.sub(r"\([^)]{25,}\)", "", value or "")
    text = re.sub(r"\s+", " ", text).strip(" -\u2013\u2014|:,&/.")
    text = re.sub(r"^(?:for|of|on|in|with|and|the|a|an|&)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+(?:for|of|on|in|with|and|the|a|an|&|-)$", "", text, flags=re.I)
    return text.strip(" -\u2013\u2014|:,&/.")


def _topic_from_subject(subject: str) -> str:
    for segment in re.split(r"\s*(?:\|\||\||\u2013|\u2014|:| - )\s*", str(subject or "")):
        reduced = _clean_topic(_SUBJECT_NOISE_RE.sub(" ", segment))
        reduced = re.sub(r"^(?:for|&|and)\s+", "", reduced, flags=re.I).strip()
        reduced = _clean_topic(re.sub(r"\s+(?:for|and|&)\s*$", "", reduced, flags=re.I))
        if reduced.count("(") > reduced.count(")"):
            reduced = _clean_topic(reduced[:reduced.rfind("(")])
        if 2 <= len(reduced) <= 60 and re.search(r"[A-Za-z]{2}", reduced) and not re.fullmatch(
            r"\d.*|(?:bangalore|bengaluru|mumbai|pune|chennai|hyderabad|delhi|noida|gurgaon|india)\b.*", reduced, re.I
        ):
            return reduced
    return ""


def _sane_topic(value: str) -> str:
    text = _clean_topic(re.sub(r"^(?:training|course|program(?:me)?)\s+(?:on|in|for)\s+", "", str(value or ""), flags=re.I))
    if text.count("(") > text.count(")"):
        text = _clean_topic(text[:text.rfind("(")])
    text = _clean_topic(re.sub(r"\s+by\s+[A-Z]\w+$", "", text))
    if re.match(rf"^{_MONTH_RE}\b", text, re.I) or _CITY_RE.fullmatch(text) or re.fullmatch(
        r"(?:Master|Official|Content|Official Content|Senior|Expert|Corporate|Client)s?", text, re.I
    ):
        return ""
    if (not text or len(text) > 45 or _TOPIC_STOP_RE.search(text) or len(text.split()) > 6
            or not re.match(r"[A-Z0-9]", text) or not re.search(r"[A-Za-z]{2}", text)
            or re.search(r"\b(?:above|below|external|internal|conducting|legal|same|following|requirement)\b", text, re.I)):
        return ""
    return text


_BODY_TOPIC_RE = re.compile(
    r"\b(?:requirements?|training|trainers?|program(?:me)?|session|course|client|customer)\s+(?:for|on|in)\s+(?:a\s+|an\s+|the\s+)?"
    r"((?:[A-Z][\w&+#./-]*|\d[\w.]*)(?:\s+(?:&\s+)?(?:\(?[A-Z0-9][\w&+#./-]*\)?|and|of|for|with|on))*)",
)
_VENDOR_PITCH_RE = re.compile(
    r"\bcame across your\b|\bsaw your (?:linkedin )?post\b|\breference your post\b|\bhappy to introduce\b"
    r"|\bintroduce (?:ourselves|our company)\b|\bwe (?:offer|provide) (?:end-to-end|industry|corporate|customi[sz]ed)\b"
    r"|\bour capabilities\b|\bglad to (?:collaborate|partner|support you)\b|\bexplore (?:a )?(?:collaboration|partnership)\b"
    r"|\bwe understand that you have a requirement\b|\bpartner with (?:you|clahan)\b",
    re.IGNORECASE,
)
_TOPIC_TAIL_RE = re.compile(
    r"\s+(?:Training|Trainer|Trainers|Certification|Program|Programme|Course|Session|Batch|Workshop|for|and|of|with)\b.*$"
)


def _topic_from_body(message: str) -> str:
    for match in _BODY_TOPIC_RE.finditer(message[:1500]):
        candidate = _sane_topic(_TOPIC_TAIL_RE.sub("", match.group(1))) or ""
        if (2 <= len(candidate) <= 50 and not _TOPIC_STOP_RE.search(candidate)
                and not re.fullmatch(r"(?:Clahan|CloudThat|Our|We|You|Your|The|This|Team|Client)\b.*", candidate)
                and not _CITY_RE.fullmatch(candidate)):
            return candidate
    return ""


def _topic(subject: str, extracted: Dict[str, Any], message: str = "") -> str:
    extracted_topic = _sane_topic(_technology(extracted))
    subject_topic = _topic_from_subject(subject)
    if subject_topic and (not extracted_topic or extracted_topic.lower() in subject_topic.lower()):
        return subject_topic
    body_topic = _topic_from_body(message)
    if body_topic and (not extracted_topic or extracted_topic.lower() in body_topic.lower()):
        return body_topic
    return extracted_topic or subject_topic or body_topic


def _trainer_count(message: str) -> int:
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "multiple": 2}
    match = re.search(r"\b(\d{1,2}|two|three|four|five|multiple)\s+(?:[\w&/-]+\s+){0,4}?trainers\b", message, re.I)
    if not match:
        return 2 if re.search(r"\btrainers\b", message, re.I) and not re.search(r"\btrainer\b", message, re.I) else 1
    token = match.group(1).lower()
    return words.get(token) or max(1, int(token))


def _experience_years(message: str) -> str:
    match = re.search(r"\b(\d{1,2}\+?)\s*(?:\+\s*)?(?:years?|yrs?)\b(?:\s+of)?(?:\s+\w+){0,3}\s+experience"
                      r"|experience(?:\s+required)?\s*[:\-]?\s*(\d{1,2}\+?)\s*(?:\+\s*)?(?:years?|yrs?)", message, re.I)
    if not match:
        return ""
    value = match.group(1) or match.group(2)
    return value if value.endswith("+") else f"{value}+" if re.search(r"\+|minimum|at least|min\b", match.group(0), re.I) else value


def _focus_from_details(details: List[str]) -> str:
    phrases: List[str] = []
    for detail in details:
        match = re.search(
            r"\b(?:experience|expertise|exposure|knowledge|background|proficiency)\s+(?:in|with|of|on)\s+"
            r"(?:delivering\s+|working (?:on|with)\s+)?(?:the\s+)?(.+)$",
            detail, re.I,
        ) or re.search(r"\bexperience delivering\s+(.+)$", detail, re.I)
        if not match:
            continue
        phrase = re.split(r"[,(;.]|\s+-\s+|\s+specifically\b|\s+particularly\b|\s+such as\b", match.group(1))[0]
        phrase = _clean_topic(re.sub(r"\b(?:trainings?|sessions?|corporate batches)\b", "", phrase, flags=re.I))
        phrase = re.split(r"\s+and\s+(?=[A-Z])|\s+/\s+", phrase)[0].strip()
        phrase = re.sub(r"\s+(?:functional|technical)?\s*(?:and/or|and|or)\s*(?:functional|technical)\s*$", "",
                        phrase, flags=re.I).strip()
        phrase = re.sub(r"\s+(?:functional|technical)$", "", phrase, flags=re.I).strip()
        if 2 <= len(phrase) <= 40 and phrase.lower() not in {p.lower() for p in phrases}:
            phrases.append(phrase)
    return _join(phrases[:2])


_CITY_RE = re.compile(
    r"\b(Bangalore|Bengaluru|Mumbai|Navi Mumbai|Pune|Chennai|Hyderabad|Delhi|New Delhi|Noida|Gurgaon|Gurugram|"
    r"Kolkata|Ahmedabad|Kochi|Cochin|Coimbatore|Mysore|Mysuru|Trivandrum|Thiruvananthapuram|Jaipur|Chandigarh|"
    r"Indore|Nagpur|Vadodara|Visakhapatnam|Vizag|Bhubaneswar|Lucknow|Mahape|Dubai|Singapore)\b",
    re.IGNORECASE,
)


def _location(message: str, extracted: Dict[str, Any], subject: str = "") -> str:
    def tidy(value: str) -> str:
        value = re.sub(r"^(?:client|customer)\s+(?:site|location|premises)\s*[\u2013\-:,]?\s*", "", value, flags=re.I)
        return _clean_topic(value)

    value = _clean(extracted.get("location"))
    if value and len(value) <= 40 and not re.search(r"online|virtual|tbd|to be|\(|training", value, re.I):
        return tidy(value)
    match = re.search(r"\b(?i:location|venue)\s*[:\-]\s*([A-Z][\w ,.\u2013-]{2,45})", message)
    if match and not re.search(r"online|virtual|tbd|to be|if the", match.group(1), re.I):
        return tidy(match.group(1))
    city = _CITY_RE.search(subject or "") or _CITY_RE.search(message)
    return city.group(1).title() if city else ""


def _duration_known(message: str, extracted: Dict[str, Any], training_days: int) -> bool:
    if training_days or _positive_int(extracted.get("duration_hours")):
        return True
    if _clean(extracted.get("duration_text")) and re.search(r"\d", _clean(extracted.get("duration_text"))):
        return True
    for line in message.split("\n"):
        if re.search(r"\blab\b", line, re.I):
            continue
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:-\s*)?(?:full\s+)?(?:days?|hours?|hrs?|weeks?|months?)\b", line, re.I):
            return True
    return False


def _dates_known(message: str, extracted: Dict[str, Any]) -> bool:
    if any(_clean(extracted.get(key)) for key in ("training_dates", "preferred_dates", "timeline_start")):
        return True
    if _dates(message):
        return True
    return bool(re.search(
        rf"\b(?:start\w*|from|timeline|dates?|schedule\w*|planned|in)\b[^.\n]{{0,40}}"
        rf"\b(?:{_MONTH_RE}|immediate\w*|asap|next week|this week|next month|q[1-4])\b",
        message, re.I,
    ))


def _participant_count_text(message: str) -> str:
    match = re.search(
        r"(?:participants?|batch size|headcount)\s*[:\-]\s*(\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?)"
        r"|\b(?:approx\.?\s*|around\s*|about\s*)?(\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?)\s*"
        r"(?:participants|learners|attendees|people|members)\b",
        message, re.IGNORECASE,
    )
    return next((group for group in match.groups() if group), "") if match else ""


def _engagement_length(message: str) -> str:
    """A long engagement such as "for a duration of 6 months" becomes "6-month"."""
    match = re.search(r"\b(?:duration\s*(?:of)?\s*[:\-]?\s*|for\s+(?:a\s+duration\s+of\s+)?)(\d{1,2})\s*(month|week)s?\b",
                      message, re.IGNORECASE)
    return f"{match.group(1)}-{match.group(2).lower()}" if match else ""


def _grounded_extracted(extracted: Dict[str, Any], message: str, subject: str = "") -> Dict[str, Any]:
    """Drop extractor values the email does not state, so the reply never repeats a guess."""
    from app.agents.requirement_understanding import _norm, _supported

    email = _norm(f"{subject}\n{message}")
    safe = dict(extracted)
    for key in ("technology_needed", "technology", "domain", "location", "audience_level",
                "training_dates", "preferred_dates", "timeline_start", "duration_text", "cloud_provider"):
        if _clean(safe.get(key)) and not _supported(safe.get(key), email, 0.75):
            safe[key] = ""
    days = _positive_int(safe.get("duration_days"))
    if days and not re.search(rf"(?<!\d){days}\s*-?\s*(?:full\s+|training\s+|working\s+)?days?\b", email):
        safe["duration_days"] = None
    count = _positive_int(safe.get("participant_count"))
    if count:
        stated = _participant_count_text(message)
        if not stated or str(count) not in re.findall(r"\d+", stated) or re.search(r"[-\u2013]", stated):
            safe["participant_count"] = None
    hours = str(safe.get("lab_hours_per_day") or "").strip()
    if hours and hours not in {"0", "0.0"}:
        number = hours[:-2] if hours.endswith(".0") else hours
        if not re.search(rf"(?<![\d.]){re.escape(number)}\s*(?:hours?|hrs?)\s+(?:of\s+)?(?:hands-on\s+)?lab\b"
                         rf"|\blab\b[^.\n]{{0,40}}(?<![\d.]){re.escape(number)}\s*(?:hours?|hrs?)\b", email):
            safe["lab_hours_per_day"] = None
    return safe


def build_reply_plan(
    message: str,
    extracted: Optional[Dict[str, Any]] = None,
    batch_type: str = "proposal",
    sender_name: str = "",
    subject: str = "",
    seed: str = "",
) -> Dict[str, Any]:
    """Build the reply plan for a first client requirement email."""
    latest = _strip_quoted_history(message)
    extracted = _grounded_extracted(dict(extracted or {}), latest, subject)
    batch = "confirmed" if str(batch_type or "").lower().startswith("confirm") else "proposal"
    items = _requested_items(latest)
    kinds = {item["kind"] for item in items}

    trainer_item = next((item for item in items if item["kind"] == "trainer"), None)
    lab_item = next((item for item in items if item["kind"] == "lab"), None)
    lab_text = lab_item["text"] if lab_item else ""
    lab_days_match = re.search(r"\b(\d{1,3})\s*-?\s*days?\b", lab_text, re.IGNORECASE)
    lab_days = int(lab_days_match.group(1)) if lab_days_match else 0
    training_days = _training_days(latest, extracted, lab_text)
    cloud = _clean(extracted.get("cloud_provider"))
    if not cloud:
        cloud_match = _CLOUD_RE.search(latest)
        cloud = cloud_match.group(0) if cloud_match else ""
    cloud_label = {"amazon web services": "AWS", "aws": "AWS", "azure": "Azure", "gcp": "GCP",
                   "google cloud": "GCP"}.get(cloud.lower(), cloud)
    participants = _positive_int(extracted.get("participant_count"))
    participants_known = bool(participants) or bool(_PARTICIPANTS_RE.search(latest))
    recommended = {item.get("field") for item in items if item["kind"] == "recommend"}
    call_item = next((item for item in items if item["kind"] == "call"), None) or next(
        (item for item in items if _CALL_RE.search(item["text"])), None)
    trainer_details = [item["text"] for item in items if item["kind"] == "trainer_detail"]
    availability_item = next((item for item in items if item["kind"] == "availability"), None)
    topic = _topic(subject, extracted, latest)
    # "We are looking for a trainer with strong expertise in CMDB and CSDM" names the focus.
    for match in re.finditer(r"\btrainers?\b[^.\n]{0,60}?\b(?:expertise|experience|exposure)\s+(?:in|with)\s+([^.\n]{3,80})",
                             latest, re.IGNORECASE):
        trainer_details.append("experience in " + match.group(1).strip())
    location = _location(latest, extracted, subject)
    mode = _mode(latest, extracted)
    onsite = bool(re.search(r"\b(?:onsite|on-site|client (?:site|location)|in-person|classroom|offline)\b", latest, re.I))

    # Tentative fields the client has explicitly left open.
    tentative: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", latest):
        if _TENTATIVE_RE.search(sentence):
            for label, pattern in _TENTATIVE_FIELDS:
                if pattern.search(sentence) and label not in tentative:
                    tentative.append(label)

    # Ask only what the client can tell us and has not already said, left open
    # on purpose, or asked us to recommend. Real replies ask three things at most.
    missing: List[Dict[str, str]] = []
    lab_is_conditional = bool(lab_item and re.search(r"if (?:any|applicable|required)", lab_text, re.I))
    if "lab" in kinds and not cloud_label and not lab_is_conditional and "lab_setup" not in recommended:
        missing.append({"key": "cloud", "question": "The preferred cloud platform for the lab (AWS, Azure, or GCP)"})
    if (not participants_known and "participant count" not in tentative and "participants" not in recommended
            and ("lab" in kinds or "commercials" in kinds or batch == "proposal")):
        missing.append({"key": "participants", "question": "The number of participants"})
    if batch == "proposal":
        if (not _dates_known(latest, extracted) and "dates" not in tentative and "dates" not in recommended
                and not availability_item):
            missing.append({"key": "dates", "question": "The preferred training dates"})
        if (not _duration_known(latest, extracted, training_days) and "duration" not in tentative
                and "duration" not in recommended):
            missing.append({"key": "duration", "question": "The expected duration (number of days and hours per day)"})
        if (not mode and not _MODE_RE.search(latest) and not location and "delivery mode" not in tentative
                and "mode" not in recommended):
            missing.append({"key": "mode", "question": "The delivery mode (online or offline)"})
        if ("toc" in kinds and not missing and "audience" not in recommended
                and not _clean(extracted.get("audience_level"))
                and not re.search(r"\b(?:beginners?|intermediate|advanced|basic|level|freshers?|experienced|novices?)\b", latest, re.I)):
            missing.append({"key": "audience", "question": "The experience level of the participants"})
    missing = missing[:3]

    conflicts: List[Dict[str, Any]] = []
    date_conflict = _start_date_conflict(latest)
    if date_conflict:
        conflicts.append(date_conflict)
    if lab_days and training_days and lab_days != training_days:
        conflicts.append({
            "kind": "lab_days",
            "values": [str(lab_days), str(training_days)],
            "question": f"Whether the lab cost should cover {lab_days} days or the full {training_days}-day program",
            "must_mention": [str(lab_days), str(training_days)],
        })

    name = _signature_name(latest) or _display_name(sender_name)
    word = _greeting_word(latest)
    greeting = f"{word} {name}," if name else "Hello,"

    # The client's main need is a trainer. Trainer first, then the client's order.
    ordered = [item for item in items if item["kind"] == "trainer"]
    ordered += [item for item in items if item["kind"] not in {
        "trainer", "availability", "proposal", "trainer_detail", "call", "scope"}]
    scope = [_clean_topic(re.split(r"[:(\u2013]| - ", item["text"])[0]) for item in items if item["kind"] == "scope"]
    scope = [entry for entry in scope if 2 <= len(entry) <= 45][:3]


    return {
        "engine": "reply_precheck_v2",
        "batch_type": batch,
        "greeting": greeting,
        "client_name": name,
        "technology": topic,
        "training_days": training_days,
        "mode": mode,
        "location": location,
        "onsite": onsite,
        "urgent": bool(_URGENT_RE.search(subject) or _URGENT_RE.search(latest)),
        "end_client": bool(_END_CLIENT_RE.search(latest)),
        "trainer_count": _trainer_count(latest),
        "experience_years": _experience_years(latest),
        "trainer_focus": _focus_from_details(trainer_details),
        "trainer_details": trainer_details[:6],
        "call_requested": bool(call_item),
        "scope": scope,
        "seed": seed or subject or latest[:200],
        "schedule": {
            "start": _clean(extracted.get("timeline_start") or extracted.get("training_dates") or extracted.get("preferred_dates"))
            if not _start_date_conflict(latest) else "",
            "duration": _clean(extracted.get("duration_text")),
            "hours_per_day": "",
            "mode": mode,
        },
        "participants_count": str(participants) if participants else _participant_count_text(latest),
        "audience_level": _clean(extracted.get("audience_level")),
        "commercial_basis": "",
        "budget_mentioned": bool(re.search(r"\bbudget\b", latest, re.I)) and "budget" not in tentative,
        "deadline": "",
        "engagement_length": _engagement_length(latest),
        "items": ordered,
        "trainer_requested": bool(trainer_item) or batch == "confirmed" or "proposal" in kinds or not items,
        "cv_requested": bool(trainer_item and re.search(r"\b(?:cv|resume)s?\b", trainer_item["text"], re.I)),
        "availability_requested": bool(availability_item),
        "lab": {"requested": bool(lab_item), "days": lab_days, "hours": _lab_hours(latest, extracted, lab_text),
                "cloud": cloud_label},
        "missing": missing,
        "conflicts": conflicts,
        "tentative": tentative,
        "signature": SIGNATURE,
    }


def _recommend_line(item: Dict[str, Any]) -> str:
    text = item["text"].strip(" .;:*")
    if len(text.split()) <= 4 and not re.search(r"\brecommend|propos|suggest|expected|tentative|preferred", text, re.I):
        # "Training Duration" -> "The recommended training duration"; keep acronyms.
        sentence = _sentence_case(text)
        return "The recommended " + sentence[:1].lower() + sentence[1:]
    return _sentence_case(text)


def _pick(plan: Dict[str, Any], key: str, options: List[str]) -> str:
    """Choose a phrasing per email, so a client who writes often does not get identical mail."""
    digest = hashlib.sha1(f"{plan.get('seed', '')}:{key}".encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _commercials_line(plan: Dict[str, Any], item: Dict[str, Any]) -> str:
    basis = _clean(plan.get("commercial_basis"))
    text = item.get("text") or ""
    if not basis:
        found = re.findall(r"per\s+(day|batch|month|hour|participant|session)", text, re.I)
        basis = _join([f"per-{word.lower()}" for word in dict.fromkeys(found)]) if found else ""
    elif not basis.lower().startswith("per-"):
        basis = re.sub(r"\bper\s+", "per-", basis, flags=re.I)
    budget = plan.get("budget_mentioned") or re.search(r"\bbudget\b", text, re.I)
    line = f"The commercials on a {basis} basis" if basis else (
        "The commercial details" if plan["batch_type"] == "confirmed" else "The commercials for the program")
    return line + (" within your stated budget" if budget else "")


def _deliverable_lines(plan: Dict[str, Any]) -> List[str]:
    confirmed = plan["batch_type"] == "confirmed"
    days = plan.get("training_days") or 0
    lab = plan.get("lab") or {}
    lines: List[str] = []
    extra: List[str] = []
    for item in plan.get("items") or []:
        kind = item["kind"]
        if kind == "trainer":
            continue
        if kind == "toc":
            scope = plan.get("scope") or []
            covering = f" covering {_join(scope)}" if scope else ""
            if confirmed:
                base = f"A detailed day-wise ToC for the {days}-day program" if days else "A detailed day-wise ToC"
            else:
                base = f"A proposed course outline for the {days}-day program" if days else "A proposed course outline"
            lines.append(base + covering)
        elif kind == "lab":
            cloud = f"{lab['cloud']} " if lab.get("cloud") else ""
            conditional = re.search(r"if (?:any|applicable|required|needed)", item["text"], re.I)
            if item.get("environment_only") or not re.search(
                    r"\b(?:cost|charges?|estimate|pricing|price|quote)\b", item["text"], re.I):
                lines.append(f"Details of the {cloud}lab and sandbox environment" + (", if applicable" if conditional else ""))
            elif lab.get("days") and lab.get("hours"):
                lines.append(f"A separate {cloud}lab cost for {lab['days']} days at {lab['hours']} hours of hands-on lab per day")
            elif lab.get("hours"):
                lines.append(f"A separate {cloud}lab cost for {lab['hours']} hours of hands-on lab per day")
            elif lab.get("days"):
                lines.append(f"A separate {cloud}lab cost for {lab['days']} days")
            elif conditional:
                lines.append(f"The {cloud}lab cost, if a lab is needed")
            else:
                lines.append(f"A separate {cloud}lab-cost estimate")
        elif kind == "commercials":
            lines.append(_commercials_line(plan, item))
        elif kind == "recommend":
            extra.append(_recommend_line(item))
        elif kind == "other":
            extra.append(_sentence_case(item["text"]))
    # Standard documents first so they always fit, then the client's other asks.
    seen, unique = set(), []
    for line in lines + extra:
        if line.lower() not in seen:
            seen.add(line.lower())
            unique.append(line)
    return unique[:6]


def _trainer_noun(plan: Dict[str, Any]) -> str:
    count = int(plan.get("trainer_count") or 1)
    topic = plan.get("technology") or ""
    amount = _NUMBER_WORDS.get(count, str(count)) if count > 1 else "a"
    return f"{amount} suitable {topic + ' ' if topic else ''}{'trainers' if count > 1 else 'trainer'}"


def _where_phrase(plan: Dict[str, Any]) -> str:
    location = plan.get("location")
    client = "your client's" if plan.get("end_client") else "the"
    if plan.get("onsite") and location:
        return f" who can deliver onsite in {location}" if _CITY_RE.fullmatch(location) else f" who can deliver onsite at {location}"
    if plan.get("onsite") and plan.get("end_client"):
        return f" who can deliver at {client} location"
    return ""


def _trainer_paragraph(plan: Dict[str, Any]) -> str:
    """Who we are finding, what their profile will show, and what we will send."""
    count = int(plan.get("trainer_count") or 1)
    years = plan.get("experience_years")
    engagement = _clean(plan.get("engagement_length"))
    program = "your client's" if plan.get("end_client") else "this"
    program += f" {engagement} engagement" if engagement else " program"
    who = _trainer_noun(plan)
    if years:
        who += f" with {years} years of experience"
    first = f"We are identifying {who}{_where_phrase(plan)} for {program}."

    # Skills come from the verified understanding, or from "experience in X" phrases.
    skills = [skill.strip(" .") for skill in (plan.get("trainer_skills") or []) if 2 <= len(skill.strip()) <= 60][:3]
    focus = _join(skills) or plan.get("trainer_focus") or ""
    if focus:
        whose = "Their profiles" if count > 1 else "The profile"
        second = f" {whose} will highlight hands-on experience in {focus}."
    else:
        if not years:
            first = first.replace(f"{who}{_where_phrase(plan)}", f"{who} with relevant hands-on experience{_where_phrase(plan)}")
        second = ""

    profile = "the trainer profiles" if count > 1 else "the trainer profile"
    what = f"{profile} and updated CV{'s' if count > 1 else ''}" if plan.get("cv_requested") else profile
    extras = []
    if plan.get("availability_requested"):
        extras.append("availability")
    if plan.get("call_requested"):
        extras.append("suitable slots for the screening call")
    if extras:
        what += " along with " + ("their " if count > 1 else "the trainer's ") + _join(extras)
    timing = "on priority" if plan.get("urgent") else "as soon as possible"
    third = f" We will share {what} with you {timing}."
    return first + second + third


def _batch_description(plan: Dict[str, Any]) -> str:
    parts = []
    if plan.get("training_days"):
        parts.append(f"{plan['training_days']}-day")
    if plan.get("mode"):
        parts.append(plan["mode"])
    if plan.get("technology"):
        parts.append(plan["technology"])
    return " ".join(parts + ["training batch"])


def _start_phrase(plan: Dict[str, Any]) -> str:
    start = _clean((plan.get("schedule") or {}).get("start"))
    if not start or any(conflict.get("kind") == "start_date" or "start" in conflict.get("kind", "")
                        for conflict in plan.get("conflicts") or []):
        return ""
    start = re.sub(r"^(?:from|starting|on)\s+", "", start, flags=re.I)
    return f" starting {start}"


def _proposal_summary(plan: Dict[str, Any]) -> str:
    topic = plan.get("technology")
    whose = "your client's" if plan.get("end_client") else "the"
    text = f"{whose} {topic + ' ' if topic else ''}training requirement"
    participants = _clean(plan.get("participants_count"))
    if participants and re.fullmatch(r"\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?", participants):
        text += f" for {participants} participants"
    mode = plan.get("mode")
    if plan.get("onsite") and plan.get("location") and _CITY_RE.fullmatch(plan["location"]):
        text += f" in {plan['location']}"
    elif mode == "online":
        text += ", delivered online"
    return text


def _urgency_sentence(plan: Dict[str, Any]) -> str:
    if not plan.get("urgent"):
        return ""
    deadline = _clean(plan.get("deadline"))
    if deadline:
        return f" We have noted your timeline ({deadline}) and are giving this requirement priority."
    return " " + _pick(plan, "urgent", [
        "We understand this is a priority requirement and are taking it up right away.",
        "We have noted the urgency and are giving this requirement priority.",
    ])


def render_plan_reply(plan: Dict[str, Any]) -> str:
    """Write the complete reply from the plan, without any LLM call."""
    confirmed = plan["batch_type"] == "confirmed"
    count = int(plan.get("trainer_count") or 1)
    paragraphs: List[str] = [plan["greeting"]]
    deliverables = _deliverable_lines(plan)
    questions = [entry["question"] for entry in plan.get("missing") or []]
    questions += [entry["question"] for entry in plan.get("conflicts") or []]
    lead_in = _pick(plan, "lead", [
        f"Along with the {'profiles' if count > 1 else 'profile'}, we will share:",
        f"Together with the {'profiles' if count > 1 else 'profile'}, we will also share:",
    ])

    if confirmed:
        opening = _pick(plan, "open_confirmed", [
            f"Thank you for sharing the confirmed requirement for the {_batch_description(plan)}{_start_phrase(plan)}.",
            f"Thank you for confirming the {_batch_description(plan)}{_start_phrase(plan)}. "
            "We appreciate the opportunity to support it.",
        ])
        paragraphs.append(opening + _urgency_sentence(plan))
        paragraphs.append(_trainer_paragraph(plan))
        if deliverables:
            paragraphs.append(lead_in + "\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(deliverables, 1)))
        if questions:
            kinds = [item["kind"] for item in plan.get("items") or []]
            names = [name for kind, name in (("toc", "ToC"), ("lab", "lab cost")) if kind in kinds]
            target = f"the {_join(names)}" if names else "the arrangements"
            paragraphs.append(f"To finalize {target}, could you please confirm:\n" + "\n".join(
                f"\u2022 {question}" for question in questions
            ))
            paragraphs.append("Once we receive these details, we will share everything for your review "
                              "and move ahead with the trainer confirmation.")
        else:
            paragraphs.append("We will share everything for your review and move ahead with the trainer confirmation.")
    else:
        opening = _pick(plan, "open_proposal", [
            f"Thank you for sharing {_proposal_summary(plan)} with us.",
            f"Thank you for reaching out to us with {_proposal_summary(plan)}.",
        ])
        paragraphs.append(opening + _urgency_sentence(plan))
        paragraphs.append(_trainer_paragraph(plan))
        if deliverables:
            paragraphs.append(lead_in + "\n" + "\n".join(f"{index}. {line}" for index, line in enumerate(deliverables, 1)))
        tentative = plan.get("tentative") or []
        if tentative:
            paragraphs.append(f"We have noted that the {_join(tentative)} {'is' if len(tentative) == 1 else 'are'} "
                              "still to be confirmed, and we will keep the proposal flexible for these.")
        if questions:
            intro = _pick(plan, "ask", [
                "To align the trainer and the proposal with your needs, could you please share:",
                "To make sure the proposal fits your requirement, could you please share:",
            ])
            paragraphs.append(intro + "\n" + "\n".join(f"\u2022 {question}" for question in questions))
            paragraphs.append("Once we receive these details, we will share the complete proposal for your review. "
                              "Thank you for considering Clahan Technologies.")
        else:
            paragraphs.append("We will share the complete details for your review. "
                              "Thank you for considering Clahan Technologies.")

    paragraphs.append(plan.get("signature") or SIGNATURE)
    return "\n\n".join(paragraphs)


def check_reply(body: str, plan: Dict[str, Any]) -> List[str]:
    """Return the problems that make a draft unsafe or incomplete to send."""
    text = str(body or "")
    lower = text.lower()
    problems: List[str] = []
    if not text.startswith(plan["greeting"]):
        problems.append("greeting_mismatch")
    if plan.get("trainer_requested") and not re.search(r"\btrainers?\b", lower):
        problems.append("trainer_missing")
    if plan.get("trainer_requested") and not re.search(r"\bprofiles?\b|\bcvs?\b", lower):
        problems.append("trainer_profile_missing")
    checks = {
        "toc": r"\btoc\b|table of contents|course outline|\boutline\b|syllabus|curriculum",
        "lab": r"\blab\b",
        "commercials": r"commercial|pricing|quot(?:e|ation)|\bcost\b|proposal",
    }
    for item in plan.get("items") or []:
        pattern = checks.get(item["kind"])
        if pattern and not re.search(pattern, lower):
            problems.append(f"{item['kind']}_missing")
    for entry in plan.get("missing") or []:
        pattern = {
            "cloud": r"\baws\b|\bazure\b|\bgcp\b|cloud",
            "participants": r"participant",
            "audience": r"level|experience",
            "dates": r"\bdates?\b",
            "duration": r"duration|training days|number of days",
            "mode": r"\bmode\b|online|offline",
        }.get(entry["key"])
        if pattern and not re.search(pattern, lower):
            problems.append(f"question_missing:{entry['key']}")
    for conflict in plan.get("conflicts") or []:
        if not all(re.search(rf"\b{re.escape(str(value).lower())}\b", lower) for value in conflict["must_mention"]):
            problems.append(f"conflict_missing:{conflict['kind']}")
    if _LEAK_RE.search(text):
        problems.append("internal_detail_leak")
    if _ATTACHMENT_CLAIM_RE.search(text):
        problems.append("attachment_claim")
    deadline = _clean(plan.get("deadline")).lower()
    promised = [match.group(0) for match in _DEADLINE_RE.finditer(text)
                if not (deadline and match.group(0).lower() in deadline)]
    if promised:
        problems.append("deadline_promise")
    words = len(re.findall(r"\w+", text))
    if words < 35:
        problems.append("too_short")
    if words > 320:
        problems.append("too_long")
    return problems


def plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """A compact, storable record of what the engine decided."""
    return {
        "engine": plan.get("engine"),
        "batch_type": plan.get("batch_type"),
        "greeting": plan.get("greeting"),
        "requested_items": [item["kind"] for item in plan.get("items") or []],
        "trainer_requested": plan.get("trainer_requested"),
        "missing": [entry["key"] for entry in plan.get("missing") or []],
        "conflicts": [entry["question"] for entry in plan.get("conflicts") or []],
        "tentative": plan.get("tentative") or [],
        "topic": plan.get("technology") or "",
        "urgent": bool(plan.get("urgent")),
        "end_client": bool(plan.get("end_client")),
        "trainer_count": plan.get("trainer_count") or 1,
        "call_requested": bool(plan.get("call_requested")),
        "understanding_source": plan.get("understanding_source", "rules"),
    }
