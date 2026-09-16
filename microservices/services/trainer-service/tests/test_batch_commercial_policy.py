from app.routes.shortlists import _trainer_mail1_commercial_text, _trainer_mail1_commercial_section, _proposal_client_commercial_section


def test_confirmed_uses_seventy_percent_and_daily_rate_above_threshold():
    text = _trainer_mail1_commercial_text({'batch_flow': 'confirmed',
        'budget_per_day': 20000, 'duration_days': 5, 'clahan_margin_percent': 25})
    assert '14,000' in text
    assert 'per training day' in text
    assert '70,000 total commercial' in text


def test_proposal_trainer_and_client_use_same_selected_offer():
    requirement = {'batch_flow': 'proposal', 'duration_days': 5, 'clahan_margin_percent': 25}
    trainer = {'clahan_skill_tier': 'advanced'}
    trainer_text = ' '.join(_trainer_mail1_commercial_section(requirement, trainer))
    client_text = _proposal_client_commercial_section(requirement, trainer)
    assert '15,000' in trainer_text
    assert '75,000 total commercial' in trainer_text
    assert 'per training day' in trainer_text
    assert '100,000' in client_text
    assert 'per day' not in trainer_text + client_text
    assert '25%' not in trainer_text


def test_automated_and_manual_offers_match():
    from app.routes.trainer_automation import _trainer_mail1_commercial_text as automated
    for req in (
        {'batch_flow': 'confirmed', 'budget_total': 60000, 'duration_days': 3},
        {'batch_flow': 'proposal', 'duration_days': 10},
    ):
        assert automated(req) == _trainer_mail1_commercial_text(req)
        assert 'per training day' in automated(req)
        assert 'total commercial' in automated(req)


def test_low_rate_is_total_only_in_manual_and_automated_emails():
    from app.routes.trainer_automation import _trainer_mail1_commercial_text as automated
    for days in (3, 10):
        req = {'batch_flow': 'confirmed', 'budget_per_day': 15000, 'duration_days': days}
        text = automated(req)
        assert text == _trainer_mail1_commercial_text(req)
        assert 'per training day' not in text
        assert f'{10500 * days:,} total commercial' in text
