import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.tasks import reminders, interview_reminders


@pytest.mark.parametrize('second', [False, True])
@pytest.mark.parametrize('success', [False, True])
def test_followup_requires_confirmed_delivery_and_has_stable_key(monkeypatch, second, success):
    class Collection:
        def find(self, query):
            assert query['replied'] == {'$ne': True}
            return self
        def limit(self, count):
            return self
        async def __aiter__(self):
            yield {'email_id': 'E1', 'recipient': 'trainer@example.com'}
        async def find_one_and_update(self, query, update):
            assert query['replied'] == {'$ne': True}
            assert query['status'] == 'sent'
            return {'email_id': 'E1'}
        update_one = AsyncMock()
    collection = Collection()
    monkeypatch.setattr(reminders, 'get_db', lambda: {'email_logs': collection})
    monkeypatch.setattr(reminders, '_followup_automation_enabled', AsyncMock(return_value=True))
    monkeypatch.setattr(reminders, '_gmail_quota_cooldown_active', AsyncMock(return_value={}))
    def post(url, **kwargs):
        if '/templates/' in url:
            return httpx.Response(200, json={'body': 'Follow up'}, request=httpx.Request('POST', url))
        assert kwargs['json']['idempotency_key'] == f"followup-{2 if second else 1}:E1"
        return httpx.Response(200, json={'success': success})
    monkeypatch.setattr(reminders.httpx, 'post', post)
    result = asyncio.run((reminders._do_followup2_reminders if second else reminders._do_followup_reminders)())
    assert result['sent'] == int(success)
    assert result['failed'] == int(not success)


def test_concurrent_meeting_reminder_workers_send_once(monkeypatch):
    class Collection:
        claimed = False
        def find(self, query):
            return self
        async def to_list(self, count):
            return [{'email_id': 'E1', 'trainer_phone': '123', 'interview_at': datetime.utcnow()}]
        async def find_one_and_update(self, query, update):
            await asyncio.sleep(0)
            if self.claimed:
                return None
            self.claimed = True
            return {'email_id': 'E1'}
        update_one = AsyncMock()
    monkeypatch.setattr(interview_reminders, 'get_db', lambda: {'email_logs': collection})
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={'success': True})
    monkeypatch.setattr(interview_reminders.httpx, 'post', post)
    collection = Collection()
    async def run():
        await asyncio.gather(*[interview_reminders._fetch_and_send_reminders() for _ in range(10)])
    asyncio.run(run())
    assert len(calls) == 1


def test_second_followup_stops_on_original_reply(monkeypatch):
    class Collection:
        def find(self, query):
            return self
        def limit(self, count):
            return self
        async def __aiter__(self):
            yield {'email_id': 'F1', 'requirement_id': 'R1', 'recipient': 'trainer@example.com'}
        find_one = AsyncMock(return_value={'_id': 'original'})
        find_one_and_update = AsyncMock()
    collection = Collection()
    monkeypatch.setattr(reminders, 'get_db', lambda: {'email_logs': collection})
    monkeypatch.setattr(reminders, '_followup_automation_enabled', AsyncMock(return_value=True))
    monkeypatch.setattr(reminders, '_gmail_quota_cooldown_active', AsyncMock(return_value={}))
    result = asyncio.run(reminders._do_followup2_reminders())
    assert result == {'sent': 0, 'failed': 0}
    collection.find_one_and_update.assert_not_awaited()
