"""
email_classifier.py — Zero-cost email classification engine for Clahan Technologies.

Detects:
  - person_type   : who sent this email (15 types)
  - scenario      : what they want (60+ scenarios)
  - urgency       : low / normal / high / critical
  - sentiment     : positive / neutral / frustrated / angry / panicked
  - safe_to_reply : True / False (never auto-reply to legal, OOO, fraud, bounce)
  - confidence    : 0.0 – 1.0

Zero API cost. No LLM. Pure regex + keyword scoring. Instant.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ─── Person Types ────────────────────────────────────────────────────────────

PERSON_TYPES = {
    "corporate_client":   "Corporate client needing training or staffing",
    "trainer":            "Trainer / Subject Matter Expert",
    "job_seeker":         "Job seeker / candidate",
    "consultant":         "Freelance consultant offering services",
    "vendor_partner":     "Vendor or partner company",
    "existing_client":    "Existing Clahan client (follow-up / repeat)",
    "referral":           "Referred by someone known to Clahan",
    "student":            "Student / individual learner",
    "finance_legal":      "Finance, accounts, or legal contact",
    "government":         "Government / PSU / regulatory body",
    "media":              "Media, journalist, blogger, event organiser",
    "internal":           "Internal Clahan team member",
    "system_automated":   "Automated system / noreply / OOO / bounce",
    "angry_escalation":   "Angry client or formal complaint / legal threat",
    "unknown":            "Cannot classify with confidence",
}

# ─── Scenarios ────────────────────────────────────────────────────────────────

SCENARIOS = {
    # Corporate client
    "new_training_requirement":    "New training requirement from client",
    "training_followup":           "Follow-up on a previously sent trainer profile",
    "trainer_approval":            "Client approving / selecting a trainer",
    "trainer_rejection":           "Client rejecting a trainer, wants alternatives",
    "training_reschedule":         "Rescheduling training dates",
    "training_cancellation":       "Cancelling training",
    "quote_request":               "Requesting a quote or proposal",
    "invoice_po_request":          "Invoice, PO, or payment query from client",
    "agreement_nda":               "NDA, MSA, or vendor registration",
    "feedback_positive":           "Positive feedback on completed training",
    "feedback_negative":           "Complaint or negative feedback",
    "repeat_requirement":          "Repeat / new requirement from existing client",
    # Trainer
    "trainer_interested":          "Trainer interested in a requirement",
    "trainer_not_interested":      "Trainer declined the requirement",
    "trainer_profile_shared":      "Trainer sharing profile / CV unsolicited",
    "trainer_slots_shared":        "Trainer sharing availability / interview slots",
    "trainer_toc_shared":          "Trainer sharing ToC / agenda",
    "trainer_payment_query":       "Trainer asking about payment",
    "trainer_panel_register":      "Trainer wanting to join Clahan panel",
    "trainer_update_profile":      "Trainer updating profile / new certification",
    "trainer_followup_work":       "Trainer following up for new assignments",
    # Job seeker
    "job_application":             "Applying for a job opening",
    "cv_no_role":                  "Sending CV without specific role",
    "job_inquiry":                 "Asking about openings",
    "application_followup":        "Following up on a submitted application",
    "internship_request":          "Internship or apprenticeship request",
    # Vendor / partner
    "vendor_hotlist":              "Sharing a trainer or candidate hotlist",
    "vendor_partnership":          "Partnership or collaboration proposal",
    "vendor_tool_pitch":           "Pitching a tool or platform",
    "vendor_subcontract":          "Subcontracting offer",
    "vendor_followup":             "Vendor following up on a previous message",
    # Finance / legal
    "invoice_finance":             "Invoice, payment, or billing from vendor/trainer",
    "legal_notice":                "Legal notice, demand notice, court summons",
    "compliance_regulatory":       "GST, TDS, ROC, or regulatory notice",
    # Government
    "government_tender":           "Government RFP, tender, or EOI",
    "government_compliance":       "Government compliance or audit",
    # Media
    "media_interview":             "Media / journalist interview request",
    "event_speaking":              "Event sponsorship or speaking opportunity",
    "content_collaboration":       "Blog, podcast, or content collaboration",
    # Student
    "student_course_inquiry":      "Individual asking about training courses",
    # Referral
    "referral_introduction":       "Warm introduction via known contact",
    # Automated
    "auto_reply_ooo":              "Out-of-office or vacation auto-reply",
    "bounce_delivery_failure":     "Email delivery failure / bounce",
    "system_notification":         "Automated system notification",
    # Escalation
    "angry_complaint":             "Angry email or escalation",
    "legal_threat":                "Threatening legal action",
    "fraud_impersonation":         "Suspected fraud or impersonation",
    # Unknown
    "unclear":                     "Cannot determine intent",
}


# ─── Keyword Signal Banks ─────────────────────────────────────────────────────

# Safety: emails that must NEVER get an auto-reply
_NEVER_REPLY_SENDER_PATTERNS = [
    r"no.?reply", r"noreply", r"donotreply", r"do.not.reply",
    r"notification", r"alerts?@", r"mailer.daemon", r"postmaster",
    r"bounce", r"delivery.status", r"linkedin\.com", r"naukri\.com",
    r"indeed\.com", r"monster\.com", r"glassdoor\.com",
]

_NEVER_REPLY_SUBJECT_PATTERNS = [
    r"out of office", r"automatic reply", r"auto.reply", r"autoreply",
    r"vacation responder", r"away from office", r"delivery status",
    r"undeliverable", r"mail delivery failed", r"returned mail",
    r"bounce", r"failed to deliver",
]

_NEVER_REPLY_BODY_PATTERNS = [
    r"i am (currently )?out of office",
    r"i will be (away|out|back)",
    r"this is an automatic(ally generated)? (reply|response|email)",
    r"do not reply to this (email|message)",
    r"this mailbox is not monitored",
]

# Legal / escalation: flag for human immediately
_LEGAL_PATTERNS = [
    r"legal notice", r"without prejudice", r"demand notice",
    r"advocate", r"solicitor", r"attorney", r"lawyer",
    r"court", r"lawsuit", r"sue\b", r"legal action",
    r"harassment", r"defamation", r"breach of contract",
    r"cease and desist", r"arbitration",
]

_ANGRY_PATTERNS = [
    r"unacceptable", r"extremely (disappointed|frustrated|upset|angry)",
    r"this is (ridiculous|pathetic|horrible|terrible|awful|disgraceful)",
    r"i (demand|want) (immediate|immediate action|refund|compensation)",
    r"worst (service|experience|company)",
    r"(escalate|escalating) (this|to management|to your boss)",
    r"i will (post|share|report) (negative|bad) (review|feedback)",
    r"never (work|do business) with you again",
    r"you (people|team|company) (are|have) (useless|failed|let me down)",
]

_FRAUD_PATTERNS = [
    r"congratulations.{0,30}(won|winner|selected|prize)",
    r"(click here|verify now).{0,30}(claim|prize|reward)",
    r"(nigerian|inheritance|lottery|jackpot).{0,50}(million|usd|transfer)",
    r"your account (has been|will be) (suspended|blocked|closed)",
    r"verify your (account|password|credentials) immediately",
]


# ─── Person-type signal keywords ─────────────────────────────────────────────

_CLIENT_SIGNALS = [
    r"\btraining requirement\b", r"\btrainer (needed|required|wanted)\b",
    r"\bneed (a )?trainer\b", r"\brequire (a )?trainer\b",
    r"\bcorporate training\b", r"\bbatch (of|training)\b",
    r"\bour (team|employees|staff) (need|require|want)\b",
    r"\bl&d\b", r"\blearning (and development|&amp; development)\b",
    r"\bkindly share (trainer|profile)\b", r"\bshare (suitable )?trainer\b",
    r"\bskill (gap|development)\b", r"\btraining programme\b",
    r"\bworkshop (requirement|needed)\b", r"\bplease (suggest|recommend) trainer\b",
    r"\bbudget (approved|available|for training)\b",
    r"\bparticipants?\b", r"\baudience (level|type)\b",
    r"\btraining (mode|dates|duration|schedule)\b",
    r"\bclassroom (training|mode)\b", r"\bonline training\b",
    r"\bhybrid (training|mode)\b",
]

_TRAINER_SIGNALS = [
    r"\bi am a trainer\b", r"\bi (conduct|deliver|provide) training\b",
    r"\bmy training experience\b", r"\btrainer profile\b",
    r"\bi am interested (in the training|in this requirement)\b",
    r"\bplease find (my |the )?attached (profile|cv|resume)\b",
    r"\bmy (rate|commercial|charges?) (is|are|per day)\b",
    r"\bper day (rate|charges?|fees?)\b",
    r"\b(i am |i'm )?available (for|on)\b",
    r"\binterview slot\b", r"\btoc (attached|shared|enclosed)\b",
    r"\bterms of contract\b", r"\btraining agenda\b",
    r"\bpast (clients?|trainings?|batches?)\b",
    r"\bcertifications?\b.{0,50}\b(aws|azure|pmp|cissp|gcp|ceh|sap)\b",
    r"\bi can (deliver|conduct|provide) training\b",
    r"\btrainer (panel|empanelment|empanelled)\b",
]

_JOB_SEEKER_SIGNALS = [
    r"\bplease find (my |the )?attached (resume|cv)\b",
    r"\bpfa (my )?(resume|cv)\b",
    r"\b(application|applying) for (the )?(position|role|job|opening)\b",
    r"\b(years? of experience|yrs? exp)\b",
    r"\b(notice period|current ctc|expected ctc|current salary|expected salary)\b",
    r"\b(immediate joiner|available immediately|can join immediately)\b",
    r"\b(looking for|seeking|exploring) (a |new )?(job|opportunity|role|position)\b",
    r"\b(open to|willing to) (relocate|onsite|hybrid|remote)\b",
    r"\bfresher\b", r"\bjob (change|switch)\b",
    r"\binterview (call|availability|process)\b.{0,50}\bjob\b",
]

_VENDOR_SIGNALS = [
    r"\bhotlist\b", r"\bbench (sales?|resource)\b",
    r"\bavailable (consultant|candidate|resource)\b",
    r"\bpartnership (opportunity|proposal|collaboration)\b",
    r"\bour (platform|tool|software|solution|services?) (can|will|offer)\b",
    r"\bsubcontract(ing)?\b", r"\bwhite.?label\b",
    r"\brevenue sharing\b", r"\brate card\b",
    r"\bwe (are|have) (empanelled|registered|certified) (vendor|partner)\b",
    r"\bplease (add|register|onboard) us\b",
]

_FINANCE_SIGNALS = [
    r"\binvoice\b", r"\bpurchase order\b", r"\b\bpo (number|attached|enclosed)\b",
    r"\bgst (invoice|number|certificate)\b",
    r"\btds (certificate|deduction)\b",
    r"\bpayment (due|pending|confirmation|received|failed|details)\b",
    r"\bbank (details|account|transfer|wire)\b",
    r"\boutstanding (amount|balance|invoice)\b",
    r"\baccounts (team|payable|receivable)\b",
    r"\bbilling (query|issue|address)\b",
]

_REFERRAL_SIGNALS = [
    r"\b(referred|recommended|suggested) by\b",
    r"\b(xyz|someone|my colleague|your (client|trainer|employee)) (asked me|told me|suggested) to (reach|contact|write)\b",
    r"\bthrough (your|a) (referral|reference|recommendation)\b",
    r"\bgot your (contact|details|email) from\b",
    r"\bfound you through\b",
]

_STUDENT_SIGNALS = [
    r"\bi am a student\b", r"\blearning (python|java|aws|azure|data science)\b",
    r"\bindividual (training|course|class)\b",
    r"\bpersonal (training|upskilling|learning)\b",
    r"\b(fees?|cost|price) for (the )?(course|training|class)\b",
    r"\bdo you (offer|provide|have) (courses?|classes?) for (individuals?|students?)\b",
    r"\bcertification (course|programme|prep)\b.{0,30}\bindividual\b",
]

_GOVERNMENT_SIGNALS = [
    r"\btender\b", r"\brfp\b", r"\beoi\b", r"\brequest for proposal\b",
    r"\bgovernment (of india|training|project|scheme)\b",
    r"\bpsu\b", r"\bpublic sector\b",
    r"\bnsdc\b", r"\bskill (india|council|ministry)\b",
    r"\bministry of\b", r"\bnational skill\b",
    r"\bgov\.in\b", r"\bnic\.in\b",
]

_MEDIA_SIGNALS = [
    r"\bjournalist\b", r"\bpress (release|inquiry|request)\b",
    r"\barticle (about|on|featuring)\b", r"\binterview (request|for article)\b",
    r"\bspeaking (opportunity|slot|invitation)\b",
    r"\bconference (speaker|panellist)\b",
    r"\bpodcast (guest|invitation)\b",
    r"\bsponsorship (opportunity|package)\b",
    r"\bguest (post|blog|article)\b",
    r"\baward (nomination|ceremony|winner)\b",
    r"\b(media|pr) (coverage|collaboration|inquiry)\b",
]


# ─── Urgency signals ─────────────────────────────────────────────────────────

_URGENCY_CRITICAL = [
    r"\btraining (starts?|begins?|is) (today|tomorrow|in \d+ hours?)\b",
    r"\btrainer (dropped|cancelled|backed out|unavailable)\b",
    r"\burgent.{0,20}(today|tomorrow|asap|immediately)\b",
    r"\bwithin (the next )?\d+ hours?\b",
    r"\bno trainer\b.{0,30}\b(tomorrow|today)\b",
]

_URGENCY_HIGH = [
    r"\b(very urgent|extremely urgent|high priority|asap|as soon as possible)\b",
    r"\bwithin (24|48) hours?\b",
    r"\btoday\b.{0,50}\b(required|needed|urgent)\b",
    r"\bcritical (requirement|need|deadline)\b",
    r"\blatest by (today|tomorrow|this week|monday|tuesday|wednesday|thursday|friday)\b",
    r"\b(need|require).{0,20}(urgently|immediately|at the earliest)\b",
]

_URGENCY_LOW = [
    r"\bno (rush|hurry|urgency)\b",
    r"\bwhenever (convenient|possible|you (have time|get a chance))\b",
    r"\bflexible (on dates?|timeline|schedule)\b",
    r"\bnext (quarter|month|year)\b",
    r"\bplanning (ahead|in advance|for future)\b",
    r"\blong.?term (plan|requirement|engagement)\b",
]

# ─── Sentiment signals ────────────────────────────────────────────────────────

_SENTIMENT_POSITIVE = [
    r"\b(thank you|thanks|appreciate|grateful|great|excellent|wonderful|happy|pleased)\b",
    r"\b(looking forward|excited|glad|delighted)\b",
    r"\bperfect\b", r"\bbrilliant\b", r"\bfantastic\b",
]

_SENTIMENT_FRUSTRATED = [
    r"\b(still (waiting|no response|not received|haven't heard))\b",
    r"\b(waited|waiting) (for|since) (days?|weeks?|long time|too long)\b",
    r"\b(no (reply|update|response|communication))\b",
    r"\bkeep (following up|chasing)\b",
    r"\bwhy (is|has|have) (it|this|there) (not|been|no)\b",
    r"\b(disappointed|let down|not happy|dissatisfied)\b",
]

_SENTIMENT_ANGRY = _ANGRY_PATTERNS

_SENTIMENT_PANICKED = [
    r"\btraining (starts?|is) (tomorrow|today|in \d+ hours?)\b",
    r"\bwhat (do i|should we) do\b.{0,30}\b(now|immediately)\b",
    r"\bemergency\b", r"\bcrisis\b",
    r"\bplease (help|respond|reply|call) (urgently|immediately|now|asap)\b",
    r"\b(panicking|stressed|worried|desperate)\b",
]


# ─── Domain suffix helpers ────────────────────────────────────────────────────

_CORPORATE_DOMAIN_TLDS = {".com", ".in", ".co.in", ".net", ".org", ".io", ".co"}
_GOVERNMENT_DOMAIN_TLDS = {".gov", ".gov.in", ".nic.in", ".ac.in", ".edu"}
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "rediffmail.com", "ymail.com", "protonmail.com", "icloud.com",
}


def _sender_domain(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    return email.rsplit("@", 1)[1].lower().strip()


def _is_free_email(email: str) -> bool:
    return _sender_domain(email) in _FREE_EMAIL_DOMAINS


def _is_corporate_email(email: str) -> bool:
    domain = _sender_domain(email)
    if not domain or domain in _FREE_EMAIL_DOMAINS:
        return False
    return any(domain.endswith(tld) for tld in _CORPORATE_DOMAIN_TLDS)


def _is_government_email(email: str) -> bool:
    domain = _sender_domain(email)
    return any(domain.endswith(tld) for tld in _GOVERNMENT_DOMAIN_TLDS)


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _score(haystack: str, patterns: List[str]) -> int:
    """Count how many patterns match in haystack."""
    return sum(1 for p in patterns if re.search(p, haystack, re.IGNORECASE))


def _any_match(haystack: str, patterns: List[str]) -> bool:
    return any(re.search(p, haystack, re.IGNORECASE) for p in patterns)


def _build_haystack(
    subject: str,
    body: str,
    from_email: str = "",
    from_name: str = "",
    max_body: int = 3000,
) -> str:
    return "\n".join([
        from_name or "",
        from_email or "",
        subject or "",
        (body or "")[:max_body],
    ]).lower()


# ─── Safety check ─────────────────────────────────────────────────────────────

def is_safe_to_reply(
    from_email: str,
    subject: str,
    body: str,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """
    Returns (True, "") if safe to auto-reply.
    Returns (False, reason) if this email must NEVER get an auto-reply.
    """
    email_lower = (from_email or "").lower()
    subject_lower = (subject or "").lower()
    body_lower = (body or "")[:2000].lower()
    haystack = f"{subject_lower}\n{body_lower}"

    # Check noreply / automated sender
    if _any_match(email_lower, _NEVER_REPLY_SENDER_PATTERNS):
        return False, "automated_sender"

    # Check OOO / bounce subject
    if _any_match(subject_lower, _NEVER_REPLY_SUBJECT_PATTERNS):
        return False, "ooo_or_bounce_subject"

    # Check OOO body
    if _any_match(body_lower, _NEVER_REPLY_BODY_PATTERNS):
        return False, "ooo_body"

    # Check headers
    hdrs = {k.lower(): v.lower() for k, v in (headers or {}).items()}
    auto_submitted = hdrs.get("auto-submitted", "")
    if auto_submitted and auto_submitted != "no":
        return False, "auto_submitted_header"
    precedence = hdrs.get("precedence", "")
    if precedence in {"bulk", "junk", "list"}:
        return False, "bulk_precedence_header"

    # Legal notice
    if _any_match(haystack, _LEGAL_PATTERNS):
        return False, "legal_notice"

    # Fraud / spam
    if _any_match(haystack, _FRAUD_PATTERNS):
        return False, "suspected_fraud"

    return True, ""


# ─── Urgency detection ────────────────────────────────────────────────────────

def detect_urgency(subject: str, body: str) -> str:
    haystack = f"{subject or ''}\n{(body or '')[:2000]}"
    if _any_match(haystack, _URGENCY_CRITICAL):
        return "critical"
    if _any_match(haystack, _URGENCY_HIGH):
        return "high"
    if _any_match(haystack, _URGENCY_LOW):
        return "low"
    return "normal"


# ─── Sentiment detection ──────────────────────────────────────────────────────

def detect_sentiment(subject: str, body: str) -> str:
    haystack = f"{subject or ''}\n{(body or '')[:2000]}"
    if _any_match(haystack, _SENTIMENT_PANICKED):
        return "panicked"
    if _any_match(haystack, _SENTIMENT_ANGRY):
        return "angry"
    if _any_match(haystack, _SENTIMENT_FRUSTRATED):
        return "frustrated"
    if _any_match(haystack, _SENTIMENT_POSITIVE):
        return "positive"
    return "neutral"


# ─── Person type detection ────────────────────────────────────────────────────

def _detect_person_type(
    from_email: str,
    subject: str,
    body: str,
    from_name: str = "",
) -> Tuple[str, float]:
    """
    Returns (person_type, confidence).
    Uses domain + keyword scoring to decide who sent this email.
    """
    haystack = _build_haystack(subject, body, from_email, from_name)
    subject_lower = (subject or "").lower()
    body_lower = (body or "").lower()

    # ── Automated / system first ─────────────────────────────────────────
    email_lower = from_email.lower()
    if _any_match(email_lower, _NEVER_REPLY_SENDER_PATTERNS):
        return "system_automated", 0.99
    if _any_match(subject_lower, _NEVER_REPLY_SUBJECT_PATTERNS):
        return "system_automated", 0.99
    if _any_match(body_lower[:500], _NEVER_REPLY_BODY_PATTERNS):
        return "system_automated", 0.97

    # ── Legal / angry escalation ─────────────────────────────────────────
    if _any_match(haystack, _LEGAL_PATTERNS):
        return "angry_escalation", 0.98
    if _score(haystack, _ANGRY_PATTERNS) >= 2:
        return "angry_escalation", 0.90
    if _score(haystack, _ANGRY_PATTERNS) == 1:
        # Could still be normal complaint — lower confidence
        pass

    # ── Government ───────────────────────────────────────────────────────
    if _is_government_email(from_email) or _score(haystack, _GOVERNMENT_SIGNALS) >= 2:
        return "government", 0.90

    # ── Score each person type ───────────────────────────────────────────
    scores: Dict[str, int] = {
        "corporate_client": _score(haystack, _CLIENT_SIGNALS),
        "trainer":          _score(haystack, _TRAINER_SIGNALS),
        "job_seeker":       _score(haystack, _JOB_SEEKER_SIGNALS),
        "vendor_partner":   _score(haystack, _VENDOR_SIGNALS),
        "finance_legal":    _score(haystack, _FINANCE_SIGNALS),
        "referral":         _score(haystack, _REFERRAL_SIGNALS),
        "student":          _score(haystack, _STUDENT_SIGNALS),
        "media":            _score(haystack, _MEDIA_SIGNALS),
    }

    # Boost corporate_client if domain is corporate + has training signals
    if _is_corporate_email(from_email) and scores["corporate_client"] >= 1:
        scores["corporate_client"] += 3

    # Boost trainer if free email + trainer signals present
    if _is_free_email(from_email) and scores["trainer"] >= 2:
        scores["trainer"] += 2

    # Boost job_seeker if free email + job signals
    if _is_free_email(from_email) and scores["job_seeker"] >= 2:
        scores["job_seeker"] += 2

    # Boost referral regardless of domain
    if scores["referral"] >= 1:
        scores["referral"] += 2

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    if best_score == 0:
        return "unknown", 0.30

    # Confidence based on score magnitude
    if best_score >= 5:
        confidence = 0.95
    elif best_score >= 3:
        confidence = 0.85
    elif best_score >= 2:
        confidence = 0.75
    else:
        confidence = 0.60

    return best_type, confidence


# ─── Scenario detection ───────────────────────────────────────────────────────

def _detect_scenario(
    person_type: str,
    subject: str,
    body: str,
) -> str:
    haystack = f"{subject or ''}\n{(body or '')[:3000]}".lower()

    # System / automated
    if person_type == "system_automated":
        if _any_match(haystack, [r"undeliverable", r"delivery (failed|failure)", r"returned mail", r"bounce"]):
            return "bounce_delivery_failure"
        return "auto_reply_ooo"

    # Legal / escalation
    if person_type == "angry_escalation":
        if _any_match(haystack, _LEGAL_PATTERNS):
            return "legal_threat"
        if _any_match(haystack, _FRAUD_PATTERNS):
            return "fraud_impersonation"
        return "angry_complaint"

    # Corporate client scenarios
    if person_type == "corporate_client":
        if _any_match(haystack, [r"\bcancel(led)?\b.{0,40}\btraining\b", r"\btraining.{0,40}\bcancel(led)?\b"]):
            return "training_cancellation"
        if _any_match(haystack, [r"\breschedul", r"\bpostpon", r"\bchange.{0,30}(date|schedule)\b"]):
            return "training_reschedule"
        if _any_match(haystack, [r"\bselect(ed)?\b.{0,40}\btrainer\b", r"\bapprove(d)?\b.{0,40}\btrainer\b", r"\bconfirm(ed)?\b.{0,40}\btrainer\b"]):
            return "trainer_approval"
        if _any_match(haystack, [r"\breject(ed)?\b.{0,40}\btrainer\b", r"\bnot (suitable|selected|approved)\b", r"\balternative (trainer|profile)\b"]):
            return "trainer_rejection"
        if _any_match(haystack, [r"\bfollow.?up\b.{0,40}\b(profile|trainer|shortlist)\b", r"\bany update\b", r"\bwaiting for\b.{0,40}\bprofile\b"]):
            return "training_followup"
        if _any_match(haystack, [r"\bquote\b", r"\bproposal\b", r"\brfp\b", r"\bcost estimate\b", r"\bcommercial offer\b"]):
            return "quote_request"
        if _any_match(haystack, [r"\binvoice\b", r"\bpo\b", r"\bpurchase order\b", r"\bpayment\b", r"\bgst\b"]):
            return "invoice_po_request"
        if _any_match(haystack, [r"\bnda\b", r"\bmsa\b", r"\bvendor (registration|onboarding|empanelment)\b", r"\bagreement\b"]):
            return "agreement_nda"
        if _any_match(haystack, [r"\bfeedback\b.{0,60}\b(trainer|training|session)\b",
                                   r"\b(good|excellent|wonderful|great).{0,40}\b(trainer|training)\b"]):
            return "feedback_positive"
        if _any_match(haystack, [r"\bcomplaint\b", r"\bnot (good|satisfied|happy)\b.{0,40}\b(trainer|training)\b",
                                   r"\bpoor (quality|trainer|training)\b"]):
            return "feedback_negative"
        if _any_match(haystack, [r"\bnew (training )?(requirement|need)\b", r"\banother (training|requirement|batch)\b",
                                   r"\bonce again\b", r"\bagain (need|require)\b"]):
            return "repeat_requirement"
        return "new_training_requirement"

    # Trainer scenarios
    if person_type == "trainer":
        if _any_match(haystack, [r"\bnot (interested|available)\b", r"\bcan(not|'t) (take|do|attend|commit)\b", r"\bregret\b"]):
            return "trainer_not_interested"
        if _any_match(haystack, [r"\btoc\b", r"\bterms of contract\b", r"\btraining agenda\b", r"\bcurriculum\b"]):
            return "trainer_toc_shared"
        if _any_match(haystack, [r"\b(slot|available|availability|interview).{0,30}(date|time|day)\b"]):
            return "trainer_slots_shared"
        if _any_match(haystack, [r"\bpayment\b", r"\bpayment (due|pending|status)\b", r"\binvoice\b", r"\bcommercials\b.{0,30}\bpaid\b"]):
            return "trainer_payment_query"
        if _any_match(haystack, [r"\bjoin.{0,30}(panel|empanel|your (team|database|pool))\b",
                                   r"\b(add|register|list) me\b", r"\bempanelment\b"]):
            return "trainer_panel_register"
        if _any_match(haystack, [r"\b(update|new) (profile|certification|cv|resume)\b", r"\bnewly (certified|qualified)\b"]):
            return "trainer_update_profile"
        if _any_match(haystack, [r"\b(any|upcoming) (requirement|opportunity|assignment|project)\b",
                                   r"\bfollowing up\b.{0,40}\b(work|requirement|training)\b"]):
            return "trainer_followup_work"
        if _any_match(haystack, [r"\b(profile|cv|resume).{0,30}(attached|enclosed|find)\b"]):
            return "trainer_profile_shared"
        if _any_match(haystack, [r"\binterested\b", r"\bi (can|would like to|want to)\b.{0,40}\btraining\b"]):
            return "trainer_interested"
        return "trainer_profile_shared"

    # Job seeker
    if person_type == "job_seeker":
        if _any_match(haystack, [r"\bfollow.?up\b.{0,40}\b(application|interview|status)\b"]):
            return "application_followup"
        if _any_match(haystack, [r"\binternship\b", r"\bapprentice\b", r"\bstudent (project|internship)\b"]):
            return "internship_request"
        if _any_match(haystack, [r"\b(any |current )?(job |career )?opening\b", r"\bhiring\b", r"\bvacancy\b"]):
            return "job_inquiry"
        if _any_match(haystack, [r"\bapplication for\b", r"\bapplying for\b"]):
            return "job_application"
        return "cv_no_role"

    # Vendor / partner
    if person_type == "vendor_partner":
        if _any_match(haystack, [r"\bhotlist\b", r"\bbench (sales?|resource)\b"]):
            return "vendor_hotlist"
        if _any_match(haystack, [r"\bsubcontract\b", r"\bwhite.?label\b"]):
            return "vendor_subcontract"
        if _any_match(haystack, [r"\bplatform\b", r"\btool\b", r"\bsoftware\b", r"\bsolution\b"]):
            return "vendor_tool_pitch"
        if _any_match(haystack, [r"\bfollow.?up\b", r"\bchecking in\b", r"\bfollowing up\b"]):
            return "vendor_followup"
        return "vendor_partnership"

    # Finance / legal
    if person_type == "finance_legal":
        if _any_match(haystack, _LEGAL_PATTERNS):
            return "legal_notice"
        if _any_match(haystack, [r"\bgst\b", r"\btds\b", r"\bpf\b", r"\broc\b", r"\bfiling\b"]):
            return "compliance_regulatory"
        return "invoice_finance"

    # Government
    if person_type == "government":
        if _any_match(haystack, [r"\btender\b", r"\brfp\b", r"\beoi\b"]):
            return "government_tender"
        return "government_compliance"

    # Media
    if person_type == "media":
        if _any_match(haystack, [r"\bspeaking\b", r"\bpanellist\b", r"\bconference\b"]):
            return "event_speaking"
        if _any_match(haystack, [r"\bjournalist\b", r"\binterview\b", r"\barticle\b"]):
            return "media_interview"
        return "content_collaboration"

    # Referral
    if person_type == "referral":
        return "referral_introduction"

    # Student
    if person_type == "student":
        return "student_course_inquiry"

    return "unclear"


# ─── Master classifier ────────────────────────────────────────────────────────

def classify_email(
    from_email: str,
    subject: str,
    body: str,
    from_name: str = "",
    headers: Optional[Dict[str, str]] = None,
    history: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Master classifier — call this for every incoming email.

    Args:
        from_email : sender email address
        subject    : email subject line
        body       : plain text body (cleaned, no quoted history)
        from_name  : sender display name (optional)
        headers    : dict of email headers (optional, improves OOO detection)
        history    : dict with keys like 'is_known_client', 'is_known_trainer',
                     'last_interaction', 'pipeline_stage' (optional)

    Returns dict with:
        person_type       : str  — who sent this
        scenario          : str  — what they want
        urgency           : str  — low / normal / high / critical
        sentiment         : str  — positive / neutral / frustrated / angry / panicked
        safe_to_reply     : bool — False means NEVER auto-reply
        no_reply_reason   : str  — why it is not safe (empty if safe)
        confidence        : float — 0.0 to 1.0
        requires_human    : bool — True for legal, angry, critical urgency
        person_label      : str  — human-readable label
        scenario_label    : str  — human-readable scenario description
    """
    safe, no_reply_reason = is_safe_to_reply(from_email, subject, body, headers)

    if not safe:
        # Map reason to person_type and scenario
        if no_reply_reason in {"ooo_or_bounce_subject", "ooo_body", "auto_submitted_header",
                                "bulk_precedence_header", "automated_sender"}:
            ptype = "system_automated"
            scenario = "bounce_delivery_failure" if "bounce" in no_reply_reason else "auto_reply_ooo"
        elif no_reply_reason == "legal_notice":
            ptype = "angry_escalation"
            scenario = "legal_threat"
        elif no_reply_reason == "suspected_fraud":
            ptype = "unknown"
            scenario = "fraud_impersonation"
        else:
            ptype = "unknown"
            scenario = "unclear"

        return {
            "person_type": ptype,
            "scenario": scenario,
            "urgency": "critical" if no_reply_reason == "legal_notice" else "normal",
            "sentiment": "neutral",
            "safe_to_reply": False,
            "no_reply_reason": no_reply_reason,
            "confidence": 0.99,
            "requires_human": True,
            "person_label": PERSON_TYPES.get(ptype, ptype),
            "scenario_label": SCENARIOS.get(scenario, scenario),
        }

    # Incorporate history signals
    hist = history or {}
    is_known_client  = bool(hist.get("is_known_client"))
    is_known_trainer = bool(hist.get("is_known_trainer"))

    person_type, confidence = _detect_person_type(from_email, subject, body, from_name)

    # Override with history context
    if is_known_client and person_type in {"unknown", "vendor_partner", "trainer"}:
        person_type = "existing_client"
        confidence = max(confidence, 0.80)
    elif is_known_client and person_type == "corporate_client":
        person_type = "existing_client"
        confidence = max(confidence, 0.88)
    if is_known_trainer and person_type in {"unknown", "job_seeker"}:
        person_type = "trainer"
        confidence = max(confidence, 0.80)

    scenario  = _detect_scenario(person_type, subject, body)
    urgency   = detect_urgency(subject, body)
    sentiment = detect_sentiment(subject, body)

    # Escalate sentiment-based urgency
    if sentiment == "panicked" and urgency == "normal":
        urgency = "high"
    if sentiment == "angry" and urgency in {"low", "normal"}:
        urgency = "high"

    # Decide if human review needed
    requires_human = (
        urgency == "critical"
        or sentiment == "angry"
        or scenario in {"legal_threat", "angry_complaint", "fraud_impersonation",
                         "feedback_negative", "training_cancellation"}
        or person_type == "angry_escalation"
    )

    return {
        "person_type": person_type,
        "scenario": scenario,
        "urgency": urgency,
        "sentiment": sentiment,
        "safe_to_reply": True,
        "no_reply_reason": "",
        "confidence": round(confidence, 2),
        "requires_human": requires_human,
        "person_label": PERSON_TYPES.get(person_type, person_type),
        "scenario_label": SCENARIOS.get(scenario, scenario),
    }


# ─── Convenience: should this email get an auto-reply at all? ─────────────────

def should_auto_reply(classification: Dict[str, Any]) -> bool:
    """True only if it is safe AND does not require human intervention."""
    return (
        classification.get("safe_to_reply", False)
        and not classification.get("requires_human", True)
        and classification.get("person_type") not in {"system_automated", "unknown"}
    )
