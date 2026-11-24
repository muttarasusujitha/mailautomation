import asyncio

from app.gmail_client import check_gmail_api_replies
from app.config import get_settings
from shared.database.service import get_db, init_db, shutdown_db
from app.routes.inbox import _create_requirement, _extract_requirement_from_email


async def main():
    replies = check_gmail_api_replies(
        since_days=30,
        max_messages=20,
        from_emails=["kalludevakeerthana@gmail.com"],
    )
    if not replies:
        print({"error": "Kallu DevOps email was not found in Gmail"})
        return
    reply = max(replies, key=lambda item: str(item.get("received_at") or ""))
    await init_db(get_settings())
    db = await get_db()
    gmail_message_id = reply.get("gmail_message_id") or ""
    existing = await db["requirements"].find_one(
        {"metadata.gmail_message_id": gmail_message_id}, {"_id": 0, "requirement_id": 1},
    )
    if existing:
        print({"requirement_id": existing.get("requirement_id"), "existing": True})
        await shutdown_db()
        return
    email_id = f"INB-{gmail_message_id.upper()}"
    body = reply.get("body") or ""
    email_doc = {
        "email_id": email_id,
        "from_email": reply.get("from_email") or "",
        "sender": reply.get("from_email") or "",
        "from_name": "Kallu Deva Keerthana",
        "subject": reply.get("subject") or "DevOps training requirement",
        "body": body,
        "raw_body": body,
        "clean_body": body,
        "classification_body": body,
        "gmail_message_id": gmail_message_id,
        "latest_gmail_message_id": gmail_message_id,
        "received_at": reply.get("received_at"),
        "attachment_names": reply.get("attachment_names") or [],
        "attachments": reply.get("attachments") or [],
    }
    extracted = _extract_requirement_from_email(
        subject=email_doc["subject"], body=body,
        sender_email=email_doc["from_email"], sender_name=email_doc["from_name"],
    )
    result = await _create_requirement(email_doc, extracted, db, force_new_requirement=True)
    requirement_id = result.get("requirement_id") or ""
    if requirement_id:
        from datetime import datetime
        now = datetime.utcnow()
        await db["client_emails"].update_one(
            {"email_id": email_id},
            {"$set": {
                **email_doc, "requirement_id": requirement_id, "processed": True,
                "status": "auto_sent", "reply_status": "sent",
                "classification_reason": "proposal_requirement_recovered_from_gmail",
                "proposal_requirement_recovery_attempted": True,
                "created_at": now, "updated_at": now,
            }},
            upsert=True,
        )
    print({"requirement_id": requirement_id, "existing": bool(result.get("existing")),
           "pipeline": "shortlist", "source_gmail_message_id": gmail_message_id})
    await shutdown_db()


asyncio.run(main())
