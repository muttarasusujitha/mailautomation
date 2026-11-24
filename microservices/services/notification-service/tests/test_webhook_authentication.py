import asyncio
import hashlib
import hmac
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.routes import whatsapp_webhooks as hooks


def request(body=b'{}', signature='', path='/meta/webhook'):
    async def receive(): return {'type': 'http.request', 'body': body, 'more_body': False}
    return Request({'type': 'http', 'method': 'POST', 'path': path, 'query_string': b'',
                    'headers': [(b'x-hub-signature-256', signature.encode())], 'scheme': 'https', 'server': ('example.com', 443)}, receive)


def test_twilio_missing_secret_or_signature_fails_closed(monkeypatch):
    monkeypatch.setattr(hooks.settings, 'TWILIO_AUTH_TOKEN', '')
    assert not hooks._verify_twilio_signature({}, 'https://example.com', {}, 'fake')
    assert not hooks._verify_twilio_signature({'authToken': 'test'}, 'https://example.com', {}, '')


@pytest.mark.parametrize('signature', ['', 'sha256=bad'])
def test_meta_rejects_before_database_access(monkeypatch, signature):
    monkeypatch.setattr(hooks.settings, 'META_APP_SECRET', 'test-secret')
    with pytest.raises(HTTPException) as error:
        asyncio.run(hooks.meta_webhook_receive(request(signature=signature), {}))
    assert error.value.status_code == 403


def test_valid_meta_signature_accepts_exact_body(monkeypatch):
    monkeypatch.setattr(hooks.settings, 'META_APP_SECRET', 'test-secret')
    body = b'{"entry": []}'
    signature = 'sha256=' + hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
    assert asyncio.run(hooks.meta_webhook_receive(request(body, signature), {})).status_code == 200
    with pytest.raises(HTTPException):
        asyncio.run(hooks.meta_webhook_receive(request(body+b' ', signature), {}))


def test_twilio_status_without_signature_cannot_change_delivery(monkeypatch):
    monkeypatch.setattr(hooks, '_get_cfg', AsyncMock(return_value={'authToken': 'test'}))
    with pytest.raises(HTTPException) as error:
        asyncio.run(hooks.twilio_status(request(path='/status-callback'), {}))
    assert error.value.status_code == 403
