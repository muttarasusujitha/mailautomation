from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings

settings = get_settings()

client: AsyncIOMotorClient = None

async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.mongodb_uri)
    print(f"Connected to MongoDB: {settings.mongodb_db}")
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

async def close_db():
    global client
    if client:
        client.close()

def get_db():
    return client[settings.mongodb_db]
