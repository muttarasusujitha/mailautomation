import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from app.routes import toc, toc_extended


class TocSafetyTests(unittest.TestCase):
    def test_scope_hours_and_fixed_schedule(self):
        document = {"quality": {"status": "approved"}, "days": [{
            "focus_area": "Git", "subtopics": ["Git branches"] * 8,
            "morning_session": {"time": "9:00 AM - 1:00 PM", "topics": [{"time": "9:00", "topic": "Git"}]},
        }]}
        toc._apply_requirement_quality(document, toc.TocRequest(
            domain="DevOps", custom_topics="Git; Kubernetes", hours_per_day=1,
        ))
        self.assertEqual(document["quality"]["missing_requested_topics"], ["Kubernetes"])
        self.assertEqual(document["quality"]["status"], "requires_review")
        self.assertIn("exceeds", " ".join(document["quality"]["review_warnings"]))
        self.assertEqual(document["days"][0]["morning_session"]["time"], "To be confirmed")
        self.assertNotIn("time", document["days"][0]["morning_session"]["topics"][0])

    def test_sufficient_hours_and_covered_scope_keep_structural_approval(self):
        document = {"quality": {"status": "approved"}, "days": [{"focus_area": "Git", "subtopics": ["Git branches"]}]}
        toc._apply_requirement_quality(document, toc.TocRequest(domain="Git", custom_topics="Git", hours_per_day=3))
        self.assertEqual(document["quality"]["status"], "approved")
        self.assertEqual(document["quality"]["review_warnings"], [])

    def test_auto_generation_inherits_advanced_but_not_lab_hours(self):
        db = MagicMock()
        db.__getitem__.return_value.find_one = AsyncMock(side_effect=[{
            "technology_needed": "DevOps", "duration_days": 20,
            "audience_level": "advanced", "lab_hours_per_day": 3,
            "requested_topics": ["Git", "Docker"],
        }, {"value": "template"}])
        generate = AsyncMock(return_value={"success": True})
        with patch.object(toc, "generate_toc", generate):
            asyncio.run(toc_extended.auto_generate_toc(toc_extended.AutoGenerateRequest(requirement_id="REQ-1"), db))
        payload = generate.call_args.args[0]
        self.assertEqual(payload.level, "advanced")
        self.assertIsNone(payload.hours_per_day)
        self.assertIn("Git; Docker", payload.custom_topics)

    def test_failed_attachment_never_calls_email_service(self):
        client = AsyncMock()
        client.post.return_value = MagicMock(status_code=500, content=b"")
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(toc_extended.httpx, "AsyncClient", factory):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(toc_extended.send_toc_email(toc_extended.TocEmailRequest(
                    toc={"title": "DevOps"}, to_email="client@example.com",
                ), MagicMock()))
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(client.post.call_count, 1)
        self.assertIn("/documents/excel/toc", client.post.call_args.args[0])
