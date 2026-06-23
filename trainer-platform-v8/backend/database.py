from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings
import asyncio
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

client: AsyncIOMotorClient = None

# REL-001: Retry constants for transient MongoDB connection failures
_DB_CONNECT_RETRIES = 5
_DB_CONNECT_DELAY_S = 2


async def connect_db():
    global client
    last_exc = None
    for attempt in range(1, _DB_CONNECT_RETRIES + 1):
        try:
            client = AsyncIOMotorClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
            )
            # Force an actual connection check
            await client.admin.command("ping")
            logger.info("Connected to MongoDB: %s", settings.mongodb_db)
            db = client[settings.mongodb_db]
            await _create_indexes(db)
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "MongoDB connection attempt %d/%d failed: %s",
                attempt, _DB_CONNECT_RETRIES, exc,
            )
            if attempt < _DB_CONNECT_RETRIES:
                await asyncio.sleep(_DB_CONNECT_DELAY_S * attempt)
    raise RuntimeError(
        f"Could not connect to MongoDB after {_DB_CONNECT_RETRIES} attempts: {last_exc}"
    )


async def _create_indexes(db) -> None:
    """Create all required indexes idempotently."""
    await db["conversations"].create_index(
        [("trainer_id", 1), ("requirement_id", 1), ("sent_at", 1)],
        background=True,
    )
    await db["conversations"].create_index(
        [("requirement_id", 1), ("trainer_id", 1), ("sent_at", 1)],
        background=True,
    )
    await db["email_logs"].create_index(
        [("trainer_id", 1), ("requirement_id", 1), ("reply_received", 1), ("replied_at", 1)],
        background=True,
    )
    await db["email_logs"].create_index(
        [("requirement_id", 1), ("trainer_id", 1), ("mail_type", 1), ("created_at", 1)],
        background=True,
    )
    await db["trainer_profile_leads"].create_index(
        [("source", 1), ("created_at", -1)],
        background=True,
    )
    await db["trainer_profile_leads"].create_index(
        [("source", 1), ("status", 1), ("created_at", -1)],
        background=True,
    )
    await db["trainer_profile_leads"].create_index(
        [("lead_id", 1)],
        background=True,
    )


def close_db():
    global client
    if client:
        client.close()
        client = None


def get_db():
    return client[settings.mongodb_db]
