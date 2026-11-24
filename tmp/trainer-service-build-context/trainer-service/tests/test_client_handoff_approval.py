import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import handoff
from app.routes import shortlists
from test_client_handoff_package import prepare, SLOTS


async def prepare_package(db, **extra):
    return await shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS, **extra), db)


def test_blocked_package_rebuilds_only_after_inputs_change(monkeypatch):
    from shared.handoff_inputs import handoff_input_version
    db, requests = prepare(monkeypatch)
    asyncio.run(prepare_package(db))
    saved = next(iter(db['client_handoff_packages'].docs.values()))
    requirement = db['requirements'].find_one.return_value
    saved.update(status='needs_input', input_version=handoff_input_version(requirement))
    old_id = saved['package_id']
    requests.clear()
    assert asyncio.run(prepare_package(db))['needs_input']
    assert requests == []
    requirement['fx_rate'] = 85
    resumed = asyncio.run(prepare_package(db))
    assert resumed['success']
    assert resumed['package_id'] != old_id
    assert sum(path.endswith('/email/send') for path, _ in requests) == 1


def test_complete_package_is_delivered_automatically(monkeypatch):
    db, requests = prepare(monkeypatch)
    result = asyncio.run(prepare_package(db, approved=True))
    assert result['success'] and not result['pending_approval']
    assert sum(path.endswith('/email/send') for path, _ in requests) == 1


def test_duplicate_slots_cannot_make_a_complete_package(monkeypatch):
    db, requests = prepare(monkeypatch)
    repeated = '\n'.join([SLOTS.splitlines()[0]] * 3)
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=repeated), db))
    assert error.value.status_code == 400
    assert requests == []


def test_repeat_preparation_reuses_saved_snapshot(monkeypatch):
    db, requests = prepare(monkeypatch)
    first = asyncio.run(prepare_package(db))
    requests.clear()
    second = asyncio.run(prepare_package(db))
    assert first['package_id'] == second['package_id']
    assert requests == []


def test_lab_document_is_optional_when_not_requested(monkeypatch):
    db, requests = prepare(monkeypatch, failure='lab', requirement_overrides={'lab_cost_requested': False})
    result = asyncio.run(prepare_package(db))
    assert result['success']
    assert not any(path.endswith('/lab-cost') for path, _ in requests)
    review = asyncio.run(shortlists.review_client_handoff('REQ-TEST', 'T-TEST', db))
    assert len(review['attachments']) == 2
    assert review['lab_cost_requested'] is False
    assert review['lab_cost_attached'] is False
    assert 'Commercials for your review' in review['body']
    assert 'smtp_config' not in review


def test_review_marks_requested_lab_estimate_as_attached(monkeypatch):
    db, _ = prepare(monkeypatch)
    asyncio.run(prepare_package(db))
    review = asyncio.run(shortlists.review_client_handoff('REQ-TEST', 'T-TEST', db))
    assert review['lab_cost_requested'] is True
    assert review['lab_cost_attached'] is True
    assert any('Lab Cost Estimate' in item['filename'] for item in review['attachments'])


def test_unapproved_package_cannot_reach_sender(monkeypatch):
    db, requests = prepare(monkeypatch)
    asyncio.run(prepare_package(db))
    saved = next(iter(db['client_handoff_packages'].docs.values()))
    saved['status'] = 'needs_input'
    requests.clear()
    with pytest.raises(HTTPException) as error:
        asyncio.run(handoff.deliver_approved_package(db, saved))
    assert error.value.status_code == 409
    assert not any(path.endswith('/email/send') for path, _ in requests)


def test_stale_version_and_changed_recipient_block_approval(monkeypatch):
    db, requests = prepare(monkeypatch)
    result = asyncio.run(prepare_package(db))
    requests.clear()
    for version in ['PKG-OLD', result['package_id']]:
        if version == result['package_id']:
            db['requirements'].find_one.return_value['client_email'] = 'different@example.com'
        with pytest.raises(HTTPException) as error:
            asyncio.run(shortlists.approve_client_handoff('REQ-TEST', 'T-TEST',
                shortlists.ApproveHandoffRequest(package_id=version), db))
        assert error.value.status_code == 409
    assert not any(path.endswith('/email/send') for path, _ in requests)


def test_duplicate_and_concurrent_approvals_send_one_frozen_package(monkeypatch):
    db, requests = prepare(monkeypatch)

    async def run():
        result = await prepare_package(db)
        review = await shortlists.review_client_handoff('REQ-TEST', 'T-TEST', db)
        payload = shortlists.ApproveHandoffRequest(package_id=result['package_id'])
        await asyncio.gather(*(shortlists.approve_client_handoff('REQ-TEST', 'T-TEST', payload, db) for _ in range(2)))
        await shortlists.approve_client_handoff('REQ-TEST', 'T-TEST', payload, db)
        sent = [mail for path, mail in requests if path.endswith('/email/send')]
        assert len(sent) == 1
        assert sent[0]['body'] == review['body']
        assert sent[0]['attachments'] == review['attachments']
        assert sent[0]['ai_generate'] is False
    asyncio.run(run())


def test_failed_approved_delivery_recovers_without_restart_or_regeneration(monkeypatch):
    db, requests = prepare(monkeypatch)

    async def run():
        result = await prepare_package(db)
        package = next(iter(db['client_handoff_packages'].docs.values()))
        package['status'] = 'approved'
        sender = AsyncMock(side_effect=[HTTPException(502, 'Provider unavailable'),
                                       {'success': True, 'email_id': 'EML-RECOVERED'}])
        monkeypatch.setattr(shortlists, '_deliver_client_handoff', sender)
        with pytest.raises(HTTPException):
            await shortlists.approve_client_handoff('REQ-TEST', 'T-TEST',
                shortlists.ApproveHandoffRequest(package_id=result['package_id']), db)
        assert package['status'] == 'approved'
        await handoff.retry_approved_packages(db)
        assert sender.await_count == 1
        package['retry_after'] = datetime.utcnow() - timedelta(seconds=1)
        requests.clear()
        await handoff.retry_approved_packages(db)
        assert sender.await_count == 2
        assert package['status'] == 'sent'
        assert package['email_id'] == 'EML-RECOVERED'
        assert requests == []
    asyncio.run(run())


def test_expired_worker_lease_recovers_without_resending_sent_package(monkeypatch):
    db, _ = prepare(monkeypatch)

    async def run():
        await prepare_package(db)
        sender = AsyncMock(return_value={'success': True, 'email_id': 'EML-RECOVERED'})
        monkeypatch.setattr(shortlists, '_deliver_client_handoff', sender)
        await handoff.retry_approved_packages(db)
        sender.assert_not_awaited()
        saved = next(iter(db['client_handoff_packages'].docs.values()))
        saved.update(status='approved', lease_until=datetime.utcnow() - timedelta(seconds=1))
        await handoff.retry_approved_packages(db)
        sender.assert_awaited_once()
    asyncio.run(run())


def test_rebuild_invalidates_old_approval_version(monkeypatch):
    db, requests = prepare(monkeypatch)

    async def run():
        first = await prepare_package(db)
        # A legacy pending package can still be rebuilt; delivered packages
        # cannot. Simulate the pre-automatic-delivery persisted state.
        next(iter(db['client_handoff_packages'].docs.values()))['status'] = 'pending_approval'
        requests.clear()
        db['shortlists'].find_one.return_value['top_trainers'][0]['slot_reply_text'] = SLOTS
        rebuilt = await shortlists.rebuild_client_handoff('REQ-TEST', 'T-TEST',
            shortlists.ApproveHandoffRequest(package_id=first['package_id']), db)
        assert rebuilt['package_id'] != first['package_id']
        with pytest.raises(HTTPException):
            await shortlists.approve_client_handoff('REQ-TEST', 'T-TEST',
                shortlists.ApproveHandoffRequest(package_id=first['package_id']), db)
        assert sum(path.endswith('/email/send') for path, _ in requests) == 1
    asyncio.run(run())
