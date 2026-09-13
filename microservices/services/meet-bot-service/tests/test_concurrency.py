import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import main


class ConcurrentMeetingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_meetings_run_together_with_capacity_and_cleanup(self):
        stop = asyncio.Event()
        both_started = asyncio.Event()
        started = []
        cleaned = []
        pending = [{"email_id": str(i), "interview_at": datetime.utcnow(),
                    "interview_link": f"https://meet.google.com/room-{i}"} for i in range(3)]
        db = SimpleNamespace(email_logs=SimpleNamespace(update_many=AsyncMock()))

        async def claim(db, active_links):
            self.assertLess(len(active_links), 2)
            return pending.pop(0) if pending else None

        async def join(log, scoped_db, context):
            started.append(log["email_id"])
            if len(started) == 2:
                both_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.append(log["email_id"])

        with patch.object(main, "shutdown_event", stop), \
             patch.object(main.settings, "MEET_BOT_MAX_CONCURRENT_MEETINGS", 2), \
             patch.object(main, "_claim_due_meeting", side_effect=claim), \
             patch.object(main, "_join_meeting", side_effect=join):
            dispatcher = asyncio.create_task(main._dispatch_meetings(db, object()))
            try:
                await asyncio.wait_for(both_started.wait(), 2)
                self.assertEqual(started, ["0", "1"])
                self.assertEqual(len(pending), 1)
            finally:
                stop.set()
                await asyncio.wait_for(dispatcher, 2)
            self.assertCountEqual(cleaned, ["0", "1"])

    async def test_each_session_closes_only_its_own_page(self):
        page_a = SimpleNamespace(close=AsyncMock())
        page_b = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(side_effect=[page_a, page_b]), close=AsyncMock())
        async with main._meeting_page(context) as first:
            async with main._meeting_page(context) as second:
                self.assertIs(first, page_a)
                self.assertIs(second, page_b)
            page_b.close.assert_awaited_once()
            page_a.close.assert_not_awaited()
        page_a.close.assert_awaited_once()
        context.close.assert_not_awaited()

    async def test_duplicate_invitation_status_is_mirrored_to_same_occurrence(self):
        log = {"email_id": "trainer-copy", "interview_at": datetime(2026, 9, 10, 10, 30),
               "interview_link": "https://meet.google.com/abc-defg-hij"}
        collection = SimpleNamespace(update_many=AsyncMock())
        await main.MeetingLogs(collection, log).update_one({}, {"$set": {"meet_bot_status": "joined"}})
        query = collection.update_many.await_args.args[0]
        self.assertEqual(query["interview_at"], log["interview_at"])
        self.assertEqual(query["$or"], [{"interview_link": log["interview_link"]}, {"meet_link": log["interview_link"]}])

    async def test_claim_excludes_rooms_already_running(self):
        collection = SimpleNamespace(find_one_and_update=AsyncMock(return_value=None))
        await main._claim_due_meeting(SimpleNamespace(email_logs=collection), ("https://meet.google.com/abc-defg-hij",))
        query = collection.find_one_and_update.await_args.args[0]
        self.assertEqual(query["$nor"], [
            {"interview_link": {"$in": ["https://meet.google.com/abc-defg-hij"]}},
            {"meet_link": {"$in": ["https://meet.google.com/abc-defg-hij"]}},
        ])

    async def test_failed_session_does_not_block_next_meeting(self):
        stop = asyncio.Event()
        pending = [{"email_id": str(i), "interview_at": datetime.utcnow(),
                    "interview_link": f"https://meet.google.com/room-{i}"} for i in range(3)]
        third_started = asyncio.Event()
        async def claim(db, active_links):
            return pending.pop(0) if pending else None
        async def join(log, db, context):
            if log["email_id"] == "0":
                raise RuntimeError("session failed")
            if log["email_id"] == "2":
                third_started.set()
            await asyncio.Event().wait()
        db = SimpleNamespace(email_logs=SimpleNamespace(update_many=AsyncMock()))
        with patch.object(main, "shutdown_event", stop), \
             patch.object(main.settings, "MEET_BOT_MAX_CONCURRENT_MEETINGS", 2), \
             patch.object(main.settings, "MEET_BOT_POLL_SECONDS", 1), \
             patch.object(main, "_claim_due_meeting", side_effect=claim), \
             patch.object(main, "_join_meeting", side_effect=join):
            dispatcher = asyncio.create_task(main._dispatch_meetings(db, object()))
            try:
                await asyncio.wait_for(third_started.wait(), 3)
            finally:
                stop.set()
                await asyncio.wait_for(dispatcher, 2)
