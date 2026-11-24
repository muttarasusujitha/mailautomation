import asyncio
from app.routes import lead_bot
from app.clients import linkedin_session, linkedin_browser


def test_connection_distinguishes_missing_saved_and_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin_browser, 'profile_path', lambda: str(tmp_path))
    assert lead_bot.connection_status()['state'] == 'disconnected'
    linkedin_session.save_session(tmp_path, [{'domain': '.linkedin.com', 'name': 'li_at', 'value': 'secret'}])
    result = lead_bot.connection_status()
    assert result['state'] == 'saved'
    assert 'secret' not in str(result)
    linkedin_session.block_session(tmp_path)
    assert lead_bot.connection_status()['state'] == 'verification_required'


def test_verification_does_not_retry_rate_limited_session(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin_browser, 'profile_path', lambda: str(tmp_path))
    linkedin_session.pause_after_rate_limit(tmp_path, 24)
    result = asyncio.run(lead_bot.verify_linkedin_connection())
    assert result['state'] == 'paused'
    assert result['retry_after']
