import asyncio
from urllib.parse import parse_qs, urlsplit

from app.clients import trainer_finder
from app.clients.serp_engines import Engine, EngineHealth
from app.clients.trainer_finder import find_trainers, query_plan


def card(slug, title, snippet=''):
    return (f'<li><h2><a href="https://in.linkedin.com/in/{slug}">{title}</a></h2>'
            f'<p>{snippet}</p></li>').encode()


def page(*cards):
    return b'<html><body><ol>' + b''.join(cards) + b'</ol></body></html>'


def engine(name, max_pages=3):
    host = f'www.{name}.test'
    return Engine(name, name.title(), host,
                  lambda q, h=host: f'https://{h}/search?q={q}&p=0',
                  page_url=lambda q, i, h=host: f'https://{h}/search?q={q}&p={i}',
                  max_pages=max_pages, min_interval=0, browser_fallback=False)


class Fetcher:
    """Serve pages by (host, page number). Unknown pages are empty result pages."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []
        self.browser_available = False

    async def http(self, method, url, data=None):
        parts = urlsplit(url)
        number = int(parse_qs(parts.query).get('p', ['0'])[0])
        self.requests.append((parts.hostname, number))
        reply = self.pages.get((parts.hostname, number), (200, page()))
        return reply(url) if callable(reply) else reply


def no_filter(row):
    return True


def run(*args, **kwargs):
    kwargs.setdefault('qualifies', no_filter)
    kwargs.setdefault('budget', 30)
    return asyncio.run(find_trainers(*args, **kwargs))


def test_query_plan_targets_linkedin_profiles_for_the_skill():
    queries = query_plan('Python trainer', 'Pune')
    assert queries[0] == 'site:linkedin.com/in Python trainer Pune'
    assert 'site:linkedin.com/in Python "corporate trainer" Pune' in queries
    assert 'site:linkedin.com/in Python trainer Bangalore' in queries
    assert all('Pune' not in q for q in queries if q.endswith('Pune trainer'))
    assert len(queries) == len(set(queries)) >= 25
    assert query_plan('Power BI')[0] == 'site:linkedin.com/in "Power BI" trainer'


def test_merges_engines_dedupes_and_skips_saved_profiles(tmp_path):
    fetcher = Fetcher({
        ('www.alpha.test', 0): (200, page(card('ravi', 'Ravi - Python Trainer'), card('saved-one', 'Saved - Python Trainer'))),
        ('www.beta.test', 0): (200, page(card('ravi', 'Ravi - Python Trainer', 'Python corporate trainer, Bangalore'),
                                         card('asha', 'Asha - Python Instructor'))),
    })
    rows, report = run('Python', 60, exclude={'https://www.linkedin.com/in/saved-one'},
                       engines=[engine('alpha'), engine('beta')], fetcher=fetcher,
                       health=EngineHealth(tmp_path / 'h.json'))
    urls = [row['url'] for row in rows]
    assert sorted(urls) == ['https://www.linkedin.com/in/asha', 'https://www.linkedin.com/in/ravi']
    ravi = next(row for row in rows if row['url'].endswith('/ravi'))
    assert sorted(ravi['engines']) == ['alpha', 'beta']
    assert 'Bangalore' in ravi['snippet']
    assert urls[0].endswith('/ravi')  # Found by two engines, ranked first.
    assert report['already_saved'] == 1
    assert report['status'] == 'partial' and not report['target_met']
    assert {s['source']: s['status'] for s in report['sources']} == {'alpha': 'ok', 'beta': 'ok', 'tavily': 'not_configured'}
    assert 'already saved' in report['limit_reason']
    assert 'Every planned query was searched' in report['limit_reason']


def test_stops_once_the_target_is_met(tmp_path):
    cards = [card(f'trainer-{i}', f'Trainer {i} - Java Trainer') for i in range(10)]
    fetcher = Fetcher({('www.alpha.test', 0): (200, page(*cards))})
    rows, report = run('Java', 5, engines=[engine('alpha')], fetcher=fetcher, health=EngineHealth(tmp_path / 'h.json'))
    assert len(rows) == 5
    assert report['target_met'] and report['status'] == 'target_met' and report['limit_reason'] == ''
    assert len(fetcher.requests) == 1


def test_pages_while_new_profiles_appear(tmp_path):
    fetcher = Fetcher({
        ('www.alpha.test', 0): (200, page(card('anil', 'A - SAP Trainer'))),
        ('www.alpha.test', 1): (200, page(card('bala', 'B - SAP Trainer'))),
        ('www.alpha.test', 2): (200, page(card('chitra', 'C - SAP Trainer'))),
    })
    rows, report = run('SAP', 3, engines=[engine('alpha')], fetcher=fetcher, health=EngineHealth(tmp_path / 'h.json'))
    assert len(rows) == 3
    assert fetcher.requests[:3] == [('www.alpha.test', 0), ('www.alpha.test', 1), ('www.alpha.test', 2)]


def test_blocked_engine_cools_down_and_others_keep_working(tmp_path):
    health_path = tmp_path / 'h.json'
    fetcher = Fetcher({
        ('www.alpha.test', 0): (429, b''),
        ('www.beta.test', 0): (200, page(card('ravi', 'Ravi - AWS Trainer'))),
    })
    rows, report = run('AWS', 60, engines=[engine('alpha'), engine('beta')], fetcher=fetcher,
                       health=EngineHealth(health_path))
    sources = {s['source']: s for s in report['sources']}
    assert sources['alpha']['status'] == 'blocked' and sources['alpha']['cooling_until']
    assert sources['beta']['status'] == 'ok'
    assert len(rows) == 1
    assert 'Blocked this run: Alpha' in report['limit_reason']
    # Alpha is asked once, then skipped for the rest of the run and the next one.
    assert fetcher.requests.count(('www.alpha.test', 0)) == 1
    _, again = run('AWS', 60, engines=[engine('alpha'), engine('beta')], fetcher=Fetcher({}),
                   health=EngineHealth(health_path))
    assert {s['source']: s['status'] for s in again['sources']}['alpha'] == 'paused'
    assert 'cooling down' in again['limit_reason']


def test_every_engine_blocked_is_reported_blocked(tmp_path):
    fetcher = Fetcher({('www.alpha.test', 0): (403, b'')})
    rows, report = run('Python', 60, engines=[engine('alpha')], fetcher=fetcher, health=EngineHealth(tmp_path / 'h.json'))
    assert rows == [] and report['status'] == 'blocked'


def test_irrelevant_profiles_are_filtered_by_the_default_qualifier(tmp_path):
    fetcher = Fetcher({('www.alpha.test', 0): (200, page(
        card('good', 'Neha - Python Corporate Trainer'),
        card('engineer', 'Kiran - Python Developer at Acme'),
        card('other-skill', 'Raj - Java Trainer'),
    ))})
    rows, report = asyncio.run(find_trainers(
        'Python', 60, engines=[engine('alpha')], fetcher=fetcher, budget=30, health=EngineHealth(tmp_path / 'h.json')))
    assert [row['url'] for row in rows] == ['https://www.linkedin.com/in/good']
    assert report['candidates_seen'] == 3
    assert '2 profiles found did not match' in report['limit_reason']


def test_time_budget_ends_the_run(tmp_path, monkeypatch):
    async def slow(method, url, data=None):
        await asyncio.sleep(10)
        return 200, page()
    fetcher = Fetcher({})
    fetcher.http = slow
    rows, report = run('Python', 60, engines=[engine('alpha')], fetcher=fetcher, budget=6,
                       health=EngineHealth(tmp_path / 'h.json'))
    assert rows == []
    assert report['elapsed_seconds'] < 9
    assert 'time budget' in report['limit_reason']


def test_finder_can_be_switched_off(monkeypatch):
    monkeypatch.setenv('TRAINER_FINDER_ENABLED', 'false')
    assert not trainer_finder.finder_enabled()
    monkeypatch.setenv('TRAINER_FINDER_ENABLED', 'true')
    assert trainer_finder.finder_enabled()
