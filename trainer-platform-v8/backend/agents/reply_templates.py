"""
reply_templates.py — Zero-cost smart reply engine for Clahan Technologies.

Covers every person type and scenario identified by email_classifier.py.
No LLM. No API cost. Pure Python building blocks.

Architecture:
  BLOCK A → Greeting
  BLOCK B → Acknowledgement
  BLOCK C → What we understood / received
  BLOCK D → What we still need
  BLOCK E → What we will do next
  BLOCK F → Timeline / commitment
  BLOCK G → Signature

Every reply = pick blocks + fill extracted fields.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ─── Signature ───────────────────────────────────────────────────────────────

DEFAULT_SIGNATURE = "Best Regards,\nRecruitment Team\nClahan Technologies"


def _sig(ctx: Dict[str, Any]) -> str:
    s = (ctx or {}).get("reply_signature") or DEFAULT_SIGNATURE
    return s.strip()


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _first_name(full_name: str) -> str:
    """Return first word of a name, capitalised."""
    name = (full_name or "").strip().split()[0] if (full_name or "").strip() else ""
    return name.capitalize() if name else ""


def _title(text: str) -> str:
    """Title-case a technology name, preserving known acronyms."""
    _caps = {
        "AWS", "GCP", "AI", "ML", "UI", "UX", "HR", "IT", "API", "SQL",
        "SAP", "CRM", "ERP", "RPA", "IOT", "NLP", "CI", "CD", "QA", "BA",
        "BI", "AR", "VR", "DEVOPS", "GENAI", "LLMOPS", "MLOPS", "AIOPS",
        "CISSP", "PMP", "CEH", "CISM", "AWS", "AZURE", "GCP",
    }
    result = []
    for w in (text or "").split():
        if w.upper() in _caps:
            result.append(w.upper())
        elif w.lower() == "devops":
            result.append("DevOps")
        elif w.lower() == "genai":
            result.append("GenAI")
        elif w.lower() == "fullstack":
            result.append("Full Stack")
        else:
            result.append(w.capitalize())
    return " ".join(result)


def _bullet(items: List[str]) -> str:
    return "\n".join(f"* {i}" for i in items if i)


def _subject_re(original: str) -> str:
    s = (original or "Training Requirement").strip()
    return s if re.match(r"^re\s*:", s, re.IGNORECASE) else f"Re: {s}"


def _duration_str(extracted: Dict[str, Any]) -> Optional[str]:
    d = extracted.get("duration_days")
    h = extracted.get("duration_hours")
    if d:
        return f"{int(d)} day{'s' if int(d) != 1 else ''}"
    if h:
        return f"{int(h)} hour{'s' if int(h) != 1 else ''}"
    return None


def _budget_str(extracted: Dict[str, Any]) -> Optional[str]:
    per_day = extracted.get("budget_per_day")
    total   = extracted.get("budget_total")
    cur     = extracted.get("budget_currency") or "INR"
    sym     = "₹" if cur == "INR" else ("$" if cur == "USD" else f"{cur} ")
    if per_day:
        return f"{sym}{int(per_day):,} per day"
    if total:
        return f"{sym}{int(total):,} total"
    return None


def _known_fields(extracted: Dict[str, Any]) -> List[str]:
    """Return human-readable list of what the client already provided."""
    parts: List[str] = []
    tech = extracted.get("technology_needed")
    if tech:
        parts.append(f"Technology: {_title(tech)}")
    dur = _duration_str(extracted)
    if dur:
        parts.append(f"Duration: {dur}")
    if extracted.get("timeline_start"):
        parts.append(f"Preferred dates: {extracted['timeline_start']}")
    if extracted.get("daily_timing"):
        parts.append(f"Daily timings: {extracted['daily_timing']}")
    if extracted.get("participant_count"):
        parts.append(f"Participants: {extracted['participant_count']}")
    if extracted.get("audience_level"):
        parts.append(f"Audience level: {str(extracted['audience_level']).capitalize()}")
    if extracted.get("mode"):
        parts.append(f"Mode: {str(extracted['mode']).capitalize()}")
    if extracted.get("location"):
        parts.append(f"Location: {extracted['location']}")
    bud = _budget_str(extracted)
    if bud:
        parts.append(f"Budget: {bud}")
    if extracted.get("special_requirements"):
        parts.append(f"Special requirements: {extracted['special_requirements']}")
    return parts


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════

# ─── BLOCK A: Greetings ───────────────────────────────────────────────────────

def _greet(name: str, person_type: str = "corporate_client") -> str:
    if name:
        return f"Dear {name},"
    mapping = {
        "corporate_client": "Dear Client,",
        "existing_client":  "Dear Client,",
        "trainer":          "Dear Trainer,",
        "job_seeker":       "Dear Candidate,",
        "consultant":       "Dear Consultant,",
        "vendor_partner":   "Dear Team,",
        "referral":         "Dear Sir/Madam,",
        "student":          "Dear Student,",
        "finance_legal":    "Dear Team,",
        "government":       "Dear Sir/Madam,",
        "media":            "Dear Team,",
    }
    return mapping.get(person_type, "Dear Sir/Madam,")


# ─── BLOCK B: Acknowledgements ───────────────────────────────────────────────

_ACK = {
    "new_training_requirement":  "Thank you for reaching out to Clahan Technologies with your training requirement.",
    "repeat_requirement":        "Thank you for choosing Clahan Technologies once again for your training needs.",
    "training_followup":         "Thank you for following up with us.",
    "trainer_approval":          "Thank you for confirming your selection.",
    "trainer_rejection":         "Thank you for your feedback regarding the trainer profiles shared.",
    "training_reschedule":       "Thank you for informing us about the change in schedule.",
    "training_cancellation":     "We acknowledge your request to cancel the training.",
    "quote_request":             "Thank you for your interest in Clahan Technologies.",
    "invoice_po_request":        "Thank you for reaching out regarding the invoice/payment.",
    "agreement_nda":             "Thank you for initiating the vendor registration/agreement process.",
    "feedback_positive":         "Thank you for the wonderful feedback. We are delighted to hear this.",
    "feedback_negative":         "Thank you for bringing this to our attention. We sincerely apologise for the inconvenience.",
    "trainer_interested":        "Thank you for your interest in the training requirement shared by Clahan Technologies.",
    "trainer_not_interested":    "Thank you for letting us know.",
    "trainer_profile_shared":    "Thank you for sharing your profile with us.",
    "trainer_slots_shared":      "Thank you for sharing your availability.",
    "trainer_toc_shared":        "Thank you for sharing the Terms of Contract and training agenda.",
    "trainer_payment_query":     "Thank you for reaching out regarding your payment.",
    "trainer_panel_register":    "Thank you for your interest in joining Clahan Technologies as a trainer.",
    "trainer_update_profile":    "Thank you for sending us your updated profile.",
    "trainer_followup_work":     "Thank you for staying in touch with us.",
    "job_application":           "Thank you for sharing your profile with us.",
    "cv_no_role":                "Thank you for reaching out to Clahan Technologies.",
    "job_inquiry":               "Thank you for your interest in opportunities at Clahan Technologies.",
    "application_followup":      "Thank you for following up on your application.",
    "internship_request":        "Thank you for your interest in interning with Clahan Technologies.",
    "vendor_hotlist":            "Thank you for sharing the hotlist with us.",
    "vendor_partnership":        "Thank you for reaching out to Clahan Technologies.",
    "vendor_tool_pitch":         "Thank you for reaching out to Clahan Technologies.",
    "vendor_subcontract":        "Thank you for your subcontracting proposal.",
    "vendor_followup":           "Thank you for following up with us.",
    "invoice_finance":           "Thank you for reaching out regarding the payment/invoice.",
    "government_tender":         "Thank you for the tender/RFP notification.",
    "government_compliance":     "Thank you for the compliance communication.",
    "media_interview":           "Thank you for reaching out to Clahan Technologies.",
    "event_speaking":            "Thank you for the speaking/sponsorship invitation.",
    "content_collaboration":     "Thank you for the collaboration proposal.",
    "student_course_inquiry":    "Thank you for your interest in training with Clahan Technologies.",
    "referral_introduction":     "Thank you for reaching out to Clahan Technologies.",
    "angry_complaint":           "We sincerely apologise for the inconvenience caused. We take all feedback very seriously.",
}

def _ack(scenario: str) -> str:
    return _ACK.get(scenario, "Thank you for reaching out to Clahan Technologies.")


# ─── BLOCK C: What we understood ─────────────────────────────────────────────

def _understood_training(extracted: Dict[str, Any]) -> str:
    fields = _known_fields(extracted)
    if not fields:
        return ""
    return "We have noted the following details shared by you:\n" + _bullet(fields)


# ─── BLOCK D: What we still need ─────────────────────────────────────────────

def _needs_section(needs: List[str]) -> str:
    if not needs:
        return ""
    return (
        "To help us identify and recommend the most suitable trainers, "
        "kindly provide the following additional details:\n"
        + _bullet(needs)
    )


# ─── BLOCK E: What we will do ────────────────────────────────────────────────

def _action_training_missing(tech: Optional[str]) -> str:
    if tech:
        return (
            f"Meanwhile, our team will begin an initial trainer search based on the "
            f"{_title(tech)} domain and the information currently available. "
            "Once we receive the above details, we will refine the shortlist and "
            "share the most relevant trainer profiles for your review."
        )
    return (
        "Once you confirm the training domain and the above details, "
        "our team will begin trainer matching and share suitable profiles for your review."
    )


def _action_training_complete(tech: Optional[str]) -> str:
    t = _title(tech) if tech else "the required domain"
    return (
        f"Our team will begin shortlisting suitable {t} trainers based on the above details. "
        "We will share relevant trainer profiles, along with their experience, "
        "domain expertise, and commercial details, for your review within 24 hours."
    )


def _action_training_urgent(tech: Optional[str]) -> str:
    t = _title(tech) if tech else "the required domain"
    return (
        f"Given the urgency, our team will prioritise shortlisting {t} trainers "
        "and share profiles with you within the next few hours."
    )


# ─── BLOCK F: Timeline ───────────────────────────────────────────────────────

_TIMELINES = {
    "24h":      "We will respond within 24 hours.",
    "few_hrs":  "We will respond within the next few hours.",
    "2_days":   "We will get back to you within 2 business days.",
    "review":   "Our team will review and respond to you shortly.",
    "asap":     "We are treating this as a priority and will respond at the earliest.",
}


# ═══════════════════════════════════════════════════════════════════════════════
# REPLY BUILDERS — one per scenario group
# ═══════════════════════════════════════════════════════════════════════════════

def _make(subject: str, body: str, scenario: str,
          asks: bool = False, llm_used: bool = False,
          whatsapp: str = "") -> Dict[str, Any]:
    return {
        "subject":            subject,
        "body":               body,
        "whatsapp_message":   (whatsapp or body[:200]).strip(),
        "tone":               "formal",
        "asks_for_clarification": asks,
        "template_used":      scenario,
        "llm_used":           llm_used,
    }


# ─── CLIENT: Missing details ──────────────────────────────────────────────────

def reply_client_missing_details(
    extracted: Dict[str, Any],
    needs: List[str],
    sender_name: str,
    signature: str,
) -> Dict[str, Any]:
    tech = extracted.get("technology_needed")
    name = _first_name(sender_name) or "Client"
    known = _understood_training(extracted)
    known_block = f"\n\n{known}" if known else ""
    needs_block = f"\n\n{_needs_section(needs)}" if needs else ""
    action = _action_training_missing(tech)
    tech_label = _title(tech) if tech else "Training"

    body = (
        f"Dear {name},\n\n"
        f"{_ack('new_training_requirement')}"
        f"{known_block}"
        f"{needs_block}\n\n"
        f"{action}\n\n"
        f"We look forward to your response.\n\n"
        f"{signature}"
    )
    wa = (
        f"Hi {name}, thank you for your {tech_label} training requirement. "
        f"We need: {', '.join(needs[:3])}{'...' if len(needs) > 3 else ''}. "
        "Initial search started."
    )
    return _make(
        subject=f"Request for Additional Details — {tech_label} Requirement",
        body=body, scenario="client_missing_details",
        asks=True, whatsapp=wa
    )


# ─── CLIENT: Complete details ─────────────────────────────────────────────────

def reply_client_complete_details(
    extracted: Dict[str, Any],
    sender_name: str,
    signature: str,
    urgency: str = "normal",
) -> Dict[str, Any]:
    tech = extracted.get("technology_needed")
    name = _first_name(sender_name) or "Client"
    known = _understood_training(extracted)
    bud   = _budget_str(extracted)
    bud_note = f"\n\nWe will align trainer recommendations to suit your budget of {bud}." if bud else ""
    special = extracted.get("special_requirements")
    special_note = f"\n\nWe have noted your specific requirement: {special}." if special else ""
    action = _action_training_urgent(tech) if urgency in {"high", "critical"} else _action_training_complete(tech)
    tech_label = _title(tech) if tech else "Training"

    body = (
        f"Dear {name},\n\n"
        f"Thank you for sharing your {tech_label} training requirement with us.\n\n"
        f"{known}"
        f"{special_note}"
        f"{bud_note}\n\n"
        f"{action}\n\n"
        "Should you have any queries, please feel free to reach us.\n\n"
        f"{signature}"
    )
    eta = "within a few hours" if urgency in {"high", "critical"} else "within 24 hours"
    wa = (
        f"Thank you for your {tech_label} training requirement. "
        f"All details noted{' including budget' if bud else ''}. "
        f"Trainer profiles shared {eta}."
    )
    return _make(
        subject=f"Re: {tech_label} Training Requirement — Profiles Being Shortlisted",
        body=body, scenario="client_complete_details",
        asks=False, whatsapp=wa
    )


# ─── CLIENT: Repeat requirement ───────────────────────────────────────────────

def reply_client_repeat(
    extracted: Dict[str, Any],
    sender_name: str,
    signature: str,
) -> Dict[str, Any]:
    result = reply_client_complete_details(extracted, sender_name, signature)
    tech_label = _title(extracted.get("technology_needed")) if extracted.get("technology_needed") else "Training"
    name = _first_name(sender_name) or "Client"
    result["body"] = (
        f"Dear {name},\n\n"
        f"Thank you for choosing Clahan Technologies once again for your {tech_label} training requirement.\n\n"
        + "\n\n".join(result["body"].split("\n\n")[1:])
    )
    result["template_used"] = "client_repeat_requirement"
    return result


# ─── CLIENT: Follow-up on profiles ───────────────────────────────────────────

def reply_client_followup(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "Thank you for following up.\n\n"
        "Our team is actively working on your requirement. "
        "We will share the shortlisted trainer profiles with you shortly.\n\n"
        f"{signature}"
    )
    return _make("Re: Training Requirement — Update", body, "client_followup",
                 whatsapp=f"Hi {name}, our team is working on your requirement and will share profiles shortly.")


# ─── CLIENT: Trainer approved ─────────────────────────────────────────────────

def reply_client_trainer_approved(
    trainer_name: str,
    sender_name: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    trainer = trainer_name or "the selected trainer"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for confirming the selection of {trainer}.\n\n"
        "We will proceed with the next steps including finalising the training schedule, "
        "sharing the Terms of Contract, and coordinating the logistics.\n\n"
        "We will keep you updated at every stage.\n\n"
        f"{signature}"
    )
    return _make(f"Re: Trainer Confirmation — {trainer}", body, "client_trainer_approved",
                 whatsapp=f"Hi {name}, noted — {trainer} confirmed. Proceeding with next steps.")


# ─── CLIENT: Trainer rejected ─────────────────────────────────────────────────

def reply_client_trainer_rejected(
    sender_name: str,
    tech: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    t = _title(tech) if tech else "this requirement"
    body = (
        f"Dear {name},\n\n"
        "Thank you for your feedback on the trainer profiles shared.\n\n"
        f"We understand the shared profiles did not meet your expectations for {t}. "
        "Our team will shortlist alternative trainer profiles and share them with you shortly.\n\n"
        f"{signature}"
    )
    return _make(f"Re: Alternative Trainer Profiles — {t}", body, "client_trainer_rejected",
                 whatsapp=f"Hi {name}, noted. We will share alternative {t} trainer profiles shortly.")


# ─── CLIENT: Reschedule ───────────────────────────────────────────────────────

def reply_client_reschedule(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "Thank you for informing us about the change in training dates.\n\n"
        "We have noted the reschedule request and will coordinate with the trainer to check availability "
        "for the new dates. We will confirm the updated schedule shortly.\n\n"
        f"{signature}"
    )
    return _make("Re: Training Reschedule — Coordination in Progress", body, "client_reschedule",
                 whatsapp=f"Hi {name}, reschedule noted. Checking trainer availability for new dates.")


# ─── CLIENT: Cancellation ─────────────────────────────────────────────────────

def reply_client_cancellation(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "We acknowledge your request to cancel the training.\n\n"
        "We have noted this and will close the requirement accordingly. "
        "Please feel free to reach out whenever you have a new training requirement "
        "and we will be happy to assist.\n\n"
        f"{signature}"
    )
    return _make("Re: Training Cancellation Acknowledged", body, "client_cancellation",
                 whatsapp=f"Hi {name}, training cancellation noted. We will close this requirement.")


# ─── CLIENT: Quote / Proposal ─────────────────────────────────────────────────

def reply_client_quote_request(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "Thank you for your interest in Clahan Technologies.\n\n"
        "We have received your request for a proposal/quote. "
        "To prepare an accurate and relevant proposal, kindly share the following details if not already provided:\n"
        "* Training domain / technology\n"
        "* Number of participants\n"
        "* Training duration and preferred dates\n"
        "* Training mode (Online / Offline / Hybrid)\n"
        "* Location (if offline)\n"
        "* Budget or expected commercial range\n\n"
        "Our team will prepare a detailed proposal and share it with you shortly.\n\n"
        f"{signature}"
    )
    return _make("Re: Training Proposal — Details Required", body, "client_quote_request",
                 asks=True, whatsapp=f"Hi {name}, received your proposal request. Kindly share training details so we can prepare an accurate quote.")


# ─── CLIENT: Invoice / PO ────────────────────────────────────────────────────

def reply_client_invoice_po(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "Thank you for reaching out regarding the invoice/purchase order.\n\n"
        "We have noted your request and our accounts team will review and respond to you shortly. "
        "If you need any specific document or GST details, please let us know.\n\n"
        f"{signature}"
    )
    return _make("Re: Invoice / PO — Noted", body, "client_invoice_po",
                 whatsapp=f"Hi {name}, invoice/PO query noted. Our accounts team will respond shortly.")


# ─── CLIENT: Positive feedback ───────────────────────────────────────────────

def reply_client_feedback_positive(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Client"
    body = (
        f"Dear {name},\n\n"
        "Thank you so much for your wonderful feedback. "
        "We are truly delighted to hear that the training was well received by your team.\n\n"
        "It motivates us to continue delivering quality training programmes. "
        "We look forward to supporting your future training requirements.\n\n"
        f"{signature}"
    )
    return _make("Re: Thank You for Your Feedback", body, "client_feedback_positive",
                 whatsapp=f"Thank you for the great feedback, {name}! Looking forward to future requirements.")


# ─── TRAINER: Interested + missing fields ────────────────────────────────────

_TRAINER_REQUIRED_FIELDS = [
    "Training domain(s) / technology specialisation",
    "Total training experience (years)",
    "List of corporate training programmes conducted",
    "Certifications (if any)",
    "Preferred training mode (Online / Offline / Hybrid)",
    "Availability and preferred schedule",
    "Location / city",
    "Expected commercial charges (per day or per session)",
]


def reply_trainer_interested_missing(
    sender_name: str,
    tech: str,
    missing_fields: List[str],
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    t = _title(tech) if tech else "the training"
    fields = missing_fields or [
        "Training rate per day (INR)",
        "Availability / preferred interview slot",
        "Latest profile / CV",
    ]
    body = (
        f"Dear {name},\n\n"
        f"Thank you for your interest in the {t} training opportunity shared by Clahan Technologies.\n\n"
        "To proceed further and share your profile with the client, kindly provide the following details:\n"
        + _bullet(fields)
        + "\n\nOnce we receive the above, we will review your profile and share it with the client for their consideration.\n\n"
        f"{signature}"
    )
    wa = (
        f"Hi {name}, thank you for your interest in the {t} training. "
        f"Please share: {', '.join(fields[:3])}. We will forward your profile to the client."
    )
    return _make(f"Re: {t} Training — Profile Details Required", body,
                 "trainer_interested_missing", asks=True, whatsapp=wa)


def reply_trainer_interested_complete(
    sender_name: str,
    tech: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    t = _title(tech) if tech else "the training"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for sharing your details for the {t} training requirement.\n\n"
        "We have noted your profile, availability, and commercial details. "
        "We will review and share your profile with the client shortly. "
        "We will keep you updated on the next steps.\n\n"
        f"{signature}"
    )
    wa = (
        f"Hi {name}, profile received for {t} training. "
        "Sharing with client shortly. Will update you on next steps."
    )
    return _make(f"Re: {t} Training — Profile Received", body,
                 "trainer_interested_complete", asks=False, whatsapp=wa)


def reply_trainer_not_interested(
    sender_name: str,
    tech: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    t = _title(tech) if tech else "this training"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for letting us know regarding the {t} training requirement.\n\n"
        "We completely understand and appreciate your response. "
        "We will reach out to you for future training requirements matching your availability and expertise.\n\n"
        f"{signature}"
    )
    return _make(f"Re: {t} Training — Noted", body, "trainer_not_interested",
                 whatsapp=f"Hi {name}, noted. We will reach out for future {t} training requirements.")


def reply_trainer_slots_received(
    sender_name: str,
    tech: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    t = _title(tech) if tech else "the training"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for sharing your availability for the {t} training.\n\n"
        "We have noted your interview slots and will share them with the client for confirmation. "
        "We will get back to you with the confirmed slot as soon as the client responds.\n\n"
        f"{signature}"
    )
    return _make(f"Re: {t} Training — Availability Noted", body, "trainer_slots_received",
                 whatsapp=f"Hi {name}, slots noted for {t} training. Sharing with client. Will confirm soon.")


def reply_trainer_toc_received(
    sender_name: str,
    tech: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    t = _title(tech) if tech else "the training"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for sharing the Terms of Contract and training agenda for the {t} training.\n\n"
        "We have received your documents and will review them. "
        "The final training confirmation details will be shared with you shortly.\n\n"
        f"{signature}"
    )
    return _make(f"Re: {t} Training — ToC Received", body, "trainer_toc_received",
                 whatsapp=f"Hi {name}, ToC and agenda received for {t}. Final confirmation follows shortly.")


def reply_trainer_panel_register(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    body = (
        f"Dear {name},\n\n"
        "Thank you for your interest in joining Clahan Technologies as a trainer.\n\n"
        "To evaluate your profile for suitable training requirements, kindly share the following details:\n"
        + _bullet(_TRAINER_REQUIRED_FIELDS)
        + "\n\nOur team will review your profile and reach out whenever there is a matching requirement.\n\n"
        f"{signature}"
    )
    wa = (
        f"Hi {name}, thank you for your interest in Clahan's trainer panel. "
        "Please share your domain, experience, past trainings, mode, availability, and commercials."
    )
    return _make("Re: Trainer Panel Registration — Profile Details Required",
                 body, "trainer_panel_register", asks=True, whatsapp=wa)


def reply_trainer_payment_query(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    body = (
        f"Dear {name},\n\n"
        "Thank you for reaching out regarding your payment.\n\n"
        "We have noted your query and our accounts team will review the payment status "
        "and get back to you shortly.\n\n"
        f"{signature}"
    )
    return _make("Re: Payment Query — Under Review", body, "trainer_payment_query",
                 whatsapp=f"Hi {name}, payment query noted. Accounts team will update you shortly.")


def reply_trainer_followup_work(sender_name: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Trainer"
    body = (
        f"Dear {name},\n\n"
        "Thank you for staying in touch with us.\n\n"
        "We have noted your availability and will reach out as soon as there is a "
        "training requirement matching your domain and expertise.\n\n"
        f"{signature}"
    )
    return _make("Re: Training Requirements — Will Keep You Posted", body,
                 "trainer_followup_work",
                 whatsapp=f"Hi {name}, noted your availability. Will reach out when a matching requirement comes in.")


# ─── JOB SEEKERS ─────────────────────────────────────────────────────────────

def reply_job_application(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Candidate"
    body = (
        f"Dear {name},\n\n"
        "Thank you for sharing your profile with us.\n\n"
        "We have received your application and our team will review your profile. "
        "We will get in touch with you if there is a suitable opening matching your experience and skill set.\n\n"
        "We appreciate your interest in Clahan Technologies.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "job_application",
                 whatsapp=f"Hi {name}, application received. We will reach out if there is a suitable opening.")


def reply_cv_no_role(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Candidate"
    body = (
        f"Dear {name},\n\n"
        "Thank you for reaching out to Clahan Technologies.\n\n"
        "We have received your profile and will keep it on record. "
        "We will get in touch with you if there is a suitable opening that matches your background.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "cv_no_role",
                 whatsapp=f"Hi {name}, profile received. Will reach out if a suitable opening arises.")


def reply_internship_request(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Student"
    body = (
        f"Dear {name},\n\n"
        "Thank you for your interest in interning with Clahan Technologies.\n\n"
        "We have noted your request. We do not have active internship openings at the moment, "
        "but we will keep your profile on record and reach out if an opportunity arises.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "internship_request",
                 whatsapp=f"Hi {name}, internship request noted. Will reach out if an opening comes up.")


# ─── VENDORS / PARTNERS ───────────────────────────────────────────────────────

def reply_vendor_hotlist(subject: str, signature: str) -> Dict[str, Any]:
    body = (
        "Dear Team,\n\n"
        "Thank you for sharing the hotlist with us.\n\n"
        "We will review the profiles and get back to you if any profile matches our active requirements.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "vendor_hotlist",
                 whatsapp="Thank you for the hotlist. Will review and reach out if any profile matches our requirements.")


def reply_vendor_generic(subject: str, signature: str) -> Dict[str, Any]:
    body = (
        "Dear Team,\n\n"
        "Thank you for reaching out to Clahan Technologies.\n\n"
        "We have noted your message and will connect with you if there is a relevant business or training requirement.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "vendor_generic",
                 whatsapp="Thank you for reaching out. We will connect if there is a relevant requirement.")


# ─── REFERRAL ─────────────────────────────────────────────────────────────────

def reply_referral(
    sender_name: str,
    referrer_name: str,
    subject: str,
    signature: str,
) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Sir/Madam"
    ref  = referrer_name or "a mutual contact"
    body = (
        f"Dear {name},\n\n"
        f"Thank you for reaching out to Clahan Technologies. "
        f"We are glad that {ref} connected us.\n\n"
        "We would be happy to understand your requirement and assist you. "
        "Kindly share the details of what you are looking for and our team will respond promptly.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "referral_introduction",
                 asks=True,
                 whatsapp=f"Hi {name}, thank you for reaching out via {ref}. Please share your requirement.")


# ─── STUDENT / INDIVIDUAL ────────────────────────────────────────────────────

def reply_student_inquiry(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Student"
    body = (
        f"Dear {name},\n\n"
        "Thank you for your interest in training with Clahan Technologies.\n\n"
        "We primarily offer corporate training programmes for organisations and their teams. "
        "We do not currently run open-enrolment individual courses.\n\n"
        "If you are looking for training on behalf of your organisation, we would be happy to assist. "
        "Kindly share your requirement and we will get back to you.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "student_inquiry",
                 whatsapp=f"Hi {name}, we primarily serve corporates. Happy to help if it's an organisational requirement.")


# ─── MEDIA / EVENT ────────────────────────────────────────────────────────────

def reply_media(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Team"
    body = (
        f"Dear {name},\n\n"
        "Thank you for reaching out to Clahan Technologies.\n\n"
        "We have noted your request and will review it. "
        "Our team will get back to you with a response shortly.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "media",
                 whatsapp=f"Hi {name}, thank you for reaching out. Our team will review and respond shortly.")


# ─── FINANCE / COMPLIANCE ─────────────────────────────────────────────────────

def reply_finance(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Team"
    body = (
        f"Dear {name},\n\n"
        "Thank you for reaching out.\n\n"
        "We have noted your communication and our accounts/finance team will review and respond to you shortly.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "finance",
                 whatsapp="Finance query noted. Our accounts team will respond shortly.")


# ─── GOVERNMENT / TENDER ─────────────────────────────────────────────────────

def reply_government(sender_name: str, subject: str, signature: str) -> Dict[str, Any]:
    name = _first_name(sender_name) or "Sir/Madam"
    body = (
        f"Dear {name},\n\n"
        "Thank you for the communication from your esteemed organisation.\n\n"
        "We have noted the details shared and our team will review the requirements. "
        "We will respond formally within the specified timeline.\n\n"
        f"{signature}"
    )
    return _make(_subject_re(subject), body, "government",
                 whatsapp="Government communication noted. We will respond formally within the timeline.")


# ═══════════════════════════════════════════════════════════════════════════════
# MASTER DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════════

def build_auto_reply(
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    context: Dict[str, Any],
    needs: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Master function — given classifier output + extracted fields, returns the
    correct zero-cost reply dict or None if human must handle it.

    Args:
        classification : output of email_classifier.classify_email()
        extracted      : normalised training extraction dict (may be empty for non-training)
        context        : dict with keys: reply_signature, subject, from_name, from_email,
                         trainer_name (optional), referrer_name (optional)
        needs          : list of missing fields (for training emails)

    Returns:
        dict with subject/body/whatsapp_message/template_used/llm_used
        or None if the email requires a human response
    """
    if not classification.get("safe_to_reply"):
        return None
    if classification.get("requires_human"):
        return None

    sig        = _sig(context)
    person     = classification.get("person_type", "unknown")
    scenario   = classification.get("scenario", "unclear")
    urgency    = classification.get("urgency", "normal")
    from_name  = context.get("from_name") or extracted.get("client_name") or ""
    subject    = context.get("subject") or extracted.get("email_subject") or "Your Enquiry"
    tech       = extracted.get("technology_needed")

    # ── Corporate / existing client ──────────────────────────────────────────
    if person in {"corporate_client", "existing_client"}:
        if scenario == "training_cancellation":
            return reply_client_cancellation(from_name, sig)
        if scenario == "training_reschedule":
            return reply_client_reschedule(from_name, sig)
        if scenario == "trainer_approval":
            trainer = context.get("trainer_name") or "the selected trainer"
            return reply_client_trainer_approved(trainer, from_name, sig)
        if scenario == "trainer_rejection":
            return reply_client_trainer_rejected(from_name, tech, sig)
        if scenario == "training_followup":
            return reply_client_followup(from_name, sig)
        if scenario == "quote_request":
            return reply_client_quote_request(from_name, sig)
        if scenario in {"invoice_po_request", "invoice_finance"}:
            return reply_client_invoice_po(from_name, sig)
        if scenario == "agreement_nda":
            return reply_vendor_generic(subject, sig)
        if scenario == "feedback_positive":
            return reply_client_feedback_positive(from_name, sig)
        if scenario == "repeat_requirement":
            return reply_client_repeat(extracted, from_name, sig)
        # Default: training requirement
        if needs:
            return reply_client_missing_details(extracted, needs, from_name, sig)
        return reply_client_complete_details(extracted, from_name, sig, urgency)

    # ── Trainer ──────────────────────────────────────────────────────────────
    if person == "trainer":
        if scenario == "trainer_not_interested":
            return reply_trainer_not_interested(from_name, tech, sig)
        if scenario == "trainer_toc_shared":
            return reply_trainer_toc_received(from_name, tech, sig)
        if scenario == "trainer_slots_shared":
            return reply_trainer_slots_received(from_name, tech, sig)
        if scenario == "trainer_payment_query":
            return reply_trainer_payment_query(from_name, sig)
        if scenario == "trainer_panel_register":
            return reply_trainer_panel_register(from_name, sig)
        if scenario == "trainer_update_profile":
            return reply_trainer_interested_complete(from_name, tech or "Training", sig)
        if scenario == "trainer_followup_work":
            return reply_trainer_followup_work(from_name, sig)
        if scenario == "trainer_profile_shared":
            return reply_trainer_panel_register(from_name, sig)
        # Trainer interested — check missing fields
        missing = context.get("trainer_missing_fields") or []
        if missing:
            return reply_trainer_interested_missing(from_name, tech or "Training", missing, sig)
        return reply_trainer_interested_complete(from_name, tech or "Training", sig)

    # ── Job seekers ──────────────────────────────────────────────────────────
    if person == "job_seeker":
        if scenario == "internship_request":
            return reply_internship_request(from_name, subject, sig)
        if scenario == "cv_no_role":
            return reply_cv_no_role(from_name, subject, sig)
        return reply_job_application(from_name, subject, sig)

    # ── Vendor / partner ─────────────────────────────────────────────────────
    if person == "vendor_partner":
        if scenario == "vendor_hotlist":
            return reply_vendor_hotlist(subject, sig)
        return reply_vendor_generic(subject, sig)

    # ── Referral ─────────────────────────────────────────────────────────────
    if person == "referral":
        ref = context.get("referrer_name") or ""
        return reply_referral(from_name, ref, subject, sig)

    # ── Student ──────────────────────────────────────────────────────────────
    if person == "student":
        return reply_student_inquiry(from_name, subject, sig)

    # ── Media ────────────────────────────────────────────────────────────────
    if person == "media":
        return reply_media(from_name, subject, sig)

    # ── Finance / legal ──────────────────────────────────────────────────────
    if person == "finance_legal":
        return reply_finance(from_name, subject, sig)

    # ── Government ───────────────────────────────────────────────────────────
    if person == "government":
        return reply_government(from_name, subject, sig)

    # ── Consultant (treat like trainer panel) ────────────────────────────────
    if person == "consultant":
        return reply_trainer_panel_register(from_name, sig)

    # ── Unknown / fallback ───────────────────────────────────────────────────
    return reply_vendor_generic(subject, sig)
