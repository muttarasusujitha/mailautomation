import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app import main


class JoinLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def exercise_join(self, launch_error=None, admission_error=None):
        db = MagicMock()
        db.email_logs.update_one = AsyncMock()
        page = MagicMock()
        page.url = "https://meet.google.com/abc-defg-hij"
        page.goto = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.get_by_text.return_value.count = AsyncMock(return_value=0)
        page.get_by_role.return_value.first.wait_for = AsyncMock(side_effect=admission_error)
        context = MagicMock()
        context.pages = [page]
        context.new_page = AsyncMock(return_value=page)
        context.close = AsyncMock()
        context.grant_permissions = AsyncMock()
        context.add_init_script = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch_persistent_context = AsyncMock(
            return_value=context, side_effect=launch_error,
        )
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=playwright)
        manager.__aexit__ = AsyncMock(return_value=False)
        log = {"email_id": "test", "interview_link": page.url,
               "interview_at": datetime.utcnow(), "meet_bot_attempts": 1}
        with patch.object(main, "async_playwright", return_value=manager), \
             patch.object(main, "_click_if_visible", new=AsyncMock(return_value=True)), \
             patch.object(main, "_observe_attendance", new=AsyncMock()), \
             patch.object(main, "shutdown_event") as shutdown:
            shutdown.is_set.return_value = True
            await main._join_meeting(log, db)
        return [call.args[1]["$set"]["meet_bot_status"]
                for call in db.email_logs.update_one.call_args_list]

    async def test_browser_launch_failure_is_retryable(self):
        self.assertEqual(await self.exercise_join(launch_error=RuntimeError("profile locked")),
                         ["retry_pending"])

    async def test_waiting_for_admission_does_not_report_joined(self):
        self.assertEqual(await self.exercise_join(admission_error=TimeoutError("not admitted")),
                         ["joining", "retry_pending"])

    async def test_confirmed_admission_reports_joined(self):
        self.assertEqual(await self.exercise_join(), ["joining", "joined", "completed"])


if __name__ == "__main__":
    unittest.main()
