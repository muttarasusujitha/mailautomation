from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings

settings = get_settings()

client: AsyncIOMotorClient = None

async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.mongodb_uri)
    print(f"Connected to MongoDB: {settings.mongodb_db}")

async def close_db():
    global client
    if client:
        client.close()

def get_db():
    return client[settings.mongodb_db]
