"""Human-operated organizer sign-in using the bot's persistent profile.

No browser automation or remote debugging is attached during authentication.
Stop the meeting service before opening this helper.
"""
import os
import signal
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    profile = str(Path(os.environ.get('MEET_BOT_PROFILE_PATH', './meet-bot-profile')).resolve())
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    args = [executable, '--user-data-dir=' + profile, '--no-first-run',
            '--window-size=1280,800', 'https://accounts.google.com/']
    # The existing Linux container runs as root. No automation/stealth flags.
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        args.insert(1, '--no-sandbox')
    browser = subprocess.Popen(args)

    def stop(*_):
        if browser.poll() is None:
            browser.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print('Sign in manually as the organizer, then open meet.google.com. '
          'Leave this window open and tell the operator when ready.', flush=True)
    try:
        browser.wait()
    finally:
        stop()
        try:
            browser.wait(timeout=15)
        except subprocess.TimeoutExpired:
            browser.kill()
            browser.wait()


if __name__ == '__main__':
    main()
