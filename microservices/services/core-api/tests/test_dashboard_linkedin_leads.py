from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import dashboard
from shared.database.service import get_db


def _collection(count=0, docs=None):
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=docs or [])
    return SimpleNamespace(
        count_documents=AsyncMock(return_value=count),
        find=Mock(return_value=cursor),
    )


def test_dashboard_includes_linkedin_client_requirements_and_trainers():
    created = datetime(2026, 10, 6, 8, 0, 0)
    db = {
        "requirements": _collection(0),
        "trainers": _collection(1),
        "resume_uploads": _collection(0),
        "trainer_profile_leads": _collection(2, [{
            "lead_id": "TPL-1",
            "name": "Ravi Kumar",
            "domain": "Python",
            "headline": "Python corporate trainer",
            "status": "found",
            "created_at": created,
            "source": "linkedin",
            "source_url": "https://www.linkedin.com/in/ravi-kumar",
        }]),
        "email_logs": _collection(0),
        "client_emails": _collection(1),
        "client_leads": _collection(3, [{
            "lead_id": "CL-1",
            "company_name": "Northwind",
            "contact_name": "Asha",
            "domain": "Python",
            "status": "new",
            "created_at": created,
            "source": "linkedin",
            "source_url": "https://www.linkedin.com/posts/activity-1",
            "post_text": "Looking for a Python trainer for a five day batch.",
        }]),
        "shortlists": _collection(0),
        "whatsapp_logs": _collection(0),
    }
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/dashboard")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).get("/dashboard/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["client_requests"]["inbox"] == 1
    assert body["client_requests"]["linkedin_total"] == 3
    assert body["client_requests"]["total"] == 4
    requirement = body["client_requests"]["recent_linkedin"][0]
    assert requirement["domain"] == "Python"
    assert requirement["summary"].startswith("Looking for a Python trainer")
    assert "post_text" not in requirement
    assert body["trainers"]["confirmed"] == 1
    assert body["trainers"]["leads"] == 2
    assert body["trainers"]["total"] == 2
    trainer = body["trainers"]["recent_linkedin"][0]
    assert trainer["name"] == "Ravi Kumar"
    assert trainer["created_at"] == created.isoformat()
