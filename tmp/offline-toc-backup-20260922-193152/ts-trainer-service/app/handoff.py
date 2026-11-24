"""Durable, versioned client packages with automatic client delivery."""
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def package_key(requirement_id, trainer_id):
    # Mongo's unique _id provides the concurrency guard without a migration.
    return f"{len(requirement_id)}:{requirement_id}:{trainer_id}"


def package_response(package):
    status = package.get("status")
    needs_input = status == "needs_input"
    return {
        "success": status == "sent",
        "pending_approval": status == "pending_approval",
        "needs_input": needs_input,
        "package_id": package["package_id"],
        "status": package["status"],
        "slots_count": 3,
        "email_id": package.get("email_id", ""),
        "message": (package.get("last_error") or "Confirm the missing client inputs before delivery.") if needs_input
                    else ("Client package delivered." if status == "sent" else "Client package queued for delivery."),
    }


async def save_package(db, package):
    collection = db["client_handoff_packages"]
    await collection.update_one({"_id": package["_id"]}, {"$setOnInsert": package}, upsert=True)
    # Concurrent preparations use the first complete snapshot, never overwrite
    # the version another reviewer may already have approved.
    saved = await collection.find_one({"_id": package["_id"]})
    if saved["status"] == "pending_approval":
        await db["shortlists"].update_one(
            {"requirement_id": saved["requirement_id"], "top_trainers": {"$elemMatch": {
                "trainer_id": saved["trainer_id"], "client_slots_sent": {"$ne": True},
            }}},
            {"$set": {
                "top_trainers.$.pipeline_status": "slot_booked",
                "top_trainers.$.slot_status": "pending_approval",
                "top_trainers.$.client_handoff_package_id": saved["package_id"],
                "top_trainers.$.slot_reply_text": saved["slot_text"],
                "top_trainers.$.client_handoff_retry_after": None,
                "top_trainers.$.client_slot_error": "",
                "top_trainers.$.client_handoff_error_detail": "",
                "pipeline_summary.current_stage": "client_handoff_pending_approval",
                "updated_at": datetime.utcnow(),
            }},
        )
    return saved


async def deliver_approved_package(db, package):
    from app.routes.shortlists import _deliver_client_handoff

    if package.get("status") == "sent":
        return {**package_response(package), "already_sent": True}
    if package.get("status") != "approved":
        raise HTTPException(409, "This package must be reviewed and approved before delivery")
    now = datetime.utcnow()
    # Lease allows multiple API processes and survives a worker crash. Email
    # service's persistent idempotency key is the final physical-send guard.
    claimed = await db["client_handoff_packages"].update_one(
        {"_id": package["_id"], "package_id": package["package_id"], "status": "approved",
         "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": now}}]},
        {"$set": {"lease_until": now + timedelta(minutes=3)}},
    )
    if not claimed.modified_count:
        return {"success": False, "retry_pending": True, "message": "Approved delivery is in progress"}
    try:
        result = await _deliver_client_handoff(package, db)
        await db["client_handoff_packages"].update_one(
            {"_id": package["_id"], "package_id": package["package_id"]},
            {"$set": {"status": "sent", "email_id": result["email_id"], "sent_at": datetime.utcnow(),
                      "last_error": ""}, "$unset": {"lease_until": "", "retry_after": ""}},
        )
        return {**package_response({**package, "status": "sent", "email_id": result["email_id"]}), **result}
    except Exception as exc:
        detail = str(exc.detail if isinstance(exc, HTTPException) else exc)
        permanent_input_error = isinstance(exc, HTTPException) and exc.status_code == 422
        if permanent_input_error:
            from shared.handoff_inputs import handoff_input_version
            requirement = await db["requirements"].find_one({"requirement_id": package["requirement_id"]}) or {}
            input_version = handoff_input_version(requirement)
            await db["client_handoff_packages"].update_one(
                {"_id": package["_id"], "package_id": package["package_id"]},
                {"$set": {"status": "needs_input", "last_error": detail, "input_version": input_version},
                 "$inc": {"attempts": 1}, "$unset": {"lease_until": "", "retry_after": ""}},
            )
            await db["shortlists"].update_one(
                {"requirement_id": package["requirement_id"], "top_trainers": {"$elemMatch": {
                    "trainer_id": package["trainer_id"], "client_slots_sent": {"$ne": True},
                }}},
                {"$set": {"top_trainers.$.slot_status": "client_handoff_needs_input",
                          "top_trainers.$.client_handoff_error_detail": detail,
                          "top_trainers.$.client_handoff_input_version": input_version,
                          "top_trainers.$.client_handoff_retry_after": None,
                          "pipeline_summary.current_stage": "client_handoff_needs_input"}},
            )
            return {**package_response({**package, "status": "needs_input", "last_error": detail})}
        retry_after = datetime.utcnow() + timedelta(minutes=5)
        await db["client_handoff_packages"].update_one(
            {"_id": package["_id"], "package_id": package["package_id"]},
            {"$set": {"last_error": detail, "retry_after": retry_after},
             "$inc": {"attempts": 1}, "$unset": {"lease_until": ""}},
        )
        await db["shortlists"].update_one(
            {"requirement_id": package["requirement_id"], "top_trainers": {"$elemMatch": {
                "trainer_id": package["trainer_id"], "client_slots_sent": {"$ne": True},
            }}},
            {"$set": {"top_trainers.$.slot_status": "client_handoff_retry_pending",
                      "top_trainers.$.client_handoff_error_detail": detail,
                      "top_trainers.$.client_handoff_retry_after": retry_after}},
        )
        raise


async def retry_approved_packages(db):
    now = datetime.utcnow()
    # Packages created before automatic delivery was enabled remain in Mongo as
    # pending approval. Move them into the same durable retry path as new
    # packages; delivery itself remains idempotent in the email service.
    await db["client_handoff_packages"].update_many(
        {"status": "pending_approval"},
        {"$set": {"status": "approved", "approved_at": now, "auto_delivery": True}},
    )
    cursor = db["client_handoff_packages"].find({
        "status": "approved",
        "$and": [
            {"$or": [{"retry_after": {"$exists": False}}, {"retry_after": {"$lte": now}}]},
            {"$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": now}}]},
        ],
    }).limit(20)
    async for package in cursor:
        try:
            await deliver_approved_package(db, package)
        except Exception:
            logger.exception("Approved handoff retry failed: %s", package["package_id"])


async def retry_changed_input_handoffs(db):
    """Resume corrected requirements even when no new inbox message arrives."""
    from shared.handoff_inputs import handoff_input_version
    from app.routes.shortlists import send_client_slots, SendClientSlotsRequest
    now = datetime.utcnow()
    async for shortlist in db["shortlists"].find({
        "top_trainers.slot_status": "client_handoff_needs_input",
    }):
        requirement_id = shortlist.get("requirement_id")
        requirement = await db["requirements"].find_one({"requirement_id": requirement_id}) or {}
        version = handoff_input_version(requirement)
        for trainer in shortlist.get("top_trainers", []):
            if (trainer.get("slot_status") != "client_handoff_needs_input"
                    or trainer.get("client_slots_sent")
                    or trainer.get("client_handoff_input_version") == version):
                continue
            retry_at = trainer.get("client_handoff_retry_after")
            if isinstance(retry_at, datetime) and retry_at > now:
                continue
            query = {"requirement_id": requirement_id, "top_trainers": {"$elemMatch": {
                "trainer_id": trainer["trainer_id"], "client_slots_sent": {"$ne": True},
                "slot_status": "client_handoff_needs_input",
            }}}
            try:
                await send_client_slots(SendClientSlotsRequest(
                    requirement_id=requirement_id, trainer_id=trainer["trainer_id"],
                    slot_text=trainer.get("slot_reply_text") or "",
                ), db)
            except Exception as exc:
                permanent = isinstance(exc, HTTPException) and exc.status_code in {400, 422}
                changes = {
                    "top_trainers.$.client_handoff_error_detail": str(getattr(exc, "detail", exc)),
                    "top_trainers.$.client_handoff_retry_after": None if permanent else now + timedelta(minutes=5),
                }
                if permanent:
                    changes["top_trainers.$.client_handoff_input_version"] = version
                await db["shortlists"].update_one(query, {"$set": changes})


async def handoff_retry_loop(db):
    while True:
        try:
            await retry_approved_packages(db)
            await retry_changed_input_handoffs(db)
        except Exception:
            logger.exception("Client handoff retry scan failed; next scan will retry")
        await asyncio.sleep(30)
