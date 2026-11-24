"""Per-source search status, the success rule, and the saved record of each lead search run."""
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# A source "worked" when it answered, even if nothing it returned was usable.
WORKING_STATUSES = ('ok', 'filtered', 'no_results')
FAILED_STATUSES = ('blocked', 'paused', 'error')
# When one source ran for several domains, the merged entry shows its best outcome.
_STATUS_ORDER = ('ok', 'filtered', 'no_results', 'blocked', 'paused', 'error', 'not_configured', 'not_needed', 'not_run')
_SOURCE_FIELDS = ('source', 'label', 'status', 'found', 'qualified', 'reason', 'note', 'queries', 'pages',
                  'links_seen', 'new_profiles', 'cooling_until')
_OUTCOME_FIELDS = ('domain', 'query', 'target', 'matched', 'target_met', 'status', 'primary_error',
                   'limit_reason', 'from_account', 'from_web_engines')


def search_succeeded(found, sources):
    """False only when nothing was found and no source that ran gave an answer."""
    return bool(found) or any((item or {}).get('status') in WORKING_STATUSES for item in sources or ())


def failure_summary(sources):
    """One sentence naming why every source failed, or '' when at least one source answered."""
    sources = [item for item in sources or () if item]
    if not sources or any(item.get('status') in WORKING_STATUSES for item in sources):
        return ''
    failed = [f"{item.get('label') or item.get('source')}: {item.get('reason') or item.get('status')}"
              for item in sources if item.get('status') in FAILED_STATUSES + ('not_configured',)]
    return ('No search source gave an answer. ' + ' '.join(failed))[:600] if failed else ''


def _rank(status):
    return _STATUS_ORDER.index(status) if status in _STATUS_ORDER else len(_STATUS_ORDER)


def merge_sources(source_lists):
    """One entry per source from the entries of several searches (one search per domain or query)."""
    merged, order = {}, []
    for sources in source_lists:
        for item in sources or ():
            key = item.get('source') or item.get('label') or 'unknown'
            entry = merged.get(key)
            if entry is None:
                entry = merged[key] = {'source': key, 'label': item.get('label') or key, 'status': '',
                                       'found': 0, 'qualified': 0, 'reason': '', '_runs': 0, '_failures': []}
                order.append(key)
            status = item.get('status') or 'not_run'
            entry['_runs'] += 1
            entry['found'] += int(item.get('found') or 0)
            entry['qualified'] += int(item.get('qualified') or 0)
            if status in FAILED_STATUSES:
                entry['_failures'].append(item.get('reason') or status)
            if not entry['status'] or _rank(status) < _rank(entry['status']):
                entry['status'] = status
                entry['reason'] = item.get('reason') or ''
    result = []
    for key in order:
        entry = merged[key]
        runs, failures = entry.pop('_runs'), entry.pop('_failures')
        if failures and entry['status'] not in FAILED_STATUSES:
            entry['note'] = f'Failed on {len(failures)} of {runs} searches: {failures[0]}'
        result.append(entry)
    return result


def outcome_status(matched, target, sources):
    if target and matched >= target:
        return 'target_met'
    if matched:
        return 'partial'
    return 'no_results' if search_succeeded(0, sources) or not sources else 'blocked'


def _compact_source(item):
    return {name: item[name] for name in _SOURCE_FIELDS if name in item}


def _compact_outcome(outcome):
    compact = {name: outcome[name] for name in _OUTCOME_FIELDS if name in outcome}
    compact['sources'] = [_compact_source(item) for item in outcome.get('sources') or () if isinstance(item, dict)]
    return compact


async def record_search_run(db, kind, request, result, started_at, search_ref=''):
    """Save what one search did, per source, so it can be read back later. Never fails the search.

    search_ref is an ID the page sent with the search, so it can find this report if its own
    request timed out.
    """
    finished_at = datetime.utcnow()
    run = {
        'run_id': f'RUN-{uuid.uuid4().hex[:12].upper()}',
        'search_ref': str(search_ref or '').strip()[:64],
        'kind': kind,
        'request': request,
        'started_at': started_at,
        'finished_at': finished_at,
        'duration_seconds': round((finished_at - started_at).total_seconds(), 1),
        'success': bool(result.get('success')),
        'found': int(result.get('found') or 0),
        'saved_count': int(result.get('saved_count') or 0),
        'search_error': str(result.get('search_error') or '')[:600],
        'sources': [_compact_source(item) for item in result.get('sources') or () if isinstance(item, dict)],
        'domain_outcomes': [_compact_outcome(item) for item in result.get('domain_outcomes') or ()
                            if isinstance(item, dict)],
    }
    try:
        # A copy, because the driver adds an _id to the document it inserts.
        await db['lead_search_runs'].insert_one(dict(run))
    except Exception as exc:
        logger.warning('Could not save the %s search run report: %s', kind, exc)
        return ''
    return run['run_id']
