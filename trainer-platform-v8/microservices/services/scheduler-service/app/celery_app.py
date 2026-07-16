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
    # Poll Gmail inbox every 5 minutes
    "poll-inbox-every-5-min": {
        "task": "app.tasks.inbox_poll.poll_inbox",
        "schedule": crontab(minute="*/5"),
        "args": [],
    },
    # Check and send interview reminders every 10 minutes
    "interview-reminders-every-10-min": {
        "task": "app.tasks.interview_reminders.send_due_reminders",
        "schedule": crontab(minute="*/10"),
        "args": [],
    },
    # Daily cleanup of old processed logs (2 AM UTC)
    "daily-log-cleanup": {
        "task": "app.tasks.reminders.cleanup_old_logs",
        "schedule": crontab(hour=2, minute=0),
        "args": [],
    },
    # Daily follow-up reminders for unanswered trainer emails (9 AM UTC)
    "daily-followup-reminders": {
        "task": "app.tasks.reminders.send_followup_reminders",
        "schedule": crontab(hour=9, minute=0),
        "args": [],
    },
    # Send followup2 for mail1_reminder logs that have been sent at least 3 hours ago.
    "followup2-reminders-every-15-min": {
        "task": "app.tasks.reminders.send_followup2_reminders",
        "schedule": crontab(minute="*/15"),
        "args": [],
    },
    # Send followup3 for mail1_reminder logs that have been sent at least 6 hours ago.
    "followup3-reminders-every-15-min": {
        "task": "app.tasks.reminders.send_followup3_reminders",
        "schedule": crontab(minute="*/15"),
        "args": [],
    },
}
