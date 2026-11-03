from app.routes.shortlists import _score_trainer


def test_shortlist_requires_minimum_experience_and_every_required_topic():
    requirement = {
        "technology_needed": "DevOps",
        "required_skills": ["Docker", "Kubernetes"],
        "min_experience_years": 5,
    }
    trainer = {
        "technology_category": "DevOps",
        "skills": ["Docker", "Kubernetes"],
        "experience_years": 5,
    }

    assert _score_trainer(trainer, requirement) is not None
    assert _score_trainer({**trainer, "experience_years": 4}, requirement) is None
    assert _score_trainer({**trainer, "skills": ["Docker"]}, requirement) is None


def test_shortlist_uses_resume_experience_when_parsed_number_is_zero():
    trainer = {
        "technology_category": "DevOps",
        "skills": ["Docker", "Kubernetes"],
        "experience_years": 0,
        "resume": "Total experience: 8 years. Docker and Kubernetes trainer.",
    }
    result = _score_trainer(trainer, {
        "technology_needed": "DevOps",
        "required_skills": ["Docker", "Kubernetes"],
        "min_experience_years": 5,
    })
    assert result is not None
    assert result["experience_years"] == 8


def test_shortlist_excludes_resume_below_minimum_despite_higher_stored_number():
    trainer = {
        "technology_category": "DevOps",
        "skills": ["Docker", "Kubernetes"],
        "experience_years": 10,
        "resume": "DevOps trainer with 3 years of experience.",
    }
    assert _score_trainer(trainer, {
        "technology_needed": "DevOps",
        "required_skills": ["Docker", "Kubernetes"],
        "min_experience_years": 5,
    }) is None
