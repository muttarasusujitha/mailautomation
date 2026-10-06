import asyncio
from unittest.mock import AsyncMock, patch
from app.routes.lead_bot import collect_due


def test_client_settings_use_ten_minutes_and_status_lists_whole_catalog():
    from app.routes.lead_bot import BotSettings, configure
    table = AsyncMock()
    table.find_one.return_value = {'enabled': False, 'domain_source': 'it_catalog', 'domain_cursor': 4}
    with patch('app.routes.lead_bot.it_course_domains', return_value=tuple('ABCDE')):
        result = asyncio.run(configure('client', BotSettings(domain_source='it_catalog'), {'lead_bots': table}))
    settings = table.update_one.await_args.args[1]['$set']
    assert settings['interval_minutes'] == 10 and settings['enabled'] is False
    assert result['next_domains'] == list('ABCDE')
    assert result['scan_strategy'] == 'posts_all_domains'


def test_trainer_defaults_remain_hourly():
    from app.routes.lead_bot import BotSettings, configure
    table = AsyncMock()
    table.find_one.return_value = None
    asyncio.run(configure('trainer', BotSettings(), {'lead_bots': table}))
    assert table.update_one.await_args.args[1]['$set']['interval_minutes'] == 60


def test_all_domain_scan_continues_when_classification_catalog_is_missing():
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': [], 'domain_source': 'all'}
    with patch('app.routes.lead_bot.it_course_domains', side_effect=ValueError('missing catalog')), patch(
        'app.routes.lead_bot.scan_client_posts', AsyncMock(return_value={'found': 2, 'saved_count': 2})
    ) as scan:
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
    assert scan.await_args.kwargs['include_unmatched'] is True
    assert table.update_one.await_args.args[1]['$set']['saved'] == 2


def test_no_lease_does_not_search():
    table = AsyncMock()
    table.find_one_and_update.return_value = None
    with patch('app.routes.lead_bot.search_linkedin_leads', AsyncMock()) as search:
        asyncio.run(collect_due({'lead_bots': table}, 'trainer'))
    search.assert_not_awaited()


def test_collection_records_counts_and_uses_connected_account_fallback():
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': ['Python'], 'interval_minutes': 60}
    with patch('app.routes.lead_bot.scan_client_posts', AsyncMock(return_value={'found': 2, 'saved_count': 1})) as search:
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
    assert search.await_args.args[0] == ['Python']
    update = table.update_one.await_args.args[1]
    assert update['$set']['saved'] == 1
    assert update['$set']['status'] == 'completed'
    assert 'lease_token' in table.update_one.await_args.args[0]
    started = table.find_one_and_update.await_args.args[1]['$set']['last_started']
    assert (update['$set']['next_run'] - started).total_seconds() == 600


def test_search_failure_is_visible_and_releases_lease():
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': ['Python']}
    with patch('app.routes.lead_bot.search_linkedin_leads', AsyncMock(side_effect=ValueError('Search blocked'))):
        asyncio.run(collect_due({'lead_bots': table}, 'trainer'))
    update = table.update_one.await_args.args[1]
    assert update['$set']['last_error'] == 'Search blocked'
    assert 'lease_until' in update['$unset']


def test_catalog_checks_every_domain_ignoring_old_rotation_cursor():
    catalog = ('DevOps', 'Python', 'Java', 'Cloud', 'SAP', 'React')
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': [], 'domain_source': 'it_catalog', 'domain_cursor': 4}
    with patch('app.routes.lead_bot.it_course_domains', return_value=catalog), patch(
        'app.routes.lead_bot.scan_client_posts', AsyncMock(return_value={'found': 1, 'saved_count': 1})
    ) as search:
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
    assert search.await_args.args[0] == list(catalog)
    assert table.update_one.await_args.args[1]['$set']['catalog_count'] == 6


def test_catalog_error_does_not_advance_cursor():
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': [], 'domain_source': 'it_catalog', 'domain_cursor': 4}
    with patch('app.routes.lead_bot.it_course_domains', return_value=('A', 'B', 'C', 'D', 'E')), patch(
        'app.routes.lead_bot.scan_client_posts', AsyncMock(return_value={'found': 0, 'search_error': 'Sign in required'})
    ):
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
    updates = table.update_one.await_args.args[1]['$set']
    assert 'domain_cursor' not in updates
    assert updates['status'] == 'error'


def test_failed_scan_retries_all_domains_next_run():
    table = AsyncMock()
    table.find_one_and_update.return_value = {'domains': [], 'domain_source': 'it_catalog'}
    result = {'found': 0, 'search_error': 'Client search reached its time limit.',
              'domain_outcomes': [{'domain': name, 'status': 'blocked'} for name in ('A', 'B', 'C', 'D')]}
    with patch('app.routes.lead_bot.it_course_domains', return_value=('A', 'B', 'C', 'D', 'E')), patch(
        'app.routes.lead_bot.scan_client_posts', AsyncMock(return_value=result)
    ) as scan:
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
        asyncio.run(collect_due({'lead_bots': table}, 'client'))
    assert [call.args[0] for call in scan.await_args_list] == [list('ABCDE'), list('ABCDE')]


def test_catalog_uses_dataset_domains_not_duplicate_duration_variants(tmp_path, monkeypatch):
    import json
    from app.clients.course_domains import it_course_domains
    for name, domain in [('py30', 'Python'), ('py60', 'Python'), ('devops', 'DevOps'), ('pm', 'Project Management')]:
        (tmp_path / (name + '.json')).write_text(json.dumps({'domain': domain}))
    monkeypatch.setenv('IT_COURSE_DATASET_PATH', str(tmp_path))
    it_course_domains.cache_clear()
    try:
        assert it_course_domains() == ('DevOps', 'Python')
    finally:
        it_course_domains.cache_clear()
