from app.routes import shortlists


def _proposal():
    return {
        "batch_flow": "proposal",
        "duration_days": 5,
        "technology_needed": "DevOps",
    }


def test_offer_confirmation_is_added_once_when_the_offer_is_available():
    requirement = _proposal()
    body = "Please confirm your interest and availability."

    result = shortlists._append_missing_offer_confirmation(body, requirement, {})

    assert "Offered trainer commercial:" in result
    assert result.lower().count("please confirm the offered") == 1


def test_offer_confirmation_is_not_added_when_no_offer_exists(monkeypatch):
    requirement = _proposal()
    body = "Please confirm your interest and availability."
    monkeypatch.setattr(shortlists, "_trainer_mail1_commercial_section", lambda *_args: [])

    assert shortlists._append_missing_offer_confirmation(body, requirement, {}) == body


def test_existing_offer_confirmation_is_not_duplicated():
    requirement = _proposal()
    body = shortlists._clean_confirmed_mail1_body("Trainer", requirement, "DevOps", {})

    result = shortlists._append_missing_offer_confirmation(body, requirement, {})

    assert result.lower().count("please confirm the offered") == 1
