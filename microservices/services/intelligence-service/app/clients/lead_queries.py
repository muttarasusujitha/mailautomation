"""Server-side list filters and counts for the lead pages, so they can page with correct totals.

Each `kind` reproduces a filter that a page used to apply in the browser to the first
150-500 rows, so the visible set stays the same while every page and total is correct.
"""
import re

NO_DOMAIN = '__none__'
DOMAIN_CHIP_LIMIT = 50

TRAINER_Q_FIELDS = ('name', 'trainer_name', 'headline', 'domain', 'snippet', 'profile_text')
CLIENT_Q_FIELDS = ('company_name', 'contact_name', 'domain', 'matched_domains', 'notes', 'source_url')
# The fields each page's domain filter searched. The Pipeline checked the domain and the profile
# summary; the Shortlist checked the domain and its profile and post text.
_PIPELINE_TOPIC_FIELDS = ('domain', 'profile_text', 'snippet', 'headline', 'notes')

# LinkedIn Search, trainer mode (isTrainerProviderProfile in LinkedInSearch.jsx).
_PROFILE_URL = r'linkedin\.com/(?:in/|posts/|feed/update)'
_SAYS_TRAINER = r'trainer|instructor|corporate training|training consultant|facilitator|coach'
_PROFILE_TEXT_FIELDS = ('trainer_name', 'name', 'headline', 'profile_text', 'snippet', 'notes', 'domain')

# LinkedIn Shortlist, trainer mode (isTrainerProviderProfile in LinkedInShortlist.jsx).
_SHORTLIST_FIELDS = ('domain', 'trainer_name', 'headline', 'profile_text', 'company_name', 'contact_name',
                     'post_text', 'notes')
_SHORTLIST_BLOCKERS = (
    ' job ', ' jobs ', 'job vacancies', 'job vacancy', 'apply to', 'job description', 'required candidate profile',
    'current ctc', 'expected ctc', 'notice period', 'immediate joiner',
    'last working day', 'offer in hand', 'actively exploring', 'open to opportunities',
    'willing to relocate', 'application for', 'my resume', 'ready to work from office',
    'work preference', 'looking for job', 'seeking opportunity',
    'institute', 'academy', 'pvt ltd', 'private limited', 'solutions', 'technologies',
    'consultant', 'consulting', 'recruiter', 'location ', 'experience ', 'yrs · consultant', 'yrs consultant',
)
_SHORTLIST_SIGNALS = (
    'trainer profile', 'freelance trainer', 'corporate trainer', 'technical trainer',
    'training delivery', 'conduct trainings', 'conducted trainings', 'delivered training',
    'instructor', 'faculty', 'mentor', 'coach', 'online training', 'classroom training',
)

# Naukri Search (isNaukriUrl in NaukriSearch.jsx), checked on the path after a naukri.com host.
_NAUKRI_HOST = r'^https?://(?:[^/?#@]*\.)?naukri\.com(?::\d+)?(?=[/?#]|$)'
_NAUKRI_PROFILE_PATH = r'(?=[^?#]*(?:/(?:resume|profile|candidate)(?:/|[?#]|$)|/(?:resume|candidate|profile)-))'
_NAUKRI_NON_PROFILE_PATH = (
    r'(?=[^?#]*(?:/(?:jobs?|job-listings?|career-advice|profile-summary|blog|campus|companies|company|services|'
    r'resume-maker|resume-templates|recruiter-zone)(?:/|[?#]|$)|-jobs?(?:-|[?#]|$)))'
)

TRAINER_KINDS = ('linkedin_profile', 'linkedin', 'shortlist', 'naukri_profile')
_TOPIC_FIELDS = {'linkedin': _PIPELINE_TOPIC_FIELDS}
CLIENT_TOPIC_FIELDS = _SHORTLIST_FIELDS


def _tokens(tokens, first, last):
    """The page's substring tests as one regex for one field.

    The page joined the fields with single spaces, so a space at either end of a token
    also matched the start or end of a field, except before the first field and after
    the last one. Only a space counts, as in the page: a newline does not.
    """
    parts = []
    for text in tokens:
        lead = (' ' if first else '(?:^| )') if text.startswith(' ') else ''
        tail = (' ' if last else '(?: |$)') if text.endswith(' ') else ''
        parts.append(lead + re.escape(text.strip()) + tail)
    return '|'.join(parts)


def _token_clauses(fields, tokens):
    last = len(fields) - 1
    return [{field: {'$regex': _tokens(tokens, index == 0, index == last), '$options': 'i'}}
            for index, field in enumerate(fields)]


def _any_field(fields, pattern):
    return [{field: {'$regex': pattern, '$options': 'i'}} for field in fields]


def contains_any(fields, text):
    return {'$or': _any_field(fields, re.escape(text))}


def not_blank(field):
    return {field: {'$regex': r'\S'}}


def blank(field):
    # {field: None} also matches a missing field.
    return {'$or': [{field: None}, {field: {'$regex': r'^\s*$'}}]}


def domain_exact(value):
    """One saved domain, ignoring case and surrounding spaces. NO_DOMAIN means leads without a domain."""
    if value == NO_DOMAIN:
        return blank('domain')
    return {'domain': {'$regex': r'^\s*' + re.escape(value.strip()) + r'\s*$', '$options': 'i'}}


def split_list(value):
    return [item.strip() for item in str(value or '').split(',') if item.strip()]


HAS_EMAIL = {'$or': [not_blank('email'), not_blank('contact_email')]}
HAS_PHONE = {'$or': [not_blank('phone'), not_blank('contact_phone')]}
HAS_CONTACT = {'$or': HAS_EMAIL['$or'] + HAS_PHONE['$or']}


def trainer_kind_filter(kind):
    if kind == 'linkedin_profile':
        return {'$and': [
            {'$or': [{'source_url': {'$regex': _PROFILE_URL, '$options': 'i'}}, {'lead_type': 'resume_trainer_post'}]},
            {'$or': [not_blank('trainer_name'), not_blank('name'), not_blank('headline'),
                     {'lead_type': 'trainer_profile'}, *_any_field(_PROFILE_TEXT_FIELDS, _SAYS_TRAINER)]},
        ]}
    if kind == 'linkedin':
        return {'$or': [{'source': None}, {'source': {'$regex': r'^\s*(?:linkedin)?\s*$', '$options': 'i'}},
                        {'linkedin_url': {'$regex': r'linkedin\.com/in', '$options': 'i'}},
                        {'source_url': {'$regex': r'linkedin\.com/in', '$options': 'i'}}]}
    if kind == 'shortlist':
        return {'$and': [{'$nor': _token_clauses(_SHORTLIST_FIELDS, _SHORTLIST_BLOCKERS)},
                         {'$or': _token_clauses(_SHORTLIST_FIELDS, _SHORTLIST_SIGNALS)}]}
    if kind == 'naukri_profile':
        return {'$and': [
            {'source': 'naukri'},
            {'source_url': {'$regex': _NAUKRI_HOST + _NAUKRI_PROFILE_PATH, '$options': 'i'}},
            {'$nor': [{'source_url': {'$regex': _NAUKRI_HOST + _NAUKRI_NON_PROFILE_PATH, '$options': 'i'}}]},
        ]}
    raise ValueError(f'kind must be one of: {", ".join(TRAINER_KINDS)}')


def _status_clauses(status, statuses, skip_status):
    clauses = []
    names = split_list(statuses)
    if names:
        clauses.append({'status': {'$in': names}})
    if status and status.lower() != 'all' and not skip_status:
        clauses.append({'status': status})
    return clauses


def trainer_query(*, status=None, statuses=None, domain=None, domain_value=None, requirement_id=None,
                  requirement_scope=None, source=None, q=None, kind=None, has_contact=False, topic=None,
                  skip_status=False, skip_domain=False):
    """The trainer lead filter. skip_status / skip_domain leave out that filter, for the counts."""
    query = {}
    clauses = _status_clauses(status, statuses, skip_status)
    domain = (domain or '').strip()
    if domain and not skip_domain:
        clauses.append({'domain': {'$regex': re.escape(domain), '$options': 'i'}})
    if domain_value and not skip_domain:
        clauses.append(domain_exact(domain_value))
    topic = ' '.join((topic or '').split())
    if topic and not skip_domain:
        clauses.append(contains_any(_TOPIC_FIELDS.get(kind, _SHORTLIST_FIELDS), topic))
    if requirement_id:
        query['requirement_id'] = requirement_id
    if requirement_scope:
        # A requirement's pipeline also shows leads not yet assigned to any requirement.
        clauses.append({'$or': [{'requirement_id': None}, {'requirement_id': {'$regex': r'^\s*$'}},
                                {'requirement_id': requirement_scope.strip()}]})
    if source:
        query['source'] = source.strip().lower()
    if kind:
        clauses.append(trainer_kind_filter(kind))
    if has_contact:
        clauses.append(HAS_CONTACT)
    q = ' '.join((q or '').split())
    if q:
        query['$or'] = _any_field(TRAINER_Q_FIELDS, re.escape(q))
    if clauses:
        query['$and'] = clauses
    return query


def client_query(*, status=None, statuses=None, domain=None, domain_value=None, q=None, topic=None,
                 skip_status=False, skip_domain=False):
    query = {}
    clauses = _status_clauses(status, statuses, skip_status)
    domain = (domain or '').strip()
    if domain and not skip_domain:
        clauses.append(contains_any(('domain', 'matched_domains'), domain))
    if domain_value and not skip_domain:
        clauses.append(domain_exact(domain_value))
    topic = ' '.join((topic or '').split())
    if topic and not skip_domain:
        clauses.append(contains_any(CLIENT_TOPIC_FIELDS, topic))
    q = ' '.join((q or '').split())
    if q:
        query['$or'] = _any_field(CLIENT_Q_FIELDS, re.escape(q))
    if clauses:
        query['$and'] = clauses
    return query


_DOMAIN_TEXT = {'$trim': {'input': {'$cond': [{'$eq': [{'$type': '$domain'}, 'string']}, '$domain', '']}}}


async def lead_counts(table, by_status_query, by_domain_query, full_query):
    """Totals for the page's status tabs, domain chips and contact cards.

    by_status ignores the status tab, by_domain ignores the domain filter, and the contact
    counts use every filter, so each number matches what choosing that tab or chip would list.
    """
    by_status = {}
    rows = await table.aggregate([
        {'$match': by_status_query},
        {'$group': {'_id': '$status', 'count': {'$sum': 1}}},
    ]).to_list(length=None)
    for row in rows:
        name = str(row['_id'] or '')
        by_status[name] = by_status.get(name, 0) + int(row['count'])

    domains = {}
    rows = await table.aggregate([
        {'$match': by_domain_query},
        {'$group': {'_id': {'key': {'$toLower': _DOMAIN_TEXT}, 'status': '$status'},
                    'count': {'$sum': 1}, 'label': {'$min': _DOMAIN_TEXT}}},
    ]).to_list(length=None)
    for row in rows:
        key = row['_id'].get('key') or ''
        entry = domains.setdefault(key, {'value': key or NO_DOMAIN, 'domain': '', 'total': 0, 'by_status': {}})
        label = row.get('label') or ''
        if label and (not entry['domain'] or label < entry['domain']):
            entry['domain'] = label
        status = str(row['_id'].get('status') or '')
        entry['total'] += int(row['count'])
        entry['by_status'][status] = entry['by_status'].get(status, 0) + int(row['count'])
    chips = sorted(domains.values(), key=lambda item: (-item['total'], (item['domain'] or 'Other').lower()))
    for chip in chips:
        chip['domain'] = chip['domain'] or 'Other'

    with_email = await table.count_documents({'$and': [full_query, HAS_EMAIL]})
    with_phone = await table.count_documents({'$and': [full_query, HAS_PHONE]})
    return {
        'by_status': by_status,
        'by_domain': chips[:DOMAIN_CHIP_LIMIT],
        'domains_total': len(chips),
        'all_domains_total': sum(chip['total'] for chip in chips),
        'with_email': with_email,
        'with_phone': with_phone,
    }
