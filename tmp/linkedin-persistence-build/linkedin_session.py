"""Private LinkedIn session persistence inside the ignored bot profile directory."""
import json
import hashlib
import os
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
