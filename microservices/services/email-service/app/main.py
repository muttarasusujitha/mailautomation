from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from shared.database.service import init_db as connect_service_db, shutdown_db
from app.routes import (
    send,
    inbox,
    templates,
    gmail,
    emails,
    email_open,
    inbox_actions,
    client_conversations,
    scheduler_config,
    business_excel,
    client_updates,
)

settings = get_settings()
logger = logging.getLogger(__name__)


async def _create_index(db, collection: str, keys, **kwargs) -> None:
    try:
        await db[collection].create_index(keys, background=True, **kwargs)
    except Exception as exc:
        logger.warning("Skipping index for %s %s: %s", collection, keys, exc)


async def _ensure_indexes(db) -> None:
    indexes = [
        ("client_emails", [("email_id", 1)], {}),
        ("client_emails", [("status", 1), ("received_at", -1), ("created_at", -1)], {}),
        ("client_emails", [("requirement_id", 1), ("updated_at", -1)], {}),
        ("client_emails", [("from_email", 1), ("created_at", -1)], {}),
        ("client_emails", [("gmail_message_id", 1)], {"sparse": True}),
        ("client_emails", [("latest_gmail_message_id", 1)], {"sparse": True}),
        ("client_emails", [("source_outbound_email_id", 1)], {"sparse": True}),
        ("client_emails", [("processed", 1), ("status", 1), ("created_at", 1)], {}),
        ("email_logs", [("email_id", 1)], {}),
        ("email_logs", [("requirement_id", 1), ("trainer_id", 1), ("mail_type", 1), ("created_at", -1)], {}),
        ("email_logs", [("direction", 1), ("status", 1), ("mail_type", 1), ("created_at", -1)], {}),
        ("email_logs", [("gmail_message_id", 1)], {"sparse": True}),
        ("email_logs", [("message_id_header", 1)], {"sparse": True}),
        ("email_logs", [("idempotency_key", 1)], {"unique": True, "sparse": True}),
        ("email_logs", [("recipient", 1), ("created_at", -1)], {}),
        ("email_logs", [("to_email", 1), ("created_at", -1)], {}),
        ("requirements", [("requirement_id", 1)], {}),
        ("requirements", [("metadata.source_email_id", 1)], {"sparse": True}),
        ("requirements", [("client_email", 1), ("status", 1), ("created_at", -1)], {}),
        ("trainer_question_queries", [("query_id", 1)], {"unique": True}),
        ("trainer_question_queries", [("source_message_id", 1)], {"unique": True, "sparse": True}),
        ("trainer_question_queries", [("client_email", 1), ("status", 1), ("created_at", -1)], {}),
        ("trainer_question_queries", [("requirement_id", 1), ("trainer_id", 1), ("created_at", -1)], {}),
    ]
    for collection, keys, options in indexes:
        await _create_index(db, collection, keys, **options)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await connect_service_db(settings)
    await _ensure_indexes(db)
    yield
    await shutdown_db()


app = FastAPI(
    title="Email Service",
    description="Gmail SMTP/IMAP/OAuth, inbox, email pipeline, client conversations",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core send + inbox poll
app.include_router(send.router,                 prefix="/api/v1/email",             tags=["email-send"])
app.include_router(inbox.router,                prefix="/api/v1/email/inbox",       tags=["email-inbox"])
app.include_router(inbox_actions.router,        prefix="/api/v1/inbox",             tags=["inbox-actions"])

# Gmail OAuth + sync
app.include_router(gmail.router,                prefix="/api/v1/gmail",             tags=["gmail"])

# Email log management
app.include_router(emails.router,               prefix="/api/v1/emails",            tags=["emails"])

# Templates
app.include_router(templates.router,            prefix="/api/v1/email/templates",   tags=["email-templates"])

# Tracking pixel
app.include_router(email_open.router,           prefix="/api/v1/email-open",        tags=["email-tracking"])

# Client conversations (AI reply inbox)
app.include_router(client_conversations.router, prefix="/api/v1/client-conversations", tags=["client-conversations"])

# Scheduler configuration
app.include_router(scheduler_config.router,     prefix="/api/v1/scheduler",         tags=["scheduler-config"])

# Business Excel
app.include_router(business_excel.router,       prefix="/api/v1/business-excel",    tags=["business-excel"])

# Client updates
app.include_router(client_updates.router,       prefix="/api/v1/client-updates",    tags=["client-updates"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}
