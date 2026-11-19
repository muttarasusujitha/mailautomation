"""Deterministic personalization engine for first client requirement replies.

The engine reads the client's latest message once, without any LLM call, and
builds a reply plan:

* batch type (confirmed or proposal), decided by the existing classifier;
* the items the client asked for, trainer first, then in the client's order;
* the details still missing (cloud platform, participant count, ...);
* conflicts inside the email (two start dates, lab days vs training days);
* the client's greeting style and the name they signed with.

The plan is used three ways:

1. ``render_plan_reply`` writes a complete, polite reply from the plan. It is
   the reply in template mode and the fallback in AI mode, so a failed or
   incomplete AI draft never costs a second LLM call and never stops sending.
2. ``plan_prompt`` and ``plan_writing_guidance`` give the single LLM call a
   ready-made checklist, so the model only phrases the reply.
3. ``check_reply`` verifies a draft against the plan before it is sent.

This module has no third-party dependencies so it can be tested in isolation.
"""

from __future__ import annotations

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
    ("availability", re.compile(r"\bavailability\b", re.IGNORECASE)),
    ("toc", re.compile(
        r"\btoc\b|table of contents|course outline|\boutline\b|syllabus|curriculum|\bagenda\b|course content",
        re.IGNORECASE,
    )),
    ("lab", re.compile(
        r"\blab[- ]?(?:cost|charges?|estimate|pricing|price|quote)s?\b"
        r"|\blab\b[^.\n]{0,30}\b(?:cost|charges?|estimate|pricing)\b",
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
    r"|\bparticipants?\s*[:\-]\s*\d+",
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
}

_LEAK_RE = re.compile(
    r"\bmargins?\b|\bmark-?ups?\b|\buplift\b|\b\d{1,3}\s*%"
    r"|\btrainer(?:'s|s')?\s+(?:rate|rates|share|fee|fees|payout|cost|commercials?|payment)\b"
    r"|\binternal(?:ly)?\b",
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
    for line in _logical_lines(message):
        text = line["text"]
        if line["item"]:
            if header_is_request or _REQUEST_VERB_RE.search(text):
                segments.append({"text": text, "item": True})
            continue
        header_is_request = bool(_REQUEST_VERB_RE.search(text)) and text.rstrip().endswith(":")
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
    return [kind for _, kind in sorted(found)]


def _requested_items(message: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen = set()
    for segment in _request_segments(message):
        kinds = _kinds_in(segment["text"])
        if not kinds and segment["item"]:
            label = segment["text"].strip(" .;:")
            if label and label.lower() not in seen:
                seen.add(label.lower())
                items.append({"kind": "other", "text": label})
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
        return _clean(hours)
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


def build_reply_plan(
    message: str,
    extracted: Optional[Dict[str, Any]] = None,
    batch_type: str = "proposal",
    sender_name: str = "",
) -> Dict[str, Any]:
    """Build the reply plan for a first client requirement email."""
    extracted = dict(extracted or {})
    latest = _strip_quoted_history(message)
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

    # Tentative fields the client has explicitly left open.
    tentative: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", latest):
        if _TENTATIVE_RE.search(sentence):
            for label, pattern in _TENTATIVE_FIELDS:
                if pattern.search(sentence) and label not in tentative:
                    tentative.append(label)

    missing: List[Dict[str, str]] = []
    if "lab" in kinds and not cloud_label:
        missing.append({"key": "cloud", "question": "The preferred cloud platform for the lab (AWS, Azure, or GCP)"})
    if not participants_known and "participant count" not in tentative and (
        "lab" in kinds or "commercials" in kinds or batch == "proposal"
    ):
        missing.append({"key": "participants", "question": "The number of participants"})
    if batch == "proposal":
        if not _clean(extracted.get("audience_level")):
            missing.append({"key": "audience", "question": "The experience level of the participants"})
        has_dates = any(_clean(extracted.get(key)) for key in ("training_dates", "preferred_dates", "timeline_start"))
        if not has_dates and "dates" not in tentative and not _dates(latest):
            missing.append({"key": "dates", "question": "The preferred training dates"})
        has_duration = bool(training_days or _positive_int(extracted.get("duration_hours")))
        if not has_duration and "duration" not in tentative:
            missing.append({"key": "duration", "question": "The expected duration"})
        if not _mode(latest, extracted) and not _MODE_RE.search(latest) and "delivery mode" not in tentative:
            missing.append({"key": "mode", "question": "The delivery mode (online or offline)"})
        missing = missing[:4]

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
    ordered += [item for item in items if item["kind"] not in {"trainer", "availability", "proposal"}]

    return {
        "engine": "reply_precheck_v1",
        "batch_type": batch,
        "greeting": greeting,
        "client_name": name,
        "technology": _technology(extracted),
        "training_days": training_days,
        "mode": _mode(latest, extracted),
        "items": ordered,
        "trainer_requested": bool(trainer_item) or batch == "confirmed" or "proposal" in kinds or not items,
        "cv_requested": bool(trainer_item and re.search(r"\b(?:cv|resume)s?\b", trainer_item["text"], re.I)),
        "availability_requested": "availability" in kinds,
        "lab": {"requested": bool(lab_item), "days": lab_days, "hours": _lab_hours(latest, extracted, lab_text),
                "cloud": cloud_label},
        "missing": missing,
        "conflicts": conflicts,
        "tentative": tentative,
        "signature": SIGNATURE,
    }


def _deliverable_lines(plan: Dict[str, Any]) -> List[str]:
    confirmed = plan["batch_type"] == "confirmed"
    days = plan.get("training_days") or 0
    lab = plan.get("lab") or {}
    lines: List[str] = []
    for item in plan.get("items") or []:
        kind = item["kind"]
        if kind == "trainer":
            continue
        if kind == "toc":
            if confirmed:
                lines.append(f"A detailed day-wise ToC for the {days}-day program" if days else "A detailed day-wise ToC")
            else:
                lines.append(f"A proposed course outline for the {days}-day program" if days else "A proposed course outline")
        elif kind == "lab":
            cloud = f"{lab['cloud']} " if lab.get("cloud") else ""
            if lab.get("days") and lab.get("hours"):
                lines.append(f"A separate {cloud}lab cost for {lab['days']} days at {lab['hours']} hours of hands-on lab per day")
            elif lab.get("hours"):
                lines.append(f"A separate {cloud}lab cost for {lab['hours']} hours of hands-on lab per day")
            elif lab.get("days"):
                lines.append(f"A separate {cloud}lab cost for {lab['days']} days")
            else:
                lines.append(f"A separate {cloud}lab-cost estimate")
        elif kind == "commercials":
            lines.append("The commercial details" if confirmed else "The commercials for the program")
        elif kind == "other":
            text = item["text"]
            lines.append(text[:1].upper() + text[1:])
    return lines


def _trainer_sentence(plan: Dict[str, Any]) -> str:
    technology = plan.get("technology") or ""
    trainer = f"{technology} trainer" if technology else "trainer"
    what = "the trainer profile and updated CV" if plan.get("cv_requested") else "the trainer profile"
    if plan.get("availability_requested"):
        what += " along with the trainer's availability"
    return (
        f"We are identifying a suitable {trainer} with relevant hands-on experience for this program, "
        f"and we will share {what} with you as soon as possible."
    )


def _batch_description(plan: Dict[str, Any]) -> str:
    parts = []
    if plan.get("training_days"):
        parts.append(f"{plan['training_days']}-day")
    if plan.get("mode"):
        parts.append(plan["mode"])
    if plan.get("technology"):
        parts.append(plan["technology"])
    return " ".join(parts + ["training batch"])


def render_plan_reply(plan: Dict[str, Any]) -> str:
    """Write the complete reply from the plan, without any LLM call."""
    confirmed = plan["batch_type"] == "confirmed"
    paragraphs: List[str] = [plan["greeting"]]
    deliverables = _deliverable_lines(plan)
    questions = [entry["question"] for entry in plan.get("missing") or []]
    questions += [entry["question"] for entry in plan.get("conflicts") or []]

    if confirmed:
        paragraphs.append(f"Thank you for sharing the confirmed requirement for the {_batch_description(plan)}.")
        paragraphs.append(_trainer_sentence(plan))
        if deliverables:
            paragraphs.append("Along with the profile, we will share:\n" + "\n".join(
                f"{index}. {line}" for index, line in enumerate(deliverables, 1)
            ))
        if questions:
            kinds = [item["kind"] for item in plan.get("items") or []]
            names = [name for kind, name in (("toc", "ToC"), ("lab", "lab cost")) if kind in kinds]
            target = f"the {_join(names)}" if names else "the details"
            paragraphs.append(f"To finalize {target}, could you please confirm:\n" + "\n".join(
                f"\u2022 {question}" for question in questions
            ))
            paragraphs.append(
                "Once we receive these details, we will share everything for your review "
                "and move ahead with the trainer confirmation."
            )
        else:
            paragraphs.append("We will share everything for your review and move ahead with the trainer confirmation.")
    else:
        technology = plan.get("technology")
        paragraphs.append(
            f"Thank you for considering Clahan Technologies for your {technology} training program."
            if technology else "Thank you for considering Clahan Technologies for your training program."
        )
        trainer_line = f"Suitable {technology} trainer profiles" if technology else "Suitable trainer profiles"
        if plan.get("availability_requested"):
            trainer_line += " with their availability"
        contents = [trainer_line] + deliverables
        if len(contents) == 1:
            contents += ["A proposed course outline", "The commercials for the program"]
        paragraphs.append("We would be glad to prepare a proposal for your review, including:\n" + "\n".join(
            f"{index}. {line}" for index, line in enumerate(contents, 1)
        ))
        tentative = plan.get("tentative") or []
        if tentative:
            paragraphs.append(f"We have noted that the {_join(tentative)} {'is' if len(tentative) == 1 else 'are'} "
                              "still to be confirmed.")
        if questions:
            paragraphs.append("To make the proposal match your needs, could you please share, if available:\n" + "\n".join(
                f"\u2022 {question}" for question in questions
            ))
        if questions or tentative:
            paragraphs.append("Once these details are available, we will share a complete proposal for your review.")
        else:
            paragraphs.append("We will share the complete proposal for your review.")

    paragraphs.append(plan.get("signature") or SIGNATURE)
    return "\n\n".join(paragraphs)


def plan_writing_guidance() -> str:
    """Writing rules for plan-based replies. They replace the short-reply rules."""
    return (
        "Write as Annapurna U. of Clahan Technologies, a polite and professional training coordinator. "
        "Use complete, well-formed sentences and a warm, respectful tone. "
        "Follow the personalization checklist exactly: keep its order and include every listed item, question, and conflict. "
        "Use a short numbered list for deliverables and a short bullet list for questions. "
        "Keep the body between 70 and 180 words, excluding the greeting and signature. "
        "Do not repeat the whole requirement back to the client. "
        "Never mention internal workflow, trainer rates, trainer shares, margins, uplift, or percentages. "
        "Do not claim anything is attached, ready, or already sent. "
        "Do not promise a specific date or deadline; 'as soon as possible' is allowed for the trainer profile. "
        "Write exactly one email. Start with the greeting from the checklist and end with the signature from the checklist. "
    )


def plan_prompt(plan: Dict[str, Any]) -> str:
    """The checklist given to the single LLM call."""
    lines = [
        "PERSONALIZATION CHECKLIST (authoritative, follow exactly):",
        f"- Batch type: {plan['batch_type']}."
        + (" The client has committed to this training; reply with commitment and focus on delivery."
           if plan["batch_type"] == "confirmed"
           else " The client is exploring; offer a proposal and do not treat open details as confirmed."),
        f"- Open with exactly: {plan['greeting']}",
        "- The client's main need is a trainer. Right after the thank-you, commit to the trainer: "
        + (_trainer_sentence(plan) if plan["batch_type"] == "confirmed"
           else "we will propose suitable trainer profiles that match the scope."),
    ]
    deliverables = _deliverable_lines(plan)
    if deliverables:
        lines.append("- Then list these deliverables in this order as a numbered list:")
        lines += [f"  {index}. {line}" for index, line in enumerate(deliverables, 1)]
    if plan.get("tentative"):
        lines.append(f"- Acknowledge that the {_join(plan['tentative'])} are still to be confirmed; do not ask for them.")
    questions = [entry["question"] for entry in plan.get("missing") or []]
    conflicts = [entry["question"] for entry in plan.get("conflicts") or []]
    if questions:
        lines.append("- Politely ask for these missing details as bullets:")
        lines += [f"  \u2022 {question}" for question in questions]
    if conflicts:
        lines.append("- Politely ask the client to confirm these points from their email as bullets:")
        lines += [f"  \u2022 {question}" for question in conflicts]
    lines.append("- Ask nothing else. Do not ask for details already in the email.")
    lines.append(
        "- Close with one sentence about the next step: "
        + ("we will share everything for review and move ahead with the trainer confirmation."
           if plan["batch_type"] == "confirmed" else "we will share a complete proposal for review.")
    )
    lines.append("- End with this signature exactly:\n" + (plan.get("signature") or SIGNATURE))
    lines.append("\nA correct reference reply follows. Improve its wording naturally for this client, "
                 "keeping every item, question, and conflict:\n" + render_plan_reply(plan))
    return "\n".join(lines)


def finalize_plan_reply(generated: str, plan: Dict[str, Any]) -> str:
    """Put the plan's greeting and signature around a generated body."""
    text = str(generated or "").replace("\r\n", "\n").strip()
    text = re.sub(r"^subject:[^\n]*\n+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:dear|hello|hi|hey)\b[^\n]{0,80}\n+", "", text, flags=re.IGNORECASE).strip()
    lines = text.split("\n")
    cut = len(lines)
    for index, line in enumerate(lines):
        if _SIGNOFF_RE.match(line.strip()):
            cut = index
            break
    body = "\n".join(lines[:cut]).rstrip()
    body = re.sub(r"(?:\n\s*)+(?:Annapurna U\.?|Clahan Technologies)\s*$", "", body).rstrip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if not body:
        return ""
    return f"{plan['greeting']}\n\n{body}\n\n{plan.get('signature') or SIGNATURE}"


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
            "duration": r"duration",
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
    if _DEADLINE_RE.search(text):
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
    }
