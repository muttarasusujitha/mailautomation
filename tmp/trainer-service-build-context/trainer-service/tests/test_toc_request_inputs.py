import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.routes import toc, shortlists


def test_exhausted_enrichment_quota_retains_curriculum_and_stops_remaining_calls(monkeypatch):
    generate = AsyncMock(side_effect=RuntimeError('credit_balance_exhausted'))
    monkeypatch.setattr(toc, '_generate_ai_day_enrichment', generate)
    curriculum = {'domain': 'DevOps', 'days': [{'day': i, 'lab': 'Existing lab'} for i in range(1, 21)]}
    count = asyncio.run(toc._enrich_toc_days_with_ai(object(), 'test-model', curriculum))
    assert count == 0
    assert curriculum['ai_enriched_days'] == 0
    assert generate.await_count <= 5
    assert all(day['lab'] == 'Existing lab' for day in curriculum['days'])


def test_day_enrichment_omits_unsupported_sampling_parameter():
    create = AsyncMock(return_value=SimpleNamespace(output_text='{}'))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    asyncio.run(toc._generate_ai_day_enrichment(client, 'gpt-5.5', 'DevOps', {}))
    assert 'temperature' not in create.call_args.kwargs
    assert create.call_args.kwargs['model'] == 'gpt-5.5'


@pytest.mark.parametrize('hours,expected', [(None, 3), (3, 3), (5, 5), (8, 8)])
def test_handoff_preserves_training_hours_and_individual_topics(monkeypatch, hours, expected):
    generate = AsyncMock(return_value={'toc_data': {'days': []}})
    monkeypatch.setattr(toc, 'generate_toc', generate)
    db = {'automation_settings': SimpleNamespace(find_one=AsyncMock(return_value={}))}
    asyncio.run(shortlists._build_toc({
        'technology_needed': 'DevOps including AWS and Azure', 'duration_days': 15,
        'training_hours_per_day': hours, 'lab_hours_per_day': 8,
        'requested_topics': ['Git', 'Docker'],
    }, {}, db))
    request = generate.call_args.args[0]
    assert request.hours_per_day == expected
    assert request.custom_topics == 'DevOps; AWS; Azure; Git; Docker'


def test_quality_checks_combined_technology_phrase_individually():
    document = {
        'quality': {'status': 'approved'},
        'days': [{'focus_area': 'DevOps', 'subtopics': ['AWS pipelines', 'Azure deployments']}],
    }
    toc._apply_requirement_quality(document, toc.TocRequest(
        domain='DevOps including AWS and Azure',
        custom_topics='DevOps including AWS and Azure',
        hours_per_day=3,
    ))
    assert document['quality']['missing_requested_topics'] == []
    assert document['quality']['status'] == 'approved'


@pytest.mark.parametrize('duration_text,numeric,expected', [
    ('20 Training Days', None, 20),
    ('15 days', None, 15),
    ('10 working days', None, 10),
    ('60 hours', None, 3),
    ('20 Training Days', 12, 12),
])
def test_mail1_toc_reads_saved_duration_text(monkeypatch, duration_text, numeric, expected):
    generate = AsyncMock(return_value={'toc_data': {'days': []}})
    monkeypatch.setattr(toc, 'generate_toc', generate)
    db = {'automation_settings': SimpleNamespace(find_one=AsyncMock(return_value={}))}
    asyncio.run(shortlists._build_toc({
        'technology_needed': 'Advanced DevOps with AWS & Azure',
        'duration_text': duration_text, 'duration_days': numeric,
    }, {}, db))
    assert generate.call_args.args[0].duration_days == expected


def test_twenty_day_devops_agenda_passes_delivery_quality():
    from app.toc_generation_agent import generate_combined_toc_from_datasets, validate_toc
    from shared.toc_quality import toc_delivery_error

    request = toc.TocRequest(
        domain='Advanced DevOps with AWS & Azure', duration_days=20,
        hours_per_day=3, custom_topics='DevOps; AWS; Azure',
    )
    document = validate_toc(generate_combined_toc_from_datasets(
        toc._inferred_technology_allocations(request), request.level,
    ), 20)
    toc._apply_requirement_quality(document, request)
    assert len(document['days']) == 20
    assert document['quality']['status'] == 'approved'
    assert not toc_delivery_error(document)


def test_mail1_toc_inherits_advanced_audience(monkeypatch):
    generate = AsyncMock(return_value={'toc_data': {'days': []}})
    monkeypatch.setattr(toc, 'generate_toc', generate)
    db = {'automation_settings': SimpleNamespace(find_one=AsyncMock(return_value={}))}
    asyncio.run(shortlists._build_toc({'technology_needed': 'DevOps', 'audience_level': 'advanced'}, {}, db))
    assert generate.call_args.args[0].level == 'advanced'
