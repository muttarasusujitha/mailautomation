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


def _client_simple_reply(client: str, tech: str, subject: str, body_lines: list[str], template_key: str) -> Dict[str, Any]:
    body = (
        f"Dear {client},\n\n"
        + "\n\n".join(body_lines)
        + f"\n\n{SIGNATURE}"
    )
    return _reply(f"Re: {_clean(subject, f'{tech} Trainer Requirement')}", body, template_key)


CONSULTANCY_REPLY_LINES = {
    "client_escalation_delay": (
        "client_escalation_delay_ack",
        [
            "Thank you for following up. We understand the urgency.",
            "We are checking the pending item internally and will prioritize the next update.",
            "We will revert with a concrete status shortly.",
        ],
    ),
    "client_cancels_requirement": (
        "client_cancellation_ack",
        [
            "Thank you for the update.",
            "We have noted that this requirement is cancelled/on hold for now.",
            "We will pause further coordination unless you ask us to resume.",
        ],
    ),
    "client_reopens_requirement": (
        "client_reopen_ack",
        [
            "Thank you for confirming that the requirement is active again.",
            "We will resume coordination and refresh the trainer/profile status accordingly.",
            "We will share the next update shortly.",
        ],
    ),
    "client_asks_contract": (
        "client_contract_request_ack",
        [
            "Thank you for sharing the contract/agreement query.",
            "We will review the required document or legal/commercial input and route it to the concerned team.",
            "We will revert with the next step shortly.",
        ],
    ),
    "client_vendor_registration": (
        "client_vendor_registration_ack",
        [
            "Thank you for sharing the vendor registration/onboarding requirement.",
            "We will review the requested details and coordinate the required company/billing documents.",
            "Please share any portal link or mandatory format if applicable.",
        ],
    ),
    "client_asks_trainer_docs": (
        "client_trainer_docs_ack",
        [
            "Thank you for requesting trainer documents/profile details.",
            "We will check the available trainer profile, credentials, and supporting details and share them shortly.",
            "If you need a specific format, please share it in the same thread.",
        ],
    ),
    "client_asks_customization": (
        "client_customization_ack",
        [
            "Thank you for sharing the customization request.",
            "We will align the agenda/content with the trainer based on your specific topic requirements.",
            "Please share any must-have or excluded topics so we can refine the plan accurately.",
        ],
    ),
    "client_asks_recording": (
        "client_recording_ack",
        [
            "Thank you for checking about session recording.",
            "We will confirm recording feasibility with the trainer and based on the training mode/platform.",
            "We will update you before the session is finalized.",
        ],
    ),
    "client_asks_materials": (
        "client_materials_ack",
        [
            "Thank you for requesting training materials.",
            "We will coordinate with the trainer on slides, handouts, labs, or supporting documents as applicable.",
            "We will share availability of materials shortly.",
        ],
    ),
    "client_asks_attendance": (
        "client_attendance_ack",
        [
            "Thank you for checking about attendance/reporting.",
            "We will coordinate the attendance or completion report requirement for this training.",
            "Please share any preferred format if your team needs one.",
        ],
    ),
    "client_asks_certificate": (
        "client_certificate_ack",
        [
            "Thank you for checking about certificates.",
            "We will verify the certificate/completion documentation requirement and coordinate accordingly.",
            "Please share participant names in the required format if certificates are needed.",
        ],
    ),
    "client_asks_lab_setup": (
        "client_lab_setup_ack",
        [
            "Thank you for sharing the lab/setup query.",
            "We will check the required tools, access, and environment prerequisites with the trainer.",
            "We will share the setup requirements before the session wherever applicable.",
        ],
    ),
    "client_asks_preassessment": (
        "client_assessment_ack",
        [
            "Thank you for asking about assessment/evaluation.",
            "We will check whether pre/post assessment or participant evaluation can be included for this training.",
            "We will revert with the available approach shortly.",
        ],
    ),
    "client_asks_timezone": (
        "client_timezone_ack",
        [
            "Thank you for confirming the timezone requirement.",
            "We will align the schedule using the correct timezone and validate trainer availability accordingly.",
            "Please confirm the preferred timezone if it differs from IST.",
        ],
    ),
    "client_asks_mode_change": (
        "client_mode_change_ack",
        [
            "Thank you for sharing the training mode change.",
            "We will check trainer feasibility for the revised mode and update the coordination plan accordingly.",
            "We will revert if commercials or logistics change due to the mode update.",
        ],
    ),
    "client_asks_location": (
        "client_location_ack",
        [
            "Thank you for sharing the location/venue query.",
            "We will check trainer feasibility for the requested location and coordinate the logistics accordingly.",
            "Please share the venue/city details if not already confirmed.",
        ],
    ),
    "client_asks_batch_split": (
        "client_batch_split_ack",
        [
            "Thank you for sharing the batch split requirement.",
            "We will check trainer availability and commercials for multiple batches or parallel sessions as applicable.",
            "Please share expected batch size and preferred schedule for each batch.",
        ],
    ),
    "client_asks_rate_card": (
        "client_rate_card_ack",
        [
            "Thank you for requesting rate/commercial details.",
            "We will check the applicable trainer commercials for the requirement and share the most relevant pricing information.",
            "Final commercials may vary based on trainer, duration, mode, and schedule.",
        ],
    ),
    "client_asks_availability": (
        "client_availability_ack",
        [
            "Thank you for checking trainer availability.",
            "We will validate the trainer's availability against your preferred dates/timings and revert shortly.",
            "Please share any strict schedule constraints if applicable.",
        ],
    ),
    "client_asks_shortlist_eta": (
        "client_shortlist_eta_ack",
        [
            "Thank you for checking the profile sharing timeline.",
            "We are working on the trainer shortlist and will share suitable profiles as soon as they are ready.",
            "We will prioritize quality and relevance while keeping the turnaround quick.",
        ],
    ),
}


TRAINER_REPLY_LINES = {
    "trainer_not_interested": (
        "trainer_not_interested_ack",
        [
            "Thank you for the update.",
            "We have noted that this requirement is not suitable for you at this time.",
            "We will reach out again if a more relevant opportunity comes up.",
        ],
    ),
    "trainer_partial_availability": (
        "trainer_partial_availability_ack",
        [
            "Thank you for sharing your availability.",
            "We will check this against the client schedule and update you on the next step.",
            "If there are any strict date or timing constraints, please mention them clearly.",
        ],
    ),
    "trainer_commercial_acceptance": (
        "trainer_commercial_acceptance_ack",
        [
            "Thank you for confirming the revised commercials.",
            "We will update the requirement records and proceed with the next coordination step.",
            "We will keep you posted once the client confirms.",
        ],
    ),
    "trainer_commercial_rejection": (
        "trainer_commercial_rejection_ack",
        [
            "Thank you for sharing your commercial feedback.",
            "We have noted that the current budget/rate is not feasible.",
            "We will review internally and update you if there is scope for revision.",
        ],
    ),
    "trainer_slot_confirmed": (
        "trainer_slot_confirmed_ack",
        [
            "Thank you for confirming the slot.",
            "We have noted your availability and will coordinate the discussion/interview details accordingly.",
            "Please keep the slot blocked until we share the final confirmation.",
        ],
    ),
    "trainer_reschedule_request": (
        "trainer_reschedule_request_ack",
        [
            "Thank you for the schedule update.",
            "We have noted your reschedule request and will coordinate revised timing with the client/team.",
            "Please share 2-3 alternate slots if not already shared.",
        ],
    ),
    "trainer_interview_done": (
        "trainer_interview_done_ack",
        [
            "Thank you for the update.",
            "We have noted that the client discussion/interview is completed.",
            "We will follow up internally/client-side and update you on the next step.",
        ],
    ),
    "trainer_selected_ack": (
        "trainer_selected_ack",
        [
            "Thank you for confirming.",
            "We will coordinate the next steps for schedule, documentation, commercials, and final training confirmation as applicable.",
            "Please keep your availability open for the agreed timeline.",
        ],
    ),
    "trainer_toc_shared": (
        "trainer_toc_shared_ack",
        [
            "Thank you for sharing the ToC/course agenda.",
            "We will review it and share it with the client/team for confirmation.",
            "If any changes are requested, we will get back to you.",
        ],
    ),
    "trainer_content_doubt": (
        "trainer_content_doubt_ack",
        [
            "Thank you for highlighting the content/scope point.",
            "We will clarify the exact topics, depth, and expected coverage with the client/team.",
            "Please mention any topics you cannot cover or any minimum duration needed.",
        ],
    ),
    "trainer_logistics_query": (
        "trainer_logistics_query_ack",
        [
            "Thank you for checking the logistics/prerequisites.",
            "We will confirm the platform, participant details, lab/tool setup, and any prerequisites before the session.",
            "Please share any mandatory setup needs from your side.",
        ],
    ),
    "trainer_recording_material_policy": (
        "trainer_recording_material_policy_ack",
        [
            "Thank you for clarifying the recording/material policy.",
            "We have noted your preference/restriction and will align it with the client before final confirmation.",
            "We will let you know if the client has any specific requirement around recording or materials.",
        ],
    ),
    "trainer_payment_query": (
        "trainer_payment_query_ack",
        [
            "Thank you for raising the payment/billing query.",
            "We will check the applicable payment terms, invoice process, GST/TDS handling, and billing details.",
            "We will revert with the relevant confirmation shortly.",
        ],
    ),
    "trainer_onsite_travel_query": (
        "trainer_onsite_travel_query_ack",
        [
            "Thank you for sharing the onsite/travel query.",
            "We will confirm the training location, travel expectations, reimbursement scope, and commercials impact if any.",
            "Please share your travel constraints if applicable.",
        ],
    ),
    "trainer_meeting_issue": (
        "trainer_meeting_issue_ack",
        [
            "Thank you for the update.",
            "We have noted the meeting/link/platform issue and will coordinate support or revised joining details as needed.",
            "Please stay available on email/phone for quick coordination.",
        ],
    ),
    "trainer_training_update": (
        "trainer_training_update_ack",
        [
            "Thank you for sharing the training/session update.",
            "We have noted the status and will coordinate any pending action, issue, material, or feedback item accordingly.",
            "Please keep us posted if anything needs client/team intervention.",
        ],
    ),
    "trainer_referral": (
        "trainer_referral_ack",
        [
            "Thank you for offering a referral.",
            "Please share the trainer's profile, skills, availability, commercials, and contact details for review.",
            "We will evaluate the referred profile against the requirement.",
        ],
    ),
    "trainer_duplicate_reply": (
        "trainer_duplicate_reply_ack",
        [
            "Thank you for the update.",
            "We will check the previous email/details shared and update our records accordingly.",
            "If anything has changed, please share the latest version in this thread.",
        ],
    ),
    "trainer_attachment_issue": (
        "trainer_attachment_issue_ack",
        [
            "Thank you for the attachment update.",
            "We will check the file/link shared and update you if we are unable to access it.",
            "Please ensure the document permissions are open for review if using a drive link.",
        ],
    ),
}


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

    if scenario == "client_confirms_trainer":
        return _client_simple_reply(client, tech, subject, [
            f"Thank you for confirming the trainer for the {tech} requirement.",
            "We have noted your approval and will proceed with the next coordination steps, including interview/training schedule alignment and commercial closure as applicable.",
            "We will keep you updated on the next action shortly.",
        ], "client_trainer_confirmation_ack")

    if scenario == "client_rejects_trainer":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We have noted that the shared trainer profile is not suitable for the {tech} requirement.",
            "We will review alternate trainer options and share more relevant profiles for your consideration.",
        ], "client_trainer_rejection_ack")

    if scenario == "client_requests_replacement":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We will arrange alternate trainer profiles for the {tech} requirement based on your feedback.",
            "If there are any specific gaps to address, please share them so we can refine the next shortlist accordingly.",
        ], "client_replacement_request_ack")

    if scenario == "client_confirms_interview_slot":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for confirming the interview/discussion slot.",
            "We will coordinate the schedule with the trainer and share the meeting link/final confirmation shortly.",
            "Please let us know if any participant details need to be added to the invite.",
        ], "client_interview_slot_confirmation_ack")

    if scenario == "client_requests_interview_slots":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for your message.",
            f"We will coordinate interview/discussion slot options for the {tech} trainer and share suitable availability shortly.",
            "Once a slot is confirmed, we will share the meeting link and final schedule details.",
        ], "client_interview_slots_request_ack")

    if scenario == "client_asks_meeting_link":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for checking.",
            "We will verify the confirmed schedule and share the meeting/joining link shortly.",
            "If there has been any change in timing or participants, please let us know.",
        ], "client_meeting_link_request_ack")

    if scenario == "client_asks_toc":
        return _client_simple_reply(client, tech, subject, [
            f"Thank you for requesting the ToC/course agenda for the {tech} training.",
            "We will coordinate with the trainer and share the relevant course outline for your review.",
            "If you have any specific topics or participant level to include, please share them.",
        ], "client_toc_request_ack")

    if scenario == "client_sends_po":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the purchase order.",
            "We have received it and will review the details for billing, training scope, and commercial alignment.",
            "We will proceed with invoice/logistics coordination shortly.",
        ], "client_po_received_ack")

    if scenario == "client_asks_invoice":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for your message.",
            "We will check the invoice status and share the invoice copy/update shortly.",
            "If any PO number, GST details, or billing address needs to be used, please share it in the same thread.",
        ], "client_invoice_request_ack")

    if scenario == "client_payment_terms":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the payment terms query.",
            "We have noted it and will align internally on the applicable billing/payment terms for this engagement.",
            "We will revert with the confirmation shortly.",
        ], "client_payment_terms_ack")

    if scenario == "client_budget_negotiation":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the budget/commercial feedback.",
            f"We will review the commercials for the {tech} requirement and check the best feasible alignment with the trainer.",
            "We will revert with an updated option or recommendation shortly.",
        ], "client_budget_negotiation_ack")

    if scenario == "client_changes_training_details":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the revised training details.",
            "We have noted the change and will align the trainer search/schedule accordingly.",
            "If any duration, timing, mode, participant count, or date is still tentative, please confirm so we can keep the plan accurate.",
        ], "client_training_change_ack")

    if scenario == "client_asks_final_logistics":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for checking on the final logistics.",
            "We will compile the confirmed trainer details, schedule, meeting link, and any required coordination notes and share them shortly.",
            "Please let us know if there are additional participants or internal instructions to include.",
        ], "client_final_logistics_ack")

    if scenario == "client_asks_status_update":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for following up.",
            f"We are checking the current status for the {tech} requirement and will update you shortly.",
            "We will share the next actionable update as soon as it is available.",
        ], "client_status_update_ack")

    if scenario == "client_asks_more_profiles":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We will look for additional trainer profiles for the {tech} requirement.",
            "If there are specific skills, experience level, budget, or location preferences to prioritize, please share them.",
        ], "client_more_profiles_ack")

    if scenario == "client_training_completed":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for confirming that the training/session has been completed.",
            "We will proceed with the required closure steps and coordinate any pending feedback, documentation, or billing items.",
            "Please share participant feedback if available.",
        ], "client_training_completion_ack")

    if scenario == "client_feedback_shared":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the feedback.",
            "We have noted it and will review it with the relevant internal/trainer team.",
            "If any corrective action or follow-up session is required, we will coordinate accordingly.",
        ], "client_feedback_ack")

    if scenario == "client_thanks":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the confirmation.",
            "We have noted your message and will proceed with the next steps as applicable.",
        ], "client_thanks_ack")

    if scenario in CONSULTANCY_REPLY_LINES:
        template_key, lines = CONSULTANCY_REPLY_LINES[scenario]
        return _client_simple_reply(client, tech, subject, list(lines), template_key)

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

    if scenario in TRAINER_REPLY_LINES:
        template_key, lines = TRAINER_REPLY_LINES[scenario]
        trainer_name = _sender_name(sender_name)
        body = (
            f"Dear {trainer_name},\n\n"
            + "\n\n".join(lines)
            + f"\n\n{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, f'{tech} Training Opportunity')}", body, template_key)

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
