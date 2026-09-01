from app.routes.inbox import (
    _client_rate_for_trainer_quote,
    _client_same_commercial_acceptance,
    _trainer_commercial_amounts,
    _trainer_commercial_body,
    _trainer_budget_amounts_from_requirement,
    _trainer_profile_commercial_amounts,
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
