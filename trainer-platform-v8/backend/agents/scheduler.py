"""
Retry Scheduler Agent — APScheduler
Supports configurable retry intervals: days, hours, or minutes
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from database import get_db
from agents.email_agent import send_email_async, compose_retry_email
from agents.whatsapp_agent import (
    send_shortlist_whatsapp,
    send_vendor_reply_notification,
)
from agents.client_intelligence_agent import (
    get_gmail_auth_status,
    poll_imap_client_inbox,
    renew_gmail_watch,
)

scheduler = AsyncIOScheduler()

# ─── Runtime config (updated via API without restart) ─────────────────────────
_config = {
    "retry_interval_unit":    "hours",   # "minutes" | "hours" | "days"
    "retry_interval_value":   6,         # number of units between retries
    "reply_check_interval":   30,        # minutes between inbox checks
    "gmail_fallback_interval":    5,     # minutes between IMAP fallback scans
    "max_retries":            2,
    "auto_retry_enabled":     True,
}

def get_config():
    return dict(_config)

def update_config(new_cfg: dict):
    """Update runtime config and reschedule jobs live."""
    _config.update({k: v for k, v in new_cfg.items() if k in _config})
    _reschedule_jobs()
    print(f"Scheduler config updated: {_config}")


def _interval_trigger_from_config(unit: str, value: int) -> IntervalTrigger:
    kwargs = {}
    if unit == "minutes":
        kwargs["minutes"] = int(value)
    elif unit == "hours":
        kwargs["hours"] = int(value)
    else:
        kwargs["days"] = int(value)
    return IntervalTrigger(**kwargs)


def _reschedule_jobs():
    try:
        if scheduler.running:
            scheduler.reschedule_job(
                "retry_job",
                trigger=_interval_trigger_from_config(
                    _config["retry_interval_unit"],
                    _config["retry_interval_value"]
                )
            )
            scheduler.reschedule_job(
                "reply_check_job",
                trigger=IntervalTrigger(minutes=int(_config["reply_check_interval"]))
            )
            print(f"Jobs rescheduled: retry every {_config['retry_interval_value']} {_config['retry_interval_unit']}, "
                  f"reply check every {_config['reply_check_interval']} min")
    except Exception as e:
        print(f"Reschedule error: {e}")


async def retry_unreplied_trainers():
    if not _config["auto_retry_enabled"]:
        return

    db = get_db()
    unit  = _config["retry_interval_unit"]
    value = int(_config["retry_interval_value"])
    if unit == "minutes":
        cutoff = datetime.utcnow() - timedelta(minutes=value)
    elif unit == "hours":
        cutoff = datetime.utcnow() - timedelta(hours=value)
    else:
        cutoff = datetime.utcnow() - timedelta(days=value)

    docs = await db["email_logs"].find({
        "reply_received": False,
        "status":         "sent",
        "retry_count":    {"$lt": _config["max_retries"]},
        "sent_at":        {"$lt": cutoff},
    }).to_list(length=100)

    print(f"Retry scheduler: {len(docs)} trainers needing follow-up ({value} {unit} ago)")

    for doc in docs:
        req  = await db["requirements"].find_one({"requirement_id": doc.get("requirement_id")})
        tech = req.get("technology_needed", "the technology") if req else "the technology"
        body = compose_retry_email(
            trainer_name=doc.get("trainer_name", "Trainer"),
            technology=tech,
            req_id=doc.get("requirement_id", "")
        )
        subject = f"Following Up — Training Opportunity [{doc.get('requirement_id', '')}]"
        success, _ = await send_email_async(doc["to_email"], subject, body, tracking_url=doc.get("tracking_url", ""))
        trainer = await db["trainers"].find_one(
            {"trainer_id": doc.get("trainer_id")},
            {"_id": 0, "phone": 1},
        ) or {}
        whatsapp_result = await send_shortlist_whatsapp(
            db,
            trainer_phone=doc.get("trainer_phone") or trainer.get("phone", ""),
            trainer_name=doc.get("trainer_name", ""),
            subject=subject,
            body=body,
            mail_type="mail1_reminder",
            requirement_id=doc.get("requirement_id", ""),
            email_id=doc.get("email_id", ""),
        )
        if success:
            await db["email_logs"].update_one(
                {"email_id": doc["email_id"]},
                {"$inc": {"retry_count": 1}, "$set": {
                    "last_retry_at": datetime.utcnow(),
                    "whatsapp_summary": whatsapp_result,
                }}
            )

    await check_and_update_replies()


async def check_and_update_replies():
    from agents.email_agent import check_email_replies, mark_emails_seen
    import re as _re
    db = get_db()
    try:
        replies = check_email_replies(since_days=7)
        for reply in replies:
            m = _re.search(r'<([^>]+)>', reply["from_email"])
            from_email_clean = m.group(1) if m else reply["from_email"].strip()

            log = await db["email_logs"].find_one(
                {"to_email": {"$regex": from_email_clean, "$options": "i"}, "status": "sent"},
                sort=[("created_at", -1)]
            )
            if not log:
                log = await db["conversations"].find_one(
                    {"to_email": {"$regex": from_email_clean, "$options": "i"}, "direction": "sent"},
                    sort=[("sent_at", -1)]
                )
            if log:
                req_id     = log.get("requirement_id")
                replied_at = datetime.utcnow()
                await db["email_logs"].update_one(
                    {"email_id": log.get("email_id")},
                    {"$set": {"reply_received": True, "reply_text": reply["body"],
                              "reply_sentiment": reply["sentiment"], "replied_at": replied_at}}
                )
                already = await db["conversations"].find_one({
                    "to_email": from_email_clean, "requirement_id": req_id,
                    "direction": "received", "subject": reply["subject"]
                })
                if not already:
                    await db["conversations"].insert_one({
                        "trainer_id":     log.get("trainer_id"),
                        "trainer_name":   log.get("trainer_name"),
                        "to_email":       from_email_clean,
                        "requirement_id": req_id,
                        "subject":        reply["subject"],
                        "body":           reply["body"],
                        "direction":      "received",
                        "mail_type":      "reply",
                        "status":         "received",
                        "sent_at":        replied_at,
                    })
                    await send_vendor_reply_notification(
                        db,
                        trainer_name=log.get("trainer_name", ""),
                        trainer_id=log.get("trainer_id", ""),
                        requirement_id=req_id,
                        mail_type=log.get("mail_type", ""),
                        reply_subject=reply.get("subject", ""),
                        reply_body=reply.get("body", ""),
                        sentiment=reply.get("sentiment", ""),
                    )
                status_map = {"mark_interested": "interested", "mark_declined": "declined", "requires_review": "pending_review"}
                await db["trainers"].update_one(
                    {"trainer_id": log.get("trainer_id")},
                    {"$set": {"status": status_map.get(reply["action"], "pending_review")}}
                )
        msg_ids = [r.get("msg_id") for r in replies if r.get("msg_id")]
        if msg_ids:
            mark_emails_seen(msg_ids)
    except Exception as e:
        print(f"Reply check error: {e}")


async def renew_gmail_watch_job():
    db = get_db()
    try:
        result = await renew_gmail_watch(db)
        print(f"Gmail watch renewed: historyId={result.get('historyId')}")
    except Exception as e:
        print(f"Gmail watch renewal skipped/failed: {e}")


async def poll_client_inbox_fallback_job():
    db = get_db()
    try:
        status = await get_gmail_auth_status(db)
        if status.get("valid"):
            return
        result = await poll_imap_client_inbox(db)
        if result.get("processed"):
            print(f"IMAP fallback processed {result.get('processed')} client emails")
    except Exception as e:
        print(f"IMAP client inbox fallback failed: {e}")


def start_scheduler():
    scheduler.add_job(
        retry_unreplied_trainers,
        trigger=_interval_trigger_from_config(_config["retry_interval_unit"], _config["retry_interval_value"]),
        id="retry_job", name="Retry Unreplied Trainers", replace_existing=True,
    )
    scheduler.add_job(
        check_and_update_replies,
        trigger=IntervalTrigger(minutes=int(_config["reply_check_interval"])),
        id="reply_check_job", name="Check Email Replies", replace_existing=True,
    )
    scheduler.add_job(
        renew_gmail_watch_job,
        trigger=IntervalTrigger(days=6),
        id="gmail_watch_renewal_job", name="Renew Gmail Watch", replace_existing=True,
    )
    scheduler.add_job(
        poll_client_inbox_fallback_job,
        trigger=IntervalTrigger(minutes=int(_config["gmail_fallback_interval"])),
        id="client_inbox_imap_fallback_job", name="Client Inbox IMAP Fallback", replace_existing=True,
    )
    scheduler.start()
    print(f"Scheduler started: retry every {_config['retry_interval_value']} {_config['retry_interval_unit']}")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
