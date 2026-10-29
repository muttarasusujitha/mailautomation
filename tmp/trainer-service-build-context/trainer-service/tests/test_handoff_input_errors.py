import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import HTTPException
from app import handoff


def test_lab_input_error_stops_retry_and_marks_needs_input(monkeypatch):
    package = {'_id': 'pkg', 'package_id': 'P1', 'status': 'approved',
               'requirement_id': 'R1', 'trainer_id': 'T1'}
    class Collection:
        def __init__(self): self.calls = []
        async def update_one(self, query, update):
            self.calls.append(update)
            return SimpleNamespace(modified_count=1)
    packages, shortlists = Collection(), Collection()
    db = {'client_handoff_packages': packages, 'shortlists': shortlists,
          'requirements': SimpleNamespace(find_one=AsyncMock(return_value={}))}
    monkeypatch.setattr(handoff, 'deliver_approved_package', handoff.deliver_approved_package)
    async def fail(db, package): raise HTTPException(422, detail={'message': 'missing fx_rate'})
    import app.routes.shortlists as shortlists_route
    monkeypatch.setattr(shortlists_route, '_deliver_client_handoff', fail)
    result = asyncio.run(handoff.deliver_approved_package(db, package))
    assert result['needs_input'] is True
    assert any(update.get('$set', {}).get('status') == 'needs_input' for update in packages.calls)
    assert any(update.get('$set', {}).get('top_trainers.$.slot_status') == 'client_handoff_needs_input' for update in shortlists.calls)


def test_background_worker_resumes_changed_inputs_without_new_email(monkeypatch):
    from shared.handoff_inputs import handoff_input_version
    from handoff_store import Cursor
    from app.routes import shortlists as routes
    requirement = {'fx_rate': None}
    trainer = {'trainer_id': 'T1', 'slot_status': 'client_handoff_needs_input',
               'slot_reply_text': 'saved slots',
               'client_handoff_input_version': handoff_input_version(requirement)}
    db = {'requirements': SimpleNamespace(find_one=AsyncMock(return_value=requirement)),
          'shortlists': SimpleNamespace(
              find=lambda query: Cursor([{'requirement_id': 'R1', 'top_trainers': [trainer]}]),
              update_one=AsyncMock())}
    send = AsyncMock(return_value={'success': True, 'email_id': 'E1'})
    monkeypatch.setattr(routes, 'send_client_slots', send)
    asyncio.run(handoff.retry_changed_input_handoffs(db))
    send.assert_not_awaited()
    requirement['fx_rate'] = 84
    asyncio.run(handoff.retry_changed_input_handoffs(db))
    send.assert_awaited_once()
    assert send.await_args.args[0].slot_text == 'saved slots'
    trainer['client_slots_sent'] = True
    asyncio.run(handoff.retry_changed_input_handoffs(db))
    assert send.await_count == 1
