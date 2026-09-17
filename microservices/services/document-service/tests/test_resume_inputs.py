import asyncio
import sys
from types import SimpleNamespace

from app.routes import resume
from app.routes.resume import _detected_skills_from_text, _regex_profile


def test_ai_invented_linkedin_is_removed():
    result = resume._normalise_profile({
        'name': 'Asha Rao', 'linkedin': 'https://linkedin.com/in/invented-asha',
        'linkedin_url': 'https://linkedin.com/in/invented-asha',
    }, 'Asha Rao\nAWS trainer')
    assert result['linkedin'] == ''
    assert result['linkedin_url'] == ''


def test_source_linkedin_overrides_ai_guess():
    result = resume._normalise_profile({
        'name': 'Asha Rao', 'linkedin': 'https://linkedin.com/in/invented-asha',
    }, 'Asha Rao\nwww.linkedin.com/in/supplied-asha')
    assert result['linkedin'] == 'https://www.linkedin.com/in/supplied-asha'


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


def test_openai_resume_extraction_is_used_when_configured(monkeypatch):
    class FakeResponses:
        async def create(self, **kwargs):
            assert kwargs['model'] == 'test-model'
            assert 'Resume:' in kwargs['input']
            return SimpleNamespace(output_text='{"name":"Asha Rao","skills":["AWS"]}')

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs['api_key'] == 'test-key'
            self.responses = FakeResponses()

    monkeypatch.setattr(resume.settings, 'OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(resume.settings, 'OPENAI_MODEL', 'test-model')
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(AsyncOpenAI=FakeClient))
    assert asyncio.run(resume._openai_profile('Asha Rao\nAWS trainer')) == {
        'name': 'Asha Rao', 'skills': ['AWS']}


def test_openai_resume_extraction_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(resume.settings, 'OPENAI_API_KEY', '')
    assert asyncio.run(resume._openai_profile('Asha Rao')) == {}
