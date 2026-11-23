"""Read visible LinkedIn search cards using a dedicated, human-authenticated profile."""
import asyncio
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from app.clients.linkedin_session import (
    LinkedInAuthenticationRequired, RECONNECT_MESSAGE,
    block_session, ensure_session_not_blocked,
)

_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


class PartialSearchError(ValueError):
    """Preserve real results when a later page fails or requires verification."""
    def __init__(self, message, results):
        super().__init__(message)
        self.results = list(results)


def bot_option(name, default=''):
    if name in os.environ:
        return os.environ[name]
    from dotenv import dotenv_values
    return dotenv_values('.env').get(name) or default


def profile_path():
    default = Path(__file__).resolve().parents[2] / 'linkedin-bot-profile'
    configured = bot_option('LINKEDIN_BOT_PROFILE_PATH')
    return str(Path(configured or default).resolve())


def canonical_url(value):
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not (host == 'linkedin.com' or host.endswith('.linkedin.com')):
        return ''
    if not parts.path.startswith(('/in/', '/posts/', '/feed/update/')):
        return ''
    return urlunsplit(('https', 'www.linkedin.com', parts.path.rstrip('/'), '', ''))


def trainer_keywords(domain, location=''):
    """Plain people-search keywords. LinkedIn treats parenthetical OR as literal text."""
    keywords = f'{domain} {location}'.strip()
    if not re.search(r'\b(?:trainer|instructor|facilitator|coach)\b', keywords, re.IGNORECASE):
        keywords = f'{keywords} trainer'
    return keywords


def search_url(domain, mode, location='', page=1):
    if mode == 'trainer':
        keywords = trainer_keywords(domain, location)
    else:
        keywords = f'{domain} {location}'.strip() + ' ("trainer required" OR "looking for trainer" OR "need trainer" OR "seeking trainer")'
    kind = 'people' if mode == 'trainer' else 'content'
    params = {'keywords': keywords, 'page': page}
    if mode == 'client':
        params['sortBy'] = '"date_posted"'
    return f'https://www.linkedin.com/search/results/{kind}/?{urlencode(params)}'


async def require_session(page):
    if urlsplit(page.url).path.startswith('/ssr-login/remember-me-auto-login'):
        # Allow LinkedIn's normal redirect to finish; never interact with a gate.
        try:
            await page.wait_for_url(
                lambda url: not urlsplit(url).path.startswith('/ssr-login/remember-me-auto-login'),
                wait_until='domcontentloaded', timeout=10000)
        except Exception:
            raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE) from None
    if urlsplit(page.url).path.startswith('/ssr-login/'):
        raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE)
    if any(part in urlsplit(page.url).path for part in ('/login', '/checkpoint', '/authwall', '/uas/')):
        raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE)
    if await page.locator('input[name="session_key"]:visible, iframe[src*="captcha"]:visible').count():
        raise LinkedInAuthenticationRequired(RECONNECT_MESSAGE)


# Restrict text to each result card, so another person's skills cannot qualify it.
EXTRACT_CARDS = """cards => cards.map(card => {
  const links = [...card.querySelectorAll('a[href]')].map(a => ({url:a.href, title:a.innerText}));
  const urn = card.getAttribute('data-urn') || card.querySelector('[data-urn]')?.getAttribute('data-urn');
  if (urn && /^urn:li:activity:\\d+$/.test(urn)) links.push({url:'https://www.linkedin.com/feed/update/'+urn, title:''});
  return {links, content:card.innerText};
})"""


def author_headline(content):
    # Both actions occur between the author header and the post body.
    # Without a boundary, a hiring post can falsely qualify its recruiter.
    parts = re.split(r'\n\s*(?:Follow|Connect)\s*\n', content, maxsplit=1)
    return parts[0] if len(parts) > 1 else ''


async def scroll_results(page, cards):
    # LinkedIn scrolls a nested results panel. A wheel event at the default
    # pointer location leaves the initial three cards unchanged.
    await cards.last.scroll_into_view_if_needed(timeout=3000)
    await cards.last.hover(timeout=3000)
    await page.mouse.wheel(0, 1800)
    await page.wait_for_timeout(1500)


async def read_post_cards(page, context, mode, limit, results=None, processed=None):
    """Read current visible post cards and copy their public permalink."""
    await context.grant_permissions(['clipboard-read', 'clipboard-write'], origin='https://www.linkedin.com')
    cards = page.locator('[role="listitem"][componentkey^="update-card-focus"]')
    await cards.first.wait_for(timeout=15000)
    if mode == 'trainer':
        for _ in range(4):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(900)
    results = [] if results is None else results
    processed = set() if processed is None else processed
    for index in range(min(await cards.count(), 25 if mode == 'trainer' else limit)):
        card = cards.nth(index)
        data = (await card.evaluate_all(EXTRACT_CARDS))[0]
        fingerprint = data['content']
        if fingerprint in processed:
            continue
        author = next((link for link in data['links'] if '/in/' in urlsplit(canonical_url(link['url'])).path and link['title'].strip()), {})
        author_name = author.get('title', '').strip().split('\n')[0]
        lines = [line.strip() for line in data['content'].splitlines() if line.strip()]
        title = author_name or (lines[1] if len(lines) > 1 and lines[0] == 'Feed post' else lines[0] if lines else '')
        if mode == 'trainer':
            if author:
                # The author's visible headline is evidence about that person;
                # the post body may describe someone else or a hiring request.
                headline = author_headline(data['content'])
                results.append({'url': canonical_url(author['url']), 'title': author_name, 'content': headline})
            processed.add(fingerprint)
            continue
        menu = card.locator('button[aria-label^="Open control menu for post"]')
        if not await menu.count():
            raise ValueError('Post card has no source-link menu')
        await menu.click()
        copy = page.get_by_text('Copy link to post', exact=True)
        try:
            await copy.wait_for(timeout=3000)
        except Exception as exc:
            await page.keyboard.press('Escape')
            raise ValueError(f'Post copy-link menu unavailable: {exc}') from exc
        # Capture only the URL written by this explicit Copy link action. Reading
        # the OS clipboard is unreliable when a headless tab loses focus.
        await page.evaluate('''() => {
            window.__botCopiedLink = '';
            window.__botOriginalWrite = navigator.clipboard.writeText;
            navigator.clipboard.writeText = async text => { window.__botCopiedLink = text; };
        }''')
        try:
            await copy.click()
            await page.wait_for_function('() => window.__botCopiedLink.startsWith("https://")', timeout=5000)
            copied = await page.evaluate('window.__botCopiedLink')
        finally:
            await page.evaluate('''() => {
                navigator.clipboard.writeText = window.__botOriginalWrite;
                delete window.__botOriginalWrite;
                delete window.__botCopiedLink;
            }''')
        url = canonical_url(copied)
        if urlsplit(copied).hostname == 'lnkd.in' and copied.startswith('https://lnkd.in/p/'):
            resolver = await context.new_page()
            try:
                await resolver.goto(copied, wait_until='domcontentloaded', timeout=15000)
                await resolver.wait_for_url('https://www.linkedin.com/**', timeout=10000)
                url = canonical_url(resolver.url)
            finally:
                await resolver.close()
        if url and urlsplit(url).path.startswith(('/posts/', '/feed/update/')):
            results.append({'url': url, 'title': title,
                            'content': data['content'], 'contact_name': author_name,
                            'contact_linkedin_url': canonical_url(author.get('url', ''))})
            processed.add(fingerprint)
            if len(results) >= limit:
                break
        else:
            raise ValueError(f'Post link did not resolve: {urlsplit(copied).hostname} {urlsplit(copied).path}; resolved {url}')
    return results


# Result-card text, not the name link alone. Header/profile-menu links stay out.
PEOPLE_CARDS = """els => els.flatMap(a => {
  const href = a.href || '';
  if (!/linkedin\\.com\\/in\\//i.test(href)) return [];
  if (a.closest('header, nav, footer, [role="navigation"], [role="banner"]')) return [];
  let node = a;
  let text = '';
  for (let i = 0; i < 8 && node; i++) {
    const next = (node.innerText || '').trim();
    if (next.length >= 24 && next.length <= 1200) {
      text = next;
      break;
    }
    if (next.length > 1200) break;
    text = next || text;
    node = node.parentElement;
  }
  if (!text) text = (a.getAttribute('aria-label') || a.innerText || '').trim();
  if (!text) return [];
  return [{url: href, text: text.slice(0, 2000)}];
})"""


RESULT_PROFILE_LINKS = 'main a[href*="/in/"], [role="main"] a[href*="/in/"], .search-results-container a[href*="/in/"]'


def trainer_people_budget(limit):
    """Seconds for people-result pages before the content fallback starts."""
    return 180 if int(limit or 1) >= 20 else 40


def trainer_content_budget(limit):
    """Seconds for the post-author fallback. It does not share the people-page clock."""
    return 40 if int(limit or 1) >= 20 else 25


def account_fetch_limit(limit, mode):
    """Keep the caller's trainer target. A 50-profile cap made a 60-profile search use the short clock."""
    ceiling = TRAINER_RESULT_CEILING if mode == 'trainer' else 50
    return min(max(int(limit or 1), 1), ceiling)


def _people_search_url(keywords, page_number):
    return 'https://www.linkedin.com/search/results/people/?' + urlencode({'keywords': keywords, 'page': page_number})


from shared.trainer_targets import TRAINER_RESULT_CEILING, TRAINER_SCAN_LIMIT


async def collect_trainer_profiles(page, domain, location, limit, collected=None):
    """Page through people search until the qualified target or the scan limit is met."""
    from app.clients.linkedin_people import profiles_from_text
    from app.routes.linkedin_leads import _normalize_result
    results = [] if collected is None else collected
    seen, visited = {row.get('url') for row in results}, set()
    limit = min(max(int(limit or 1), 1), TRAINER_RESULT_CEILING)
    batch = limit >= 20
    scan_limit = TRAINER_SCAN_LIMIT if batch else min(TRAINER_SCAN_LIMIT, max(limit * 4, limit))
    # LinkedIn shows about ten people per page. A full fetch can read 24 pages, then stops.
    page_cap = max(1, (scan_limit + 9) // 10) if batch else min(20, max(limit, 2))
    people_deadline = asyncio.get_running_loop().time() + trainer_people_budget(limit)

    def people_time_up():
        return asyncio.get_running_loop().time() >= people_deadline

    def profile_title(text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if not re.fullmatch(r'(?i)(?:connect|follow|message|pending)', line):
                return line[:200]
        return (lines[0] if lines else '')[:200]

    async def read_people():
        # Only the results region. A profile link in the global header is not a search hit.
        links = await page.locator(RESULT_PROFILE_LINKS).evaluate_all(PEOPLE_CARDS)
        new_urls = 0
        for item in links or []:
            url = canonical_url((item or {}).get('url', ''))
            text = (item or {}).get('text', '') or ''
            if not url or url in visited or len(visited) >= scan_limit:
                continue
            visited.add(url)
            new_urls += 1
            if url in seen or not text.strip():
                continue
            candidate = {'url': url, 'title': profile_title(text), 'content': text[:5000]}
            # This page was opened for the requested keywords. Keep a trainer card
            # when the visible headline leaves out one of those skill words.
            if _normalize_result(candidate, domain, 'trainer', require_domain=False):
                seen.add(url)
                results.append(candidate)
                if len(results) >= limit:
                    break
        return new_urls, len(links or [])

    payloads, tasks = [], []

    async def capture_response(response):
        try:
            content_type = (response.headers.get('content-type') or '')
            if response.status != 200 or 'json' not in content_type:
                return
            body = await response.text()
        except Exception:
            return
        if not isinstance(body, str):
            return
        flattened = body.replace('\\/', '/')
        markers = flattened.lower()
        if 'linkedin.com/in/' in markers and ('navigationurl' in markers or 'actiontarget' in markers):
            payloads.append(body[:2_000_000])

    def on_response(response):
        tasks.append(asyncio.create_task(capture_response(response)))

    try:
        page.on('response', on_response)
    except Exception:
        pass

    async def absorb_markup():
        """Read headlines from the search payload when the card links are not painted yet."""
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks.clear()
        blobs = list(payloads)
        payloads.clear()
        try:
            html = await page.content()
        except Exception:
            html = ''
        if isinstance(html, str) and html:
            blobs.append(html)
        added = 0
        for blob in blobs:
            if not isinstance(blob, str):
                continue
            for profile in profiles_from_text(blob):
                url = canonical_url(profile.get('url', ''))
                text = profile.get('content') or ''
                if not url or not text.strip() or url in visited or len(visited) >= scan_limit:
                    continue
                visited.add(url)
                added += 1
                if url in seen:
                    continue
                candidate = {
                    'url': url,
                    'title': (profile.get('title') or profile_title(text))[:200],
                    'content': text[:5000],
                }
                if _normalize_result(candidate, domain, 'trainer'):
                    seen.add(url)
                    results.append(candidate)
                if len(results) >= limit:
                    return added
        return added

    async def open_people_page(keywords, page_number):
        """Open one numbered people-search page. The page URL is the scan position."""
        try:
            return await page.goto(_people_search_url(keywords, page_number), wait_until='commit', timeout=12000), True
        except Exception:
            return None, False

    queries = [trainer_keywords(domain, location)]
    instructor = f'{domain} {location} instructor'.strip()
    if instructor.lower() != queries[0].lower():
        queries.append(instructor)
    try:
        page_loads = 0
        for keywords in queries:
            if len(results) >= limit or len(visited) >= scan_limit or people_time_up():
                break
            failures = 0
            for page_number in range(1, page_cap + 1):
                if len(results) >= limit or len(visited) >= scan_limit or page_loads >= page_cap or people_time_up():
                    break
                page_loads += 1
                response, opened = await open_people_page(keywords, page_number)
                if not opened:
                    # Two dead pages end this keyword so the content fallback still has time.
                    failures += 1
                    if failures >= 2:
                        break
                    continue
                failures = 0
                if response and response.status in (403, 429):
                    raise ValueError('LinkedIn limited this session. Fetching stopped.')
                try:
                    await page.locator(RESULT_PROFILE_LINKS).first.wait_for(timeout=10000)
                except Exception:
                    pass
                await require_session(page)
                markup_added = await absorb_markup()
                if len(results) >= limit:
                    return results
                new_urls, raw_count = await read_people()
                new_urls += markup_added
                if new_urls == 0 and raw_count == 0:
                    # The result list often paints after the first lookup.
                    try:
                        await page.mouse.wheel(0, 1600)
                        await page.wait_for_timeout(1200)
                    except Exception:
                        pass
                    markup_added = await absorb_markup()
                    new_urls, raw_count = await read_people()
                    new_urls += markup_added
                if new_urls == 0:
                    break
                if len(results) >= limit or len(visited) >= scan_limit:
                    return results
    except ValueError:
        # Verification and rate limits require human action, not another search.
        raise
    except Exception:
        # People layouts vary; continue with the content search below.
        if results:
            return results
    if results:
        return results
    phrases = ('"corporate trainer"', '"trainer" "I am"', '"technical trainer"',
               '"instructor"', '"freelance trainer"',
               '"training consultant"', '"trainer" "delivered"', '"trainer" "workshop"')
    content_queries = []
    for keywords in (trainer_keywords(domain, location), *(f'{domain} {location} {phrase}'.strip() for phrase in phrases)):
        if keywords and keywords not in content_queries:
            content_queries.append(keywords)
    try:
        async with asyncio.timeout(trainer_content_budget(limit)):
            for keywords in content_queries:
                url = 'https://www.linkedin.com/search/results/content/?' + urlencode({
                    'keywords': keywords, 'sortBy': '"relevance"'})
                try:
                    response = await page.goto(url, wait_until='commit', timeout=15000)
                except Exception:
                    response = None
                await page.wait_for_timeout(2000)
                if response and response.status in (403, 429):
                    raise ValueError('LinkedIn limited this session. Fetching stopped.')
                await require_session(page)
                cards = page.locator('[role="listitem"][componentkey^="update-card-focus"]')
                try:
                    await cards.first.wait_for(timeout=5000)
                except Exception:
                    await require_session(page)
                    continue
                stagnant = 0
                previous = set()
                for _ in range(6):
                    batch = await cards.evaluate_all(EXTRACT_CARDS)
                    fingerprints = {card['content'] for card in batch}
                    stagnant = stagnant + 1 if fingerprints == previous else 0
                    previous = fingerprints
                    for card in batch:
                        headline = author_headline(card['content'])
                        for link in card['links']:
                            url = canonical_url(link['url'])
                            if not url or '/in/' not in urlsplit(url).path or not link['title'].strip():
                                continue
                            item = {'url': url, 'title': link['title'].strip().split('\n')[0], 'content': headline}
                            if url not in seen and _normalize_result(item, domain, 'trainer'):
                                seen.add(url)
                                results.append(item)
                            break
                        if len(results) >= limit:
                            return results
                    if stagnant >= 2:
                        break
                    await scroll_results(page, cards)
                    await require_session(page)
    except TimeoutError:
        if results:
            return results
        raise PartialSearchError('Trainer search reached its time limit.', results)
    except Exception as exc:
        if results:
            return results
        raise PartialSearchError(str(exc) or 'Trainer search reached its time limit.', results) from exc
    return results


async def collect_client_posts(page, context, domain, location, limit):
    from app.routes.linkedin_leads import _normalize_result
    collected, processed = [], set()
    def qualified():
        distinct = {}
        for row in collected:
            if _normalize_result(row, domain, 'client'):
                distinct.setdefault(row['url'], row)
        return list(distinct.values())[:limit]
    try:
        async with asyncio.timeout(50):
            response = await page.goto(search_url(domain, 'client', location), wait_until='domcontentloaded', timeout=15000)
            if response and response.status in (403, 429):
                raise ValueError('LinkedIn limited this session.')
            await page.wait_for_timeout(2000)
            await require_session(page)
            stagnant = 0
            for _ in range(12):
                before = len(processed)
                # Inspect each loaded batch, retaining results before scrolling.
                await read_post_cards(page, context, 'client', len(collected) + 10, collected, processed)
                if len(qualified()) >= limit:
                    return qualified()
                stagnant = stagnant + 1 if len(processed) == before else 0
                if stagnant >= 2:
                    break
                await scroll_results(page, page.locator('[role="listitem"][componentkey^="update-card-focus"]'))
                await require_session(page)
    except Exception as exc:
        raise PartialSearchError(str(exc) or 'Client search reached its time limit.', qualified()) from exc
    return qualified()


async def search_linkedin_account(domain, mode, limit=20, location='', collected=None):
    if bot_option('LINKEDIN_BOT_ENABLED', 'false').lower() != 'true':
        raise ValueError('LinkedIn bot is not enabled. Connect the dedicated account and set LINKEDIN_BOT_ENABLED=true.')
    if _lock.locked():
        raise ValueError('LinkedIn bot is busy. Try again after the current fetch finishes.')
    from playwright.async_api import async_playwright
    async with _lock:
        ensure_session_not_blocked(profile_path())
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                profile_path(), headless=True, accept_downloads=False)
            page = None
            try:
                from app.clients.linkedin_session import load_session
                saved = load_session(profile_path())
                if saved:
                    await context.add_cookies(saved)
                page = await context.new_page()
                if mode == 'trainer':
                    return await collect_trainer_profiles(page, domain, location, account_fetch_limit(limit, mode), collected)
                if mode == 'client':
                    return await collect_client_posts(page, context, domain, location, min(max(limit, 1), 50))
            except Exception as exc:
                cause = exc
                partial = None
                auth_required = False
                while cause is not None:
                    if isinstance(cause, LinkedInAuthenticationRequired):
                        auth_required = True
                        block_session(profile_path())
                    if partial is None and getattr(cause, 'results', None):
                        partial = list(cause.results)
                    cause = cause.__cause__
                # Profiles collected before a deadline are a completed search.
                if partial and not auth_required:
                    return partial
                raise
            finally:
                try:
                    if page is not None:
                        await persist_session(context, page)
                finally:
                    await context.close()


async def persist_session(context, page):
    """Keep refreshed cookies instead of replaying the original login forever."""
    from app.clients.linkedin_session import save_session
    try:
        parts = urlsplit(page.url)
        if parts.hostname != 'www.linkedin.com' or not parts.path.startswith(('/feed/', '/search/')):
            return
        await require_session(page)
        cookies = await context.cookies()
        if any(cookie.get('name') == 'li_at' and cookie.get('value') for cookie in cookies):
            save_session(profile_path(), cookies)
    except Exception:
        # Do not hide results/errors or leak cookie values in exception messages.
        logger.warning('Could not refresh the saved LinkedIn session; previous snapshot retained.')
