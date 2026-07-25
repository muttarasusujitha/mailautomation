"""Synchronous Motor wrapper used by Celery tasks (runs outside async context)."""
import asyncio
from functools import lru_cache
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _get_client() -> AsyncIOMotorClient:
    return AsyncIOMotorClient(settings.MONGODB_URL)


def get_db() -> AsyncIOMotorDatabase:
    return _get_client()[settings.MONGODB_DB_NAME]


def run_async(coro):
    """Run a coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
