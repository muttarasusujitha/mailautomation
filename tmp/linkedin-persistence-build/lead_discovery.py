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
    scope = f'{domain} {location}'.strip()
    phrases = ('corporate trainer', 'freelance trainer', 'technical instructor', 'training consultant', 'trainer', 'instructor') if mode == 'trainer' else (
        'trainer required', 'looking for trainer', 'seeking trainer', 'trainers needed', 'training requirement', 'training partner')
    path = 'in' if mode == 'trainer' else 'posts'
    return [f'{scope} "{phrase}" site:linkedin.com/{path}/' for phrase in phrases]


async def discover(domain, mode, target, location=''):
    from app.clients.public_search import search_public
    from app.clients.linkedin_browser import search_linkedin_account, canonical_url
    from app.routes.linkedin_leads import _normalize_result
    results, seen, warnings = [], set(), []
    attempts = 0

    def accept(rows, provider):
        for row in rows:
            url = canonical_url(row.get('url', ''))
            row = {**row, 'url': url, 'discovery_provider': provider}
            if url and url not in seen and _normalize_result(row, domain, mode):
                seen.add(url)
                results.append(row)
                if len(results) >= target:
                    break

    # Public indexes remain usable when the account needs manual verification.
    queries = public_queries(domain, mode, location)
    for start in range(0, len(queries), 2):
        batch = queries[start:start + 2]
        outcomes = await asyncio.gather(*(asyncio.wait_for(search_public(q, 20), timeout=5) for q in batch), return_exceptions=True)
        attempts += len(batch)
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                warning = search_warning('public', outcome)
                if warning not in warnings:
                    warnings.append(warning)
            else:
                accept(outcome, 'public')
        if len(results) >= target:
            break
    if len(results) < target:
        attempts += 1
        try:
            # Let the people search and bounded fallback return partial matches.
            accept(await asyncio.wait_for(search_linkedin_account(domain, mode, target, location), timeout=100), 'linkedin_account')
        except Exception as exc:
            accept(getattr(exc, 'results', []), 'linkedin_account')
            # Account verification is the actionable blocker. Put it first for
            # the domain message and use the same warning for the route error.
            warnings.insert(0, search_warning('linkedin_account', exc))
    return results[:target], {'domain': domain, 'target': target, 'matched': min(len(results), target),
                              'target_met': len(results) >= target, 'attempts': attempts,
                              'warnings': warnings, 'primary_error': warnings[0]['error'] if warnings else None,
                              'status': 'target_met' if len(results) >= target else 'partial' if results else 'blocked' if warnings else 'no_results'}
