import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.routes import assistant
from app.routes.ai import reply_decision


@pytest.mark.parametrize('text,action', [
    ('Not available Monday, but available Tuesday.', 'requires_review'),
    ('I am interested.\nOn Monday somebody wrote:\nNot available', 'mark_interested'),
    ('Not interested', 'mark_declined'),
    ('Yesterday I reviewed the proposal', 'requires_review'),
])
def test_reply_intent(text, action):
    assert reply_decision(text)[1] == action


def test_all_provider_failures_are_not_success(monkeypatch):
    monkeypatch.setattr(assistant, 'get_settings', lambda: SimpleNamespace(OPENAI_API_KEY='test', ANTHROPIC_API_KEY='', GEMINI_API_KEY=''))
    monkeypatch.setattr(assistant, '_call_openai', AsyncMock(side_effect=RuntimeError('provider error')))
    result = asyncio.run(assistant.assistant_chat(assistant.ChatRequest(messages=[assistant.ChatMessage(role='user', content='Hello')]), None))
    assert result['success'] is False
    assert result['error'] == 'ai_provider_unavailable'
    assert len(result['messages']) == 1


def test_recovered_fallback_does_not_return_stale_error(monkeypatch):
    monkeypatch.setattr(assistant, 'get_settings', lambda: SimpleNamespace(OPENAI_API_KEY='test', ANTHROPIC_API_KEY='test', GEMINI_API_KEY=''))
    monkeypatch.setattr(assistant, '_call_openai', AsyncMock(side_effect=RuntimeError('failed')))
    monkeypatch.setattr(assistant, '_call_anthropic', AsyncMock(return_value='Hello'))
    result = asyncio.run(assistant.assistant_chat(assistant.ChatRequest(messages=[assistant.ChatMessage(role='user', content='Hello')]), None))
    assert result['success'] and result['error'] is None
