import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.routes import shortlists


def setup_delivery(monkeypatch, requirement, document_status=200, toc=None, existing=None):
    trainer = {"trainer_id": "T-TEST", "name": "Test Trainer", "email": "trainer@example.com"}
    shortlist = {"top_trainers": [trainer]}
    db = {
        name: SimpleNamespace(find_one=AsyncMock(return_value=value), update_one=AsyncMock())
        for name, value in (("shortlists", shortlist), ("requirements", requirement), ("email_logs", existing))
    }
    monkeypatch.setattr(shortlists, "_sync_shortlist_with_trainers", AsyncMock(return_value=shortlist))
    monkeypatch.setattr(shortlists, "_ai_trainer_mail1", AsyncMock(return_value=None))
    monkeypatch.setattr(shortlists.asyncio, "sleep", AsyncMock())
    generate = AsyncMock(return_value=toc)
    monkeypatch.setattr(shortlists, "_build_toc", generate)
    calls = []

    async def post(client, url, **kwargs):
        calls.append((url, kwargs["json"]))
        if "/documents/" in url:
            return httpx.Response(document_status, content=b"test-workbook")
        return httpx.Response(200, json={"email_id": "EML-TEST"})

    monkeypatch.setattr(shortlists, "_post_with_local_fallback", post)
    result = asyncio.run(shortlists.send_shortlist_mail(
        shortlists.SendMailRequest(requirement_id="REQ-TEST"), db,
    ))
    return result, calls, generate


def requirement(**overrides):
    return {
        "batch_flow": "proposal", "toc_action": "generate_by_clahan",
        "technology_needed": "DevOps including AWS and Azure", "duration_days": 15,
        "training_dates": "November 1, 2026 to November 15, 2026", "mode": "Online",
        **overrides,
    }


@pytest.mark.parametrize("nested", [False, True])
def test_proposal_generation_instruction_attaches_toc_in_first_mail(monkeypatch, nested):
    req = requirement()
    if nested:
        req["extracted"] = {"toc_action": req.pop("toc_action")}
    result, calls, generate = setup_delivery(monkeypatch, req, toc={"title": "DevOps"})
    assert result["sent"] == 1
    generate.assert_awaited_once()
    assert "/documents/excel/toc" in calls[0][0]
    mail = calls[1][1]
    assert base64.b64decode(mail["attachments"][0]["content_base64"]) == b"test-workbook"
    assert "proposed ToC/course agenda is attached" in mail["body"]
    assert mail["attachments"][0]["filename"].endswith(" - Proposed TOC.xlsx")


@pytest.mark.parametrize("toc,status", [(None, 200), ({"title": "DevOps"}, 500)])
def test_missing_toc_blocks_email_delivery(monkeypatch, toc, status):
    result, calls, _ = setup_delivery(monkeypatch, requirement(), document_status=status, toc=toc)
    assert result["sent"] == 0
    assert result["failed"] == 1
    assert not any("/email/send" in url for url, _ in calls)


@pytest.mark.parametrize("flow", [
    {"batch_flow": "confirmed"},
    {"batch_flow": "proposal", "pipeline_target": "shortlist1"},
])
def test_confirmed_batch_still_generates_without_action(monkeypatch, flow):
    result, calls, generate = setup_delivery(
        monkeypatch, requirement(**flow, toc_action=""), toc={"title": "DevOps"},
    )
    assert result["sent"] == 1
    generate.assert_awaited_once()
    assert calls[-1][1]["attachments"]
    mail = calls[-1][1]
    assert mail["attachments"][0]["filename"].endswith(" - Confirmed Batch TOC.xlsx")
    assert "for the confirmed batch is attached" in mail["body"]
    assert "proposed ToC/course agenda is attached" not in mail["body"]


def test_proposal_without_generation_instruction_still_attaches_generated_toc(monkeypatch):
    result, calls, generate = setup_delivery(monkeypatch, requirement(toc_action=""), toc={"title": "DevOps"})
    assert result["sent"] == 1
    generate.assert_awaited_once()
    assert calls[-1][1]["attachments"]
    assert calls[-1][1]["attachments"][0]["filename"].endswith(" - Proposed TOC.xlsx")


def test_existing_client_toc_is_forwarded_without_regeneration(monkeypatch):
    req = requirement(source_attachments=[{
        "filename": "Client TOC.xlsx", "safe_client_scope": True,
        "content_base64": base64.b64encode(b"client-workbook").decode(), "size_bytes": 15,
    }])
    result, calls, generate = setup_delivery(monkeypatch, req)
    assert result["sent"] == 1
    generate.assert_not_awaited()
    assert calls[-1][1]["attachments"][0]["filename"] == "Client TOC.xlsx"


def test_ai_off_confirmed_mail1_keeps_the_client_commercial_body(monkeypatch):
    req = requirement(batch_flow="confirmed", budget_total=130000, toc_action="")
    result, calls, _ = setup_delivery(monkeypatch, req, toc={"title": "DevOps"})
    assert result["sent"] == 1
    mail = calls[-1][1]
    assert mail["ai_generate"] is False
    assert mail["ai_context"]["generation"] == "confirmed_body"
    assert "Client commercial: INR 130,000 total-course commercial" in mail["body"]
    assert "Offered trainer commercial" not in mail["body"]
    assert "70%" not in mail["body"]
    assert "[Your available date 1]" in mail["body"]
    assert "[Your available date 3]" in mail["body"]
    assert "These are not the client's dates" in mail["body"]
    assert "01 November 2026" not in mail["body"]
    assert "Please confirm the offered commercials" not in mail["body"]


def test_ai_on_generates_confirmed_mail1(monkeypatch):
    generated = AsyncMock(return_value={
        "subject": "Confirmed DevOps requirement",
        "body": "Hi Test Trainer,\n\nClient commercial: INR 130,000 total-course commercial\n\nRegards,\nClahan Technologies",
    })
    req = requirement(batch_flow="confirmed", budget_total=130000, toc_action="")
    trainer = {"trainer_id": "T-TEST", "name": "Test Trainer", "email": "trainer@example.com"}
    db = {
        name: SimpleNamespace(find_one=AsyncMock(return_value=value), update_one=AsyncMock())
        for name, value in (
            ("shortlists", {"top_trainers": [trainer]}),
            ("requirements", req),
            ("email_logs", None),
            ("automation_settings", {"value": "ai"}),
        )
    }
    monkeypatch.setattr(shortlists, "_sync_shortlist_with_trainers", AsyncMock(return_value={"top_trainers": [trainer]}))
    monkeypatch.setattr(shortlists, "_ai_trainer_mail1", generated)
    monkeypatch.setattr(shortlists.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(shortlists, "_build_toc", AsyncMock(return_value={"title": "DevOps"}))
    calls = []

    async def post(client, url, **kwargs):
        calls.append((url, kwargs["json"]))
        if "/documents/" in url:
            return httpx.Response(200, content=b"test-workbook")
        return httpx.Response(200, json={"email_id": "EML-TEST"})

    monkeypatch.setattr(shortlists, "_post_with_local_fallback", post)
    result = asyncio.run(shortlists.send_shortlist_mail(shortlists.SendMailRequest(requirement_id="REQ-TEST"), db))
    assert result["sent"] == 1
    generated.assert_awaited()
    mail = calls[-1][1]
    assert mail["ai_context"]["generation"] == "ai"
    assert mail["ai_generate"] is False
    assert "Client commercial: INR 130,000 total-course commercial" in mail["body"]
    assert "Offered trainer commercial" not in mail["body"]


def test_ai_on_sets_followup_generation_and_ai_off_keeps_the_body(monkeypatch):
    trainer = {
        "trainer_id": "T-TEST", "name": "Test Trainer", "email": "trainer@example.com",
        "pipeline_status": "mail1_replied",
    }
    req = {
        "batch_flow": "confirmed",
        "technology_needed": "DevOps",
        "client_requirement_text": "Please share the trainer profile and availability.",
        "budget_total": 130000,
    }

    def send(mode):
        db = {
            "shortlists": SimpleNamespace(find_one=AsyncMock(return_value={"top_trainers": [trainer]}), update_one=AsyncMock()),
            "requirements": SimpleNamespace(find_one=AsyncMock(return_value=req), update_one=AsyncMock()),
            "email_logs": SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock()),
            "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": mode})),
        }
        calls = []

        async def post(client, url, **kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(200, json={"email_id": "EML-TEST"})

        monkeypatch.setattr(shortlists, "_sync_shortlist_with_trainers", AsyncMock(return_value={"top_trainers": [trainer]}))
        monkeypatch.setattr(shortlists.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(shortlists, "_post_with_local_fallback", post)
        result = asyncio.run(shortlists.send_shortlist_mail(shortlists.SendMailRequest(
            requirement_id="REQ-TEST", mail_type="mail2_followup", trainer_id="T-TEST",
        ), db))
        assert result["sent"] == 1
        return calls[-1]

    off = send("template")
    assert off["ai_generate"] is False
    assert "please share only the following outstanding item" in off["body"].lower()
    assert "Offered trainer commercial" not in off["body"]
    assert "70%" not in off["body"]
    on = send("ai")
    assert on["ai_generate"] is True
    assert on["ai_context"]["stage"] == "mail2_followup"
    assert "please share only the following outstanding item" in on["body"].lower()


def test_already_sent_mail_is_not_resent(monkeypatch):
    result, calls, generate = setup_delivery(monkeypatch, requirement(), existing={"email_id": "OLD"})
    assert result["sent"] == 0
    assert result["results"][0]["status"] == "skipped_already_sent"
    generate.assert_not_awaited()
    assert calls == []
