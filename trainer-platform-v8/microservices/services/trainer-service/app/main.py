from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import (
    trainers, matching, slots, toc,
    resume_data, resume_uploads, shortlists,
    interview_reminders, purchase_orders, invoices,
    toc_extended, trainer_automation,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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

# Slots + shortlists
app.include_router(slots.router,              prefix="/api/v1/trainer-slots",        tags=["slots"])
app.include_router(shortlists.router,         prefix="/api/v1/shortlists",           tags=["shortlists"])

# Interview reminders
app.include_router(interview_reminders.router, prefix="/api/v1/interview-reminders", tags=["interview-reminders"])

# TOC
app.include_router(toc.router,                prefix="/api/v1/toc",                  tags=["toc"])
app.include_router(toc_extended.router,       prefix="/api/v1/toc",                  tags=["toc-extended"])

# Purchase orders + invoices
app.include_router(purchase_orders.router,    prefix="/api/v1/purchase-orders",      tags=["purchase-orders"])
app.include_router(invoices.router,           prefix="/api/v1/invoices",             tags=["invoices"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}
