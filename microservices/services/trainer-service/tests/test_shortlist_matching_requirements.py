from app.routes.shortlists import _location_balanced_trainers, _score_trainer


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


def test_shortlist_uses_five_local_and_five_other_location_trainers():
    local = [
        {"trainer_id": f"L{index}", "location": "Bengaluru", "match_score": 100 - index}
        for index in range(7)
    ]
    other = [
        {"trainer_id": f"O{index}", "location": "Chennai", "match_score": 90 - index}
        for index in range(7)
    ]
    chosen = _location_balanced_trainers(local + other, "Bengaluru")

    assert len(chosen) == 10
    assert [trainer["trainer_id"] for trainer in chosen[:5]] == ["L0", "L1", "L2", "L3", "L4"]
    assert [trainer["trainer_id"] for trainer in chosen[5:]] == ["O0", "O1", "O2", "O3", "O4"]


def test_shortlist_fills_missing_local_places_with_other_qualified_trainers():
    scored = [
        {"trainer_id": "L1", "current_location": "Bengaluru"},
        *[{"trainer_id": f"O{index}", "location": "Chennai"} for index in range(9)],
    ]
    chosen = _location_balanced_trainers(scored, "Bengaluru")

    assert len(chosen) == 10
    assert sum(trainer["trainer_id"].startswith("L") for trainer in chosen) == 1
