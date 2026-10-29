import asyncio
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
    db = client["trainersync"]
    await db["client_emails"].update_one(
        {"email_id": "CLH-C54B6FDE24"},
        {
            "$set": {
                "requirement_id": "REQ-A1B3476F",
                "requirement_created": True,
                "requirement_created_at": datetime.utcnow(),
                "status": "sent",
                "reply_status": "sent",
                "reply_sent": True,
                "reply_sent_at": datetime.utcnow(),
            }
        },
    )
    doc = await db["client_emails"].find_one(
        {"email_id": "CLH-C54B6FDE24"},
        {
            "_id": 0,
            "email_id": 1,
            "status": 1,
            "reply_status": 1,
            "requirement_id": 1,
            "requirement_created": 1,
            "reply_sent": 1,
            "reply_sent_at": 1,
        },
    )
    await db["email_logs"].update_many(
        {"source_email_id": "CLH-C54B6FDE24", "mail_type": "client_reply"},
        {"$set": {"requirement_id": "REQ-A1B3476F", "updated_at": datetime.utcnow()}},
    )
    print(doc)
    client.close()


asyncio.run(main())
