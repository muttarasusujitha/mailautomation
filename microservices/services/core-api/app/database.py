from app.config import get_settings
from shared.database.connection import connect_database, close_database, get_database

settings = get_settings()


async def init_db():
    return await connect_database(settings.MONGODB_URL, settings.MONGODB_DB_NAME)


async def shutdown_db():
    await close_database()


async def get_db():
    return await get_database()
