"""Shared Motor (async MongoDB) connection helper.

Every microservice calls connect_database() at startup and get_database() via
its FastAPI Depends chain.  The module-level _db variable is intentionally
process-local — each container has its own connection pool.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def connect_database(mongodb_url: str, db_name: str) -> AsyncIOMotorDatabase:
    global _client, _db
    _client = AsyncIOMotorClient(mongodb_url)
    _db = _client[db_name]
    # Verify connectivity
    await _client.admin.command("ping")
    logger.info("Connected to MongoDB  url=%s  db=%s", mongodb_url, db_name)
    return _db


async def close_database() -> None:
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed.")


async def get_database() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError(
            "Database not initialised — call connect_database() first."
        )
    return _db
