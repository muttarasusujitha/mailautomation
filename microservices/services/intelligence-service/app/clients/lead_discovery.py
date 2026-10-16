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


async def discover(domain, mode, target, location=''):
    from app.clients.linkedin_browser import search_linkedin_account
    from app.clients.search_accuracy import canonical_public_url, select_accurate_profiles
    from app.routes.linkedin_leads import _normalize_result
    results, seen, warnings = [], set(), []
    attempts = 0

    def accept(rows, provider):
        if provider == 'public' and mode == 'trainer':
            rows = select_accurate_profiles(rows, domain)
        for row in rows:
            url = canonical_public_url(row.get('url', ''))
            row = {**row, 'url': url, 'discovery_provider': provider}
            if url and url not in seen and _normalize_result(row, domain, mode):
                seen.add(url)
                results.append(row)
                if len(results) >= target:
                    break

    # Public indexes remain usable when the account needs manual verification.
    queries = public_queries(domain, mode, location)
    from app.clients.public_search import search_public_many
    attempts += 1
    batch = None
    public_limit = max(50, target) if mode == 'trainer' else max(20, min(target, 50))
    try:
        # One pass for every phrase. Cancelling each phrase at 20 seconds
        # discarded results that were still arriving.
        batch = await asyncio.wait_for(search_public_many(queries, public_limit), timeout=50)
        rows, used = batch
        attempts += max(int(used) - 1, 0)
    except TimeoutError:
        rows = []
        warnings.append(search_warning('public', TimeoutError()))
    except Exception as exc:
        warning = search_warning('public', exc)
        if warning not in warnings:
            warnings.append(warning)
        rows = []
    else:
        if not rows and getattr(batch, 'timed_out', False):
            warnings.append(search_warning('public', TimeoutError()))
    accept(rows, 'public')
    if len(results) < target:
        attempts += 1
        collected = []
        try:
            # People search paginates inside this budget. Keep every profile
            # appended before a timeout, including when the browser is cancelled.
            accept(await asyncio.wait_for(
                search_linkedin_account(domain, mode, target, location, collected), timeout=260), 'linkedin_account')
        except Exception as exc:
            accept(getattr(exc, 'results', None) or collected, 'linkedin_account')
            # Account verification is the actionable blocker. Put it first for
            # the domain message and use the same warning for the route error.
            warnings.insert(0, search_warning('linkedin_account', exc))
    return results[:target], {'domain': domain, 'target': target, 'matched': min(len(results), target),
                              'target_met': len(results) >= target, 'attempts': attempts,
                              'warnings': warnings, 'primary_error': warnings[0]['error'] if warnings else None,
                              'status': 'target_met' if len(results) >= target else 'partial' if results else 'blocked' if warnings else 'no_results'}
