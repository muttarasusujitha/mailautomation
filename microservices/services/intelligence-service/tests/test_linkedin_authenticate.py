from unittest.mock import MagicMock, patch

import pytest

from app.linkedin_authenticate import search_ready, verify_search


@pytest.mark.parametrize('url,mode,captcha,token,ready', [
    ('https://www.linkedin.com/feed/', 'trainer', False, True, False),
    ('https://www.linkedin.com/login/', 'trainer', False, True, False),
    ('https://www.linkedin.com/checkpoint/challenge', 'trainer', False, True, False),
    ('https://www.linkedin.com/search/results/people/', 'trainer', False, True, True),
    ('https://www.linkedin.com/search/results/people/', 'trainer', True, True, False),
    ('https://www.linkedin.com/search/results/people/', 'trainer', False, False, False),
    ('https://www.linkedin.com/search/results/content/', 'trainer', False, True, False),
    ('https://www.linkedin.com/search/results/content/', 'client', False, True, True),
    ('https://www.linkedin.com.evil.test/search/results/people/', 'trainer', False, True, False),
])
def test_ready_requires_requested_search_without_verification(url, mode, captcha, token, ready):
    page, context = MagicMock(), MagicMock()
    page.url = url
    page.locator.return_value.count.return_value = int(captcha)
    context.cookies.return_value = [{'name': 'li_at', 'value': 'test-token'}] if token else []
    assert search_ready(page, context, mode) is ready


@pytest.mark.parametrize('ready', [True, False])
def test_fresh_browser_check_saves_only_verified_search_and_always_closes(ready, tmp_path, monkeypatch):
    monkeypatch.setenv('LINKEDIN_BOT_PROFILE_PATH', str(tmp_path))
    playwright = MagicMock()
    context = playwright.chromium.launch_persistent_context.return_value
    with patch('app.linkedin_authenticate.load_session', return_value=[]), \
            patch('app.linkedin_authenticate.search_ready', return_value=ready), \
            patch('app.linkedin_authenticate.save_session') as save:
        if ready:
            verify_search(playwright, 'sap trainer', 'trainer')
            save.assert_called_once()
        else:
            with pytest.raises(ValueError, match='Session is not ready'):
                verify_search(playwright, 'sap trainer', 'trainer')
            save.assert_not_called()
    context.close.assert_called_once()
    target = context.new_page.return_value.goto.call_args.args[0]
    assert '/search/results/people/' in target
    assert 'sap+trainer' in target
