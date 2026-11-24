import asyncio

from app.routes import inbox


def test_first_offline_reply_requests_only_missing_logistics_before_signature():
    fields = inbox._initial_offline_logistics_fields(
        {"delivery_mode": "offline", "location": "Bengaluru", "food_policy": "Client provides lunch"},
        first_client_mail=True,
    )

    assert fields == ["travel", "accommodation"]
    body = inbox._append_initial_offline_logistics_request(
        "Hi Asha,\n\nWe will share the trainer profile.\n\nRegards,\nClahan Technologies",
        fields,
    )

    assert "Travel terms: [details]" in body
    assert "Accommodation: [details]" in body
    assert "Food: [details]" not in body
    assert "Confirmed training address: [details]" not in body
    assert body.index("Travel terms") < body.index("Regards,")


def test_first_reply_does_not_ask_logistics_for_online_or_later_messages():
    assert inbox._initial_offline_logistics_fields(
        {"delivery_mode": "online"}, first_client_mail=True,
    ) == []
    assert inbox._initial_offline_logistics_fields(
        {"delivery_mode": "offline"}, first_client_mail=False,
    ) == []


def test_selection_safety_guard_never_sends_post_selection_logistics():
    result = asyncio.run(inbox._auto_request_offline_logistics(
        None, requirement_id="REQ-1", trainer_id="TR-1", trainer_name="Asha", trainer_email="asha@example.com",
    ))

    assert result == {
        "attempted": False,
        "reason": "offline_logistics_requested_in_first_client_reply",
    }
