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
