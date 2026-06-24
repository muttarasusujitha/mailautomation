"""
Retry Scheduler Agent — APScheduler
Supports configurable retry intervals: days, hours, or minutes
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from utils.time_utils import utc_now
import logging
import httpx
from database import get_db
from agents.email_agent import send_email_async, compose_retry_email
from agents.client_slot_agent import send_pending_client_slot_replies
from agents.whatsapp_agent import (
    send_shortlist_whatsapp,
    send_vendor_reply_notification,
)
from agents.client_intelligence_agent import (
    auto_send_pending_client_replies_smtp,
    get_gmail_auth_status,
    poll_imap_client_inbox,
    renew_gmail_watch,
)
from agents.excel_store_agent import sync_business_excel

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)

# ─── Runtime config (updated via API without restart) ─────────────────────────
_config = {
    "retry_interval_unit":    "hours",   # "minutes" | "hours" | "days"
    "retry_interval_value":   6,         # number of units between retries
    "reply_check_interval":   30,        # minutes between inbox checks
    "gmail_fallback_interval":    5,     # minutes between IMAP fallback scans
    "excel_sync_interval":        3,     # minutes between automatic Excel register updates
    "linkedin_client_lead_interval": 60,  # minutes between LinkedIn client post discovery scans
    "linkedin_client_lead_enabled": True,
    "max_retries":            2,
    "auto_retry_enabled":     True,
}


_SCHEDULER_CFG_KEYS = set(_config.keys())


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _coerce_int(value, default: int, minimum: int = 1, maximum: int = 10080) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(parsed, maximum))


def _clean_scheduler_config(raw: dict) -> dict:
    raw = raw or {}
    clean = {}
    if "retry_interval_unit" in raw and raw.get("retry_interval_unit") in {"minutes", "hours", "days"}:
        clean["retry_interval_unit"] = raw["retry_interval_unit"]
    if "retry_interval_value" in raw:
        clean["retry_interval_value"] = _coerce_int(raw.get("retry_interval_value"), _config["retry_interval_value"])
    if "reply_check_interval" in raw:
        clean["reply_check_interval"] = _coerce_int(raw.get("reply_check_interval"), _config["reply_check_interval"])
    if "gmail_fallback_interval" in raw:
        clean["gmail_fallback_interval"] = _coerce_int(raw.get("gmail_fallback_interval"), _config["gmail_fallback_interval"])
    if "excel_sync_interval" in raw:
        clean["excel_sync_interval"] = _coerce_int(raw.get("excel_sync_interval"), _config["excel_sync_interval"])
    if "linkedin_client_lead_interval" in raw:
        clean["linkedin_client_lead_interval"] = _coerce_int(raw.get("linkedin_client_lead_interval"), _config["linkedin_client_lead_interval"])
    if "max_retries" in raw:
        clean["max_retries"] = _coerce_int(raw.get("max_retries"), _config["max_retries"], minimum=0, maximum=10)
    if "auto_retry_enabled" in raw:
        clean["auto_retry_enabled"] = _coerce_bool(raw.get("auto_retry_enabled"), _config["auto_retry_enabled"])
    if "linkedin_client_lead_enabled" in raw:
        clean["linkedin_client_lead_enabled"] = _coerce_bool(raw.get("linkedin_client_lead_enabled"), _config["linkedin_client_lead_enabled"])
    return clean


async def load_config_from_db(reschedule: bool = False) -> dict:
    db = get_db()
    settings = await db["admin_settings"].find_one(
        {"settings_id": "default"},
        {"_id": 0, "schedulerCfg": 1},
    ) or {}
    clean = _clean_scheduler_config(settings.get("schedulerCfg") or {})
    if clean:
        _config.update(clean)
        if reschedule:
            _reschedule_jobs()
    return get_config()


async def save_config_to_db(new_cfg: dict) -> dict:
    clean = _clean_scheduler_config(new_cfg)
    if not clean:
        return get_config()
    db = get_db()
    await db["admin_settings"].update_one(
        {"settings_id": "default"},
        {"$set": {"settings_id": "default", "schedulerCfg": {**_config, **clean}, "updated_at": utc_now()}},
        upsert=True,
    )
    _config.update(clean)
    _reschedule_jobs()
    logger.info("Scheduler config saved to admin_settings: %s", _config)
    return get_config()


def _requirement_locked_for_other_trainer(requirement: dict, trainer_id: str) -> bool:
    requirement = requirement or {}
    selected_trainer_id = str(requirement.get("selected_trainer_id") or "").strip()
    selection_status = str(requirement.get("selection_status") or requirement.get("status") or "").strip().lower()
    locked_statuses = {
        "selected",
        "trainer_selected_auto_sent",
        "toc_requested",
        "training_confirmed",
        "closed",
        "fulfilled",
    }
    locked = bool(selected_trainer_id) or selection_status in locked_statuses
    return locked and (not selected_trainer_id or str(trainer_id or "").strip() != selected_trainer_id)

def get_config():
    return dict(_config)

def update_config(new_cfg: dict):
    """Update runtime config and reschedule jobs live."""
    _config.update(_clean_scheduler_config({k: v for k, v in new_cfg.items() if k in _SCHEDULER_CFG_KEYS}))
    _reschedule_jobs()
    logger.info("Scheduler config updated: %s", _config)


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
            if scheduler.get_job("retry_job"):
                scheduler.reschedule_job(
                    "retry_job",
                    trigger=_interval_trigger_from_config(
                        _config["retry_interval_unit"],
                        _config["retry_interval_value"]
                    )
                )
            if scheduler.get_job("reply_check_job"):
                scheduler.reschedule_job(
                    "reply_check_job",
                    trigger=IntervalTrigger(minutes=int(_config["reply_check_interval"]))
                )
            if scheduler.get_job("client_inbox_imap_fallback_job"):
                scheduler.reschedule_job(
                    "client_inbox_imap_fallback_job",
                    trigger=IntervalTrigger(minutes=int(_config["gmail_fallback_interval"]))
                )
            if scheduler.get_job("business_excel_sync_job"):
                scheduler.reschedule_job(
                    "business_excel_sync_job",
                    trigger=IntervalTrigger(minutes=int(_config["excel_sync_interval"]))
                )
            if scheduler.get_job("linkedin_client_lead_discovery_job"):
                scheduler.reschedule_job(
                    "linkedin_client_lead_discovery_job",
                    trigger=IntervalTrigger(minutes=int(_config["linkedin_client_lead_interval"]))
                )
            logger.info(
                "Jobs rescheduled: retry every %s %s, reply check every %s min, Excel sync every %s min, LinkedIn client discovery every %s min",
                _config["retry_interval_value"],
                _config["retry_interval_unit"],
                _config["reply_check_interval"],
                _config["excel_sync_interval"],
                _config["linkedin_client_lead_interval"],
            )
    except Exception:
        logger.exception("Reschedule error")


async def retry_unreplied_trainers():
    await load_config_from_db()
    if not _config["auto_retry_enabled"]:
        return

    db = get_db()
    unit  = _config["retry_interval_unit"]
    value = int(_config["retry_interval_value"])
    if unit == "minutes":
        cutoff = utc_now() - timedelta(minutes=value)
    elif unit == "hours":
        cutoff = utc_now() - timedelta(hours=value)
    else:
        cutoff = utc_now() - timedelta(days=value)

    docs = await db["email_logs"].find({
        "reply_received": False,
        "status":         "sent",
        "retry_count":    {"$lt": _config["max_retries"]},
        "sent_at":        {"$lt": cutoff},
    }).to_list(length=100)

    logger.info("Retry scheduler: %s trainers needing follow-up (%s %s ago)", len(docs), value, unit)

    for doc in docs:
        req  = await db["requirements"].find_one({"requirement_id": doc.get("requirement_id")})
        if _requirement_locked_for_other_trainer(req, doc.get("trainer_id", "")):
            await db["email_logs"].update_one(
                {"email_id": doc.get("email_id")},
                {"$set": {
                    "auto_retry_status": "skipped_requirement_selected",
                    "auto_retry_skipped_at": utc_now(),
                }},
            )
            continue
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
                    "last_retry_at": utc_now(),
                    "whatsapp_summary": whatsapp_result,
                }}
            )

    await check_and_update_replies()


async def check_and_update_replies():
    await load_config_from_db()
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
                replied_at = utc_now()
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
                if log.get("mail_type") == "client_slot_options":
                    continue
                status_map = {"mark_interested": "interested", "mark_declined": "declined", "requires_review": "pending_review"}
                await db["trainers"].update_one(
                    {"trainer_id": log.get("trainer_id")},
                    {"$set": {"status": status_map.get(reply["action"], "pending_review")}}
                )
                if log.get("mail_type") == "mail3" and (
                    reply.get("action") == "mark_interested" or reply.get("sentiment") == "positive"
                ):
                    await db["email_logs"].update_one(
                        {"email_id": log.get("email_id")},
                        {"$set": {
                            "client_slot_auto_result": {
                                "skipped": True,
                                "manual_only": True,
                                "reason": "Client slot mails are manual only",
                            },
                            "client_slot_auto_checked_at": utc_now(),
                        }},
                    )
        msg_ids = [r.get("msg_id") for r in replies if r.get("msg_id")]
        if msg_ids:
            mark_emails_seen(msg_ids)
        pending_slots = await send_pending_client_slot_replies(
            db,
            source="reply_scheduler_pending_scan",
        )
        if pending_slots.get("sent") or pending_slots.get("failed"):
            logger.info(
                "Client slot auto-send: %s sent, %s failed",
                pending_slots.get("sent"),
                pending_slots.get("failed"),
            )
    except Exception:
        logger.exception("Reply check error")


async def renew_gmail_watch_job():
    db = get_db()
    try:
        result = await renew_gmail_watch(db)
        logger.info("Gmail watch renewed: historyId=%s", result.get("historyId"))
    except Exception:
        logger.exception("Gmail watch renewal skipped/failed")


async def poll_client_inbox_fallback_job():
    await load_config_from_db()
    db = get_db()
    try:
        settings_doc = await db["admin_settings"].find_one(
            {"settings_id": "default"},
            {"_id": 0, "clientInboxCfg.inboxProvider": 1},
        ) or {}
        inbox_provider = str(((settings_doc.get("clientInboxCfg") or {}).get("inboxProvider")) or "smtp_only").strip().lower()
        if inbox_provider in {"smtp_only", "smtp"}:
            # SMTP-only test mode intentionally skips inbox polling.
            auto_sent_existing = await auto_send_pending_client_replies_smtp(db)
            if auto_sent_existing:
                logger.info("SMTP-only client inbox sent %s pending replies", len(auto_sent_existing))
            return

        if inbox_provider in {"imap", "imap_poll", "imap_polling"}:
            result = await poll_imap_client_inbox(db)
            if result.get("processed"):
                logger.info("IMAP fallback processed %s client emails", result.get("processed"))
            if result.get("auto_sent_existing"):
                logger.info("IMAP fallback auto-sent %s pending client replies", result.get("auto_sent_existing"))
            elif result.get("skipped"):
                logger.warning("IMAP fallback skipped: %s", result.get("skipped"))
            return

        status = await get_gmail_auth_status(db)
        watch_expiration = status.get("watch_expiration")
        watch_active = False
        if watch_expiration:
            try:
                watch_active = datetime.fromisoformat(str(watch_expiration)) > utc_now()
            except Exception:
                watch_active = False
        if status.get("valid") and watch_active:
            # Gmail watch is active — webhook should deliver new mails.
            # But STILL run pending-reply sweep to catch any emails that were
            # stored as "pending_approval" but never auto-sent (e.g. low confidence
            # emails that got reclassified, or ones that missed the first send attempt).
            pending = await auto_send_pending_client_replies_smtp(db)
            if pending:
                logger.info("Gmail watch active — swept %s pending client replies", len(pending))
            return
        if status.get("valid"):
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.post("http://127.0.0.1:8000/api/gmail/sync-now?limit=25")
                    response.raise_for_status()
                    result = response.json()
                if result.get("processed_count") or result.get("auto_sent_existing_count"):
                    logger.info(
                        "Gmail API fallback sync processed=%s auto_sent_existing=%s",
                        result.get("processed_count"),
                        result.get("auto_sent_existing_count"),
                    )
                return
            except Exception:
                logger.exception("Gmail API fallback sync failed; continuing with IMAP poll")
        result = await poll_imap_client_inbox(db)
        if result.get("processed"):
            logger.info("IMAP fallback processed %s client emails", result.get("processed"))
        if result.get("auto_sent_existing"):
            logger.info("IMAP fallback auto-sent %s pending client replies", result.get("auto_sent_existing"))
        elif result.get("skipped"):
            logger.warning("IMAP fallback skipped: %s", result.get("skipped"))
    except Exception:
        logger.exception("IMAP client inbox fallback failed")


async def sync_business_excel_job():
    await load_config_from_db()
    db = get_db()
    try:
        result = await sync_business_excel(db)
        logger.info(
            "Business Excel register updated: %s (%s trainers, %s requirements)",
            result.get("path"),
            (result.get("counts") or {}).get("trainers"),
            (result.get("counts") or {}).get("requirements"),
        )
    except Exception:
        logger.exception("Business Excel register update failed")


async def discover_linkedin_client_leads_job():
    await load_config_from_db()
    if not _config.get("linkedin_client_lead_enabled", True):
        return
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            response = await client.post(
                "http://127.0.0.1:8000/api/client-leads/search-public",
                json={
                    "auto_discover": True,
                    "max_results": 8,
                    "max_queries": 180,
                    "concurrency": 4,
                },
            )
            response.raise_for_status()
            result = response.json()
        logger.info(
            "LinkedIn client lead discovery: saved=%s skipped=%s",
            result.get("saved_count"),
            result.get("skipped_count"),
        )
    except Exception:
        logger.exception("LinkedIn client lead discovery failed")


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
        next_run_time=utc_now(),
    )
    scheduler.add_job(
        sync_business_excel_job,
        trigger=IntervalTrigger(minutes=int(_config["excel_sync_interval"])),
        id="business_excel_sync_job", name="Business Excel Register Sync", replace_existing=True,
        next_run_time=utc_now(),
    )
    scheduler.add_job(
        discover_linkedin_client_leads_job,
        trigger=IntervalTrigger(minutes=int(_config["linkedin_client_lead_interval"])),
        id="linkedin_client_lead_discovery_job", name="LinkedIn Client Lead Discovery", replace_existing=True,
        next_run_time=utc_now(),
    )
    scheduler.start()
    logger.info(
        "Scheduler started: retry every %s %s",
        _config["retry_interval_value"],
        _config["retry_interval_unit"],
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
