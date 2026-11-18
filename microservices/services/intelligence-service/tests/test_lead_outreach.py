"""Single and bulk trainer outreach, and the public email lookup's failure report."""
import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.routes.trainer_profile_leads import (
    EnrichRequest,
    SendOutreachRequest,
    enrich_public_emails,
    send_lead_outreach,
    send_public_email_outreach,
)
from fake_mongo import FakeDB


class Client:
    def __init__(self, status=200):
        self.status = status
        self.sent = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.sent.append((url, kwargs.get('json')))
        return httpx.Response(self.status, json={}, request=httpx.Request('POST', url))


def seeded(*leads):
    db = FakeDB()
    for lead in leads:
        asyncio.run(db['trainer_profile_leads'].insert_one({'status': 'new', 'domain': 'Python', 'name': 'Ravi', **lead}))
    return db


def lead(db, lead_id):
    return next(doc for doc in db['trainer_profile_leads'].docs if doc['lead_id'] == lead_id)


def send(db, lead_id, client, **fields):
    with patch('httpx.AsyncClient', client):
        return asyncio.run(send_lead_outreach(lead_id, SendOutreachRequest(**fields), db))


def test_a_typed_email_is_used_saved_and_the_page_status_is_set():
    # Shortlist and Naukri pages send to_email and no lead_ids; that request used to fail validation.
    db = seeded({'lead_id': 'TPL-1'})
    client = Client()
    result = send(db, 'TPL-1', client, to_email=' ravi@example.com ', sent_status='contacted', domain='Python', mode='Online')
    assert result['sent_to'] == 'ravi@example.com' and result['status'] == 'contacted'
    assert client.sent[0][1]['to'] == 'ravi@example.com'
    saved = lead(db, 'TPL-1')
    assert saved['status'] == 'contacted' and saved['email'] == saved['contact_email'] == 'ravi@example.com'


def test_saved_contact_email_is_used_and_the_default_status_is_unchanged():
    db = seeded({'lead_id': 'TPL-1', 'email': '', 'contact_email': 'asha@example.com'})
    client = Client()
    send(db, 'TPL-1', client, sent_status='anything-else')
    assert client.sent[0][1]['to'] == 'asha@example.com'
    assert lead(db, 'TPL-1')['status'] == 'outreach_sent'


@pytest.mark.parametrize('fields,status', [({'to_email': 'not-an-email'}, 400), ({}, 400)])
def test_missing_or_invalid_addresses_are_rejected(fields, status):
    db = seeded({'lead_id': 'TPL-1'})
    with pytest.raises(HTTPException) as error:
        send(db, 'TPL-1', Client(), **fields)
    assert error.value.status_code == status


def test_a_failed_send_keeps_the_lead_visible():
    db = seeded({'lead_id': 'TPL-1', 'email': 'ravi@example.com', 'status': 'reviewed'})
    with pytest.raises(HTTPException) as error:
        send(db, 'TPL-1', Client(status=500), sent_status='contacted')
    assert error.value.status_code == 502
    saved = lead(db, 'TPL-1')
    assert saved['status'] == 'reviewed' and 'HTTP 500' in saved['last_email_error']


def test_bulk_outreach_needs_lead_ids_and_reports_each_failure():
    db = seeded({'lead_id': 'TPL-1', 'email': 'ravi@example.com'}, {'lead_id': 'TPL-2'})
    with pytest.raises(HTTPException) as error:
        asyncio.run(send_public_email_outreach(SendOutreachRequest(), db))
    assert error.value.status_code == 400
    with patch('httpx.AsyncClient', Client()):
        result = asyncio.run(send_public_email_outreach(
            SendOutreachRequest(lead_ids=['TPL-1', 'TPL-2', 'TPL-1'], sent_status='contacted'), db))
    assert result['sent'] == 1 and result['failed'] == 1
    assert result['errors'] == [{'lead_id': 'TPL-2', 'error': 'No email found for this lead'}]
    assert lead(db, 'TPL-1')['status'] == 'contacted'


def test_public_email_lookup_reports_when_every_lookup_fails():
    db = seeded({'lead_id': 'TPL-1', 'email': ''}, {'lead_id': 'TPL-2', 'email': ''})
    with patch('httpx.AsyncClient', Client(status=404)):
        result = asyncio.run(enrich_public_emails(EnrichRequest(lead_ids=['TPL-1', 'TPL-2']), db))
    assert result == {'success': False, 'checked': 2, 'enriched': 0, 'failed': 2,
                      'error': 'The contact lookup returned HTTP 404.'}


@pytest.mark.parametrize('status,after', [
    ('new', 'contacted'), ('found', 'contacted'), ('reviewed', 'contacted'), ('outreach_failed', 'contacted'),
    ('converted', 'converted'), ('rejected', 'rejected'), ('interview_scheduled', 'interview_scheduled'),
])
def test_a_send_moves_only_leads_not_contacted_yet(status, after):
    db = seeded({'lead_id': 'TPL-1', 'email': 'ravi@example.com', 'status': status})
    result = send(db, 'TPL-1', Client(), sent_status='contacted')
    assert lead(db, 'TPL-1')['status'] == after and result['status'] == after


def test_bulk_outreach_sent_again_does_not_email_anyone_twice():
    # For example after the gateway timed out a request that the server went on to finish.
    db = seeded({'lead_id': 'TPL-1', 'email': 'ravi@example.com'}, {'lead_id': 'TPL-2', 'email': 'asha@example.com',
                                                                    'status': 'converted'})
    client = Client()
    request = SendOutreachRequest(lead_ids=['TPL-1', 'TPL-2'], sent_status='contacted')
    with patch('httpx.AsyncClient', client):
        first = asyncio.run(send_public_email_outreach(request, db))
        again = asyncio.run(send_public_email_outreach(request, db))
    assert (first['sent'], first['skipped']) == (1, 1)
    assert (again['sent'], again['skipped']) == (0, 2)
    assert [body['to'] for _url, body in client.sent] == ['ravi@example.com']
