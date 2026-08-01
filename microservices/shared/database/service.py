"""Service-level database helpers built on the shared MongoDB connection."""
from shared.database.connection import close_database, connect_database, get_database


async def init_db(settings):
    return await connect_database(settings.MONGODB_URL, settings.MONGODB_DB_NAME)


async def shutdown_db():
    await close_database()


async def get_db():
    return await get_database()
