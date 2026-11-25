"""Read trainer profiles from LinkedIn search markup and result JSON.

People-search cards are often painted inside a shadow tree, or only after a
network payload arrives. The visible anchors can be missing while the result
JSON is already on the page. This parser only accepts profile URLs that
LinkedIn labels as search navigation targets, then keeps the nearby headline
text so domain matching still has something to read.
"""
import json
import re

_NAV_URL = re.compile(
    r'"(?:navigationUrl|actionTarget)"\s*:\s*"(https://(?:[\w.-]+\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+)',
    re.IGNORECASE,
)
_TEXT = re.compile(r'"text"\s*:\s*"((?:\\.|[^"\\]){1,220})"')
_NOISE = re.compile(r'(?i)^(?:connect|follow|message|pending|search|people|\d+(?:st|nd|rd|th)\+?)$')


def _prepare(raw):
    return (
        str(raw or '')
        .replace('\\/', '/')
        .replace('\\u002F', '/')
        .replace('\\u002f', '/')
    )


def _unescape(value):
    try:
        return json.loads(f'"{value}"')
    except (json.JSONDecodeError, ValueError):
        return value.replace('\\n', ' ').replace('\\"', '"').strip()


def profiles_from_text(raw, limit=25):
    """Return {url, title, content} rows from one search document or payload."""
    text = _prepare(raw)
    lowered = text.lower()
    if 'linkedin.com/in/' not in lowered or ('"navigationurl"' not in lowered and '"actiontarget"' not in lowered):
        return []
    decoder = json.JSONDecoder()
    parsed_rows, parsed_seen = [], set()
    index = 0
    while index < len(text):
        start = text.find('{', index)
        if start < 0:
            break
        try:
            root, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = max(end, start + 1)
        stack = [root]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item[:100])
                continue
            if not isinstance(item, dict):
                continue
            url = item.get('navigationUrl') or item.get('actionTarget')
            public_id = str(item.get('publicIdentifier') or '').lower()
            title = item.get('title')
            title = title.get('text', '') if isinstance(title, dict) else str(title or '')
            subtitle = item.get('primarySubtitle') or item.get('headline') or ''
            subtitle = subtitle.get('text', '') if isinstance(subtitle, dict) else str(subtitle)
            summary = item.get('summary') or item.get('secondarySubtitle') or ''
            summary = summary.get('text', '') if isinstance(summary, dict) else str(summary)
            content = '\n'.join(part.strip() for part in (title, subtitle, summary) if part and part.strip())
            if (isinstance(url, str) and '/in/' in url and public_id != 'me' and content
                    and url not in parsed_seen):
                parsed_seen.add(url)
                parsed_rows.append({'url': url.split('?', 1)[0].rstrip('/'), 'title': title.strip(), 'content': content[:5000]})
                if len(parsed_rows) >= limit:
                    return parsed_rows
            stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
    if parsed_rows:
        return parsed_rows
    matches = list(_NAV_URL.finditer(text))
    rows, seen, previous_end = [], set(), 0
    for index, match in enumerate(matches):
        url = match.group(1).split('?', 1)[0].rstrip('/')
        next_start = matches[index + 1].start() if index + 1 < len(matches) else -1
        if url in seen:
            previous_end = match.end()
            continue
        # Search payloads put the title and headline next to each navigation URL.
        # Start at this result's title so the previous card's details cannot
        # make a different profile look like a skill match.
        title_start = text.rfind('"title"', previous_end, match.start())
        start = title_start if title_start >= 0 else max(previous_end, match.start() - 700)
        after = match.end() + 220 if next_start < 0 else min(match.end() + 220, next_start)
        window = text[start:after]
        if re.search(r'"publicIdentifier"\s*:\s*"me"', window, re.IGNORECASE):
            continue
        previous_end = match.end()
        parts = []
        for found in _TEXT.finditer(window):
            value = _unescape(found.group(1)).strip()
            if not value or _NOISE.fullmatch(value) or value in parts:
                continue
            parts.append(value)
            if len(parts) == 6:
                break
        if len(parts) < 2:
            # A bare profile URL without a headline is not a result card.
            continue
        seen.add(url)
        rows.append({
            'url': url,
            'title': parts[0][:200],
            'content': '\n'.join(parts)[:5000],
        })
        if len(rows) >= limit:
            break
    return rows
