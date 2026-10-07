"""Bounded public search feed lookup; no API key or login required."""
from xml.etree import ElementTree
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

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


def parse_html(content, limit):
    parser = _BingLinks(); parser.feed(content.decode('utf-8', 'ignore'))
    results, seen = [], set()
    for url, title in parser.links:
        parts = urlsplit(url); host = (parts.hostname or '').lower()
        if not (parts.scheme in ('http', 'https') and any(host == d or host.endswith('.' + d) for d in ('linkedin.com', 'naukri.com'))):
            continue
        clean = urlunsplit(('https', 'www.linkedin.com' if host.endswith('linkedin.com') else parts.netloc, parts.path.rstrip('/'), '', ''))
        if clean in seen or not parts.path.startswith(('/in/', '/posts/', '/feed/update/')): continue
        seen.add(clean); results.append({'url': clean, 'title': title, 'content': title})
        if len(results) >= limit: break
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
        url = (item.findtext('link') or '').strip()
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
        if parts.scheme not in ('http', 'https') or not any(
            host == domain or host.endswith('.' + domain)
            for domain in ('linkedin.com', 'naukri.com')
        ):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
        if url in seen:
            continue
        seen.add(url)
        results.append({'url': url, 'title': item.findtext('title') or '',
                        'content': item.findtext('description') or ''})
        if len(results) >= limit:
            break
    return results


async def search_public(query, limit=10):
    # Fixed destination: result URLs are never fetched or used for redirects.
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        async with client.stream('GET', 'https://www.bing.com/search',
                                 params={'q': query, 'format': 'rss'}) as response:
            if response.status_code != 200:
                raise ValueError('Public search is temporarily unavailable or rate limited')
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1_000_000:
                    raise ValueError('Public search response is too large')
    parsed = parse_results(bytes(content), min(max(limit, 1), 20))
    if parsed:
        return parsed
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = await client.get('https://www.bing.com/search', params={'q': query})
    if response.status_code == 200:
        return parse_html(response.content, min(max(limit, 1), 20))
    return []
