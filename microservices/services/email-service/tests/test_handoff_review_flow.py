import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from app.routes import inbox
from shared.handoff_inputs import handoff_input_version


def database():
    trainer = {'trainer_id': 'TR-1', 'email': 'trainer@example.com', 'name': 'Trainer'}
    return {name: SimpleNamespace(find_one=AsyncMock(return_value=value),
                                 update_one=AsyncMock(), insert_one=AsyncMock())
            for name, value in (
                ('shortlists', {'top_trainers': [trainer]}),
                ('requirements', {'client_email': 'client@example.com', 'technology_needed': 'DevOps'}),
                ('email_logs', None), ('admin_settings', {}),
            )}


def test_missing_input_pauses_until_requirement_changes(monkeypatch):
    db = database()
    requirement = db['requirements'].find_one.return_value
    trainer = db['shortlists'].find_one.return_value['top_trainers'][0]
    trainer.update(slot_status='client_handoff_needs_input',
                   client_handoff_input_version=handoff_input_version(requirement))
    monkeypatch.setattr(inbox, '_latest_mail3_log', AsyncMock(return_value={}))
    monkeypatch.setattr(inbox, '_client_email_from_context', AsyncMock(return_value='client@example.com'))
    monkeypatch.setattr(inbox, '_load_admin_settings', AsyncMock(return_value={}))
    post = AsyncMock(return_value=httpx.Response(422,
        request=httpx.Request('POST', 'http://trainer/test'),
        json={'detail': {'missing_inputs': ['participant_count']}}))
    monkeypatch.setattr(inbox, '_post_with_local_fallback', post)
    reply = {'requirement_id': 'REQ-1', 'trainer_id': 'TR-1', 'from_email': 'trainer@example.com',
             'source_outbound_mail_type': 'mail1',
             'body': 'All times are IST: Nov 6, 2026 - 10 AM, 2:15 PM and 4.30 PM.'}
    paused = asyncio.run(inbox._handle_trainer_slot_reply(db, reply))
    assert paused['needs_input'] and not paused['attempted']
    post.assert_not_awaited()
    requirement['fx_rate'] = 84
    retried = asyncio.run(inbox._handle_trainer_slot_reply(db, reply))
    post.assert_awaited_once()
    assert retried['needs_input'] and not retried['retry_pending']
    db['email_logs'].insert_one.assert_not_awaited()
    updated = db['shortlists'].update_one.await_args.args[1]['$set']
    assert updated['top_trainers.$.client_handoff_input_version'] == handoff_input_version(requirement)
    assert updated['top_trainers.$.client_handoff_retry_after'] is None
    trainer['client_handoff_input_version'] = updated['top_trainers.$.client_handoff_input_version']
    requirement['participant_count'] = 35
    post.return_value = httpx.Response(200, request=httpx.Request('POST', 'http://trainer/test'),
                                     json={'success': True, 'email_id': 'EML-RECOVERED'})
    resumed = asyncio.run(inbox._handle_trainer_slot_reply(db, reply))
    assert resumed['success'] and not resumed['needs_input']
    assert post.await_count == 2


def test_three_inline_slots_prepare_package_without_recording_delivery(monkeypatch):
    db = database()
    monkeypatch.setattr(inbox, '_latest_mail3_log', AsyncMock(return_value={}))
    monkeypatch.setattr(inbox, '_client_email_from_context', AsyncMock(return_value='client@example.com'))
    monkeypatch.setattr(inbox, '_load_admin_settings', AsyncMock(return_value={}))
    requests = []

    async def post(client, url, **kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'success': False, 'pending_approval': True, 'package_id': 'PKG-1',
        })

    monkeypatch.setattr(inbox, '_post_with_local_fallback', post)
    result = asyncio.run(inbox._handle_trainer_slot_reply(db, {
        'requirement_id': 'REQ-1', 'trainer_id': 'TR-1', 'from_email': 'trainer@example.com',
        'source_outbound_mail_type': 'mail1',
        'body': 'All times are IST: Nov 6, 2026 - 10 AM, 2:15 PM and 4.30 PM.',
    }))
    assert result['pending_approval'] is True
    assert result['success'] is False
    assert not result.get('retry_pending')
    assert requests[0]['slot_text'].splitlines() == [
        '06 November 2026, 10:00 AM IST', '06 November 2026, 02:15 PM IST',
        '06 November 2026, 04:30 PM IST',
    ]
    db['email_logs'].insert_one.assert_not_awaited()
    db['shortlists'].update_one.assert_not_awaited()


def test_client_cannot_select_before_handoff_and_other_sender_cannot_select(monkeypatch):
    db = database()
    monkeypatch.setattr(inbox, '_client_email_from_context', AsyncMock(return_value='client@example.com'))
    create_event = AsyncMock()
    monkeypatch.setattr(inbox, 'create_google_meet_event', create_event)
    for sender, reason in [('stranger@example.com', 'sender_not_linked_client'),
                           ('client@example.com', 'client_handoff_not_delivered')]:
        result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
            'requirement_id': 'REQ-1', 'trainer_id': 'TR-1', 'from_email': sender,
            'source_outbound_mail_type': 'client_slots', 'subject': 'Re: Interview Slots - DevOps',
            'body': 'I select slot 2.',
        }))
        assert result['reason'] == reason
    create_event.assert_not_awaited()


def test_delivered_client_choice_invites_both_participants_at_offered_time(monkeypatch):
    db = database()
    slots = '06 November 2026, 10:00 AM IST\n06 November 2026, 02:15 PM IST\n06 November 2026, 04:30 PM IST'

    async def find_email(query, *args, **kwargs):
        if query.get('mail_type') == 'client_slots':
            return {'email_id': 'EML-HANDOFF', 'slot_text': slots, 'status': 'sent'}
        return None

    db['email_logs'].find_one.side_effect = find_email
    monkeypatch.setattr(inbox, '_client_email_from_context', AsyncMock(return_value='client@example.com'))
    monkeypatch.setattr(inbox, '_load_admin_settings', AsyncMock(return_value={}))
    create_event = AsyncMock(return_value={'success': True, 'event_id': 'CAL-TEST', 'meet_link': 'https://meet.google.com/test-only'})
    monkeypatch.setattr(inbox, 'create_google_meet_event', create_event)
    monkeypatch.setattr(inbox, '_client_pipeline_email_body', AsyncMock(return_value=('Test invitation', 'template')))
    trainer_mail = AsyncMock(return_value=(True, ''))
    client_mail = AsyncMock(return_value={'success': True, 'email_id': 'EML-CLIENT'})
    monkeypatch.setattr(inbox, '_send_verified_workflow_email', trainer_mail)
    monkeypatch.setattr(inbox, '_send_client_interview_schedule_email', client_mail)
    base = {'requirement_id': 'REQ-1', 'trainer_id': 'TR-1', 'from_email': 'client@example.com',
            'source_outbound_mail_type': 'client_slots', 'subject': 'Re: Interview Slots - DevOps'}
    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {**base, 'body': 'I select slot 2.'}))
    assert result['success'] is True
    args = create_event.await_args.kwargs
    assert args['attendees'] == ['trainer@example.com', 'client@example.com']
    assert args['start'].strftime('%Y-%m-%d %H:%M') == '2026-11-06 14:15'
    assert trainer_mail.await_args.kwargs['to'] == 'trainer@example.com'
    assert client_mail.await_args.kwargs['client_email'] == 'client@example.com'
    assert db['shortlists'].update_one.await_args.args[1]['$set']['top_trainers.$.pipeline_status'] == 'interview_scheduled'

    create_event.reset_mock()
    result = asyncio.run(inbox._handle_client_slot_confirmation_reply(db, {
        **base, 'body': 'I select 07 November 2026 at 10 AM IST.',
    }))
    assert result['reason'] == 'selected_slot_not_offered'
    create_event.assert_not_awaited()
