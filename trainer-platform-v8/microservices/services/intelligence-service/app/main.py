from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import (
    categorisation,
    client_intelligence,
    contact_finder,
    free_search,
    client_leads,
    trainer_profile_leads,
    ai,
    assistant,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Intelligence Service",
    description="AI categorisation, client intelligence, contact finder, leads, assistant chat",
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

app.include_router(categorisation.router,       prefix="/api/v1/intelligence",              tags=["categorisation"])
app.include_router(client_intelligence.router,  prefix="/api/v1/intelligence",              tags=["client-intelligence"])
app.include_router(contact_finder.router,       prefix="/api/v1/contact-finder",            tags=["contact-finder"])
app.include_router(free_search.router,          prefix="/api/v1/intelligence/trainers",     tags=["free-search"])
app.include_router(client_leads.router,         prefix="/api/v1/client-leads",              tags=["client-leads"])
app.include_router(trainer_profile_leads.router,prefix="/api/v1/trainer-profile-leads",     tags=["trainer-profile-leads"])
app.include_router(ai.router,                   prefix="/api/v1/ai",                        tags=["ai"])
app.include_router(assistant.router,            prefix="/api/v1/assistant",                 tags=["assistant"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}
