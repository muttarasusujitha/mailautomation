"""Bounded public web search. No API key, and result links are never fetched."""
import base64
from xml.etree import ElementTree
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx


class _BingLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self._href = ''
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self._href = dict(attrs).get('href', '')
    def handle_endtag(self, tag):
        if tag == 'a': self._href = ''
    def handle_data(self, data):
        if self._href and data.strip(): self.links.append((self._href, data.strip()))


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
    clean = urlunsplit(('https', 'www.linkedin.com' if host.endswith('linkedin.com') else parts.netloc, parts.path.rstrip('/'), '', ''))
    if clean in seen:
        return False
    seen.add(clean)
    results.append({'url': clean, 'title': title, 'content': content or title})
    return len(results) >= limit


def parse_html(content, limit):
    parser = _BingLinks()
    parser.feed(content.decode('utf-8', 'ignore'))
    results, seen = [], set()
    for url, title in parser.links:
        if _keep_result(url, title, limit, results, seen):
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
