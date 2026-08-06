from app.routes.inbox import (
    _client_same_commercial_acceptance,
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
