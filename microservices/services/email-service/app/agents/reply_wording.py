"""Approved wording alternatives shared by template and AI email writing.

Only matched coordination sentences change. Names, links, commercial terms,
attachments, detailed answers and approval decisions remain in the reference.
"""
import hashlib
import re
from difflib import SequenceMatcher
from email.utils import parseaddr

from app.agents.natural_voice import is_professional_requirement_thanks


# Every family has ten options. Captured fields are copied verbatim, never
# inferred from another customer's email or from a writing example.
WORDING_BANKS = {
    "details_received": (
        r"Thank you for sharing (?P<detail>[^.!?\n]+)\.",
        (
            "Thanks for sharing {detail}.",
            "We've received {detail}.",
            "Thank you for sending {detail}.",
            "Thanks, we've received {detail}.",
            "We've received {detail}; thank you.",
            "Thanks for sending {detail} through.",
            "Thank you. We've received {detail}.",
            "We've noted {detail}.",
            "Thanks, we've noted {detail}.",
            "Thank you for passing along {detail}.",
        ),
    ),
    "confirmation_received": (
        r"Thank you for confirming (?P<detail>(?!that\b)[^.!?\n]+)\.",
        (
            "Thanks for confirming {detail}.",
            "We've noted your confirmation of {detail}.",
            "Thank you. We've noted your confirmation of {detail}.",
            "Thanks, your confirmation of {detail} is noted.",
            "We've received your confirmation of {detail}.",
            "Thank you for the confirmation of {detail}.",
            "Thanks for getting back to us about {detail}.",
            "Your confirmation of {detail} is noted, thank you.",
            "Thanks. We've received your confirmation of {detail}.",
            "Thank you for confirming the details regarding {detail}.",
        ),
    ),
    "update_received": (
        r"Thank you for (?:the update|your message|your email|your response)\.",
        (
            "Thanks for the update.", "We've received your message.",
            "Thanks for letting us know.", "Your update is noted.",
            "Thanks for getting back to us.", "We've noted your message.",
            "Thank you for keeping us informed.", "Thanks, we've noted the update.",
            "Your message has reached us, thank you.", "Thank you for the information.",
        ),
    ),
    "missing_details": (
        r"To help us refine the shortlist, please share:",
        (
            "Could you share these remaining details?",
            "We still need the following to refine the shortlist:",
            "Please send the remaining details below:",
            "To narrow down the trainer options, could you confirm:",
            "These details will help us refine the shortlist:",
            "Could you help with the following details?",
            "Please fill in these remaining points:",
            "To refine the trainer options, we need:",
            "Could you send us the missing information below?",
            "Please confirm these points so we can refine the shortlist:",
        ),
    ),
    "availability_check": (
        r"We will check this against the client schedule and update you on the next step\.",
        (
            "We'll check these times against the client's schedule and get back to you.",
            "We'll compare your availability with the client's schedule, then confirm the next step.",
            "We'll check whether these times work for the client and update you.",
            "We'll review the client's schedule alongside yours and get back to you.",
            "We'll check the schedule with the client before confirming the next step.",
            "We'll see how your availability fits the client's schedule and let you know.",
            "We'll match these times against the client's schedule and follow up.",
            "We'll review the timing with the client and come back with the next step.",
            "We'll check the client's schedule for these times and respond with an update.",
            "We'll compare both schedules and update you on what comes next.",
        ),
    ),
    "reschedule_request": (
        r"Please share 2-3 alternate slots if not already shared\.",
        (
            "If you haven't already, please send 2-3 alternative slots.",
            "Could you send 2-3 other slots, unless you've already shared them?",
            "Please suggest 2-3 alternative times if those aren't already in the thread.",
            "If you haven't sent alternatives yet, 2-3 slots would help.",
            "Please share 2-3 replacement slots if you haven't done so yet.",
            "Could you provide 2-3 alternative slots if they're still outstanding?",
            "If alternative slots haven't been shared, please suggest 2-3.",
            "Please send 2-3 other possible slots if you haven't already.",
            "If needed, could you add 2-3 alternative slots to this thread?",
            "Unless you've already sent them, please suggest 2-3 other times.",
        ),
    ),
    "toc_review": (
        r"We will review it and share it with the client for confirmation\.",
        (
            "We'll review it, then send it to the client for confirmation.",
            "We'll check it and share it with the client for confirmation.",
            "We'll review it before asking the client to confirm.",
            "We'll check it and pass it to the client for confirmation.",
            "After reviewing it, we'll share it with the client for confirmation.",
            "We'll go through it and ask the client to confirm it.",
            "We'll review it first, then seek the client's confirmation.",
            "We'll check it before sending it to the client for confirmation.",
            "We'll review what you've sent and forward it for the client's confirmation.",
            "We'll review it and follow up with the client for confirmation.",
        ),
    ),
    "commercial_review": (
        r"We will review internally and update you if there is scope for revision\.",
        (
            "We'll review this internally and let you know if a revision is possible.",
            "We'll check whether there's room for a revision and update you if there is.",
            "We'll review the position internally and get back to you if it can change.",
            "We'll check this with our team and update you if a revision is possible.",
            "If an internal review allows a revision, we'll let you know.",
            "We'll review the scope for a change and update you if one is possible.",
            "We'll check internally whether this can be revised and respond if it can.",
            "We'll look into a possible revision internally and let you know if there is room.",
            "We'll review this with the team and update you if we can revise it.",
            "We'll consider the scope for revision internally and follow up if it is possible.",
        ),
    ),
    "brief_thanks": (
        r"You're welcome\.",
        (
            "You're welcome.", "You're very welcome.", "Happy to help.",
            "Glad to help.", "It's a pleasure.", "You are welcome.",
            "Of course, you're welcome.", "My pleasure.",
            "Always glad to help.", "A pleasure to help.",
        ),
    ),
    "invoice_status": (
        r"We will check the invoice status and share the invoice copy/update shortly\.",
        (
            "We'll check the invoice status and send the copy or an update shortly.",
            "We'll confirm the invoice status and share a copy or update shortly.",
            "We'll review the invoice status and get back to you shortly with the copy or an update.",
            "We'll check where the invoice stands and share the copy or an update shortly.",
            "We'll look into the invoice status and send a copy or update shortly.",
            "We'll verify the invoice status, then send the copy or an update shortly.",
            "We'll check the status of the invoice and follow up shortly with the copy or an update.",
            "We'll review the status and share the invoice copy or an update shortly.",
            "We'll check the invoice and respond shortly with its copy or a status update.",
            "We'll check the invoice's status before sharing a copy or update shortly.",
        ),
    ),
    "meeting_preparation": (
        r"Check your microphone, speakers, and internet connection before joining\.",
        (
            "Please check your microphone, speakers, and internet connection before joining.",
            "Before you join, check your microphone, speakers, and internet connection.",
            "Please test your microphone, speakers, and internet connection before the call.",
            "Make sure your microphone, speakers, and internet connection work before joining.",
            "Give your microphone, speakers, and internet connection a quick check before joining.",
            "Before joining the call, please test your microphone, speakers, and internet connection.",
            "Check that your microphone, speakers, and internet connection are working before you join.",
            "Please make sure your microphone, speakers, and internet connection are ready before joining.",
            "Test your microphone, speakers, and internet connection before you enter the meeting.",
            "Before entering the meeting, check your microphone, speakers, and internet connection.",
        ),
    ),
    "join_or_reschedule": (
        r"Please join now if you are available\. If you need to reschedule, reply with your preferred date and time zone\.",
        (
            "If you're available, please join now. To reschedule, reply with your preferred date and time zone.",
            "Please join if you can. If a new date is needed, reply with your preferred date and time zone.",
            "You can join now if you're available. Otherwise, if you need to reschedule, send your preferred date and time zone.",
            "If you can attend, please join now. If you need another date, reply with that date and your time zone.",
            "Please join now if possible. For a reschedule, let us know your preferred date and time zone.",
            "Join now if you're free. If you'd like to reschedule, please reply with your preferred date and time zone.",
            "If you're free, please join the meeting now. For a different date, send your preference and time zone.",
            "Please join the meeting if you're available. If rescheduling is needed, reply with your preferred date and time zone.",
            "If you can join now, please do. To arrange another date, reply with your preferred date and time zone.",
            "Please join now if you can attend. If you need to move the meeting, send your preferred date and time zone.",
        ),
    ),
}


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _rank_options(options, recent_replies, seed):
    history = [_norm(item) for item in recent_replies]
    normalized_options = {_norm(option) for option in options}
    used_by_message = []
    for text in history:
        matches = {option for option in normalized_options if option in text}
        # 'Glad to help.' inside 'Always glad to help.' is one use of the
        # longer option, not a use of both alternatives.
        used_by_message.append({option for option in matches
                                if not any(option != other and option in other for other in matches)})
    def score(option):
        normalized = _norm(option)
        # Most recent messages appear first. Prefer unused wording, then the
        # least recently used option after all ten have appeared.
        reuse = sum(len(history) - index for index, used in enumerate(used_by_message) if normalized in used)
        tie = hashlib.sha256(f"{seed}:{option}".encode()).hexdigest()
        return reuse, tie
    return sorted(options, key=score)


def wording_choices(body, recent_replies=(), seed=""):
    for family, (pattern, variants) in WORDING_BANKS.items():
        # Never rewrite a quotation, factual clause, or text inside a URL.
        bounded = rf"(^|(?<=[.!?])\s+)({pattern})(?=\s|$)"
        for match in re.finditer(bounded, body, flags=re.MULTILINE):
            # The ten professional requirement notes already vary by version.
            # Do not fold their "Thank you for sharing the {technology} ..."
            # opening back into "Thanks for sharing".
            if family == "details_received" and is_professional_requirement_thanks(match.group(2)):
                continue
            options = [variant.format(**match.groupdict()) for variant in variants]
            yield family, match, _rank_options(options, recent_replies, f"{seed}:{family}")


def vary_template(body, recent_replies=(), seed=""):
    body = str(body or "")
    replacements = [(match.start(2), match.end(2), options[0])
                    for _, match, options in wording_choices(body, recent_replies, seed)]
    for start, end, replacement in sorted(replacements, reverse=True):
        body = body[:start] + replacement + body[end:]
    return body


def ai_wording_examples(body, recent_replies=(), seed=""):
    """At most three short alternatives grounded in this exact reference."""
    examples = []
    for family, match, options in wording_choices(str(body or ""), recent_replies, seed):
        examples.append({"situation": family, "reference": match.group(2), "alternative": options[0]})
        if len(examples) == 3:
            break
    return examples


def repeats_recent(body, recent_replies):
    """Catch near-identical prose; brief acknowledgements may legitimately recur."""
    def prose(text):
        lines = str(text or "").splitlines()
        kept = []
        for line in lines:
            if re.fullmatch(
                r"(?:thanks(?: and|&) )?(?:(?:best|kind|warm) )?regards,?|thanks,?|thank you,?|sincerely,?",
                line.strip(),
                re.I,
            ):
                break
            if re.fullmatch(r"(?:hi|dear|hello)(?: [^.!?]{1,70})?[,!]", line.strip(), re.I):
                continue
            if _norm(line) not in {
                "clahan technologies", "recruitment team", "murali mohan m", "murali mohan",
                "annapurna u.", "annapurna u", "annapurna.", "annapurna",
            }:
                kept.append(line)
        return _norm(" ".join(kept))
    draft = prose(body)
    if len(draft.split()) < 12:
        return False
    return any(SequenceMatcher(None, draft, prose(previous)).ratio() >= 0.92 for previous in recent_replies)


async def recent_sent_replies(db, recipient, limit=10):
    """Read only successfully sent messages to this exact recipient."""
    address = (parseaddr(str(recipient or ""))[1] or str(recipient or "")).strip().lower()
    if not address:
        return []
    exact_address = {"$regex": f"^{re.escape(address)}$", "$options": "i"}
    try:
        cursor = db["email_logs"].find(
            {"direction": "outbound", "status": "sent",
             "$or": [{"to_email": exact_address}, {"recipient": exact_address}]},
            {"_id": 0, "body": 1},
        ).sort("sent_at", -1).limit(limit)
        return [str(item["body"])[:6000] async for item in cursor if item.get("body")]
    except (KeyError, AttributeError, TypeError):
        # Lightweight test stores may not provide the email-log collection.
        return []
