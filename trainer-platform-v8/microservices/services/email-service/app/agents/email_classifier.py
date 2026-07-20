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
    ("client_confirms_trainer", ("confirm this trainer", "trainer is confirmed", "we confirm the trainer", "selected this trainer", "go ahead with this trainer", "proceed with this trainer", "profile approved", "trainer approved", "shortlist approved", "looks good proceed", "please onboard this trainer")),
    ("client_rejects_trainer", ("not suitable", "reject this trainer", "not moving ahead with this trainer", "profile is rejected", "not shortlisted", "not a fit", "not aligned", "does not match", "not relevant", "profile not suitable", "trainer not suitable")),
    ("client_requests_replacement", ("replacement trainer", "alternate trainer", "another trainer", "share another profile", "different trainer", "backup trainer", "alternate profile", "more relevant trainer", "replace the trainer", "new trainer option")),
    ("client_confirms_interview_slot", ("confirm this slot", "slot is confirmed", "available for the slot", "book this slot", "schedule this slot", "confirmed for interview", "this timing works", "we are available", "please block this time", "go ahead with this slot", "slot works for us")),
    ("client_requests_interview_slots", ("share interview slots", "available slots for interview", "schedule interview", "arrange interview", "discussion slot", "interview availability", "when can we connect", "trainer discussion", "technical discussion", "evaluation call", "screening call")),
    ("client_asks_meeting_link", ("meeting link", "meet link", "google meet link", "teams link", "zoom link", "joining link", "call link", "vc link", "conference link", "link for discussion", "invite link")),
    ("client_asks_toc", ("toc", "course agenda", "agenda", "curriculum", "course outline", "training outline", "syllabus", "module list", "day wise plan", "session plan", "learning objectives", "course content")),
    ("client_sends_po", ("attached po", "po attached", "purchase order attached", "sharing po", "please find po", "po number", "find attached purchase order", "attached purchase order", "work order attached", "wo attached", "approved po")),
    ("client_asks_invoice", ("send invoice", "share invoice", "invoice status", "invoice copy", "tax invoice", "proforma invoice", "raise invoice", "billing invoice", "need invoice", "invoice format", "invoice details")),
    ("client_payment_terms", ("payment terms", "payment cycle", "credit period", "payment timeline", "advance payment", "milestone payment", "payment schedule", "payment process", "vendor payment", "billing cycle", "tds")),
    ("client_budget_negotiation", ("reduce commercials", "negotiate", "budget constraint", "too high", "lower rate", "revise quote", "best price", "discount", "fit in budget", "within budget", "commercials high", "rate is high", "price revision", "cost reduction")),
    ("client_changes_training_details", ("change duration", "change dates", "change timing", "change mode", "change participants", "updated dates", "revised schedule", "rescheduled dates", "change batch size", "change audience", "change location", "change venue", "change scope")),
    ("client_asks_final_logistics", ("final logistics", "joining instructions", "trainer details", "final confirmation", "session details", "training logistics", "trainer contact", "participant invite", "calendar invite", "session link", "pre requisites", "prerequisites")),
    ("client_asks_status_update", ("any update", "status update", "please update", "where are we", "current status", "follow up", "following up", "gentle reminder", "pending update", "waiting for update", "please revert", "revert asap")),
    ("client_asks_more_profiles", ("more profiles", "additional profiles", "more trainer profiles", "share more options", "more suitable profiles", "send more profiles", "few more trainers", "more candidates", "other options", "more choices")),
    ("client_training_completed", ("training completed", "session completed", "training is completed", "completed successfully", "feedback form", "training done", "session done", "program completed", "workshop completed", "closure")),
    ("client_feedback_shared", ("feedback", "trainer feedback", "session feedback", "participant feedback", "rating", "csat", "survey response", "feedback attached", "feedback shared")),
    ("client_escalation_delay", ("delay", "delayed", "not received", "still waiting", "no response", "pending since", "escalating", "escalation", "urgent update required")),
    ("client_cancels_requirement", ("cancel requirement", "cancel this requirement", "put on hold", "requirement on hold", "hold this", "not going ahead", "dropped", "pause this requirement")),
    ("client_reopens_requirement", ("reopen requirement", "restart requirement", "resume search", "requirement is active again", "start again", "continue this requirement")),
    ("client_asks_contract", ("msa", "sow", "agreement", "contract", "nda", "vendor agreement", "service agreement", "work order", "legal document")),
    ("client_vendor_registration", ("vendor registration", "vendor onboarding", "empanelment", "supplier registration", "vendor form", "bank details", "company documents")),
    ("client_asks_trainer_docs", ("trainer resume", "trainer cv", "trainer profile", "trainer documents", "certificates", "trainer linkedin", "experience proof", "trainer credentials")),
    ("client_asks_customization", ("customize", "tailor", "custom agenda", "customized content", "modify agenda", "specific topics", "include topics", "exclude topics")),
    ("client_asks_recording", ("recording", "session recording", "recorded session", "record the training", "recorded videos")),
    ("client_asks_materials", ("training material", "course material", "slides", "ppts", "handouts", "lab guide", "assignments", "documents")),
    ("client_asks_attendance", ("attendance", "attendance sheet", "participant list", "attendance report", "completion report")),
    ("client_asks_certificate", ("certificate", "certificates", "completion certificate", "participation certificate")),
    ("client_asks_lab_setup", ("lab setup", "environment setup", "software setup", "vm setup", "cloud access", "tools installation", "lab access")),
    ("client_asks_preassessment", ("assessment", "pre assessment", "post assessment", "test", "quiz", "evaluation report")),
    ("client_asks_timezone", ("timezone", "time zone", "ist", "est", "pst", "gmt", "time difference")),
    ("client_asks_mode_change", ("online to offline", "offline to online", "hybrid mode", "classroom training", "virtual training", "onsite training")),
    ("client_asks_location", ("training location", "venue", "office address", "onsite location", "client location", "city for training")),
    ("client_asks_batch_split", ("split batch", "multiple batches", "two batches", "batch wise", "separate batch", "parallel batch")),
    ("client_asks_rate_card", ("rate card", "standard rates", "pricing sheet", "commercial sheet", "rate list")),
    ("client_asks_availability", ("trainer availability", "availability check", "available dates", "available this week", "trainer free", "availability confirmation")),
    ("client_asks_shortlist_eta", ("when can you share profiles", "profile eta", "shortlist eta", "by when profiles", "how soon can you share", "timeline for profiles")),
    ("client_thanks", ("thank you", "thanks", "noted", "okay noted", "received", "acknowledged", "ok thanks", "fine", "great thanks")),
    ("client_updates_requirement", ("updated requirement", "revised requirement", "updated details", "revised details", "please update", "correction", "change in requirement")),
    ("quote_request", ("quote", "quotation", "commercial proposal", "pricing", "cost estimate", "commercials")),
    ("new_training_requirement", ("looking for", "need", "requirement", "trainer", "training", "workshop", "instructor")),
    ("client_sent_details", ("please find the training", "training duration", "preferred dates", "participant count", "budget")),
    ("client_asks_profiles", ("share suitable", "trainer profiles", "profiles for review", "availability and commercials")),
    ("trainer_interested", ("i am interested", "interested for this", "available for this", "can take this training", "sounds good", "please share details", "can do this", "happy to take", "open for this", "relevant to me")),
    ("trainer_not_interested", ("not interested", "not relevant", "not my area", "remove me", "do not send", "not suitable for me", "not looking for this")),
    ("trainer_unavailable", ("not available", "unavailable", "occupied", "not possible", "cannot take", "calendar packed", "travelling", "traveling", "busy on those dates", "available next month", "contact later")),
    ("trainer_partial_availability", ("half day", "weekends only", "evening slots", "after 6 pm", "available except", "tentatively available", "let me check", "will confirm availability", "available partially")),
    ("trainer_more_details", (
        "share more details",
        "please share more details",
        "can you share more details",
        "provide more details",
        "need more details",
        "more details on the requirement",
        "more details on the client",
        "additional details",
        "details required",
        "more information",
        "need more information",
        "let me know the details",
        "can you please share details",
        "can you provide details",
        "can you share details",
        "share client details",
    )),
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
        "per hour",
        "fixed cost",
        "plus gst",
        "excluding travel",
        "travel extra",
        "minimum days",
    )),
    ("trainer_commercial_acceptance", ("budget works", "rate okay", "commercials accepted", "fine with commercials", "revised budget accepted", "okay with revised budget")),
    ("trainer_commercial_rejection", ("budget too low", "not feasible", "cannot work at this rate", "rate is low", "increase budget", "cannot reduce", "best rate already shared")),
    ("trainer_slots_sent", (
        "slots",
        "available slots",
        "interview slots",
        "can connect",
        "schedule a call",
        "availability",
        "full-day",
        "half-day",
        "tomorrow",
        "next week",
        "calendar updated",
        "new availability",
    )),
    ("trainer_slot_confirmed", ("confirmed", "this slot works", "i will join", "meeting accepted", "calendar accepted", "will join on time", "slot confirmed")),
    ("trainer_reschedule_request", ("reschedule", "postpone", "prepone", "change timing", "change the slot", "need to postpone", "can we reschedule")),
    ("trainer_interview_done", ("interview done", "discussion completed", "client call completed", "call completed", "interview completed", "discussion done")),
    ("trainer_selected_ack", ("thanks for selection", "happy to proceed", "share next steps", "selected", "formal confirmation", "training confirmation")),
    ("trainer_toc_shared", ("attached agenda", "sharing toc", "toc attached", "course outline attached", "agenda attached", "day wise plan attached")),
    ("trainer_content_doubt", ("not my expertise", "cannot cover", "can cover basics only", "need clarification on topics", "scope mismatch", "too much content", "need more days")),
    ("trainer_logistics_query", ("participant list", "platform", "lab access", "material format", "who provides", "aws account", "kubernetes cluster", "tools installation", "prerequisites", "pre-read")),
    ("trainer_recording_material_policy", ("recording not allowed", "okay to record", "cannot share source files", "can share pdf only", "ip restriction", "material ownership")),
    ("trainer_payment_query", ("payment terms", "advance required", "payment after training", "tds", "gst invoice", "payment pending", "invoice submitted", "when will payment release", "billing details")),
    ("trainer_onsite_travel_query", ("travel reimbursement", "hotel required", "onsite charges", "location details", "offline only", "online only", "no travel", "onsite possible")),
    ("trainer_meeting_issue", ("link not working", "unable to join", "waiting in lobby", "teams not working", "zoom preferred", "google meet okay", "stuck in meeting", "may be late")),
    ("trainer_training_update", ("session started", "day 1 completed", "training completed", "shared materials", "participants not joining", "lab not ready", "internet issue")),
    ("trainer_referral", ("can refer", "my colleague can take", "sharing another trainer", "refer someone", "another trainer can take")),
    ("trainer_duplicate_reply", ("already replied", "already shared details", "please check previous mail", "shared earlier", "as mentioned earlier")),
    ("trainer_attachment_issue", ("forgot to attach", "please find attached now", "attachment not opening", "file too large", "drive link", "sharing drive link")),
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
    has_client_requirement = "new_training_requirement" in matched or bool(
        re.search(
            r"\b(?:need|require|required|requirement|looking\s+for)\b.{0,90}\b(?:trainer|training|workshop|instructor)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    has_client_detail_fields = bool(
        re.search(
            r"\b(?:training\s+dates?|duration|mode|location|participants?|participant\s+level|client\s+domain|budget|commercials?)\s*:",
            text,
            flags=re.IGNORECASE,
        )
    )
    if has_client_requirement and has_client_detail_fields:
        return "new_training_requirement", matched
    if "legal_notice" in matched:
        best = "legal_notice"
    elif "fraud_security" in matched:
        best = "fraud_security"
    elif "bounce" in matched:
        best = "bounce"
    elif "ooo" in matched:
        best = "ooo"
    else:
        trainer_priority = (
            "trainer_not_interested",
            "trainer_unavailable",
            "trainer_partial_availability",
            "trainer_commercial_rejection",
            "trainer_commercial_acceptance",
            "trainer_commercials_sent",
            "trainer_slot_confirmed",
            "trainer_reschedule_request",
            "trainer_interview_done",
            "trainer_selected_ack",
            "trainer_toc_shared",
            "trainer_content_doubt",
            "trainer_logistics_query",
            "trainer_recording_material_policy",
            "trainer_payment_query",
            "trainer_onsite_travel_query",
            "trainer_meeting_issue",
            "trainer_training_update",
            "trainer_referral",
            "trainer_duplicate_reply",
            "trainer_attachment_issue",
            "trainer_slots_sent",
            "trainer_credentials_sent",
            "trainer_more_details",
            "trainer_interested",
        )
        for scenario_name in trainer_priority:
            if scenario_name in matched:
                return scenario_name, matched

    if best in {"legal_notice", "fraud_security", "bounce", "ooo"}:
        return best, matched

    if "client_budget_negotiation" in matched:
        best = "client_budget_negotiation"
    elif "client_sent_details" in matched:
        best = "client_sent_details"
    else:
        priority = (
            "client_confirms_trainer",
            "client_requests_replacement",
            "client_rejects_trainer",
            "client_confirms_interview_slot",
            "client_requests_interview_slots",
            "client_asks_meeting_link",
            "client_sends_po",
            "client_asks_invoice",
            "client_payment_terms",
            "client_budget_negotiation",
            "client_asks_customization",
            "client_asks_certificate",
            "client_asks_toc",
            "client_changes_training_details",
            "client_asks_final_logistics",
            "client_asks_status_update",
            "client_asks_more_profiles",
            "client_training_completed",
            "client_feedback_shared",
            "client_escalation_delay",
            "client_cancels_requirement",
            "client_reopens_requirement",
            "client_asks_contract",
            "client_vendor_registration",
            "client_asks_trainer_docs",
            "client_asks_recording",
            "client_asks_materials",
            "client_asks_attendance",
            "client_asks_lab_setup",
            "client_asks_preassessment",
            "client_asks_timezone",
            "client_asks_mode_change",
            "client_asks_location",
            "client_asks_batch_split",
            "client_asks_rate_card",
            "client_asks_availability",
            "client_asks_shortlist_eta",
            "client_updates_requirement",
            "client_asks_profiles",
            "client_thanks",
        )
        for scenario_name in priority:
            if scenario_name in matched:
                best = scenario_name
                break
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
    if scenario.startswith("trainer_") and person_type not in {"bounce", "system", "ooo", "internal_team"}:
        person_type = "trainer"
    if scenario.startswith("client_") and person_type not in {"bounce", "system", "ooo", "internal_team"}:
        person_type = "corporate_client"
    if person_type == "trainer":
        trainer_detail_matches = {
            "trainer_credentials_sent",
            "trainer_commercials_sent",
            "trainer_slots_sent",
        } & set(matched)
        if "trainer_unavailable" in matched:
            scenario = "trainer_unavailable"
        elif "trainer_not_interested" in matched:
            scenario = "trainer_not_interested"
        elif len(trainer_detail_matches) >= 2:
            scenario = "trainer_details_sent"
        else:
            for trainer_scenario in (
                "trainer_commercial_rejection",
                "trainer_commercial_acceptance",
                "trainer_reschedule_request",
                "trainer_slot_confirmed",
                "trainer_interview_done",
                "trainer_selected_ack",
                "trainer_toc_shared",
                "trainer_content_doubt",
                "trainer_logistics_query",
                "trainer_recording_material_policy",
                "trainer_payment_query",
                "trainer_onsite_travel_query",
                "trainer_meeting_issue",
                "trainer_training_update",
                "trainer_referral",
                "trainer_duplicate_reply",
                "trainer_attachment_issue",
                "trainer_partial_availability",
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
