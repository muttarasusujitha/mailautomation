"""Deterministic reply templates for classified emails."""
from typing import Any, Dict


SIGNATURE = "Regards,\nRecruitment Team\nClahan Technologies"
TRAINER_SIGNATURE = "Regards,\nTrainerSync Team"


def _clean(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _client_name(extracted: Dict[str, Any]) -> str:
    name = _clean(extracted.get("client_name"), "Client")
    if "@" in name.lower() or name.lower() in {"client", "team"}:
        return "Client"
    return name


def _sender_name(sender_name: str, default: str = "Trainer") -> str:
    name = _clean(sender_name, default)
    if "@" in name.lower() or name.lower() in {"sender", "team", "client"}:
        return default
    return name


def _technology(extracted: Dict[str, Any]) -> str:
    return _clean(extracted.get("technology_needed") or extracted.get("technology") or extracted.get("domain"), "training")


def _duration(extracted: Dict[str, Any]) -> str:
    if extracted.get("duration_text"):
        return str(extracted["duration_text"])
    if extracted.get("duration_days"):
        return f"{extracted['duration_days']} days"
    if extracted.get("duration_hours"):
        return f"{extracted['duration_hours']} hours"
    return "To be confirmed"


def _dates_or_timing(extracted: Dict[str, Any]) -> str:
    return _clean(
        extracted.get("training_dates")
        or extracted.get("preferred_dates")
        or " to ".join(part for part in [extracted.get("timeline_start"), extracted.get("timeline_end")] if part)
        or extracted.get("timing"),
        "To be confirmed",
    )


def _budget(extracted: Dict[str, Any]) -> str:
    currency = _clean(extracted.get("budget_currency"), "INR")
    if extracted.get("budget_range"):
        return str(extracted["budget_range"])
    if extracted.get("budget_min") and extracted.get("budget_max"):
        return f"{currency} {extracted['budget_min']} - {extracted['budget_max']}"
    if extracted.get("budget_total"):
        return f"{currency} {extracted['budget_total']}"
    if extracted.get("budget_per_day"):
        return f"{currency} {extracted['budget_per_day']} per day"
    return "To be confirmed"


def _missing_lines(extracted: Dict[str, Any]) -> str:
    missing = extracted.get("needs_clarification") or []
    return "\n".join(f"* {item}" for item in missing)


def _details_block(extracted: Dict[str, Any]) -> str:
    rows = [
        ("Technology/Domain", _technology(extracted)),
        ("Duration", _duration(extracted)),
        ("Dates/Timings", _dates_or_timing(extracted)),
        ("Mode/Location", _clean(extracted.get("mode"), "To be confirmed")),
        ("Participant Count", _clean(extracted.get("participant_count"), "To be confirmed")),
        ("Participant Level", _clean(extracted.get("audience_level"), "To be confirmed")),
        ("Client Domain", _clean(extracted.get("client_domain") or extracted.get("client_industry"), "To be confirmed")),
        ("Budget/Commercial Range", _budget(extracted)),
    ]
    topics = _clean(extracted.get("topics") or extracted.get("custom_topics"))
    if topics:
        rows.append(("Topics", topics))
    return "\n".join(f"{label}: {value}" for label, value in rows)


def _safe_ack(sender_name: str, subject: str) -> Dict[str, Any]:
    name = _clean(sender_name, "Sender")
    return {
        "subject": f"Re: {_clean(subject, 'Your Email')}",
        "body": (
            f"Dear {name},\n\n"
            "Thank you for your email.\n\n"
            "We have received your message and our team will review it carefully before responding further.\n\n"
            f"{SIGNATURE}"
        ),
        "auto_send_safe": False,
        "template_key": "human_review_ack",
    }


def _reply(subject: str, body: str, template_key: str, auto_send_safe: bool = True) -> Dict[str, Any]:
    return {
        "subject": subject,
        "body": body,
        "auto_send_safe": auto_send_safe,
        "template_key": template_key,
    }


def _client_missing_details_reply(client: str, tech: str, missing: str) -> Dict[str, Any]:
    body = (
        f"Dear {client},\n\n"
        f"Thank you for sharing your {tech} training requirement.\n\n"
        "To help us refine the trainer shortlist, kindly share only the following missing details:\n\n"
        f"{missing}\n\n"
        "Meanwhile, we will begin the initial trainer search based on the information currently available.\n\n"
        f"{SIGNATURE}"
    )
    return _reply(f"Re: {tech} Trainer Requirement", body, "client_missing_details")


def _client_details_ack_reply(
    client: str,
    tech: str,
    extracted: Dict[str, Any],
    template_key: str,
    intro: str,
) -> Dict[str, Any]:
    body = (
        f"Dear {client},\n\n"
        f"{intro}\n\n"
        "We have noted the following details:\n\n"
        f"{_details_block(extracted)}\n\n"
        f"We will proceed with the trainer search for your {tech} requirement and share suitable profiles with availability and commercials for your review shortly.\n\n"
        f"{SIGNATURE}"
    )
    return _reply(f"Re: {tech} Trainer Requirement", body, template_key)


def build_auto_reply(
    classification: Dict[str, Any],
    extracted: Dict[str, Any],
    subject: str = "",
    sender_name: str = "",
) -> Dict[str, Any]:
    """Return a deterministic reply for classifier output and extracted fields."""
    if classification.get("requires_human") or not classification.get("auto_reply_allowed", True):
        return _safe_ack(sender_name, subject)

    scenario = classification.get("scenario") or "general_enquiry"
    tech = _technology(extracted)
    client = _client_name(extracted)
    missing = _missing_lines(extracted)

    if scenario in {"new_training_requirement", "quote_request"}:
        if missing:
            return _client_missing_details_reply(client, tech, missing)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_requirement_ack",
            "Thank you for sharing the training requirement details.",
        )

    if scenario == "client_sent_details":
        if missing:
            return _client_missing_details_reply(client, tech, missing)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_details_ack",
            "Thank you for sharing the required details.",
        )

    if scenario == "client_asks_profiles":
        if missing:
            return _client_missing_details_reply(client, tech, missing)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_profiles_requested_ack",
            "Thank you for confirming the requirement and requesting suitable trainer profiles.",
        )

    if scenario == "client_updates_requirement":
        if missing:
            return _client_missing_details_reply(client, tech, missing)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_requirement_update_ack",
            "Thank you for sharing the updated requirement details.",
        )

    if scenario == "reschedule":
        body = (
            f"Dear {client},\n\n"
            "Thank you for the schedule update.\n\n"
            "We have noted the revised dates/timings below and will align trainer availability accordingly:\n\n"
            f"{_details_block(extracted)}\n\n"
            "We will come back with suitable trainer availability and commercials for your review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Trainer Requirement", body, "client_reschedule_ack")

    if scenario == "trainer_interested":
        trainer_name = _sender_name(sender_name)
        body = (
            f"Dear {trainer_name},\n\n"
            "Thank you for your response.\n\n"
            "To proceed further, kindly share the below details:\n\n"
            "* Total years of experience\n"
            "* Number of trainings conducted previously\n"
            "* Relevant certifications\n"
            "* Preferred training mode (Online / Offline)\n"
            "* Availability for Full-Day or Half-Day sessions\n"
            "* Expected commercial charges per day/session\n"
            "* Current location\n"
            "* Availability for the mentioned dates\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_interested_ack")

    if scenario == "trainer_details_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for sharing your profile, availability, and commercial details.\n\n"
            "We will review them for the requirement and update you with the next steps shortly.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_details_ack")

    if scenario == "trainer_credentials_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for sharing your profile/credentials.\n\n"
            "Kindly also share your availability and commercials for this requirement so we can proceed with client review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_credentials_ack")

    if scenario == "trainer_commercials_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for sharing your commercial details.\n\n"
            "Kindly confirm your availability for the proposed schedule as well, so we can share the complete profile with the client.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_commercials_ack")

    if scenario == "trainer_slots_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for sharing your availability/slots.\n\n"
            "We will align this with the client schedule and update you with the next step shortly.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_slots_ack")

    if scenario == "trainer_more_details":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for your response.\n\n"
            "At this stage, we are first checking your interest, availability, and commercials. Confirmed client details will be shared once your profile is shortlisted for the next step.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_more_details")

    if scenario == "trainer_unavailable":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for the update. We have noted your unavailability for this requirement.\n\n"
            "We will reach out for suitable future opportunities.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_unavailable_ack")

    if scenario == "job_application":
        body = (
            "Dear Candidate,\n\n"
            "Thank you for sharing your profile.\n\n"
            "We will review your details and get back to you if there is a suitable opening or trainer engagement.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Profile Received')}", body, "job_application_ack")

    if scenario == "vendor_hotlist":
        body = (
            "Dear Vendor,\n\n"
            "Thank you for sharing the profiles/hotlist.\n\n"
            "We will review the details and reach out if there is a matching requirement.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Profiles Received')}", body, "vendor_hotlist_ack")

    if scenario == "referral":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for the referral.\n\n"
            "We will review the shared details and reach out if the profile or requirement matches our current needs.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Referral Received')}", body, "referral_ack")

    if scenario == "student_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Student')},\n\n"
            "Thank you for reaching out.\n\n"
            "We have received your training/course enquiry and will route it to the appropriate team for review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Training Enquiry')}", body, "student_enquiry_ack")

    if scenario == "government_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for sharing the government/public sector training enquiry.\n\n"
            "We will review the requirement details and route it to the concerned team for the next step.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Government Training Enquiry')}", body, "government_enquiry_ack")

    if scenario == "media_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for reaching out.\n\n"
            "We have received your media/press enquiry and will route it to the appropriate team for review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Media Enquiry')}", body, "media_enquiry_ack")

    if scenario == "partnership":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for sharing the partnership/collaboration enquiry.\n\n"
            "We will review the details and get back to you if there is a suitable opportunity to proceed.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Partnership Enquiry')}", body, "partnership_ack")

    if scenario == "finance_legal":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for sharing the finance/legal related details.\n\n"
            "We have received your message and will route it to the concerned team for review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Your Email')}", body, "finance_legal_ack")

    if scenario == "general_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for reaching out.\n\n"
            "We have received your message and will route it to the appropriate team for review.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Your Email')}", body, "general_enquiry_ack")

    return _safe_ack(sender_name, subject)
