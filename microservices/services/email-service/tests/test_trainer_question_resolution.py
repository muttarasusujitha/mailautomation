import asyncio
from datetime import datetime

from pymongo.errors import DuplicateKeyError

from app.routes import inbox


class _Collection:
    def __init__(self, documents=None):
        if isinstance(documents, list):
            self.documents = documents
        elif documents:
            self.documents = [documents]
        else:
            self.documents = []
        self.inserted = []
        self.updated = []

    async def find_one(self, query, *args, **kwargs):
        for document in reversed(self.documents + self.inserted):
            if all(
                (key not in document and isinstance(value, dict))
                or document.get(key) == value
                for key, value in query.items()
                if not isinstance(value, dict)
            ):
                return dict(document)
        return None

    async def insert_one(self, document):
        source_id = document.get("source_message_id")
        if source_id and any(
            item.get("source_message_id") == source_id
            for item in self.documents + self.inserted
        ):
            raise DuplicateKeyError("duplicate source_message_id")
        self.inserted.append(dict(document))

    async def update_one(self, query, update):
        self.updated.append((query, update))
        for document in self.documents + self.inserted:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update.get("$set") or {})
                break

    async def find_one_and_update(self, query, update, **kwargs):
        for document in self.documents + self.inserted:
            if document.get("source_message_id") != query.get("source_message_id"):
                continue
            statuses = ((query.get("$or") or [{}])[0].get("status") or {}).get("$in") or []
            expired = document.get("status") == "processing" and document.get("claim_expires_at") <= inbox._now()
            if document.get("status") in statuses or expired:
                document.update(update.get("$set") or {})
                return dict(document)
        return None


class _Database:
    def __init__(self, pending_query=None):
        self.collections = {
            "requirements": _Collection({
                "requirement_id": "REQ-001",
                "technology_needed": "DevOps",
                "client_name": "Client Team",
                "client_email": "client@example.com",
            }),
            "shortlists": _Collection({
                "requirement_id": "REQ-001",
                "top_trainers": [{
                    "trainer_id": "TR-001",
                    "name": "Asha",
                    "email": "asha@example.com",
                    "pipeline_status": "waiting_reply1",
                }],
            }),
            "trainer_question_queries": _Collection(pending_query),
        }

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = _Collection()
        return self.collections[name]


def _patch_delivery(monkeypatch, delivered):
    async def client_email(*args, **kwargs):
        return "client@example.com"

    async def settings(*args, **kwargs):
        return {}

    async def body(*args, **kwargs):
        return kwargs["reference_body"], "template"

    async def send(**kwargs):
        delivered.append(kwargs)
        return True, ""

    monkeypatch.setattr(inbox, "_client_email_from_context", client_email)
    monkeypatch.setattr(inbox, "_load_admin_settings", settings)
    monkeypatch.setattr(inbox, "_client_pipeline_email_body", body)
    monkeypatch.setattr(inbox, "send_email_async", send)


def test_verified_requirement_or_thread_answer_goes_to_trainer_without_stage_change(monkeypatch):
    database = _Database()
    delivered = []
    _patch_delivery(monkeypatch, delivered)
    before = dict(database["shortlists"].documents[0])

    result = asyncio.run(inbox._handle_trainer_general_question(
        database,
        {
            "email_id": "IN-001",
            "requirement_id": "REQ-001",
            "trainer_id": "TR-001",
            "from_email": "asha@example.com",
            "subject": "Re: DevOps training",
            "body": "Is the training online?",
        },
        {"subject": "Re: DevOps training", "body": "Hi Asha, the confirmed mode is online."},
    ))

    assert result["success"] is True
    assert delivered[0]["to"] == "asha@example.com"
    assert database["trainer_question_queries"].inserted[0]["status"] == "answer_sent"
    assert database["shortlists"].updated == []
    assert database["shortlists"].documents[0] == before


def test_common_question_is_answered_from_requirement_without_ai():
    answer = inbox._verified_requirement_question_answer(
        "Is this training online and what is the location?",
        {"technology_needed": "DevOps", "mode": "Online", "location": "Remote"},
        "Asha",
    )

    assert answer is not None
    assert "Training mode: Online" in answer["body"]
    assert "Training location: Remote" in answer["body"]


def test_partial_requirement_facts_do_not_create_an_incomplete_answer():
    answer = inbox._verified_requirement_question_answer(
        "What are the training date and timing?",
        {"technology_needed": "DevOps", "training_dates": "15-19 September 2026"},
        "Asha",
    )

    assert answer is None


def test_unknown_answer_is_automatically_sent_to_client(monkeypatch):
    database = _Database()
    delivered = []
    _patch_delivery(monkeypatch, delivered)

    result = asyncio.run(inbox._handle_trainer_general_question(
        database,
        {
            "email_id": "IN-002",
            "requirement_id": "REQ-001",
            "trainer_id": "TR-001",
            "from_email": "asha@example.com",
            "subject": "Re: DevOps training",
            "body": "Will recordings be available?",
        },
        {"subject": "Re: DevOps training", "body": "We are checking whether recordings will be available."},
    ))

    assert result["success"] is True
    assert result["asked_client"] is True
    assert delivered[0]["to"] == "client@example.com"
    assert "Will recordings be available?" in delivered[0]["body"]
    assert database["trainer_question_queries"].inserted[0]["status"] == "client_asked"
    assert database["shortlists"].updated == []


def test_client_answer_is_relayed_to_the_original_trainer(monkeypatch):
    pending = {
        "query_id": "TQ-001",
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "trainer_name": "Asha",
        "trainer_email": "asha@example.com",
        "client_email": "client@example.com",
        "trainer_question": "Will recordings be available?",
        "clarification_subject": "Clarification Required [TQ-001] - DevOps",
        "status": "client_asked",
    }
    database = _Database(pending)
    delivered = []
    _patch_delivery(monkeypatch, delivered)

    result = asyncio.run(inbox._relay_client_question_answer(database, {
        "from_email": "client@example.com",
        "subject": "Re: Clarification Required [TQ-001] - DevOps",
        "body": "Yes, recordings will be shared after each session.",
    }))

    assert result["success"] is True
    assert delivered[0]["to"] == "asha@example.com"
    assert "recordings will be shared" in delivered[0]["body"]
    update = database["trainer_question_queries"].updated[0][1]["$set"]
    assert update["status"] == "trainer_answer_sent"
    assert database["shortlists"].updated == []


def test_same_inbound_message_is_not_sent_twice(monkeypatch):
    database = _Database({
        "query_id": "TQ-OLD",
        "source_message_id": "IN-003",
        "status": "answer_sent",
    })

    async def should_not_send(**kwargs):
        raise AssertionError("A duplicate inbound message must not send another email")

    monkeypatch.setattr(inbox, "send_email_async", should_not_send)
    result = asyncio.run(inbox._handle_trainer_general_question(
        database,
        {
            "email_id": "IN-003",
            "requirement_id": "REQ-001",
            "trainer_id": "TR-001",
            "body": "Is the training online?",
        },
        {"body": "The training is online."},
    ))

    assert result["skipped"] is True
    assert result["reason"] == "question_already_processing_or_processed"


def test_concurrent_workers_send_only_one_trainer_answer(monkeypatch):
    database = _Database()
    delivered = []
    _patch_delivery(monkeypatch, delivered)
    email = {
        "email_id": "IN-CONCURRENT",
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "from_email": "asha@example.com",
        "subject": "Re: DevOps training",
        "body": "Is this training online?",
    }
    reply = {"subject": "Re: DevOps training", "body": "The confirmed training mode is online."}

    async def run_both():
        return await asyncio.gather(
            inbox._handle_trainer_general_question(database, email, reply),
            inbox._handle_trainer_general_question(database, email, reply),
        )

    results = asyncio.run(run_both())

    assert len(delivered) == 1
    assert sum(bool(result.get("skipped")) for result in results) == 1
    assert database["trainer_question_queries"].inserted[0]["status"] == "answer_sent"


def test_missing_message_id_uses_stable_fingerprint():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "from_email": "asha@example.com",
        "subject": "Re: DevOps training",
        "body": "Is this training online?",
    }

    first = inbox._question_source_id(email)
    second = inbox._question_source_id(dict(email))

    assert first.startswith("sha256:")
    assert first == second


def test_mail1_trainer_question_is_detected_before_pipeline_progression():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "source_outbound_mail_type": "mail1",
    }

    assert inbox._is_linked_trainer_question(
        email,
        "Re: DevOps training",
        "Can you please confirm whether the client will provide the lab setup?",
    ) is True


def test_mail1_toc_question_is_not_treated_as_client_toc_request():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "source_outbound_mail_type": "mail1",
    }

    assert inbox._is_linked_trainer_question(
        email,
        "Re: DevOps training",
        "Could you share the approved ToC for this training?",
    ) is True


def test_normal_trainer_acceptance_does_not_enter_question_side_flow():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "source_outbound_mail_type": "mail1",
    }

    assert inbox._is_linked_trainer_question(
        email,
        "Re: DevOps training",
        "I can take this training and I am available next week.",
    ) is False


def test_unlinked_client_toc_question_does_not_enter_trainer_side_flow():
    assert inbox._is_linked_trainer_question(
        {},
        "ToC required",
        "Can you share a five-day DevOps ToC?",
    ) is False


def test_mail1_profile_reply_is_recognized_as_linked_trainer_thread():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "source_outbound_mail_type": "mail1",
        "attachments": [{"filename": "updated-profile.pdf"}],
    }

    assert inbox._is_linked_trainer_thread(email) is True


def test_mail2_profile_reply_is_recognized_as_linked_trainer_thread():
    email = {
        "requirement_id": "REQ-001",
        "trainer_id": "TR-001",
        "source_outbound_mail_type": "mail2_followup",
        "attachments": [{"filename": "updated-profile.pdf"}],
    }

    assert inbox._is_linked_trainer_thread(email) is True


def test_client_toc_request_is_not_a_linked_trainer_thread():
    assert inbox._is_linked_trainer_thread({
        "requirement_id": "REQ-001",
        "source_outbound_mail_type": "client_auto_reply",
    }) is False


def test_client_handoff_retry_uses_the_email_provider_retry_time():
    now = datetime(2026, 9, 4, 12, 0, 0)

    retry_after = inbox._client_handoff_retry_after({
        "detail": {
            "retry_after": "2026-09-04T12:07:00Z",
        },
    }, now)

    assert retry_after == datetime(2026, 9, 4, 12, 7, 0)
    assert inbox._client_handoff_retry_pending({"success": False, "retry_pending": True}) is True
    assert inbox._client_handoff_retry_pending({"success": False, "reason": "invalid_slot_text"}) is False
