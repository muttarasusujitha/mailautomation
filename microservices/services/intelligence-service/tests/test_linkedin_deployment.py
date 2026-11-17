from app.linkedin_deployment import session_status
from app.clients.linkedin_session import block_session, save_session
import json
from datetime import datetime, timezone


def test_missing_or_expired_session_requires_sign_in(tmp_path):
    assert session_status(tmp_path, now=100) == 'sign_in_required'
    save_session(tmp_path, [{'name': 'li_at', 'value': 'test-only',
                            'domain': '.linkedin.com', 'expires': 99}])
    assert session_status(tmp_path, now=100) == 'sign_in_required'


def test_saved_session_is_not_claimed_as_verified(tmp_path):
    save_session(tmp_path, [{'name': 'li_at', 'value': 'test-only',
                            'domain': '.linkedin.com', 'expires': 200}])
    assert session_status(tmp_path, now=100) == 'saved_unverified'
    block_session(tmp_path)
    assert session_status(tmp_path, now=100) == 'verification_required'


def test_corrupt_session_does_not_expose_contents(tmp_path):
    (tmp_path / 'linkedin-session.json').write_text('private invalid content')
    assert session_status(tmp_path) == 'invalid_session'


def test_other_cookie_is_not_a_login(tmp_path):
    save_session(tmp_path, [{'name': 'preference', 'value': 'test-only',
                            'domain': '.linkedin.com'}])
    assert session_status(tmp_path) == 'sign_in_required'


def test_cooldown_is_reported_without_clearing_it(tmp_path):
    marker = tmp_path / 'linkedin-rate-limited.json'
    marker.write_text(json.dumps({'paused_until': datetime.fromtimestamp(200, timezone.utc).isoformat()}))
    assert session_status(tmp_path, now=100) == 'rate_limited'
    assert session_status(tmp_path, now=300) == 'sign_in_required'
    assert marker.exists()
