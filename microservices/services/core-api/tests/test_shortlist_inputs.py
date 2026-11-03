from app.routes.requirements import _normalise_requirement_payload, _score_trainer


def test_experience_and_location_cannot_qualify_unrelated_trainer():
    trainer = {'name': 'Java Trainer', 'skills': ['Java'], 'experience_years': 20,
               'location': 'Chennai', 'linkedin': 'https://example.com', 'resume': 'Java Spring Boot',
               'certifications': ['Java'], 'training_count': 100, 'resume_rank_score': 90}
    assert _score_trainer(trainer, {'technology_needed': 'Advanced DevOps', 'location': 'Chennai'}) is None


def test_requested_topics_contribute_to_matching():
    trainer = {'skills': ['Python', 'Docker', 'AWS'], 'experience_years': 5}
    result = _score_trainer(trainer, {'required_skills': ['Python'], 'skills': ['Docker'], 'requested_topics': ['AWS']})
    assert result['score_breakdown']['matched_required_skills'] == ['Python', 'Docker', 'AWS']


def test_shortlist_requires_minimum_experience_and_every_required_topic():
    requirement = {
        'technology_needed': 'DevOps',
        'required_skills': ['Docker', 'Kubernetes'],
        'min_experience_years': 5,
    }
    qualified = {
        'technology_category': 'DevOps',
        'skills': ['Docker', 'Kubernetes'],
        'experience_years': 5,
    }
    assert _score_trainer(qualified, requirement) is not None
    assert _score_trainer({**qualified, 'experience_years': 4}, requirement) is None
    assert _score_trainer({**qualified, 'skills': ['Docker']}, requirement) is None


def test_shortlist_reads_experience_from_resume_when_numeric_field_is_empty():
    trainer = {
        'technology_category': 'DevOps',
        'skills': ['Docker', 'Kubernetes'],
        'experience_years': 0,
        'resume': 'Total experience: 8 years. Docker and Kubernetes trainer.',
    }
    result = _score_trainer(trainer, {
        'technology_needed': 'DevOps',
        'required_skills': ['Docker', 'Kubernetes'],
        'min_experience_years': 5,
    })
    assert result is not None
    assert result['experience_years'] == 8


def test_shortlist_trusts_resume_over_conflicting_stored_years():
    trainer = {
        'technology_category': 'DevOps',
        'skills': ['Docker', 'Kubernetes'],
        'experience_years': 10,
        'resume': 'DevOps trainer with 3 years of experience.',
    }
    assert _score_trainer(trainer, {
        'technology_needed': 'DevOps',
        'required_skills': ['Docker', 'Kubernetes'],
        'min_experience_years': 5,
    }) is None


def test_client_proposal_wording_beats_tentative_schedule_details():
    result = _normalise_requirement_payload({
        'technology_needed': 'DevOps',
        'original_body': 'We have an upcoming proposal requirement. Duration: 20 days. Training date: To be confirmed.',
        'duration_days': 20,
        'training_dates': 'To be confirmed',
    })
    assert result['batch_flow'] == 'proposal'
    assert result['pipeline_target'] == 'shortlist'


def test_placeholder_schedule_and_commercial_do_not_turn_request_into_confirmed_batch():
    result = _normalise_requirement_payload({
        'technology_needed': 'WhatsApp Business API',
        'training_dates': 'To be confirmed',
        'timeline_start': 'TBD',
        'budget_total': 'Pending confirmation',
        'client_requirement_text': 'Please prepare a training proposal for WhatsApp Business API.',
    })

    assert result['batch_flow'] == 'proposal'
    assert result['requirement_type'] == 'proposal_batch'
    assert result['pipeline_target'] == 'shortlist'


def test_real_schedule_or_commercial_can_identify_confirmed_batch():
    for details in (
        {'training_dates': 'November 2 to November 6, 2026'},
        {'budget_total': 250000},
    ):
        result = _normalise_requirement_payload({
            'technology_needed': 'DevOps',
            'client_requirement_text': 'We need a trainer for a corporate batch.',
            **details,
        })
        assert result['batch_flow'] == 'confirmed'
        assert result['requirement_type'] == 'confirmed_batch'
        assert result['pipeline_target'] == 'shortlist1'
