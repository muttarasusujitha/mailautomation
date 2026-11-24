"""Check the deployed LinkedIn runtime without searching or exposing cookies."""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.clients.linkedin_session import (
    LinkedInAuthenticationRequired,
    ensure_session_not_blocked,
    load_session,
)


def session_status(profile, now=None):
    """A saved cookie is not proof that LinkedIn will accept the session."""
    try:
        ensure_session_not_blocked(profile)
        pause = Path(profile) / 'linkedin-rate-limited.json'
        if pause.exists():
            until = datetime.fromisoformat(json.loads(pause.read_text())['paused_until'])
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if until.timestamp() > (time.time() if now is None else now):
                return 'rate_limited'
        cookies = load_session(profile)
        now = time.time() if now is None else now
        for cookie in cookies:
            if cookie.get('name') != 'li_at' or not cookie.get('value'):
                continue
            expires = cookie.get('expires', -1)
            if expires is None or float(expires) <= 0 or float(expires) > now:
                return 'saved_unverified'
        return 'sign_in_required'
    except LinkedInAuthenticationRequired:
        return 'verification_required'
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return 'invalid_session'


def read_api(path):
    with urllib.request.urlopen('http://127.0.0.1:8005' + path, timeout=5) as response:
        return json.load(response)


def main():
    from playwright.sync_api import sync_playwright
    from app.clients.linkedin_browser import bot_option, profile_path

    deadline = time.monotonic() + 180
    while True:
        try:
            read_api('/health')
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise SystemExit('LinkedIn intelligence-service did not become healthy.')
            time.sleep(5)

    if bot_option('LINKEDIN_BOT_ENABLED', 'false').lower() != 'true':
        raise SystemExit('LinkedIn bot is disabled in the deployed intelligence-service.')

    profile = profile_path()
    if not os.path.isdir(profile) or not os.access(profile, os.R_OK | os.W_OK):
        raise SystemExit('LinkedIn profile volume is missing or not writable.')

    # Use a temporary browser, never open or lock the active account profile.
    # Launching detects missing Chromium binaries and missing Linux libraries.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()

    collection = {}
    for mode in ('trainer', 'client'):
        config = read_api('/api/v1/linkedin-leads/bot/' + mode)
        collection[mode] = {'enabled': bool(config.get('enabled')),
                            'status': config.get('status', 'idle')}
    account = session_status(profile)
    print(json.dumps({'runtime': 'ready', 'account': account,
                      'automatic_collection': collection}, sort_keys=True))
    if account == 'rate_limited':
        print('::warning::LinkedIn is deployed but account searches are rate-limited. '
              'The stored cooldown must expire before retrying. No search was attempted.')
        return
    if account != 'saved_unverified':
        raise SystemExit('LinkedIn runtime is deployed, but its account needs manual '
                         'sign-in/verification on EC2: ' + account)
    print('LinkedIn browser runtime is deployed. Saved session is present; '
          'live LinkedIn search access has not been verified by this check.')


if __name__ == '__main__':
    main()
