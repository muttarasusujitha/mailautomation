import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.clients.client_post_scan import scan_client_posts
from app.clients.lead_discovery import discover


def post(text, slug='request'):
    return {'url': f'https://www.linkedin.com/posts/{slug}', 'content': text}


def test_broad_discovery_does_not_search_individual_domains():
    rows = [post('Looking for a Python and SAP trainer')]
    with patch('app.clients.public_search.search_public', AsyncMock(return_value=rows)) as public, patch(
        'app.clients.linkedin_browser.search_linkedin_account', AsyncMock(return_value=[])
    ) as account:
        result, _ = asyncio.run(discover('', 'client', 50))
    assert len(result) == 1
    assert all('Python' not in call.args[0] and 'SAP' not in call.args[0] for call in public.await_args_list)
    assert account.await_args.args[:3] == ('', 'client', 50)


def test_all_domains_multi_match_dedupe_and_repeat_status_preservation():
    table = AsyncMock()
    table.update_one.side_effect = [SimpleNamespace(upserted_id='new'), SimpleNamespace(upserted_id=None)]
    row = post('Looking for Python and SAP trainers')
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(
        [row, row], {'status': 'partial', 'warnings': []}
    ))) as discovery:
        first = asyncio.run(scan_client_posts(['Java', 'Cloud', 'React', 'DevOps', 'Python', 'SAP'], {'client_leads': table}))
        second = asyncio.run(scan_client_posts(['Python', 'SAP'], {'client_leads': table}))
    assert discovery.await_args.args == ('', 'client', 50)
    assert first['found'] == 1 and first['saved_count'] == 1
    assert len(first['domain_outcomes']) == 6
    assert second['saved_count'] == 0
    assert table.update_one.await_count == 2
    update = table.update_one.await_args.args[1]
    assert update['$addToSet']['matched_domains']['$each'] == ['Python', 'SAP']
    assert 'status' not in update['$set'] and 'domain' not in update['$set']
    assert update['$setOnInsert']['status'] == 'new'


def test_unrelated_posts_and_short_domain_names_do_not_match_everything():
    rows = [post('Looking for Python trainer'), post('I offer Python training', 'offer'),
            {'url': 'https://www.linkedin.com/in/person', 'content': 'Python trainer required'}]
    table = AsyncMock()
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(rows, {'status': 'partial'}))):
        result = asyncio.run(scan_client_posts(['C', 'R', 'Java'], {'client_leads': table}))
    assert result['found'] == 0
    table.update_one.assert_not_awaited()


def test_partial_results_keep_source_warnings_and_blocked_scan_reports_error():
    warning = {'source': 'linkedin_account', 'error': 'Verification required'}
    table = AsyncMock()
    table.update_one.return_value = SimpleNamespace(upserted_id='new')
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(
        [post('SAP trainer required')], {'status': 'partial', 'warnings': [warning]}
    ))):
        result = asyncio.run(scan_client_posts(['SAP'], {'client_leads': table}))
    assert result['found'] == 1 and not result['search_error']
    assert result['scan_warnings'] == [warning]
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(
        [], {'status': 'blocked', 'warnings': [warning]}
    ))):
        result = asyncio.run(scan_client_posts(['SAP'], {'client_leads': table}))
    assert result['search_error'] == 'Verification required'


def test_all_domains_saves_nontechnical_and_unknown_requests_but_not_ads():
    rows = [post('Looking for a leadership trainer', 'leadership'),
            post('Need a pottery instructor', 'pottery'),
            post('Seeking a Project Management trainer', 'pm'),
            post('We require communication skills training for our employees', 'communication'),
            post('I offer Python training', 'advert')]
    table = AsyncMock()
    table.update_one.return_value = SimpleNamespace(upserted_id='new')
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(rows, {'status': 'partial'}))):
        result = asyncio.run(scan_client_posts(['Python', 'Project Management'], {'client_leads': table}, include_unmatched=True))
    assert result['found'] == result['saved_count'] == 4
    inserted = [call.args[1]['$setOnInsert'] for call in table.update_one.await_args_list]
    assert [lead['domain'] for lead in inserted] == ['Unclassified', 'Unclassified', 'Project Management', 'Unclassified']


def test_url_variants_of_same_post_are_saved_once():
    rows = [post('Need a Python trainer', 'author-python-activity-1234567890123456789-abcd'),
            {'url': 'https://in.linkedin.com/feed/update/urn:li:activity:1234567890123456789/?trk=search',
             'content': 'Need a Python trainer'}]
    table = AsyncMock()
    table.update_one.return_value = SimpleNamespace(upserted_id='new')
    with patch('app.clients.client_post_scan.discover', AsyncMock(return_value=(rows, {'status': 'partial'}))):
        result = asyncio.run(scan_client_posts([], {'client_leads': table}, include_unmatched=True))
    assert result['found'] == 1
    table.update_one.assert_awaited_once()
