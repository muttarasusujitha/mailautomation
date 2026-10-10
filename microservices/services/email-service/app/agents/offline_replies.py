"""Replies from stored records when AI generation is off.

No model is called. A client requirement uses the professional acknowledgement.
A trainer question uses that trainer's record and the requirement they are on.
Money and lab defaults that belong to the other side, or only to the lab
workbook, are left out of both replies.
"""

import re
from typing import Any, Dict, List, Optional

from app.agents.natural_voice import ANNAPURNA, apply_voice, signature_for


_GENERIC_CHECKING = "Thanks for your question. We are checking the relevant training details"
_MONEY_KEYS = (
    "budget",
    "budget_total",
    "budget_per_day",
    "budget_min",
    "budget_max",
    "budget_range",
    "budget_currency",
    "client_budget_per_day",
    "client_budget",
)
_TRAINER_VISIBLE_KEYS = (
    "trainer_visible_budget_per_session",
    "trainer_requested_budget_per_session",
)
_TRAINER_OWN_KEYS = (
    "offered_commercial",
    "commercial",
    "rate",
    "trainer_rate",
    "expected_commercial",
    "commercial_per_day",
)
_SAFE_REQUIREMENT_KEYS = (
    "technology_needed",
    "technology",
    "domain",
    "topics",
    "custom_topics",
    "duration_days",
    "duration_text",
    "mode",
    "training_mode",
    "training_dates",
    "preferred_dates",
    "timing",
    "audience_level",
    "lab_hours_per_day",
    "hours_per_day",
    "requested_details",
    "clahan_managed_details",
    "needs_clarification",
    "toc_requested",
    "toc_action",
    "client_name",
    "client_email",
)
_SECRET_PHRASES = (
    re.compile(r"(?i)\b70\s*%"),
    re.compile(r"(?i)\b70\s*percent\b"),
    re.compile(r"(?i)\b0\.70\b"),
    re.compile(r"(?i)\btrainer share\b"),
    re.compile(r"(?i)training duration is not the participant count"),
    re.compile(r"(?i)not treated as the participant count"),
    re.compile(r"(?i)\bAWS Mumbai\b"),
    re.compile(r"(?i)\bfx[\s_]*rate\b"),
    re.compile(r"(?i)\bexchange rate\b"),
    re.compile(r"(?i)\b1 participant(?:s)?\b"),
    re.compile(r"(?i)\b(?:api[_ ]?key|openai[_ ]?key|sk-[A-Za-z0-9]{8,})\b"),
    re.compile(r"(?i)\b(?:mailbox|smtp|imap)\s+password\b"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _amount(value: Any) -> int:
    if value in (None, "", [], {}):
        return 0
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return 0
    try:
        amount = float(match.group(0).replace(",", ""))
    except ValueError:
        return 0
    if amount < 1000:
        return 0
    return int(round(amount))


def _money_tokens(amount: int) -> List[str]:
    if amount < 1000:
        return []
    plain = str(amount)
    grouped = f"{amount:,}"
    tokens = [plain, grouped]
    if plain.endswith("000") and len(plain) > 3:
        tokens.append(plain[:-3])
    return tokens


def _first_text(source: Dict[str, Any], keys: tuple) -> str:
    for key in keys:
        value = _text(source.get(key) if isinstance(source, dict) else "")
        if value:
            return value
    return ""


def trainer_secret_kinds(question: str) -> List[str]:
    """Categories a trainer asked for that we do not put in the reply."""
    text = _text(question).lower()
    kinds: List[str] = []
    if re.search(r"\b(?:client(?:'s|s)?\s+budget|client budget|their budget|customer(?:'s|s)?\s+budget)\b", text):
        kinds.append("the client's budget")
    if re.search(r"\b(?:other|another|second)\s+trainer\b", text):
        kinds.append("another trainer's rate")
    internal = bool(re.search(
        r"\b(?:70\s*%|70\s*percent|0\.70|trainer share)\b",
        text,
    )) or bool(re.search(
        r"\b(?:fx[\s_]*rate|exchange rate|aws mumbai|internal (?:lab )?default|"
        r"mailbox password|api[_ ]?key|openai key|"
        r"not the participant count|not treated as the participant count)\b",
        text,
    ))
    if re.search(r"\b(?:default|assume|assumption|internal)\b", text) and re.search(
        r"\b(?:participant|aws mumbai|fx[\s_]*rate|exchange rate)\b", text
    ):
        internal = True
    if internal:
        kinds.append("internal defaults")
    return kinds


def client_secret_kinds(question: str) -> List[str]:
    """Categories a client asked for that we do not put in the reply."""
    text = _text(question).lower()
    kinds: List[str] = []
    if re.search(r"\b(?:trainer(?:'s|s)?\s+(?:rate|commercial|charge|fee)|other trainer|another trainer)\b", text):
        kinds.append("the trainer's rate")
    if re.search(r"\b(?:other|another)\s+client(?:'s|s)?\s+budget\b", text):
        kinds.append("another client's budget")
    kinds.extend(kind for kind in trainer_secret_kinds(question) if kind not in kinds and kind != "the client's budget")
    return kinds


def _refusal_sentence(kinds: List[str]) -> str:
    items = list(dict.fromkeys(kinds))
    if not items:
        return ""
    if len(items) == 1:
        return f"We cannot share {items[0]}."
    if len(items) == 2:
        return f"We cannot share {items[0]} or {items[1]}."
    return "We cannot share " + ", ".join(items[:-1]) + f", or {items[-1]}."


def _is_generic_checking_reply(reply: Optional[Dict[str, Any]]) -> bool:
    body = _text((reply or {}).get("body"))
    return _GENERIC_CHECKING in body or "will share a confirmed response shortly" in body


def _client_budget_amounts(requirement: Dict[str, Any]) -> List[int]:
    amounts = []
    for key in _MONEY_KEYS:
        amount = _amount(requirement.get(key) if isinstance(requirement, dict) else None)
        if amount and amount not in amounts:
            amounts.append(amount)
    return amounts


def _other_trainer_amounts(shortlist: Dict[str, Any], trainer_id: str) -> List[int]:
    amounts = []
    for other in (shortlist or {}).get("top_trainers") or []:
        if not isinstance(other, dict):
            continue
        if _text(other.get("trainer_id")) == _text(trainer_id):
            continue
        for key in _TRAINER_VISIBLE_KEYS + _TRAINER_OWN_KEYS + _MONEY_KEYS:
            amount = _amount(other.get(key))
            if amount and amount not in amounts:
                amounts.append(amount)
    return amounts


def trainer_offered_amount(trainer: Dict[str, Any], requirement: Dict[str, Any]) -> int:
    """The commercial already shown to this trainer, not a figure derived here."""
    for source, keys in (
        (requirement, _TRAINER_VISIBLE_KEYS),
        (trainer, _TRAINER_OWN_KEYS),
    ):
        if not isinstance(source, dict):
            continue
        for key in keys:
            amount = _amount(source.get(key))
            if amount:
                return amount
    return 0


def _is_signature_paragraph(paragraph: str) -> bool:
    first = paragraph.strip().splitlines()[0].strip() if paragraph.strip() else ""
    return bool(re.match(r"(?i)thanks(?: and regards)?,?$", first))


def _sentence_leaks_secret(sentence: str, forbidden_tokens: List[str]) -> bool:
    if sentence.lower().startswith("we cannot share"):
        return False
    if any(pattern.search(sentence) for pattern in _SECRET_PHRASES):
        return True
    if re.search(r"(?i)\bclient(?:'s|s)?\s+budget\b", sentence) and not sentence.lower().startswith("we cannot share"):
        return True
    return bool(forbidden_tokens and any(
        re.search(rf"(?<!\d){re.escape(token)}(?!\d)", sentence) for token in forbidden_tokens
    ))


def _drop_secret_sentences(body: str, forbidden_amounts: List[int], allowed_amounts: List[int]) -> str:
    allowed = {amount for amount in allowed_amounts if amount >= 1000}
    forbidden_tokens: List[str] = []
    for amount in forbidden_amounts:
        if amount in allowed:
            continue
        forbidden_tokens.extend(_money_tokens(amount))
    kept: List[str] = []
    for paragraph in str(body or "").split("\n\n"):
        if not paragraph.strip():
            continue
        if _is_signature_paragraph(paragraph):
            kept.append(paragraph.strip())
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
        safe_sentences = [sentence for sentence in sentences if sentence and not _sentence_leaks_secret(sentence, forbidden_tokens)]
        if safe_sentences:
            kept.append(" ".join(safe_sentences))
    return "\n\n".join(kept).strip()


def guard_trainer_body(
    body: str,
    question: str,
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    shortlist: Optional[Dict[str, Any]] = None,
) -> str:
    trainer_id = _text((trainer or {}).get("trainer_id"))
    allowed = [trainer_offered_amount(trainer or {}, requirement or {})]
    forbidden = _client_budget_amounts(requirement or {}) + _other_trainer_amounts(shortlist or {}, trainer_id)
    fx = _amount((requirement or {}).get("fx_rate"))
    if fx:
        forbidden.append(fx)
    cleaned = _drop_secret_sentences(body, forbidden, allowed)
    kinds = trainer_secret_kinds(question)
    refusal = _refusal_sentence(kinds)
    if refusal and refusal not in cleaned:
        signature = signature_for(ANNAPURNA)
        if signature in cleaned:
            cleaned = cleaned.replace(signature, refusal + "\n\n" + signature, 1)
        elif cleaned:
            cleaned = cleaned + "\n\n" + refusal
        else:
            cleaned = refusal
    return apply_voice(cleaned, ANNAPURNA) if cleaned else ""


def guard_client_body(body: str, question: str, extracted: Optional[Dict[str, Any]] = None) -> str:
    """Remove secrets from a client reply without rewriting a clean acknowledgement."""
    forbidden = []
    source = extracted or {}
    for key in _TRAINER_VISIBLE_KEYS + _TRAINER_OWN_KEYS:
        amount = _amount(source.get(key))
        if amount:
            forbidden.append(amount)
    if client_secret_kinds(question) or trainer_secret_kinds(question):
        forbidden.extend(_client_budget_amounts(source))
        fx = _amount(source.get("fx_rate"))
        if fx:
            forbidden.append(fx)
    cleaned = _drop_secret_sentences(body, forbidden, [])
    if cleaned:
        return cleaned
    if any(pattern.search(body or "") for pattern in _SECRET_PHRASES):
        return ""
    return _text(body)


def _requirement_technology(requirement: Dict[str, Any]) -> str:
    return _first_text(requirement or {}, ("technology_needed", "technology", "domain")) or "training"


def _requirement_dates(requirement: Dict[str, Any]) -> str:
    return _first_text(requirement or {}, ("training_dates", "preferred_dates", "timeline_start"))


def offline_trainer_question_reply(
    question: str,
    trainer: Optional[Dict[str, Any]],
    requirement: Optional[Dict[str, Any]],
    shortlist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Short Annapurna note from the trainer record and their requirement."""
    trainer = trainer or {}
    requirement = requirement or {}
    shortlist = shortlist or {}
    name = _first_text(trainer, ("name", "trainer_name")) or "there"
    if name.lower() in {"trainer", "team", "sender"}:
        name = "there"
    technology = _requirement_technology(requirement)
    dates = _requirement_dates(requirement)
    mode = _first_text(requirement, ("mode", "training_mode", "delivery_mode"))
    offered = trainer_offered_amount(trainer, requirement)
    sentences = [f"The {technology} requirement is the one on your record."]
    if dates:
        sentences.append(f"The training dates are {dates}.")
    if mode:
        sentences.append(f"Delivery is {mode}.")
    if offered:
        sentences.append(f"Your offered commercial is INR {offered:,} per day.")
    kinds = trainer_secret_kinds(question)
    if not dates and not mode and not offered and not kinds:
        sentences.append("That point is not on the requirement record.")
    paragraphs = [f"Hi {name},", " ".join(sentences)]
    refusal = _refusal_sentence(kinds)
    if refusal:
        paragraphs.append(refusal)
    paragraphs.append(signature_for(ANNAPURNA))
    body = guard_trainer_body("\n\n".join(paragraphs), question, trainer, requirement, shortlist)
    subject_technology = technology if technology.lower() != "training" else "Training"
    return {
        "subject": f"Re: {subject_technology} Clarification",
        "body": body,
        "from_records": True,
        "template_key": "trainer_record_reply",
    }


def _client_stated_real_participant_count(message: str) -> bool:
    text = _text(message)
    if re.search(r"\b(?:default|assume|assumption|internal)\b", text, flags=re.IGNORECASE):
        return False
    return bool(re.search(r"\b\d+\s+participants?\b", text, flags=re.IGNORECASE))


def merge_client_facts(
    extracted: Optional[Dict[str, Any]],
    requirement: Optional[Dict[str, Any]] = None,
    message: str = "",
) -> Dict[str, Any]:
    """What the client just said, filled from the requirement when a fact is missing."""
    merged = dict(extracted or {})
    for key in _SAFE_REQUIREMENT_KEYS:
        if merged.get(key) in (None, "", [], {}) and (requirement or {}).get(key) not in (None, "", [], {}):
            merged[key] = requirement[key]
    for key in _MONEY_KEYS + _TRAINER_VISIBLE_KEYS + ("fx_rate", "cloud_region", "api_key", "password"):
        merged.pop(key, None)
    participants = merged.get("participant_count")
    try:
        participant_number = int(float(participants))
    except (TypeError, ValueError):
        participant_number = 0
    if participant_number == 1 and not _client_stated_real_participant_count(message):
        merged.pop("participant_count", None)
    region = _text(merged.get("cloud_region")).lower()
    if "mumbai" in region:
        merged.pop("cloud_region", None)
    return merged


def offline_client_requirement_reply(extracted: Optional[Dict[str, Any]], message: str = "") -> Dict[str, str]:
    """The professional acknowledgement already used for requirement mail."""
    from app.routes.inbox import _client_short_requirement_ack

    safe = merge_client_facts(extracted, message=message)
    reply = _client_short_requirement_ack(safe)
    body = guard_client_body(reply.get("body") or "", message, extracted or {})
    return {"subject": reply.get("subject") or "Re: Training Requirement", "body": body}


def _should_replace_trainer_reply(question: str, generated_reply: Optional[Dict[str, Any]], ai_on: bool) -> bool:
    if ai_on:
        return False
    if not _text((generated_reply or {}).get("body")):
        return True
    if (generated_reply or {}).get("from_records"):
        return False
    if "on your record" in _text((generated_reply or {}).get("body")):
        return False
    if _is_generic_checking_reply(generated_reply):
        return True
    return bool(trainer_secret_kinds(question))


def prepare_trainer_reply(
    question: str,
    generated_reply: Optional[Dict[str, Any]],
    trainer: Optional[Dict[str, Any]],
    requirement: Optional[Dict[str, Any]],
    shortlist: Optional[Dict[str, Any]] = None,
    *,
    ai_on: bool = False,
) -> Dict[str, Any]:
    """Use the record reply when AI is off and the draft is empty, generic, or unsafe."""
    reply = dict(generated_reply or {})
    if _should_replace_trainer_reply(question, reply, ai_on):
        record = offline_trainer_question_reply(question, trainer, requirement, shortlist)
        if record.get("body"):
            reply = record
    body = guard_trainer_body(reply.get("body") or "", question, trainer or {}, requirement or {}, shortlist)
    if not body:
        record = offline_trainer_question_reply(question, trainer, requirement, shortlist)
        reply = record
        body = record.get("body") or ""
    reply["body"] = body
    return reply


async def _optional_find(db: Any, collection: str, query: Dict[str, Any]) -> Dict[str, Any]:
    try:
        store = db[collection]
    except (KeyError, TypeError):
        return {}
    if store is None:
        return {}
    found = await store.find_one(query, {"_id": 0})
    return found or {}


async def trainer_reply_for_email(db: Any, email_doc: Dict[str, Any], question: str) -> Dict[str, Any]:
    from app.routes.inbox import _find_shortlist_trainer

    requirement_id = _text(email_doc.get("requirement_id"))
    trainer_id = _text(email_doc.get("trainer_id"))
    requirement = await _optional_find(db, "requirements", {"requirement_id": requirement_id}) if requirement_id else {}
    shortlist = await _optional_find(db, "shortlists", {"requirement_id": requirement_id}) if requirement_id else {}
    trainer = _find_shortlist_trainer(shortlist, trainer_id) if trainer_id else {}
    if not trainer and trainer_id:
        trainer = await _optional_find(db, "trainers", {"trainer_id": trainer_id})
    if not trainer:
        trainer = {
            "trainer_id": trainer_id,
            "name": email_doc.get("from_name") or email_doc.get("trainer_name") or "",
            "email": email_doc.get("from_email") or "",
        }
    return offline_trainer_question_reply(question, trainer, requirement, shortlist)


async def reply_for_stored_message(db: Any, email_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Pipeline reply for one stored inbound message. Does not call a model."""
    subject = email_doc.get("subject") or ""
    message = email_doc.get("classification_body") or email_doc.get("clean_body") or email_doc.get("body") or email_doc.get("raw_body") or ""
    classification = email_doc.get("email_classification") if isinstance(email_doc.get("email_classification"), dict) else {}
    extracted = dict(email_doc.get("extracted") or {}) if isinstance(email_doc.get("extracted"), dict) else {}
    if not extracted:
        from app.routes.inbox import _extract_requirement_from_email

        extracted = _extract_requirement_from_email(
            subject,
            message,
            email_doc.get("from_email") or email_doc.get("sender") or "",
            email_doc.get("from_name") or "",
        )
    extracted.setdefault("client_email", email_doc.get("from_email") or email_doc.get("sender") or "")
    extracted.setdefault("client_name", email_doc.get("from_name") or "")
    person = _text(classification.get("person_type")).lower()
    if person == "trainer" or email_doc.get("trainer_id"):
        return await trainer_reply_for_email(db, email_doc, message)

    requirement: Dict[str, Any] = {}
    requirement_id = _text(email_doc.get("requirement_id"))
    if requirement_id:
        requirement = await _optional_find(db, "requirements", {"requirement_id": requirement_id})
    elif extracted.get("client_email"):
        requirement = await _optional_find(db, "requirements", {"client_email": extracted.get("client_email")})
    merged = merge_client_facts(extracted, requirement, message)
    return offline_client_requirement_reply(merged, message)
