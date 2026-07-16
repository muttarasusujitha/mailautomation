from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
