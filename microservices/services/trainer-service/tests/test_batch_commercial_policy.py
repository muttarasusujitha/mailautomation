from app.routes.shortlists import _trainer_mail1_commercial_text, _trainer_mail1_commercial_section, _proposal_client_commercial_section


def test_confirmed_uses_seventy_percent_and_total_for_week():
    text = _trainer_mail1_commercial_text({'batch_flow': 'confirmed',
        'budget_per_day': 20000, 'duration_days': 5, 'clahan_margin_percent': 25})
    assert '70,000' in text
    assert 'total' in text
    assert 'per day' not in text


def test_proposal_trainer_and_client_use_same_selected_offer():
    requirement = {'batch_flow': 'proposal', 'duration_days': 5, 'clahan_margin_percent': 25}
    trainer = {'clahan_skill_tier': 'advanced'}
    trainer_text = ' '.join(_trainer_mail1_commercial_section(requirement, trainer))
    client_text = _proposal_client_commercial_section(requirement, trainer)
    assert '75,000' in trainer_text
    assert '100,000' in client_text
    assert 'per day' not in trainer_text + client_text
    assert '25%' not in trainer_text
