"""Identify one LinkedIn post across permalink and tracking URL variants."""
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from pymongo.errors import DuplicateKeyError


def post_identity(url):
    from app.clients.linkedin_browser import canonical_url
    normalized = canonical_url(url)
    if not normalized:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
        if parts.scheme == 'https' and (host == 'linkedin.com' or host.endswith('.linkedin.com')) and parts.path.startswith('/pulse/'):
            normalized = urlunsplit(('https', 'www.linkedin.com', parts.path.rstrip('/'), '', ''))
        else:
            raise ValueError('A supported LinkedIn post URL is required')
    path = unquote(urlsplit(normalized).path)
    activity = re.search(r'(?:activity-|urn:li:activity:)(\d{6,})(?!\d)', path)
    return 'linkedin:activity:' + activity[1] if activity else normalized


def post_lookup(url):
    key = post_identity(url)
    if key.startswith('linkedin:activity:'):
        activity = re.escape(key.rsplit(':', 1)[-1])
        pattern = r'^https://(?:[a-z]+\.)?linkedin\.com/(?:posts/[^?]*activity-|feed/update/urn(?::|%3a)li(?::|%3a)activity(?::|%3a))' + activity + r'(?!\d)'
    else:
        path = re.escape(urlsplit(key).path.rstrip('/'))
        pattern = r'^https://(?:[a-z]+\.)?linkedin\.com' + path + r'/?(?:[?#].*)?$'
    return {'$or': [{'post_key': key}, {'source_url': {'$regex': pattern, '$options': 'i'}}]}


async def save_client_post(lead, db, now):
    from app.routes.linkedin_leads import _contact_update_fields
    key = post_identity(lead['source_url'])
    updates = {**_contact_update_fields(lead), 'updated_at': now, 'post_key': key}
    matches = lead.get('matched_domains') or ([lead['domain']] if lead.get('domain') and lead['domain'] != 'Unclassified' else [])
    initial = {name: value for name, value in lead.items() if name not in updates and name != 'matched_domains'}
    mutation = {'$set': updates, '$setOnInsert': {**initial, 'created_at': now},
                '$addToSet': {'matched_domains': {'$each': matches}}}
    try:
        result = await db['client_leads'].update_one(post_lookup(lead['source_url']), mutation, upsert=True)
    except DuplicateKeyError:
        # Another collector saved this post after our lookup. Update its record.
        result = await db['client_leads'].update_one({'post_key': key}, mutation)
    return result.upserted_id is not None
