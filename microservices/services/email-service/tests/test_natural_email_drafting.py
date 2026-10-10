"""Regression checks for context-specific replies, without sending email."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app import config
from app.routes import inbox_actions


def use_ollama(monkeypatch, draft):
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        USE_LLM_FOR_EMAILS=True, AI_PROVIDER="ollama",
    ))
    writer = AsyncMock(return_value={"reply_body": draft, "analysis": {}})
    monkeypatch.setattr(inbox_actions, "_ollama_email_draft", writer)
    return writer


def test_missing_syllabus_preserves_actual_reply_and_review_requirement(monkeypatch):
    draft = "Hi Mira,\n\nThe Azure syllabus still needs confirmation.\n\nRegards,\nClahan Technologies"
    use_ollama(monkeypatch, draft)
    context = {"extracted_request": {"technology_needed": "Azure", "toc_requested": True},
               "business_features": {"toc": {"exists": False}}}
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Azure syllabus", "Can you send the Azure syllabus?", workflow_context=context,
        require_openai=True,
    ))
    assert result == (
        "Hi Mira,\n\nThe Azure syllabus still needs confirmation.\n\n"
        "Thanks,\nAnnapurna U.\nClahan Technologies"
    )
    assert "Python" not in result
    assert "confirming the dates" not in result
    assert context["reply_analysis"]["needs_human_review"] is True


def test_brief_acknowledgement_is_not_padded_with_default_template(monkeypatch):
    draft = "Thanks, Mira. Noted.\n\nClahan Technologies"
    writer = use_ollama(monkeypatch, draft)
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Re: Schedule", "Received, thank you.", require_openai=True,
    ))
    assert result == "Hi,\n\nThanks, Mira. Noted.\n\nThanks,\nAnnapurna U.\nClahan Technologies"
    prompt = writer.call_args.args[1]
    assert "kindly provide the following details" not in prompt
    assert "initial trainer search" not in prompt


def test_large_business_context_does_not_hide_thread_or_prior_replies(monkeypatch):
    writer = use_ollama(monkeypatch, "Hi Mira,\n\nYes, the confirmed session is online.")
    context = {
        "business_record": "x" * 15000,
        "verified_conversation_history": [{"direction": "outbound", "text": "The session is confirmed online."}],
        "recent_replies_to_this_sender": ["Thank you for sharing your requirement."],
        "clahan_reply_style_examples": ["UNRELATED OLD TEMPLATE"],
    }
    asyncio.run(inbox_actions._ai_draft_reply(
        "Delivery mode", "Is it online?", workflow_context=context, require_openai=True,
    ))
    prompt = writer.call_args.args[1]
    assert "The session is confirmed online." in prompt
    assert "Thank you for sharing your requirement." in prompt
    assert "UNRELATED OLD TEMPLATE" not in prompt
    assert context["verified_conversation_history"]


def test_required_ai_failure_does_not_return_repetitive_template(monkeypatch):
    writer = use_ollama(monkeypatch, "")
    writer.side_effect = RuntimeError("Provider unavailable")
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Availability", "Is the trainer available?", require_openai=True,
        reference_reply={"body": "Stock template"},
    ))
    assert result == ""


def test_stock_closing_removed_but_substantive_answer_preserved(monkeypatch):
    use_ollama(monkeypatch, "You're welcome, Mira. Let me know if you need anything else.")
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Re: Invite", "Received, thank you.", require_openai=True,
    ))
    assert result == "Hi,\n\nYou're welcome, Mira.\n\nThanks,\nAnnapurna U.\nClahan Technologies"


def test_cleanup_preserves_specific_requests_and_verified_details():
    body = (
        "Hi Mira,\n\nThe confirmed rate is INR 12,500 per day. "
        "Please let us know if 3 PM IST on 12 October works for you. "
        "Join at https://meet.google.com/abc-defg-hij.\n\nRegards,\nClahan Technologies"
    )
    assert inbox_actions._finish_email_draft(body) == body


def test_cleanup_preserves_signature_and_removes_only_whole_stock_sentence():
    body = "Hi Mira,\n\nThe session is online. We look forward to your response.\n\nRegards,\nClahan Technologies"
    assert inbox_actions._finish_email_draft(body) == (
        "Hi Mira,\n\nThe session is online.\n\nRegards,\nClahan Technologies"
    )


def test_ai_gets_relevant_approved_examples_and_all_ten_recent_replies(monkeypatch):
    writer = use_ollama(monkeypatch, "Thanks, Mira. Received.")
    context = {"recent_replies_to_this_sender": [f"Earlier reply {i}" for i in range(10)]}
    asyncio.run(inbox_actions._ai_draft_reply(
        "Azure syllabus", "Here is the syllabus.", workflow_context=context,
        reference_reply={"body": "Thank you for sharing the Azure syllabus."}, require_openai=True,
    ))
    prompt = writer.call_args.args[1]
    assert "details_received" in prompt
    assert "Azure syllabus" in prompt
    assert "Earlier reply 9" in prompt


def test_repeated_ai_draft_gets_one_rewrite(monkeypatch):
    repeated = "We will check the trainer availability against your preferred dates and share the next update with you."
    fresh = "The trainer's availability still needs checking. We'll get back to you once we can confirm the dates."
    writer = use_ollama(monkeypatch, repeated)
    writer.side_effect = [
        {"reply_body": repeated, "analysis": {}},
        {"reply_body": fresh, "analysis": {}},
    ]
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Availability", "Any news?", require_openai=True,
        workflow_context={"recent_replies_to_this_sender": [repeated]},
    ))
    assert result == f"Hi,\n\n{fresh}\n\nThanks,\nAnnapurna U.\nClahan Technologies"
    assert writer.await_count == 2
    assert "previous draft repeated a recent reply" in writer.call_args.args[1]


def test_persistent_ai_repetition_is_held_for_review(monkeypatch):
    repeated = "We will check the trainer availability against your preferred dates and share the next update with you."
    writer = use_ollama(monkeypatch, repeated)
    context = {"recent_replies_to_this_sender": [repeated]}
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Availability", "Any news?", workflow_context=context, require_openai=True,
    ))
    assert result == ""
    assert writer.await_count == 2
    assert context["reply_analysis"]["needs_human_review"] is True


def test_empty_schema_response_retries_json_with_review_validation(monkeypatch):
    import json
    analysis = {
        "sender_intent": "Ask for syllabus", "observed_tone": "neutral", "communication_stage": "enquiry",
        "verified_facts": [], "unresolved_questions": ["Syllabus availability"],
        "reply_strategy": "Check availability", "commitments_to_avoid": ["Do not promise delivery"],
        "needs_human_review": True, "human_review_reason": "Availability not confirmed", "confidence": 0.8,
    }
    replies = iter([{"response": "", "done": False}, {"response": json.dumps({
        "reply_body": "The syllabus availability needs confirmation.", "analysis": analysis,
    })}])
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, endpoint, json):
            calls.append(json)
            payload = next(replies)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(inbox_actions.httpx, "AsyncClient", Client)
    result = asyncio.run(inbox_actions._ollama_email_draft(
        SimpleNamespace(OLLAMA_URL="http://model.example/api/generate", OLLAMA_MODEL="test"),
        "Please share the syllabus.",
    ))
    assert isinstance(calls[0]["format"], dict)
    assert calls[1]["format"] == "json"
    assert "needs_human_review" in calls[1]["prompt"]
    assert result["analysis"]["needs_human_review"] is True
    assert result["reply_body"] == "The syllabus availability needs confirmation."


def test_ai_draft_drops_the_stiff_opening_and_office_phrases(monkeypatch):
    draft = (
        "Hi,\n\n"
        "Greetings of the day! Thanks for sharing the DevOps training requirement.\n\n"
        "We have recorded the confirmed batch scope: 7 training days, Offline.\n\n"
        "We will revert with the next step shortly. "
        "Training duration is used only for the number of lab days; it is not treated as the participant count. "
        "The region can be finalized after the cloud provider is selected."
    )
    use_ollama(monkeypatch, draft)
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "DevOps training requirement",
        "Please share a trainer CV and ToC for 7 offline days.",
        require_openai=True,
    ))
    lowered = result.lower()
    assert "greetings of the day" not in lowered
    assert "confirmed batch scope" not in lowered
    assert "revert" not in lowered
    assert "not treated as the participant count" not in lowered
    assert "region can be finalized" not in lowered
    assert "7 training days, Offline" in result
    assert result.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")


def test_ai_prompt_does_not_ask_for_greetings_of_the_day(monkeypatch):
    writer = use_ollama(monkeypatch, "Thanks for sharing the requirement.")
    asyncio.run(inbox_actions._ai_draft_reply(
        "DevOps training", "We need a trainer.", require_openai=True,
        reference_reply={"body": "Greetings of the day! Thanks for sharing the requirement. We will revert shortly."},
    ))
    prompt = writer.call_args.args[1]
    assert "begin that sentence with Greetings of the day" not in prompt
    assert "Do not open with Greetings of the day" in prompt
    assert "Greetings of the day" not in prompt.split("Reference facts", 1)[-1].split("Incoming email", 1)[0]


def test_generated_reply_adds_named_greeting_and_short_signature(monkeypatch):
    writer = use_ollama(monkeypatch, "The session is online.\n\nPlease confirm your availability.")
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Delivery mode", "Is it online?", workflow_context={"sender_name": "Mira"}, require_openai=True,
    ))
    assert result == (
        "Hi Mira,\n\nThe session is online.\n\nPlease confirm your availability."
        "\n\nThanks,\nAnnapurna U.\nClahan Technologies"
    )
    assert "under 80 words" in writer.call_args.args[1]
    assert "Ask only for missing information the recipient can provide" in writer.call_args.args[1]


def test_structure_separates_inline_greeting_without_losing_details():
    body = "Hi Mira, The rate is INR 12,500 per day.\nJoin: https://meet.google.com/abc-defg-hij"
    result = inbox_actions._structure_email_draft(body)
    assert result.startswith("Hi Mira,\n\nThe rate is INR 12,500 per day.")
    assert "Join: https://meet.google.com/abc-defg-hij" in result
    assert result.count("Hi Mira,") == 1
    assert result.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")


def test_structure_does_not_create_email_from_empty_output_or_use_address_as_name():
    assert inbox_actions._structure_email_draft("") == ""
    assert inbox_actions._structure_email_draft("Confirmed.", "mira@example.com").startswith("Hi,\n\n")


def test_structure_preserves_contact_details_and_postscript():
    body = (
        "Hi Mira,\nThe session is online.\nRegards,\nClahan Technologies\n"
        "coordinator@example.com\n\nPS: The revised start time is 3 PM IST."
    )
    result = inbox_actions._structure_email_draft(body)
    assert "coordinator@example.com" in result
    assert result.endswith("PS: The revised start time is 3 PM IST.")
    assert result.count("Thanks,") == 1
    assert "Annapurna U." in result


def test_dashboard_ai_calls_the_model_without_the_env_flag(monkeypatch):
    writer = use_ollama(monkeypatch, "Hi Mira,\n\nThe session is online.")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        USE_LLM_FOR_EMAILS=False, AI_PROVIDER="ollama",
    ))
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Delivery mode", "Is it online?", require_openai=True,
    ))
    assert writer.await_count == 1
    assert "online" in result


def test_callers_without_ai_selection_stay_on_the_reference(monkeypatch):
    writer = use_ollama(monkeypatch, "This must not be used.")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        USE_LLM_FOR_EMAILS=False, AI_PROVIDER="ollama",
    ))
    result = asyncio.run(inbox_actions._ai_draft_reply(
        "Delivery mode", "Is it online?", require_openai=False,
        reference_reply={"body": "Approved reference"},
    ))
    assert writer.await_count == 0
    assert result == "Approved reference"


@pytest.mark.parametrize("ai_enabled", [True, False])
def test_regenerate_never_saves_template_when_ai_is_unavailable(monkeypatch, ai_enabled):
    from app.routes import inbox
    writer = use_ollama(monkeypatch, "")
    writer.side_effect = RuntimeError("Provider unavailable")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        USE_LLM_FOR_EMAILS=ai_enabled, AI_PROVIDER="ollama",
    ))
    records = SimpleNamespace(
        find_one=AsyncMock(return_value={
            "email_id": "test-email", "subject": "Session mode", "body": "Is it online?",
            "from_name": "Mira", "email_classification": {"scenario": "general_question"},
        }),
        update_one=AsyncMock(),
    )
    db = {
        "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "ai"})),
        "client_emails": records,
    }
    monkeypatch.setattr(inbox_actions, "build_auto_reply", lambda **kwargs: {"body": "Stock fallback template"})
    monkeypatch.setattr(inbox_actions, "_load_reply_workflow_context", AsyncMock(return_value={}))
    monkeypatch.setattr(inbox, "_verified_question_history", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as error:
        asyncio.run(inbox_actions.regenerate_reply("test-email", inbox_actions.RegenerateRequest(), db))
    assert error.value.status_code == 502
    assert "no template was substituted" in error.value.detail
    records.update_one.assert_not_awaited()
    assert writer.await_count == 1
