import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.routes import shortlists


@pytest.mark.parametrize('flow,expected', [('proposal', 'This is a PROPOSAL'), ('confirmed', 'This is a CONFIRMED CLIENT REQUIREMENT')])
def test_mail1_ai_receives_batch_rules_and_reference(monkeypatch, flow, expected):
    import openai
    create = AsyncMock(return_value=SimpleNamespace(output_text='SUBJECT: Training\nBODY: Dear Trainer, please confirm feasibility.'))
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)), raising=False)
    monkeypatch.setattr(shortlists.settings, 'OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(shortlists.settings, 'AI_PROVIDER', 'openai')
    db = {'automation_settings': SimpleNamespace(find_one=AsyncMock(return_value={'value': 'ai'}))}
    asyncio.run(shortlists._ai_trainer_mail1(db, trainer_name='Trainer', domain='Python',
        requirement={'batch_flow': flow}, fallback_subject='Reference', fallback_body='Verified scope: five days.'))
    prompt = create.call_args.kwargs['input']
    assert expected in prompt
    assert 'Verified scope: five days.' in prompt


@pytest.mark.parametrize('page,proposal', [('shortlist', True), ('shortlist1', False)])
def test_explicit_page_controls_batch_flow(page, proposal):
    assert shortlists._is_proposal_requirement({'pipeline_target': page, 'batch_flow': 'proposal'}) is proposal


def test_generate_ai_mail_refuses_template_mode():
    from fastapi import HTTPException
    db = {"automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "template"}))}
    with pytest.raises(HTTPException) as error:
        asyncio.run(shortlists.generate_ai_mail(shortlists.GenerateAiMailRequest(
            requirement_id="R1", mail_type="mail2", subject="Subject", body="Body",
        ), db))
    assert error.value.status_code == 409


def test_generate_ai_mail_uses_llm_when_ai_generation_is_on(monkeypatch):
    writer = AsyncMock(return_value={"subject": "AI subject", "body": "AI body"})
    monkeypatch.setattr(shortlists, "_ai_stage_mail", writer)
    db = {
        "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "ai"})),
        "requirements": SimpleNamespace(find_one=AsyncMock(return_value={"technology_needed": "Python"})),
    }
    result = asyncio.run(shortlists.generate_ai_mail(shortlists.GenerateAiMailRequest(
        requirement_id="R1", trainer_name="Ada", mail_type="mail2", subject="Subject", body="Reference",
    ), db))
    assert result["success"] is True
    assert result["generation_mode"] == "ai"
    assert result["body"] == "AI body"
    writer.assert_awaited()
