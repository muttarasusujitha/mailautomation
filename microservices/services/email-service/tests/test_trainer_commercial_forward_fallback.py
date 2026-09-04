from app.routes.inbox import (
    _client_rate_for_trainer_quote,
    _client_same_commercial_acceptance,
    _trainer_commercial_amounts,
    _trainer_commercial_body,
    _trainer_budget_amounts_from_requirement,
    _trainer_profile_commercial_amounts,
    _has_proper_interview_slots,
    _resolve_interview_slot_datetime,
    _slot_options_from_text,
)


def test_trainer_profile_commercial_amounts_fallback_uses_rate_fields():
    trainer = {
        "name": "Divya Menon",
        "day_rate": "18000",
        "commercial_text": "Trainer shared profile and availability.",
    }

    assert _trainer_profile_commercial_amounts(trainer) == [18000]


def test_client_same_commercial_acceptance_detects_same_approval():
    assert _client_same_commercial_acceptance(
        "Hi, same commercial is accepted. Please proceed with this trainer."
    )


def test_client_same_commercial_acceptance_ignores_negotiation():
    assert not _client_same_commercial_acceptance(
        "The commercials are too high. Please reduce and share the best rate."
    )


def test_trainer_budget_amounts_from_requirement_uses_client_budget_split():
    requirement = {"budget_per_day": 40000}

    assert _trainer_budget_amounts_from_requirement(requirement) == [28000]


def test_client_rate_uses_original_budget_when_trainer_accepts_mail1_rate():
    requirement = {
        "budget_per_day": 200000,
        "trainer_visible_budget_per_session": 140000,
    }

    assert _client_rate_for_trainer_quote(140000, requirement) == 200000


def test_client_rate_adds_thirty_percent_when_trainer_asks_more():
    requirement = {
        "budget_per_day": 200000,
        "trainer_visible_budget_per_session": 140000,
    }

    assert _client_rate_for_trainer_quote(196000, requirement) == 254800


def test_proposal_range_quotes_to_client_with_thirty_percent_markup():
    requirement = {
        "technology_needed": "DevOps",
        "requirement_type": "proposal_batch",
        "batch_flow": "proposal",
        "duration_days": 20,
    }
    amounts = _trainer_commercial_amounts("Commercials: INR 12 to 15k per day")
    client_rates = [round(_client_rate_for_trainer_quote(amount, requirement)) for amount in amounts]

    assert amounts == [12000, 15000]
    assert client_rates == [15600, 19500]


def test_commercial_body_shows_day_rate_and_total_without_invented_toc():
    body = _trainer_commercial_body(
        {"technology_needed": "DevOps", "duration_days": 20, "batch_flow": "proposal"},
        {},
        {"name": "Karthik Menon"},
        [15600, 19500],
    )["body"]

    assert "INR 15,600 per day/session x 20 days = INR 312,000 total" in body
    assert "INR 19,500 per day/session x 20 days = INR 390,000 total" in body
    assert "Proposed ToC / Course Agenda" not in body


def test_shared_date_heading_applies_to_markdown_time_only_slots():
    slots = (
        "For tomorrow, **2 September 2026**, you can use these 3 trainer interview slots:\n\n"
        "- **10:00 AM – 10:30 AM IST**\n"
        "- **2:00 PM – 2:30 PM IST**\n"
        "- **5:00 PM – 5:30 PM IST**"
    )

    options = _slot_options_from_text(slots)

    assert _has_proper_interview_slots(slots)
    assert len(options) == 3
    assert all(option["start"].date().isoformat() == "2026-09-02" for option in options)
    assert [option["start"].strftime("%H:%M") for option in options] == ["10:00", "14:00", "17:00"]


def test_client_time_only_selection_matches_dated_reschedule_slots():
    trainer_slots = (
        "For tomorrow, 2 September 2026, the available interview slots are:\n"
        "- 10:00 AM - 10:30 AM IST\n"
        "- 2:00 PM - 2:30 PM IST\n"
        "- 5:00 PM - 5:30 PM IST"
    )

    selected = _resolve_interview_slot_datetime(
        "2:00 PM - 2:30 PM IST works for us.",
        trainer_slots,
    )

    assert selected["source"] == "client_time_matched_to_source_slot"
    assert selected["label"] == "02/09/2026, 02:00 PM - 02:30 PM"
