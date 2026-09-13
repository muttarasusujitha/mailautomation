from app.routes.requirements import _score_trainer


def test_experience_and_location_cannot_qualify_unrelated_trainer():
    trainer = {'name': 'Java Trainer', 'skills': ['Java'], 'experience_years': 20,
               'location': 'Chennai', 'linkedin': 'https://example.com', 'resume': 'Java Spring Boot',
               'certifications': ['Java'], 'training_count': 100, 'resume_rank_score': 90}
    assert _score_trainer(trainer, {'technology_needed': 'Advanced DevOps', 'location': 'Chennai'}) is None


def test_requested_topics_contribute_to_matching():
    trainer = {'skills': ['Python', 'Docker', 'AWS'], 'experience_years': 5}
    result = _score_trainer(trainer, {'required_skills': ['Python'], 'skills': ['Docker'], 'requested_topics': ['AWS']})
    assert result['score_breakdown']['matched_required_skills'] == ['Python', 'Docker', 'AWS']
