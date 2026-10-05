from app.clients.linkedin_session import save_session, load_session
import pytest
from app.clients.linkedin_session import (
    block_session, ensure_session_not_blocked, clear_session_block,
    LinkedInAuthenticationRequired,
)


def test_session_roundtrip_keeps_only_linkedin_cookies(tmp_path):
    cookies = [
        {'name': 'li_at', 'value': 'test-session', 'domain': '.linkedin.com', 'path': '/'},
        {'name': 'other', 'value': 'test-other', 'domain': 'example.com', 'path': '/'},
        {'name': 'fake', 'value': 'test-fake', 'domain': 'linkedin.com.evil.test', 'path': '/'},
    ]
    save_session(tmp_path, cookies)
    assert load_session(tmp_path) == cookies[:1]


def test_missing_session_is_empty(tmp_path):
    assert load_session(tmp_path) == []


def test_rejected_snapshot_stays_blocked_until_replaced(tmp_path):
    cookies = [{'name': 'li_at', 'value': 'old-test-token', 'domain': '.linkedin.com', 'path': '/'}]
    save_session(tmp_path, cookies)
    block_session(tmp_path)
    with pytest.raises(LinkedInAuthenticationRequired, match='retries are paused'):
        ensure_session_not_blocked(tmp_path)
    # Rewriting the same rejected snapshot must not restart requests.
    save_session(tmp_path, cookies)
    with pytest.raises(LinkedInAuthenticationRequired):
        ensure_session_not_blocked(tmp_path)
    save_session(tmp_path, [{**cookies[0], 'value': 'fresh-test-token'}])
    ensure_session_not_blocked(tmp_path)


def test_verified_helper_can_clear_block_and_corrupt_marker_fails_closed(tmp_path):
    block_session(tmp_path)
    marker = tmp_path / 'linkedin-verification-required.json'
    marker.write_text('invalid json', encoding='utf-8')
    with pytest.raises(LinkedInAuthenticationRequired):
        ensure_session_not_blocked(tmp_path)
    clear_session_block(tmp_path)
    ensure_session_not_blocked(tmp_path)
