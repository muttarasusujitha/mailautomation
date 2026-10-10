from app.routes import shortlists, trainer_automation


def _requirement():
    return {
        "technology_needed": "DevOps",
        "duration_days": 20,
        "training_dates": "10 September 2026 to 7 October 2026",
        "mode": "Offline / classroom",
        "participant_count": 20,
        "budget_total": 130000,
    }


def test_confirmed_mail1_shows_client_commercial_not_trainer_share():
    body = shortlists._clean_confirmed_mail1_body(
        "Suresh Reddy", _requirement(), "DevOps", {}
    )

    assert "Client commercial: INR 130,000 total-course commercial" in body
    assert "Offered trainer commercial" not in body
    assert "91,000" not in body
    assert "70%" not in body
    assert "Please confirm the offered" not in body
    assert "three convenient interview/discussion slots" in body
    assert "updated profile" in body.lower()


def test_confirmed_mail1_asks_for_cv_only_when_it_is_not_stored():
    body = shortlists._clean_confirmed_mail1_body(
        "Suresh Reddy",
        _requirement(),
        "DevOps",
        {"resume_text": "Ten years delivering corporate DevOps training."},
    )

    assert "updated profile" not in body.lower()
    assert "three convenient interview/discussion slots" in body


def test_proposal_mail1_still_hides_the_client_commercial():
    requirement = {**_requirement(), "batch_flow": "proposal", "pipeline_target": "shortlist"}
    body = shortlists._clean_confirmed_mail1_body(
        "Suresh Reddy", requirement, "DevOps", {}
    )

    assert "Offered trainer commercial" in body
    assert "Please confirm the offered trainer commercial" in body
    assert "130,000" not in body
    assert "91,000" not in body


def test_secondary_trainer_automation_hides_margin_formula():
    commercial = trainer_automation._trainer_mail1_commercial_text(_requirement())

    assert commercial == "INR 91,000 total commercial, inclusive of applicable TDS"
    assert "70%" not in commercial
    assert "client" not in commercial.lower()


def test_total_budget_stays_total_for_short_duration_batches():
    requirement = {**_requirement(), "duration_days": 10}

    assert shortlists._trainer_mail1_commercial_text(requirement) == "INR 91,000 total commercial, inclusive of applicable TDS"
    assert trainer_automation._trainer_mail1_commercial_text(requirement) == "INR 91,000 total commercial, inclusive of applicable TDS"


def test_attachment_note_is_inserted_before_signature():
    body = "Hi Trainer,\n\nPlease review.\n\nRegards,\nClahan Technologies"
    result = shortlists._insert_before_signature(
        body, "The proposed ToC/course agenda is attached."
    )

    assert result.index("The proposed ToC") < result.index("Regards,")


def test_mail1_normalizer_removes_duplicate_blocks_and_extra_slot_examples():
    body = """Hi Trainer,

Please review the requirement.

Please review the requirement.

Example:
- 01 November 2026, 10:00 AM IST
- 02 November 2026, 10:00 AM IST
- 03 November 2026, 10:00 AM IST
- 04 November 2026, 10:00 AM IST
- 05 November 2026, 10:00 AM IST
- 06 November 2026, 10:00 AM IST

Regards,
Clahan Technologies"""

    result = shortlists._normalize_trainer_mail1_body(body)

    assert result.count("Please review the requirement.") == 1
    assert result.count("AM IST") == 3
    assert result.count("Regards,") == 1
