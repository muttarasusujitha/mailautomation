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
    db = {'automation_settings': SimpleNamespace(find_one=AsyncMock(return_value={'value': 'ai'}))}
    asyncio.run(shortlists._ai_trainer_mail1(db, trainer_name='Trainer', domain='Python',
        requirement={'batch_flow': flow}, fallback_subject='Reference', fallback_body='Verified scope: five days.'))
    prompt = create.call_args.kwargs['input']
    assert expected in prompt
    assert 'Verified scope: five days.' in prompt


@pytest.mark.parametrize('page,proposal', [('shortlist', True), ('shortlist1', False)])
def test_explicit_page_controls_batch_flow(page, proposal):
    assert shortlists._is_proposal_requirement({'pipeline_target': page, 'batch_flow': 'proposal'}) is proposal
