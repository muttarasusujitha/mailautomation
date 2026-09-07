import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from fastapi import HTTPException
from app.routes import finance_approvals as finance, purchase_orders as po, invoices, interview_reminders as reminders


def database():
    db = {}
    for name in ('finance_approvals', 'purchase_orders', 'invoices', 'requirements', 'interview_reminders'):
        db[name] = SimpleNamespace(find_one=AsyncMock(return_value={
            'status': 'draft', 'client_email': 'client@example.com',
            'trainer_email': 'trainer@example.com', 'interview_link': 'https://meet.google.com/test',
        }), update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)), insert_one=AsyncMock())
    async def insert(doc):
        doc['_id'] = ObjectId()  # Motor mutates the inserted document.
    db['invoices'].insert_one.side_effect = insert
    return db


def transport(monkeypatch, pdf_status=200, mail_status=200):
    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if '/documents/' in request.url.path:
            return httpx.Response(pdf_status, content=b'%PDF-test')
        return httpx.Response(mail_status, json={'success': mail_status == 200, 'email_id': 'TEST'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    return requests


def test_finance_approval_serializes_dates_and_excludes_database_id(monkeypatch):
    requests = transport(monkeypatch)
    db = database()
    payload = finance.FinanceApproveRequest(client_name='Test', client_email='client@example.com', po_number='TEST', total_amount=1000)
    result = asyncio.run(finance.approve_and_send_invoice('TEST', payload, db))
    assert result['status'] == 'invoice_sent'
    assert len(requests) == 2
    assert '_id' not in requests[0][1]
    assert isinstance(requests[0][1]['created_at'], str)
    assert requests[1][1]['attachments']


def test_invalid_amount_does_not_claim_approval():
    db = database()
    payload = finance.FinanceApproveRequest(client_name='Test', client_email='client@example.com', po_number='TEST', total_amount=0)
    with pytest.raises(HTTPException):
        asyncio.run(finance.approve_and_send_invoice('TEST', payload, db))
    db['finance_approvals'].update_one.assert_not_awaited()


@pytest.mark.parametrize('kind', ['po', 'invoice'])
@pytest.mark.parametrize('pdf_status,mail_status', [(500, 200), (200, 500), (200, 200)])
def test_document_delivery_status(monkeypatch, kind, pdf_status, mail_status):
    requests = transport(monkeypatch, pdf_status, mail_status)
    db = database()
    call = (po.send_po('TEST', po.POSendRequest(to_email='client@example.com'), db) if kind == 'po'
            else invoices.send_invoice('TEST', invoices.InvoiceSendRequest(to_email='client@example.com'), db))
    collection = db['purchase_orders' if kind == 'po' else 'invoices']
    if pdf_status != 200 or mail_status != 200:
        with pytest.raises(HTTPException):
            asyncio.run(call)
        collection.update_one.assert_not_awaited()
        if pdf_status != 200:
            assert len(requests) == 1
    else:
        assert asyncio.run(call)['success']
        assert requests[-1][1]['attachments']
        collection.update_one.assert_awaited_once()


def test_reschedule_sends_both_invites_before_updating(monkeypatch):
    requests = transport(monkeypatch)
    db = database()
    result = asyncio.run(reminders.reschedule_reminder('TEST', reminders.RescheduleRequest(new_interview_at='2026-10-01T10:00:00'), db))
    assert result['success']
    assert {body['to'] for _, body in requests} == {'trainer@example.com', 'client@example.com'}
    assert all(body['calendar_invite']['meeting_url'] for _, body in requests)
    db['interview_reminders'].update_one.assert_awaited_once()


def test_reschedule_delivery_failure_does_not_mark_complete(monkeypatch):
    transport(monkeypatch, mail_status=500)
    db = database()
    with pytest.raises(HTTPException):
        asyncio.run(reminders.reschedule_reminder('TEST', reminders.RescheduleRequest(new_interview_at='2026-10-01T10:00:00'), db))
    db['interview_reminders'].update_one.assert_not_awaited()
