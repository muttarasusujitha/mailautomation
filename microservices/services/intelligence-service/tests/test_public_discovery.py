import asyncio
from unittest.mock import AsyncMock, patch
from app.clients.public_discovery import discover_public


def batch(start, end):
    return [{'url': f'https://www.linkedin.com/in/trainer-{i}', 'title': 'Python corporate trainer', 'content': 'Python corporate trainer'} for i in range(start, end)]


def test_expands_queries_and_stops_at_twenty_unique_matches():
    with patch('app.clients.public_discovery.search_public', AsyncMock(side_effect=[batch(0, 12), batch(8, 25)])) as search:
        rows, status = asyncio.run(discover_public('Python', 'trainer', 20))
    assert len(rows) == 20
    assert status['target_met']
    assert search.await_count == 2


def test_partial_results_are_not_padded():
    with patch('app.clients.public_discovery.search_public', AsyncMock(return_value=batch(0, 3))):
        rows, status = asyncio.run(discover_public('Python', 'trainer'))
    assert len(rows) == 3 and status['status'] == 'partial'
    assert status['reason']
