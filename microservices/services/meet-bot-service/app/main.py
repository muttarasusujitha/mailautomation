import asyncio
import logging
import re
import signal
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright

from app.config import get_settings
from app.safety import valid_meet_link

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("meet-bot")
settings = get_settings()
shutdown_event = asyncio.Event()
service_state = {"ready": False, "last_poll": None, "active_meeting": ""}


def _clean(value) -> str:
    return str(value or "").strip()


def _valid_meet_link(link: str) -> bool:
    return valid_meet_link(link, settings.MEET_BOT_ALLOWED_HOSTS)


def _participant_identity(name: str, email: str, role: str) -> tuple[set[str], bool]:
    """Return safe, specific tokens used only to match the visible People list."""
    generic = {"", "client", "team", "trainer", "candidate", "unknown"}
    display_name = _clean(name).lower()
    tokens = {
        token for token in re.findall(r"[a-z0-9]{3,}", display_name)
        if token not in generic
    }
    local_part = _clean(email).split("@", 1)[0].lower()
    local_tokens = {
        token for token in re.findall(r"[a-z0-9]{3,}", local_part)
        if token not in generic
    }
    # Never infer attendance from only the generic role label.  A meaningful
    # name or email-local-part is required before the scheduler may notify.
    specific = bool(tokens or local_tokens)
    return tokens | local_tokens, specific


async def _observe_attendance(page, log: dict, db, email_id: str) -> None:
    """Best-effort, privacy-minimised attendance observation from Meet's People UI.

    We persist only role-level booleans, never a participant list or page text.
    If Meet's UI cannot be read, the scheduler will not send a no-show notice.
    """
    trainer_tokens, trainer_identity_available = _participant_identity(
        _clean(log.get("trainer_name")),
        _clean(log.get("trainer_email") or log.get("to_email") or log.get("recipient")),
        "trainer",
    )
    client_tokens, client_identity_available = _participant_identity(
        _clean(log.get("client_name")),
        _clean(log.get("client_email")),
        "client",
    )
    try:
        await _click_if_visible(page, ["Show everyone", "People", "Participants"])
        await page.wait_for_timeout(600)
        visible_text = (await page.locator("body").inner_text(timeout=2500)).lower()
        trainer_joined = bool(trainer_tokens and any(token in visible_text for token in trainer_tokens))
        client_joined = bool(client_tokens and any(token in visible_text for token in client_tokens))
        now = datetime.utcnow()
        fields = {
            "meet_attendance_observed_at": now,
            "meet_attendance_source": "meet_bot_visible_participants",
            "meet_participant_view_available": True,
            "trainer_attendance_identity_available": trainer_identity_available,
            "client_attendance_identity_available": client_identity_available,
            "trainer_joined": trainer_joined,
            "client_joined": client_joined,
        }
        if trainer_joined:
            fields["trainer_joined_at"] = now
        if client_joined:
            fields["client_joined_at"] = now
        await db.email_logs.update_one({"email_id": email_id}, {"$set": fields})
    except Exception as exc:
        logger.debug("Could not observe participants for %s: %s", email_id, exc)


async def _health_response(reader, writer) -> None:
    try:
        await reader.read(2048)
        healthy = service_state["ready"] or not settings.MEET_BOT_ENABLED
        status = "200 OK" if healthy else "503 Service Unavailable"
        body = b'{"status":"ok"}' if healthy else b'{"status":"starting"}'
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _click_if_visible(page, names: list[str]) -> bool:
    for name in names:
        button = page.get_by_role("button", name=name, exact=False).first
        try:
            if await button.is_visible(timeout=700):
                await button.click()
                return True
        except Exception:
            continue
    return False


async def _join_meeting(log: dict, db) -> None:
    email_id = _clean(log.get("email_id"))
    link = _clean(log.get("interview_link") or log.get("meet_link"))
    if not _valid_meet_link(link):
        await db.email_logs.update_one(
            {"email_id": email_id},
            {"$set": {
                "meet_bot_status": "failed_permanent",
                "meet_bot_error": "Only allowlisted HTTPS Google Meet links can be opened",
                "meet_bot_updated_at": datetime.utcnow(),
            }},
        )
        return
    interview_at = log.get("interview_at")
    if not isinstance(interview_at, datetime):
        await db.email_logs.update_one(
            {"email_id": email_id},
            {"$set": {
                "meet_bot_status": "failed_permanent",
                "meet_bot_error": "Interview start time is missing or invalid",
                "meet_bot_updated_at": datetime.utcnow(),
            }},
        )
        return
    end_at = log.get("interview_end_at")
    if not isinstance(end_at, datetime):
        end_at = interview_at + timedelta(minutes=settings.MEET_BOT_DEFAULT_DURATION_MINUTES)
    leave_at = end_at + timedelta(minutes=settings.MEET_BOT_LEAVE_MINUTES_AFTER)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            settings.MEET_BOT_PROFILE_PATH,
            headless=settings.MEET_BOT_HEADLESS,
            viewport={"width": 1280, "height": 800},
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(link, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            if "accounts.google.com" in page.url or await page.get_by_text("Sign in", exact=True).count():
                raise RuntimeError("Bot browser profile is not authenticated")
            await _click_if_visible(page, ["Turn off microphone", "Mute microphone"])
            await _click_if_visible(page, ["Turn off camera"])
            joined = await _click_if_visible(page, ["Join now", "Ask to join"])
            if not joined:
                raise RuntimeError("Meet join control was not available; authentication or UI may require attention")
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {"meet_bot_status": "joined", "meet_bot_joined_at": datetime.utcnow()}},
            )
            await _observe_attendance(page, log, db, email_id)
            logger.info("Bot joined interview %s", email_id)
            service_state["active_meeting"] = email_id

            last_attendance_check = datetime.utcnow()
            while datetime.utcnow() < leave_at and not shutdown_event.is_set():
                latest = await db.email_logs.find_one(
                    {"email_id": email_id},
                    {"interview_scheduled": 1, "status": 1},
                ) or {}
                if latest.get("interview_scheduled") is False or latest.get("status") == "cancelled":
                    logger.info("Interview %s was cancelled; leaving", email_id)
                    break
                if page.is_closed():
                    raise RuntimeError("Meet browser page closed unexpectedly")
                if settings.MEET_BOT_AUTO_ADMIT:
                    # Meet's browser UI does not reliably expose the requester's
                    # email address. Enable only for invite-restricted meetings.
                    await _click_if_visible(page, ["Admit all", "Admit"])
                if datetime.utcnow() - last_attendance_check >= timedelta(seconds=20):
                    await _observe_attendance(page, log, db, email_id)
                    last_attendance_check = datetime.utcnow()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
            await _click_if_visible(page, ["Leave call"])
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {"meet_bot_status": "completed", "meet_bot_left_at": datetime.utcnow()}},
            )
        except Exception as exc:
            logger.exception("Meeting bot failed for %s", email_id)
            attempts = int(log.get("meet_bot_attempts") or 1)
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {
                    "meet_bot_status": "failed_permanent" if attempts >= settings.MEET_BOT_MAX_ATTEMPTS else "retry_pending",
                    "meet_bot_error": str(exc),
                    "meet_bot_next_retry_at": datetime.utcnow() + timedelta(seconds=30),
                    "meet_bot_updated_at": datetime.utcnow(),
                }},
            )
        finally:
            service_state["active_meeting"] = ""
            await context.close()


async def _claim_due_meeting(db):
    now = datetime.utcnow()
    due_before = now + timedelta(minutes=settings.MEET_BOT_JOIN_MINUTES_BEFORE)
    return await db.email_logs.find_one_and_update(
        {
            "interview_scheduled": True,
            "interview_at": {"$gte": now - timedelta(minutes=2), "$lte": due_before},
            "$and": [
                {"$or": [
                    {"meet_bot_status": {"$exists": False}},
                    {"meet_bot_status": "pending"},
                    {"meet_bot_status": "retry_pending", "meet_bot_next_retry_at": {"$lte": now}},
                    {"meet_bot_status": "claimed", "meet_bot_claimed_at": {"$lte": now - timedelta(minutes=5)}},
                ]},
                {"$or": [
                    {"interview_link": {"$exists": True, "$nin": ["", None]}},
                    {"meet_link": {"$exists": True, "$nin": ["", None]}},
                ]},
            ],
        },
        {
            "$set": {"meet_bot_status": "claimed", "meet_bot_claimed_at": now},
            "$inc": {"meet_bot_attempts": 1},
        },
        return_document=True,
    )


async def run() -> None:
    health_server = await asyncio.start_server(_health_response, "0.0.0.0", settings.MEET_BOT_HEALTH_PORT)
    if not settings.MEET_BOT_ENABLED:
        logger.warning("Meeting bot is disabled. Set MEET_BOT_ENABLED=true after authentication and testing.")
        service_state["ready"] = True
        await shutdown_event.wait()
        health_server.close()
        await health_server.wait_closed()
        return
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    await db.command("ping")
    await db.email_logs.create_index([("interview_scheduled", 1), ("interview_at", 1), ("meet_bot_status", 1)])
    service_state["ready"] = True
    logger.info("Meeting bot enabled; polling for scheduled interviews")
    while not shutdown_event.is_set():
        service_state["last_poll"] = datetime.utcnow().isoformat()
        meeting = await _claim_due_meeting(db)
        if meeting:
            await _join_meeting(meeting, db)
        else:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=max(5, settings.MEET_BOT_POLL_SECONDS))
            except asyncio.TimeoutError:
                pass
    health_server.close()
    await health_server.wait_closed()
    client.close()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(shutdown_event.set))
    loop.run_until_complete(run())
