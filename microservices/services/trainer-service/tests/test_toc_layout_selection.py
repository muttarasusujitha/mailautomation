import asyncio
from unittest.mock import AsyncMock

import pytest
from shared.toc_layouts import REFERENCE_LAYOUTS, select_toc_layout


def test_same_sender_rotates_layout_without_mixing_other_senders():
    collection = AsyncMock()
    collection.find_one.return_value = {"toc": {"excel_layout": "execution_plan"}}
    result = asyncio.run(select_toc_layout({"toc_generations": collection}, client_email="Client <SIR@Example.com>"))
    assert result == "technical_plan"
    assert collection.find_one.call_args.args[0]["client_email"] == "sir@example.com"


@pytest.mark.parametrize("layout", REFERENCE_LAYOUTS)
def test_regeneration_keeps_saved_layout(layout):
    collection = AsyncMock()
    collection.find_one.return_value = {"toc": {"excel_layout": layout}}
    assert asyncio.run(select_toc_layout({"toc_generations": collection}, toc_id="TOC-123")) == layout
    assert collection.find_one.await_count == 1


def test_explicit_layout_and_anonymous_default_need_no_history():
    collection = AsyncMock()
    db = {"toc_generations": collection}
    assert asyncio.run(select_toc_layout(db, requested="skills_matrix")) == "skills_matrix"
    assert asyncio.run(select_toc_layout(db)) == "execution_plan"
    collection.find_one.assert_not_awaited()
