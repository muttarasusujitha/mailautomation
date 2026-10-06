from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import client_pipeline
from shared.database.service import get_db


def pipeline_client(monkeypatch):
    requirement = {"requirement_id": "REQ-1", "client_name": "Sample Client", "duration_days": 5}
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[requirement])
    db = {
        "requirements": SimpleNamespace(count_documents=AsyncMock(return_value=1), find=Mock(return_value=cursor)),
        "shortlists": SimpleNamespace(find_one=AsyncMock(return_value={})),
        "purchase_orders": SimpleNamespace(find_one=AsyncMock(return_value={"po_id": "PO-1", "total_amount": 2000})),
        "invoices": SimpleNamespace(find_one=AsyncMock(return_value={"invoice_id": "INV-1"})),
    }
    timeline = AsyncMock(return_value={"messages": [{"body": "Previous conversation"}], "last_preview": "Previous conversation"})
    monkeypatch.setattr(client_pipeline, "_client_timeline", timeline)
    app = FastAPI()
    app.include_router(client_pipeline.router, prefix="/client-pipeline")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), timeline


def test_billing_summary_keeps_commercial_data_without_loading_conversations(monkeypatch):
    client, timeline = pipeline_client(monkeypatch)
    response = client.get("/client-pipeline?include_timeline=false")
    assert response.status_code == 200
    item = response.json()["pipeline"][0]
    assert item["duration_days"] == 5
    assert item["client"]["name"] == "Sample Client"
    assert item["client_po"]["total_amount"] == 2000
    assert item["invoice"]["invoice_id"] == "INV-1"
    assert item["messages"] == []
    timeline.assert_not_awaited()


def test_client_pipeline_keeps_conversations_by_default(monkeypatch):
    client, timeline = pipeline_client(monkeypatch)
    response = client.get("/client-pipeline")
    assert response.status_code == 200
    assert response.json()["pipeline"][0]["last_preview"] == "Previous conversation"
    timeline.assert_awaited_once()
