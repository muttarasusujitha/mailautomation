import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.clients.lead_personalization import collect_evidence, validate_draft, personalize_lead
from app.routes.client_leads import regenerate_lead_draft, RegenerateDraftRequest, send_lead_email, SendLeadEmailRequest
from app.routes.client_leads import _inferred_website, queue_auto_personalization


def test_research_excludes_other_companies_and_keeps_sources():
    search = AsyncMock(return_value=[
        {'url': 'https://acme.example/services', 'snippet': 'We build logistics software.'},
        {'url': 'https://acme.example.evil.test/', 'snippet': 'Wrong company'},
    ])
    with patch('app.clients.lead_personalization.search_public', search):
        evidence, warnings = asyncio.run(collect_evidence({'website': 'https://acme.example'}))
    assert len(evidence) == 1
    assert evidence[0]['source_url'] == 'https://acme.example/services'
    assert evidence[0]['retrieved_at']
    assert not warnings


def test_failed_research_preserves_provided_context():
    with patch('app.clients.lead_personalization.search_public', AsyncMock(side_effect=TimeoutError)):
        evidence, warnings = asyncio.run(collect_evidence({'website': 'acme.example', 'post_text': 'Python workshop requested'}))
    assert evidence[0]['text'] == 'Python workshop requested'
    assert warnings


@pytest.mark.parametrize('changes', [
    {'evidence_ids': ['invented']}, {'evidence_ids': []},
    {'offering_id': 'invented'}, {'subject': 'Hi\nBcc: person@example.com'},
    {'insufficient_evidence': True}, {'body': ''},
])
def test_invalid_evidence_or_offerings_are_rejected(changes):
    draft = {'subject': 'Python workshop', 'body': 'Hello', 'rationale': 'Fit',
             'proposed_application': 'Reporting', 'offering_id': 'training', 'evidence_ids': ['post']}
    with pytest.raises(ValueError):
        validate_draft(json.dumps({**draft, **changes}), [{'id': 'post'}], [{'id': 'training'}])


def test_generation_failure_does_not_overwrite_existing_draft():
    table = AsyncMock()
    table.find_one.return_value = {'lead_id': 'CL-1', 'draft_body': 'Existing'}
    with patch('app.clients.lead_personalization.personalize_lead', AsyncMock(side_effect=ValueError('Missing evidence'))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(regenerate_lead_draft('CL-1', RegenerateDraftRequest(), {'client_leads': table}))
    assert exc.value.status_code == 422
    table.update_one.assert_not_awaited()


def test_generation_saves_auditable_draft_without_sending():
    table = AsyncMock()
    table.find_one.return_value = {'lead_id': 'CL-1'}
    draft = {'subject': 'Relevant offer', 'body': 'Personal email', 'evidence': [{'id': 'post'}]}
    with patch('app.clients.lead_personalization.personalize_lead', AsyncMock(return_value=draft)), patch('app.routes.client_leads._post_with_local_fallback', AsyncMock()) as send:
        result = asyncio.run(regenerate_lead_draft('CL-1', RegenerateDraftRequest(), {'client_leads': table}))
    saved = table.update_one.await_args.args[1]['$set']
    assert saved['draft_body'] == result['body']
    assert saved['personalization']['evidence'] == draft['evidence']
    send.assert_not_awaited()


def test_send_requires_a_draft():
    table = AsyncMock()
    table.find_one.return_value = {'email': 'client@example.com'}
    with patch('app.routes.client_leads._post_with_local_fallback', AsyncMock()) as send:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(send_lead_email('CL-1', SendLeadEmailRequest(), {'client_leads': table}))
    assert exc.value.status_code == 400
    send.assert_not_awaited()


def test_personalization_passes_company_evidence_and_saved_services_to_writer():
    profiles = AsyncMock()
    profiles.find_one.return_value = {'offerings': [{'id': 'python', 'description': 'Practical Python workshops'}]}
    draft = {'subject': 'Python for logistics workflows', 'body': 'Hi Priya, a workshop could use shipment-data exercises.',
             'rationale': 'Logistics software context fits data exercises.', 'proposed_application': 'Shipment-data exercises',
             'offering_id': 'python', 'evidence_ids': ['lead_training_requirement'], 'trainer_ids_used': []}
    writer = AsyncMock(return_value={'success': True, 'reply': json.dumps(draft)})
    with patch('app.routes.assistant.assistant_chat', writer):
        result = asyncio.run(personalize_lead({'company_name': 'Acme', 'notes': 'Builds logistics software', 'training_requirement': {'topics': 'Python'}}, {'outreach_profiles': profiles}))
    request = writer.await_args.args[0]
    context = json.loads(request.messages[0].content)
    assert context['offerings'][0]['id'] == 'python'
    assert context['training_requirement']['topics'] == 'Python'
    assert result['body'] == draft['body']
    assert result['review_required'] is True


def test_no_context_does_not_call_writer():
    with patch('app.routes.assistant.assistant_chat', AsyncMock()) as writer:
        with pytest.raises(ValueError):
            asyncio.run(personalize_lead({'company_name': 'Acme'}, {}))
    writer.assert_not_awaited()


def test_business_contact_domain_becomes_research_website_without_user_input():
    assert _inferred_website({'contact_email': 'training@acme.example'}) == 'https://acme.example'
    assert _inferred_website({'contact_email': 'person@gmail.com'}) == ''


def test_queue_schedules_automatic_personalization(monkeypatch):
    scheduled = []
    monkeypatch.setattr('app.routes.client_leads.asyncio.create_task', lambda task: scheduled.append(task))
    queue_auto_personalization('CL-1', {})
    assert len(scheduled) == 1
    scheduled[0].close()
