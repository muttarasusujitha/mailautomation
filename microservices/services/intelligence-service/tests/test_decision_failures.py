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


def test_anthropic_retries_without_rejected_temperature(monkeypatch):
    import sys
    calls = []

    class Messages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if 'temperature' in kwargs:
                raise TypeError("AsyncMessages.create() got an unexpected keyword argument 'temperature'")
            return SimpleNamespace(content=[SimpleNamespace(type='text', text=' Hi ')])

    fake = SimpleNamespace(AsyncAnthropic=lambda api_key: SimpleNamespace(messages=Messages()))
    monkeypatch.setitem(sys.modules, 'anthropic', fake)
    settings = SimpleNamespace(ANTHROPIC_API_KEY='k', ANTHROPIC_MODEL='m')
    reply = asyncio.run(assistant._call_anthropic([{'role': 'user', 'content': 'x'}], '', settings, 10, 0.7))
    assert reply == 'Hi'
    assert 'temperature' in calls[0] and 'temperature' not in calls[1]


def test_closed_browser_noise_is_ignored_but_other_errors_are_not():
    from app import main

    class TargetClosedError(Exception):
        pass

    seen = []
    loop = SimpleNamespace(default_exception_handler=seen.append)
    main._ignore_closed_browser_noise(loop, {'exception': TargetClosedError()})
    assert not seen
    main._ignore_closed_browser_noise(loop, {'exception': ValueError('real')})
    assert len(seen) == 1
