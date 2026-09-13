from app.routes.resume import _detected_skills_from_text, _regex_profile


def test_fallback_keeps_supported_specialist_skills():
    skills = _detected_skills_from_text('DevOps, SRE, Machine Learning, Spark, Databricks, Kafka, Airflow, LangChain')
    assert {'DevOps', 'SRE', 'Machine Learning', 'Spark', 'Databricks', 'Kafka', 'Airflow', 'LangChain'} <= set(skills)


def test_skill_boundaries_do_not_confuse_java_and_javascript():
    assert 'Java' not in _detected_skills_from_text('JavaScript developer')
    assert 'SQL' not in _detected_skills_from_text('NoSQL specialist')


def test_regex_resume_retains_identity_and_skill_evidence():
    result = _regex_profile('Suresh Reddy\nsuresh@example.com\n8 years experience\nDevOps, Terraform, Kubernetes, Kafka', 'resume.pdf')
    assert result['name'] == 'Suresh Reddy'
    assert result['email'] == 'suresh@example.com'
    assert result['experience_years'] == 8
    assert 'Kafka' in result['skills']
    assert result['needs_review'] is True
