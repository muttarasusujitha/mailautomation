"""Celery application — broker is Redis, beat schedule drives all periodic tasks."""
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "scheduler",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.reminders",
        "app.tasks.inbox_poll",
        "app.tasks.interview_reminders",
        "app.tasks.meet_start_notices",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# ── Beat schedule ──────────────────────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # Poll Gmail inbox every minute so trainer/client automations continue without the browser open.
    "poll-inbox-every-minute": {
        "task": "app.tasks.inbox_poll.poll_inbox",
        "schedule": crontab(minute="*"),
        "args": [],
    },
    # Check and send interview reminders every 10 minutes
    "interview-reminders-every-10-min": {
        "task": "app.tasks.interview_reminders.send_due_reminders",
        "schedule": crontab(minute="*/10"),
        "args": [],
    },
    # Send exact start-time Google Meet join notices every minute.
    "meet-start-notices-every-minute": {
        "task": "app.tasks.meet_start_notices.send_due_start_notices",
        "schedule": crontab(minute="*"),
        "args": [],
    },
    # Daily cleanup of old processed logs (2 AM UTC)
    "daily-log-cleanup": {
        "task": "app.tasks.reminders.cleanup_old_logs",
        "schedule": crontab(hour=2, minute=0),
        "args": [],
    },
    # First trainer follow-up for unanswered Mail 1 after 6 hours.
    # Checked hourly; each original Mail 1 can produce this follow-up only once.
    "trainer-followup-1-hourly": {
        "task": "app.tasks.reminders.send_followup_reminders",
        "schedule": crontab(minute=0),
        "args": [],
    },
    # Second and final trainer follow-up 24 hours after the first follow-up.
    # Checked hourly; each original Mail 1 can produce this follow-up only once.
    "trainer-followup-2-hourly": {
        "task": "app.tasks.reminders.send_followup2_reminders",
        "schedule": crontab(minute=0),
        "args": [],
    },
}
