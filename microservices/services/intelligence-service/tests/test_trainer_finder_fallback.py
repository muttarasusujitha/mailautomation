import asyncio
from unittest.mock import AsyncMock, patch

from app.clients.lead_discovery import discover_with_trainer_finder

PAUSED = 'LinkedIn limited this session. Account searches are paused until 2026-11-18 10:00 UTC.'


def web_rows(count):
    return [{'url': f'https://www.linkedin.com/in/web-{i}', 'title': 'Python Trainer', 'engines': ['bing'],
             'discovery_provider': 'trainer_finder'} for i in range(count)]


def finder_report(matched, target, reason=''):
    return {'status': 'target_met' if matched >= target else 'partial', 'limit_reason': reason,
            'sources': [{'source': 'bing', 'label': 'Bing', 'status': 'ok', 'qualified': matched}]}


def test_paused_account_is_filled_by_web_engines_and_reported():
    db = {'trainer_profile_leads': AsyncMock()}
    db['trainer_profile_leads'].distinct.return_value = ['https://in.linkedin.com/in/saved-trainer']
    account = [{'url': 'https://www.linkedin.com/in/acct-1', 'title': 'Python Trainer'}]
    outcome = {'primary_error': PAUSED, 'warnings': [{'source': 'linkedin_account', 'error': PAUSED}], 'attempts': 1}
    with patch('app.clients.trainer_finder.find_leads', AsyncMock(return_value=(web_rows(59), finder_report(59, 59)))) as find:
        rows, result = asyncio.run(discover_with_trainer_finder('Python', 60, '', db, account, outcome, time_left=500))
    args, kwargs = find.await_args
    assert args[:2] == ('Python', 59)
    assert 'https://www.linkedin.com/in/saved-trainer' in kwargs['exclude']
    assert 'https://www.linkedin.com/in/acct-1' in kwargs['exclude']
    assert len(rows) == 60 and result['target_met'] and result['status'] == 'target_met'
    assert result['from_account'] == 1 and result['from_web_engines'] == 59
    assert result['sources'][0] == {'source': 'linkedin_account', 'label': 'LinkedIn account', 'status': 'paused',
                                    'qualified': 1, 'reason': PAUSED}
    assert result['primary_error'] == PAUSED


def test_short_result_explains_why():
    reason = 'Blocked this run: Bing. Every planned query was searched on every working engine.'
    with patch('app.clients.trainer_finder.find_leads', AsyncMock(return_value=(web_rows(12), finder_report(12, 60, reason)))):
        rows, result = asyncio.run(discover_with_trainer_finder(
            'Python', 60, '', None, [], {'primary_error': 'LinkedIn bot is not enabled.', 'warnings': []}, time_left=500))
    assert len(rows) == 12 and result['status'] == 'partial'
    assert result['limit_reason'] == reason
    assert result['warnings'][-1] == {'source': 'trainer_finder', 'error': reason}
    assert result['sources'][0]['status'] == 'blocked'


def test_no_time_left_skips_the_engines():
    with patch('app.clients.trainer_finder.find_leads', AsyncMock()) as find:
        rows, result = asyncio.run(discover_with_trainer_finder('Python', 60, '', None, [], {}, time_left=15))
    find.assert_not_awaited()
    assert rows == [] and 'time budget' in result['limit_reason']


def test_auto_route_uses_the_finder_and_saves_web_profiles(monkeypatch):
    from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads

    monkeypatch.setenv('TRAINER_FINDER_ENABLED', 'true')
    db = {'trainer_profile_leads': AsyncMock(), 'client_leads': AsyncMock()}
    db['trainer_profile_leads'].find_one.return_value = None
    db['trainer_profile_leads'].distinct.return_value = []
    paused = {'primary_error': PAUSED, 'warnings': [{'source': 'linkedin_account', 'error': PAUSED}], 'status': 'blocked'}
    rows = [{'url': f'https://www.linkedin.com/in/python-trainer-{i}', 'title': 'Python Corporate Trainer',
             'content': 'Python corporate trainer', 'keyword_qualified': True, 'engines': ['bing', 'mojeek'],
             'discovery_provider': 'trainer_finder'} for i in range(60)]
    with patch('app.clients.lead_discovery.discover', AsyncMock(return_value=([], paused))), \
            patch('app.clients.trainer_finder.find_leads', AsyncMock(return_value=(rows, finder_report(60, 60)))):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(
            domains=['Python'], search_provider='auto', max_results=60), db))
    outcome = result['domain_outcomes'][0]
    assert outcome['fallback_source'] == 'trainer_finder' and outcome['target_met']
    assert outcome['sources'][0]['status'] == 'paused'
    assert result['saved_count'] == 60 and result['success']
    saved = db['trainer_profile_leads'].insert_one.await_args.args[0]
    assert saved['found_by'] == ['bing', 'mojeek']
    assert saved['verification_status'] == 'unverified_public_search'


def test_client_mode_excludes_saved_posts_and_asks_for_posts():
    db = {'client_leads': AsyncMock()}

    async def distinct(field):
        return {'post_key': ['linkedin:activity:7123456789012345678'],
                'source_url': ['https://www.linkedin.com/posts/acme_python-trainer-activity-7000000000000000001-ab']}[field]
    db['client_leads'].distinct.side_effect = distinct
    report = finder_report(5, 50)
    with patch('app.clients.trainer_finder.find_leads', AsyncMock(return_value=(web_rows(5), report))) as find:
        rows, result = asyncio.run(discover_with_trainer_finder(
            'Python', 50, '', db, [], {'primary_error': PAUSED}, time_left=500, mode='client'))
    kwargs = find.await_args.kwargs
    assert kwargs['mode'] == 'client'
    assert {'linkedin:activity:7123456789012345678', 'linkedin:activity:7000000000000000001'} <= kwargs['exclude']
    assert result['status'] == 'partial' and result['from_web_engines'] == 5
