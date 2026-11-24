"""Redis Streams event-bus helpers.

Services that need to emit or consume cross-service events use these helpers
instead of calling Redis directly.  The stream names follow the convention:
  <domain>.<event_name>   e.g.  trainer.shortlisted, email.received
"""
import json
import logging
from typing import AsyncIterator, Dict, Any

logger = logging.getLogger(__name__)


async def _get_redis(redis_url: str):
    """Lazy import so services that don't use Redis don't need aioredis installed."""
    import aioredis  # type: ignore
    return await aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)


async def publish_event(
    redis,
    stream: str,
    payload: Dict[str, Any],
    maxlen: int = 10_000,
) -> str:
    """Append *payload* to *stream* and return the assigned message-id."""
    message = {"data": json.dumps(payload)}
    msg_id = await redis.xadd(stream, message, maxlen=maxlen)
    logger.debug("Published event  stream=%s  id=%s", stream, msg_id)
    return msg_id


async def ensure_consumer_group(redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def consume_events(
    redis,
    stream: str,
    group: str,
    consumer: str,
    batch_size: int = 10,
    block_ms: int = 5_000,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield acknowledged events from a Redis Stream consumer group."""
    await ensure_consumer_group(redis, stream, group)
    while True:
        results = await redis.xreadgroup(
            group, consumer, {stream: ">"}, count=batch_size, block=block_ms
        )
        if not results:
            continue
        for _stream, messages in results:
            for msg_id, fields in messages:
                try:
                    payload = json.loads(fields["data"])
                    yield {"id": msg_id, "payload": payload}
                    await redis.xack(stream, group, msg_id)
                except Exception as exc:
                    logger.error("Failed to process event  id=%s  err=%s", msg_id, exc)
