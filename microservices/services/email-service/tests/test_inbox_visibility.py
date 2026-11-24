import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes.inbox_actions import CLIENT_REQUEST_SIGNAL, PENDING_STATUSES, _status_filter


def _contains_clause(value, expected):
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_contains_clause(child, expected) for child in value.values())
    if isinstance(value, list):
        return any(_contains_clause(child, expected) for child in value)
    return False


def test_pending_general_enquiry_with_saved_draft_is_visible_for_manual_review():
    query = _status_filter("pending_approval")

    assert _contains_clause(
        CLIENT_REQUEST_SIGNAL,
        {"reply_status": {"$in": PENDING_STATUSES}},
    )
    assert _contains_clause(
        CLIENT_REQUEST_SIGNAL,
        {"draft_reply": {"$exists": True, "$nin": ["", None]}},
    )
    assert _contains_clause(query, CLIENT_REQUEST_SIGNAL)
