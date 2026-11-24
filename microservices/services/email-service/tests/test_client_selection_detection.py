import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.routes.inbox import _handle_client_selection_reply, _recover_client_slot_reply_context
import pytest


@pytest.mark.parametrize('body', ['He has been selected', 'Selected. Please proceed.', 'The trainer has been selected'])
def test_short_selection_decisions_are_recognised(body):
    result = asyncio.run(_handle_client_selection_reply({}, {'clean_body': body}))
    assert result['attempted'] is True
    assert result['reason'] == 'missing_requirement_or_trainer_link'


@pytest.mark.parametrize('body', ['He is not selected', 'Please check whether he is selected', 'We are still reviewing profiles'])
def test_old_selection_subject_does_not_select_trainer(body):
    result = asyncio.run(_handle_client_selection_reply({}, {'subject': 'Re: Trainer selected', 'clean_body': body}))
    assert result == {'attempted': False}


def test_client_selection_reply_recognises_selectedslove_typo():
    result = asyncio.run(_handle_client_selection_reply({}, {
        "subject": "Re: Interview Starts in 10 Minutes - Training",
        "clean_body": "he is selectedslove",
    }))

    # It is a recognised selection reply.  The missing links are reported
    # separately, rather than allowing it to take the standard reply path.
    assert result == {
        "attempted": True,
        "success": False,
        "reason": "missing_requirement_or_trainer_link",
    }


def test_client_selection_reply_resolves_trainer_from_interview_reminder_name():
    shortlist = SimpleNamespace(find_one=AsyncMock(return_value={"top_trainers": [
        {"trainer_id": "TR-1", "name": "Pooja Thomas"},
    ]}), update_one=AsyncMock())
    email_logs = SimpleNamespace(find_one=AsyncMock(return_value=None), insert_one=AsyncMock())
    requirements = SimpleNamespace(update_one=AsyncMock())
    result = asyncio.run(_handle_client_selection_reply({
        "shortlists": shortlist,
        "email_logs": email_logs,
        "requirements": requirements,
    }, {
        "clean_body": "he is selected",
        "requirement_id": "REQ-1",
        "trainer_name": "Pooja Thomas",
    }))

    assert result["reason"] == "client_selection_workflow_incomplete"
    assert requirements.update_one.await_args.args[1]["$set"]["selected_trainer_id"] == "TR-1"
    assert shortlist.find_one.await_args_list[0].args[0] == {"requirement_id": "REQ-1"}
    assert shortlist.update_one.await_args.args[0] == {
        "requirement_id": "REQ-1", "top_trainers.trainer_id": "TR-1",
    }


def test_headerless_client_selection_recovers_handoff_context():
    outbound = SimpleNamespace(find_one=AsyncMock(return_value={
        "email_id": "EML-HANDOFF", "requirement_id": "REQ-1",
        "trainer_id": "TR-1", "trainer_name": "Pooja Thomas",
    }), update_one=AsyncMock())
    client_emails = SimpleNamespace(update_one=AsyncMock())
    result = asyncio.run(_recover_client_slot_reply_context({
        "email_logs": outbound,
        "client_emails": client_emails,
    }, {
        "email_id": "EML-INBOUND", "from_email": "client@example.com",
        "clean_body": "The client said he is selected. Please proceed.",
    }))

    assert result["requirement_id"] == "REQ-1"
    assert result["trainer_id"] == "TR-1"
    assert result["source_outbound_mail_type"] == "client_slots"
    assert client_emails.update_one.await_count == 1
    assert outbound.update_one.await_count == 1
