import asyncio
import json
import logging
import re
import signal
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright

from app.config import get_settings
from app.safety import valid_meet_link
from app.voice import MICROPHONE_SCRIPT, speak_into_meeting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("meet-bot")
settings = get_settings()
shutdown_event = asyncio.Event()
service_state = {"ready": False, "last_poll": None, "active_meetings": {}}


def _meeting_filter(log):
    """Trainer/client invitation copies for the same meeting occurrence."""
    link = _clean(log.get("interview_link") or log.get("meet_link"))
    if not link or not log.get("interview_at"):
        return {"email_id": log["email_id"]}
    return {"interview_at": log["interview_at"], "$or": [
        {"interview_link": link}, {"meet_link": link},
    ]}


class MeetingLogs:
    """Mirror lifecycle updates to both invitations without launching twice."""
    def __init__(self, collection, log):
        self.collection = collection
        self.log = log

    async def update_one(self, query, update):
        return await self.collection.update_many(_meeting_filter(self.log), update)

    async def find_one(self, *args, **kwargs):
        return await self.collection.find_one(*args, **kwargs)


@asynccontextmanager
async def _meeting_page(context=None):
    if context is not None:
        page = await context.new_page()
        try:
            yield page
        finally:
            await page.close()
        return
    # Standalone callers retain the original single-meeting behavior.
    async with async_playwright() as playwright:
        owned_context = await _launch_browser(playwright)
        try:
            page = await owned_context.new_page()
            yield page
        finally:
            await owned_context.close()


async def _launch_browser(playwright):
    context = await playwright.chromium.launch_persistent_context(
        settings.MEET_BOT_PROFILE_PATH,
        headless=settings.MEET_BOT_HEADLESS,
        viewport={"width": 1280, "height": 800},
        args=["--disable-dev-shm-usage", "--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
    )
    await context.grant_permissions(["microphone"], origin="https://meet.google.com")
    await context.add_init_script(MICROPHONE_SCRIPT)
    return context


def _clean(value) -> str:
    return str(value or "").strip()


async def _inspect_google_account(context):
    page = await context.new_page()
    try:
        await page.goto("https://meet.google.com/", wait_until="domcontentloaded", timeout=45000)
        account = page.locator('[aria-label*="Google Account"], [title*="Google Account"]').first
        try:
            await account.wait_for(state="visible", timeout=15000)
            label = (await account.get_attribute("aria-label") or await account.get_attribute("title") or "")
            match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", label)
            return {"status": "signed_in", "email": match.group(0) if match else "",
                    "checked_at": datetime.utcnow().isoformat()}
        except Exception:
            signed_out = "accounts.google.com" in page.url or await page.get_by_text("Sign in", exact=True).count()
            return {"status": "sign_in_required" if signed_out else "unverified",
                    "checked_at": datetime.utcnow().isoformat()}
    except Exception as exc:
        return {"status": "check_failed", "error": str(exc)[:200]}
    finally:
        await page.close()


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
        return trainer_joined, client_joined
    except Exception as exc:
        logger.debug("Could not observe participants for %s: %s", email_id, exc)
        return False, False


def _welcome_message(log: dict, now=None) -> str:
    current = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    greeting = "Good morning" if current.hour < 12 else "Good afternoon" if current.hour < 17 else "Good evening"
    client = _clean(log.get("client_name")) or "Client"
    trainer = _clean(log.get("trainer_name")) or "Trainer"
    host = _clean(getattr(settings, "MEET_BOT_DISPLAY_NAME", "Clahan Technologies")) or "Clahan Technologies"
    return (
        f"{greeting}. This is the automated meeting assistant from {host}. Hi {client}, and hi {trainer}. "
        "Welcome to the trainer interview coordinated by Clahan Technologies. "
        "Please check that your microphone and internet connection are working. "
        "Please confirm that you can hear each other before starting. "
        "Keep your microphone muted when you are not speaking, "
        "and stay in the meeting until the interview ends. "
        "If you lose connection, rejoin using the meeting link in your Clahan invitation email. "
        "If you cannot continue, please reply to that email so our coordinator can assist."
    )


async def _send_chat_welcome(page, message: str) -> bool:
    """Send the coordinator instruction in Meet chat as a reliable fallback.

    Chat makes the instruction visible even when the virtual microphone or
    local speech synthesizer is unavailable.
    """
    try:
        opened = await _click_if_visible(page, ["Chat with everyone", "Open chat"])
        if not opened:
            return False
        textbox = page.get_by_role("textbox", name="Chat", exact=False).last
        if not await textbox.is_visible(timeout=1500):
            textbox = page.locator("textarea").last
        if not await textbox.is_visible(timeout=1500):
            return False
        await textbox.fill(message)
        await textbox.press("Enter")
        return True
    except Exception as exc:
        logger.debug("Could not send Meet chat welcome: %s", exc)
        return False


async def _speak_welcome(page, log: dict, db, email_id: str) -> bool:
    """Deliver one coordinator instruction after both participants join.

    The instruction is always posted to Meet chat. Voice is attempted as an
    additional channel when the bot microphone can be enabled.
    """
    if not settings.MEET_BOT_WELCOME_ENABLED:
        return False
    message = _welcome_message(log)
    chat_sent = bool(log.get("meet_bot_welcome_chat_sent"))
    if not chat_sent:
        chat_sent = await _send_chat_welcome(page, message)
        log["meet_bot_welcome_chat_sent"] = chat_sent
    try:
        online = await page.evaluate("() => navigator.onLine")
        if not online:
            await db.email_logs.update_one({"email_id": email_id}, {"$set": {
                "meet_bot_welcome_text": message,
                "meet_bot_welcome_chat_sent": chat_sent,
                "meet_bot_welcome_status": "chat_sent_offline_voice" if chat_sent else "offline",
            }})
            return False
        unmuted = await _click_if_visible(page, ["Turn on microphone", "Unmute microphone"])
        if not unmuted:
            await db.email_logs.update_one({"email_id": email_id}, {"$set": {
                "meet_bot_welcome_text": message,
                "meet_bot_welcome_chat_sent": chat_sent,
                "meet_bot_welcome_status": "chat_sent_microphone_unavailable" if chat_sent else "skipped_microphone_unavailable",
            }})
            return False
        spoken = await speak_into_meeting(page, message)
        await _click_if_visible(page, ["Turn off microphone", "Mute microphone"])
        await db.email_logs.update_one({"email_id": email_id}, {"$set": {
            "meet_bot_welcome_sent": bool(spoken),
            "meet_bot_voice_transport": "webrtc_microphone",
            "meet_bot_welcome_text": message,
            "meet_bot_welcome_chat_sent": chat_sent,
            "meet_bot_welcome_sent_at": datetime.utcnow() if spoken else None,
            "meet_bot_welcome_status": "spoken_and_chat" if spoken and chat_sent else "spoken" if spoken else "chat_sent_speech_unavailable" if chat_sent else "speech_unavailable",
        }})
        return bool(spoken)
    except Exception as exc:
        logger.warning("Welcome instruction failed for %s: %s", email_id, exc)
        await db.email_logs.update_one({"email_id": email_id}, {"$set": {
            "meet_bot_welcome_status": "chat_sent_voice_failed" if chat_sent else "voice_failed",
            "meet_bot_welcome_error": str(exc)[:500],
        }})
        await _click_if_visible(page, ["Turn off microphone", "Mute microphone"])
        return False


async def _health_response(reader, writer) -> None:
    try:
        await reader.read(2048)
        healthy = service_state["ready"] or not settings.MEET_BOT_ENABLED
        status = "200 OK" if healthy else "503 Service Unavailable"
        body = json.dumps({
            "status": "ok" if healthy else "starting",
            "enabled": settings.MEET_BOT_ENABLED,
            "max_concurrent_meetings": settings.MEET_BOT_MAX_CONCURRENT_MEETINGS,
            "active_meetings": service_state["active_meetings"],
            "last_poll": service_state["last_poll"],
            "google_account": service_state.get("google_account", {"status": "not_checked"}),
            "voice_transport": "webrtc_microphone",
        }).encode()
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
                await button.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


async def _join_when_ready(page, timeout_seconds=90) -> bool:
    """Wait for prejoin loading; never transfer another device's active call."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        await _click_if_visible(page, ["Got it"])
        await _click_if_visible(page, ["Turn off microphone", "Mute microphone"])
        await _click_if_visible(page, ["Turn off camera"])
        if await _click_if_visible(page, ["Join now", "Ask to join", "Join here too"]):
            return True
        if await _click_if_visible(page, ["Other ways to join", "Other joining options"]):
            option = page.get_by_text("Join here too", exact=True).first
            if await option.is_visible():
                await option.click()
                return True
        await page.wait_for_timeout(2000)
    return False


async def _join_meeting(log: dict, db, context=None) -> None:
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

    # The dispatcher owns the browser; this task owns only its meeting tab.
    async with _meeting_lifecycle(log, db), AsyncExitStack() as pages:
        try:
            page = await pages.enter_async_context(_meeting_page(context))
            await page.goto(link, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            if "accounts.google.com" in page.url or await page.get_by_text("Sign in", exact=True).count():
                raise RuntimeError("Bot browser profile is not authenticated")
            await _click_if_visible(page, ["Turn off microphone", "Mute microphone"])
            await _click_if_visible(page, ["Turn off camera"])
            joined = await _join_when_ready(page)
            if not joined:
                raise RuntimeError("Meet join control was not available; authentication or UI may require attention")
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {"meet_bot_status": "joining", "meet_bot_updated_at": datetime.utcnow()}},
            )
            # A click on Ask to join only requests admission. The leave control
            # appears after admission and is also used to detect disconnection.
            await page.get_by_role("button", name="Leave call", exact=False).first.wait_for(
                state="visible", timeout=180000,
            )
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {"meet_bot_status": "joined", "meet_bot_joined_at": datetime.utcnow(),
                          "meet_bot_updated_at": datetime.utcnow()},
                 "$unset": {"meet_bot_error": "", "meet_bot_next_retry_at": ""}},
            )
            attendance = await _observe_attendance(page, log, db, email_id)
            if attendance == (True, True) and not log.get("meet_bot_welcome_sent"):
                log["meet_bot_welcome_sent"] = await _speak_welcome(page, log, db, email_id)
            logger.info("Bot joined interview %s", email_id)
            service_state["active_meetings"][email_id] = "joined"

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
                await page.get_by_role("button", name="Leave call", exact=False).first.wait_for(
                    state="visible", timeout=10000,
                )
                if settings.MEET_BOT_AUTO_ADMIT:
                    # Meet's browser UI does not reliably expose the requester's
                    # email address. Enable only for invite-restricted meetings.
                    await _click_if_visible(page, ["Admit all", "Admit"])
                if datetime.utcnow() - last_attendance_check >= timedelta(seconds=20):
                    await db.email_logs.update_one({"email_id": email_id}, {"$set": {
                        "meet_bot_updated_at": datetime.utcnow(),
                    }})
                    attendance = await _observe_attendance(page, log, db, email_id)
                    if attendance == (True, True) and not log.get("meet_bot_welcome_sent"):
                        log["meet_bot_welcome_sent"] = await _speak_welcome(page, log, db, email_id)
                    last_attendance_check = datetime.utcnow()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
            await _click_if_visible(page, ["Leave call"])
            await db.email_logs.update_one(
                {"email_id": email_id},
                {"$set": {"meet_bot_status": "completed", "meet_bot_left_at": datetime.utcnow(),
                          "meet_bot_updated_at": datetime.utcnow()}},
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


@asynccontextmanager
async def _meeting_lifecycle(log, db):
    email_id = log["email_id"]
    service_state["active_meetings"][email_id] = "joining"
    try:
        yield
    except asyncio.CancelledError:
        await db.email_logs.update_one({"email_id": email_id}, {"$set": {
            "meet_bot_status": "retry_pending",
            "meet_bot_error": "Bot service stopped; meeting session interrupted",
            "meet_bot_next_retry_at": datetime.utcnow(),
            "meet_bot_updated_at": datetime.utcnow(),
        }})
        raise
    finally:
        service_state["active_meetings"].pop(email_id, None)


async def _claim_due_meeting(db, active_links=()):
    now = datetime.utcnow()
    due_before = now + timedelta(minutes=settings.MEET_BOT_JOIN_MINUTES_BEFORE)
    return await db.email_logs.find_one_and_update(
        {
            "interview_scheduled": True,
            "status": {"$ne": "cancelled"},
            "$nor": [{"interview_link": {"$in": list(active_links)}},
                     {"meet_link": {"$in": list(active_links)}}],
            "interview_at": {"$lte": due_before},
            "$and": [
                {"$or": [
                    {"interview_end_at": {"$gt": now}},
                    {"interview_end_at": None, "interview_at": {
                        "$gt": now - timedelta(minutes=settings.MEET_BOT_DEFAULT_DURATION_MINUTES),
                    }},
                ]},
                {"$or": [
                    {"meet_bot_status": {"$exists": False}},
                    {"meet_bot_status": "pending"},
                    {"meet_bot_status": "retry_pending", "meet_bot_next_retry_at": {"$lte": now}},
                    {"meet_bot_status": "claimed", "meet_bot_claimed_at": {"$lte": now - timedelta(minutes=5)}},
                    {"meet_bot_status": "joining", "meet_bot_updated_at": {"$lte": now - timedelta(minutes=5)}},
                    {"meet_bot_status": "joined", "meet_bot_updated_at": {"$lte": now - timedelta(minutes=5)}},
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
        sort=[("interview_at", 1)],
    )


async def _dispatch_meetings(db, context, browser_closed=None):
    from types import SimpleNamespace

    tasks = {}
    try:
        while not shutdown_event.is_set():
            if browser_closed is not None and browser_closed.is_set():
                raise RuntimeError("Shared bot browser closed; restarting service")
            for link, task in list(tasks.items()):
                if task.done():
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        logger.warning("Meeting task cancelled")
                    except Exception:
                        logger.exception("Meeting task failed")
                    del tasks[link]
            service_state["last_poll"] = datetime.utcnow().isoformat()
            while len(tasks) < settings.MEET_BOT_MAX_CONCURRENT_MEETINGS and not shutdown_event.is_set():
                meeting = await _claim_due_meeting(db, tuple(tasks))
                if not meeting:
                    break
                link = _clean(meeting.get("interview_link") or meeting.get("meet_link"))
                logs = MeetingLogs(db.email_logs, meeting)
                await logs.update_one({}, {"$set": {
                    "meet_bot_status": "claimed", "meet_bot_claimed_at": datetime.utcnow(),
                    "meet_bot_attempts": meeting.get("meet_bot_attempts", 1),
                }})
                tasks[link] = asyncio.create_task(_join_meeting(
                    meeting, SimpleNamespace(email_logs=logs), context,
                ))
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=max(1, settings.MEET_BOT_POLL_SECONDS))
            except asyncio.TimeoutError:
                pass
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


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
    try:
        async with async_playwright() as playwright:
            context = await _launch_browser(playwright)
            try:
                service_state["google_account"] = await _inspect_google_account(context)
                browser_closed = asyncio.Event()
                context.on("close", lambda *_: browser_closed.set())
                service_state["ready"] = True
                logger.info("Meeting bot enabled; capacity=%s concurrent meetings", settings.MEET_BOT_MAX_CONCURRENT_MEETINGS)
                await _dispatch_meetings(db, context, browser_closed)
            finally:
                await context.close()
    finally:
        service_state["ready"] = False
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
