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
