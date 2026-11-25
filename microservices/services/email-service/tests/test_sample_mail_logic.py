import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.routes.inbox import (
    _client_proceed_ack_reply,
    _confirmed_requirement_on_first_client_mail,
    _extract_requirement_from_email,
    _requirement_flow_from_email,
    _requirement_is_proposal,
    _requirement_payload_from_email,
    _should_send_trainer_mail1_now,
    _trainer_mail2_details_reply,
    _trainer_missing_requested_details,
    _trainer_reply_has_requested_details,
)

SAILPOINT_BODY = """Dear Team,
We have an immediate requirement for an experienced SailPoint Trainer for an upcoming corporate training engagement.
Training Requirement:
Technology: SailPoint IdentityIQ / SailPoint Identity Security
Mode: To be confirmed (Online/Offline)
Duration: To be confirmed
Location: To be confirmed
Participants: Corporate professionals
Experience Required: 8+ years of relevant hands-on implementation and training experience
If you have a suitable trainer available, kindly share the following details at the earliest:
Updated trainer profile (CV)
LinkedIn profile
Relevant SailPoint training and implementation experience
Availability
Commercials (per hour/day)
Lab support availability and associated cost (if applicable)
Any relevant certifications
Since this is an urgent requirement, we request you to share the details as soon as possible.
Looking forward to your response.
"""

DEVOPS_BODY = """Training Details – DevOps CI/CD
Topic: DevOps & CI/CD
Audience: Software / Non-Embedded Professionals
Location: Mexico
Training Duration: 3 Days
Total Sessions: 6 Half-Day Sessions
Duration per Session: 4 Hours
Training Time: 7:30 PM – 11:30 PM IST
Total Training Hours: 24 Hours
Mode: Online
"""

SAILPOINT_ACK = """Hi,

Greetings of the day! Thanks for sharing your training requirement.

We have noted the following from your email:
- Technology: SailPoint IdentityIQ / SailPoint Identity Security
- Experience required: 8+ years
- Participants: Corporate professionals
- Trainer details requested: CV, LinkedIn profile, relevant experience, availability, commercials, and certifications; lab support availability and associated cost, if applicable

Please share:
- Training mode
- Training duration
- Location or dates

Thanks,
Annapurna U.
Clahan Technologies"""


def _extract(subject, body):
    return _extract_requirement_from_email(subject, body, "client@example.com", "Client Team")


def _first_mail_sends(subject, body, extracted):
    email_doc = {"subject": subject, "body": body, "clean_body": body}
    confirmed = _confirmed_requirement_on_first_client_mail(subject, email_doc, extracted)
    sends = _should_send_trainer_mail1_now(
        automation_ready=True,
        confirmed_first_mail=confirmed,
        is_first_client_mail=True,
        explicit_trainer_authorization=False,
        details_ready_on_client_reply=False,
        is_training_request=bool(extracted.get("is_training_request")),
        has_domain=bool(extracted.get("technology_needed")),
    )
    return confirmed, sends


def _mail1_body(payload, trainer=None):
    env = os.environ.copy()
    env["TRAINER_APP"] = str(Path(__file__).resolve().parents[2] / "trainer-service")
    env["ROOT"] = str(Path(__file__).resolve().parents[3])
    env["PAYLOAD"] = json.dumps(payload, default=str)
    env["TRAINER"] = json.dumps(trainer or {})
    script = r"""
import json, os, sys
sys.path[:0] = [os.environ["TRAINER_APP"], os.environ["ROOT"]]
from app.routes.shortlists import _clean_confirmed_mail1_body
payload = json.loads(os.environ["PAYLOAD"])
trainer = json.loads(os.environ["TRAINER"])
print(_clean_confirmed_mail1_body("Trainer", payload, payload.get("technology_needed") or "Training", trainer))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def test_sailpoint_mail_is_a_proposal_and_the_ack_answers_only_this_email():
    extracted = _extract("SailPoint Trainer Requirement", SAILPOINT_BODY)

    assert _requirement_flow_from_email(extracted, SAILPOINT_BODY) == "proposal"
    assert extracted["technology_needed"] == "SailPoint IdentityIQ / SailPoint Identity Security"
    assert extracted["min_experience_years"] == 8
    assert extracted["audience_level"] == "Corporate professionals"
    assert extracted["mode"] == "To be confirmed (Online/Offline)"
    assert extracted["duration_text"] == "To be confirmed"
    assert extracted["location"] == "To be confirmed"
    assert not extracted.get("training_dates")
    assert not extracted.get("budget_total")
    assert not extracted.get("budget_per_day")
    assert "Commercials (per hour/day)" in extracted["requested_details"]
    assert "Updated CV / Trainer Profile" in extracted["requested_details"]
    assert "LinkedIn Profile" in extracted["requested_details"]
    assert "Relevant Certifications" in extracted["requested_details"]
    assert extracted["clahan_managed_details"] == ["Lab availability and cost"]
    confirmed, sends = _first_mail_sends("SailPoint Trainer Requirement", SAILPOINT_BODY, extracted)
    assert confirmed is False
    assert sends is False

    body = _client_proceed_ack_reply(extracted)["body"]
    assert body == SAILPOINT_ACK
    ask = body.split("Please share:", 1)[1]
    assert "CV" not in ask
    assert "LinkedIn" not in ask
    assert "certification" not in ask.lower()
    assert "confirmed" not in body.lower()
    assert "INR" not in body and "₹" not in body


def test_devops_schedule_is_confirmed_and_mail1_states_only_those_facts():
    extracted = _extract("Training Details – DevOps CI/CD", DEVOPS_BODY)

    assert _requirement_flow_from_email(extracted, DEVOPS_BODY) == "confirmed"
    assert extracted["technology_needed"] == "DevOps & CI/CD"
    assert extracted["audience_level"] == "Software / Non-Embedded Professionals"
    assert extracted["location"] == "Mexico"
    assert extracted["duration_text"] == "3 Days"
    assert extracted["duration_days"] == 3
    assert extracted["total_sessions"] == "6 Half-Day Sessions"
    assert extracted["duration_per_session"] == "4 Hours"
    assert extracted["hours_per_session"] == 4
    assert extracted["timing"] == "7:30 PM – 11:30 PM IST"
    assert extracted["total_training_hours"] == "24 Hours"
    assert extracted["mode"] == "Online"
    assert not extracted.get("budget_total")
    assert not extracted.get("budget_per_day")
    confirmed, sends = _first_mail_sends("Training Details – DevOps CI/CD", DEVOPS_BODY, extracted)
    assert confirmed is True
    assert sends is True

    ack = _client_proceed_ack_reply(extracted)["body"]
    assert "to be confirmed" not in ack.lower()
    assert "proposal" not in ack.lower()
    assert "Budget" not in ack

    payload = _requirement_payload_from_email(
        {"subject": "Training Details – DevOps CI/CD", "body": DEVOPS_BODY, "clean_body": DEVOPS_BODY},
        extracted,
    )
    assert payload["batch_flow"] == "confirmed"
    assert payload["location"] == "Mexico"
    assert payload["total_sessions"] == "6 Half-Day Sessions"
    assert payload["total_training_hours"] == "24 Hours"
    body = _mail1_body(payload)
    assert "DevOps & CI/CD" in body
    assert "Software / Non-Embedded Professionals" in body
    assert "Mexico" in body
    assert "3 Days" in body
    assert "6 Half-Day Sessions" in body
    assert "4 Hours" in body
    assert "7:30 PM – 11:30 PM IST" in body
    assert "24 Hours" in body
    assert "Online" in body
    assert "confirm you can deliver this scope" in body
    assert "availability for this schedule" in body
    assert "updated CV" in body
    assert "[Your available date 1]" in body
    assert "[Your available date 3]" in body
    assert "not the client's dates" in body
    assert "01 November 2026" not in body
    assert "03 November 2026" not in body
    assert "05 November 2026" not in body
    assert "to be confirmed" not in body.lower()
    assert "proposal" not in body.lower()
    assert "commercial" not in body.lower()
    assert "70%" not in body
    assert "INR" not in body
    stored = _mail1_body(payload, {"resume_text": "A stored SailPoint and DevOps profile."})
    assert "updated CV" not in stored
    assert "confirm you can deliver this scope" in stored


def test_proposal_followup_uses_the_proposal_batch_and_a_commercial_yes_is_not_complete():
    requirement = {
        "batch_flow": "proposal",
        "technology_needed": "SailPoint",
        "requested_details": [
            "Updated CV / Trainer Profile",
            "Availability",
            "Commercials (per hour/day)",
        ],
    }
    assert _requirement_is_proposal(requirement) is True
    missing = _trainer_missing_requested_details("Yes", requirement, {})
    assert "Updated CV / Trainer Profile" in missing
    assert any("three interview" in item.lower() for item in missing)
    assert not any("commercial" in item.lower() for item in missing)
    assert _trainer_reply_has_requested_details("Yes, the commercial is fine.", requirement, {}) is False

    followup = _trainer_mail2_details_reply({
        "trainer_name": "Trainer",
        "requirement": requirement,
        "missing_requested_details": [
            "Exactly three interview/discussion slots (date, time, and time zone)",
        ],
    })
    assert "confirmed training details" not in followup["body"].lower()
    assert "proposal" in followup["body"].lower()
    assert "three interview/discussion slots" in followup["body"].lower()

    confirmed = _trainer_mail2_details_reply({
        "trainer_name": "Trainer",
        "requirement": {"batch_flow": "confirmed", "technology_needed": "DevOps"},
        "missing_requested_details": ["Updated CV / Trainer Profile"],
    })
    assert "confirmed training details" in confirmed["body"].lower()


@pytest.mark.parametrize("reply", ["Yes", "Yes, the offered commercial works."])
def test_commercial_only_yes_still_leaves_the_slot_followup(reply):
    requirement = {
        "batch_flow": "proposal",
        "pipeline_target": "shortlist",
        "technology_needed": "SailPoint",
        "requested_details": ["Availability", "Commercials (per hour/day)"],
    }
    email_doc = {"attachments": [{"filename": "Trainer_Profile.pdf", "safe_client_scope": True}]}
    missing = _trainer_missing_requested_details(reply, requirement, email_doc)
    assert missing == ["Exactly three interview/discussion slots (date, time, and time zone)"]
    assert _trainer_reply_has_requested_details(reply, requirement, email_doc) is False
