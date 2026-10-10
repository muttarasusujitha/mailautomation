from app.routes.shortlists import (
    _append_missing_offer_confirmation,
    _clean_confirmed_mail1_body,
    _trainer_missing_followup_details,
)


DEVOPS = {
    "batch_flow": "confirmed",
    "technology_needed": "DevOps & CI/CD",
    "audience_level": "Software / Non-Embedded Professionals",
    "location": "Mexico",
    "duration_text": "3 Days",
    "duration_days": 3,
    "timing": "7:30 PM – 11:30 PM IST",
    "mode": "Online",
    "total_sessions": "6 Half-Day Sessions",
    "duration_per_session": "4 Hours",
    "total_training_hours": "24 Hours",
    "requirement_source_text": """Training Details – DevOps CI/CD
Topic: DevOps & CI/CD
Audience: Software / Non-Embedded Professionals
Location: Mexico
Training Duration: 3 Days
Total Sessions: 6 Half-Day Sessions
Duration per Session: 4 Hours
Training Time: 7:30 PM – 11:30 PM IST
Total Training Hours: 24 Hours
Mode: Online
""",
}


def test_devops_mail1_states_the_schedule_and_uses_format_placeholders():
    body = _clean_confirmed_mail1_body("Trainer", DEVOPS, "DevOps & CI/CD", {})

    assert "Technology: DevOps & CI/CD" in body
    assert "Audience: Software / Non-Embedded Professionals" in body
    assert "Location: Mexico" in body
    assert "Duration: 3 Days" in body
    assert "Training time: 7:30 PM – 11:30 PM IST" in body
    assert "Mode: Online" in body
    assert "Total sessions: 6 Half-Day Sessions" in body
    assert "Duration per session: 4 Hours" in body
    assert "Total training hours: 24 Hours" in body
    assert "confirm you can deliver this scope" in body
    assert "availability for this schedule" in body
    assert "updated CV" in body
    assert "[Your available date 1], [time], [time zone]" in body
    assert "01 November 2026" not in body
    assert "commercial" not in body.lower()
    assert "70%" not in body
    assert "to be confirmed" not in body.lower()

    stored = _clean_confirmed_mail1_body("Trainer", DEVOPS, "DevOps & CI/CD", {"resume_text": "Stored CV"})
    assert "updated CV" not in stored


def test_offer_confirmation_is_not_repeated_and_is_omitted_when_no_offer_exists(monkeypatch):
    requirement = {"batch_flow": "proposal", "duration_days": 5, "technology_needed": "DevOps"}
    body = _clean_confirmed_mail1_body("Trainer", requirement, "DevOps", {})
    assert body.lower().count("please confirm the offered") == 1
    assert _append_missing_offer_confirmation(body, requirement, {}).lower().count("please confirm the offered") == 1

    monkeypatch.setattr(
        "app.routes.shortlists._trainer_mail1_commercial_section",
        lambda *_args, **_kwargs: [],
    )
    plain = "Please confirm your interest and availability."
    assert _append_missing_offer_confirmation(plain, requirement, {}) == plain


def test_commercial_only_yes_on_a_proposal_still_asks_for_dated_slots():
    requirement = {
        "batch_flow": "proposal",
        "client_requirement_text": "Please share the updated trainer profile and availability.",
    }
    missing = _trainer_missing_followup_details(
        {"availability": "Yes", "resume_text": "Stored trainer profile."},
        requirement,
    )
    assert missing == ["Exactly three interview/discussion slots (date, time, and time zone)"]
