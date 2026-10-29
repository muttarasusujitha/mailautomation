import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from app.routes import shortlists
from handoff_store import PackageStore


SLOTS = "01 November 2026, 10:00 AM IST\n03 November 2026, 2:00 PM IST\n05 November 2026, 4:00 PM IST"


def test_ai_handoff_passes_ai_resource_mapping_to_workbook(monkeypatch):
    import openai
    from shared import lab_planning
    db, requests = prepare(monkeypatch)
    db['automation_settings'].find_one.return_value = {'value': 'ai'}
    class Planner:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: Planner(), raising=False)
    mapping = [{'vm_qty': 1, 'vm_profile': 'Light', 'active_days': 1,
                'k8s_control_plane': 0, 'k8s_worker_nodes': 0, 'managed_db': 0, 'object_storage_gb': 0}]
    plan = AsyncMock(return_value=mapping)
    monkeypatch.setattr(lab_planning, 'plan_resources', plan)
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    plan.assert_awaited_once()
    assert plan.call_args.args[0] == 'ai'
    lab_payload = next(body for path, body in requests if path.endswith('/lab-cost'))
    assert lab_payload['assumptions']['lab_day_mapping'] == mapping


def test_template_handoff_preserves_cloud_resources_and_uses_saved_catalog(monkeypatch):
    db, requests = prepare(monkeypatch)
    monkeypatch.setattr(shortlists, '_build_toc', AsyncMock(return_value={
        'title': 'DevOps', 'days': [{'day': 1, 'topic': 'Docker AWS EKS S3 lab'}]}))
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    assumptions = next(body for path, body in requests if path.endswith('/lab-cost'))['assumptions']
    day = assumptions['lab_day_mapping'][0]
    assert day['vm_qty'] == 1
    assert day['k8s_control_plane'] == 1
    assert day['object_storage_gb'] == 10
    assert assumptions['pricing_selections'] == {}


def prepare(monkeypatch, failure=None, requirement_overrides=None):
    trainer = {"trainer_id": "T-TEST", "name": "Test Trainer", "email": "trainer@example.com"}
    req = {
        "client_email": "client@example.com", "technology_needed": "DevOps",
        "batch_flow": "proposal", "lab_cost_requested": True,
        "participant_count": 1, "lab_hours_per_day": 3,
        "cloud_provider": "aws", "cloud_region": "ap-south-1", "fx_rate": 84,
    }
    req.update(requirement_overrides or {})
    db = {
        name: SimpleNamespace(find_one=AsyncMock(return_value=value), update_one=AsyncMock())
        for name, value in (("requirements", req), ("shortlists", {"top_trainers": [trainer]}),
                            ("email_logs", None), ("resume_uploads", None), ("admin_settings", None), ("automation_settings", None))
    }
    db['client_handoff_packages'] = PackageStore()
    monkeypatch.setattr(shortlists, "_generate_trainer_profile_pdf", AsyncMock(return_value=None if failure == "profile" else b"profile"))
    monkeypatch.setattr(shortlists, "_build_toc", AsyncMock(return_value={"title": "DevOps", "days": [{"day": 1}]}))
    requests = []

    def handle(request):
        requests.append((request.url.path, json.loads(request.content)))
        if "/documents/" in request.url.path:
            is_lab = request.url.path.endswith("/lab-cost")
            fails = (failure == "lab" and is_lab or failure == "toc" and not is_lab
                     or failure == "combine" and request.url.path.endswith('/combine'))
            return httpx.Response(
                502 if fails else 200,
                content=b"workbook",
                headers={"X-Lab-Cost-Pricing-Status": "provider_api_verified_public_retail"} if is_lab and not fails else {},
            )
        return httpx.Response(200, json={"success": True, "email_id": "EML-TEST"})

    original = httpx.AsyncClient
    monkeypatch.setattr(shortlists.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))

    async def post(client, url, **kwargs):
        return await client.post(url, **kwargs)

    monkeypatch.setattr(shortlists, "_post_with_local_fallback", post)
    return db, requests


def test_client_gets_profile_toc_lab_and_three_slots(monkeypatch):
    db, requests = prepare(monkeypatch)
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["slots_count"] == 3
    assert result['success'] is True
    assert result['pending_approval'] is False
    mail = requests[-1][1]
    assert requests[-1][0].endswith("/email/send")
    assert len(mail["attachments"]) == 3
    assert [a["filename"] for a in mail["attachments"]] == [
        "Test Trainer - Client Aligned Profile.pdf", "DevOps - Training ToC.xlsx", "DevOps - Lab Cost Estimate.xlsx",
    ]
    assert mail["ai_context"]["available_slots"] == SLOTS
    assert mail["ai_context"]["lab_cost_attached"] is True
    assert mail["ai_context"]["lab_hours_per_day"] == 3
    assert mail["ai_context"]["participant_count"] == 1
    assert mail["ai_context"]["lab_defaults_used"] is False
    assert "3 lab-access hours per day for 1 participant" in mail["body"]
    assert "confirmed inputs change" in mail["body"]
    assert mail["idempotency_key"].startswith("client-handoff:")
    assert db["shortlists"].update_one.await_count == 1


@pytest.mark.parametrize("failure", ["profile", "toc", "lab"])
def test_missing_required_document_prevents_send_and_completion(monkeypatch, failure):
    db, requests = prepare(monkeypatch, failure)
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
        ), db))
    assert error.value.status_code == 502
    assert not any(path.endswith("/email/send") for path, _ in requests)
    db["shortlists"].update_one.assert_not_awaited()


def test_incomplete_slots_prevent_handoff(monkeypatch):
    db, requests = prepare(monkeypatch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS.splitlines()[0],
        ), db))
    assert error.value.status_code == 400
    assert requests == []


def test_existing_sent_handoff_repairs_shortlist_without_resending(monkeypatch):
    db, requests = prepare(monkeypatch)
    db['email_logs'].find_one.return_value = {
        'email_id': 'EML-OLD', 'sent_at': '2026-09-08T04:11:00Z', 'slot_text': SLOTS,
    }
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    assert result['already_sent'] is True
    assert result['email_id'] == 'EML-OLD'
    assert requests == []
    update = db['shortlists'].update_one.await_args.args[1]['$set']
    assert update['top_trainers.$.client_slots_sent'] is True
    assert update['top_trainers.$.client_slots_email_id'] == 'EML-OLD'
    assert update['top_trainers.$.slot_status'] == 'sent_to_client'


@pytest.mark.parametrize('lab_hours,expected', [(5, 5), (8, 8)])
def test_lab_hours_use_confirmed_lab_input(monkeypatch, lab_hours, expected):
    db, requests = prepare(monkeypatch, requirement_overrides={
        'hours_per_day': 8, 'lab_hours_per_day': lab_hours,
    })
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    lab_request = next(body for path, body in requests if path.endswith('/lab-cost'))
    assert lab_request['assumptions']['hours_per_day'] == expected


@pytest.mark.parametrize("batch", ["confirmed", "proposal"])
@pytest.mark.parametrize("missing", ["cloud_provider", "cloud_region", "fx_rate"])
def test_missing_system_input_is_resolved_automatically(monkeypatch, missing, batch):
    db, requests = prepare(monkeypatch, requirement_overrides={missing: None, 'batch_flow': batch})
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    lab = next(body for path, body in requests if path.endswith('/lab-cost'))['assumptions']
    assert lab['cloud_provider'] == 'aws'
    assert lab['cloud_region'] == 'Mumbai'
    assert 'fx_rate' not in lab


def test_missing_usage_uses_approved_one_person_three_hour_baseline(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "participant_count": None, "participants": None, "lab_hours_per_day": None,
    })
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    lab_request = next(body for path, body in requests if path.endswith('/lab-cost'))
    assert lab_request['assumptions']['hours_per_day'] == 3
    assert lab_request['assumptions']['participant_count'] == 1


def test_aws_and_azure_produce_one_client_attachment(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={'cloud_provider': 'aws azure'})
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    merge = next(body for path, body in requests if path.endswith('/combine'))
    assert [item['provider'] for item in merge['estimates']] == ['aws', 'azure']
    mail = next(body for path, body in requests if path.endswith('/email/send'))
    assert len([a for a in mail['attachments'] if 'Lab Cost' in a['filename']]) == 1


def test_single_cloud_uses_the_client_first_workbook_without_flattening(monkeypatch):
    db, requests = prepare(monkeypatch)
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    assert not any(path.endswith('/combine') for path, _ in requests)


def test_unverified_lab_workbook_blocks_package(monkeypatch):
    db, requests = prepare(monkeypatch)
    original = httpx.AsyncClient

    def handle(request):
        if request.url.path.endswith("/lab-cost"):
            return httpx.Response(200, content=b"workbook")
        return httpx.Response(200, content=b"workbook")

    monkeypatch.setattr(shortlists.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
        ), db))
    assert error.value.status_code == 502
    assert not any(path.endswith("/email/send") for path, _ in requests)


def test_supplied_lab_inputs_are_used_and_disclosed(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        'lab_hours_per_day': 8, 'participant_count': 25,
    })
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    mail = next(iter(db['client_handoff_packages'].docs.values()))['email_payload']
    assert mail['ai_context']['lab_hours_per_day'] == 8
    assert mail['ai_context']['participant_count'] == 25
    assert mail['ai_context']['lab_defaults_used'] is False
    assert "8 lab-access hours per day for 25 participants" in mail['body']


@pytest.mark.parametrize('count', [1.5, '2.5', True, -1])
def test_invalid_participant_count_never_reaches_lab_export(monkeypatch, count):
    db, requests = prepare(monkeypatch, requirement_overrides={'participant_count': count})
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
        ), db))
    assert error.value.status_code == 422
    assert not any(path.endswith('/lab-cost') or path.endswith('/email/send') for path, _ in requests)
