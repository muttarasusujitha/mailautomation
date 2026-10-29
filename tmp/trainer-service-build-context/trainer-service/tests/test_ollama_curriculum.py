import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import ollama_curriculum as oc
from app.routes.toc import TocRequest


def curriculum():
    return oc.ClientCurriculum.model_validate({
        "overview": "Prepare invoice records and report rejected rows for finance analysts.",
        "excluded_topics": ["Django", "web APIs"],
        "days": [{
            "day": 1, "focus_area": "Invoice CSV validation",
            "subtopics": ["CSV parsing", "Missing IDs", "Duplicate invoices"],
            "lab": "Validate an invoice CSV and save accepted and rejected rows with reasons.",
            "learning_objectives": ["Parse invoice CSV", "Detect missing IDs", "Report duplicate invoices"],
            "tools": ["Python", "csv"],
            "prerequisites": ["Read Python lists and dictionaries"],
            "preparation_requirements": ["Provide invoices.csv with valid, missing and duplicate invoice IDs"],
            "prerequisite_days": [],
            "deliverable": "validator.py, accepted.csv and rejected.csv with rejection reasons",
            "assessment": "Run validator.py on the invoice fixture and compare CSV rows with the expected files",
            "acceptance_checks": [
                {"input_or_condition": "Invoice INV-001 has all required CSV fields",
                 "expected_result": "INV-001 appears once in accepted.csv",
                 "evidence": "accepted.csv row containing invoice INV-001"},
                {"input_or_condition": "Two input rows contain invoice ID INV-002",
                 "expected_result": "Second INV-002 is rejected with a duplicate reason",
                 "evidence": "rejected.csv row for INV-002 with duplicate reason"},
                {"input_or_condition": "Run the validator twice with the same invoice CSV",
                 "expected_result": "Output CSV files have identical contents on both runs",
                 "evidence": "File comparison of accepted.csv and rejected.csv across runs"},
            ],
        }]
    })


def request(**kwargs):
    return TocRequest(domain="Python", duration_days=1, hours_per_day=3, **kwargs)


def test_complete_client_plan_passes_structural_checks():
    plan = curriculum()
    payload = request(custom_topics="CSV")
    brief, days = oc._materialize_curriculum(plan, payload)
    brief.excluded_topics = plan.excluded_topics
    errors, coverage, evaluation = oc.validate_curriculum(
        {"overview": plan.overview, "days": days, "excluded_topics": plan.excluded_topics}, payload)
    assert not errors
    assert coverage == {"CSV": [1]}
    assert evaluation["status"] == "pass"
    assert evaluation["technical_accuracy_verified"] is False


@pytest.mark.parametrize("fault", ["missing_topic", "excluded", "overload", "future_prerequisite", "missing_objectives", "wrong_minutes"])
def test_invalid_curriculum_is_flagged(fault):
    model = curriculum()
    payload = request(custom_topics="FastAPI" if fault == "missing_topic" else "")
    brief, days = oc._materialize_curriculum(model, payload)
    if fault == "excluded":
        model.excluded_topics = ["CSV"]
    if fault == "overload":
        payload.hours_per_day = 1
        with pytest.raises(ValueError, match="At least 90 training minutes"):
            oc._materialize_curriculum(model, payload)
        return
    if fault == "future_prerequisite":
        days[0]["prerequisite_days"] = [2]
    if fault == "missing_objectives":
        days[0]["learning_objectives"] = []
    if fault == "wrong_minutes":
        days[0]["delivery_steps"][0]["minutes"] += 5
    result = {"overview": model.overview, "days": days, "excluded_topics": model.excluded_topics}
    assert oc.validate_curriculum(result, payload)[0]


def test_wrong_day_count_is_rejected():
    payload = request()
    payload.duration_days = 2
    _, days = oc._materialize_curriculum(curriculum(), payload)
    with pytest.raises(ValueError, match="exactly the requested days"):
        oc.validate_curriculum({"days": days}, payload)


def test_generated_lab_evidence_and_prerequisites_are_preserved():
    model = curriculum()
    _, days = oc._materialize_curriculum(model, request())
    for field in ('tools', 'prerequisites', 'preparation_requirements', 'prerequisite_days',
                  'deliverable', 'assessment', 'acceptance_checks'):
        assert days[0][field] == model.model_dump()['days'][0][field]
    assert days[0]['delivery_steps'][-1]['activity'] == model.days[0].assessment
    assert 'rejected.csv' in days[0]['delivery_steps'][-1]['evidence']


@pytest.mark.parametrize('fault', ['generic', 'duplicate', 'empty'])
def test_boilerplate_or_repeated_lab_evidence_cannot_pass(fault):
    _, days = oc._materialize_curriculum(curriculum(), request())
    checks = days[0]['acceptance_checks']
    if fault == 'generic':
        checks[0]['expected_result'] = 'Participant completes the lab and meets the stated objectives.'
    elif fault == 'duplicate':
        checks[1]['expected_result'] = checks[0]['expected_result']
        checks[1]['evidence'] = checks[0]['evidence']
    else:
        checks[0]['evidence'] = ''
    errors, _, evaluation = oc.validate_curriculum({'days': days}, request())
    assert any('lab-specific acceptance checks' in error for error in errors)
    assert evaluation['assessable_modules'] == 0
    assert evaluation['status'] != 'pass'


def test_missing_model_authored_evidence_is_not_silently_filled():
    from pydantic import ValidationError
    data = curriculum().model_dump()
    del data['days'][0]['acceptance_checks']
    with pytest.raises(ValidationError):
        oc.ClientCurriculum.model_validate(data)


def test_no_dataset_match_still_uses_model_topics_and_client_context(monkeypatch):
    monkeypatch.setattr(oc, "load_records", AsyncMock(return_value=[]))
    response = AsyncMock(return_value=SimpleNamespace(output_text=curriculum().model_dump_json()))
    monkeypatch.setattr(oc, "OllamaClient", lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=response)))
    settings = SimpleNamespace(OLLAMA_URL="http://test/api/generate", OLLAMA_MODEL="test", OLLAMA_TOC_TIMEOUT_SECONDS=300)
    payload = request(client_notes="Finance analysts must validate invoice CSV files; exclude Django", notes="Participants know Python")
    result = asyncio.run(oc.generate_client_curriculum(payload, settings))
    context = json.loads(response.call_args.kwargs["input"])
    assert context["optional_references"] == []
    assert context["request"]["client_notes"] == payload.client_notes
    assert context["request"]["notes"] == payload.notes
    assert result["days"][0]["focus_area"] == "Invoice CSV validation"
    assert result["planning_method"] == "ollama_client_curriculum"
    assert result["quality"]["status"] == "requires_review"
    assert "date" not in result["days"][0]


def test_ollama_transport_uses_native_schema_only_when_requested(monkeypatch):
    from app import ollama_client
    sent = []

    class HttpClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            sent.append(json)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"response": '{"ok":true}'})

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", HttpClient)
    client = ollama_client.OllamaClient("http://test")
    schema = {"type": "object"}
    asyncio.run(client.responses.create(model="test", input="plan", native_schema=True, think=False,
        text={"format": {"type": "json_schema", "schema": schema}}))
    asyncio.run(client.responses.create(model="test", input="mail"))
    assert sent[0]["format"] == schema and sent[0]["think"] is False
    assert "format" not in sent[1] and "think" not in sent[1]
    assert json.dumps(schema) in sent[0]['system']
    assert sent[0]['options']['temperature'] == 0
    assert sent[1]['options']['temperature'] == 0.7


@pytest.mark.parametrize('first_failure', ['empty', 'missing_topic'])
def test_one_retry_repairs_empty_or_incomplete_output_within_original_budget(monkeypatch, first_failure):
    monkeypatch.setattr(oc, 'load_records', AsyncMock(return_value=[]))
    valid = curriculum().model_dump_json()
    first = ValueError('Ollama returned an empty generate response') if first_failure == 'empty' else SimpleNamespace(
        output_text=valid.replace('CSV', 'JSON'))
    create = AsyncMock(side_effect=[first, SimpleNamespace(output_text=valid)])
    timeouts = []
    def client(*args, **kwargs):
        timeouts.append(kwargs['timeout'])
        return SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(oc, 'OllamaClient', client)
    settings = SimpleNamespace(OLLAMA_URL='http://test', OLLAMA_MODEL='test', OLLAMA_TOC_TIMEOUT_SECONDS=300)
    result = asyncio.run(oc.generate_client_curriculum(request(custom_topics='CSV'), settings))
    assert result['generation_attempts'] == 2
    assert not result['quality']['validation_errors']
    assert 0 < timeouts[1] <= timeouts[0] <= 300
    retry_input = json.loads(create.await_args_list[1].kwargs['input'])
    assert retry_input['corrections_required']
    assert retry_input['request']['custom_topics'] == 'CSV'


def test_repeated_incomplete_output_remains_blocked_after_two_attempts(monkeypatch):
    monkeypatch.setattr(oc, 'load_records', AsyncMock(return_value=[]))
    create = AsyncMock(return_value=SimpleNamespace(output_text=curriculum().model_dump_json()))
    monkeypatch.setattr(oc, 'OllamaClient', lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)))
    settings = SimpleNamespace(OLLAMA_URL='http://test', OLLAMA_MODEL='test', OLLAMA_TOC_TIMEOUT_SECONDS=300)
    result = asyncio.run(oc.generate_client_curriculum(request(custom_topics='FastAPI'), settings))
    assert create.await_count == 2
    assert result['quality']['status'] == 'requires_regeneration'


def test_expired_request_is_not_retried_with_a_fresh_timeout(monkeypatch):
    monkeypatch.setattr(oc, 'load_records', AsyncMock(return_value=[]))
    create = AsyncMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr(oc, 'OllamaClient', lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)))
    settings = SimpleNamespace(OLLAMA_URL='http://test', OLLAMA_MODEL='test', OLLAMA_TOC_TIMEOUT_SECONDS=300)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(oc.generate_client_curriculum(request(), settings))
    assert create.await_count == 1


def test_retry_drops_conflicting_reference_examples_and_retains_client_brief(monkeypatch):
    references = [{'domain': 'Python', 'title': 'Orders', 'subtopics': ['Duplicate order IDs']}]
    monkeypatch.setattr(oc, 'load_records', AsyncMock(return_value=[]))
    monkeypatch.setattr(oc, 'retrieve', AsyncMock(return_value=(references, {})))
    valid = curriculum().model_dump_json()
    create = AsyncMock(side_effect=[SimpleNamespace(output_text=valid.replace('CSV', 'JSON')),
                                   SimpleNamespace(output_text=valid)])
    monkeypatch.setattr(oc, 'OllamaClient', lambda *args, **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)))
    settings = SimpleNamespace(OLLAMA_URL='http://test', OLLAMA_MODEL='test', OLLAMA_TOC_TIMEOUT_SECONDS=300)
    result = asyncio.run(oc.generate_client_curriculum(request(custom_topics='CSV', client_notes='Invoice validation'), settings))
    first, retry = [json.loads(call.kwargs['input']) for call in create.await_args_list]
    assert first['optional_references'] == references
    assert retry['optional_references'] == []
    assert retry['required_topic_names'] == ['CSV']
    assert retry['request']['client_notes'] == 'Invoice validation'
    assert result['generation_attempts'] == 2
    assert not result['quality']['validation_errors']
