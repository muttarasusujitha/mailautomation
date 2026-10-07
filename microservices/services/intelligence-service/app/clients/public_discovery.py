"""Search multiple public queries until the qualified per-domain target is met."""
import asyncio
from app.clients.public_search import search_public


async def discover_public(domain, mode, target=20, location=''):
    from app.clients.lead_discovery import public_queries
    from app.clients.linkedin_browser import canonical_url
    from app.routes.linkedin_leads import _normalize_result
    target = min(100, max(20, target))
    queries = public_queries(domain, mode, location)
    queries += [f'{domain} {location} {phrase} site:linkedin.com/{"in" if mode == "trainer" else "posts"}/'
                for phrase in (('independent trainer', 'certified instructor', 'corporate training', 'technical trainer')
                               if mode == 'trainer' else ('need a trainer', 'freelance trainer required', 'corporate training requirement', 'seeking training partner'))]
    rows, seen, warnings = [], set(), []
    attempts = 0
    for query in queries:
        attempts += 1
        try:
            batch = await asyncio.wait_for(search_public(query, 20), timeout=18)
        except Exception as exc:
            warnings.append(str(exc) or type(exc).__name__)
            if len(warnings) >= 3:
                break
            continue
        for item in batch:
            url = canonical_url(item.get('url', ''))
            item = {**item, 'url': url}
            if url and url not in seen and _normalize_result(item, domain, mode):
                seen.add(url)
                rows.append(item)
            if len(rows) >= target:
                break
        if len(rows) >= target:
            break
    return rows, {'domain': domain, 'target': target, 'matched': len(rows),
                  'target_met': len(rows) >= target, 'attempts': attempts,
                  'status': 'target_met' if len(rows) >= target else 'partial' if rows else 'blocked' if warnings else 'no_results',
                  'warnings': warnings,
                  'reason': '' if len(rows) >= target else 'Accessible public queries exhausted or unavailable; no unrelated profiles added.'}
