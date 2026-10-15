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
    matches = list(_NAV_URL.finditer(text))
    rows, seen, previous_end = [], set(), 0
    for index, match in enumerate(matches):
        url = match.group(1).split('?', 1)[0].rstrip('/')
        next_start = matches[index + 1].start() if index + 1 < len(matches) else -1
        if url in seen:
            previous_end = match.end()
            continue
        # Keep the headline that belongs to this result. The next profile's
        # title often follows the URL, so do not read past the next result.
        after = match.end() + 220 if next_start < 0 else min(match.end() + 220, next_start)
        window = text[max(previous_end, match.start() - 700):after]
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
