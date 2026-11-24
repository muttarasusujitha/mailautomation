"""Deterministic reply templates for classified emails."""
import re
from typing import Any, Dict


from app.agents.natural_voice import ANNAPURNA, apply_voice, choose_voice, signature_for

CLIENT_SIGNATURE = signature_for(ANNAPURNA)
TRAINER_SIGNATURE = signature_for(ANNAPURNA)
SIGNATURE = CLIENT_SIGNATURE


def _clean(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _hostinger_style_body(body: str, hint: str = "") -> str:
    """Apply Annapurna's or Murali's sent-mail voice without changing the facts."""
    text = str(body or "")
    text = re.sub(r"\bDevops\s+Devops\b", "DevOps", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDevops\b", "DevOps", text)
    text = text.replace("TrainerSync Team", "Clahan Technologies")
    return apply_voice(text, choose_voice(hint))


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
    requested_details = extracted.get("requested_details") or []
    if isinstance(requested_details, (list, tuple, set)):
        profile_markers = ("cv", "resume", "profile", "linkedin", "linked in")
        if any(
            any(marker in str(item or "").lower() for marker in profile_markers)
            for item in requested_details
        ):
            return ""

    missing = list(extracted.get("needs_clarification") or [])
    if extracted.get("duration_inferred_from_dates") and "Training duration" not in missing:
        missing.insert(0, "Training duration")
    return "\n".join(f"* {item}" for item in missing)


def _details_block(extracted: Dict[str, Any]) -> str:
    rows = [
        ("Technology", _technology(extracted)),
        ("Duration", _duration(extracted)),
        ("Dates", _dates_or_timing(extracted)),
        ("Mode", _clean(extracted.get("mode"), "To be confirmed")),
        ("Participant Count", _clean(extracted.get("participant_count"), "To be confirmed")),
        ("Participant Level", _clean(extracted.get("audience_level"), "To be confirmed")),
        ("Client Domain", _clean(extracted.get("client_domain") or extracted.get("client_industry"), "To be confirmed")),
        ("Commercials", _budget(extracted)),
    ]
    topics = _clean(extracted.get("topics") or extracted.get("custom_topics"))
    if topics:
        rows.append(("Topics", topics))
    return "\n".join(f"{label}: {value}" for label, value in rows)


def _client_short_requirement_ack(
    client: str,
    tech: str,
    extracted: Dict[str, Any] | None = None,
    template_key: str = "client_requirement_ack",
    extra_text: str = "",
    intro: str = "",
) -> Dict[str, Any]:
    """Every requirement acknowledgement uses the one professional version pool.

    The domain string is read from the requirement input, in this order:
    technology_needed, technology, domain. That exact string is placed in the
    sentence. There is no template per domain name. When none of those fields
    is present, the note says "training requirement". Days, mode, topics, and
    lab hours are filled in only when this requirement has them. The older
    intro is not the opening.
    """
    del intro
    # Imported lazily: inbox already imports this module while it loads.
    from app.routes.inbox import _client_short_requirement_ack as render_ack

    payload = dict(extracted or {})
    if client and not _clean(payload.get("client_name")):
        payload["client_name"] = client
    if tech and not _clean(payload.get("technology_needed") or payload.get("technology") or payload.get("domain")):
        payload["technology_needed"] = tech
    if extra_text and not payload.get("needs_clarification"):
        items = []
        for line in str(extra_text).splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)
        if items:
            payload["needs_clarification"] = items
    reply = render_ack(payload)
    return {
        "subject": reply.get("subject") or f"Re: {_clean(tech, 'training')} Trainer Requirement",
        "body": reply.get("body") or "",
        "auto_send_safe": True,
        "template_key": template_key,
    }


def _safe_ack(sender_name: str, subject: str) -> Dict[str, Any]:
    name = _clean(sender_name, "Sender")
    body = (
        f"Dear {name},\n\n"
        "Thanks for your email.\n\n"
        "We will review it and reply.\n\n"
        f"{TRAINER_SIGNATURE}"
    )
    return {
        "subject": f"Re: {_clean(subject, 'Your Email')}",
        "body": apply_voice(body, ANNAPURNA),
        "auto_send_safe": False,
        "template_key": "human_review_ack",
    }


def _reply(subject: str, body: str, template_key: str, auto_send_safe: bool = True) -> Dict[str, Any]:
    return {
        "subject": subject,
        "body": _hostinger_style_body(body, template_key),
        "auto_send_safe": auto_send_safe,
        "template_key": template_key,
    }


_SITUATION_KEYS = {
    "toc": "client_toc_only",
    "lab_cost": "client_lab_cost_grounded",
    "toc_and_lab_cost": "client_toc_and_lab_cost",
    "invoice": "client_invoice_request_ack",
    "po": "client_po_received_ack",
    "payment": "client_payment_terms_ack",
}


def compose_typed_client_reply(
    kind: str,
    client_name: str,
    subject: str,
    lines: list[str],
    *,
    technology: str = "",
) -> Dict[str, Any]:
    """Render one situation in one voice. Finance uses Murali; coordination uses Annapurna."""
    template_key = _SITUATION_KEYS.get(kind, "client_toc_only")
    name = _clean(client_name, "Team").split()[0]
    if name.lower() in {"client", "team", "sender"}:
        name = "Team"
    clean_subject = _clean(subject)
    if clean_subject.lower().startswith("re:"):
        subject_line = clean_subject
    elif clean_subject:
        subject_line = f"Re: {clean_subject}"
    else:
        subject_line = f"Re: {_clean(technology, 'Your request')}"
    spoken = [str(line).strip() for line in lines if str(line or "").strip()]
    body = f"Dear {name},\n\n" + "\n\n".join(spoken) + f"\n\n{SIGNATURE}"
    return _reply(subject_line, body, template_key)


def render_delivery_reply(
    *,
    client_name: str,
    subject: str,
    technology: str = "",
    toc_requested: bool = False,
    lab_requested: bool = False,
    toc_attached: bool = False,
    lab_attached: bool = False,
    lab_sentence: str = "",
    missing_lab: str = "",
    toc_missing: str = "",
    closing_note: str = "",
) -> Dict[str, Any]:
    """One ToC and/or lab-cost reply. Callers attach every ready file to this same mail."""
    tech = _clean(technology, "the training")
    if toc_requested and lab_requested:
        kind = "toc_and_lab_cost"
        lines = [f"Thanks for sharing the ToC and lab-cost request for the {tech} training."]
    elif toc_requested:
        kind = "toc"
        lines = [f"Thanks for sharing the ToC request for the {tech} training."]
    else:
        kind = "lab_cost"
        lines = ["Thanks for sharing the lab-cost request."]
    if toc_requested:
        if toc_attached:
            lines.append("Please find the day-wise ToC attached.")
        elif toc_missing:
            lines.append(f"To prepare the ToC, please confirm {toc_missing}.")
        else:
            lines.append("The day-wise ToC will be prepared from the technology and duration you shared.")
    if lab_requested:
        if lab_attached:
            lines.append(_clean(lab_sentence, "Please find the lab-cost estimate attached."))
        elif missing_lab:
            lines.append(f"To prepare the lab-cost total, please confirm {missing_lab}.")
        else:
            lines.append("The lab-cost calculation will use these inputs and stay with this request.")
    if toc_requested and lab_requested:
        lines.append("Both are covered in this one mail.")
    if closing_note:
        lines.append(closing_note)
    return compose_typed_client_reply(kind, client_name, subject, lines, technology=tech)


def _client_missing_details_reply(
    client: str,
    tech: str,
    missing: str,
    extracted: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return _client_short_requirement_ack(
        client,
        tech,
        extracted=extracted,
        template_key="client_missing_details",
        extra_text=missing,
    )


def _client_details_ack_reply(
    client: str,
    tech: str,
    extracted: Dict[str, Any],
    template_key: str,
    intro: str,
) -> Dict[str, Any]:
    return _client_short_requirement_ack(client, tech, extracted, template_key, intro=intro)


def _client_simple_reply(client: str, tech: str, subject: str, body_lines: list[str], template_key: str) -> Dict[str, Any]:
    body = (
        f"Dear {client},\n\n"
        + "\n\n".join(body_lines)
        + f"\n\n{SIGNATURE}"
    )
    return _reply(f"Re: {_clean(subject, f'{tech} Trainer Requirement')}", body, template_key)


CONSULTANCY_REPLY_LINES = {
    "client_asks_technology_catalogue": (
        "client_technology_catalogue_ack",
        [
            "Thanks for asking about our training catalogue.",
            "We run instructor-led courses across software, cloud, DevOps, data, AI, and cybersecurity.",
            "Please share the technologies you need, and we will send the closest options.",
        ],
    ),
    "client_escalation_delay": (
        "client_escalation_delay_ack",
        [
            "Thanks for following up. We can see this is urgent.",
            "We are checking the pending item and will send the next update.",
        ],
    ),
    "client_cancels_requirement": (
        "client_cancellation_ack",
        [
            "Thanks for the update. We have put this requirement on hold.",
            "We will wait to hear from you before doing anything further.",
        ],
    ),
    "client_reopens_requirement": (
        "client_reopen_ack",
        [
            "Thanks for confirming that this requirement is active again.",
            "We will pick it up and share the next update.",
        ],
    ),
    "client_asks_contract": (
        "client_contract_request_ack",
        [
            "Thanks for the agreement question.",
            "We will check the document and send the next step.",
        ],
    ),
    "client_vendor_registration": (
        "client_vendor_registration_ack",
        [
            "Thanks for the vendor registration request.",
            "We will check the company and billing documents you need.",
            "Please share the portal link or the format if there is one.",
        ],
    ),
    "client_asks_trainer_docs": (
        "client_trainer_docs_ack",
        [
            "Thanks for asking for the trainer documents.",
            "We will check the profile and supporting details and send them for your review.",
            "If you need a specific format, please send it in this thread.",
        ],
    ),
    "client_asks_customization": (
        "client_customization_ack",
        [
            "Thanks for the customization request.",
            "We will align the agenda with the trainer around the topics you listed.",
            "Please share any topics that must be included or left out.",
        ],
    ),
    "client_asks_recording": (
        "client_recording_ack",
        [
            "Thanks for checking on session recording.",
            "We will confirm this with the trainer and the training platform, and update you before the session is fixed.",
        ],
    ),
    "client_asks_materials": (
        "client_materials_ack",
        [
            "Thanks for asking about the training materials.",
            "We will check slides, handouts, and labs with the trainer and tell you what can be shared.",
        ],
    ),
    "client_asks_attendance": (
        "client_attendance_ack",
        [
            "Thanks for checking on attendance.",
            "We will arrange the attendance or completion report for this training.",
            "Please share the format if your team needs a specific one.",
        ],
    ),
    "client_asks_certificate": (
        "client_certificate_ack",
        [
            "Thanks for checking on certificates.",
            "We will confirm what completion document we can provide.",
            "Please share the participant names in the format you need.",
        ],
    ),
    "client_asks_lab_setup": (
        "client_lab_setup_ack",
        [
            "Thanks for the lab setup question.",
            "We will check the tools, access, and setup with the trainer and send the requirements before the session.",
        ],
    ),
    "client_asks_preassessment": (
        "client_assessment_ack",
        [
            "Thanks for asking about assessment.",
            "We will check whether a pre or post assessment can be included, and send what we can offer.",
        ],
    ),
    "client_asks_timezone": (
        "client_timezone_ack",
        [
            "Thanks for the timezone note.",
            "We will set the schedule in that timezone and check the trainer's availability.",
            "Please confirm the timezone if it is not IST.",
        ],
    ),
    "client_asks_mode_change": (
        "client_mode_change_ack",
        [
            "Thanks for the mode change.",
            "We will check whether the trainer can do the revised mode.",
            "We will write back if the commercials or logistics need to change.",
        ],
    ),
    "client_asks_location": (
        "client_location_ack",
        [
            "Thanks for the location question.",
            "We will check whether the trainer can travel to that location.",
            "Please share the city and venue if they are not confirmed yet.",
        ],
    ),
    "client_asks_batch_split": (
        "client_batch_split_ack",
        [
            "Thanks for the batch split request.",
            "We will check trainer availability and commercials for the extra batches.",
            "Please share the batch size and preferred dates for each batch.",
        ],
    ),
    "client_asks_rate_card": (
        "client_rate_card_ack",
        [
            "Thanks for asking about the rate.",
            "We will check the trainer commercials for this requirement and send them for your review.",
            "The final figure can change with the trainer, duration, mode, and dates.",
        ],
    ),
    "client_asks_availability": (
        "client_availability_ack",
        [
            "Thanks for checking availability.",
            "We will match the trainer's dates with yours and write back.",
            "Please share any dates that cannot move.",
        ],
    ),
    "client_asks_shortlist_eta": (
        "client_shortlist_eta_ack",
        [
            "Thanks for checking on the profiles.",
            "We are preparing the trainer shortlist and will send profiles with commercials and availability.",
        ],
    ),
}


TRAINER_REPLY_LINES = {
    "trainer_not_interested": (
        "trainer_not_interested_ack",
        [
            "Thanks for letting us know.",
            "We will write if a closer requirement comes up.",
        ],
    ),
    "trainer_partial_availability": (
        "trainer_partial_availability_ack",
        [
            "Thanks for sharing your availability.",
            "We will check it against the client dates and update you.",
            "Please mention any dates that cannot move.",
        ],
    ),
    "trainer_commercial_acceptance": (
        "trainer_commercial_acceptance_ack",
        [
            "Thanks for confirming the revised commercials.",
            "We will take this to the client and update you once they confirm.",
        ],
    ),
    "trainer_commercial_rejection": (
        "trainer_commercial_rejection_ack",
        [
            "Thanks for the commercial feedback.",
            "We have noted that this rate does not work.",
            "We will update you if the budget can be revised.",
        ],
    ),
    "trainer_slot_confirmed": (
        "trainer_slot_confirmed_ack",
        [
            "Thanks for confirming the slot.",
            "Please keep it blocked until we send the final confirmation.",
        ],
    ),
    "trainer_reschedule_request": (
        "trainer_reschedule_request_ack",
        [
            "Thanks for the schedule update.",
            "We will check a new time with the client.",
            "Please share two or three other slots if you have not already.",
        ],
    ),
    "trainer_interview_done": (
        "trainer_interview_done_ack",
        [
            "Thanks for the update. We have noted that the client discussion is done.",
            "We will update you on the next step.",
        ],
    ),
    "trainer_selected_ack": (
        "trainer_selected_ack",
        [
            "Thanks for confirming.",
            "We will share the schedule and the remaining documents next.",
            "Please keep the agreed dates open.",
        ],
    ),
    "trainer_toc_shared": (
        "trainer_toc_shared_ack",
        [
            "Thanks for sharing the ToC.",
            "We will review it and send it to the client. We will come back if they ask for changes.",
        ],
    ),
    "trainer_content_doubt": (
        "trainer_content_doubt_ack",
        [
            "Thanks for flagging the scope.",
            "We will confirm the topics and depth with the client.",
            "Please mention any topics you cannot cover, or a minimum duration you need.",
        ],
    ),
    "trainer_logistics_query": (
        "trainer_logistics_query_ack",
        [
            "Thanks for checking the setup.",
            "We will confirm the platform, participants, and lab access before the session.",
            "Please share anything you need installed before then.",
        ],
    ),
    "trainer_recording_material_policy": (
        "trainer_recording_material_policy_ack",
        [
            "Thanks for explaining your recording and material preference.",
            "We will check it with the client before the training is confirmed.",
        ],
    ),
    "trainer_payment_query": (
        "trainer_payment_query_ack",
        [
            "Thanks for the payment question.",
            "We will check the payment terms, invoice process, and GST or TDS handling, and confirm them.",
        ],
    ),
    "trainer_onsite_travel_query": (
        "trainer_onsite_travel_query_ack",
        [
            "Thanks for the travel question.",
            "We will confirm the location, what travel is covered, and whether it changes the commercials.",
            "Please share any travel limits from your side.",
        ],
    ),
    "trainer_meeting_issue": (
        "trainer_meeting_issue_ack",
        [
            "Thanks for flagging the meeting problem.",
            "We will send a working link or a revised joining detail.",
            "Please stay reachable on email or phone while we sort it.",
        ],
    ),
    "trainer_training_update": (
        "trainer_training_update_ack",
        [
            "Thanks for the session update.",
            "Please tell us if you need anything from the client.",
        ],
    ),
    "trainer_referral": (
        "trainer_referral_ack",
        [
            "Thanks for the referral.",
            "Please share the trainer's profile, skills, availability, commercials, and contact details.",
        ],
    ),
    "trainer_duplicate_reply": (
        "trainer_duplicate_reply_ack",
        [
            "Thanks for the update.",
            "We will use the latest details in this thread. Please send a fresh copy if anything changed.",
        ],
    ),
    "trainer_attachment_issue": (
        "trainer_attachment_issue_ack",
        [
            "Thanks for the file update.",
            "We will open it and write back if we cannot access it.",
            "If it is a drive link, please leave the permission open.",
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
    person_type = str(classification.get("person_type") or "").strip().lower()
    if (
        scenario.startswith("trainer_")
        and person_type != "trainer"
        and extracted.get("is_training_request")
        and not extracted.get("is_non_client_email")
    ):
        scenario = "client_sent_details" if not _missing_lines(extracted) else "new_training_requirement"
    tech = _technology(extracted)
    client = _client_name(extracted)
    missing = _missing_lines(extracted)

    if scenario in {"new_training_requirement", "quote_request"}:
        if missing:
            return _client_missing_details_reply(client, tech, missing, extracted)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_requirement_ack",
            "Thank you for sharing the training requirement details.",
        )

    if scenario == "client_sent_details":
        if missing:
            return _client_missing_details_reply(client, tech, missing, extracted)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_details_ack",
            "Thank you for sharing the required details.",
        )

    if scenario == "client_asks_profiles":
        if missing:
            return _client_missing_details_reply(client, tech, missing, extracted)
        return _client_details_ack_reply(
            client,
            tech,
            extracted,
            "client_profiles_requested_ack",
            "Thank you for confirming the requirement and requesting suitable trainer profiles.",
        )

    if scenario == "client_updates_requirement":
        if missing:
            return _client_missing_details_reply(client, tech, missing, extracted)
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
            "Thanks for the schedule update.\n\n"
            "We have noted the revised dates below and will check trainer availability:\n\n"
            f"{_details_block(extracted)}\n\n"
            "We will come back with suitable trainer availability and commercials for your review.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Trainer Requirement", body, "client_reschedule_ack")

    if scenario == "client_confirms_trainer":
        return _client_simple_reply(client, tech, subject, [
            f"Thanks for confirming the trainer for the {tech} requirement.",
            "We will set the schedule and close the commercials next.",
        ], "client_trainer_confirmation_ack")

    if scenario == "client_rejects_trainer":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We have noted that this profile is not the right fit for the {tech} requirement.",
            "We will send other profiles for your review.",
        ], "client_trainer_rejection_ack")

    if scenario == "client_requests_replacement":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We will send other trainer profiles for the {tech} requirement.",
            "Please share the gaps you want the next profiles to cover.",
        ], "client_replacement_request_ack")

    if scenario == "client_shared_meeting_link_to_trainer":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the technical-call joining link.",
            "We will forward the link to the trainer and confirm that he has received the invite.",
            "We will keep you updated if any timing or access issue arises.",
        ], "client_meeting_link_forward_to_trainer_ack")

    if scenario == "client_confirms_interview_slot":
        return _client_simple_reply(client, tech, subject, [
            "Thanks for confirming the discussion slot.",
            "We will confirm it with the trainer and send the meeting link.",
            "Please let us know if any participant details need to be added to the invite.",
        ], "client_interview_slot_confirmation_ack")

    if scenario == "client_requests_interview_slots":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for your message.",
            f"We will ask the {tech} trainer for discussion slots and send the options.",
            "Once a slot is confirmed, we will share the meeting link and final schedule details.",
        ], "client_interview_slots_request_ack")

    if scenario == "client_asks_meeting_link":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for checking.",
            "We will check the confirmed schedule and send the meeting link.",
            "If there has been any change in timing or participants, please let us know.",
        ], "client_meeting_link_request_ack")

    if scenario == "client_asks_toc":
        return _client_simple_reply(client, tech, subject, [
            f"Thanks for asking for the ToC for the {tech} training.",
            "We will prepare the course outline and send it for your review.",
            "If you have any specific topics or participant level to include, please share them.",
        ], "client_toc_request_ack")

    if scenario == "client_sends_po":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the purchase order.",
            "We have received the purchase order and will check the billing and training scope.",
            "We will send the invoice next.",
        ], "client_po_received_ack")

    if scenario == "client_asks_invoice":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for your message.",
            "We will check the invoice and send the copy or the current status.",
            "If any PO number, GST details, or billing address needs to be used, please share it in the same thread.",
        ], "client_invoice_request_ack")

    if scenario == "client_payment_terms":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the payment terms query.",
            "We have noted the payment terms and will confirm what applies to this engagement.",
        ], "client_payment_terms_ack")

    if scenario == "client_budget_negotiation":
        return _client_simple_reply(client, tech, subject, [
            "Thanks for the commercial feedback.",
            f"We will check the commercials for the {tech} requirement with the trainer and send an updated option.",
        ], "client_budget_negotiation_ack")

    if scenario == "client_changes_training_details":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the revised training details.",
            "We have noted the change and will update the trainer search and schedule.",
            "If any duration, timing, mode, participant count, or date is still tentative, please confirm so we can keep the plan accurate.",
        ], "client_training_change_ack")

    if scenario == "client_asks_final_logistics":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for checking on the final logistics.",
            "We will send the confirmed trainer, schedule, and meeting link.",
            "Please let us know if there are additional participants or internal instructions to include.",
        ], "client_final_logistics_ack")

    if scenario == "client_asks_status_update":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for following up.",
            f"We are checking the current status for the {tech} requirement and will update you shortly.",
            "We will share the next update as soon as it is available.",
        ], "client_status_update_ack")

    if scenario == "client_asks_more_profiles":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for the update.",
            f"We will look for additional trainer profiles for the {tech} requirement.",
            "Please share any skill, experience, budget, or location preference we should prioritise.",
        ], "client_more_profiles_ack")

    if scenario == "client_training_completed":
        return _client_simple_reply(client, tech, subject, [
            "Thanks for confirming that the training is complete.",
            "We will close the pending feedback, documents, and billing.",
            "Please share participant feedback if available.",
        ], "client_training_completion_ack")

    if scenario == "client_feedback_shared":
        return _client_simple_reply(client, tech, subject, [
            "Thank you for sharing the feedback.",
            "We have noted it and will review it with the trainer.",
            "We will arrange a follow-up if one is needed.",
        ], "client_feedback_ack")

    if scenario == "client_thanks":
        return _client_simple_reply(client, tech, subject, [
            "You're welcome.",
        ], "client_thanks_ack")

    if scenario in CONSULTANCY_REPLY_LINES:
        template_key, lines = CONSULTANCY_REPLY_LINES[scenario]
        return _client_simple_reply(client, tech, subject, list(lines), template_key)

    if scenario == "trainer_interested":
        trainer_name = _sender_name(sender_name)
        body = (
            f"Dear {trainer_name},\n\n"
            "Thank you for your response.\n\n"
            "We will write if we still need your availability for the proposed dates.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        # Do not automatically send a generic profile/CV/LinkedIn request.
        # The shortlist workflow sends a follow-up only after checking the
        # analysed trainer record for genuinely missing information.
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_interested_ack", auto_send_safe=False)

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
            "We will share your details with the client and ask for a discussion slot if they want to proceed.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_details_ack")

    if scenario == "trainer_credentials_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thanks for sharing your profile.\n\n"
            "Please also share your availability and commercials so we can send this to the client.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_credentials_ack")

    if scenario == "trainer_commercials_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for sharing your commercial details.\n\n"
            "Please also confirm your availability for the proposed dates so we can share the full profile with the client.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_commercials_ack")

    if scenario == "trainer_slots_sent":
        body = (
            "Dear Trainer,\n\n"
            "Thanks for sharing your slots.\n\n"
            "We are reviewing them with the client and will confirm the next step shortly.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_slots_ack", auto_send_safe=False)

    if scenario == "trainer_more_details":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for your response.\n\n"
            "Please share any remaining details the client asked for, such as your profile, availability, commercials, LinkedIn, ToC, or certifications.\n\n"
            f"{TRAINER_SIGNATURE}"
        )
        return _reply(f"Re: {tech} Training Opportunity", body, "trainer_more_details")

    if scenario == "trainer_unavailable":
        body = (
            "Dear Trainer,\n\n"
            "Thank you for the update. We have noted your unavailability for this requirement.\n\n"
            "We will reach out for suitable future opportunities.\n\n"
            f"{TRAINER_SIGNATURE}"
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
            "Thanks for sharing the profiles.\n\n"
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
            "We have received your course enquiry and will review it.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Training Enquiry')}", body, "student_enquiry_ack")

    if scenario == "government_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thanks for the public-sector training enquiry.\n\n"
            "We will review the requirement and take the next step.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Government Training Enquiry')}", body, "government_enquiry_ack")

    if scenario == "media_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for reaching out.\n\n"
            "We have received your press enquiry and will review it.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Media Enquiry')}", body, "media_enquiry_ack")

    if scenario == "partnership":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thanks for the partnership enquiry.\n\n"
            "We will review the details and get back to you if there is a suitable opportunity to proceed.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Partnership Enquiry')}", body, "partnership_ack")

    if scenario == "finance_legal":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thanks for the finance and legal details.\n\n"
            "We have received your message and will review it.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Your Email')}", body, "finance_legal_ack")

    if scenario == "general_enquiry":
        body = (
            f"Dear {_clean(sender_name, 'Team')},\n\n"
            "Thank you for reaching out.\n\n"
            "We have received your message and will review it.\n\n"
            f"{SIGNATURE}"
        )
        return _reply(f"Re: {_clean(subject, 'Your Email')}", body, "general_enquiry_ack")

    return _safe_ack(sender_name, subject)
