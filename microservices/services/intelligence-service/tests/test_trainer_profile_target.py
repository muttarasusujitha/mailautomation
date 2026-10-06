import asyncio
from unittest.mock import AsyncMock, patch

from app.routes.linkedin_leads import LinkedInLeadSearchRequest, search_linkedin_leads
from shared.trainer_targets import trainer_keep_limit


def test_trainer_keep_limit_is_at_least_sixty():
    assert trainer_keep_limit(None) == 60
    assert trainer_keep_limit(20) == 60
    assert trainer_keep_limit(80) == 80
    assert trainer_keep_limit(500) == 100


def test_trainer_search_stops_after_sixty_profiles():
    calls = []

    async def fake(domain, mode, target, location):
        calls.append((domain, target))
        rows = [
            {
                'url': f'https://www.linkedin.com/in/{domain}-{index}',
                'title': f'{domain} corporate trainer',
                'content': f'{domain} corporate trainer',
            }
            for index in range(target)
        ]
        return rows, {
            'domain': domain,
            'target': target,
            'matched': len(rows),
            'target_met': True,
            'status': 'target_met',
            'warnings': [],
        }

    table = AsyncMock()
    table.find_one = AsyncMock(return_value=None)
    table.insert_one = AsyncMock()
    db = {'trainer_profile_leads': table, 'client_leads': AsyncMock()}
    with patch('app.clients.lead_discovery.discover', side_effect=fake):
        result = asyncio.run(search_linkedin_leads(
            LinkedInLeadSearchRequest(domains=['Python', 'Java'], search_provider='auto', max_results=20),
            db,
        ))
    assert calls == [('Python', 60)]
    assert result['saved_count'] == 60
    assert result['found'] == 60
