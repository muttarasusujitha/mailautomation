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
