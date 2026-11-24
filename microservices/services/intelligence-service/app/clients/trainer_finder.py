"""Self-hosted LinkedIn lead finder: many key-free search engine agents, one deduplicated list.

No search API or API key is used. Each engine agent reads public result pages.

Two kinds of leads are found for one domain (skill):
- trainer: LinkedIn profiles (/in/) of trainers for the skill;
- client:  recent LinkedIn posts (/posts/, /feed/update/) where someone needs a
           trainer for the skill.

Every enabled engine runs in parallel over a plan of queries. Each engine pages
through results while new links appear, reads extra pages when an engine is
productive, drops out after many empty queries, and backs off when it refuses
this server. The run stops when the target is reached, every query is used, or
the time budget ends. A lead counts only after it passes the same checks as the
LinkedIn account results.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from app.clients.serp_engines import (
    CANONICAL, EngineHealth, Fetcher, Pacer, enabled_engines, fetch_results_page, post_key, with_params,
)

logger = logging.getLogger(__name__)

ROLE_PHRASES = (
    'trainer', '"corporate trainer"', '"freelance trainer"', '"technical trainer"',
    'instructor', '"training consultant"', '"corporate training"', 'mentor', 'faculty', 'coach',
)
CLIENT_PHRASES = (
    '"trainer required"', '"looking for a trainer"', '"looking for trainer"', '"need a trainer"',
    '"freelance trainer required"', '"corporate trainer required"', '"training requirement"',
    '"seeking trainer"', '"trainers needed"', '"looking for freelance trainer"',
    '"require trainer"', '"training partner"',
)
CITIES = ('Bangalore', 'Hyderabad', 'Pune', 'Chennai', 'Mumbai', 'Delhi', 'Noida', 'Gurgaon', 'Kolkata', 'Ahmedabad')
# Common alternative names. Profiles often use the long form.
SKILL_ALIASES = {
    'aws': ('Amazon Web Services',),
    'gcp': ('Google Cloud',),
    'azure': ('Microsoft Azure',),
    'js': ('JavaScript',),
    'ml': ('Machine Learning',),
    'ai': ('Artificial Intelligence',),
    'genai': ('Generative AI',),
    'gen ai': ('Generative AI',),
    'k8s': ('Kubernetes',),
    'sfdc': ('Salesforce',),
    'rpa': ('Robotic Process Automation',),
    'bi': ('Business Intelligence',),
    'ui ux': ('UI/UX design',),
}
_ROLE_WORDS = re.compile(r'\b(trainers?|instructors?|training|facilitators?|coach|mentor|faculty)\b', re.I)
_NEED_WORDS = re.compile(r'\b(need|needs|needed|looking (?:out )?for|require|requires|required|requirements?|hiring|seeking)\b', re.I)
_CONTACT = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|(?:\+91[\s-]?)?[6-9]\d{9}\b')
_MAX_EMPTY_QUERIES = 6


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


def client_post_max_age():
    """'week', 'month' (default) or 'any'. Engines without a date filter ignore it."""
    value = os.environ.get('CLIENT_POST_MAX_AGE', 'month').strip().lower()
    return value if value in ('week', 'month', 'any') else 'month'


def _skill_text(skill):
    return ' '.join(_ROLE_WORDS.sub(' ', skill or '').split()) or (skill or '').strip()


def skill_aliases(skill):
    return SKILL_ALIASES.get(_skill_text(skill).lower(), ())


def _quote(text):
    return f'"{text}"' if ' ' in text else text


def query_plan(skill, location='', mode='trainer'):
    """Site-scoped queries first, then alias, city and plain queries for wider coverage."""
    core = _skill_text(skill)
    place = (location or '').strip()
    quoted = _quote(core)
    queries = []

    def add(text):
        text = ' '.join(text.split())
        if text and text not in queries:
            queries.append(text)

    if mode == 'client':
        for phrase in CLIENT_PHRASES[:4]:
            add(f'site:linkedin.com/posts {quoted} {phrase} {place}')
        # Search engines differ in how they index LinkedIn post paths. Try
        # broad indexed-result queries before the long city expansion.
        for phrase in CLIENT_PHRASES[:4]:
            add(f'{quoted} {phrase} LinkedIn {place}')
        for phrase in CLIENT_PHRASES[4:]:
            add(f'site:linkedin.com/posts {quoted} {phrase} {place}')
        for phrase in CLIENT_PHRASES[:4]:
            add(f'site:linkedin.com/feed/update {quoted} {phrase} {place}')
        for city in CITIES:
            if not (place and city.lower() == place.lower()):
                add(f'site:linkedin.com/posts {quoted} "trainer required" {city}')
        add(f'{core} trainer required linkedin post {place}')
        add(f'{core} looking for freelance trainer linkedin {place}')
        return queries

    for role in ROLE_PHRASES:
        add(f'site:linkedin.com/in {quoted} {role} {place}')
    # Broaden beyond site-scoped indexing early so a sparse exact query does
    # not spend the engine's empty-query budget before trying general search.
    for role in ('corporate trainer', 'freelance trainer', 'technical trainer', 'instructor'):
        add(f'{core} {role} linkedin {place}')
    add(f'site:in.linkedin.com/in {quoted} trainer {place}')
    for alias in skill_aliases(skill):
        add(f'site:linkedin.com/in {_quote(alias)} trainer {place}')
        add(f'site:linkedin.com/in {_quote(alias)} "corporate trainer" {place}')
    add(f'{core} trainer linkedin {place}')
    add(f'{core} corporate trainer linkedin profile {place}')
    for city in CITIES:
        if not (place and city.lower() == place.lower()):
            add(f'site:linkedin.com/in {quoted} trainer {city}')
    for role in ('freelance trainer', 'technical trainer', 'training consultant', 'online trainer'):
        add(f'{core} {role} linkedin {place}')
    return queries


def _route_normalizer():
    try:
        from app.routes.linkedin_leads import _normalize_result
        return _normalize_result
    except Exception:  # The route module needs FastAPI; unit tests run without it.
        return None


def _skill_tokens(skill):
    return [t for t in re.findall(r'[a-z0-9+#.]+', _skill_text(skill).lower()) if len(t) > 1 or t in ('c', 'r')]


def _default_qualifier(skill, mode):
    from app.clients.search_accuracy import has_trainer_language, matches_requested_skill
    normalize = _route_normalizer()
    aliases = [alias.lower() for alias in skill_aliases(skill)]

    if mode == 'client':
        tokens = _skill_tokens(skill)

        def qualifies(row):
            text = f"{row.get('title', '')} {row.get('content', '')}".lower()
            if normalize is not None:
                return bool(normalize(row, skill, 'client'))
            return bool(_NEED_WORDS.search(text) and _ROLE_WORDS.search(text)
                        and all(token in text for token in tokens))
        return qualifies

    def qualifies(row):
        text = f"{row.get('title', '')} {row.get('content', '')}".lower()
        skill_found = matches_requested_skill(row, skill) or any(alias in text for alias in aliases)
        if not (skill_found and has_trainer_language(row)):
            return False
        if normalize is None:
            return True
        return bool(normalize({**row, 'keyword_qualified': True}, skill, 'trainer'))
    return qualifies


def _score(row, skill, mode):
    title = (row.get('title') or '').lower()
    text = (row.get('content') or '').lower()
    tokens = _skill_tokens(skill)
    score = len(row.get('engines') or []) - 1
    score += 3 if tokens and all(token in title for token in tokens) else 0
    score += 1 if tokens and any(token in text for token in tokens) else 0
    if mode == 'client':
        score += 2 if _NEED_WORDS.search(text) else 0
        score += 2 if _CONTACT.search(text) else 0
    else:
        score += 2 if _ROLE_WORDS.search(title) else 0
    return score


class _Run:
    def __init__(self, skill, target, mode, exclude, qualifies, deadline):
        self.skill = skill
        self.target = target
        self.mode = mode
        self.canonical = CANONICAL['post' if mode == 'client' else 'profile']
        self.exclude = {self.key(url) for url in exclude or () if url}
        self.qualifies = qualifies
        self.deadline = deadline
        self.candidates = {}
        self.qualified = {}
        self.already_saved = set()
        self.done = asyncio.Event()
        age = client_post_max_age() if mode == 'client' else 'any'
        self.post_cutoff = (datetime.now(timezone.utc) - timedelta(days=7 if age == 'week' else 30)
                            if age in ('week', 'month') else None)

    def key(self, url):
        return post_key(url) if self.mode == 'client' and not str(url).startswith('linkedin:') else str(url).lower()

    def time_left(self):
        return self.deadline - time.monotonic()

    def add(self, row, engine_name, query):
        """Merge one harvested row. Return True when the lead is new to this run."""
        url = self.canonical(row.get('url'))
        if not url:
            return False
        if self.post_cutoff:
            # Search-engine date parameters can fail silently. LinkedIn post
            # activity IDs encode creation time; enforce the requested window
            # locally so stale posts never pass as recent.
            match = re.search(r'(?:activity[-:]|urn:li:activity:)(\d{6,})', url, re.I)
            if not match:
                return False
            created = datetime.fromtimestamp((int(match.group(1)) >> 22) / 1000, tz=timezone.utc)
            if created < self.post_cutoff:
                return False
        key = self.key(url)
        if key in self.exclude:
            self.already_saved.add(key)
            return False
        existing = self.candidates.get(key)
        is_new = existing is None
        if is_new:
            existing = {'url': url, 'title': row.get('title') or '', 'snippet': '', 'content': '',
                        'engines': [], 'search_query': query}
            self.candidates[key] = existing
        if len(row.get('title') or '') > len(existing['title']):
            existing['title'] = row['title']
        snippet = row.get('snippet') or ''
        if snippet and snippet not in existing['snippet']:
            existing['snippet'] = f"{existing['snippet']} {snippet}".strip()[:1500]
        existing['content'] = f"{existing['title']} {existing['snippet']}".strip()
        if engine_name not in existing['engines']:
            existing['engines'].append(engine_name)
        if key not in self.qualified:
            check = {'url': url, 'title': existing['title'], 'snippet': existing['snippet'], 'content': existing['content']}
            if self.qualifies(check):
                self.qualified[key] = existing
                if len(self.qualified) >= self.target:
                    self.done.set()
        return is_new


def _engine_report(engine, **extra):
    return {'source': engine.name, 'label': engine.label, 'status': 'not_run', 'queries': 0, 'pages': 0,
            'browser_pages': 0, 'links_seen': 0, 'new_profiles': 0, 'qualified': 0, 'reason': '', **extra}


async def _run_engine(engine, queries, run, fetcher, health, report, offset, recent):
    pacer = Pacer(engine.min_interval)
    kind = 'post' if run.mode == 'client' else 'profile'
    extra = engine.recent.get(recent, {}) if recent else {}
    errors_in_row = 0
    empty_queries = 0
    ordered = queries[offset:] + queries[:offset]
    for query in ordered:
        if run.done.is_set() or run.time_left() < 5:
            break
        report['queries'] += 1
        method, url, data = 'GET', with_params(engine.first_url(query), extra), None
        query_links = 0
        max_pages = engine.max_pages
        page_index = 0
        while page_index < max_pages:
            if run.done.is_set() or run.time_left() < 5:
                break
            await pacer.wait()
            page = await fetch_results_page(engine, fetcher, method, url, data, kind)
            report['pages'] += 1
            report['browser_pages'] += int(page.via_browser)
            if report['pages'] == 1:
                _save_debug_page(engine.name, query, page)
            if page.status == 'blocked':
                until = health.record_block(engine.name)
                report.update(status='blocked', cooling_until=until.isoformat(),
                              reason=f'{page.reason or f"{engine.label} refused this request"} '
                                     f'It will be retried after {until.strftime("%H:%M")} UTC.')
                return
            if page.status == 'error':
                errors_in_row += 1
                report['reason'] = page.reason
                if errors_in_row >= 3:
                    report.update(status='error', reason=f'{engine.label} did not answer three requests in a row.')
                    return
                break
            errors_in_row = 0
            report['links_seen'] += page.links_seen
            query_links += page.links_seen
            new = sum(run.add(row, engine.name, query) for row in page.rows)
            report['new_profiles'] += new
            if page.status == 'empty' or not new:
                break
            # A productive query earns two extra pages.
            if new >= 3 and max_pages == engine.max_pages:
                max_pages += 2
            page_index += 1
            if engine.next_form:
                step = engine.next_form(page.body)
                if not step:
                    break
                method, url, data = 'POST', step[0], {**step[1], **extra}
            elif engine.page_url:
                method, url, data = 'GET', with_params(engine.page_url(query, page_index), extra), None
            else:
                break
        empty_queries = 0 if query_links else empty_queries + 1
        if empty_queries >= _MAX_EMPTY_QUERIES:
            report['reason'] = f'Stopped after {_MAX_EMPTY_QUERIES} queries in a row returned no LinkedIn links.'
            break
    health.record_ok(engine.name)


def _save_debug_page(engine_name, query, page):
    """TRAINER_FINDER_DEBUG_DIR=/tmp/finder saves each engine's first results page for checking the parser."""
    folder = os.environ.get('TRAINER_FINDER_DEBUG_DIR', '').strip()
    if not folder or not page.body:
        return
    try:
        from pathlib import Path
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        (path / f'{engine_name}.html').write_bytes(page.body)
        (path / f'{engine_name}.query.txt').write_text(query)
    except OSError:
        logger.warning('Could not save a debug results page to %s', folder)


def _finish_report(report, run):
    noun = 'posts' if run.mode == 'client' else 'profiles'
    want = 'the domain and a trainer requirement' if run.mode == 'client' else 'the skill and trainer wording'
    report['qualified'] = sum(1 for row in run.qualified.values() if report['source'] in row['engines'])
    if report['status'] in ('blocked', 'error', 'paused'):
        return
    if report['queries'] == 0:
        report['status'] = 'not_needed'
        report['reason'] = report['reason'] or 'The target was reached before this source was needed.'
    elif report['qualified']:
        report['status'] = 'ok'
    elif report['links_seen']:
        report['status'] = 'filtered'
        report['reason'] = f'Returned LinkedIn {noun}, but none matched {want}.'
    else:
        report['status'] = 'no_results'
        report['reason'] = report['reason'] or f'Returned no LinkedIn {noun} for these queries.'


def _limit_reason(reports, run, timed_out, queries_exhausted):
    if len(run.qualified) >= run.target:
        return ''
    noun = 'posts' if run.mode == 'client' else 'profiles'
    want = 'the domain or a trainer requirement' if run.mode == 'client' else 'the skill or trainer wording'
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
        parts.append(f'{len(run.already_saved)} matching {noun} were skipped because they are already saved.')
    rejected = len(run.candidates) - len(run.qualified)
    if rejected > 0:
        parts.append(f'{rejected} {noun} found did not match {want} and were left out.')
    return ' '.join(parts) or f'Search engines returned fewer matching {noun} than the target.'


async def find_leads(skill, target, location='', mode='trainer', exclude=(), qualifies=None, budget=None,
                     engines=None, fetcher=None, health=None):
    """Return (rows, report) with up to `target` qualified, deduplicated LinkedIn leads.

    mode='trainer' finds trainer profiles; mode='client' finds posts asking for a trainer.
    """
    mode = 'client' if mode == 'client' else 'trainer'
    started = time.monotonic()
    target = max(1, int(target or 1))
    budget = budget if budget is not None else budget_seconds()
    queries = query_plan(skill, location, mode)
    run = _Run(skill, target, mode, exclude, qualifies or _default_qualifier(skill, mode), started + budget)
    health = health or EngineHealth()
    owns_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(use_browser=os.environ.get('TRAINER_FINDER_BROWSER', 'true').lower() != 'false')
    engines = list(engines) if engines is not None else enabled_engines()
    recent = client_post_max_age() if mode == 'client' else ''
    recent = '' if recent == 'any' else recent

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
        tasks.append(asyncio.create_task(_run_engine(engine, queries, run, fetcher, health, report, offset, recent)))

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
            logger.warning('Lead search source failed: %r', task.exception())
    for report in reports:
        _finish_report(report, run)

    ranked = sorted(run.qualified.values(), key=lambda row: _score(row, skill, mode), reverse=True)[:target]
    rows = []
    for row in ranked:
        item = {'url': row['url'], 'title': row['title'], 'snippet': row['snippet'], 'content': row['content'],
                'search_query': row['search_query'], 'engines': list(row['engines']),
                'discovery_provider': 'trainer_finder'}
        if mode == 'trainer':
            item['keyword_qualified'] = True
        rows.append(item)
    working = [r for r in reports if r['status'] not in ('blocked', 'paused', 'error')]
    queries_exhausted = bool(working) and not timed_out and not run.done.is_set()
    matched = len(rows)
    report = {
        'source': 'trainer_finder',
        'mode': mode,
        'target': target,
        'matched': matched,
        'target_met': matched >= target,
        'status': 'target_met' if matched >= target else 'partial' if matched else
                  'blocked' if not working else 'no_results',
        'candidates_seen': len(run.candidates),
        'already_saved': len(run.already_saved),
        'queries_planned': len(queries),
        'recent_filter': recent or 'any',
        'elapsed_seconds': round(time.monotonic() - started, 1),
        'finished_at': datetime.now(timezone.utc).isoformat(),
        'sources': reports,
        'limit_reason': _limit_reason(reports, run, timed_out, queries_exhausted),
    }
    return rows, report


async def find_trainers(skill, target, location='', **kwargs):
    """Trainer profiles only. Kept for callers that do not pass a mode."""
    return await find_leads(skill, target, location, mode='trainer', **kwargs)
