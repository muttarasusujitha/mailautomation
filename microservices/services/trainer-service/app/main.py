from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from shared.database.service import init_db as connect_service_db, shutdown_db
from app.routes import (
    trainers, matching, slots, toc,
    resume_data, resume_uploads, shortlists,
    interview_reminders, purchase_orders, invoices, finance_approvals,
    toc_extended, trainer_automation, voice_ai, profile_enhancements,
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
        ("trainers", [("trainer_id", 1)], {}),
        ("trainers", [("email", 1)], {"sparse": True}),
        ("trainers", [("domain", 1), ("status", 1)], {}),
        ("trainers", [("category", 1), ("status", 1)], {}),
        ("trainers", [("created_at", -1)], {}),
        ("requirements", [("requirement_id", 1)], {}),
        ("requirements", [("technology_needed", 1), ("status", 1)], {}),
        ("requirements", [("domain", 1), ("status", 1)], {}),
        ("shortlists", [("requirement_id", 1)], {}),
        ("shortlists", [("top_trainers.trainer_id", 1)], {}),
        ("shortlists", [("updated_at", -1)], {}),
        ("email_logs", [("trainer_id", 1), ("created_at", -1)], {}),
        ("email_logs", [("requirement_id", 1), ("trainer_id", 1), ("mail_type", 1), ("created_at", -1)], {}),
        ("email_logs", [("direction", 1), ("status", 1), ("mail_type", 1), ("created_at", -1)], {}),
        ("trainer_slots", [("trainer_id", 1), ("created_at", -1)], {}),
        ("resume_uploads", [("trainer_id", 1), ("created_at", -1)], {}),
        ("profile_enhancements", [("requirement_id", 1), ("trainer_id", 1)], {"unique": True}),
        ("interview_meeting_notes", [("schedule_key", 1), ("created_at", -1)], {}),
        ("purchase_orders", [("requirement_id", 1), ("created_at", -1)], {}),
        ("invoices", [("requirement_id", 1), ("created_at", -1)], {}),
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
    title="Trainer Service",
    description="Trainer CRUD, pipeline, resume, shortlists, slots, TOC, POs, invoices",
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

# Core trainer CRUD + matching
app.include_router(trainers.router,           prefix="/api/v1/trainers",             tags=["trainers"])
app.include_router(matching.router,           prefix="/api/v1/trainers",             tags=["matching"])
app.include_router(trainer_automation.router, prefix="/api/v1/trainers",             tags=["trainer-automation"])

# Resume pipeline
app.include_router(resume_uploads.router,     prefix="/api/v1/resume-uploads",       tags=["resume-uploads"])
app.include_router(resume_data.router,        prefix="/api/v1/resume-data",          tags=["resume-data"])
app.include_router(profile_enhancements.router, prefix="/api/v1/profile-enhancements", tags=["profile-enhancements"])

# Slots + shortlists
app.include_router(slots.router,              prefix="/api/v1/trainer-slots",        tags=["slots"])
app.include_router(shortlists.router,         prefix="/api/v1/shortlists",           tags=["shortlists"])

# Interview reminders
app.include_router(interview_reminders.router, prefix="/api/v1/interview-reminders", tags=["interview-reminders"])
app.include_router(interview_reminders.schedules_router, prefix="/api/v1/interview-schedules", tags=["interview-schedules"])

# TOC
app.include_router(toc.router,                prefix="/api/v1/toc",                  tags=["toc"])
app.include_router(toc_extended.router,       prefix="/api/v1/toc",                  tags=["toc-extended"])

# Purchase orders + invoices
app.include_router(purchase_orders.router,    prefix="/api/v1/purchase-orders",      tags=["purchase-orders"])
app.include_router(invoices.router,           prefix="/api/v1/invoices",             tags=["invoices"])
app.include_router(finance_approvals.router,  prefix="/api/v1/finance",              tags=["finance"])

# Voice AI recruiter assistant
app.include_router(voice_ai.router,           prefix="/api/v1/voice-ai",             tags=["voice-ai"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}
