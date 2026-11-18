"""Per-source search status, the success rule, saved run reports, and saved lead IDs in search results."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import pytest

from app.clients.public_search import engine_sources, search_public_many
from app.clients.search_runs import failure_summary, merge_sources, search_succeeded
from fake_mongo import FakeDB


class _Page:
    def __init__(self, status, body=b''):
        self.status_code = status
        self.content = body


def ddg_page(*slugs):
    html = ''
    for slug in slugs:
        target = quote(f'https://www.linkedin.com/in/{slug}', safe='')
        html += (f'<a class="result__a" href="//duckduckgo.com/l/?uddg={target}">{slug} Python trainer</a>'
                 f'<a class="result__snippet" href="//duckduckgo.com/l/?uddg={target}">Python corporate trainer</a>')
    return _Page(200, html.encode())


def run_many(responses, queries=('q1',), limit=10):
    sequence = list(responses)

    async def fetch(method, url, **kwargs):
        return sequence.pop(0)

    report = {}
    with patch('app.clients.public_search._fetch', side_effect=fetch):
        rows, _attempts = asyncio.run(search_public_many(list(queries), limit, report=report))
    return rows, report


def by_source(sources):
    return {item['source']: item for item in sources}


def test_a_bot_check_and_a_timeout_are_reported_separately():
    # Warm-up page, a DuckDuckGo challenge page, then Bing does not answer.
    rows, report = run_many([(_Page(200), False), (_Page(202, b'anomaly-modal'), False), (None, True)])
    sources = by_source(engine_sources(report))
    assert rows == []
    assert sources['duckduckgo']['status'] == 'blocked' and 'not bypassed' in sources['duckduckgo']['reason']
    assert sources['bing']['status'] == 'error' and 'did not answer' in sources['bing']['reason']


def test_results_that_fail_later_checks_are_filtered_and_bing_is_not_needed():
    rows, report = run_many([(_Page(200), False), (ddg_page('ravi', 'asha'), False)])
    assert [row['url'] for row in rows] == ['https://www.linkedin.com/in/ravi', 'https://www.linkedin.com/in/asha']
    kept = by_source(engine_sources(report, ['https://www.linkedin.com/in/asha']))
    assert kept['duckduckgo'] == {'source': 'duckduckgo', 'label': 'DuckDuckGo', 'status': 'ok', 'found': 2,
                                  'qualified': 1, 'reason': ''}
    assert kept['bing']['status'] == 'not_needed'
    assert by_source(engine_sources(report, []))['duckduckgo']['status'] == 'filtered'


def test_success_rule_and_merging():
    blocked = {'source': 'bing', 'label': 'Bing', 'status': 'blocked', 'reason': 'refused'}
    empty = {'source': 'bing', 'label': 'Bing', 'status': 'no_results', 'reason': 'none'}
    worked = {'source': 'bing', 'label': 'Bing', 'status': 'ok', 'found': 3, 'qualified': 2}
    assert not search_succeeded(0, [blocked]) and search_succeeded(0, [blocked, empty]) and search_succeeded(1, [blocked])
    assert failure_summary([blocked]).startswith('No search source gave an answer. Bing: refused')
    assert failure_summary([blocked, empty]) == ''
    merged = merge_sources([[worked], [blocked]])
    assert merged == [{'source': 'bing', 'label': 'Bing', 'status': 'ok', 'found': 3, 'qualified': 2, 'reason': '',
                       'note': 'Failed on 1 of 2 searches: refused'}]


def test_naukri_search_reports_each_engine():
    from app.clients.naukri_public_search import search_public_naukri_profiles

    async def fake_many(queries, limit, domains, report=None):
        report['duckduckgo'] = {'attempts': 4, 'found': 2, 'challenged': 0, 'refused': 0, 'timeouts': 0,
                                'urls': ['https://www.naukri.com/resume/java-dev', 'https://www.naukri.com/java-jobs']}
        report['bing'] = {'attempts': 0, 'found': 0, 'skipped': 'enough', 'urls': []}
        return [{'url': 'https://www.naukri.com/resume/java-dev', 'title': 'Java dev', 'content': 'Java'},
                {'url': 'https://www.naukri.com/java-jobs', 'title': 'Java jobs', 'content': 'Java'}], 4

    report = {}
    with patch('app.clients.naukri_public_search.search_public_many', side_effect=fake_many):
        profiles = asyncio.run(search_public_naukri_profiles('Java', '', 10, report=report))
    assert len(profiles) == 1
    sources = by_source(report['sources'])
    assert sources['duckduckgo']['status'] == 'ok' and sources['duckduckgo']['qualified'] == 1
    assert sources['bing']['status'] == 'not_needed'


class FakeClient:
    """Stands in for httpx.AsyncClient. handler(url, json) returns an httpx.Response or raises."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get('json')))
        result = self.handler(url, kwargs.get('json'))
        if isinstance(result, Exception):
            raise result
        return result


def response(status, payload=None, url='http://test'):
    return httpx.Response(status, json=payload if payload is not None else {}, request=httpx.Request('POST', url))


def free_search(settings, **patches):
    from app.routes import free_search as module
    payload = module.FreeSearchRequest(domain='Python', query='Python', max_results=20, include_domains=['linkedin.com'])
    with patch.object(module, 'get_settings', return_value=settings):
        return asyncio.run(module.free_search_trainers(payload, None))


def test_free_search_without_a_key_reports_tavily_and_the_engines():
    async def fake_many(queries, limit, allowed_domains=None, report=None):
        report['duckduckgo'] = {'attempts': 1, 'found': 0, 'challenged': 1, 'refused': 0, 'timeouts': 0, 'urls': []}
        report['bing'] = {'attempts': 1, 'found': 0, 'challenged': 0, 'refused': 1, 'timeouts': 0, 'urls': []}
        return [], 1

    with patch('app.clients.public_search.search_public_many', side_effect=fake_many):
        result = free_search(SimpleNamespace(TAVILY_API_KEY=''))
    sources = by_source(result['sources'])
    assert sources['tavily']['status'] == 'not_configured'
    assert sources['duckduckgo']['status'] == sources['bing']['status'] == 'blocked'
    assert result['found'] == 0 and result['success'] is False


def test_free_search_reports_a_tavily_rate_limit():
    settings = SimpleNamespace(TAVILY_API_KEY='key', TAVILY_API_URL='https://api.tavily.com', TAVILY_SEARCH_DEPTH='basic')
    client = FakeClient(lambda url, body: response(429, {'detail': 'limit'}, url))
    with patch('httpx.AsyncClient', client):
        result = free_search(settings)
    tavily = by_source(result['sources'])['tavily']
    assert tavily['status'] == 'blocked' and 'HTTP 429' in tavily['reason']
    assert result['success'] is False


def test_free_search_credits_tavily_with_kept_profiles():
    settings = SimpleNamespace(TAVILY_API_KEY='key', TAVILY_API_URL='https://api.tavily.com', TAVILY_SEARCH_DEPTH='basic')
    year = datetime.utcnow().year
    rows = {'results': [{'url': 'https://www.linkedin.com/in/ravi', 'title': f'Python corporate trainer {year}',
                         'content': 'Python trainer, present'}]}
    with patch('httpx.AsyncClient', FakeClient(lambda url, body: response(200, rows, url))):
        result = free_search(settings)
    assert result['found'] == 1 and 'result_url' not in result['profiles'][0]
    assert by_source(result['sources'])['tavily']['status'] == 'ok'


def trainer_search_public(db, client, **fields):
    from app.routes.trainer_profile_leads import SearchPublicRequest, search_public_trainer_leads
    with patch('httpx.AsyncClient', client):
        return asyncio.run(search_public_trainer_leads(SearchPublicRequest(**fields), db))


def test_trainer_search_public_saves_once_and_records_the_run():
    db = FakeDB()
    asyncio.run(db['trainer_profile_leads'].insert_one({'lead_id': 'TPL-OLD', 'source_url': 'https://www.linkedin.com/in/asha',
                                                        'status': 'reviewed', 'created_at': datetime(2026, 1, 1)}))
    found = {'profiles': [{'source_url': 'https://linkedin.com/in/ravi', 'slug': 'ravi', 'source': 'linkedin', 'title': 'Ravi'},
                          {'source_url': 'https://linkedin.com/in/asha', 'slug': 'asha', 'source': 'linkedin', 'title': 'Asha'}],
             'sources': [{'source': 'tavily', 'label': 'Tavily', 'status': 'ok', 'found': 2, 'qualified': 2, 'reason': ''}]}
    client = FakeClient(lambda url, body: response(200, found, url))
    result = trainer_search_public(db, client, domain='Python', query='Python', source='linkedin', max_results=50)
    # The same query and domain are searched once.
    assert len(client.calls) == 1
    assert result['success'] and result['saved_count'] == 1
    assert result['skipped'][0]['reason'] == 'already_saved' and result['skipped'][0]['lead_id'] == 'TPL-OLD'
    assert result['sources'][0]['status'] == 'ok' and result['domain_outcomes'][0]['matched'] == 2
    assert len(db['trainer_profile_leads'].docs) == 2
    run = db['lead_search_runs'].docs[0]
    assert run['run_id'] == result['run_id'] and run['kind'] == 'trainer_search_public'
    assert run['found'] == 2 and run['saved_count'] == 1 and run['sources'][0]['source'] == 'tavily'


def test_trainer_search_public_reports_a_service_timeout_and_skips_the_rest():
    db = FakeDB()
    client = FakeClient(lambda url, body: httpx.ReadTimeout('timed out'))
    result = trainer_search_public(db, client, domains=['Python', 'AWS'], source='linkedin')
    assert len(client.calls) == 1
    assert result['success'] is False and 'did not answer within 30 seconds' in result['search_error']
    assert [outcome['status'] for outcome in result['domain_outcomes']] == ['blocked', 'not_run']
    assert db['lead_search_runs'].docs[0]['success'] is False


def test_naukri_search_public_explains_blocked_engines():
    db = FakeDB()

    async def fake_naukri(skill, location, limit, report=None):
        report['sources'] = [{'source': 'duckduckgo', 'label': 'DuckDuckGo', 'status': 'blocked', 'reason': 'Bot check.'},
                             {'source': 'bing', 'label': 'Bing', 'status': 'error', 'reason': 'No answer.'}]
        return []

    with patch('app.clients.naukri_public_search.search_public_naukri_profiles', side_effect=fake_naukri):
        result = trainer_search_public(db, FakeClient(lambda *a: None), domains=['Java'], source='naukri')
    assert result['success'] is False
    assert result['search_error'] == 'No search source gave an answer. DuckDuckGo: Bot check. Bing: No answer.'
    assert db['lead_search_runs'].docs[0]['kind'] == 'naukri_search'


def test_client_search_public_does_not_copy_a_saved_post_or_profile():
    from app.routes import client_leads
    db = FakeDB()
    asyncio.run(db['client_leads'].insert_one({'lead_id': 'CL-OLD', 'post_key': 'linkedin:activity:7123456789012345678',
                                               'source_url': 'https://www.linkedin.com/posts/acme-activity-7123456789012345678-x',
                                               'status': 'contacted', 'notes': 'edited by hand'}))
    found = {'profiles': [
        {'source_url': 'https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678', 'title': 'Acme', 'source': 'linkedin'},
        {'source_url': 'https://www.naukri.com/resume/x', 'title': 'X', 'source': 'naukri', 'snippet': 'Java'},
        {'source_url': 'https://www.naukri.com/resume/x', 'title': 'X', 'source': 'naukri', 'snippet': 'Java'},
    ], 'sources': [{'source': 'tavily', 'label': 'Tavily', 'status': 'ok', 'found': 3, 'qualified': 3}]}
    queue = MagicMock()
    with patch('httpx.AsyncClient', FakeClient(lambda url, body: response(200, found, url))), \
            patch.object(client_leads, 'queue_auto_personalization', queue):
        result = asyncio.run(client_leads.search_public_leads(client_leads.SearchPublicRequest(domains=['Java']), db))
    assert result['saved_count'] == 1 and result['skipped_count'] == 2 and result['success']
    assert len(db['client_leads'].docs) == 2
    assert db['client_leads'].docs[0]['notes'] == 'edited by hand' and db['client_leads'].docs[0]['status'] == 'contacted'
    queue.assert_called_once()
    assert db['lead_search_runs'].docs[0]['kind'] == 'client_search_public'


def linkedin_search(db, mode, row, outcome=None):
    from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads
    outcome = outcome or {'status': 'target_met', 'warnings': [], 'primary_error': None,
                          'sources': [{'source': 'linkedin_account', 'label': 'LinkedIn account', 'status': 'ok', 'qualified': 1}]}
    with patch('app.clients.lead_discovery.discover', AsyncMock(return_value=([row], outcome))):
        return asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domains=['Python'], mode=mode, max_results=20), db))


def test_linkedin_search_results_carry_the_saved_trainer_lead():
    db = FakeDB()
    asyncio.run(db['trainer_profile_leads'].insert_one({'lead_id': 'TPL-OLD', 'source_url': 'https://www.linkedin.com/in/ravi',
                                                        'linkedin_url': 'https://www.linkedin.com/in/ravi', 'status': 'contacted'}))
    row = {'url': 'https://in.linkedin.com/in/ravi/', 'title': 'Python corporate trainer', 'content': 'Python corporate trainer'}
    result = linkedin_search(db, 'trainer', row)
    assert result['saved_count'] == 0 and result['found'] == 1
    assert result['results'][0]['lead_id'] == 'TPL-OLD' and result['results'][0]['status'] == 'contacted'
    assert len(db['trainer_profile_leads'].docs) == 1
    assert result['sources'][0]['source'] == 'linkedin_account' and result['success']
    assert db['lead_search_runs'].docs[0]['kind'] == 'linkedin_search'


def test_linkedin_search_results_carry_the_saved_client_post():
    db = FakeDB()
    asyncio.run(db['client_leads'].insert_one({'lead_id': 'CL-OLD', 'post_key': 'linkedin:activity:7123456789012345678',
                                               'source_url': 'https://www.linkedin.com/posts/acme_python-activity-7123456789012345678-x',
                                               'status': 'reviewed'}))
    row = {'url': 'https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/',
           'title': 'Acme', 'content': 'We need a Python trainer for a corporate training requirement'}
    result = linkedin_search(db, 'client', row)
    assert result['saved_count'] == 0
    assert result['results'][0]['lead_id'] == 'CL-OLD' and result['results'][0]['status'] == 'reviewed'
    assert len(db['client_leads'].docs) == 1


def test_an_account_search_with_the_bot_off_is_not_configured():
    from app.clients.lead_discovery import discover
    error = ValueError('LinkedIn bot is not enabled. Connect the dedicated account and set LINKEDIN_BOT_ENABLED=true.')
    with patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=error)):
        rows, outcome = asyncio.run(discover('Python', 'trainer', 10))
    assert rows == [] and outcome['sources'][0]['status'] == 'not_configured'


def test_search_runs_are_listed_newest_first():
    from app.routes.linkedin_leads import list_search_runs
    db = FakeDB()
    start = datetime(2026, 11, 16, 9, 0)
    for index, kind in enumerate(['naukri_search', 'linkedin_search', 'naukri_search']):
        asyncio.run(db['lead_search_runs'].insert_one({'run_id': f'R{index}', 'kind': kind,
                                                       'started_at': start + timedelta(minutes=index)}))
    result = asyncio.run(list_search_runs(kind='naukri_search', limit=5, db=db))
    assert [run['run_id'] for run in result['runs']] == ['R2', 'R0']
    assert '_id' not in result['runs'][0]
    assert len(asyncio.run(list_search_runs(kind=None, limit=500, db=db))['runs']) == 3


def test_a_run_report_that_cannot_be_saved_does_not_fail_the_search():
    from app.clients.search_runs import record_search_run
    db = {'lead_search_runs': SimpleNamespace(insert_one=AsyncMock(side_effect=RuntimeError('database down')))}
    assert asyncio.run(record_search_run(db, 'naukri_search', {}, {'found': 1}, datetime.utcnow())) == ''


@pytest.mark.parametrize('status_code', [500, 404])
def test_a_failing_search_service_response_is_reported(status_code):
    db = FakeDB()
    client = FakeClient(lambda url, body: httpx.Response(status_code, text='upstream failed', request=httpx.Request('POST', url)))
    result = trainer_search_public(db, client, domains=['Python'], source='linkedin')
    source = result['sources'][0]
    assert source['status'] == 'error' and source['reason'].startswith(f'HTTP {status_code}')
    assert result['success'] is False
