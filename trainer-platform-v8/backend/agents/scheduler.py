"""
Retry Scheduler Agent — APScheduler
Checks every 3 days for non-responding trainers and sends follow-ups
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from database import get_db
from agents.email_agent import send_email_async, compose_retry_email

scheduler = AsyncIOScheduler()


async def retry_unreplied_trainers():
    """Find trainers who haven't replied in 3 days and send follow-up"""
    db = get_db()
    cutoff = datetime.utcnow() - timedelta(days=3)

    # Find emails sent > 3 days ago, no reply, retry count < 2
    cursor = db["email_logs"].find({
        "reply_received": False,
        "status": "sent",
        "retry_count": {"$lt": 2},
        "sent_at": {"$lt": cutoff}
    })

    docs = await cursor.to_list(length=100)
    print(f"🔄 Retry scheduler: found {len(docs)} trainers needing follow-up")

    for doc in docs:
        # Get requirement info
        req = await db["requirements"].find_one({"requirement_id": doc["requirement_id"]})
        tech = req.get("technology_needed", "the technology") if req else "the technology"

        body = compose_retry_email(
            trainer_name=doc.get("trainer_name", "Trainer"),
            technology=tech,
            req_id=doc["requirement_id"]
        )
        subject = f"Following Up — Training Opportunity [{doc['requirement_id']}]"
        success = await send_email_async(doc["to_email"], subject, body)

        if success:
            await db["email_logs"].update_one(
                {"email_id": doc["email_id"]},
                {"$inc": {"retry_count": 1},
                 "$set": {"last_retry_at": datetime.utcnow()}}
            )
            print(f"  ✅ Follow-up sent to {doc['to_email']}")

    # Daily: check inbox for new replies
    await check_and_update_replies()


async def check_and_update_replies():
    """Poll Gmail inbox for replies and update MongoDB"""
    from agents.email_agent import check_email_replies
    db = get_db()

    try:
        replies = check_email_replies(since_days=7)
        for reply in replies:
            # Match reply to sent email by from_email
            email_log = await db["email_logs"].find_one({"to_email": reply["from_email"]})
            if email_log:
                await db["email_logs"].update_one(
                    {"to_email": reply["from_email"]},
                    {"$set": {
                        "reply_received": True,
                        "reply_text": reply["body"],
                        "reply_sentiment": reply["sentiment"],
                        "replied_at": datetime.utcnow()
                    }}
                )
                # Update trainer status
                status_map = {
                    "mark_interested": "interested",
                    "mark_declined": "declined",
                    "requires_review": "pending_review"
                }
                new_status = status_map.get(reply["action"], "pending_review")
                await db["trainers"].update_one(
                    {"trainer_id": email_log["trainer_id"]},
                    {"$set": {"status": new_status}}
                )
                print(f"  📬 Reply processed: {reply['from_email']} → {new_status}")
    except Exception as e:
        print(f"❌ Reply check error: {e}")


def start_scheduler():
    """Start APScheduler with retry + reply check jobs"""
    scheduler.add_job(
        retry_unreplied_trainers,
        trigger=IntervalTrigger(days=3),
        id="retry_job",
        name="Retry Unreplied Trainers",
        replace_existing=True,
    )
    scheduler.add_job(
        check_and_update_replies,
        trigger=IntervalTrigger(hours=6),
        id="reply_check_job",
        name="Check Email Replies",
        replace_existing=True,
    )
    scheduler.start()
    print("✅ Scheduler started: retry every 3 days, reply check every 6 hours")


def stop_scheduler():
    scheduler.shutdown()
