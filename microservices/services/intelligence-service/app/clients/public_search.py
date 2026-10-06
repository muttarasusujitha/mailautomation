"""Bounded public web search. No API key, and result links are never fetched."""
import base64
import re
from xml.etree import ElementTree
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import httpx

_BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'


class _BingLinks(HTMLParser):
    """Read the heading link and the caption under it. Result links are not opened."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = ''
        self._capture = None
        self._block = None
        self._depth = 0
        self._in_h2 = False

    def _close_block(self):
        if not self._block:
            return
        title = ' '.join(self._block['title']).strip()
        snippet = ' '.join(self._block['snippet']).strip()
        if self._block['href'] and title:
            self.links.append((self._block['href'], title, snippet))
        self._block = None
        self._href = ''
        self._capture = None
        self._depth = 0
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if tag == 'li' and 'b_algo' in classes:
            self._close_block()
            self._block = {'href': '', 'title': [], 'snippet': []}
            self._depth = 1
            self._in_h2 = False
            return
        if self._block is not None and tag == 'li':
            self._depth += 1
        if self._block is not None and tag == 'h2':
            self._in_h2 = True
        if tag == 'a':
            href = attrs.get('href', '')
            if self._block is None:
                self._href = href
            elif self._in_h2 and not self._block['href']:
                self._block['href'] = href
                self._capture = 'title'
        if self._block is not None and self._block['href'] and (
            tag == 'p' or 'b_caption' in classes or any(name.startswith('b_lineclamp') for name in classes)
        ):
            self._capture = 'snippet'

    def handle_endtag(self, tag):
        if tag == 'a' and self._block is None:
            self._href = ''
        elif tag == 'a' and self._capture == 'title':
            self._capture = None
        elif tag == 'h2':
            self._in_h2 = False
        elif tag == 'p' and self._capture == 'snippet':
            self._capture = None
        elif tag == 'li' and self._block is not None:
            self._depth -= 1
            if self._depth <= 0:
                self._close_block()

    def handle_data(self, data):
        text = ' '.join(data.split())
        if not text:
            return
        if self._block is not None:
            if self._capture == 'title':
                self._block['title'].append(text)
            elif self._capture == 'snippet':
                self._block['snippet'].append(text)
            return
        if self._href:
            self.links.append((self._href, text, ''))


def unwrap_result_url(url):
    """Read a result target locally. Wrapper and redirect URLs are not requested."""
    if url.startswith('//'):
        url = 'https:' + url
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    embedded = (query.get('uddg') or [''])[0]
    if embedded:
        target = unquote(embedded)
        return target if target.startswith(('http://', 'https://')) else ''
    if parts.path.rstrip('/') != '/ck/a':
        return url
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


class _DdgLinks(HTMLParser):
    """Read a public results page. The redirect URL around each result is not opened."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._href = ''
        self._kind = ''
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if 'result__a' in classes:
            self._kind = 'title'
            self._href = attrs.get('href', '')
            self._buf = []
        elif 'result__snippet' in classes:
            self._kind = 'snippet'
            self._buf = []
        else:
            self._kind = ''

    def handle_endtag(self, tag):
        if tag != 'a' or not self._kind:
            return
        text = ' '.join(''.join(self._buf).split())
        if self._kind == 'title' and self._href and text:
            self.rows.append({'href': self._href, 'title': text, 'snippet': ''})
        elif self._kind == 'snippet' and self.rows:
            self.rows[-1]['snippet'] = text
        self._kind = ''
        self._buf = []

    def handle_data(self, data):
        if self._kind:
            self._buf.append(data)


def parse_ddg(content, limit):
    parser = _DdgLinks()
    parser.feed(content.decode('utf-8', 'ignore'))
    results, seen = [], set()
    for row in parser.rows:
        if _keep_result(row['href'], row['title'], limit, results, seen, row['snippet'] or row['title']):
            break
    return results


def _ddg_next_fields(content):
    text = content.decode('utf-8', 'ignore')
    for match in re.finditer(r'<form action="/html/" method="post">([\s\S]*?)</form>', text):
        form = match.group(1)
        if 'name="vqd"' not in form:
            continue
        fields = {}
        for tag in re.findall(r'<input\b[^>]*>', form, re.I):
            name = re.search(r'\bname="([^"]*)"', tag)
            value = re.search(r'\bvalue="([^"]*)"', tag)
            if name:
                fields[name.group(1)] = value.group(1) if value else ''
        if fields.get('q') and fields.get('vqd'):
            return fields
    return None


def _ddg_challenged(response):
    return response.status_code == 202 or b'anomaly-modal' in response.content


def _keep_result(url, title, limit, results, seen, content=None):
    url = unwrap_result_url(url)
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https') or not any(host == domain or host.endswith('.' + domain) for domain in ('linkedin.com', 'naukri.com')):
        return False
    if host.endswith('linkedin.com') and not parts.path.startswith(('/in/', '/posts/', '/feed/update/')):
        return False
    if host.endswith('naukri.com') and not parts.path.strip('/'):
        return False
    clean = urlunsplit(('https', 'www.linkedin.com' if host.endswith('linkedin.com') else parts.netloc, parts.path.rstrip('/'), '', ''))
    if clean in seen:
        return False
    seen.add(clean)
    results.append({'url': clean, 'title': title, 'content': content or title})
    return len(results) >= limit


def parse_html(content, limit):
    parser = _BingLinks()
    parser.feed(content.decode('utf-8', 'ignore'))
    parser._close_block()
    results, seen = [], set()
    for url, title, snippet in parser.links:
        if _keep_result(url, title, limit, results, seen, snippet or title):
            break
    return results


def parse_results(content, limit):
    if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Unsupported search feed')
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError('Public search is unavailable; please try again later') from exc
    if root.tag != 'rss':
        raise ValueError('Public search did not return a search feed')
    results, seen = [], set()
    for item in root.findall('./channel/item'):
        title = item.findtext('title') or ''
        description = item.findtext('description') or title
        if _keep_result((item.findtext('link') or '').strip(), title, limit, results, seen, description):
            break
    return results


_PAGE_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
_HEADERS = {'User-Agent': _BROWSER, 'Accept-Language': 'en-US,en;q=0.9'}


async def _fetch(method, url, retries=1, **kwargs):
    """One short request, then one retry. A timeout returns no response and does not raise."""
    timed_out = False
    for _ in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=_PAGE_TIMEOUT, follow_redirects=False, headers=_HEADERS) as client:
                return await client.request(method, url, **kwargs), False
        except httpx.TimeoutException:
            timed_out = True
        except httpx.HTTPError:
            return None, False
    return None, timed_out


async def _search_page(query, limit, first):
    response, timed_out = await _fetch(
        'GET', 'https://www.bing.com/search', params={'q': query, 'count': min(limit, 20), 'first': first})
    if timed_out or response is None or response.status_code != 200:
        raise ValueError('Public search is temporarily unavailable or rate limited')
    if len(response.content) > 1_000_000:
        raise ValueError('Public search response is too large')
    return parse_html(response.content, limit)


async def _read_ddg_pages(response, limit, found, seen):
    """Page a results response until no new profile links appear. A challenge is not solved."""
    challenged = False
    timed_out = False
    pages = 0
    while pages < 6 and response is not None and len(found) < limit:
        pages += 1
        if _ddg_challenged(response):
            challenged = True
            break
        if response.status_code != 200 or len(response.content) > 1_000_000:
            break
        page = parse_ddg(response.content, limit - len(found))
        added = [row for row in page if row['url'] not in seen]
        if not added:
            break
        seen.update(row['url'] for row in added)
        found.extend(added)
        fields = _ddg_next_fields(response.content)
        if not fields or len(found) >= limit:
            break
        response, timed_out = await _fetch('POST', 'https://html.duckduckgo.com/html/', data=fields)
        if timed_out or response is None:
            break
    return challenged, timed_out


async def _search_ddg(query, limit, found=None, seen=None, warm=True):
    """Read profile links from a public results page. A challenge page is not solved."""
    found = found if found is not None else []
    seen = seen if seen is not None else set()
    if warm:
        await _fetch('GET', 'https://duckduckgo.com/', retries=0)
    response, timed_out = await _fetch('GET', 'https://html.duckduckgo.com/html/', params={'q': query, 'kl': 'in-en'})
    if timed_out or response is None:
        return found, False
    challenged, _timed_out = await _read_ddg_pages(response, limit, found, seen)
    return found, challenged


async def _search_bing(query, limit):
    found, seen = [], set()
    first = 1
    while len(found) < limit and first <= 41:
        try:
            page = await _search_page(query, limit - len(found), first)
        except ValueError:
            break
        added = [row for row in page if row['url'] not in seen]
        if not added:
            break
        seen.update(row['url'] for row in added)
        found.extend(added)
        first += 20
    return found


async def search_public(query, limit=10):
    """Read a public results page, then the next page only while new profile links appear."""
    limit = min(max(int(limit or 1), 1), 60)
    found, challenged = await _search_ddg(query, limit)
    if found or challenged:
        return found[:limit]
    return (await _search_bing(query, limit))[:limit]


async def search_public_many(queries, limit=50):
    """Keep reading result pages until the route minimum is filled or the connection stops answering."""
    limit = min(max(int(limit or 1), 1), 60)
    found, seen = [], set()
    challenges = 0
    timeouts = 0
    attempts = 0
    await _fetch('GET', 'https://duckduckgo.com/', retries=0)
    for query in queries:
        if len(found) >= limit or challenges >= 8 or timeouts >= 2:
            break
        attempts += 1
        before = len(found)
        response, timed_out = await _fetch('GET', 'https://html.duckduckgo.com/html/', params={'q': query, 'kl': 'in-en'})
        if timed_out or response is None:
            if timed_out:
                timeouts += 1
            else:
                challenges += 1
                timeouts = 0
            continue
        challenged, page_timeout = await _read_ddg_pages(response, limit, found, seen)
        if page_timeout:
            timeouts += 1
        elif challenged and len(found) == before:
            challenges += 1
            timeouts = 0
        elif len(found) > before:
            challenges = 0
            timeouts = 0
        else:
            timeouts = 0
    if not found and timeouts < 2 and challenges < 3 and queries:
        found.extend(await _search_bing(queries[0], limit))
    return found[:limit], attempts
