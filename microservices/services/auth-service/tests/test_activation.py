import asyncio
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import manage_users, security
from app.routes import accounts


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    settings = SimpleNamespace(allowed_origins_list=[], FRONTEND_URL='http://localhost',
                               MONGODB_URL='mongodb://unused', MONGODB_DB_NAME='test')
    monkeypatch.setattr(security, 'get_settings', lambda: settings)
    monkeypatch.setattr(manage_users, 'get_settings', lambda: settings)


def request(path='/api/v1/auth/login', cookie=None):
    headers = [(b'cookie', f'ts_session={cookie}'.encode())] if cookie else []
    return Request({'type': 'http', 'method': 'GET', 'path': path, 'headers': headers})


def test_registration_is_ready_without_admin_activation(monkeypatch):
    db = MagicMock()
    db.__getitem__.return_value = AsyncMock()
    monkeypatch.setattr(accounts, 'rate_limit', AsyncMock())
    payload = accounts.Registration(email='User@example.com', name='User',
                                    password='long-test-password', role='trainer')
    result = asyncio.run(accounts.register(payload, request(), db))
    stored = db['auth_users'].insert_one.call_args.args[0]
    assert stored['status'] == 'active'
    assert stored['role'] == 'recruiter'
    assert stored['requested_role'] == 'trainer'
    assert security.verify_password(payload.password, stored['password_hash'])
    assert 'password' not in stored
    assert 'csrf_token' not in result
    assert 'ready to use' in result['message']


def test_pending_account_is_activated_on_valid_password_login(monkeypatch):
    collection = AsyncMock()
    user = {'user_id': 'u1', 'email': 'user@example.com', 'status': 'pending',
            'role': 'recruiter', 'auth_version': 0,
            'password_hash': security.hash_password('correct-password')}
    collection.find_one.return_value = user
    collection.update_one.return_value = SimpleNamespace(matched_count=1)
    monkeypatch.setattr(accounts, 'rate_limit', AsyncMock())
    monkeypatch.setattr(accounts, 'issue_session', AsyncMock(return_value={'success': True}))
    response = Response()
    result = asyncio.run(accounts.login(accounts.Credentials(email='user@example.com', password='correct-password'),
                                       request(), response, {'auth_users': collection}))
    assert result['success'] is True
    assert user['status'] == 'active'
    assert collection.update_one.call_args.args[0] == {'user_id': 'u1', 'status': 'pending'}
    assert response.headers.get('set-cookie') is None


def test_disabled_account_cannot_login(monkeypatch):
    collection = AsyncMock()
    collection.find_one.return_value = {'status': 'disabled', 'password_hash': security.hash_password('correct-password')}
    monkeypatch.setattr(accounts, 'rate_limit', AsyncMock())
    response = Response()
    with pytest.raises(HTTPException) as error:
        asyncio.run(accounts.login(accounts.Credentials(email='user@example.com', password='correct-password'),
                                   request(), response, {'auth_users': collection}))
    assert error.value.status_code == 401
    assert 'set-cookie' not in response.headers


def test_social_login_creates_standard_account_for_verified_identity():
    users = AsyncMock()
    users.find_one.side_effect = [None, {
        'user_id': 'USR-new', 'email_normalized': 'new@example.com', 'role': 'recruiter',
        'status': 'active', 'auth_version': 0,
    }]
    result = asyncio.run(accounts._resolve_social_user(
        {'auth_users': users}, {'email': 'New@example.com', 'name': 'New User'}))
    created = users.insert_one.call_args.args[0]
    assert created['email_normalized'] == 'new@example.com'
    assert created['role'] == 'recruiter'
    assert created['status'] == 'active'
    assert result['status'] == 'active'


def test_social_login_activates_pending_account_but_not_disabled_account():
    users = AsyncMock()
    pending = {'user_id': 'u1', 'email_normalized': 'user@example.com', 'role': 'recruiter', 'status': 'pending'}
    users.find_one.return_value = pending
    users.update_one.return_value = SimpleNamespace(matched_count=1)
    activated = asyncio.run(accounts._resolve_social_user(
        {'auth_users': users}, {'email': 'user@example.com', 'name': 'User'}))
    assert activated['status'] == 'active'

    disabled_users = AsyncMock()
    disabled_users.find_one.return_value = {'user_id': 'u2', 'status': 'disabled'}
    disabled = asyncio.run(accounts._resolve_social_user(
        {'auth_users': disabled_users}, {'email': 'disabled@example.com'}))
    assert disabled is None
    disabled_users.update_one.assert_not_awaited()


@pytest.mark.parametrize('user', [None, {'status': 'active', 'auth_version': 2}])
def test_existing_session_cannot_bypass_activation_or_revocation(user):
    sessions, users = AsyncMock(), AsyncMock()
    sessions.find_one.return_value = {'user_id': 'u1', 'auth_version': 1}
    users.find_one.return_value = user
    with pytest.raises(HTTPException) as error:
        asyncio.run(security.authenticate({'auth_sessions': sessions, 'auth_users': users}, request(cookie='old-session')))
    assert error.value.status_code == 401
    assert users.find_one.call_args.args[0]['status'] == 'active'


@pytest.mark.parametrize('action', ['create-admin', 'activate', 'disable'])
def test_operator_commands(monkeypatch, action):
    users = AsyncMock()
    users.find_one.return_value = None
    users.update_one.return_value = SimpleNamespace(matched_count=1)
    db = MagicMock(auth_users=users)
    mongo = MagicMock()
    mongo.__getitem__.return_value = db
    monkeypatch.setattr(manage_users, 'AsyncIOMotorClient', lambda *a, **kw: mongo)
    monkeypatch.setattr(manage_users, 'ensure_indexes', AsyncMock())
    monkeypatch.setattr(manage_users, 'read_password', lambda: 'operator-test-password')
    asyncio.run(manage_users.run(SimpleNamespace(action=action, email='User@example.com', name='User', role='recruiter')))
    if action == 'create-admin':
        stored = users.insert_one.call_args.args[0]
        assert stored['role'] == 'admin' and stored['status'] == 'active'
        assert security.verify_password('operator-test-password', stored['password_hash'])
    else:
        query, update = users.update_one.call_args.args
        assert query == {'email_normalized': 'user@example.com'}
        assert update['$set']['status'] == ('active' if action == 'activate' else 'disabled')
        assert update['$inc']['auth_version'] == 1
    mongo.close.assert_called_once()


def test_password_prompt_refuses_visible_input(monkeypatch):
    def unsupported_terminal(*args):
        warnings.warn('Cannot hide input', manage_users.getpass.GetPassWarning)
    monkeypatch.setattr(manage_users.getpass, 'getpass', unsupported_terminal)
    with pytest.raises(SystemExit, match='hidden password input'):
        manage_users.read_password()
