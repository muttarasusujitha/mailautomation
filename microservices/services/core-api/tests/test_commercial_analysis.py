from app.routes.requirements import _commercial_options_for_trainer, _recommend_option


def _selected_model(requirement, trainer):
    options = _commercial_options_for_trainer(requirement, trainer)
    return _recommend_option(options, 20.0)


def test_long_training_selects_more_profitable_per_day():
    requirement = {
        "duration_days": 40,
        "budget": 800000,
        "client_day_rate": 20000,
        "client_lumpsum": 780000,
    }
    trainer = {"day_rate": 14000, "trainer_total_commercial": 620000}

    selected = _selected_model(requirement, trainer)

    assert selected["model"] == "PER_DAY"
    assert selected["clahan_gross_profit"] == 240000
    assert selected["profit_margin_percent"] == 30


def test_short_training_can_select_one_time_when_most_profitable():
    requirement = {"duration_days": 5, "budget": 150000, "client_day_rate": 20000}
    trainer = {"day_rate": 20000}

    selected = _selected_model(requirement, trainer)

    assert selected["model"] == "ONE_TIME_30"
    assert selected["trainer_cost"] == 105000
    assert selected["clahan_gross_profit"] == 45000


def test_one_time_tds_is_calculated_on_trainer_70_percent_share():
    requirement = {"duration_days": 5, "budget": 150000, "client_day_rate": 20000, "tds_rate": 10}
    trainer = {"day_rate": 20000}

    selected = _selected_model(requirement, trainer)

    assert selected["model"] == "ONE_TIME_30"
    assert selected["tds_base_amount"] == 105000
    assert selected["tds"] == 10500
    assert selected["net_amount_after_tds"] == 94500
    assert selected["clahan_gross_profit"] == 45000


def test_day_wise_tds_is_reported_without_reducing_gross_profit():
    requirement = {"duration_days": 10, "budget": 200000, "client_day_rate": 20000, "tds_rate": 10}
    trainer = {"day_rate": 12000}

    selected = _selected_model(requirement, trainer)

    assert selected["model"] == "PER_DAY"
    assert selected["tds_base_amount"] == 120000
    assert selected["tds"] == 12000
    assert selected["net_amount_after_tds"] == 108000
    assert selected["clahan_gross_profit"] == 80000


def test_low_margin_marks_negotiation_required():
    requirement = {"duration_days": 10, "budget": 150000, "client_day_rate": 15000}
    trainer = {"day_rate": 14500}

    selected = _recommend_option(_commercial_options_for_trainer(requirement, trainer), 20.0)

    assert selected["model"] == "PER_DAY"
    assert selected["negotiation_required"] is True


def test_missing_trainer_rate_does_not_create_fake_per_day_profit():
    requirement = {"duration_days": 14.29, "budget": 560000, "client_day_rate": 39202.24}
    trainer = {"day_rate": 0}

    options = _commercial_options_for_trainer(requirement, trainer)
    per_day = next(option for option in options if option["model"] == "PER_DAY")
    selected = _recommend_option(options, 20.0)

    assert per_day["missing_trainer_commercial"] is True
    assert per_day["valid"] is False
    assert selected["model"] == "ONE_TIME_30"
