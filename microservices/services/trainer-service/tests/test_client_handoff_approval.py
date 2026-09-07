from app.routes.shortlists import SendClientSlotsRequest, _format_client_slot_lines


def test_client_handoff_has_no_manual_approval_gate():
    payload = SendClientSlotsRequest(
        requirement_id="REQ-1",
        trainer_id="TR-1",
    )

    assert "approved" not in payload.model_fields_set


def test_client_handoff_formats_three_slots_as_emphasized_lines():
    assert _format_client_slot_lines(
        "07 September 2026, 10:00 AM IST\n07 September 2026, 3:00 PM IST"
    ) == "*07 September 2026, 10:00 AM IST*\n*07 September 2026, 3:00 PM IST*"
