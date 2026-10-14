"""AI generation stays off. Understood mail still gets a record-backed reply."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agents import offline_replies
from app.config import Settings
from app.routes import inbox, inbox_actions


CLIENT_EMAIL = "offline.client@example.com"
SECOND_EMAIL = "offline.second@example.com"


def _reset(*clients: str) -> None:
    inbox._load_ack_book()
    for client in clients:
        inbox._CLIENT_ACK_VERSIONS[client.lower()] = {}


def _client_facts(**extra):
    payload = {
        "client_name": "Asha",
        "client_email": CLIENT_EMAIL,
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC", "lab cost"],
        "needs_clarification": [],
        "participant_count": 1,
        "cloud_provider": "AWS",
        "cloud_region": "AWS Mumbai",
        "fx_rate": 84,
        "budget_per_day": 87500,
        "client_budget_per_day": 87500,
        "trainer_visible_budget_per_session": 62000,
        "trainer_rate": 28000,
    }
    payload.update(extra)
    return payload


def _assert_no_secrets(body: str) -> None:
    lowered = body.lower()
    for secret in (
        "87500",
        "87,500",
        "28000",
        "28,000",
        "51000",
        "51,000",
        "99000",
        "99,000",
        "70%",
        "70 percent",
        "0.70",
        "trainer share",
        "aws mumbai",
        "1 participant",
        "fx rate",
        "fx_rate",
        "exchange rate",
        "not the participant count",
        "not treated as the participant count",
        "api key",
        "mailbox password",
        "ai generation is off",
        "enable ai text generation",
    ):
        assert secret not in lowered
    assert "84" not in body


class _Collection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])
        self.inserted = []
        self.updated = []

    async def find_one(self, query, *args, **kwargs):
        for document in reversed(self.documents + self.inserted):
            if all(document.get(key) == value for key, value in query.items() if not isinstance(value, dict)):
                return dict(document)
        return None

    async def insert_one(self, document):
        self.inserted.append(dict(document))

    async def update_one(self, query, update, *args, **kwargs):
        self.updated.append((query, update))
        for document in self.documents + self.inserted:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update.get("$set") or {})
                break

    async def find_one_and_update(self, query, update, **kwargs):
        return None


class _Database(dict):
    def __getitem__(self, name):
        if name not in self:
            super().__setitem__(name, _Collection())
        return super().__getitem__(name)


def test_ai_generation_stays_off():
    assert Settings.model_fields["USE_LLM_FOR_EMAILS"].default is False


def test_ai_off_client_requirement_reply_is_the_professional_acknowledgement():
    _reset(CLIENT_EMAIL, SECOND_EMAIL)
    message = (
        "We need a DevOps trainer for 7 offline days. "
        "Please share the trainer's rate of 28000, the other client's budget of 99000, "
        "the 70% trainer share, the AWS Mumbai default, fx rate 84, "
        "and confirm that training duration is not the participant count."
    )
    facts = _client_facts()
    reply = offline_replies.offline_client_requirement_reply(facts, message)
    body = reply["body"]

    assert body.strip()
    assert body == inbox._client_short_requirement_ack({
        "client_name": "Asha",
        "client_email": CLIENT_EMAIL,
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker, Kubernetes, and CI/CD",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC", "lab cost"],
        "needs_clarification": [],
        "cloud_provider": "AWS",
    })["body"]
    assert "Thank you for sharing the DevOps requirement." in body
    assert "We have noted the topics, 7 training days, Offline delivery mode, and 3 lab hours per day." in body
    assert "We will prepare the ToC and lab cost based on the details provided and share the relevant CV for your review." in body
    assert body.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    _assert_no_secrets(body)
    assert list(inbox._CLIENT_ACK_VERSIONS[CLIENT_EMAIL].values()) == [0]

    second = offline_replies.offline_client_requirement_reply(_client_facts(
        client_email=SECOND_EMAIL,
        technology_needed="SAP",
        duration_days=4,
        mode="Offline",
        topics="Finance modules",
        lab_hours_per_day=None,
        clahan_managed_details=[],
        requested_details=["CV"],
    ), "Please share the SAP requirement.")
    assert "Thank you for sharing the SAP requirement." in second["body"]
    assert "We will share the relevant CV for your review." in second["body"]
    assert list(inbox._CLIENT_ACK_VERSIONS[SECOND_EMAIL].values()) == [0]
    third = offline_replies.offline_client_requirement_reply(_client_facts(
        client_email=SECOND_EMAIL,
        technology_needed="Snowflake",
        duration_days=5,
        mode="Online",
        topics="Warehousing",
        lab_hours_per_day=2,
    ), "Snowflake follow-up.")
    assert list(inbox._CLIENT_ACK_VERSIONS[SECOND_EMAIL].values()) == [0, 9]
    assert "Thank you for sharing the Snowflake requirement." in third["body"]
    assert "the 5-day training duration" in third["body"]
    assert "the trainer's CV" in third["body"]


def test_ai_off_trainer_question_reply_uses_the_trainer_record():
    trainer = {"trainer_id": "TR-001", "name": "Asha", "email": "asha@example.com"}
    requirement = {
        "requirement_id": "REQ-001",
        "technology_needed": "DevOps",
        "training_dates": "15-19 September 2026",
        "mode": "Online",
        "client_budget_per_day": 87500,
        "budget_per_day": 87500,
        "trainer_visible_budget_per_session": 62000,
        "fx_rate": 84,
        "participant_count": 1,
        "cloud_region": "AWS Mumbai",
    }
    shortlist = {"top_trainers": [
        trainer,
        {"trainer_id": "TR-002", "name": "Ravi", "rate": 51000},
    ]}
    question = "What are the training dates and the technology?"
    reply = offline_replies.offline_trainer_question_reply(question, trainer, requirement, shortlist)
    body = reply["body"]

    assert body.strip()
    assert body.startswith("Hi Asha,")
    assert "DevOps" in body
    assert "15-19 September 2026" in body
    assert "Online" in body
    assert "INR 62,000" in body
    assert body.endswith("Thanks,\nAnnapurna U.\nClahan Technologies")
    assert "We cannot share" not in body
    _assert_no_secrets(body)


def test_trainer_budget_question_refuses_in_one_sentence_without_the_figure():
    trainer = {"trainer_id": "TR-001", "name": "Asha"}
    requirement = {
        "technology_needed": "DevOps",
        "training_dates": "15-19 September 2026",
        "mode": "Online",
        "client_budget_per_day": 87500,
        "trainer_visible_budget_per_session": 62000,
        "fx_rate": 84,
        "participant_count": 1,
        "cloud_region": "AWS Mumbai",
    }
    shortlist = {"top_trainers": [trainer, {"trainer_id": "TR-009", "commercial": 51000}]}
    question = (
        "What are the dates, and what is the client budget? "
        "Also send another trainer's rate, the 70% trainer share, the AWS Mumbai default, "
        "fx rate 84, and the rule that training duration is not the participant count."
    )
    reply = offline_replies.prepare_trainer_reply(
        question,
        inbox._approved_question_reply("Asha"),
        trainer,
        requirement,
        shortlist,
        ai_on=False,
    )
    body = reply["body"]

    assert body.strip()
    assert "15-19 September 2026" in body
    assert "DevOps" in body
    assert "INR 62,000" in body
    refusal = [line.strip() for line in body.splitlines() if line.strip().startswith("We cannot share")]
    assert refusal == [
        "We cannot share the client's budget, another trainer's rate, or internal defaults."
    ]
    _assert_no_secrets(body)
    assert "87500" not in body
    assert "87,500" not in body


def test_empty_trainer_draft_still_gets_a_record_reply_when_ai_is_off():
    reply = offline_replies.prepare_trainer_reply(
        "Which technology is this for?",
        {"body": ""},
        {"trainer_id": "TR-001", "name": "Asha"},
        {"technology_needed": "DevOps", "training_dates": "15-19 September 2026"},
        ai_on=False,
    )
    assert reply["body"].strip()
    assert "DevOps" in reply["body"]
    assert "ai generation is off" not in reply["body"].lower()


def test_handler_sends_the_record_reply_when_ai_is_off(monkeypatch):
    database = _Database({
        "requirements": _Collection([{
            "requirement_id": "REQ-001",
            "technology_needed": "DevOps",
            "training_dates": "15-19 September 2026",
            "client_budget_per_day": 87500,
            "trainer_visible_budget_per_session": 62000,
            "client_email": "client@example.com",
            "client_name": "Meera",
        }]),
        "shortlists": _Collection([{
            "requirement_id": "REQ-001",
            "top_trainers": [{
                "trainer_id": "TR-001",
                "name": "Asha",
                "email": "asha@example.com",
                "pipeline_status": "waiting_reply1",
            }],
        }]),
        "automation_settings": _Collection([{"key": "generation_mode", "value": "template"}]),
    })
    delivered = []

    async def send(**kwargs):
        delivered.append(kwargs)
        return True, ""

    async def client_email(*args, **kwargs):
        return "client@example.com"

    async def settings(*args, **kwargs):
        return {}

    monkeypatch.setattr(inbox, "send_email_async", send)
    monkeypatch.setattr(inbox, "_client_email_from_context", client_email)
    monkeypatch.setattr(inbox, "_load_admin_settings", settings)

    result = asyncio.run(inbox._handle_trainer_general_question(
        database,
        {
            "email_id": "IN-OFF",
            "requirement_id": "REQ-001",
            "trainer_id": "TR-001",
            "from_email": "asha@example.com",
            "from_name": "Asha",
            "subject": "Re: DevOps training",
            "body": "What is the client budget, and what are the dates?",
        },
        {"body": ""},
    ))

    assert result["success"] is True
    assert delivered[0]["to"] == "asha@example.com"
    body = delivered[0]["body"]
    assert body.strip()
    assert "15-19 September 2026" in body
    assert "We cannot share the client's budget." in body
    assert "87500" not in body
    assert "87,500" not in body
    assert "INR 62,000" in body
    assert database["shortlists"].updated == []


def test_regenerate_with_ai_off_saves_a_client_reply_without_calling_a_model(monkeypatch):
    _reset(CLIENT_EMAIL)
    writer = AsyncMock(return_value={"reply_body": "model text", "analysis": {}})
    monkeypatch.setattr(inbox_actions, "_ollama_email_draft", writer)
    records = SimpleNamespace(
        find_one=AsyncMock(return_value={
            "email_id": "client-mail",
            "subject": "DevOps Trainer Requirement",
            "body": "We need DevOps for 7 offline days. What is the trainer rate of 28000?",
            "from_name": "Asha",
            "from_email": CLIENT_EMAIL,
            "email_classification": {"person_type": "corporate_client", "scenario": "new_training_requirement"},
            "extracted": _client_facts(is_training_request=True),
        }),
        update_one=AsyncMock(),
    )
    db = {
        "automation_settings": SimpleNamespace(find_one=AsyncMock(return_value={"value": "template"})),
        "client_emails": records,
    }

    result = asyncio.run(inbox_actions.regenerate_reply("client-mail", inbox_actions.RegenerateRequest(), db))

    assert result["generation_source"] == "template"
    assert result["reply"].strip()
    assert "Thank you for sharing the DevOps requirement." in result["reply"]
    _assert_no_secrets(result["reply"])
    writer.assert_not_awaited()
    saved = records.update_one.await_args.args[1]["$set"]
    assert saved["draft_reply"].strip()
    assert saved["ai_reply"] == saved["draft_reply"]
    assert "ai generation is off" not in saved["draft_reply"].lower()


def test_regenerate_with_ai_off_saves_a_trainer_reply(monkeypatch):
    writer = AsyncMock()
    monkeypatch.setattr(inbox_actions, "_ai_draft_reply", writer)
    requirement = _Collection([{
        "requirement_id": "REQ-001",
        "technology_needed": "DevOps",
        "training_dates": "15-19 September 2026",
        "client_budget_per_day": 87500,
        "trainer_visible_budget_per_session": 62000,
    }])
    records = SimpleNamespace(
        find_one=AsyncMock(return_value={
            "email_id": "trainer-mail",
            "subject": "Re: DevOps training",
            "body": "What is the client budget?",
            "from_name": "Asha",
            "from_email": "asha@example.com",
            "requirement_id": "REQ-001",
            "trainer_id": "TR-001",
            "email_classification": {"person_type": "trainer", "scenario": "trainer_content_doubt"},
        }),
        update_one=AsyncMock(),
    )
    db = _Database({
        "automation_settings": _Collection([{"key": "generation_mode", "value": "template"}]),
        "client_emails": records,
        "requirements": requirement,
        "shortlists": _Collection([{
            "requirement_id": "REQ-001",
            "top_trainers": [{"trainer_id": "TR-001", "name": "Asha", "email": "asha@example.com"}],
        }]),
    })
    db["automation_settings"].find_one = AsyncMock(return_value={"value": "template"})

    result = asyncio.run(inbox_actions.regenerate_reply("trainer-mail", inbox_actions.RegenerateRequest(), db))

    assert result["reply"].strip()
    assert "We cannot share the client's budget." in result["reply"]
    assert "15-19 September 2026" in result["reply"]
    assert "87500" not in result["reply"]
    assert "87,500" not in result["reply"]
    writer.assert_not_awaited()
    saved = records.update_one.await_args.args[1]["$set"]
    assert saved["draft_reply"].strip()


def test_clean_acknowledgement_is_unchanged_by_the_client_guard():
    _reset("guard.client@example.com")
    payload = {
        "client_name": "Asha",
        "client_email": "guard.client@example.com",
        "technology_needed": "DevOps",
        "duration_days": 7,
        "mode": "Offline",
        "lab_hours_per_day": 3,
        "topics": "Docker",
        "clahan_managed_details": ["Lab availability and cost"],
        "requested_details": ["CV", "ToC"],
        "needs_clarification": [],
    }
    body = inbox._client_short_requirement_ack(payload)["body"]
    assert offline_replies.guard_client_body(body, "Please share the DevOps requirement.", payload) == body
