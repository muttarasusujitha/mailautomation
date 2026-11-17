"""Self-hosted trainer search: many key-free search engines, one deduplicated result list.

Every enabled engine runs in parallel over a plan of trainer queries for one
skill. Each engine pages through results while new LinkedIn profile links
appear, backs off when it refuses this server, and reports what happened.
The run stops when the target is reached, every query is used, or the time
budget ends. Profiles are checked against the requested skill and trainer
wording before they count toward the target.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

from app.clients.serp_engines import (
    EngineHealth, Fetcher, Pacer, canonical_profile_url, enabled_engines, fetch_results_page,
)

logger = logging.getLogger(__name__)

ROLE_PHRASES = (
    'trainer', '"corporate trainer"', '"freelance trainer"', '"technical trainer"',
    'instructor', '"training consultant"', '"corporate training"', 'mentor', 'faculty', 'coach',
)
CITIES = ('Bangalore', 'Hyderabad', 'Pune', 'Chennai', 'Mumbai', 'Delhi', 'Noida', 'Gurgaon', 'Kolkata', 'Ahmedabad')
_ROLE_WORDS = re.compile(r'\b(trainers?|instructors?|training|facilitators?|coach|mentor|faculty)\b', re.I)


def _env_float(name, default, low, high):
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def finder_enabled():
    return os.environ.get('TRAINER_FINDER_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')


def budget_seconds():
    return _env_float('TRAINER_FINDER_BUDGET_SECONDS', 180, 20, 500)


def _skill_text(skill):
    return ' '.join(_ROLE_WORDS.sub(' ', skill or '').split()) or (skill or '').strip()


def query_plan(skill, location=''):
    """Site-scoped profile queries first, then plain and city queries for wider coverage."""
    core = _skill_text(skill)
    place = (location or '').strip()
    quoted = f'"{core}"' if ' ' in core else core
    queries = []

    def add(text):
        text = ' '.join(text.split())
        if text and text not in queries:
            queries.append(text)

    for role in ROLE_PHRASES:
        add(f'site:linkedin.com/in {quoted} {role} {place}')
    add(f'site:in.linkedin.com/in {quoted} trainer {place}')
    add(f'{core} trainer linkedin {place}')
    add(f'{core} corporate trainer linkedin profile {place}')
    for city in CITIES:
        if place and city.lower() == place.lower():
            continue
        add(f'site:linkedin.com/in {quoted} trainer {city}')
    for role in ('freelance trainer', 'technical trainer', 'training consultant', 'online trainer'):
        add(f'{core} {role} linkedin {place}')
    return queries


def _default_qualifier(skill):
    from app.clients.search_accuracy import has_trainer_language, matches_requested_skill
    try:
        from app.routes.linkedin_leads import _normalize_result
    except Exception:  # The route module needs FastAPI; tests can run without it.
        _normalize_result = None

    def qualifies(row):
        if not (matches_requested_skill(row, skill) and has_trainer_language(row)):
            return False
        if _normalize_result is None:
            return True
        return bool(_normalize_result({**row, 'keyword_qualified': True}, skill, 'trainer'))
    return qualifies


def _score(row, skill):
    title = (row.get('title') or '').lower()
    text = (row.get('content') or '').lower()
    tokens = [token for token in re.findall(r'[a-z0-9+#.]+', _skill_text(skill).lower()) if len(token) > 1]
    score = 0
    score += 3 if tokens and all(token in title for token in tokens) else 0
    score += 1 if tokens and any(token in text for token in tokens) else 0
    score += 2 if _ROLE_WORDS.search(title) else 0
    score += len(row.get('engines') or []) - 1
    return score


class _Run:
    def __init__(self, skill, target, exclude, qualifies, deadline):
        self.skill = skill
        self.target = target
        self.exclude = {url.lower() for url in exclude or ()}
        self.qualifies = qualifies
        self.deadline = deadline
        self.candidates = {}
        self.qualified = {}
        self.already_saved = set()
        self.done = asyncio.Event()

    def time_left(self):
        return self.deadline - time.monotonic()

    def add(self, row, engine_name, query):
        """Merge one harvested row. Return True when the URL is new to this run."""
        url = canonical_profile_url(row.get('url'))
        if not url:
            return False
        if url.lower() in self.exclude:
            self.already_saved.add(url)
            return False
        existing = self.candidates.get(url)
        is_new = existing is None
        if is_new:
            existing = {'url': url, 'title': row.get('title') or '', 'snippet': '', 'content': '',
                        'engines': [], 'search_query': query}
            self.candidates[url] = existing
        if len(row.get('title') or '') > len(existing['title']):
            existing['title'] = row['title']
        snippet = row.get('snippet') or ''
        if snippet and snippet not in existing['snippet']:
            existing['snippet'] = f"{existing['snippet']} {snippet}".strip()[:1200]
        existing['content'] = f"{existing['title']} {existing['snippet']}".strip()
        if engine_name not in existing['engines']:
            existing['engines'].append(engine_name)
        if url not in self.qualified:
            check = {'url': url, 'title': existing['title'], 'snippet': existing['snippet'], 'content': existing['content']}
            if self.qualifies(check):
                self.qualified[url] = existing
                if len(self.qualified) >= self.target:
                    self.done.set()
        return is_new


def _engine_report(engine, **extra):
    return {'source': engine.name, 'label': engine.label, 'status': 'not_run', 'queries': 0, 'pages': 0,
            'browser_pages': 0, 'links_seen': 0, 'new_profiles': 0, 'qualified': 0, 'reason': '', **extra}


async def _run_engine(engine, queries, run, fetcher, health, report, offset):
    pacer = Pacer(engine.min_interval)
    errors_in_row = 0
    ordered = queries[offset:] + queries[:offset]
    for query in ordered:
        if run.done.is_set() or run.time_left() < 5:
            break
        report['queries'] += 1
        method, url, data = 'GET', engine.first_url(query), None
        for page_index in range(engine.max_pages):
            if run.done.is_set() or run.time_left() < 5:
                break
            await pacer.wait()
            page = await fetch_results_page(engine, fetcher, method, url, data)
            report['pages'] += 1
            report['browser_pages'] += int(page.via_browser)
            if page.status == 'blocked':
                until = health.record_block(engine.name)
                report.update(status='blocked', cooling_until=until.isoformat(),
                              reason=f'{engine.label} refused requests from this server (captcha or rate limit). '
                                     f'It will be retried after {until.strftime("%H:%M")} UTC.')
                return
            if page.status == 'error':
                errors_in_row += 1
                if errors_in_row >= 3:
                    report.update(status='error', reason=f'{engine.label} did not answer three requests in a row.')
                    return
                break
            errors_in_row = 0
            report['links_seen'] += page.links_seen
            new = sum(run.add(row, engine.name, query) for row in page.rows)
            report['new_profiles'] += new
            if page.status == 'empty' or not new:
                break
            # Next results page.
            if engine.next_form:
                step = engine.next_form(page.body)
                if not step:
                    break
                method, url, data = 'POST', step[0], step[1]
            elif engine.page_url:
                method, url, data = 'GET', engine.page_url(query, page_index + 1), None
            else:
                break
    health.record_ok(engine.name)


async def _run_tavily(queries, run, report):
    from app.routes.linkedin_leads import _plain_tavily_search
    for query in queries[:8]:
        if run.done.is_set() or run.time_left() < 5:
            break
        report['queries'] += 1
        try:
            rows = await _plain_tavily_search(query, 20)
        except Exception as exc:
            report.update(status='error', reason=f'Tavily failed: {str(exc)[:160]}')
            return
        report['pages'] += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = canonical_profile_url(row.get('url') or '')
            if not url:
                continue
            report['links_seen'] += 1
            report['new_profiles'] += run.add(
                {'url': url, 'title': row.get('title') or '', 'snippet': row.get('content') or ''}, 'tavily', query)


def _tavily_configured():
    if not os.environ.get('TAVILY_API_KEY'):
        try:
            from app.config import get_settings
            return bool(get_settings().TAVILY_API_KEY)
        except Exception:
            return False
    return True


def _finish_report(report, run):
    report['qualified'] = sum(1 for row in run.qualified.values() if report['source'] in row['engines'])
    if report['status'] in ('blocked', 'error', 'paused', 'not_configured'):
        return
    if report['queries'] == 0:
        report['status'] = 'not_needed'
        report['reason'] = report['reason'] or 'The target was reached before this source was needed.'
    elif report['qualified']:
        report['status'] = 'ok'
    elif report['links_seen']:
        report['status'] = 'filtered'
        report['reason'] = 'Returned LinkedIn profiles, but none matched the skill and trainer wording.'
    else:
        report['status'] = 'no_results'
        report['reason'] = 'Returned no LinkedIn profile links for these queries.'


def _limit_reason(reports, run, timed_out, queries_exhausted):
    if len(run.qualified) >= run.target:
        return ''
    parts = []
    blocked = [r['label'] for r in reports if r['status'] == 'blocked']
    paused = [r['label'] for r in reports if r['status'] == 'paused']
    failed = [r['label'] for r in reports if r['status'] == 'error']
    if blocked:
        parts.append(f"Blocked this run: {', '.join(blocked)}.")
    if paused:
        parts.append(f"Still cooling down from an earlier block: {', '.join(paused)}.")
    if failed:
        parts.append(f"Not answering: {', '.join(failed)}.")
    if timed_out:
        parts.append('The search time budget ran out.')
    elif queries_exhausted:
        parts.append('Every planned query was searched on every working engine.')
    if run.already_saved:
        parts.append(f'{len(run.already_saved)} matching profiles were skipped because they are already saved.')
    rejected = len(run.candidates) - len(run.qualified)
    if rejected > 0:
        parts.append(f'{rejected} profiles found did not match the skill or trainer wording and were left out.')
    return ' '.join(parts) or 'Search engines returned fewer matching trainer profiles than the target.'


async def find_trainers(skill, target, location='', exclude=(), qualifies=None, budget=None,
                        engines=None, fetcher=None, health=None):
    """Return (rows, report) with up to `target` qualified, deduplicated LinkedIn trainer profiles."""
    started = time.monotonic()
    target = max(1, int(target or 1))
    budget = budget if budget is not None else budget_seconds()
    queries = query_plan(skill, location)
    run = _Run(skill, target, exclude, qualifies or _default_qualifier(skill), started + budget)
    health = health or EngineHealth()
    owns_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(use_browser=os.environ.get('TRAINER_FINDER_BROWSER', 'true').lower() != 'false')
    engines = list(engines) if engines is not None else enabled_engines()

    reports, tasks = [], []
    for index, engine in enumerate(engines):
        cooling = health.cooling_until(engine.name)
        if cooling:
            reports.append(_engine_report(
                engine, status='paused', cooling_until=cooling.isoformat(),
                reason=f'{engine.label} refused this server earlier; retrying after {cooling.strftime("%H:%M")} UTC.'))
            continue
        report = _engine_report(engine)
        reports.append(report)
        offset = (index * 3) % max(1, len(queries))
        tasks.append(asyncio.create_task(_run_engine(engine, queries, run, fetcher, health, report, offset)))

    tavily = {'source': 'tavily', 'label': 'Tavily (optional)', 'status': 'not_configured', 'queries': 0,
              'pages': 0, 'browser_pages': 0, 'links_seen': 0, 'new_profiles': 0, 'qualified': 0,
              'reason': 'TAVILY_API_KEY is not set. This source is optional.'}
    if _tavily_configured():
        tavily.update(status='not_run', reason='')
        tasks.append(asyncio.create_task(_run_tavily(queries, run, tavily)))
    reports.append(tavily)

    timed_out = False
    waiter = asyncio.create_task(run.done.wait())
    try:
        pending = set(tasks)
        # Stop when every source finished, the target is met, or the budget ends.
        while pending and not run.done.is_set():
            done, _ = await asyncio.wait(
                pending | {waiter}, timeout=max(0.5, run.time_left()), return_when=asyncio.FIRST_COMPLETED)
            if not done:
                timed_out = True
                break
            pending -= done
        timed_out = timed_out or (bool(tasks) and run.time_left() < 5 and not run.done.is_set())
    finally:
        waiter.cancel()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if owns_fetcher:
            await fetcher.close()

    for task in tasks:
        if task.done() and not task.cancelled() and task.exception():
            logger.warning('Trainer search source failed: %r', task.exception())
    for report in reports:
        _finish_report(report, run)

    ranked = sorted(run.qualified.values(), key=lambda row: _score(row, skill), reverse=True)[:target]
    rows = [{'url': row['url'], 'title': row['title'], 'snippet': row['snippet'], 'content': row['content'],
             'search_query': row['search_query'], 'engines': list(row['engines']),
             'keyword_qualified': True, 'discovery_provider': 'trainer_finder'} for row in ranked]
    working = [r for r in reports if r['status'] not in ('blocked', 'paused', 'error', 'not_configured')]
    queries_exhausted = bool(working) and not timed_out and not run.done.is_set()
    matched = len(rows)
    report = {
        'source': 'trainer_finder',
        'target': target,
        'matched': matched,
        'target_met': matched >= target,
        'status': 'target_met' if matched >= target else 'partial' if matched else
                  'blocked' if not working else 'no_results',
        'candidates_seen': len(run.candidates),
        'already_saved': len(run.already_saved),
        'queries_planned': len(queries),
        'elapsed_seconds': round(time.monotonic() - started, 1),
        'finished_at': datetime.now(timezone.utc).isoformat(),
        'sources': reports,
        'limit_reason': _limit_reason(reports, run, timed_out, queries_exhausted),
    }
    return rows, report
