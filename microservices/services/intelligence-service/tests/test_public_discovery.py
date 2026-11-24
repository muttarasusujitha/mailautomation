import asyncio
from unittest.mock import AsyncMock, patch
from app.clients.public_discovery import discover_public


def batch(start, end):
    return [{'url': f'https://www.linkedin.com/in/trainer-{i}', 'title': 'Python corporate trainer', 'content': 'Python corporate trainer'} for i in range(start, end)]


def test_trainer_route_keeps_at_least_fifty_profiles():
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(batch(0, 50), 8))) as search:
        rows, status = asyncio.run(discover_public('Python', 'trainer', 20))
    assert len(rows) == 50
    assert status['target'] >= 50
    assert status['target_met']
    assert search.await_args.args[1] >= 50


def test_partial_results_are_not_padded():
    with patch('app.clients.public_search.search_public_many', AsyncMock(return_value=(batch(0, 3), 4))):
        rows, status = asyncio.run(discover_public('Python', 'trainer'))
    assert len(rows) == 3 and status['status'] == 'partial'
    assert status['target'] >= 50
    assert status['reason']
