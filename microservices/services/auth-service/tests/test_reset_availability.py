import asyncio
from unittest.mock import AsyncMock
from starlette.requests import Request
from app.routes import accounts


def test_pending_account_cannot_receive_reset_token(monkeypatch):
    users = AsyncMock()
    users.find_one.return_value = None
    monkeypatch.setattr(accounts, 'require_origin', lambda request: None)
    monkeypatch.setattr(accounts, 'rate_limit', AsyncMock())
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': []})
    result = asyncio.run(accounts.forgot_password(
        accounts.Forgot(email='user@example.com'), request, {'auth_users': users}))
    assert users.find_one.call_args.args[0]['status'] == 'active'
    users.update_one.assert_not_called()
    assert result['success'] is True
    assert result['message'].startswith('If this active account')
