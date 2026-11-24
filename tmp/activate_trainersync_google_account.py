"""Activate the explicitly requested local Google sign-in account."""
import secrets
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument

from app.config import get_settings


settings = get_settings()
email = "sujithaofficial784@gmail.com"
with MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=10000) as client:
    users = client[settings.MONGODB_DB_NAME].auth_users
    user = users.find_one_and_update(
        {"email_normalized": email},
        {
            "$set": {"status": "active", "updated_at": datetime.now(timezone.utc)},
            "$inc": {"auth_version": 1},
            "$setOnInsert": {
                "user_id": "USR-" + secrets.token_hex(12),
                "email": email,
                "email_normalized": email,
                "name": email.split("@")[0],
                "role": "recruiter",
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "email": 1, "status": 1, "role": 1},
    )
    print(user)
