import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from app.routes import shortlists
from handoff_store import PackageStore


def _future_slot_text():
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    return "\n".join(
        f"{(today + timedelta(days=day)).strftime('%d %B %Y')}, {hour:02d}:00 {period} IST"
        for day, hour, period in ((3, 10, "AM"), (4, 2, "PM"), (5, 4, "PM"))
    )


SLOTS = _future_slot_text()


def test_requested_evidence_needs_the_named_holder_and_document_type():
    from shared.trainer_documents import requested_documents
    req = {"client_requirement_text": "Please share the experience letter and graduation certificate."}
    assert requested_documents(req) == ["Experience letter", "Graduation certificate"]
    attachment = {"filename": "letter.pdf", "original_file": b"%PDF-1.5 example",
                  "analysis": {"extracted_text": "Experience letter\nEmployee name: Test Trainer"}}
    check = shortlists._requested_evidence_attachment
    assert check(attachment, "Experience letter", "Test Trainer")
    assert not check(attachment, "Experience letter", "Other Trainer")
    assert not check(attachment, "Graduation certificate", "Test Trainer")
    attachment["analysis"] = {}
    assert not check(attachment, "Experience letter", "Test Trainer")


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
        "training_dates": "2027-01-15 to 2027-01-16",
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
                headers={"X-Lab-Cost-Pricing-Status": "provider_api_verified_public_retail",
                         "X-Lab-Cost-Quote-Valid-Until": (datetime.now(timezone.utc) + timedelta(days=-1 if failure == "expired" else 7)).isoformat()} if is_lab and not fails else {},
            )
        return httpx.Response(200, json={"success": True, "email_id": "EML-TEST"})

    original = httpx.AsyncClient
    monkeypatch.setattr(shortlists.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))

    async def post(client, url, **kwargs):
        return await client.post(url, **kwargs)

    monkeypatch.setattr(shortlists, "_post_with_local_fallback", post)
    return db, requests


def test_proposal_handoff_with_unspecified_duration_dates_and_headcount(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "training_dates": "", "duration_days": None, "participant_count": None, "lab_hours_per_day": None,
    })
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"]
    assert shortlists._build_toc.await_args.args[0]["duration_days"] == 1
    assert db["requirements"].find_one.return_value["duration_days"] is None
    lab = next(body["assumptions"] for path, body in requests if path.endswith("/lab-cost"))
    assert (lab["participant_count"], lab["hours_per_day"]) == (1, 3)
    assert "provisional one-day scope" in requests[-1][1]["body"]


def test_issuer_check_holds_cached_package_before_email_delivery(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "client_requirement_text": "Please verify the authenticity of the trainer's degree.",
    })
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["needs_input"]
    assert not any(path.endswith("/email/send") for path, _ in requests)


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
    assert "participant count or lab hours change" in mail["body"]
    assert mail["idempotency_key"].startswith("client-handoff:")
    assert db["shortlists"].update_one.await_count == 1


def test_ai_mode_personalizes_client_handoff_from_explicit_context(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        'client_company': 'Northstar Health',
        'client_industry': 'Healthcare',
        'client_business_context': 'Modernize secure cloud deployment for clinical analytics.',
        'client_requirement_text': 'DevOps and AWS training for clinical analytics teams.',
        'required_skills': ['DevOps', 'AWS'],
    })
    db['automation_settings'].find_one.return_value = {'value': 'ai'}
    monkeypatch.setattr(shortlists, '_build_toc', AsyncMock(return_value={
        'title': 'DevOps and AWS', 'days': [{'day': 1}],
        'generation_mode': 'ai', 'requested_generation_mode': 'ai',
    }))
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id='REQ-TEST', trainer_id='T-TEST', slot_text=SLOTS,
    ), db))
    mail = next(body for path, body in requests if path.endswith('/email/send'))
    assert mail['ai_generate'] is True
    assert mail['ai_context']['client_company'] == 'Northstar Health'
    assert mail['ai_context']['client_industry'] == 'Healthcare'
    assert 'clinical analytics' in mail['ai_context']['client_business_context']
    assert 'AWS' in mail['ai_context']['requested_topics']
    assert 'Do not claim unverified company systems' in mail['ai_context']['personalization_rule']


def test_handoff_always_includes_lab_workbook_without_explicit_request(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "lab_cost_requested": False,
        "explicit_lab_cost_requested": False,
    })
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"] is True
    mail = next(body for path, body in requests if path.endswith("/email/send"))
    assert mail["ai_generate"] is False
    assert [item["filename"] for item in mail["attachments"]] == [
        "Test Trainer - Client Aligned Profile.pdf",
        "DevOps - Training ToC.xlsx",
        "DevOps - Lab Cost Estimate.xlsx",
    ]


def test_explicit_lab_cost_request_blocks_handoff_without_workbook(monkeypatch):
    db, requests = prepare(monkeypatch, failure="lab", requirement_overrides={
        "explicit_lab_cost_requested": True,
        "client_requirement_text": "Please share the lab cost estimate.",
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
        ), db))
    assert error.value.status_code == 502
    assert not any(path.endswith("/email/send") for path, _ in requests)
    db["shortlists"].update_one.assert_not_awaited()


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


def test_broader_lab_mention_does_not_attach_or_block_workbook(monkeypatch):
    db, requests = prepare(monkeypatch, failure="lab", requirement_overrides={
        "lab_cost_requested": True,
        "client_requirement_text": "Please arrange lab tools, setup, access, and a local or cloud lab.",
        "requirement_items": [{"category": "lab_requirements"}, {"category": "lab_delivery_preference"}],
    })
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"] is True
    mail = requests[-1][1]
    assert not any(path.endswith("/lab-cost") for path, _ in requests)
    assert all("Lab Cost" not in item["filename"] for item in mail["attachments"])
    assert mail["ai_generate"] is False
    assert "Available slots:" in mail["body"]


def test_confirmed_handoff_uses_toc_for_lab_cost_and_does_not_attach_it(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "batch_flow": "confirmed",
        "lab_cost_requested": False,
        "client_requirement_text": "Please arrange lab tools, setup, access, and a local or cloud lab.",
        "availability": "Available on the stated dates",
    })
    db["shortlists"].find_one.return_value = {
        "top_trainers": [{
            "trainer_id": "T-TEST", "name": "Test Trainer", "email": "trainer@example.com",
            "availability": "Available 01-20 November 2026",
        }],
    }
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"] is True
    mail = requests[-1][1]
    names = [item["filename"] for item in mail["attachments"]]
    assert names == [
        "Test Trainer - Client Aligned Profile.pdf",
        "DevOps - Lab Cost Estimate.xlsx",
    ]
    assert any(path.endswith("/lab-cost") for path, _ in requests)
    assert not any(path.endswith("/excel/toc") for path, _ in requests)
    assert "ToC is attached" not in mail["body"]
    assert "Training ToC" not in " ".join(names)
    assert "The lab-cost estimate is attached." in mail["body"]
    assert "Trainer availability:" in mail["body"]
    assert "Available slots:" in mail["body"]
    assert mail["ai_context"]["toc_attached"] is False
    assert mail["ai_context"]["lab_cost_attached"] is True
    assert mail["ai_context"]["lab_cost_unavailable"] is False
    assert mail["ai_generate"] is False


def test_confirmed_handoff_still_sends_when_lab_workbook_cannot_be_built(monkeypatch):
    db, requests = prepare(monkeypatch, failure="lab", requirement_overrides={
        "batch_flow": "confirmed",
        "lab_cost_requested": False,
    })
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"] is True
    mail = requests[-1][1]
    assert [item["filename"] for item in mail["attachments"]] == [
        "Test Trainer - Client Aligned Profile.pdf",
    ]
    assert mail["ai_context"]["lab_cost_unavailable"] is True
    assert mail["ai_context"]["lab_cost_attached"] is False
    assert mail["ai_context"]["toc_attached"] is False
    assert "Available slots:" in mail["body"]
    assert "lab-cost estimate is attached" not in mail["body"]
    assert db["shortlists"].update_one.await_count == 1


def test_ai_on_rewrites_client_handoff(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={"lab_cost_requested": False})
    db["automation_settings"].find_one.return_value = {"value": "ai"}
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    mail = requests[-1][1]
    assert mail["ai_generate"] is True
    assert mail["ai_context"]["workflow"] == "client_handoff"
    assert "Available slots:" in mail["body"]


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


def test_partial_topics_still_cost_the_lab_from_the_approved_baseline(monkeypatch):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "batch_flow": "confirmed",
        "participant_count": None,
        "participants": None,
        "cloud_provider": None,
        "cloud_region": None,
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
        "requested_details": ["CV", "ToC", "lab cost"],
        "explicit_lab_cost_requested": True,
    })
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    lab_request = next(body for path, body in requests if path.endswith("/lab-cost"))
    assert lab_request["assumptions"]["participant_count"] == 1
    assert lab_request["assumptions"]["hours_per_day"] == 3
    assert lab_request["assumptions"]["cloud_provider"] == "aws"
    assert lab_request["assumptions"]["cloud_region"] == "Mumbai"
    mail = next(body for path, body in requests if path.endswith("/email/send"))
    assert "DevOps - Lab Cost Estimate.xlsx" in [item["filename"] for item in mail["attachments"]]
    assert "DevOps - Training ToC.xlsx" in [item["filename"] for item in mail["attachments"]]


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


def test_client_handoff_adds_the_course_outline_pdf_after_the_workbook(monkeypatch):
    db, requests = prepare(monkeypatch)
    monkeypatch.setattr(shortlists, "_generate_toc_pdf", AsyncMock(return_value=b"%PDF-1.7 outline"))
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    mail = next(body for path, body in requests if path.endswith("/email/send"))
    assert [a["filename"] for a in mail["attachments"]] == [
        "Test Trainer - Client Aligned Profile.pdf", "DevOps - Training ToC.xlsx",
        "DevOps - Course Outline.pdf", "DevOps - Lab Cost Estimate.xlsx",
    ]
    assert mail["attachments"][2]["subtype"] == "pdf"


def test_client_handoff_still_sends_when_the_course_outline_pdf_fails(monkeypatch):
    db, requests = prepare(monkeypatch)
    monkeypatch.setattr(shortlists, "_generate_toc_pdf", AsyncMock(side_effect=RuntimeError("renderer down")))
    result = asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS,
    ), db))
    assert result["success"] is True
    mail = next(body for path, body in requests if path.endswith("/email/send"))
    assert "DevOps - Course Outline.pdf" not in [a["filename"] for a in mail["attachments"]]


@pytest.mark.parametrize("headcount,expected_days,expected_hours", [(None, 1, 3), (12, 2, 4)])
def test_confirmed_agenda_and_lab_scope(monkeypatch, headcount, expected_days, expected_hours):
    db, requests = prepare(monkeypatch, requirement_overrides={
        "duration_days": 2, "participant_count": headcount, "lab_hours_per_day": None})
    agenda = {"excel_layout": "course_workbook", "hours_per_day": 7,
              "days": [{"day": 1, "topic": "Shell"}, {"day": 2, "topic": "Networking"}]}
    monkeypatch.setattr(shortlists, "_build_toc", AsyncMock(return_value=agenda))
    asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
        requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS), db))
    lab = next(body for path, body in requests if path.endswith("/lab-cost"))
    outline = next(body for path, body in requests if path.endswith("/excel/toc"))
    assert outline["toc"] == agenda
    assert [day["topic"] for day in lab["toc"]["days"]] == ["Shell", "Networking"][:expected_days]
    assert lab["assumptions"]["hours_per_day"] == expected_hours
    assert lab["assumptions"]["sample_quote"] == (headcount is None)


def test_expired_quote_blocks_handoff(monkeypatch):
    db, requests = prepare(monkeypatch, failure="expired")
    with pytest.raises(HTTPException):
        asyncio.run(shortlists.send_client_slots(shortlists.SendClientSlotsRequest(
            requirement_id="REQ-TEST", trainer_id="T-TEST", slot_text=SLOTS), db))
    assert all(not path.endswith("/email/send") for path, _ in requests)
