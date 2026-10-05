import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

from app.routes.trainer_profile_leads import list_trainer_leads


def search_query(text):
    table = MagicMock()
    table.count_documents = AsyncMock(return_value=0)
    cursor = table.find.return_value.sort.return_value.skip.return_value.limit.return_value
    cursor.__aiter__.return_value = []
    asyncio.run(list_trainer_leads(page=1, page_size=20, limit=150, q=text,
                                  db={'trainer_profile_leads': table}))
    return table.count_documents.await_args.args[0]


def test_trailing_space_does_not_hide_new_devops_profile():
    query = search_query(' devops   trainer  ')
    domain = next(clause['domain'] for clause in query['$or'] if 'domain' in clause)
    assert re.search(domain['$regex'], 'Devops trainer', re.I)
    assert any('profile_text' in clause for clause in query['$or'])


def test_saved_search_treats_technology_names_as_literal_text():
    query = search_query('C++')
    pattern = query['$or'][0]['name']['$regex']
    assert re.search(pattern, 'C++ trainer')
    assert not re.search(pattern, 'Cloud trainer')
    assert '$or' not in search_query('   ')
