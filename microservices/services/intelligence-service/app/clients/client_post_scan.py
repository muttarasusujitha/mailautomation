"""Scan training requests once, then match every post against every domain."""
import re
from datetime import datetime

from app.clients.lead_discovery import (
    discover,
    discover_public_fallback,
    search_warning,
)
from app.routes.linkedin_leads import _normalize_result, _result_text
from app.clients.client_post_identity import post_identity, save_client_post


async def scan_client_posts(domains, db, include_unmatched=False):
    # Empty domain deliberately makes discovery search only for request intent.
    rows, discovery = await discover('', 'client', 50)
    target = 50
    # A zero-result account search is not proof that there are no posts: LinkedIn
    # can return an empty page while limiting a session. Always try public indexed
    # results when the account search did not fill the scan target.
    if len(rows) < target:
        account_rows = list(rows)
        try:
            public_rows, public_outcome = await discover_public_fallback(
                '', 'client', target - len(account_rows))
        except Exception as exc:
            public_rows = []
            public_outcome = {
                'status': 'blocked',
                'warnings': [str(exc) or type(exc).__name__],
            }

        seen_urls = set()
        combined_rows = []
        for row in [*account_rows, *public_rows]:
            url = row.get('url') or row.get('source_url') or ''
            try:
                identity = post_identity(url)
            except ValueError:
                continue
            if identity not in seen_urls:
                seen_urls.add(identity)
                combined_rows.append(row)
                if len(combined_rows) >= target:
                    break

        fallback_warnings = list(discovery.get('warnings') or [])
        fallback_warnings.extend(
            search_warning('public', warning)
            for warning in (public_outcome.get('warnings') or [])
        )
        discovery = {
            **public_outcome,
            'status': (
                'target_met' if len(combined_rows) >= target
                else 'partial' if combined_rows
                else 'blocked' if fallback_warnings
                else 'no_results'
            ),
            'matched': len(combined_rows),
            'target_met': len(combined_rows) >= target,
            'fallback_source': 'public_search',
            'warnings': fallback_warnings,
            'primary_error': fallback_warnings[0]['error'] if fallback_warnings else None,
        }
        rows = combined_rows

    domains = list(dict.fromkeys(domain.strip() for domain in domains if domain.strip()))
    counts = dict.fromkeys(domains, 0)
    found = saved = 0
    seen = set()
    now = datetime.utcnow()
    for row in rows:
        matches = []
        lead = None
        for domain in domains:
            # The shared matcher omits single-letter terms. Require them here
            # so catalog entries such as C cannot match every training post.
            short_terms = re.findall(r'\b[a-zA-Z]\b', domain)
            if any(not re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)',
                                 _result_text(row), re.I) for term in short_terms):
                continue
            candidate = _normalize_result(row, domain, 'client')
            if candidate:
                matches.append(domain)
                lead = lead or candidate
        if not lead and include_unmatched:
            lead = _normalize_result(row, '', 'client')
            if lead:
                lead['domain'] = 'Unclassified'
        if not lead or post_identity(lead['source_url']) in seen:
            continue
        seen.add(post_identity(lead['source_url']))
        found += 1
        for domain in matches:
            counts[domain] += 1
        provider = row.get('discovery_provider', 'linkedin_account')
        lead.update(matched_domains=matches, discovery_provider=provider,
                    verification_status='unverified_linkedin_account' if provider == 'linkedin_account' else 'unverified_public_search',
                    discovered_at=now)
        saved += int(await save_client_post(lead, db, now))
    warnings = discovery.get('warnings', [])
    error = '; '.join(warning['error'] for warning in warnings) if discovery['status'] == 'blocked' else ''
    return {'found': found, 'saved_count': saved, 'scanned_posts': len(rows),
            'target': target, 'target_met': len(rows) >= target,
            'search_error': error, 'scan_warnings': warnings,
            'domain_outcomes': [{'domain': domain, 'matched': count,
                                 'status': 'matched' if count else 'no_match'}
                                for domain, count in counts.items()]}
