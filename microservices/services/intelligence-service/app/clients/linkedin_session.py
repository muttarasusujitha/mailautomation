"""Private LinkedIn session persistence inside the ignored bot profile directory."""
import json
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def session_file(profile):
    return Path(profile) / 'linkedin-session.json'


def linkedin_cookies(cookies):
    return [cookie for cookie in cookies if
            (cookie.get('domain', '').lstrip('.') == 'linkedin.com'
             or cookie.get('domain', '').lstrip('.').endswith('.linkedin.com'))]


def save_session(profile, cookies):
    path = session_file(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(linkedin_cookies(cookies), stream)
    temporary.replace(path)


def load_session(profile):
    path = session_file(profile)
    if not path.exists():
        return []
    return linkedin_cookies(json.loads(path.read_text(encoding='utf-8')))


class LinkedInAuthenticationRequired(ValueError):
    """Human verification is required before another account search."""


RECONNECT_MESSAGE = (
    'LinkedIn sign-in or verification required. Account retries are paused. '
    'Run the sign-in helper and complete verification before fetching again.'
)


def _session_fingerprint(profile):
    path = session_file(profile)
    return hashlib.sha256(path.read_bytes() if path.exists() else b'').hexdigest()


def block_session(profile):
    """Remember a rejected snapshot across workers and container restarts."""
    path = Path(profile) / 'linkedin-verification-required.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump({'session_fingerprint': _session_fingerprint(profile)}, stream)
    temporary.replace(path)


def ensure_session_not_blocked(profile):
    path = Path(profile) / 'linkedin-verification-required.json'
    if not path.exists():
        return
    try:
        blocked = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE) from None
    if blocked.get('session_fingerprint') == _session_fingerprint(profile):
        raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE)


def clear_session_block(profile):
    """Only the sign-in helper calls this after verifying search access."""
    (Path(profile) / 'linkedin-verification-required.json').unlink(missing_ok=True)


def _write_private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream)
    temporary.replace(path)


class LinkedInRateLimited(ValueError):
    """LinkedIn refused a search page with HTTP 403 or 429."""


RATE_LIMITED_MESSAGE = 'LinkedIn limited this session (HTTP 403/429). Fetching stopped.'


def _rate_limit_file(profile):
    return Path(profile) / 'linkedin-rate-limited.json'


def rate_limit_message(until):
    # Keep the "LinkedIn limited this session" prefix: the public fallback keys on it.
    return f'LinkedIn limited this session. Account searches are paused until {until:%Y-%m-%d %H:%M} UTC.'


def pause_after_rate_limit(profile, hours, now=None):
    """Stop account searches for a while so retries do not extend LinkedIn's limit."""
    until = (now or datetime.now(timezone.utc)) + timedelta(hours=hours)
    _write_private_json(_rate_limit_file(profile), {'paused_until': until.isoformat()})
    return until


def rate_limit_paused_until(profile, now=None):
    path = _rate_limit_file(profile)
    if not path.exists():
        return None
    try:
        until = datetime.fromisoformat(json.loads(path.read_text(encoding='utf-8'))['paused_until'])
    except (ValueError, KeyError, TypeError, OSError):
        path.unlink(missing_ok=True)
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if until <= (now or datetime.now(timezone.utc)):
        path.unlink(missing_ok=True)
        return None
    return until


def ensure_not_rate_limited(profile, now=None):
    until = rate_limit_paused_until(profile, now)
    if until:
        raise LinkedInRateLimited(rate_limit_message(until))


def _cursor_file(profile):
    return Path(profile) / 'linkedin-search-cursor.json'


def load_search_cursor(profile, key):
    """Where the last people search stopped for one domain and location."""
    path = _cursor_file(profile)
    try:
        cursors = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, OSError):
        cursors = {}
    cursor = cursors.get(key) if isinstance(cursors, dict) else None
    if not isinstance(cursor, dict):
        return {'query': 0, 'pages': {}}
    pages = cursor.get('pages') if isinstance(cursor.get('pages'), dict) else {}
    try:
        query = int(cursor.get('query', 0))
    except (TypeError, ValueError):
        query = 0
    return {'query': query, 'pages': dict(pages)}


def save_search_cursor(profile, key, cursor):
    path = _cursor_file(profile)
    try:
        cursors = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, OSError):
        cursors = {}
    if not isinstance(cursors, dict):
        cursors = {}
    cursors[key] = {'query': int(cursor.get('query', 0)), 'pages': dict(cursor.get('pages') or {})}
    _write_private_json(path, cursors)
