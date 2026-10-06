"""Bounded public web search. No API key, and result links are never fetched."""
import base64
from xml.etree import ElementTree
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx


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
    """Read a Bing result target locally. The wrapper itself is not requested."""
    parts = urlsplit(url)
    if parts.path.rstrip('/') != '/ck/a':
        return url
    encoded = (parse_qs(parts.query).get('u') or [''])[0]
    if encoded.startswith('a1'):
        encoded = encoded[2:]
    encoded = encoded.replace('-', '+').replace('_', '/')
    encoded += '=' * ((4 - len(encoded) % 4) % 4)
    try:
        decoded = base64.b64decode(encoded).decode('utf-8', 'ignore')
    except (ValueError, UnicodeError):
        return ''
    return decoded if decoded.startswith(('http://', 'https://')) else ''


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


async def _search_page(client, query, limit, first):
    response = await client.get('https://www.bing.com/search', params={'q': query, 'count': min(limit, 20), 'first': first})
    if response.status_code != 200:
        raise ValueError('Public search is temporarily unavailable or rate limited')
    if len(response.content) > 1_000_000:
        raise ValueError('Public search response is too large')
    return parse_html(response.content, limit)


async def search_public(query, limit=10):
    """One web search, then the next page only while new profile links are returned."""
    limit = min(max(int(limit or 1), 1), 60)
    headers = {'User-Agent': 'Mozilla/5.0'}
    found, seen = [], set()
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers=headers) as client:
        first = 1
        while len(found) < limit and first <= 41:
            page = await _search_page(client, query, limit - len(found), first)
            added = [row for row in page if row['url'] not in seen]
            if not added:
                break
            seen.update(row['url'] for row in added)
            found.extend(added)
            first += 20
    return found[:limit]
