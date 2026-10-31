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
            status = document_status.pop(0) if isinstance(document_status, list) else document_status
            if status == 422:
                return httpx.Response(422, json={"detail": "TOC requires review before export or delivery"})
            return httpx.Response(status, content=b"test-workbook")
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
    assert calls[0][1] == {"toc": {"title": "DevOps"}}
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


def test_mail1_attaches_labeled_draft_for_review_required_toc(monkeypatch):
    toc = {"title": "DevOps", "quality": {"status": "requires_review", "review_warnings": ["Verify technical fit"],
                                             "validation_errors": []}, "days": [{"day": 1}]}
    result, calls, _ = setup_delivery(monkeypatch, requirement(), document_status=[422, 200], toc=toc)

    assert result["sent"] == 1
    assert [payload.get("draft", False) for url, payload in calls if "/documents/" in url] == [False, True]
    mail = calls[-1][1]
    assert "DRAFT FOR REVIEW" in mail["attachments"][0]["filename"]
    assert "draft ToC/course agenda is attached for your review" in mail["body"]


def test_mail1_sends_without_toc_when_review_gate_422_has_missing_quality_metadata(monkeypatch):
    toc = {"title": "DevOps", "days": [{"day": 1}]}
    result, calls, _ = setup_delivery(monkeypatch, requirement(), document_status=422, toc=toc)

    assert result["sent"] == 1
    assert result["failed"] == 0
    assert [payload for url, payload in calls if "/documents/" in url] == [{"toc": toc}]
    mail = next(payload for url, payload in calls if "/email/send" in url)
    assert not mail.get("attachments")
    assert "being held for quality review" in mail["body"]


def test_mail1_does_not_export_regeneration_required_toc_as_draft(monkeypatch):
    toc = {"title": "DevOps", "quality": {"status": "requires_regeneration", "validation_errors": ["Missing requested scope"]},
           "days": [{"day": 1}]}
    result, calls, _ = setup_delivery(monkeypatch, requirement(), document_status=422, toc=toc)

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert [payload for url, payload in calls if "/documents/" in url] == [{"toc": toc}]
    assert not any("/email/send" in url for url, _ in calls)


def test_existing_client_toc_is_forwarded_without_regeneration(monkeypatch):
    req = requirement(source_attachments=[{
        "filename": "Client TOC.xlsx", "safe_client_scope": True,
        "content_base64": base64.b64encode(b"client-workbook").decode(), "size_bytes": 15,
    }])
    result, calls, generate = setup_delivery(monkeypatch, req)
    assert result["sent"] == 1
    generate.assert_not_awaited()
    assert calls[-1][1]["attachments"][0]["filename"] == "Client TOC.xlsx"


def test_already_sent_mail_is_not_resent(monkeypatch):
    result, calls, generate = setup_delivery(monkeypatch, requirement(), existing={"email_id": "OLD"})
    assert result["sent"] == 0
    assert result["results"][0]["status"] == "skipped_already_sent"
    generate.assert_not_awaited()
    assert calls == []
