from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

client: AsyncIOMotorClient = None

async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.mongodb_uri)
    logger.info("Connected to MongoDB: %s", settings.mongodb_db)
    db = client[settings.mongodb_db]
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

def get_db():
    return client[settings.mongodb_db]
