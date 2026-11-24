"""Key-free web search engines used to find public LinkedIn trainer profiles.

Only search result pages are requested. The LinkedIn profile links found on
those pages are never opened, so LinkedIn itself is not contacted here.
"""
import asyncio
import base64
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

logger = logging.getLogger(__name__)

_USER_AGENTS = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0',
)
_MAX_BODY = 2_000_000
# Markers of a challenge, captcha or consent page. Checked only when a page has no profile links.
_BLOCK_MARKERS = (
    b'anomaly-modal', b'captcha', b'unusual traffic', b'are you a robot', b'not a robot',
    b'challenge-platform', b'cf-chl', b'verify you are human', b'/sorry/index',
    b'detected unusual', b'consent.yahoo.com', b'please enable javascript',
)
_BLOCK_STATUSES = (202, 403, 429, 503)


# ---------------------------------------------------------------- URL handling

def canonical_profile_url(url):
    """Return https://www.linkedin.com/in/<slug> for a LinkedIn profile link, else ''."""
    if not url:
        return ''
    parts = urlsplit(url.strip())
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https'):
        return ''
    if not (host == 'linkedin.com' or host.endswith('.linkedin.com')):
        return ''
    segments = [segment for segment in parts.path.split('/') if segment]
    if len(segments) < 2 or segments[0].lower() != 'in':
        return ''
    slug = unquote(segments[1]).strip()
    if not slug or not re.fullmatch(r'[\w\-.%À-ɏ]{2,100}', slug):
        return ''
    return f'https://www.linkedin.com/in/{quote(slug, safe="-_.")}'


_ACTIVITY = re.compile(r'(?:activity[-:]|urn:li:activity:|urn%3ali%3aactivity%3a)(\d{6,})(?!\d)', re.IGNORECASE)


def canonical_post_url(url):
    """Return https://www.linkedin.com/posts/... or /feed/update/... for a LinkedIn post link, else ''."""
    if not url:
        return ''
    parts = urlsplit(url.strip())
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https'):
        return ''
    if not (host == 'linkedin.com' or host.endswith('.linkedin.com')):
        return ''
    path = parts.path.rstrip('/')
    if path.startswith('/posts/') and len(path) > len('/posts/') + 3:
        return f'https://www.linkedin.com{path}'
    if path.startswith('/feed/update/') and _ACTIVITY.search(unquote(path)):
        return f'https://www.linkedin.com{path}'
    return ''


def post_key(url):
    """One key per post across /posts/ and /feed/update/ URL variants (matches client_post_identity)."""
    match = _ACTIVITY.search(unquote(urlsplit(url or '').path))
    return f'linkedin:activity:{match.group(1)}' if match else (url or '')


CANONICAL = {'profile': canonical_profile_url, 'post': canonical_post_url}


def unwrap_link(href, engine_host=''):
    """Read the real target of a result link locally. Redirect wrappers are not requested."""
    if not href:
        return ''
    href = href.strip()
    if href.startswith('//'):
        href = 'https:' + href
    elif href.startswith('/'):
        href = f'https://{engine_host}{href}' if engine_host else ''
    if not href.startswith(('http://', 'https://')):
        return ''
    parts = urlsplit(href)
    query = parse_qs(parts.query)
    # DuckDuckGo: /l/?uddg=<target>
    for key in ('uddg', 'url', 'q', 'imgurl'):
        value = (query.get(key) or [''])[0]
        if value.startswith(('http://', 'https://')):
            return value
    # Yahoo: r.search.yahoo.com/.../RU=<target>/RK=...
    match = re.search(r'/RU=([^/]+)/', parts.path)
    if match:
        target = unquote(match.group(1))
        return target if target.startswith(('http://', 'https://')) else ''
    # Bing: /ck/a?...&u=a1<base64 target>
    if parts.path.rstrip('/') == '/ck/a':
        encoded = (query.get('u') or [''])[0]
        if encoded.startswith('a1'):
            encoded = encoded[2:]
        encoded = encoded.replace('-', '+').replace('_', '/')
        encoded += '=' * ((4 - len(encoded) % 4) % 4)
        try:
            decoded = base64.b64decode(encoded).decode('utf-8', 'ignore')
        except (ValueError, UnicodeError):
            return ''
        return decoded if decoded.startswith(('http://', 'https://')) else ''
    return href


# ---------------------------------------------------------------- page parsing

def _looks_like_url_text(text):
    low = text.lower()
    return '›' in text or low.startswith(('http', 'www.', 'linkedin.com', 'in.linkedin.com')) or ' › ' in text


def _clean_title(text):
    text = ' '.join((text or '').split())
    if _looks_like_url_text(text):
        # Keep the part after a breadcrumb such as "linkedin.com › in › ravi Ravi Kumar - Trainer".
        parts = re.split(r'\s*›\s*\S+', text)
        text = parts[-1].strip() if parts else ''
        if _looks_like_url_text(text):
            return ''
    return text


class _ProfileHarvester(HTMLParser):
    """Collect every LinkedIn profile link on a results page with its nearby text.

    This does not depend on one engine's CSS classes, so it keeps working when an
    engine changes its markup. Text after a profile link is kept as its snippet
    until the next result heading or external link.
    """

    _HEADINGS = {'h1', 'h2', 'h3', 'h4'}
    _SKIP = {'script', 'style', 'noscript', 'svg', 'template'}

    def __init__(self, engine_host, kind='profile'):
        super().__init__(convert_charrefs=True)
        self.engine_host = engine_host
        self.canonical = CANONICAL[kind]
        self.rows = {}
        self.order = []
        self.links_seen = 0
        self._anchor_url = None
        self._anchor_text = []
        self._capture_url = None
        self._capture_len = 0
        self._skip_depth = 0
        self._other_anchor = None

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        # Some engines put the heading element inside the profile anchor. In
        # that layout this heading belongs to the current profile, so do not
        # clear its snippet capture before the following description.
        if tag in self._HEADINGS and not self._anchor_url:
            self._capture_url = None
        if tag != 'a':
            return
        attrs = dict(attrs)
        href = attrs.get('href') or ''
        target = unwrap_link(href, self.engine_host)
        profile = self.canonical(target)
        if profile:
            self.links_seen += 1
            if profile not in self.rows:
                self.rows[profile] = {'url': profile, 'title': '', 'snippet': ''}
                self.order.append(profile)
            self._anchor_url = profile
            self._anchor_text = []
            label = _clean_title(attrs.get('aria-label') or attrs.get('title') or '')
            if label and len(label) > len(self.rows[profile]['title']):
                self.rows[profile]['title'] = label[:300]
            self._capture_url = profile
            self._capture_len = len(self.rows[profile]['snippet'])
            return
        self._anchor_url = None
        host = (urlsplit(target).hostname or '').lower() if target else ''
        if host and self.engine_host and not host.endswith(self.engine_host.split('.', 1)[-1]):
            # Maybe a different result. Decided at the end of the link: a short
            # "Cached" or menu link does not end the current snippet.
            self._other_anchor = []

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == 'a' and self._other_anchor is not None:
            if len(' '.join(self._other_anchor)) > 25:
                self._capture_url = None  # A real result title for another site.
            self._other_anchor = None
            return
        if tag != 'a' or not self._anchor_url:
            return
        text = _clean_title(' '.join(self._anchor_text))
        row = self.rows[self._anchor_url]
        if text and len(text) > len(row['title']):
            row['title'] = text[:300]
        self._anchor_url = None
        self._anchor_text = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = ' '.join(data.split())
        if not text:
            return
        if self._anchor_url:
            # Yahoo and Bing put the breadcrumb ("in.linkedin.com › in › ravi") inside the
            # title link. Drop that piece and keep the real title next to it.
            if not _looks_like_url_text(text):
                self._anchor_text.append(text)
            return
        if self._other_anchor is not None:
            self._other_anchor.append(text)
            return
        if self._capture_url and self._capture_len < 600 and not _looks_like_url_text(text):
            row = self.rows[self._capture_url]
            row['snippet'] = f"{row['snippet']} {text}".strip()[:600]
            self._capture_len = len(row['snippet'])


def harvest_profiles(body, engine_host='', kind='profile'):
    """Return (rows, links_seen) for LinkedIn profile (or post) links on a results page."""
    if isinstance(body, bytes):
        body = body.decode('utf-8', 'ignore')
    parser = _ProfileHarvester(engine_host, kind)
    try:
        parser.feed(body)
        parser.close()
    except Exception:  # Malformed markup: keep what was read.
        pass
    rows = []
    for url in parser.order:
        row = parser.rows[url]
        title = row['title'] or url.rsplit('/', 1)[-1].replace('-', ' ')
        rows.append({'url': url, 'title': title, 'snippet': row['snippet'],
                     'content': f"{title} {row['snippet']}".strip()})
    return rows, parser.links_seen


def looks_blocked(status, body, links_seen):
    if status in _BLOCK_STATUSES:
        return True
    if links_seen:
        return False
    low = (body if isinstance(body, bytes) else body.encode('utf-8', 'ignore'))[:300_000].lower()
    return any(marker in low for marker in _BLOCK_MARKERS)


def ddg_next_form(body, endpoint):
    """Read the hidden "next page" form of DuckDuckGo html/lite pages."""
    text = body.decode('utf-8', 'ignore') if isinstance(body, bytes) else body
    for match in re.finditer(r'<form[^>]*action="[^"]*/(?:html|lite)/?"[^>]*>([\s\S]*?)</form>', text, re.I):
        form = match.group(1)
        fields = {}
        for tag in re.findall(r'<input\b[^>]*>', form, re.I):
            name = re.search(r'\bname="([^"]*)"', tag)
            value = re.search(r'\bvalue="([^"]*)"', tag)
            if name:
                fields[name.group(1)] = value.group(1) if value else ''
        if fields.get('q') and ('s' in fields or 'vqd' in fields) and fields.get('s', '1') not in ('', '0'):
            return endpoint, fields
    return None


# ---------------------------------------------------------------- engines

@dataclass(frozen=True)
class Engine:
    name: str
    label: str
    host: str
    first_url: Callable[[str], str]
    page_url: Optional[Callable[[str, int], str]] = None
    next_form: Optional[Callable[[bytes], Optional[tuple]]] = None
    max_pages: int = 3
    min_interval: float = 2.5
    browser_fallback: bool = True
    # URL parameters that limit results to the past 'week' or 'month'.
    recent: dict = field(default_factory=dict)


def _q(params):
    return urlencode(params)


def with_params(url, params):
    """Append extra query parameters to a results URL."""
    if not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


ENGINES = (
    Engine('bing', 'Bing', 'www.bing.com',
           lambda q: f'https://www.bing.com/search?{_q({"q": q, "setlang": "en", "cc": "IN"})}',
           page_url=lambda q, i: f'https://www.bing.com/search?{_q({"q": q, "setlang": "en", "cc": "IN", "first": 1 + 10 * i})}',
           recent={'week': {'filters': 'ex1:"ez2"'}, 'month': {'filters': 'ex1:"ez3"'}}),
    Engine('duckduckgo', 'DuckDuckGo', 'html.duckduckgo.com',
           lambda q: f'https://html.duckduckgo.com/html/?{_q({"q": q, "kl": "in-en"})}',
           next_form=lambda body: ddg_next_form(body, 'https://html.duckduckgo.com/html/'),
           recent={'week': {'df': 'w'}, 'month': {'df': 'm'}}),
    Engine('duckduckgo_lite', 'DuckDuckGo Lite', 'lite.duckduckgo.com',
           lambda q: f'https://lite.duckduckgo.com/lite/?{_q({"q": q, "kl": "in-en"})}',
           next_form=lambda body: ddg_next_form(body, 'https://lite.duckduckgo.com/lite/'),
           browser_fallback=False, recent={'week': {'df': 'w'}, 'month': {'df': 'm'}}),
    Engine('yahoo', 'Yahoo', 'search.yahoo.com',
           lambda q: f'https://search.yahoo.com/search?{_q({"p": q})}',
           page_url=lambda q, i: f'https://search.yahoo.com/search?{_q({"p": q, "b": 1 + 10 * i})}',
           recent={'week': {'btf': 'w'}, 'month': {'btf': 'm'}}),
    Engine('mojeek', 'Mojeek', 'www.mojeek.com',
           lambda q: f'https://www.mojeek.com/search?{_q({"q": q})}',
           page_url=lambda q, i: f'https://www.mojeek.com/search?{_q({"q": q, "s": 1 + 10 * i})}',
           browser_fallback=False),
    Engine('brave', 'Brave Search', 'search.brave.com',
           lambda q: f'https://search.brave.com/search?{_q({"q": q, "source": "web"})}',
           page_url=lambda q, i: f'https://search.brave.com/search?{_q({"q": q, "source": "web", "offset": i})}',
           min_interval=4.0, recent={'week': {'tf': 'pw'}, 'month': {'tf': 'pm'}}),
)
ENGINE_BY_NAME = {engine.name: engine for engine in ENGINES}


def enabled_engines():
    """TRAINER_FINDER_ENGINES=bing,mojeek limits the engines. Empty means all."""
    names = [name.strip().lower() for name in os.environ.get('TRAINER_FINDER_ENGINES', '').split(',') if name.strip()]
    if not names:
        return list(ENGINES)
    return [ENGINE_BY_NAME[name] for name in names if name in ENGINE_BY_NAME]


# ---------------------------------------------------------------- engine health

def _state_dir():
    configured = os.environ.get('TRAINER_FINDER_STATE_DIR') or os.environ.get('LINKEDIN_BOT_PROFILE_PATH')
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / 'linkedin-bot-profile'


class EngineHealth:
    """Remember engines that refused this server, and back off before asking again.

    Each consecutive block doubles the pause: 15, 30, 60 ... up to 360 minutes.
    """

    BASE_MINUTES = 15
    MAX_MINUTES = 360

    def __init__(self, path=None):
        self.path = Path(path) if path else _state_dir() / 'serp-engine-health.json'
        try:
            self.state = json.loads(self.path.read_text())
            if not isinstance(self.state, dict):
                self.state = {}
        except (OSError, ValueError):
            self.state = {}

    def cooling_until(self, name, now=None):
        now = now or datetime.now(timezone.utc)
        raw = (self.state.get(name) or {}).get('cool_until')
        if not raw:
            return None
        try:
            until = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return until if until > now else None

    def record_block(self, name, now=None):
        now = now or datetime.now(timezone.utc)
        entry = self.state.setdefault(name, {})
        strikes = int(entry.get('strikes') or 0) + 1
        minutes = min(self.BASE_MINUTES * 2 ** (strikes - 1), self.MAX_MINUTES)
        until = now + timedelta(minutes=minutes)
        entry.update(strikes=strikes, cool_until=until.isoformat())
        self._save()
        return until

    def record_ok(self, name):
        if name in self.state:
            self.state.pop(name)
            self._save()

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state))
        except OSError:
            logger.warning('Could not save search engine health to %s', self.path)


# ---------------------------------------------------------------- fetching

class Fetcher:
    """One HTTP client per search run (keeps engine cookies), plus an optional headless browser.

    The browser is a plain Chromium with no LinkedIn profile or cookies. It is
    only used to render a results page that refused the plain HTTP request.
    """

    def __init__(self, use_browser=True, browser_page_limit=40):
        self.user_agent = random.choice(_USER_AGENTS)
        self.use_browser = use_browser
        self.browser_page_limit = browser_page_limit
        self.browser_pages = 0
        self._client = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._browser_failed = False
        self._browser_lock = asyncio.Lock()

    async def http(self, method, url, data=None):
        """Return (status, body). Network errors return (0, b'')."""
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=6.0, read=12.0, write=6.0, pool=6.0),
                follow_redirects=True, max_redirects=3,
                headers={'User-Agent': self.user_agent,
                         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                         'Accept-Language': 'en-IN,en;q=0.9'})
        try:
            response = await self._client.request(method, url, data=data)
        except httpx.HTTPError:
            return 0, b''
        return response.status_code, response.content[:_MAX_BODY]

    @property
    def browser_available(self):
        return self.use_browser and not self._browser_failed and self.browser_pages < self.browser_page_limit

    async def browser(self, url):
        """Render a results page in headless Chromium. Return (status, body) or (0, b'')."""
        if not self.browser_available:
            return 0, b''
        async with self._browser_lock:
            try:
                if self._context is None:
                    from playwright.async_api import async_playwright
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(
                        headless=True, args=['--disable-blink-features=AutomationControlled'])
                    self._context = await self._browser.new_context(
                        user_agent=self.user_agent, locale='en-IN', viewport={'width': 1366, 'height': 900})
                self.browser_pages += 1
                page = await self._context.new_page()
                try:
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=20_000)
                    await page.wait_for_timeout(1_500)
                    body = (await page.content()).encode('utf-8', 'ignore')
                    return (response.status if response else 200), body[:_MAX_BODY]
                finally:
                    await page.close()
            except Exception as exc:
                logger.warning('Headless search browser failed: %s', type(exc).__name__)
                if self._context is None:
                    self._browser_failed = True
                return 0, b''

    async def close(self):
        for closer in (
            lambda: self._client.aclose() if self._client else None,
            lambda: self._context.close() if self._context else None,
            lambda: self._browser.close() if self._browser else None,
            lambda: self._playwright.stop() if self._playwright else None,
        ):
            try:
                awaitable = closer()
                if awaitable is not None:
                    await awaitable
            except Exception:
                pass


class Pacer:
    """Keep a minimum, slightly random gap between requests to the same engine."""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._last = 0.0

    async def wait(self):
        gap = self.min_interval * random.uniform(1.0, 1.6)
        delay = self._last + gap - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._last = time.monotonic()


@dataclass
class PageResult:
    status: str  # ok | empty | blocked | error
    rows: list
    links_seen: int = 0
    via_browser: bool = False
    body: bytes = b''
    reason: str = ''


async def fetch_results_page(engine, fetcher, method, url, data=None, kind='profile'):
    """Fetch one results page. A refused page is retried once in the headless browser."""
    status, body = await fetcher.http(method, url, data)
    rows, links = harvest_profiles(body, engine.host, kind) if body else ([], 0)
    if status and status < 400 and not looks_blocked(status, body, links):
        return PageResult('ok' if links else 'empty', rows, links, body=body)
    refused = bool(status) and looks_blocked(status, body, links)
    if engine.browser_fallback and method == 'GET' and fetcher.browser_available:
        b_status, b_body = await fetcher.browser(url)
        if b_body:
            b_rows, b_links = harvest_profiles(b_body, engine.host, kind)
            if b_status < 400 and not looks_blocked(b_status, b_body, b_links):
                return PageResult('ok' if b_links else 'empty', b_rows, b_links, via_browser=True, body=b_body)
            refused = refused or looks_blocked(b_status, b_body, b_links)
    if refused:
        return PageResult('blocked', [], reason=f'{engine.label} returned HTTP {status or b_status}.')
    return PageResult('error', [], reason=(f'{engine.label} returned HTTP {status}.' if status else
                                           f'{engine.label} request failed before receiving an HTTP response.'))
