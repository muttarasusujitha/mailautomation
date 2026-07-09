"""REST endpoints to inspect and manually trigger Celery tasks."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class TriggerResponse(BaseModel):
    task_id: str
    task_name: str
    status: str


@router.post("/inbox-poll", response_model=TriggerResponse)
async def trigger_inbox_poll():
    from app.tasks.inbox_poll import poll_inbox
    task = poll_inbox.delay()
    return TriggerResponse(task_id=task.id, task_name="poll_inbox", status="queued")


@router.post("/interview-reminders", response_model=TriggerResponse)
async def trigger_interview_reminders():
    from app.tasks.interview_reminders import send_due_reminders
    task = send_due_reminders.delay()
    return TriggerResponse(task_id=task.id, task_name="send_due_reminders", status="queued")


@router.post("/followup-reminders", response_model=TriggerResponse)
async def trigger_followup_reminders():
    from app.tasks.reminders import send_followup_reminders
    task = send_followup_reminders.delay()
    return TriggerResponse(task_id=task.id, task_name="send_followup_reminders", status="queued")


@router.post("/followup2-reminders", response_model=TriggerResponse)
async def trigger_followup2_reminders():
    from app.tasks.reminders import send_followup2_reminders
    task = send_followup2_reminders.delay()
    return TriggerResponse(task_id=task.id, task_name="send_followup2_reminders", status="queued")


@router.post("/followup3-reminders", response_model=TriggerResponse)
async def trigger_followup3_reminders():
    from app.tasks.reminders import send_followup3_reminders
    task = send_followup3_reminders.delay()
    return TriggerResponse(task_id=task.id, task_name="send_followup3_reminders", status="queued")


class TestLogRequest(BaseModel):
    to: str
    requirement_id: Optional[str] = "TEST-REQ"
    mail_type: Optional[str] = "mail1_reminder"
    hours_ago: Optional[int] = 4
    trainer_name: Optional[str] = "Test Trainer"


@router.post("/create-test-log")
async def create_test_log(payload: TestLogRequest):
    from datetime import datetime, timedelta
    from app.database import get_db
    import uuid

    db = get_db()
    now = datetime.utcnow()
    sent_at = now - timedelta(hours=payload.hours_ago)
    log = {
        "email_id": f"EMT-{uuid.uuid4().hex[:10].upper()}",
        "direction": "outbound",
        "recipient": payload.to,
        "subject": "Test followup",
        "body_snippet": "Test body",
        "status": "sent",
        "customer_id": None,
        "requirement_id": payload.requirement_id,
        "mail_type": payload.mail_type,
        "trainer_name": payload.trainer_name,
        "sent_at": sent_at,
        "created_at": now,
        "updated_at": now,
        "reminder_sent": True,
    }
    await db.email_logs.insert_one(log)
    return {"success": True, "email_id": log["email_id"], "sent_at": sent_at}


@router.post("/cleanup-logs", response_model=TriggerResponse)
async def trigger_log_cleanup():
    from app.tasks.reminders import cleanup_old_logs
    task = cleanup_old_logs.delay()
    return TriggerResponse(task_id=task.id, task_name="cleanup_old_logs", status="queued")


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    from app.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
