"""Periodic Core API agent reconciliation with bounded retries."""
import logging

import httpx

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(name="app.tasks.agent_orchestrator.run_agent_orchestrator", bind=True, max_retries=3)
def run_agent_orchestrator(self, dry_run: bool = False):
    """Ask Core API to preview or record decisions and queue safe actions."""
    url = f"{settings.CORE_API_URL.rstrip('/')}/api/v1/agent-orchestrator/run"
    try:
        response = httpx.post(url, params={"limit": 25, "dry_run": dry_run}, timeout=90)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Agent orchestrator: dry_run=%s created=%s previewed=%s would_queue=%s",
            dry_run,
            result.get("created", 0),
            result.get("previewed", 0),
            result.get("would_queue", 0),
        )
        return result
    except Exception as exc:
        logger.error("Agent orchestrator run failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)
