import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import recipient_guard
from app.routes import send


def setup_sender(monkeypatch, existing):
    monkeypatch.setattr(recipient_guard, 'recipient_error', AsyncMock(return_value=''))
    monkeypatch.setattr(send, '_gmail_quota_cooldown', AsyncMock(return_value=None))
    deliveries = []

    async def deliver(**kwargs):
        deliveries.append(kwargs)
        await asyncio.sleep(0)
        return True, ''

    monkeypatch.setattr(send, 'send_email_async', deliver)

    async def find_one(query, projection):
        return {key: value for key, value in existing.items() if projection.get(key)}

    logs = SimpleNamespace(find_one=AsyncMock(side_effect=find_one),
                           update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)))
    db = SimpleNamespace(email_logs=logs)
    payload = send.SendEmailRequest(to='client@example.com', subject='Interview slots', body='Review package',
                                   mail_type='client_slots', idempotency_key='client-handoff:REQ:TR:client')
    return db, payload, deliveries


def test_stale_sending_record_can_recover_and_reuses_message_id(monkeypatch):
    db, payload, deliveries = setup_sender(monkeypatch, {
        'email_id': 'EML-1', 'status': 'sending', 'message_id_header': '<stable@example.com>',
        'updated_at': datetime.utcnow() - timedelta(minutes=11),
    })
    result = asyncio.run(send.send_single_email(payload, db))
    assert result['success'] is True
    assert len(deliveries) == 1
    assert deliveries[0]['message_id_header'] == '<stable@example.com>'


def test_concurrent_failed_retries_have_one_physical_sender(monkeypatch):
    db, payload, deliveries = setup_sender(monkeypatch, {
        'email_id': 'EML-1', 'status': 'failed', 'updated_at': datetime.utcnow(),
    })
    db.email_logs.update_one.side_effect = [SimpleNamespace(modified_count=n) for n in (1, 0, 1)]

    async def run():
        return await asyncio.gather(send.send_single_email(payload, db), send.send_single_email(payload, db))

    results = asyncio.run(run())
    assert len(deliveries) == 1
    assert sum(bool(result.get('success')) for result in results) == 1
    assert sum(bool(result.get('already_in_progress')) for result in results) == 1


def test_sent_handoff_never_sends_again(monkeypatch):
    db, payload, deliveries = setup_sender(monkeypatch, {'email_id': 'EML-1', 'status': 'sent'})
    result = asyncio.run(send.send_single_email(payload, db))
    assert result['already_sent'] is True
    assert deliveries == []
