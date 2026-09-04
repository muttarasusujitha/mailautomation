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


def test_mail1_exposes_only_trainer_offer_not_client_pricing_or_margin():
    body = shortlists._clean_confirmed_mail1_body(
        "Suresh Reddy", _requirement(), "DevOps", {}
    )

    assert "Offered trainer commercial: INR 91,000 total commercial" in body
    assert "Client commercial/budget" not in body
    assert "Clahan-calculated" not in body
    assert "70% of client commercial" not in body
    assert "130,000" not in body


def test_secondary_trainer_automation_hides_margin_formula():
    commercial = trainer_automation._trainer_mail1_commercial_text(_requirement())

    assert commercial == "INR 91,000 total commercial, inclusive of applicable TDS"
    assert "70%" not in commercial
    assert "client" not in commercial.lower()


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
