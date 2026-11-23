import asyncio
from unittest.mock import AsyncMock, patch
from app.clients.lead_discovery import discover, public_queries
from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads
from app.clients.linkedin_session import LinkedInAuthenticationRequired, RECONNECT_MESSAGE


def test_trainer_public_queries_ask_for_linkedin_profiles():
    queries = public_queries('Python', 'trainer', 'Hyderabad')
    assert queries[0] == 'Python corporate trainer Hyderabad'
    assert queries[1] == 'Python freelance trainer Hyderabad'
    assert len(queries) >= 12
    assert 'Python corporate trainer Bangalore' in queries
    assert all('site:' not in query for query in queries)
    client = public_queries('Python', 'client')
    assert client[0] == 'Python trainer required'
    assert all('site:' not in query for query in client)


def test_linkedin_discovery_uses_only_the_connected_account():
    rows = [{'url': 'https://www.linkedin.com/in/ravi', 'title': 'Ravi', 'content': 'Python corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock()) as public, patch(
        'app.clients.linkedin_browser.search_linkedin_account', AsyncMock(return_value=rows)
    ) as account:
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    public.assert_not_awaited()
    account.assert_awaited()
    assert account.await_args.args[:3] == ('Python', 'trainer', 20)
    assert [row['url'] for row in results] == ['https://www.linkedin.com/in/ravi']
    assert outcome['warnings'] == []
    assert outcome['status'] == 'partial'


def test_later_browser_failure_preserves_collected_matches():
    from app.clients.linkedin_browser import PartialSearchError
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Python corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock()) as public, patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=PartialSearchError('Later page timed out', rows))):
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    public.assert_not_awaited()
    assert len(results) == 1
    assert outcome['status'] == 'partial'
    assert outcome['warnings'][0]['error'] == 'Later page timed out'


def test_blocked_account_does_not_keep_public_web_matches():
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'title': 'Python corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(rows, 1))) as public, patch(
        'app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=ValueError('Verification required'))
    ):
        results, outcome = asyncio.run(discover('Python', 'trainer', 20))
    public.assert_not_awaited()
    assert results == []
    assert outcome['matched'] == 0
    assert outcome['status'] == 'blocked'
    assert outcome['warnings'][0]['source'] == 'linkedin_account'


def test_auto_target_is_per_domain_and_saves_separate_collections():
    async def fake(domain, mode, target, location, **kwargs):
        rows = [{'url': f'https://www.linkedin.com/in/{domain}-{i}', 'title': f'{domain} trainer'} for i in range(20)]
        return rows, {'domain': domain, 'target': target, 'matched': 20, 'target_met': True, 'status': 'target_met'}
    db = {'trainer_profile_leads': AsyncMock(), 'client_leads': AsyncMock()}
    db['trainer_profile_leads'].find_one.return_value = None
    with patch('app.clients.lead_discovery.discover', side_effect=fake):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(domains=['Python','Java'], search_provider='auto', max_results=20), db))
    assert result['saved_count'] == 40
    assert len(result['domain_outcomes']) == 2
    db['client_leads'].insert_one.assert_not_awaited()


def test_paused_login_is_the_only_discovery_error():
    with patch('app.clients.public_search.search_public_many', AsyncMock()) as public, \
            patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=LinkedInAuthenticationRequired(RECONNECT_MESSAGE))):
        result = asyncio.run(search_linkedin_leads(LinkedInLeadSearchRequest(
            domains=['sap trainer'], search_provider='auto', max_results=50), {'trainer_profile_leads': AsyncMock()}))
    public.assert_not_awaited()
    outcome = result['domain_outcomes'][0]
    assert result['search_error'] == outcome['primary_error'] == outcome['warnings'][0]['error'] == RECONNECT_MESSAGE
    assert len(outcome['warnings']) == 1
    assert outcome['matched'] == 0
    assert result['saved_count'] == 0


def test_cancelled_account_search_keeps_profiles_already_collected():
    async def boom(domain, mode, target, location, collected=None):
        collected.append({'url': 'https://www.linkedin.com/in/ada', 'title': 'Ada', 'content': 'Soft skills corporate trainer'})
        raise TimeoutError()

    with patch('app.clients.public_search.search_public_many', AsyncMock()) as public, \
            patch('app.clients.linkedin_browser.search_linkedin_account', side_effect=boom):
        results, outcome = asyncio.run(discover('soft skills', 'trainer', 20))
    public.assert_not_awaited()
    assert [row['url'] for row in results] == ['https://www.linkedin.com/in/ada']
    assert outcome['status'] == 'partial'
    assert outcome['primary_error'].startswith('LinkedIn account search timed out.')


def test_account_timeout_does_not_keep_public_web_matches():
    rows = [{'url': 'https://www.linkedin.com/in/alice', 'title': 'SAP corporate trainer'}]
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(rows, 1))) as public, \
            patch('app.clients.linkedin_browser.search_linkedin_account', AsyncMock(side_effect=TimeoutError())):
        found, outcome = asyncio.run(discover('SAP', 'trainer', 50))
    public.assert_not_awaited()
    assert found == []
    assert outcome['status'] == 'blocked'
    assert outcome['primary_error'].startswith('LinkedIn account search timed out.')
