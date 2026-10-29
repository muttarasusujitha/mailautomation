from app.routes.matching import _score_trainer
from app.routes.profile_enhancements import _fallback_analysis


def test_similar_names_do_not_imply_skill_eligibility():
    assert _score_trainer({"skills": ["JavaScript"], "experience_years": 10, "resume_rank_score": 100}, ["Java"], "", "") == 0
    assert _score_trainer({"skills": ["Excel"], "experience_years": 10, "resume_rank_score": 100}, ["Python"], "", "") == 0


def test_invalid_numeric_data_does_not_break_valid_matching():
    assert _score_trainer({"skills": ["Python"], "experience_years": "NaN", "resume_rank_score": "bad"}, ["Python"], "", "") == 10


def test_profile_mentions_require_experience_confirmation():
    result = _fallback_analysis({"required_skills": ["Python"]}, {"resume": "Python is listed in the skills section."})
    assert result["suggestions"]
    assert all(row["requires_trainer_confirmation"] for row in result["suggestions"])
    assert all("Applied" not in row["suggested_bullet"] for row in result["suggestions"])
