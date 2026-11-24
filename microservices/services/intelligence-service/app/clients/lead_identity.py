"""One identity per trainer lead across URL variants, and a save that updates instead of adding a copy."""
import logging
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

# Empty fields on a saved lead that a later search may fill in. Values already saved,
# status, requirement and review fields are never overwritten by a search.
_FILL_FIELDS = ('email', 'phone', 'contact_email', 'contact_phone', 'name', 'trainer_name', 'headline',
                'snippet', 'profile_text', 'linkedin_url', 'linkedin_slug', 'external_slug', 'source_url')
_CONTACT_FIELDS = ('email', 'phone', 'contact_email', 'contact_phone')
# A contact found in the profile text upgrades only these tiers.
_WEAK_TIERS = ('', 'unverified', 'linkedin_signal')
_SAVED_FIELDS = {name: 1 for name in ('_id', 'lead_id', 'status', 'profile_key', 'verification_tier', *_FILL_FIELDS)}


def _normalized_url(value):
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    # Reading .port raises ValueError for a malformed port, which the caller treats as no URL.
    if parts.scheme not in ('http', 'https') or not host or parts.port == 0:
        return ''
    return urlunsplit(('https', host, parts.path.rstrip('/'), '', '')).lower()


def trainer_lead_key(url):
    """Lowercase key shared by every URL variant of one profile or post; '' when the URL names nothing.

    LinkedIn profiles become https://www.linkedin.com/in/<slug>, LinkedIn posts become
    linkedin:activity:<id> (the client post key), and Naukri pages become https://www.naukri.com/<path>.
    """
    from app.clients.search_accuracy import canonical_public_url
    from app.clients.serp_engines import canonical_post_url, canonical_profile_url, post_key

    value = str(url or '').strip()
    if not value:
        return ''
    try:
        profile = canonical_profile_url(value)
        if profile:
            return profile.lower()
        post = canonical_post_url(value)
        if post:
            return post_key(post).lower()
        public = canonical_public_url(value)
        return public.lower() if public else _normalized_url(value)
    except ValueError:
        # urlsplit rejects some malformed URLs, such as a bad port.
        return ''


def lead_key(lead):
    """The key for a saved lead document: its source URL, then its LinkedIn URL, then its LinkedIn slug."""
    for field in ('source_url', 'linkedin_url'):
        key = trainer_lead_key(lead.get(field))
        if key:
            return key
    slug = str(lead.get('linkedin_slug') or '').strip()
    return trainer_lead_key(f'https://www.linkedin.com/in/{slug}') if slug else ''


def _slug_pattern(key):
    """The profile slug of a key, percent-encoded or not, as a regex alternation."""
    slug = key.rsplit('/', 1)[-1]
    variants = sorted({re.escape(slug), re.escape(quote(unquote(slug), safe='-_.')), re.escape(unquote(slug))})
    return '(?:' + '|'.join(variants) + ')'


def _url_pattern(key):
    """A regex that matches the saved URL variants of a key, for leads saved before keys existed."""
    if key.startswith('https://www.linkedin.com/in/'):
        # Also /in/<slug>/details/... and other sub-pages of the same profile.
        return r'^https?://(?:[a-z0-9-]+\.)?linkedin\.com/in/' + _slug_pattern(key) + r'(?:/[^?#]*)?(?:[?#].*)?$'
    if key.startswith('linkedin:activity:'):
        activity = re.escape(key.rsplit(':', 1)[-1])
        return (r'^https?://(?:[a-z0-9-]+\.)?linkedin\.com/(?:posts/[^?#]*activity-|'
                r'feed/update/urn(?::|%3a)li(?::|%3a)activity(?::|%3a))' + activity + r'(?!\d)')
    parts = urlsplit(key)
    host = parts.hostname or ''
    if host.endswith('naukri.com'):
        host = r'(?:[a-z0-9-]+\.)?naukri\.com'
    else:
        host = re.escape(host)
    return r'^https?://' + host + re.escape(parts.path) + r'/?(?:[?#].*)?$'


def legacy_lookup(key, lead):
    """Match leads saved before profile keys existed: URL variants and the saved slugs."""
    terms = []
    if key:
        pattern = _url_pattern(key)
        terms += [{'source_url': {'$regex': pattern, '$options': 'i'}},
                  {'linkedin_url': {'$regex': pattern, '$options': 'i'}}]
    else:
        for field in ('source_url', 'linkedin_url'):
            if lead.get(field):
                terms.append({field: lead[field]})
    if key.startswith('https://www.linkedin.com/in/'):
        # Some older leads kept only the slug. Only those are matched by it: older slugs were cut at
        # characters such as ".", so /in/jose.garcia was saved with the slug "jose". Naukri path
        # slugs are not used at all: two pages can share one.
        terms.append({'$and': [{'linkedin_slug': {'$regex': '^' + _slug_pattern(key) + '$', '$options': 'i'}},
                               {'$or': [{'source_url': None}, {'source_url': ''}]},
                               {'$or': [{'linkedin_url': None}, {'linkedin_url': ''}]}]})
    if not terms:
        return None
    # A lead that already has a key is found by that key only.
    return {'$and': [{'profile_key': {'$exists': False}}, {'$or': terms}]}


async def find_saved_trainer_lead(table, key, lead):
    if key:
        saved = await table.find_one({'profile_key': key}, _SAVED_FIELDS)
        if saved:
            return saved
    lookup = legacy_lookup(key, lead)
    return await table.find_one(lookup, _SAVED_FIELDS) if lookup else None


async def _refresh(table, saved, lead, key, now):
    fill = {name: lead[name] for name in _FILL_FIELDS if lead.get(name) and not saved.get(name)}
    updates = {**fill, 'last_found_at': now}
    if fill:
        updates['updated_at'] = now
    if any(name in fill for name in _CONTACT_FIELDS) and (saved.get('verification_tier') or '') in _WEAK_TIERS:
        for name in ('verification_tier', 'confidence'):
            if lead.get(name):
                updates[name] = lead[name]
    if key and saved.get('profile_key') != key:
        updates['profile_key'] = key
    target = {'_id': saved['_id']} if '_id' in saved else {'lead_id': saved.get('lead_id')}
    try:
        await table.update_one(target, {'$set': updates})
    except DuplicateKeyError:
        # A copy saved before keys existed already holds this key; merge_duplicate_leads merges them.
        updates.pop('profile_key', None)
        await table.update_one(target, {'$set': updates})


async def save_trainer_lead(db, lead, now):
    """Insert a trainer lead, or update the lead already saved for the same profile.

    Returns {'lead_id', 'created', 'status'}: the saved lead's ID and status, which differ from
    lead['lead_id'] and lead['status'] when the profile was saved before.
    """
    table = db['trainer_profile_leads']
    key = lead_key(lead)
    saved = await find_saved_trainer_lead(table, key, lead)
    if saved is None:
        record = {**lead, 'created_at': now, 'updated_at': now, 'last_found_at': now}
        if key:
            record['profile_key'] = key
        try:
            await table.insert_one(record)
            return {'lead_id': lead['lead_id'], 'created': True, 'status': lead.get('status', '')}
        except DuplicateKeyError:
            # Another search saved this profile after the lookup above.
            saved = await table.find_one({'profile_key': key}, _SAVED_FIELDS) if key else None
            if saved is None:
                raise
    await _refresh(table, saved, lead, key, now)
    return {'lead_id': saved.get('lead_id') or lead['lead_id'], 'created': False, 'status': saved.get('status') or ''}
