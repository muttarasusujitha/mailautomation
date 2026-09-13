import pytest
from shared.requirement_duration import training_duration


@pytest.mark.parametrize("requirement,expected", [
    ({"duration_text": "20 Training Days"}, {"duration_days": 20}),
    ({"extracted": {"duration_text": "15 working days"}}, {"duration_days": 15}),
    ({"body": "Technology: DevOps\nDuration: 20 Training Days\nTraining hours per day: 3 hours\nLab access: 8 hours/day"}, {"duration_days": 20, "hours_per_day": 3}),
    ({"duration_hours": 60, "training_hours_per_day": 3}, {"duration_hours": 60, "hours_per_day": 3, "duration_days": 20}),
    ({"duration_hours": 60, "lab_hours_per_day": 8}, {"duration_hours": 60}),
    ({"description": "Trainer has 20 days availability. Lab access: 8 hours/day"}, {}),
    ({"duration_days": "NaN", "duration_text": "10 days"}, {"duration_days": 10}),
    ({"duration_days": 12, "duration_text": "20 days"}, {"duration_days": 12}),
])
def test_duration_uses_explicit_training_evidence(requirement, expected):
    assert training_duration(requirement) == expected
