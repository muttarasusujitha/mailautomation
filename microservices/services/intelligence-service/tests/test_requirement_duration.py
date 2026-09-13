from app.routes.client_intelligence import _regex_extract


def test_training_days_read_from_requirement_line():
    assert _regex_extract('Technology: DevOps\nDuration: 20 Training Days')['duration_days'] == 20


def test_weeks_are_not_mistaken_for_days():
    assert _regex_extract('Duration: 2 weeks')['duration_days'] is None
