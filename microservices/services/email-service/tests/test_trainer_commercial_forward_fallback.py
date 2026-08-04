from app.routes.inbox import _trainer_profile_commercial_amounts


def test_trainer_profile_commercial_amounts_fallback_uses_rate_fields():
    trainer = {
        "name": "Divya Menon",
        "day_rate": "18000",
        "commercial_text": "Trainer shared profile and availability.",
    }

    assert _trainer_profile_commercial_amounts(trainer) == [18000]
