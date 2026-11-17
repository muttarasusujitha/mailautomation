"""Bounded, key-free discovery with per-source outcomes and qualified counts."""
import asyncio
import httpx


def search_warning(source, error):
    label = 'Public web search' if source == 'public' else 'LinkedIn account search'
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        message = f'{label} timed out. Any matches already found have been retained.'
    else:
        message = str(error) or f'{label} failed. Please try again later.'
    return {'source': source, 'error': message}


def linkedin_requires_public_fallback(error):
    message = str(error or '').lower()
    return 'linkedin limited this session' in message


def linkedin_session_requires_public_fallback(error):
    message = str(error or '').lower()
    return linkedin_requires_public_fallback(message) or 'linkedin sign-in or verification required' in message


async def discover_public_fallback(domain, mode, target, location=''):
    """Use public indexed LinkedIn pages after LinkedIn blocks an account search."""
    from urllib.parse import urlsplit
    from app.clients.public_discovery import discover_public

    rows, outcome = await discover_public(domain, mode, target, location)
    linkedin_rows = []
    for row in rows:
        url = row.get('url') or row.get('source_url') or ''
        host = (urlsplit(url).hostname or '').lower()
        if host == 'linkedin.com' or host.endswith('.linkedin.com'):
            linkedin_rows.append({**row, 'discovery_provider': 'public_fallback'})
    outcome = {**outcome, 'matched': len(linkedin_rows), 'target_met': len(linkedin_rows) >= target}
    if len(linkedin_rows) < target:
        # Keep "blocked": a refused search engine is not the same as no matching profiles.
        outcome['status'] = ('partial' if linkedin_rows
                             else 'blocked' if outcome.get('status') == 'blocked' else 'no_results')
    return linkedin_rows, outcome


def public_queries(domain, mode, location=''):
    if mode == 'trainer':
        from app.clients.search_accuracy import trainer_public_queries
        return trainer_public_queries(domain, location)
    scope = f'{domain} {location}'.strip()
    phrases = (
        'trainer required', 'looking for trainer', 'seeking trainer',
        'trainers needed', 'training requirement', 'training partner',
    )
    return [f'{scope} {phrase}'.strip() for phrase in phrases]


async def discover(domain, mode, target, location='', db=None):
    """Find leads with the connected LinkedIn account. Public web search is not used."""
    from app.clients.linkedin_browser import search_linkedin_account
    from app.clients.search_accuracy import canonical_public_url
    from app.routes.linkedin_leads import _normalize_result
    results, seen, warnings = [], set(), []
    attempts = 1
    collected = []
    excluded = set()
    if mode == 'trainer' and db is not None:
        for field in ('source_url', 'linkedin_url'):
            for value in await db['trainer_profile_leads'].distinct(field):
                url = canonical_public_url(value or '')
                if url:
                    excluded.add(url.lower())

    def accept(rows, provider):
        for row in rows:
            url = canonical_public_url(row.get('url', ''))
            row = {**row, 'url': url, 'discovery_provider': provider}
            if url and url.lower() not in excluded and url not in seen and _normalize_result(row, domain, mode):
                seen.add(url)
                results.append(row)
                if len(results) >= target:
                    break

    try:
        # People search paginates inside this budget. Keep every profile
        # appended before a timeout, including when the browser is cancelled.
        accept(await asyncio.wait_for(
            search_linkedin_account(domain, mode, target, location, collected, **({"excluded_urls": excluded} if excluded else {})), timeout=260), 'linkedin_account')
    except Exception as exc:
        accept(getattr(exc, 'results', None) or collected, 'linkedin_account')
        warnings.insert(0, search_warning('linkedin_account', exc))
    return results[:target], {'domain': domain, 'target': target, 'matched': min(len(results), target),
                              'target_met': len(results) >= target, 'attempts': attempts,
                              'warnings': warnings, 'primary_error': warnings[0]['error'] if warnings else None,
                              'status': 'target_met' if len(results) >= target else 'partial' if results else 'blocked' if warnings else 'no_results'}


def _account_source(rows, outcome):
    error = outcome.get('primary_error') or ''
    low = error.lower()
    if 'paused until' in low or 'linkedin limited this session' in low:
        status = 'paused'
    elif rows:
        status = 'ok'
    elif error:
        status = 'blocked'
    else:
        status = 'no_results'
    return {'source': 'linkedin_account', 'label': 'LinkedIn account', 'status': status,
            'qualified': len(rows), 'reason': error}


async def _saved_trainer_urls(db):
    from app.clients.search_accuracy import canonical_public_url
    urls = set()
    if db is None:
        return urls
    try:
        for field in ('source_url', 'linkedin_url'):
            for value in await db['trainer_profile_leads'].distinct(field) or []:
                url = canonical_public_url(value or '') if isinstance(value, str) else ''
                if url:
                    urls.add(url.lower())
    except Exception:
        pass
    return urls


async def discover_with_trainer_finder(domain, target, location, db, account_rows, account_outcome, time_left=None):
    """Fill the rest of the trainer target with the multi-engine finder after the account search."""
    from app.clients.trainer_finder import budget_seconds, find_trainers

    account_rows = list(account_rows or [])
    account = _account_source(account_rows, account_outcome or {})
    warnings = list((account_outcome or {}).get('warnings') or [])
    needed = target - len(account_rows)
    budget = budget_seconds() if time_left is None else min(budget_seconds(), time_left - 10)
    if needed <= 0:
        rows, report = [], {'sources': [], 'limit_reason': '', 'status': 'target_met'}
    elif budget < 20:
        rows, report = [], {'sources': [], 'status': 'no_results',
                            'limit_reason': 'The search time budget was used before the web engines could run.'}
    else:
        exclude = await _saved_trainer_urls(db)
        exclude.update(str(row.get('url') or '').lower() for row in account_rows)
        try:
            rows, report = await find_trainers(domain, needed, location, exclude=exclude, budget=budget)
        except Exception as exc:
            rows, report = [], {'sources': [], 'status': 'blocked',
                                'limit_reason': f'The web engine search failed: {str(exc)[:200] or type(exc).__name__}'}
    combined = account_rows + rows
    sources = [account, *report.get('sources', [])]
    limit_reason = report.get('limit_reason') or ''
    if len(combined) < target and limit_reason:
        warnings.append({'source': 'trainer_finder', 'error': limit_reason})
    any_source_worked = any(item.get('status') in ('ok', 'filtered', 'no_results', 'not_needed') for item in sources)
    status = ('target_met' if len(combined) >= target else 'partial' if combined
              else 'no_results' if any_source_worked else 'blocked')
    return combined, {
        'domain': domain,
        'target': target,
        'matched': len(combined),
        'target_met': len(combined) >= target,
        'status': status,
        'attempts': (account_outcome or {}).get('attempts', 1),
        'warnings': warnings,
        'primary_error': (account_outcome or {}).get('primary_error') or (
            (limit_reason or 'No search source could be reached.') if status == 'blocked' else None),
        'fallback_source': 'trainer_finder',
        'from_account': len(account_rows),
        'from_web_engines': len(rows),
        'sources': sources,
        'limit_reason': '' if len(combined) >= target else limit_reason,
        'reason': '' if len(combined) >= target else limit_reason,
    }
