"""Run on the bot host with a desktop; leave the browser open after signing in."""
import argparse
import time
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from app.clients.linkedin_browser import profile_path, search_url
from app.clients.linkedin_session import load_session, save_session, clear_session_block, block_session


def search_ready(page, context, mode):
    parts = urlsplit(page.url)
    kind = 'people' if mode == 'trainer' else 'content'
    return (
        parts.scheme == 'https'
        and parts.hostname == 'www.linkedin.com'
        and parts.path == f'/search/results/{kind}/'
        and has_session(context)
        and not page.locator('input[name="session_key"]:visible, iframe[src*="captcha"]:visible').count()
    )


def verify_search(playwright, domain, mode):
    """Verify the operation the fetcher needs, not just the home feed."""
    context = playwright.chromium.launch_persistent_context(profile_path(), headless=True, accept_downloads=False)
    try:
        context.add_cookies(load_session(profile_path()))
        page = context.new_page()
        page.goto(search_url(domain, mode), wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        if not search_ready(page, context, mode):
            block_session(profile_path())
            raise ValueError('LinkedIn search still requires sign-in or verification on this host. Session is not ready.')
        save_session(profile_path(), context.cookies())
        clear_session_block(profile_path())
    finally:
        context.close()


def main(domain='SAP', mode='trainer', verify_only=False):
    with sync_playwright() as playwright:
        if verify_only:
            verify_search(playwright, domain, mode)
            print('SESSION_READY: Saved login verified on the search page on this host.', flush=True)
            return
        context = playwright.chromium.launch_persistent_context(profile_path(), headless=False, accept_downloads=False)
        try:
            saved = load_session(profile_path())
            if saved:
                context.add_cookies(saved)
            page = context.new_page()
            try:
                page.goto(search_url(domain, mode), wait_until='domcontentloaded')
            except PlaywrightError:
                if page.is_closed():
                    raise
                print('Initial navigation was interrupted. Finish signing in in this window.', flush=True)
            print('Complete sign-in or verification in THIS window. The helper will open the requested search. Leave it open until that search is verified.', flush=True)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if not context.pages:
                    raise ValueError('Browser closed before login was confirmed.')
                if page.is_closed():
                    page = context.pages[-1]
                if search_ready(page, context, mode):
                    page.wait_for_timeout(3000)
                    if search_ready(page, context, mode):
                        save_session(profile_path(), context.cookies())
                        break
                if page.url.startswith('https://www.linkedin.com/feed/') and has_session(context):
                    try:
                        page.goto(search_url(domain, mode), wait_until='domcontentloaded')
                    except PlaywrightError:
                        if page.is_closed():
                            raise
                page.wait_for_timeout(1000)
            else:
                raise ValueError('Timed out waiting for verified LinkedIn search access.')
        finally:
            context.close()
        print('Checking search access in a fresh fetcher browser...', flush=True)
        verify_search(playwright, domain, mode)
        print('SESSION_READY: Saved login verified on the search page on this host.', flush=True)


def has_session(context):
    return any(cookie.get('name') == 'li_at' and cookie.get('value')
               for cookie in context.cookies('https://www.linkedin.com'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', default='SAP')
    parser.add_argument('--mode', choices=('trainer', 'client'), default='trainer')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    main(args.domain, args.mode, args.verify_only)
