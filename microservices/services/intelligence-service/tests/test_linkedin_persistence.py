import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.linkedin_browser import PartialSearchError, search_linkedin_account
from app.clients.linkedin_session import load_session, save_session
from app.clients.linkedin_session import LinkedInAuthenticationRequired


@pytest.mark.parametrize('outcome', ['success', 'partial', 'checkpoint', 'captcha', 'logged_out', 'disk_error'])
def test_search_retains_refreshed_login_without_hiding_results(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv('LINKEDIN_BOT_ENABLED', 'true')
    monkeypatch.setenv('LINKEDIN_BOT_PROFILE_PATH', str(tmp_path))
    original = [{'name': 'li_at', 'value': 'old-test-token', 'domain': '.linkedin.com', 'path': '/'}]
    refreshed = [{**original[0], 'value': 'new-test-token'}]
    save_session(tmp_path, original)
    page = MagicMock()
    page.url = 'https://www.linkedin.com/search/results/people/'
    page.locator.return_value.count = AsyncMock(return_value=0)
    context = AsyncMock()
    context.new_page.return_value = page
    context.cookies.return_value = refreshed
    playwright = MagicMock()
    playwright.chromium.launch_persistent_context = AsyncMock(return_value=context)
    manager = AsyncMock()
    manager.__aenter__.return_value = playwright
    rows = [{'url': 'https://www.linkedin.com/in/test'}]
    collector = AsyncMock(return_value=rows)
    if outcome == 'partial':
        collector.side_effect = PartialSearchError('time limit', rows)
    elif outcome == 'checkpoint':
        page.url = 'https://www.linkedin.com/checkpoint/challenge'
        collector.side_effect = ValueError('verification required')
    elif outcome == 'captcha':
        page.locator.return_value.count.return_value = 1
        collector.side_effect = ValueError('verification required')
    elif outcome == 'logged_out':
        context.cookies.return_value = []

    real_save = save_session
    saver = MagicMock(side_effect=OSError('disk unavailable') if outcome == 'disk_error' else real_save)
    with patch('playwright.async_api.async_playwright', return_value=manager), \
            patch('app.clients.linkedin_browser.collect_trainer_profiles', collector), \
            patch('app.clients.linkedin_session.save_session', saver):
        if outcome == 'partial':
            assert asyncio.run(search_linkedin_account('SAP', 'trainer')) == rows
        elif outcome in ('checkpoint', 'captcha'):
            with pytest.raises(ValueError):
                asyncio.run(search_linkedin_account('SAP', 'trainer'))
        else:
            assert asyncio.run(search_linkedin_account('SAP', 'trainer')) == rows

    context.add_cookies.assert_awaited_once_with(original)
    context.close.assert_awaited_once()
    expected = refreshed if outcome in ('success', 'partial') else original
    assert load_session(tmp_path) == expected
    # A fresh fetch must restore the updated snapshot, including rotated tokens.
    if outcome in ('success', 'partial'):
        context.add_cookies.reset_mock()
        with patch('playwright.async_api.async_playwright', return_value=manager), \
                patch('app.clients.linkedin_browser.collect_trainer_profiles', AsyncMock(return_value=rows)):
            asyncio.run(search_linkedin_account('SAP', 'trainer'))
        context.add_cookies.assert_awaited_once_with(refreshed)


@pytest.mark.parametrize('partial', [False, True])
def test_checkpoint_stops_future_browser_launches_and_preserves_partial_results(tmp_path, monkeypatch, partial):
    monkeypatch.setenv('LINKEDIN_BOT_ENABLED', 'true')
    monkeypatch.setenv('LINKEDIN_BOT_PROFILE_PATH', str(tmp_path))
    page = MagicMock()
    page.url = 'https://www.linkedin.com/checkpoint/challenge'
    context = AsyncMock()
    context.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch_persistent_context = AsyncMock(return_value=context)
    manager = AsyncMock()
    manager.__aenter__.return_value = playwright
    error = LinkedInAuthenticationRequired('verification required')
    rows = [{'url': 'https://www.linkedin.com/in/test'}]
    if partial:
        wrapped = PartialSearchError(str(error), rows)
        wrapped.__cause__ = error
        error = wrapped
    with patch('playwright.async_api.async_playwright', return_value=manager) as browser, \
            patch('app.clients.linkedin_browser.collect_trainer_profiles', AsyncMock(side_effect=error)):
        with pytest.raises(ValueError) as first:
            asyncio.run(search_linkedin_account('SAP', 'trainer'))
        if partial:
            assert first.value.results == rows
        context.close.assert_awaited_once()
        browser.reset_mock()
        with pytest.raises(LinkedInAuthenticationRequired, match='retries are paused'):
            asyncio.run(search_linkedin_account('SAP', 'trainer'))
        browser.assert_not_called()
