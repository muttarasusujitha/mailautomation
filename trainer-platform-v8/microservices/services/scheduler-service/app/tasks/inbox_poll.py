"""Periodic Gmail inbox polling task — delegates to email-service via HTTP."""
import logging
import httpx

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="app.tasks.inbox_poll.poll_inbox", bind=True, max_retries=3)
def poll_inbox(self):
    """Call email-service /inbox/poll/sync to fetch new inbound emails."""
    url = f"{settings.EMAIL_SERVICE_URL}/api/v1/email/inbox/poll/sync"
    try:
        resp = httpx.post(url, json={"since_days": 1, "max_messages": 100}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Inbox poll: fetched=%s stored=%s", data.get("fetched"), data.get("stored"))
        return data
    except Exception as exc:
        logger.error("Inbox poll failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
