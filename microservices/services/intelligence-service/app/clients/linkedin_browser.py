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


# Walk up from the profile link. closest() used to stop on the name row, so
# the headline never reached the matcher and every real trainer was rejected.
PEOPLE_CARDS = """els => els.flatMap(a => {
  const href = a.href || '';
  if (!/\\/in\\//i.test(href)) return [];
  const layers = [];
  let node = a;
  let chosen = '';
  const profileCount = root => {
    const urls = new Set();
    root.querySelectorAll('a[href*="/in/"]').forEach(link => {
      const value = String(link.href || '').split('?')[0].replace(/\\/$/, '').toLowerCase();
      if (value.includes('/in/')) urls.add(value);
    });
    return urls.size;
  };
  for (let depth = 0; depth < 10 && node; depth += 1) {
    if (node.matches && node.matches('main, [role="main"], body, header, nav')) break;
    const text = String(node.innerText || '').replace(/\\u00a0/g, ' ').trim();
    if (text) layers.push(text.slice(0, 4000));
    const lines = text ? text.split(/\\n/).map(line => line.trim()).filter(Boolean) : [];
    const actions = (text.match(/(^|\\n)\\s*(Connect|Follow|Message|Pending)\\s*(?=\\n|$)/gi) || []).length;
    const onePerson = profileCount(node) <= 4 && lines.length <= 40 && text.length <= 2500 && actions <= 3;
    if (text && onePerson) chosen = text.slice(0, 4000);
    else if (chosen) break;
    node = node.parentElement;
  }
  if (!chosen && !layers.length) return [];
  return [{url: href, text: chosen, layers}];
})"""


def select_profile_text(layers):
    """Keep the largest block that is still one result card, not the whole page."""
    best = ''
    for raw in layers or []:
        text = str(raw or '').strip()
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        actions = len(re.findall(r'(?im)^(?:connect|follow|message|pending)$', text))
        if len(text) > 1800 or len(lines) > 18 or actions > 3:
            break
        best = text
    return best[:4000]


def _single_line(text):
    return len([line for line in str(text or '').splitlines() if line.strip()]) <= 1


def profiles_from_html(html):
    """Read profile URLs from the page body when the result anchors are not queryable."""
    if not isinstance(html, str) or '/in/' not in html:
        return []
    sample = html[:500_000]
    found, seen = [], set()
    pattern = re.compile(
        r'https://(?:[\w.-]+\.)?linkedin\.com/in/[A-Za-z0-9\-_%]{3,100}|/in/[A-Za-z0-9\-_%]{3,100}',
        re.I,
    )
    for match in pattern.finditer(sample):
        raw = match.group(0)
        if raw.startswith('/'):
            prefix = sample[max(0, match.start() - 80):match.start()]
            host = re.search(r'https?://([^/\s"\'<>]+)$', prefix, re.I)
            if host:
                hostname = host.group(1).split(':')[0].lower()
                if hostname != 'linkedin.com' and not hostname.endswith('.linkedin.com'):
                    continue
            raw = 'https://www.linkedin.com' + raw
        url = canonical_url(raw)
        if not url or url in seen:
            continue
        window = sample[max(0, match.start() - 500):match.end() + 900]
        text = re.sub(r'<[^>]+>', '\n', window)
        text = re.sub(r'&(?:amp|nbsp);', ' ', text, flags=re.I)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{2,}', '\n', text).strip()
        seen.add(url)
        found.append({'url': url, 'text': text[:4000]})
        if len(found) >= 30:
            break
    return found


def _people_search_url(keywords, page_number):
    return 'https://www.linkedin.com/search/results/people/?' + urlencode({'keywords': keywords, 'page': page_number})


from shared.trainer_targets import TRAINER_RESULT_TARGET, TRAINER_SCAN_LIMIT


async def collect_trainer_profiles(page, domain, location, limit, collected=None):
    """Page through people search until the qualified target or the scan limit is met."""
    from app.routes.linkedin_leads import _normalize_result
    results = [] if collected is None else collected
    seen, visited = {row.get('url') for row in results}, set()
    limit = min(max(int(limit or 1), 1), TRAINER_RESULT_TARGET)
    scan_limit = TRAINER_SCAN_LIMIT if limit >= TRAINER_RESULT_TARGET else min(TRAINER_SCAN_LIMIT, max(limit * 4, limit))
    # LinkedIn shows about ten people per page, so 200 profiles is 20 pages.
    page_cap = 20 if limit >= TRAINER_RESULT_TARGET else min(20, max(limit, 2))
    # A 20-profile hourly run needs the same page budget as a 50-profile search.
    # Sixty-five seconds expired while the result list was still painting.
    deadline = asyncio.get_running_loop().time() + (180 if limit >= 20 else 65)

    def timed_out():
        return asyncio.get_running_loop().time() >= deadline

    def profile_title(text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if not re.fullmatch(r'(?i)(?:connect|follow|message|pending)', line):
                return line[:200]
        return (lines[0] if lines else '')[:200]

    async def page_html():
        try:
            return await page.content()
        except Exception:
            return ''

    async def read_people():
        # Result links live in main. The header profile link appears first and
        # used to end the wait before any trainer card existed.
        links = await page.locator('main a[href*="/in/"], [role="main"] a[href*="/in/"]').evaluate_all(PEOPLE_CARDS)
        if not links:
            links = await page.locator('a[href*="/in/"]').evaluate_all(PEOPLE_CARDS)
        prepared = []
        for item in links or []:
            url = canonical_url((item or {}).get('url', ''))
            text = (item or {}).get('text') or select_profile_text((item or {}).get('layers')) or ''
            prepared.append((url, text))
        if not prepared or all(_single_line(text) for _url, text in prepared):
            html_rows = {row['url']: row['text'] for row in profiles_from_html(await page_html())}
            if not prepared:
                prepared = [(url, text) for url, text in html_rows.items()]
            else:
                prepared = [
                    (url, html_rows.get(url, text) if _single_line(text) else text)
                    for url, text in prepared
                ]
        new_urls = 0
        for url, text in prepared:
            if not url or url in visited or len(visited) >= scan_limit:
                continue
            visited.add(url)
            new_urls += 1
            if url in seen or not str(text or '').strip():
                continue
            candidate = {'url': url, 'title': profile_title(text), 'content': text[:5000]}
            # The save path uses this same check, so rejected cards are not reported as found.
            if _normalize_result(candidate, domain, 'trainer'):
                seen.add(url)
                results.append(candidate)
                if len(results) >= limit:
                    break
        return new_urls, len(prepared)

    async def open_people_page(keywords, page_number):
        """Open one numbered people-search page. The page URL is the scan position."""
        # The first paint is the slow one. Later pages should not each consume
        # the whole search budget when LinkedIn never answers.
        timeout = 20000 if page_number == 1 else 12000
        try:
            return await page.goto(
                _people_search_url(keywords, page_number), wait_until='domcontentloaded', timeout=timeout), True
        except Exception:
            return None, False

    queries = [trainer_keywords(domain, location)]
    instructor = f'{domain} {location} instructor'.strip()
    if instructor.lower() != queries[0].lower():
        queries.append(instructor)
    try:
        page_loads = 0
        failed_opens = 0
        plain_pages = 0
        stop_people = False
        for keywords in queries:
            if len(results) >= limit or len(visited) >= scan_limit or timed_out() or stop_people:
                break
            for page_number in range(1, page_cap + 1):
                if (len(results) >= limit or len(visited) >= scan_limit or page_loads >= page_cap
                        or timed_out() or failed_opens >= 2 or plain_pages >= 3):
                    stop_people = failed_opens >= 2 or plain_pages >= 3
                    break
                page_loads += 1
                response, opened = await open_people_page(keywords, page_number)
                if not opened:
                    # Two missed pages means this query is not loading. Stop and
                    # use the content fallback while time is still left.
                    failed_opens += 1
                    continue
                failed_opens = 0
                if response and response.status in (403, 429):
                    raise ValueError('LinkedIn limited this session. Fetching stopped.')
                try:
                    await page.locator('main a[href*="/in/"], [role="main"] a[href*="/in/"]').first.wait_for(timeout=10000)
                except Exception:
                    pass
                await require_session(page)
                qualified_before = len(results)
                new_urls, raw_count = await read_people()
                if len(results) == qualified_before:
                    # The result list often paints after the first lookup.
                    # Keep the first read's count: a second pass sees those
                    # links as already visited and would look like an empty page.
                    try:
                        await page.mouse.wheel(0, 1600)
                        await page.wait_for_timeout(800)
                    except Exception:
                        pass
                    more_urls, more_raw = await read_people()
                    new_urls += more_urls
                    raw_count = max(raw_count, more_raw)
                if new_urls == 0:
                    break
                if len(results) == qualified_before:
                    plain_pages += 1
                else:
                    plain_pages = 0
                if plain_pages >= 3:
                    stop_people = True
                    break
                if len(results) >= limit or len(visited) >= scan_limit:
                    return results
    except ValueError:
        # Verification and rate limits require human action, not another search.
        raise
    except TimeoutError:
        if results:
            return results
        raise PartialSearchError('Trainer search reached its time limit.', results)
    except Exception:
        # People layouts vary; continue with the content search below.
        if results:
            return results
    if results:
        return results
    if timed_out():
        raise PartialSearchError('Trainer search reached its time limit.', results)
    phrases = ('"corporate trainer"', '"trainer" "I am"', '"technical trainer"',
               '"instructor"', '"freelance trainer"',
               '"training consultant"', '"trainer" "delivered"', '"trainer" "workshop"')
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining < 8:
        return results
    try:
        async with asyncio.timeout(min(40, remaining)):
            for phrase in phrases:
                url = 'https://www.linkedin.com/search/results/content/?' + urlencode({
                    'keywords': f'{domain} {location} {phrase}'.strip(), 'sortBy': '"relevance"'})
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
                            if not url or '/in/' not in urlsplit(url).path:
                                continue
                            title = str(link.get('title') or '').strip().split('\n')[0]
                            if not title:
                                title = profile_title(headline)
                            if not title:
                                continue
                            item = {'url': url, 'title': title, 'content': headline}
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
                    return await collect_trainer_profiles(page, domain, location, min(max(limit, 1), 50), collected)
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
