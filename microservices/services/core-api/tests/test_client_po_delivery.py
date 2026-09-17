import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routes import requirements


def test_client_po_request_does_not_report_success_when_email_delivery_fails(monkeypatch):
    response = SimpleNamespace(raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError("SMTP unavailable")))
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *_args):
            return False

    db = SimpleNamespace(requirements=SimpleNamespace(find_one=AsyncMock(return_value={
        "requirement_id": "REQ-1", "technology_needed": "DevOps", "client_email": "client@example.com",
    })))
    monkeypatch.setattr(requirements._httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(HTTPException) as error:
        asyncio.run(requirements.request_client_po(
            "REQ-1",
            requirements.ClientPORequest(client_email="client@example.com", body="Please share the PO."),
            db,
        ))

    assert error.value.status_code == 502
    assert "SMTP unavailable" in str(error.value.detail)
    assert client.post.await_args.kwargs["json"]["idempotency_key"] == "client-po-request:REQ-1"
    assert client.post.await_args.kwargs["json"]["ai_generate"] is False


def test_client_po_request_requires_a_saved_client_commercial(monkeypatch):
    response = SimpleNamespace(raise_for_status=lambda: None)
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *_args):
            return False

    collection = SimpleNamespace(
        find_one=AsyncMock(return_value={
            "requirement_id": "REQ-2", "technology_needed": "DevOps",
            "client_email": "client@example.com", "duration_days": 10,
        }),
        update_one=AsyncMock(),
    )

    class FakeDatabase:
        requirements = collection

        def __getitem__(self, name):
            assert name == "requirements"
            return collection

    db = FakeDatabase()
    monkeypatch.setattr(requirements._httpx, "AsyncClient", FakeAsyncClient)
    async def no_commercial(*_args, **_kwargs):
        return None
    monkeypatch.setattr(requirements, "_latest_client_commercial", no_commercial)

    with pytest.raises(HTTPException) as error:
        asyncio.run(requirements.request_client_po(
            "REQ-2",
            requirements.ClientPORequest(client_email="client@example.com"),
            db,
        ))

    assert error.value.status_code == 400
    assert "Client commercial amount is required" in str(error.value.detail)
    assert client.post.await_count == 0
