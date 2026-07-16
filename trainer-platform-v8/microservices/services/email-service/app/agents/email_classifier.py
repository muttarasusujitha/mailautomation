"""Deterministic email classifier for inbox automation.

The classifier is intentionally regex/keyword based: fast, free, and predictable.
It decides who sent the mail, what scenario it represents, and whether an
automatic reply is safe.
"""
import re
from typing import Any, Dict, Iterable, List, Tuple


PERSON_TYPES = {
    "corporate_client",
    "trainer",
    "job_seeker",
    "vendor",
    "referral",
    "student",
    "government",
    "media",
    "finance_legal",
    "partner",
    "internal_team",
    "system",
    "bounce",
    "ooo",
    "unknown",
}

SAFETY_SCENARIOS = {
    "ooo",
    "bounce",
    "legal_notice",
    "fraud_security",
    "system_notification",
    "cancellation",
    "angry_complaint",
    "critical_escalation",
}


SCENARIO_KEYWORDS: List[Tuple[str, Iterable[str]]] = [
    ("ooo", ("out of office", "automatic reply", "auto-reply", "vacation responder", "away from office")),
    ("bounce", ("delivery status notification", "undeliverable", "mail delivery failed", "address not found", "mailer-daemon")),
    ("legal_notice", ("legal notice", "lawyer", "advocate", "court", "breach", "lawsuit", "liable", "litigation")),
    ("fraud_security", ("fraud", "phishing", "unauthorized", "security alert", "password reset", "otp", "verification code")),
    ("system_notification", ("noreply", "no-reply", "do not reply", "donotreply", "notification", "alert")),
    ("cancellation", ("cancel", "cancelled", "canceled", "call off", "not going ahead", "drop this requirement")),
    ("reschedule", ("reschedule", "postpone", "prepone", "change the date", "change timing", "new schedule")),
    ("client_updates_requirement", ("updated requirement", "revised requirement", "updated details", "revised details", "please update", "correction", "change in requirement")),
    ("quote_request", ("quote", "quotation", "commercial proposal", "pricing", "cost estimate", "commercials")),
    ("new_training_requirement", ("looking for", "need", "requirement", "trainer", "training", "workshop", "instructor")),
    ("client_sent_details", ("please find the training", "training duration", "preferred dates", "participant count", "budget")),
    ("client_asks_profiles", ("share suitable", "trainer profiles", "profiles for review", "availability and commercials")),
    ("trainer_interested", ("i am interested", "interested for this", "available for this", "can take this training")),
    ("trainer_unavailable", ("not available", "unavailable", "occupied", "not possible", "cannot take")),
    ("trainer_more_details", ("share more details", "client details", "duration", "topics", "mode", "schedule")),
    ("trainer_credentials_sent", (
        "attached profile",
        "updated profile",
        "resume attached",
        "credentials",
        "linkedin",
        "total years of experience",
        "trainings conducted",
        "relevant certifications",
        "certifications",
    )),
    ("trainer_commercials_sent", (
        "my commercials",
        "commercials are",
        "commercial charges",
        "expected commercial",
        "rate is",
        "fee is",
        "fees are",
        "charges per day",
        "per day",
        "per session",
    )),
    ("trainer_slots_sent", (
        "slots",
        "available slots",
        "interview slots",
        "can connect",
        "schedule a call",
        "availability",
        "full-day",
        "half-day",
    )),
    ("job_application", ("applying for", "job application", "resume", "cv", "opening", "role", "position")),
    ("vendor_hotlist", ("hotlist", "bench", "available resources", "consultants available", "vendor")),
    ("referral", ("referred", "reference", "referral", "recommended by")),
    ("student_enquiry", ("course fee", "student", "learn", "training course", "enroll", "placement")),
    ("government_enquiry", ("government", "department", "tender", "rfp", "empanelment", "public sector")),
    ("media_enquiry", ("media", "press", "interview", "publication", "article")),
    ("finance_legal", ("invoice", "payment", "gst", "tax", "po", "purchase order", "agreement", "contract")),
    ("partnership", ("partnership", "collaboration", "tie-up", "alliance")),
]


def _text(*parts: Any) -> str:
    return re.sub(r"\s+", " ", " ".join(str(part or "") for part in parts)).strip().lower()


def _keyword_found(text: str, needle: str) -> bool:
    needle = str(needle or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9\s\-/]*[a-z0-9]", needle):
        pattern = re.escape(needle).replace(r"\ ", r"\s+")
        words = re.findall(r"[a-z0-9]+", needle)
        last_word = words[-1] if words else ""
        plural = "s?" if len(last_word) > 3 and not last_word.endswith("s") else ""
        return bool(re.search(rf"(?<![a-z0-9]){pattern}{plural}(?![a-z0-9])", text))
    return needle in text


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(_keyword_found(text, needle) for needle in needles)


def _score(text: str, needles: Iterable[str]) -> int:
    return sum(1 for needle in needles if _keyword_found(text, needle))


def _person_type(sender_email: str, text: str) -> str:
    email = (sender_email or "").lower()
    local = email.split("@", 1)[0] if "@" in email else email
    domain = email.split("@", 1)[1] if "@" in email else ""

    if local in {"mailer-daemon", "postmaster"} or "delivery status notification" in text:
        return "bounce"
    if (
        local in {"support", "notification", "notifications", "security", "system"}
        or local.startswith(("no-reply", "noreply", "donotreply", "do-not-reply", "support", "notification"))
        or domain.endswith(("facebookmail.com", "whatsapp.com", "instagram.com"))
    ):
        return "system"
    if "out of office" in text or "automatic reply" in text:
        return "ooo"
    if domain.endswith(("clahantech.com", "calhantech.com")):
        return "internal_team"
    if _contains_any(text, ("invoice", "payment", "gst", "contract", "agreement", "legal notice")):
        return "finance_legal"
    trainer_signals = (
        "my profile",
        "updated profile",
        "attached profile",
        "my commercials",
        "commercials are",
        "commercial charges",
        "expected commercial",
        "i am available",
        "i am interested",
        "available for this",
        "can take this training",
        "total years of experience",
        "trainings conducted",
        "relevant training experience",
        "relevant certifications",
        "preferred training mode",
    )
    if _contains_any(text, trainer_signals):
        return "trainer"
    if _contains_any(text, ("resume", "cv", "job application", "position", "opening")):
        return "job_seeker"
    if _contains_any(text, ("hotlist", "bench", "vendor", "available resources")):
        return "vendor"
    if _contains_any(text, ("student", "course fee", "enroll", "placement")):
        return "student"
    if _contains_any(text, ("government", "department", "tender", "rfp")):
        return "government"
    if _contains_any(text, ("press", "media", "publication", "article")):
        return "media"
    if _contains_any(text, ("trainer", "training", "workshop", "profiles", "requirement")):
        return "corporate_client"
    return "unknown"


def _scenario(text: str) -> Tuple[str, List[str]]:
    scores = [(name, _score(text, words)) for name, words in SCENARIO_KEYWORDS]
    scores = [(name, score) for name, score in scores if score > 0]
    if not scores:
        return "general_enquiry", []
    scores.sort(key=lambda item: item[1], reverse=True)
    best = scores[0][0]
    matched = [name for name, score in scores[:8]]
    if "legal_notice" in matched:
        best = "legal_notice"
    elif "fraud_security" in matched:
        best = "fraud_security"
    elif "bounce" in matched:
        best = "bounce"
    elif "ooo" in matched:
        best = "ooo"
    elif "client_sent_details" in matched:
        best = "client_sent_details"
    elif "client_updates_requirement" in matched:
        best = "client_updates_requirement"
    elif "client_asks_profiles" in matched:
        best = "client_asks_profiles"
    return best, matched


def _urgency(text: str) -> str:
    if _contains_any(text, ("critical", "immediately", "asap", "panic", "urgent urgent", "escalation")):
        return "critical"
    if _contains_any(text, ("urgent", "earliest", "priority", "today", "tomorrow")):
        return "high"
    if _contains_any(text, ("whenever possible", "no rush", "low priority")):
        return "low"
    return "normal"


def _sentiment(text: str) -> str:
    if _contains_any(text, ("furious", "angry", "unacceptable", "legal action", "escalate")):
        return "angry"
    if _contains_any(text, ("frustrated", "disappointed", "not happy", "delay", "issue")):
        return "frustrated"
    if _contains_any(text, ("thank", "thanks", "appreciate", "looking forward", "please")):
        return "positive"
    return "neutral"


def classify_email(subject: str = "", body: str = "", sender_email: str = "", sender_name: str = "") -> Dict[str, Any]:
    """Classify a single email for deterministic automation."""
    text = _text(subject, body, sender_email, sender_name)
    person_type = _person_type(sender_email, text)
    scenario, matched = _scenario(text)
    if person_type == "trainer":
        trainer_detail_matches = {
            "trainer_credentials_sent",
            "trainer_commercials_sent",
            "trainer_slots_sent",
        } & set(matched)
        if "trainer_unavailable" in matched:
            scenario = "trainer_unavailable"
        elif len(trainer_detail_matches) >= 2:
            scenario = "trainer_details_sent"
        else:
            for trainer_scenario in (
                "trainer_commercials_sent",
                "trainer_slots_sent",
                "trainer_credentials_sent",
                "trainer_interested",
                "trainer_more_details",
            ):
                if trainer_scenario in matched:
                    scenario = trainer_scenario
                    break
    urgency = _urgency(text)
    sentiment = _sentiment(text)

    requires_human = (
        scenario in SAFETY_SCENARIOS
        or urgency == "critical"
        or sentiment in {"angry", "frustrated"}
    )
    auto_reply_allowed = not requires_human and person_type not in {"bounce", "system", "ooo"}
    confidence = 0.25
    if scenario != "general_enquiry":
        confidence = 0.72 + min(0.18, max(0, len(matched) - 1) * 0.03)
    if requires_human:
        confidence = max(confidence, 0.95)

    return {
        "person_type": person_type,
        "scenario": scenario,
        "urgency": urgency,
        "sentiment": sentiment,
        "requires_human": requires_human,
        "auto_reply_allowed": auto_reply_allowed,
        "safety_reasons": [
            reason for reason in (scenario if scenario in SAFETY_SCENARIOS else "", urgency if urgency == "critical" else "", sentiment if sentiment in {"angry", "frustrated"} else "")
            if reason
        ],
        "confidence": round(min(confidence, 0.99), 2),
        "matched_scenarios": matched,
    }
